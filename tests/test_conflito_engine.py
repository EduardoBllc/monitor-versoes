"""Testes do engine do conflito de 3 vias, com `Deps` sobre `FakeGit`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from motor.adapters.git.fake import FakeGit
from motor.adapters.sugestao.fake import FakeProvedorSugestao
from motor.domain.conflito import (
    LadosDoBloco,
    PedidoAoProvedor,
    PropostaDeBloco,
    TipoArquivo,
)
from motor.engine.conflito import (
    ArquivoDoConflito,
    ler_arquivo,
    ler_conflito,
    propor_resolucao,
    reabrir_arquivo,
    resolver_arquivo,
)
from motor.errors import (
    BackendIndisponivel,
    ErroDeEntrada,
    NaoEncontrado,
    RespostaInvalida,
    VersaoDesatualizada,
)
from motor.ports import ProvedorSugestao
from tests.conflito_falso import (
    APAGADO,
    CHAMADO,
    COM_MARCADOR,
    CONTEUDO,
    DOIS,
    ESTAGIOS,
    ESTAGIOS_DOIS,
    MENSAGEM,
    VERSAO,
    deps_em_conflito,
    deps_falsas,
    git_falso,
)

LINHAS_DO_MARCADOR = "2, 4, 6"
RESOLVIDO = "a\nc\n"
MUDOU_FORA = "editado fora da web\n"


def test_ler_conflito_lista_arquivos_e_contexto():
    conflito = ler_conflito(deps_em_conflito(), VERSAO)

    assert (conflito.commit, conflito.mensagem, conflito.chamado) == (
        "a0",
        MENSAGEM,
        CHAMADO,
    )
    assert sorted(conflito.arquivos, key=lambda a: a.caminho) == [
        ArquivoDoConflito(APAGADO, TipoArquivo.MODIFICADO_APAGADO, resolvido=False),
        ArquivoDoConflito(CONTEUDO, TipoArquivo.CONTEUDO, resolvido=False),
    ]


@pytest.mark.parametrize("caminho", ["outro.txt", "../a.txt", "/etc/passwd"])
def test_caminho_fora_do_pick_e_recusado(caminho: str):
    deps = deps_em_conflito()

    with pytest.raises(NaoEncontrado):
        ler_arquivo(deps, VERSAO, caminho)
    with pytest.raises(NaoEncontrado):
        resolver_arquivo(deps, VERSAO, caminho, RESOLVIDO, "")
    with pytest.raises(NaoEncontrado):
        reabrir_arquivo(deps, VERSAO, caminho)


def test_sem_pick_pendente():
    with pytest.raises(NaoEncontrado):
        ler_conflito(deps_falsas(git_falso()), VERSAO)


def test_resolver_recusa_disco_mudado():
    deps = deps_em_conflito()
    lido = ler_arquivo(deps, VERSAO, CONTEUDO)
    assert isinstance(deps.git, FakeGit)
    # Edição fora da web num arquivo ainda pendente: muda só o disco do fake.
    deps.git._arquivos_pick[CONTEUDO] = replace(ESTAGIOS[CONTEUDO], disco=MUDOU_FORA)

    with pytest.raises(VersaoDesatualizada):
        resolver_arquivo(deps, VERSAO, CONTEUDO, RESOLVIDO, lido.versao_disco)
    assert ler_arquivo(deps, VERSAO, CONTEUDO).disco == MUDOU_FORA
    assert deps.git.arquivos_do_pick()[CONTEUDO] is False


def test_resolver_recusa_marcador():
    deps = deps_em_conflito()
    lido = ler_arquivo(deps, VERSAO, CONTEUDO)

    with pytest.raises(ErroDeEntrada, match=LINHAS_DO_MARCADOR):
        resolver_arquivo(deps, VERSAO, CONTEUDO, COM_MARCADOR, lido.versao_disco)


def test_resolver_e_reabrir():
    deps = deps_em_conflito()

    def resolvido() -> bool:
        return {a.caminho: a.resolvido for a in ler_conflito(deps, VERSAO).arquivos}[
            CONTEUDO
        ]

    with pytest.raises(ErroDeEntrada):
        reabrir_arquivo(deps, VERSAO, CONTEUDO)

    lido = ler_arquivo(deps, VERSAO, CONTEUDO)
    resolver_arquivo(deps, VERSAO, CONTEUDO, RESOLVIDO, lido.versao_disco)
    assert resolvido()
    assert ler_arquivo(deps, VERSAO, CONTEUDO).disco == RESOLVIDO

    reabrir_arquivo(deps, VERSAO, CONTEUDO)
    assert not resolvido()
    assert ler_arquivo(deps, VERSAO, CONTEUDO).disco == COM_MARCADOR


def _levanta(erro: Exception) -> Callable[[], ProvedorSugestao | None]:
    def fonte() -> ProvedorSugestao | None:
        raise erro

    return fonte


@pytest.mark.parametrize(
    ("fonte", "esperado"),
    [
        (FakeProvedorSugestao, True),
        (lambda: None, False),
        (_levanta(ErroDeEntrada("provedor não instalado")), False),
    ],
)
def test_disponibilidade_da_sugestao_no_conflito_aberto(fonte, esperado: bool):
    deps = replace(deps_em_conflito(), sugestao=fonte)

    assert ler_conflito(deps, VERSAO).sugestao_disponivel is esperado


def _pedir(deps, ordens: list[int], caminho: str = DOIS):
    disco = ler_arquivo(deps, VERSAO, caminho).versao_disco
    return propor_resolucao(deps, VERSAO, caminho, disco, ordens)


def test_pedido_leva_so_os_blocos_pedidos():
    provedor = FakeProvedorSugestao()
    deps = deps_em_conflito(estagios=ESTAGIOS_DOIS, provedor=provedor)

    _pedir(deps, [1])

    assert provedor.pedidos == [
        PedidoAoProvedor(
            DOIS, MENSAGEM, CHAMADO, [LadosDoBloco(1, "O2\n", "A2\n", "B2\n")]
        )
    ]
    for ausente in ("meio mesclado", "topo", "A1"):
        assert ausente not in repr(provedor.pedidos)

    _pedir(deps, [0, 1])

    assert [b.ordem for b in provedor.pedidos[1].blocos] == [0, 1]
    assert provedor.pedidos[1].blocos[0].base is None


def test_mensagem_sem_tarefa_nao_leva_identificador():
    provedor = FakeProvedorSugestao()
    deps = deps_em_conflito(
        mensagem="corrige logs", estagios=ESTAGIOS_DOIS, provedor=provedor
    )

    _pedir(deps, [0])

    assert provedor.pedidos[0].chamado is None


def test_pedir_nao_altera_disco_nem_estagios():
    deps = deps_em_conflito(estagios=ESTAGIOS_DOIS, provedor=FakeProvedorSugestao())
    antes = (deps.git.estagios(DOIS), deps.git.arquivos_do_pick())

    _pedir(deps, [0, 1])

    assert (deps.git.estagios(DOIS), deps.git.arquivos_do_pick()) == antes


def _resolvido(deps):
    disco = ler_arquivo(deps, VERSAO, DOIS).versao_disco
    resolver_arquivo(deps, VERSAO, DOIS, "ok\n", disco)


@pytest.mark.parametrize(
    ("caminho", "versao_disco", "ordens", "resolvido", "com_provedor", "erro"),
    [
        (DOIS, "velha", [0], False, True, VersaoDesatualizada),
        (DOIS, None, [2], False, True, ErroDeEntrada),
        (DOIS, None, [], False, True, ErroDeEntrada),
        (DOIS, None, [0, 0], False, True, ErroDeEntrada),
        (DOIS, None, [-1], False, True, ErroDeEntrada),
        (APAGADO, None, [0], False, True, ErroDeEntrada),
        (DOIS, None, [0], True, True, ErroDeEntrada),
        (DOIS, None, [0], False, False, ErroDeEntrada),
        ("fora.txt", "", [0], False, True, NaoEncontrado),
    ],
)
def test_pedido_invalido(caminho, versao_disco, ordens, resolvido, com_provedor, erro):
    provedor = FakeProvedorSugestao()
    deps = deps_em_conflito(
        estagios=ESTAGIOS_DOIS, provedor=provedor if com_provedor else None
    )
    if resolvido:
        _resolvido(deps)
    if versao_disco is None:
        versao_disco = ler_arquivo(deps, VERSAO, caminho).versao_disco

    with pytest.raises(erro):
        propor_resolucao(deps, VERSAO, caminho, versao_disco, ordens)
    assert provedor.pedidos == []


def _omite_um(p: PedidoAoProvedor) -> list[PropostaDeBloco]:
    return [PropostaDeBloco(b.ordem, "x\n", "porque") for b in p.blocos[:1]]


def _sem_justificativa(p: PedidoAoProvedor) -> list[PropostaDeBloco]:
    return [PropostaDeBloco(b.ordem, "x\n", "  ") for b in p.blocos]


def _ordem_nao_pedida(p: PedidoAoProvedor) -> list[PropostaDeBloco]:
    return [PropostaDeBloco(b.ordem + 5, "x\n", "porque") for b in p.blocos]


@pytest.mark.parametrize(
    "responder", [_omite_um, _sem_justificativa, _ordem_nao_pedida]
)
def test_resposta_fora_do_contrato_e_resposta_invalida(responder):
    deps = deps_em_conflito(
        estagios=ESTAGIOS_DOIS, provedor=FakeProvedorSugestao(responder=responder)
    )

    with pytest.raises(RespostaInvalida):
        _pedir(deps, [0, 1])


def test_conteudo_vazio_e_proposta_valida():
    deps = deps_em_conflito(
        estagios=ESTAGIOS_DOIS,
        provedor=FakeProvedorSugestao(
            responder=lambda p: [
                PropostaDeBloco(b.ordem, "", "apaga") for b in p.blocos
            ]
        ),
    )

    assert [p.conteudo for p in _pedir(deps, [1, 0])] == ["", ""]


def test_erro_do_provedor_chega_com_o_tipo():
    def falha(_: PedidoAoProvedor) -> list[PropostaDeBloco]:
        raise BackendIndisponivel("fora do ar")

    deps = deps_em_conflito(
        estagios=ESTAGIOS_DOIS, provedor=FakeProvedorSugestao(responder=falha)
    )

    with pytest.raises(BackendIndisponivel):
        _pedir(deps, [0])
