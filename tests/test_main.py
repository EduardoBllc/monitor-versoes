"""Testes do composition root.

Os testes de ponta a ponta chamam `main()` de verdade e trocam so as tres
bordas de IO (git, sessao do banco, adapter de estado). Um teste que so
importa helpers nao prova nada sobre a entrada: foi assim que um
`Deps(lock_dir=...)` invalido sobreviveu quatro tasks.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import json
import os
import pkgutil
import subprocess
import sys
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any

import dotenv
import pytest

import motor.__main__ as cli
import motor.montagem as montagem
import motor.novidades as modulo_novidades
from motor.__main__ import (
    _build_parser,
    imprimir_atualizacao,
    imprimir_status,
    main,
)
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.cli_instalacao import COMANDO_ATUALIZAR_MOTOR
from motor.config import SECAO_REPOS
from motor.diagnostico import Peca
from motor.domain.referencia import Referencia
from motor.domain.types import (
    Atribuicao,
    CommitRef,
    RepoInfo,
    VersaoInfo,
    VersionStatus,
)
from motor.engine.atualizar import AtualizarResult, AtualizarStatus
from motor.engine.deps import Deps
from motor.errors import MotorError
from motor.inscricoes import Inscricao
from motor.instalacao import PACOTE_MOTOR
from motor.novidades import Cache, Novidade
from motor.plugins import carregar_plugin
from tests.config_repos import rotulo_secao, secao_repo
from tests.fontes_falsas import REFERENCIA_CH, FonteFixa

D = datetime.datetime(2026, 1, 1)


# -- parser -------------------------------------------------------------------


#: Saída do argparse para argumento inválido.
ARGPARSE_USO_INVALIDO = 2


def test_task_source_default_e_config():
    args = _build_parser().parse_args(["criar", "1.0.0", "--repo", "."])
    assert args.fonte_flag == "config"


@pytest.mark.parametrize(
    ("argv", "arquivo", "ambiente"),
    [
        (["tui"], ".env", "production"),
        (["--env", "development", "tui"], ".env.development", "development"),
    ],
)
def test_tui_despacha_sem_abrir_banco_no_cli(monkeypatch, argv, arquivo, ambiente):
    chamadas: list[str] = []
    ambientes: list[str] = []
    monkeypatch.setattr(
        cli,
        "load_dotenv",
        lambda caminho, **opcoes: ambientes.append(os.path.basename(caminho)),
    )
    monkeypatch.setattr(cli, "_iniciar_tui", lambda: chamadas.append("tui"))
    monkeypatch.setattr(
        cli,
        "abrir_sessao",
        lambda: pytest.fail("o CLI nao deve abrir banco antes da TUI"),
    )

    main(argv)

    assert chamadas == ["tui"]
    assert ambientes == [arquivo]


def _versao_do_pyproject() -> str:
    raiz = Path(__file__).resolve().parent.parent
    with (raiz / "pyproject.toml").open("rb") as f:
        return str(tomllib.load(f)["project"]["version"])


def test_version_ignora_config_central_invalida(tmp_path, monkeypatch, capsys):
    (tmp_path / "monitor-versoes").mkdir()
    (tmp_path / "monitor-versoes" / "config.toml").write_text("[ambiente")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    with pytest.raises(SystemExit) as saida:
        main(["--version"])

    assert saida.value.code == 0
    assert (
        capsys.readouterr().out.strip() == f"monitor-versoes {_versao_do_pyproject()}"
    )


def test_help_descreve_as_acoes_da_tui():
    ajuda = " ".join(_build_parser().format_help().split())

    assert "consulta, verificacao e atualizacao" in ajuda


@pytest.mark.parametrize(
    ("argv", "arquivo"),
    [
        (["--help"], ".env"),
        (["--env", "development", "--help"], ".env.development"),
        (["--env", "development", "diagnostico", "--help"], ".env.development"),
    ],
)
def test_main_carrega_o_ambiente_escolhido_antes_do_parser(monkeypatch, argv, arquivo):
    chamadas = []

    def carregar(caminho=None, **opcoes):
        nome = os.path.basename(caminho) if caminho else None
        chamadas.append((nome, opcoes))

    monkeypatch.setattr(cli, "load_dotenv", carregar)

    with pytest.raises(SystemExit) as saida:
        main(argv)

    assert saida.value.code == 0
    assert chamadas == [(arquivo, {"override": True})]


def test_fonte_de_tasks_disponivel_em_todos_os_subcomandos():
    # --task-source/--lista vivem no parser pai 'comum': se ficassem so no
    # 'criar', os outros comandos leriam args.lista_manual inexistente —
    # AttributeError com traceback, nao mensagem.
    for comando in ("verificar", "criar", "atualizar", "reconstruir-estado"):
        args = _build_parser().parse_args(
            [
                comando,
                "13.34.0",
                "--repo",
                "webapp",
                "--task-source",
                "manual",
                "--lista",
                "x.txt",
            ]
        )
        assert (args.fonte_flag, args.lista_manual) == ("manual", "x.txt")


def test_reconstruir_estado_esta_no_parser():
    subparsers = _build_parser()._subparsers
    assert subparsers is not None
    acoes = subparsers._group_actions[0].choices
    assert acoes is not None
    assert "reconstruir-estado" in acoes
    assert "reconstruir-lock" not in acoes


def test_comando_desconhecido_sai_com_erro():
    with pytest.raises(SystemExit) as saida:
        main(["inexistente", "13.34.0", "--repo", "/tmp"])
    assert saida.value.code != 0


def test_subcomando_repo_nao_existe_mais():
    with pytest.raises(SystemExit) as saida:
        main(["repo", "adicionar", "x"])
    assert saida.value.code == ARGPARSE_USO_INVALIDO


# -- impressao ----------------------------------------------------------------


def test_imprimir_status_mostra_as_ambiguas(capsys):
    # tasks_ambiguas derruba o verde; sem imprimi-las o operador ve
    # "verde: False" com todas as secoes vazias e nenhuma explicacao.
    imprimir_status(
        VersionStatus(estado_integro=True, tasks_ambiguas=["123456"]),
        lambda: REFERENCIA_CH,
    )

    saida = capsys.readouterr().out
    assert "123456" in saida
    assert "mais de uma versao" in saida


def test_imprimir_status_aponta_sem_entrega_no_banco(capsys):
    imprimir_status(
        VersionStatus(estado_integro=True, tasks_sem_commits=["123456"]),
        lambda: REFERENCIA_CH,
    )

    saida = capsys.readouterr().out
    assert "sem_entrega" in saida
    assert "lock" not in saida  # sem_entrega vive no banco, nao num lock


def test_imprimir_status_de_versao_liberada_marca_o_snapshot(capsys):
    """Versao liberada imprime o snapshot do banco e sai
    (docs/decisoes/010-travas-publicada-e-liberada.md). Sem cabecalho
    e sem chamados a saida sai byte-a-byte igual a de uma versao verde em
    construcao — e um snapshot vazio ainda diria "verde: True", porque all([])
    e True. Esta e a unica superficie de leitura do que so o banco registra.
    """
    imprimir_status(
        VersionStatus(
            verde=True,
            estado_integro=True,
            liberada_em=datetime.datetime(2026, 8, 7, 14, 22),
            chamados=["255514", "256308"],
        ),
        lambda: REFERENCIA_CH,
    )

    saida = capsys.readouterr().out
    assert "liberada em 2026-08-07 14:22" in saida
    assert "snapshot congelado, nao recalculado" in saida
    assert "255514, 256308" in saida
    # nao imprime secao que nao foi recalculada: seria mentira dizer "faltantes"
    assert "faltantes" not in saida


def _referencia_ch() -> Referencia:
    return REFERENCIA_CH


def test_imprimir_atualizacao_mostra_as_secoes_vermelhas_do_verificar(capsys):
    """O lote e empurrado mesmo sem verde (todo commit sai de status.faltantes
    depois de filtrar_excluidos, e travar em tasks_sem_commits emperraria o
    fluxo toda vez que um chamado nao tem codigo), mas tasks_ambiguas,
    tasks_sem_commits e commits_sumidos eram calculados e descartados: o run
    imprimia "concluido" e nada mais. commits_sumidos e o pior — historico
    reescrito debaixo de um commit ja aplicado, e o verificar ja sobrescreveu a
    linha de estado que guardava a evidencia.
    """
    imprimir_atualizacao(
        AtualizarResult(
            status=AtualizarStatus.DONE,
            status_versao=VersionStatus(
                estado_integro=False,
                tasks_ambiguas=["123456"],
                tasks_sem_commits=["999111"],
                commits_sumidos=["deadbeefcafe"],
            ),
        ),
        _referencia_ch,
    )

    saida = capsys.readouterr().out
    assert "123456" in saida and "mais de uma versao" in saida
    assert "999111" in saida and "sem_entrega" in saida
    assert "deadbeef" in saida and "commits sumidos" in saida
    # o push aconteceu: o defeito nunca foi o push, era o operador nao saber
    assert "concluido" in saida


def test_imprimir_atualizacao_avisa_reaproveitamento(capsys):
    verificado_em = datetime.datetime(2026, 1, 2, 13, 45, tzinfo=datetime.UTC)
    imprimir_atualizacao(
        AtualizarResult(status=AtualizarStatus.DONE, reaproveitada_de=verificado_em),
        _referencia_ch,
    )
    hora = verificado_em.astimezone().strftime("%H:%M")
    assert f"reaproveitando a verificacao das {hora}" in capsys.readouterr().out

    imprimir_atualizacao(AtualizarResult(status=AtualizarStatus.DONE), _referencia_ch)
    assert "reaproveitando" not in capsys.readouterr().out


def _referencia_proibida() -> Referencia:
    raise AssertionError("bloqueio sem culpado nao pode exigir padrao de referencia")


@pytest.mark.parametrize(
    ("culpados", "referencia", "linha"),
    [
        (
            ["257056"],
            _referencia_ch,
            "BLOQUEADO em f5d02b45, arquivos: ['integracoes/tests.py'], "
            "depende de ch257056, fora desta versao",
        ),
        (
            [],
            _referencia_proibida,
            "BLOQUEADO em f5d02b45, arquivos: ['integracoes/tests.py']",
        ),
    ],
    ids=["com_culpado", "sem_culpado"],
)
def test_imprimir_atualizacao_bloqueada_nomeia_os_culpados(
    capsys, culpados, referencia, linha
):
    imprimir_atualizacao(
        AtualizarResult(
            status=AtualizarStatus.BLOCKED,
            blocked_commit="f5d02b45aaaa",
            arquivos_conflito=["integracoes/tests.py"],
            culpados=culpados,
        ),
        referencia,
    )

    assert linha in capsys.readouterr().out.splitlines()


# -- main() ponta a ponta -----------------------------------------------------


def _central() -> str:
    return os.path.join(os.environ["XDG_CONFIG_HOME"], "monitor-versoes", "config.toml")


def _repo_dir(tmp_path, nome: str = "webapp", do_repo: str = "") -> str:
    """Cria o checkout, registra a seção do repo na config central e devolve o nome."""
    caminho = tmp_path / nome
    caminho.mkdir()
    with open(_central(), "a", encoding="utf-8") as f:
        f.write(secao_repo(nome, caminho, do_repo))
    return nome


def _repo_com_padrao(tmp_path) -> str:
    """Repo com `padrao = "ch{id}"`: a lista manual nao propoe referencia."""
    return _repo_dir(tmp_path, do_repo='[referencia]\npadrao = "ch{id}"\n')


def _git() -> FakeGit:
    """m0 e a raiz das versoes; a0 so existe no master (logo, faltante)."""
    git = FakeGit()
    git.add_commit("m0", "", "raiz", D)
    git.add_commit("a0", "m0", "ch123456 alfa", D)
    git.set_branch("master", "a0")
    git.set_branch("origin/master", "a0")
    # 13.33.0 e a base inferida da 13.34.0 (docs/decisoes/009-inferencia-de-base.md)
    for versao in ("13.33.0", "13.34.0"):
        git.set_branch(versao, "m0")
    return git


_COM_CREDENCIAL = "tests.fontes_falsas:FonteComCredencial"
_FIXA = "tests.fontes_falsas:FonteFixa"


def _fonte_central(fonte: str | None, chamados: list[str] | None = None) -> None:
    """Reescreve o topo do `config.toml` central da fixture `bordas` com outra
    fonte, mantendo as seções `[repos.*]` já registradas."""
    with open(_central(), encoding="utf-8") as f:
        atual = f.read()
    indice = atual.find(f"[{SECAO_REPOS}.")
    repos = "" if indice < 0 else atual[indice:]
    conteudo = '[versao]\nesquema = "tests.versionamento:Escalonado"\natribuicao = "composta"\n'
    if fonte is not None:
        conteudo += f'[tarefas]\nfonte = "{fonte}"\n'
        if chamados is not None:
            conteudo += "chamados = [" + ", ".join(f'"{c}"' for c in chamados) + "]\n"
    with open(_central(), "w", encoding="utf-8") as f:
        f.write(conteudo + repos)


@pytest.fixture
def bordas(monkeypatch, tmp_path_factory):
    """Troca as tres bordas de IO da montagem e devolve os doubles.

    Duas delas moram em `motor.montagem` (git e adapter de estado), que e onde o
    Deps e montado; a sessao ainda e aberta pelo `main()`.

    Todo o resto de main() roda de verdade: parse, resolucao do repo, montagem
    de Deps, escolha da fonte de tasks, despacho e impressao.
    """
    tmp_path = tmp_path_factory.mktemp("cfg")
    git = _git()
    estado = FakeEstado(repos={"webapp": RepoInfo(nome="webapp")})
    monkeypatch.setenv("FONTE_FALSA_TOKEN", "certo")
    monkeypatch.setattr(FonteFixa, "recebidos", [])
    monkeypatch.setattr(FonteFixa, "buscadas", [])
    # config global isolada: o teste nao le o ~/.config de quem roda a suite.
    # O repo de teste segue o esquema escalonado (`master`, base em degraus,
    # regra composta da 005): sem isso o padrao `semver`/`main` mudaria o que
    # estes testes verificam.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    global_ = tmp_path / "xdg" / "monitor-versoes" / "config.toml"
    global_.parent.mkdir(parents=True)
    global_.write_text(
        '[versao]\nesquema = "tests.versionamento:Escalonado"\natribuicao = "composta"\n'
        f'[tarefas]\nfonte = "{_COM_CREDENCIAL}"\n'
    )
    monkeypatch.setattr(montagem, "new_git_subprocess", lambda repo, **_: git)
    monkeypatch.setattr(cli, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(montagem, "Estado", lambda sessao: estado)
    return git, estado


def test_verificar_ponta_a_ponta_com_lista_manual(bordas, tmp_path, capsys):
    git, _estado = bordas
    lista = tmp_path / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")

    main(
        [
            "verificar",
            "13.34.0",
            "--repo",
            _repo_com_padrao(tmp_path),
            "--task-source",
            "manual",
            "--lista",
            str(lista),
        ]
    )

    saida = capsys.readouterr().out
    assert "verde:" in saida
    # a0 saiu como faltante: Deps foi montada com o repo canonico e o estado,
    # e o verificar rodou de ponta a ponta em cima deles.
    assert "a0" in saida
    assert git.fetched == ["origin"]


def test_verificar_auditar_exibe_faltantes_de_versao_liberada(bordas, tmp_path, capsys):
    git, estado = bordas
    git.tags["13.34.0"] = True
    estado.registrar_versao(
        "webapp",
        VersaoInfo(
            numero="13.34.0",
            tipo="ajustada",
            base_ref="13.33.0",
            base_commit="m0",
        ),
    )
    estado.marcar_liberadas("webapp", {"13.34.0": D})
    lista = tmp_path / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")

    main(
        [
            "verificar",
            "13.34.0",
            "--repo",
            _repo_com_padrao(tmp_path),
            "--task-source",
            "manual",
            "--lista",
            str(lista),
            "--auditar",
        ]
    )

    saida = capsys.readouterr().out
    assert "auditoria da tag 13.34.0" in saida
    assert "faltantes" in saida and "a0" in saida
    assert estado.atribuicoes("webapp", "13.34.0") == []
    assert git.removed_worktrees == []


def test_fonte_da_config_recebe_o_sistema_do_repo(bordas, tmp_path):
    _fonte_central(_FIXA)

    # sem --task-source: prova que o default do CLI e a fonte da config
    repo = _repo_dir(tmp_path, do_repo="[tarefas]\nsistema = 7\n")
    main(["verificar", "13.34.0", "--repo", repo])

    assert len(FonteFixa.recebidos) == 1
    recebido = FonteFixa.recebidos[0]
    tarefas = recebido["tarefas"]
    assert isinstance(tarefas, dict)
    # 7 vem da seção do repo no config.toml, nao do banco
    assert tarefas["sistema"] == 7
    assert tarefas["fonte"] == _FIXA
    arquivos = recebido["arquivos"]
    assert isinstance(arquivos, tuple)
    assert arquivos[-1] == rotulo_secao(_central(), repo)


def test_verificar_busca_tarefas_pela_fonte_da_config(bordas, tmp_path, capsys):
    _fonte_central(_FIXA, chamados=["123456"])

    main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    saida = capsys.readouterr().out
    # a0 cita ch123456 e so existe no master: a task chegou pela fonte
    assert "a0" in saida and "123456" in saida


def test_fonte_nao_instalada_e_recusada(bordas, tmp_path, caplog):
    _fonte_central("inexistente")

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert saida.value.code == 1
    assert "plugin 'inexistente' nao encontrado" in caplog.text


def test_sem_fonte_a_busca_pede_a_chave(bordas, tmp_path, caplog):
    _fonte_central(None)
    repo = _repo_com_padrao(tmp_path)
    central = _central()

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", repo])

    assert saida.value.code == 1
    # o topo e a seção do repo aparecem, unidos por "e"
    assert (
        f"faltando [tarefas] fonte em {central} e {rotulo_secao(central, repo)}; "
        "ou use --task-source manual --lista <arquivo>"
    ) in caplog.text


def test_atualizar_abort_com_fonte_inexistente(bordas, tmp_path, capsys):
    _fonte_central("inexistente")

    main(["atualizar", "13.34.0", "--repo", _repo_dir(tmp_path), "--abort"])

    assert capsys.readouterr().out == "abortado\n"


def test_reconstruir_sem_fonte_usa_o_padrao_da_config(
    bordas, tmp_path, capsys, monkeypatch
):
    _fonte_central(None)

    def so_sem_tarefas(grupo: str, nome: str) -> type:
        if grupo == montagem.GRUPO_TAREFAS:
            raise AssertionError("o plugin da fonte de tarefas foi carregado")
        return carregar_plugin(grupo, nome)

    monkeypatch.setattr(montagem, "carregar_plugin", so_sem_tarefas)

    main(["reconstruir-estado", "13.34.0", "--repo", _repo_com_padrao(tmp_path)])

    assert "status: DONE" in capsys.readouterr().out


def test_reconstruir_sem_fonte_e_sem_padrao_pede_a_chave(bordas, tmp_path, caplog):
    _fonte_central(None)
    git, _ = bordas
    git.add_commit("p1", "m0", "ch1 ajuste", D)
    git.set_branch("13.34.0", "p1")

    with pytest.raises(SystemExit) as saida:
        main(["reconstruir-estado", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert saida.value.code == 1
    assert "[referencia] padrao" in caplog.text


def test_reconstruir_estado_ponta_a_ponta(bordas, tmp_path, capsys):
    git, _estado = bordas
    # commit na branch da versao sem ch<num> na mensagem: orfao
    git.add_commit("p1", "m0", "ajuste sem numero", D)
    git.set_branch("13.34.0", "p1")

    main(["reconstruir-estado", "13.34.0", "--repo", _repo_dir(tmp_path)])

    saida = capsys.readouterr().out
    assert "status: PENDING_JUDGMENT, orfaos: 1" in saida
    assert "p1" in saida and "sem referencia de tarefa na mensagem" in saida


def test_reconstruir_estado_pendente_indica_julgar_orfao(bordas, tmp_path, capsys):
    git, _estado = bordas
    git.add_commit("p1", "m0", "ajuste sem numero", D)
    git.set_branch("13.34.0", "p1")

    main(["reconstruir-estado", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert "monitor-versoes julgar-orfao 13.34.0" in capsys.readouterr().out


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param(["--nenhum"], id="sem-motivo"),
        pytest.param(["--motivo", "m"], id="sem-chamado-nem-nenhum"),
        pytest.param(
            ["--chamado", "1", "--nenhum", "--motivo", "m"], id="chamado-e-nenhum"
        ),
    ],
)
def test_julgar_orfao_erro_de_uso(monkeypatch, extra):
    def proibido():
        raise AssertionError("abriu o banco antes de validar as flags")

    monkeypatch.setattr(cli, "abrir_sessao", proibido)

    with pytest.raises(SystemExit) as saida:
        main(["julgar-orfao", "13.34.0", "p1", "--repo", "webapp", *extra])

    assert saida.value.code == 2


def test_orfaos_e_julgar_orfao_pelo_main(bordas, tmp_path, capsys):
    git, estado = bordas
    git.add_commit("p1", "m0", "ajuste sem numero", D)
    git.set_branch("13.34.0", "p1")
    estado.registrar_versao(
        "webapp",
        VersaoInfo(
            numero="13.34.0", tipo="ajustada", base_ref="13.33.0", base_commit="m0"
        ),
    )
    repo = _repo_dir(tmp_path)

    main(["julgar-orfao", "13.34.0", "p1", "--repo", repo, "--nenhum", "--motivo", "m"])
    main(["orfaos", "13.34.0", "--repo", repo])

    saida = capsys.readouterr().out
    assert "julgado: p1 -> nenhum" in saida
    assert "p1 2026-01-01 ajuste sem numero [nenhum: m]" in saida


def test_consulta_ponta_a_ponta_le_snapshot_sem_recalcular(bordas, tmp_path, capsys):
    git, estado = bordas
    git.add_commit(
        "c0ffee123456", "a0", "Título " + "longo " * 30 + "\ncorpo oculto", D
    )
    estado.registrar_versao(
        "webapp",
        VersaoInfo(numero="13.34.0", tipo="ajustada"),
    )
    estado.substituir_atribuicoes(
        "webapp",
        "13.34.0",
        [
            Atribuicao(
                chamado="123456",
                marcada="13.34.0",
                estado="aplicado",
                commits=["c0ffee123456", "deadbeefcafe"],
            )
        ],
    )

    main(["consulta", "13.34.0", "--repo", _repo_dir(tmp_path)])

    saida = capsys.readouterr().out
    assert "123456" in saida and "APLICADO" in saida
    assert "c0ffee12" in saida and "…" in saida
    assert "corpo oculto" not in saida
    assert "deadbeef" in saida and "mensagem indisponível" in saida
    assert git.fetched == []


def test_criar_ponta_a_ponta(bordas, tmp_path, capsys):
    lista = tmp_path / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")

    main(
        [
            "criar",
            "13.35.0",
            "--repo",
            _repo_com_padrao(tmp_path),
            "--task-source",
            "manual",
            "--lista",
            str(lista),
        ]
    )

    saida = capsys.readouterr().out
    assert "cherry-picks aplicados" in saida
    assert "a0" in saida and "concluido" in saida


def test_atualizar_abort_ponta_a_ponta(bordas, tmp_path, capsys, monkeypatch):
    # pina o despacho de --abort: a flag e lida como args.abortar, e o comando
    # nem chega a precisar de fonte de tasks.
    git, _ = bordas
    # Pina o default: o conftest carrega .env.development na coleta, e um
    # WORKTREES_MANTIDAS=0 na maquina de alguem trocaria o resultado aqui.
    monkeypatch.setenv("WORKTREES_MANTIDAS", "")

    main(["atualizar", "13.34.0", "--repo", _repo_dir(tmp_path), "--abort"])

    assert capsys.readouterr().out == "abortado\n"
    # Default de WORKTREES_MANTIDAS (3): o checkout sobrevive ao abort, pra o
    # `atualizar` seguinte na mesma versao nao pagar `worktree add` de novo.
    assert git.removed_worktrees == []


@pytest.mark.parametrize(
    "config",
    ['[versao]\nesquema = "naoexiste"\n', '[versao]\npiso = "abc"\n'],
    ids=["esquema-desconhecido", "piso-invalido"],
)
def test_abort_nao_resolve_o_versionamento(bordas, tmp_path, capsys, config):
    """Sair de um lote travado nao pode depender de o esquema carregar nem de
    o piso valer (docs/decisoes/026-esquema-e-atribuicao-plugaveis.md)."""
    repo = _repo_dir(tmp_path, do_repo=config)

    main(["atualizar", "13.34.0", "--repo", repo, "--abort"])

    assert capsys.readouterr().out == "abortado\n"


def test_abort_usa_a_branch_da_versao_da_config(bordas, tmp_path, capsys):
    git, _ = bordas
    git.set_branch("release/13.34.0", "m0")
    repo = _repo_dir(
        tmp_path,
        do_repo='[versao]\nesquema = "naoexiste"\n[branches]\nversao = "release/{versao}"\n',
    )

    main(["atualizar", "13.34.0", "--repo", repo, "--abort"])

    assert capsys.readouterr().out == "abortado\n"
    assert git.worktrees_mru[0] == "release/13.34.0"


def test_worktrees_mantidas_zero_descarta_o_checkout_no_fim(
    bordas, tmp_path, capsys, monkeypatch
):
    """Ponta a ponta do outro extremo: `WORKTREES_MANTIDAS=0` no ambiente
    chega ate o `worktree_gc` e reproduz o comportamento historico."""
    git, _ = bordas
    monkeypatch.setenv("WORKTREES_MANTIDAS", "0")

    main(["atualizar", "13.34.0", "--repo", _repo_dir(tmp_path), "--abort"])

    assert git.removed_worktrees == ["13.34.0"]


def test_worktrees_mantidas_invalido_sai_1(bordas, tmp_path, caplog, monkeypatch):
    """Erro de config nao pode virar default calado: o comando para, e a
    mensagem diz qual variavel esta errada."""
    monkeypatch.setenv("WORKTREES_MANTIDAS", "tres")

    with pytest.raises(SystemExit) as saida:
        main(["atualizar", "13.34.0", "--repo", _repo_dir(tmp_path), "--abort"])

    assert saida.value.code == 1
    assert "WORKTREES_MANTIDAS inválido: 'tres'" in caplog.text


def test_manual_sem_lista_sai_1(bordas, tmp_path, capsys):
    with pytest.raises(SystemExit) as saida:
        main(
            [
                "verificar",
                "13.34.0",
                "--repo",
                _repo_dir(tmp_path),
                "--task-source",
                "manual",
            ]
        )

    assert saida.value.code == 1
    assert "--lista" in capsys.readouterr().err


def test_erro_operacional_sai_1_sem_traceback(bordas, tmp_path, monkeypatch, caplog):
    def sem_banco():
        raise MotorError("banco inacessivel na fixture")

    monkeypatch.setattr(cli, "abrir_sessao", sem_banco)

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert saida.value.code == 1
    assert caplog.messages == ["banco inacessivel na fixture"]
    assert "Traceback" not in caplog.text


def test_erro_com_nota_mostra_contexto_e_causa_na_linha(
    bordas, tmp_path, monkeypatch, caplog
):
    """__notes__ so aparece em traceback renderizado, e MotorError nunca
    renderiza traceback aqui — sem concatenar a nota na linha visivel, o
    contexto que os services agregam via add_note (task 7) se perdia por
    completo para o operador.
    """

    def sem_banco():
        erro = MotorError("rastreador respondeu 503")
        erro.add_note("buscando tasks da versao 13.34.0")
        raise erro

    monkeypatch.setattr(cli, "abrir_sessao", sem_banco)

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert saida.value.code == 1
    assert "buscando tasks da versao 13.34.0" in caplog.text
    assert "rastreador respondeu 503" in caplog.text


def test_bug_sai_1_com_traceback(bordas, tmp_path, monkeypatch, caplog):
    def bug():
        raise RuntimeError("isto e um bug")

    monkeypatch.setattr(cli, "abrir_sessao", bug)

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert saida.value.code == 1
    assert "Traceback" in caplog.text


def test_main_nao_repovoa_variavel_que_o_teste_apagou(
    bordas, tmp_path, monkeypatch, caplog
):
    """Pina a guarda estrutural do "sem rede" (fixture _sem_dotenv_dentro_do_main
    no conftest): sem ela, o load_dotenv() de dentro do main() traz de volta toda
    variavel que o teste apagou — foi assim que um teste de credencial ausente
    saiu para o host real do rastreador na Task 12.

    """
    # Pin estrutural, nao comportamental: `load_dotenv()` procura o .env a partir
    # do arquivo que a chama, nao da CWD, entao nao da para plantar um .env de
    # teste e observar o efeito. E `main()` faz `if load_dotenv: load_dotenv()`,
    # logo "a guarda esta instalada" E o contrato inteiro. Antes a assercao era
    # so comportamental e ficava vazia em maquina sem .env — em clone novo ou CI
    # a guarda podia ser apagada sem nada ficar vermelho, que e exatamente a
    # classe de falha que ela existe para fechar.
    assert cli.load_dotenv is None, (
        "a fixture _sem_dotenv_dentro_do_main nao desligou o load_dotenv() do "
        "main(): variavel apagada por um teste volta do .env de verdade e o run "
        "sai para a rede"
    )

    monkeypatch.delenv("FONTE_FALSA_TOKEN", raising=False)

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert saida.value.code == 1
    assert "faltando no .env: FONTE_FALSA_TOKEN" in caplog.text
    assert "FONTE_FALSA_TOKEN" not in os.environ, "load_dotenv() rodou dentro do main()"


@pytest.mark.parametrize(
    "comando,esperado",
    [
        (["atualizar", "13.34.0", "--abort"], "abortado"),
        (["reconstruir-estado", "13.34.0"], "status: DONE"),
    ],
)
def test_comando_que_nao_busca_tarefa_roda_sem_credencial_da_fonte(
    bordas, tmp_path, monkeypatch, capsys, comando, esperado
):
    """`atualizar --abort` e `reconstruir-estado` montam a fonte de tarefas mas
    nunca chamam fetch. Sao os comandos de recuperacao: exigir a credencial da
    fonte (vazia num [ambiente] recém-escrito) travaria justamente o comando que se usa
    quando algo ja esta quebrado.
    """
    # "" e nao delenv: o que se testa aqui e credencial vazia, nao a
    # variavel ausente.
    monkeypatch.setenv("FONTE_FALSA_TOKEN", "")

    main([*comando, "--repo", _repo_dir(tmp_path)])

    # chegou ao fim do comando, nao so deixou de reclamar
    assert esperado in capsys.readouterr().out


def test_lista_manual_funciona_sem_fonte_na_config(bordas, tmp_path, capsys):
    # quem usa --lista nao precisa de fonte de tarefas configurada.
    _fonte_central(None)
    lista = tmp_path / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")

    main(
        [
            "verificar",
            "13.34.0",
            "--repo",
            _repo_com_padrao(tmp_path),
            "--task-source",
            "manual",
            "--lista",
            str(lista),
        ]
    )

    assert "verde:" in capsys.readouterr().out


# -- --repo pelo nome da seção -------------------------------------------------


def test_repo_por_nome_da_secao(bordas, tmp_path, monkeypatch):
    git, estado = bordas
    assert isinstance(git, FakeGit)
    abertos: list[str] = []
    vistos: list[str] = []

    def abrir_git(caminho: str, **_: object) -> FakeGit:
        abertos.append(caminho)
        return git

    def consultar_espiao(deps: Deps, versao: str) -> list[Any]:
        vistos.append(deps.repo)
        return []

    monkeypatch.setattr(montagem, "new_git_subprocess", abrir_git)
    monkeypatch.setattr(cli, "consultar", consultar_espiao)
    nome = _repo_dir(tmp_path, "x")

    main(["consulta", "13.34.0", "--repo", nome])

    assert abertos == [str(tmp_path / "x")]
    assert vistos == ["x"]
    assert "x" in [r.nome for r in estado.listar_repos()]


def test_repo_por_caminho_nao_e_aceito(bordas, tmp_path, capsys):
    _, estado = bordas
    nome = _repo_dir(tmp_path, "x")
    antes = estado.listar_repos()

    with pytest.raises(SystemExit) as saida:
        main(["consulta", "13.34.0", "--repo", str(tmp_path / nome)])

    assert saida.value.code == ARGPARSE_USO_INVALIDO
    assert "use um nome simples, sem caminho" in capsys.readouterr().err
    assert estado.listar_repos() == antes


def test_imprimir_status_nomeia_os_chamados_culpados_pelo_conflito(capsys):
    """ "[CONFLITANTE]" sozinho diz que o commit trava, nao de que alteracao ele
    depende. Nomear os chamados e o que permite decidir entre puxar a
    dependencia para esta versao ou devolver o chamado.
    """
    faltante = CommitRef(
        hash_origem="a0a0a0a0a0", chamado="255514", msg="ch255514 alfa"
    )
    imprimir_status(
        VersionStatus(
            estado_integro=True,
            faltantes=[faltante],
            conflitantes=[faltante],
            conflito_causado_por={"a0a0a0a0a0": ["255101", "254800"]},
        ),
        lambda: REFERENCIA_CH,
    )

    saida = capsys.readouterr().out
    assert "CONFLITANTE" in saida
    assert "ch255101" in saida
    assert "ch254800" in saida


def test_imprimir_status_nomeia_culpado_pelo_padrao_da_referencia(capsys):
    faltante = CommitRef(hash_origem="a0a0a0a0a0", chamado="PAY-1", msg="PAY-1 x")
    imprimir_status(
        VersionStatus(
            estado_integro=True,
            faltantes=[faltante],
            conflitantes=[faltante],
            conflito_causado_por={"a0a0a0a0a0": ["PAY-123"]},
        ),
        lambda: Referencia("{id}"),
    )

    saida = capsys.readouterr().out
    assert "depende de PAY-123," in saida


def test_lista_manual_sem_padrao_de_referencia_sai_1(bordas, tmp_path):
    lista = tmp_path / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")
    argv = ["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)]

    with pytest.raises(SystemExit) as e:
        main([*argv, "--task-source", "manual", "--lista", str(lista)])

    assert e.value.code == 1


def test_abort_com_lista_manual_nao_exige_padrao_de_referencia(
    bordas, tmp_path, capsys
):
    # Recuperacao nao usa a referencia: a falta dela nao pode travar o abort.
    lista = tmp_path / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")
    argv = ["atualizar", "13.34.0", "--repo", _repo_dir(tmp_path), "--abort"]

    main([*argv, "--task-source", "manual", "--lista", str(lista)])

    assert capsys.readouterr().out == "abortado\n"


def test_imprimir_status_sem_culpados_mantem_a_tag_seca(capsys):
    faltante = CommitRef(
        hash_origem="a0a0a0a0a0", chamado="255514", msg="ch255514 alfa"
    )
    imprimir_status(
        VersionStatus(
            estado_integro=True,
            faltantes=[faltante],
            conflitantes=[faltante],
        ),
        lambda: REFERENCIA_CH,
    )

    saida = capsys.readouterr().out
    assert "[CONFLITANTE]" in saida
    assert "depende" not in saida


def test_verificar_nao_busca_versao_abaixo_do_piso_do_repo(bordas, tmp_path):
    _fonte_central(_FIXA)
    repo = _repo_dir(tmp_path, do_repo='[versao]\npiso = "13.34.0"\n')

    main(["verificar", "13.34.0", "--repo", repo])

    # 13.33.0 esta aberta e seria fonte sem o piso
    assert FonteFixa.buscadas == ["13.34.0"]


def test_sem_piso_nenhuma_versao_e_cortada(bordas, tmp_path):
    _fonte_central(_FIXA)

    main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert "13.33.0" in FonteFixa.buscadas and "13.34.0" in FonteFixa.buscadas


# -- diagnostico --------------------------------------------------------------


def test_diagnostico_esta_no_parser_sem_exigir_repo():
    args = _build_parser().parse_args(["diagnostico"])

    assert args.comando == "diagnostico"


@pytest.mark.parametrize(("falha", "codigo"), [(False, 0), (True, 1)])
def test_diagnostico_imprime_e_sai_com_o_codigo_certo(
    monkeypatch, capsys, falha, codigo
):
    from motor.diagnostico import Estado, Resultado

    estado = Estado.FALHA if falha else Estado.OK
    monkeypatch.setattr(cli, "load_dotenv", None)
    monkeypatch.setattr(cli, "head", lambda: "rev")
    monkeypatch.setattr(
        cli,
        "diagnosticar",
        lambda *a, **k: [
            Resultado(Peca.SQLITE, estado, "x", "conferir DATABASE_SQLITE_PATH")
        ],
    )
    monkeypatch.setattr(
        cli, "abrir_sessao", lambda: pytest.fail("não abre sessão por conta própria")
    )

    if falha:
        with pytest.raises(SystemExit) as saida:
            main(["diagnostico"])
        assert saida.value.code == codigo
    else:
        main(["diagnostico"])
    assert estado.value in capsys.readouterr().out


def test_diagnostico_le_a_fonte_do_config_central(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    central = tmp_path / "monitor-versoes" / "config.toml"
    central.parent.mkdir()
    central.write_text('[tarefas]\nfonte = "tests.fontes_falsas:FonteFixa"\n')
    monkeypatch.setattr(cli, "load_dotenv", None)
    monkeypatch.setattr(cli, "head", lambda: "rev")
    recebido = {}

    def falso(*a, **k):
        recebido["config"] = k["config_central"]()
        return []

    monkeypatch.setattr(cli, "diagnosticar", falso)

    main(["diagnostico"])

    fonte = recebido["config"].fonte_tarefas
    assert fonte is not None and fonte.valor == "tests.fontes_falsas:FonteFixa"


def test_diagnostico_mostra_o_central_invalido_e_as_demais_linhas(
    monkeypatch, capsys, tmp_path
):
    from motor.errors import BackendIndisponivel

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    central = tmp_path / "monitor-versoes" / "config.toml"
    central.parent.mkdir()
    central.write_text("isto = = nao\n")
    monkeypatch.setattr(cli, "head", lambda: "rev")

    def banco_fora(garantir=True):
        raise BackendIndisponivel("banco fora")

    monkeypatch.setattr(cli, "abrir_sessao", banco_fora)

    with pytest.raises(SystemExit):
        main(["diagnostico"])

    linhas = capsys.readouterr().out.splitlines()
    assert linhas[0].startswith("FALHA  Ambiente:")
    assert str(central) in linhas[0]
    for peca in ("Variáveis", "SQLite", "Tarefas", "Fonte de PR"):
        assert any(f"  {peca}" in linha for linha in linhas), peca


# -- inscricao ----------------------------------------------------------------


class _Inscr(StrEnum):
    VERSAO = "13.34.0"
    BUG = "boom"


@pytest.fixture
def inscricoes_env(monkeypatch, tmp_path):
    """Arquivo de inscrições e HOME em tmp_path; notificador fake."""
    from motor.adapters.notificador.fake import FakeNotificador

    arquivo = tmp_path / "inscricoes.json"
    monkeypatch.setattr(cli, "caminho_arquivo", lambda: arquivo)
    monkeypatch.setattr(cli, "load_dotenv", None)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    (tmp_path / "xdg" / "monitor-versoes").mkdir(parents=True)
    notificador = FakeNotificador()
    monkeypatch.setattr(cli, "montar_notificador", lambda: notificador)
    return arquivo, notificador


def _inscrever(repo: str) -> None:
    main(["inscricao", "adicionar", _Inscr.VERSAO, "--repo", repo])


def test_inscricao_adicionar_guarda_o_nome_e_recusa_repo_fora_da_config(
    inscricoes_env, tmp_path
):
    from motor.inscricoes import carregar

    arquivo, _ = inscricoes_env
    nome = _repo_dir(tmp_path)
    _inscrever(nome)
    with pytest.raises(SystemExit):
        _inscrever("inexistente")
    assert [i.repo for i in carregar(arquivo)] == [nome]


def test_inscricao_adicionar_grava_sem_diretorio_nem_ambiente(inscricoes_env, tmp_path):
    arquivo, _ = inscricoes_env
    _inscrever(_repo_dir(tmp_path))
    [crua] = json.loads(arquivo.read_text(encoding="utf-8"))
    assert "diretorio" not in crua
    assert "ambiente" not in crua


def test_inscricao_adicionar_avisa_sem_agendador(inscricoes_env, tmp_path, capsys):
    _inscrever(_repo_dir(tmp_path))
    assert "agendador não instalado" in capsys.readouterr().err


def test_inscricao_listar(inscricoes_env, tmp_path, capsys):
    nome = _repo_dir(tmp_path)
    _inscrever(nome)
    capsys.readouterr()
    main(["inscricao", "listar"])
    saida = capsys.readouterr().out
    assert _Inscr.VERSAO in saida
    assert nome in saida
    assert "nunca rodou" in saida


def test_inscricao_listar_mostra_a_mensagem_do_erro(inscricoes_env, tmp_path, capsys):
    from motor.domain.inscricao import Desfecho, UltimaExecucao
    from motor.inscricoes import carregar, salvar

    arquivo, _ = inscricoes_env
    _inscrever(_repo_dir(tmp_path))
    [i] = carregar(arquivo)
    ultima = UltimaExecucao(
        datetime.datetime.now(datetime.UTC),
        Desfecho.ERRO,
        Desfecho.ERRO,
        frozenset(),
        _Inscr.BUG,
    )
    salvar(arquivo, [dataclasses.replace(i, ultima=ultima)])
    capsys.readouterr()
    main(["inscricao", "listar"])
    assert f"{Desfecho.ERRO.value}: {_Inscr.BUG}" in capsys.readouterr().out


def test_inscricao_listar_mostra_intervalo_formatado(inscricoes_env, tmp_path, capsys):
    from motor.inscricoes import INTERVALO_PADRAO, formatar_intervalo, parse_intervalo

    _inscrever(_repo_dir(tmp_path))
    capsys.readouterr()
    main(["inscricao", "listar"])
    padrao = formatar_intervalo(parse_intervalo(INTERVALO_PADRAO))
    assert f"a cada {padrao}  " in capsys.readouterr().out


def test_executavel_sem_console_roda_as_inscricoes_sem_stdout_nem_stderr(
    inscricoes_env, monkeypatch
):
    """O `gui-scripts` do pacote (a tarefa agendada do Windows) roda o mesmo que
    `inscricao rodar`, e sem console o Windows dá `None` em stdout/stderr."""
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    (alvo,) = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"][
        "gui-scripts"
    ].values()
    vistos: list[Any] = []
    monkeypatch.setattr(cli, "rodar", lambda *a: vistos.append(a))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    pkgutil.resolve_name(alvo)()
    assert len(vistos) == 1


def test_inscricao_rodar_nao_le_env_nem_central(inscricoes_env, monkeypatch, tmp_path):
    chave = "CHAVE_SO_DO_DOTENV"
    monkeypatch.setenv(chave, "")  # registra a limpeza do que o .env poria
    monkeypatch.delenv(chave)
    (tmp_path / ".env").write_text(f"{chave}=x\n")
    with open(_central(), "w", encoding="utf-8") as f:
        f.write("isto = = nao\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_dotenv", dotenv.load_dotenv)
    visto: dict[str, Any] = {}
    monkeypatch.setattr(
        cli, "rodar", lambda c, a, disparar, n: visto.update(d=disparar)
    )
    monkeypatch.setattr(cli, "montar_notificador", lambda: None)
    main(["inscricao", "rodar"])
    assert chave not in os.environ
    capturado: dict[str, Any] = {}

    def falso(cmd, **kw):
        capturado.update(kw)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", falso)
    inscricao = Inscricao(str(tmp_path), _Inscr.VERSAO, datetime.timedelta(minutes=1))
    visto["d"](inscricao)
    assert chave not in capturado["env"]


def test_central_invalido_derruba_o_comando(inscricoes_env, capsys):
    with open(_central(), "w", encoding="utf-8") as f:
        f.write("isto = = nao\n")
    with pytest.raises(SystemExit) as saida:
        main(["inscricao", "listar"])
    assert saida.value.code == 1
    assert _central() in capsys.readouterr().err


def test_central_invalido_no_executar_vira_erro_da_inscricao(
    inscricoes_env, monkeypatch, tmp_path, capsys
):
    nome = _preparar_execucao(
        monkeypatch, tmp_path, lambda deps, versao: pytest.fail("não executa")
    )
    with open(_central(), encoding="utf-8") as f:
        valido = f.read()
    with open(_central(), "w", encoding="utf-8") as f:
        f.write("isto = = nao\n" + valido)
    monkeypatch.setattr(
        cli,
        "abrir_sessao",
        lambda: pytest.fail("não abre sessão com o central quebrado"),
    )

    main(["inscricao", "executar", _Inscr.VERSAO, "--repo", nome])

    with open(_central(), "w", encoding="utf-8") as f:
        f.write(valido)
    capsys.readouterr()
    main(["inscricao", "listar"])
    linha = capsys.readouterr().out
    assert "erro" in linha
    assert _central() in linha


def _preparar_execucao(monkeypatch, tmp_path, executar):
    nome = _repo_dir(tmp_path)
    _inscrever(nome)
    monkeypatch.setattr(cli, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(cli, "montar_deps", lambda *a, **k: None)
    monkeypatch.setattr(cli, "executar_inscricao", executar)
    return nome


def test_inscricao_executar_grava_resultado(inscricoes_env, monkeypatch, tmp_path):
    from motor.domain.inscricao import Desfecho, Resultado
    from motor.inscricoes import carregar

    arquivo, _ = inscricoes_env
    nome = _preparar_execucao(
        monkeypatch, tmp_path, lambda deps, versao: Resultado(Desfecho.NADA)
    )
    main(["inscricao", "executar", _Inscr.VERSAO, "--repo", nome])
    ultima = carregar(arquivo)[0].ultima
    assert ultima is not None
    assert ultima.desfecho == Desfecho.NADA


def test_inscricao_executar_bug_grava_erro_e_propaga(
    inscricoes_env, monkeypatch, tmp_path
):
    from motor.domain.inscricao import Desfecho
    from motor.inscricoes import carregar

    def bug(deps, versao):
        raise RuntimeError(_Inscr.BUG)

    arquivo, _ = inscricoes_env
    nome = _preparar_execucao(monkeypatch, tmp_path, bug)
    with pytest.raises(SystemExit):
        main(["inscricao", "executar", _Inscr.VERSAO, "--repo", nome])
    ultima = carregar(arquivo)[0].ultima
    assert ultima is not None
    assert ultima.desfecho == Desfecho.ERRO
    assert ultima.mensagem == f"RuntimeError: {_Inscr.BUG}"


def test_inscricao_nao_abre_banco_exceto_executar(
    inscricoes_env, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        cli, "abrir_sessao", lambda: pytest.fail("só o executar abre sessão")
    )
    _inscrever(_repo_dir(tmp_path))
    main(["inscricao", "listar"])


def test_executar_fora_do_help(capsys):
    with pytest.raises(SystemExit):
        main(["inscricao", "-h"])
    saida = capsys.readouterr().out
    assert "listar" in saida
    assert "executar" not in saida


def test_serve_com_porta_ocupada_sai_com_uma_linha(bordas, caplog):
    import socket

    with socket.socket() as ocupada:
        ocupada.bind(("127.0.0.1", 0))
        porta = ocupada.getsockname()[1]
        ocupada.listen()
        with pytest.raises(SystemExit) as saida:
            main(["serve", "--porta", str(porta)])

    assert saida.value.code == 1
    assert caplog.messages == [f"porta {porta} em uso; use --porta"]


def test_serve_aceita_porta_so_com_time_wait(monkeypatch):
    import socket

    import motor.daemon.app as daemon_app

    with socket.socket() as escuta:
        escuta.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # como o uvicorn
        escuta.bind(("127.0.0.1", 0))
        porta = escuta.getsockname()[1]
        escuta.listen()
        with socket.create_connection(("127.0.0.1", porta)) as cliente:
            conexao, _ = escuta.accept()
            conexao.close()  # o lado servidor fecha primeiro e fica em TIME_WAIT
            cliente.recv(1)
    rodou = []
    monkeypatch.setattr(daemon_app, "_rodar", lambda app, p: rodou.append(p))
    daemon_app.servir(porta)
    assert rodou == [porta]


# -- configuração antiga do Postgres ------------------------------------------

_BACKEND_POSTGRES = '[ambiente]\nDATABASE_BACKEND = "postgres"\n'
_CINCO_POSTGRES = "[ambiente]\n" + "".join(
    f'DATABASE_{c} = "x"\n' for c in ("HOST", "PORT", "NAME", "USER", "PASSWORD")
)


def _central_com(monkeypatch, tmp_path, conteudo: str):
    """Central em tmp_path com `conteudo` e o repo `webapp`; devolve o SQLite."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-antigo"))
    central = tmp_path / "xdg-antigo" / "monitor-versoes" / "config.toml"
    central.parent.mkdir(parents=True)
    clone = tmp_path / "webapp"
    clone.mkdir()
    central.write_text(f"{conteudo}\n[repos.webapp]\ncaminho = '{clone}'\n")
    return tmp_path / "estado.db"


def _sai_com_o_erro_da_config_antiga(argv, caplog):
    from motor.config import ULTIMO_COMMIT_COM_POSTGRES

    with pytest.raises(SystemExit) as saida:
        main(argv)
    assert saida.value.code == 1
    # O formato do log no terminal é `ERROR: <mensagem>`; aqui, o nível.
    (registro,) = caplog.records
    assert registro.levelname == "ERROR"
    assert "migrar-estado" in registro.message
    assert ULTIMO_COMMIT_COM_POSTGRES in registro.message


@pytest.mark.parametrize("conteudo", [_BACKEND_POSTGRES, _CINCO_POSTGRES])
@pytest.mark.parametrize(
    "argv", [["migrar"], ["verificar", "1.0.0", "--repo", "webapp"]]
)
def test_config_antiga_do_postgres_para_sem_criar_o_sqlite(
    monkeypatch, tmp_path, caplog, conteudo, argv
):
    sqlite = _central_com(monkeypatch, tmp_path, conteudo)

    _sai_com_o_erro_da_config_antiga(argv, caplog)

    assert not sqlite.exists()


def test_so_o_host_do_postgres_no_central_usa_o_sqlite(monkeypatch, tmp_path):
    import sqlite3

    from motor.migracoes import head

    sqlite = _central_com(
        monkeypatch, tmp_path, '[ambiente]\nDATABASE_HOST = "localhost"\n'
    )

    main(["migrar"])
    main(["migrar"])  # idempotente: a segunda não falha nem muda a revisão

    with contextlib.closing(sqlite3.connect(sqlite)) as conexao:
        (revisao,) = conexao.execute(
            "select version_num from alembic_version"
        ).fetchone()
    assert revisao == head()


def test_tui_com_config_antiga_nao_monta_a_tela(monkeypatch, tmp_path, caplog):
    import motor.tui

    _central_com(monkeypatch, tmp_path, _BACKEND_POSTGRES)
    monkeypatch.setattr(motor.tui, "run_tui", lambda: pytest.fail("montou a tela"))

    _sai_com_o_erro_da_config_antiga(["tui"], caplog)


def test_serve_com_config_antiga_nao_abre_a_porta(monkeypatch, tmp_path, caplog):
    import motor.daemon.app as daemon_app

    _central_com(monkeypatch, tmp_path, _BACKEND_POSTGRES)
    monkeypatch.setattr(daemon_app, "servir", lambda porta: pytest.fail("subiu"))

    _sai_com_o_erro_da_config_antiga(["serve"], caplog)


def test_inscricao_executar_com_config_antiga_grava_o_erro(
    inscricoes_env, monkeypatch, tmp_path
):
    from motor.domain.inscricao import Desfecho
    from motor.inscricoes import carregar

    arquivo, _ = inscricoes_env
    nome = _repo_dir(tmp_path)
    _inscrever(nome)
    with open(_central(), "a", encoding="utf-8") as f:
        f.write(_BACKEND_POSTGRES)
    monkeypatch.setattr(
        cli, "executar_inscricao", lambda deps, versao: pytest.fail("executou")
    )

    main(["inscricao", "executar", _Inscr.VERSAO, "--repo", nome])

    ultima = carregar(arquivo)[0].ultima
    assert ultima is not None
    assert ultima.desfecho == Desfecho.ERRO
    assert "migrar-estado" in ultima.mensagem
    assert not (tmp_path / "estado.db").exists()


# -- lock do repo (decisão 032) ---------------------------------------------


@pytest.mark.parametrize(
    "comando",
    [
        ["atualizar"],
        ["atualizar", "--continue"],
        ["atualizar", "--abort"],
        ["criar"],
        ["verificar"],
    ],
    ids=["atualizar", "continue", "abort", "criar", "verificar"],
)
def test_operacao_coberta_com_repo_ocupado_e_recusada_antes_do_banco(
    bordas, tmp_path, caplog, monkeypatch, comando
):
    from motor.trava import travar

    nome = _repo_dir(tmp_path)
    monkeypatch.setattr(cli, "abrir_sessao", lambda: pytest.fail("abriu o banco"))
    with travar(nome, str(tmp_path / nome)), pytest.raises(SystemExit) as saida:
        main([comando[0], "13.34.0", "--repo", nome, *comando[1:]])
    assert saida.value.code == 1
    assert f"ocupado por outra operação (pid {os.getpid()})" in caplog.text


@pytest.mark.parametrize(
    "comando",
    [["verificar", "--auditar"], ["consulta"], ["reconstruir-estado"]],
    ids=["auditar", "consulta", "reconstruir-estado"],
)
def test_leituras_rodam_com_repo_ocupado(bordas, tmp_path, monkeypatch, comando):
    from motor.trava import travar

    nome = _repo_dir(tmp_path)
    sentinela = object()
    despachados: list[object] = []
    monkeypatch.setattr(cli, "montar_deps", lambda *a, **k: sentinela)
    monkeypatch.setattr(cli, "_despachar", lambda args, deps: despachados.append(deps))
    with travar(nome, str(tmp_path / nome)):
        main([comando[0], "13.34.0", "--repo", nome, *comando[1:]])
    assert despachados == [sentinela]


def test_inscricao_executar_com_repo_ocupado_sai_pulada_sem_notificar(
    inscricoes_env, monkeypatch, tmp_path, capsys
):
    from motor.domain.inscricao import Desfecho
    from motor.inscricoes import carregar
    from motor.trava import travar

    arquivo, notificador = inscricoes_env
    nome = _preparar_execucao(
        monkeypatch, tmp_path, lambda deps, versao: pytest.fail("executou")
    )
    with travar(nome, str(tmp_path / nome)):
        main(["inscricao", "executar", _Inscr.VERSAO, "--repo", nome])
    ultima = carregar(arquivo)[0].ultima
    assert ultima is not None
    assert ultima.desfecho == Desfecho.PULADA
    assert ultima.mensagem is not None and "ocupado" in ultima.mensagem
    assert notificador.enviadas == []
    capsys.readouterr()
    main(["inscricao", "listar"])
    assert ultima.mensagem in capsys.readouterr().out


# -- aviso de versão nova -----------------------------------------------------


class _Cmd(StrEnum):
    DIAGNOSTICO = "diagnostico"
    INSCRICAO_RODAR = "inscricao rodar"
    PLUGIN_LISTAR = "plugin listar"
    ATUALIZAR_MOTOR = "atualizar-motor"
    VERSAO = "--version"


class _SemAviso(StrEnum):
    CHECAR_DESLIGADO = "checar_desligado"
    FORA_DO_UV_TOOL = "fora_do_uv_tool"


_COMANDO_MOTOR = f"{PACOTE_MOTOR} {COMANDO_ATUALIZAR_MOTOR}"
_NOVIDADE_MOTOR = Novidade(PACOTE_MOTOR, "0.2.0", "0.3.0", _COMANDO_MOTOR)
_MARCA_DO_AVISO = "disponível"
_LINHA_MOTOR = f"Versão 0.3.0 {_MARCA_DO_AVISO} (você tem 0.2.0): {_COMANDO_MOTOR}"
_PLUGIN = "meu-plugin"


def _preparar_aviso(monkeypatch, checado_em, *, novidades=None):
    renovacoes: list[int] = []
    novidades = (_NOVIDADE_MOTOR,) if novidades is None else novidades
    monkeypatch.setattr(modulo_novidades, "ler_registro", object)
    monkeypatch.setattr(modulo_novidades, "checagem_ligada", lambda: True)
    monkeypatch.setattr(
        modulo_novidades, "ler_cache", lambda _: Cache(checado_em, novidades)
    )
    monkeypatch.setattr(
        modulo_novidades, "disparar_renovacao", lambda _: renovacoes.append(1)
    )
    monkeypatch.setattr(cli, "head", lambda: "rev")
    monkeypatch.setattr(cli, "diagnosticar", lambda *a, **k: [])
    return renovacoes


def _agora() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def test_aviso_de_versao_nova_no_stderr(monkeypatch, capsys):
    _preparar_aviso(monkeypatch, _agora())

    main([_Cmd.DIAGNOSTICO])

    saida = capsys.readouterr()
    assert saida.err.rstrip().endswith(_LINHA_MOTOR)
    assert _MARCA_DO_AVISO not in saida.out


def test_aviso_de_plugin_traz_o_pacote_e_o_comando(monkeypatch, capsys):
    plugin = Novidade(
        _PLUGIN, "1.0.0", "1.1.0", f"{PACOTE_MOTOR} plugin atualizar {_PLUGIN}"
    )
    _preparar_aviso(monkeypatch, _agora(), novidades=(_NOVIDADE_MOTOR, plugin))

    main([_Cmd.DIAGNOSTICO])

    err = capsys.readouterr().err
    assert _LINHA_MOTOR in err
    assert f"{_PLUGIN}: Versão 1.1.0 {_MARCA_DO_AVISO} (você tem 1.0.0): " in err


@pytest.mark.parametrize(
    "comando",
    [_Cmd.INSCRICAO_RODAR, _Cmd.PLUGIN_LISTAR, _Cmd.ATUALIZAR_MOTOR, _Cmd.VERSAO],
)
def test_sem_aviso_nos_comandos_excluidos(monkeypatch, capsys, comando):
    renovacoes = _preparar_aviso(monkeypatch, _agora() - datetime.timedelta(days=3))
    monkeypatch.setattr(cli, "_SEM_BANCO", {c: lambda a: None for c in cli._SEM_BANCO})
    monkeypatch.setattr(cli, "_inscricao", lambda a: None)

    with contextlib.suppress(SystemExit):
        main(comando.split())

    assert _MARCA_DO_AVISO not in capsys.readouterr().err
    assert renovacoes == []


@pytest.mark.parametrize("motivo", list(_SemAviso))
def test_sem_aviso_sem_checagem_ou_fora_do_uv_tool(monkeypatch, capsys, motivo):
    renovacoes = _preparar_aviso(monkeypatch, _agora() - datetime.timedelta(days=3))
    if motivo is _SemAviso.CHECAR_DESLIGADO:
        monkeypatch.setattr(modulo_novidades, "checagem_ligada", lambda: False)
    else:
        monkeypatch.setattr(modulo_novidades, "ler_registro", lambda: None)

    main([_Cmd.DIAGNOSTICO])

    assert _MARCA_DO_AVISO not in capsys.readouterr().err
    assert renovacoes == []


def test_cache_vencido_dispara_renovacao_sem_esperar(monkeypatch, capsys):
    renovacoes = _preparar_aviso(monkeypatch, _agora() - datetime.timedelta(days=3))

    main([_Cmd.DIAGNOSTICO])

    assert renovacoes == [1]
    assert _LINHA_MOTOR in capsys.readouterr().err


def test_aviso_aparece_tambem_quando_o_comando_falha(monkeypatch, capsys):
    from motor.diagnostico import Estado, Resultado

    _preparar_aviso(monkeypatch, _agora())
    monkeypatch.setattr(
        cli,
        "diagnosticar",
        lambda *a, **k: [Resultado(Peca.SQLITE, Estado.FALHA, "x", "y")],
    )

    with pytest.raises(SystemExit):
        main([_Cmd.DIAGNOSTICO])

    assert _LINHA_MOTOR in capsys.readouterr().err


def test_falha_no_aviso_nao_derruba_o_comando(monkeypatch, capsys):
    _preparar_aviso(monkeypatch, _agora())
    monkeypatch.setattr(modulo_novidades, "ler_cache", lambda _: 1 / 0)

    main([_Cmd.DIAGNOSTICO])

    assert _MARCA_DO_AVISO not in capsys.readouterr().err
