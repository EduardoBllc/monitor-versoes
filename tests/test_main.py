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
import os
import subprocess
from enum import StrEnum
from typing import Any

import dotenv
import pytest

import motor.__main__ as cli
import motor.montagem as montagem
from motor.__main__ import (
    _build_parser,
    _resolver_repo,
    imprimir_atualizacao,
    imprimir_status,
    main,
)
from motor.adapters.commitsource.bitbucket import BitbucketPRCommitSource
from motor.adapters.commitsource.chain import ChainCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
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
from motor.montagem import CredenciaisBitbucket
from motor.plugins import Origem, carregar_plugin
from tests.fontes_falsas import REFERENCIA_CH, FonteFixa
from tests.versionamento import ESCALONADO_COMPOSTA

D = datetime.datetime(2026, 1, 1)


# -- parser -------------------------------------------------------------------


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
    monkeypatch.setattr(cli, "_iniciar_tui", chamadas.append)
    monkeypatch.setattr(
        cli,
        "abrir_sessao",
        lambda: pytest.fail("o CLI nao deve abrir banco antes da TUI"),
    )

    main(argv)

    assert chamadas == [ambiente]
    assert ambientes == [arquivo]


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
                "/tmp",
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


def test_repo_adicionar_cadastra_sem_checkout_git(monkeypatch, capsys):
    estado = FakeEstado()
    monkeypatch.setattr(cli, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(cli, "PostgresEstado", lambda sessao: estado)

    main(["repo", "adicionar", "backend"])

    assert estado.resolver_repo("backend") == RepoInfo(nome="backend")
    assert capsys.readouterr().out == "repo 'backend' adicionado\n"


@pytest.mark.parametrize(
    ("argumentos", "mensagem"),
    [
        (["pasta/backend"], "nome simples"),
        ([" backend"], "nome simples"),
    ],
)
def test_repo_adicionar_recusa_argumentos_invalidos(argumentos, mensagem, capsys):
    with pytest.raises(SystemExit) as saida:
        _build_parser().parse_args(["repo", "adicionar", *argumentos])

    assert saida.value.code != 0
    assert mensagem in capsys.readouterr().err


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


def _repo_dir(tmp_path, nome: str = "webapp") -> str:
    caminho = tmp_path / nome
    caminho.mkdir()
    return str(caminho)


def _repo_com_padrao(tmp_path) -> str:
    """Repo com `padrao = "ch{id}"`: a lista manual nao propoe referencia."""
    caminho = _repo_dir(tmp_path)
    with open(f"{caminho}/.monitor-versoes.toml", "w", encoding="utf-8") as f:
        f.write('[referencia]\npadrao = "ch{id}"\n')
    return caminho


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
    """Reescreve o `config.toml` central da fixture `bordas` com outra fonte."""
    global_ = os.path.join(
        os.environ["XDG_CONFIG_HOME"], "monitor-versoes", "config.toml"
    )
    conteudo = '[versao]\nesquema = "tests.versionamento:Escalonado"\natribuicao = "composta"\n'
    if fonte is not None:
        conteudo += f'[tarefas]\nfonte = "{fonte}"\n'
        if chamados is not None:
            conteudo += "chamados = [" + ", ".join(f'"{c}"' for c in chamados) + "]\n"
    with open(global_, "w", encoding="utf-8") as f:
        f.write(conteudo)


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
    monkeypatch.setattr(montagem, "PostgresEstado", lambda sessao: estado)
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


def test_repo_alias_vira_o_nome_canonico_na_deps(bordas, tmp_path):
    _git, estado = bordas
    estado.aliases["vbweb"] = "webapp"
    lista = tmp_path / "lista.txt"
    lista.write_text("", encoding="utf-8")

    main(
        [
            "verificar",
            "13.34.0",
            "--repo",
            _repo_dir(tmp_path, "vbweb"),
            "--task-source",
            "manual",
            "--lista",
            str(lista),
        ]
    )

    # gravou sob o nome canonico, nao sob o basename do diretorio
    assert ("webapp", "13.34.0") in estado.versoes


def test_fonte_da_config_recebe_o_sistema_do_repo(bordas, tmp_path):
    _fonte_central(_FIXA)

    # sem --task-source: prova que o default do CLI e a fonte da config
    repo = _repo_dir(tmp_path)
    with open(f"{repo}/.monitor-versoes.toml", "w", encoding="utf-8") as f:
        f.write("[tarefas]\nsistema = 7\n")
    main(["verificar", "13.34.0", "--repo", repo])

    assert len(FonteFixa.recebidos) == 1
    recebido = FonteFixa.recebidos[0]
    tarefas = recebido["tarefas"]
    assert isinstance(tarefas, dict)
    # 7 vem do .monitor-versoes.toml do repo, nao do banco
    assert tarefas["sistema"] == 7
    assert tarefas["fonte"] == _FIXA
    arquivos = recebido["arquivos"]
    assert isinstance(arquivos, tuple)
    assert arquivos[-1] == f"{repo}/.monitor-versoes.toml"


def test_verificar_busca_tarefas_pela_fonte_da_config(bordas, tmp_path, capsys):
    _fonte_central(_FIXA, chamados=["123456"])

    main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    saida = capsys.readouterr().out
    # a0 cita ch123456 e so existe no master: a task chegou pela fonte
    assert "a0" in saida and "123456" in saida


def test_fonte_por_import_no_repo_e_recusada(bordas, tmp_path, caplog):
    _fonte_central(None)
    repo = _repo_dir(tmp_path)
    with open(f"{repo}/.monitor-versoes.toml", "w", encoding="utf-8") as f:
        f.write(f'[tarefas]\nfonte = "{_FIXA}"\n')

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", repo])

    assert saida.value.code == 1
    assert "import direto so vale no config.toml central" in caplog.text


def test_fonte_nao_instalada_e_recusada(bordas, tmp_path, caplog):
    _fonte_central("inexistente")

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert saida.value.code == 1
    assert "plugin 'inexistente' nao encontrado" in caplog.text


def test_sem_fonte_a_busca_pede_a_chave(bordas, tmp_path, caplog):
    _fonte_central(None)
    repo = _repo_com_padrao(tmp_path)
    central = os.path.join(
        os.environ["XDG_CONFIG_HOME"], "monitor-versoes", "config.toml"
    )

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", repo])

    assert saida.value.code == 1
    # as duas configs lidas aparecem, unidas por "e"
    assert (
        f"faltando [tarefas] fonte em {central} e {repo}/.monitor-versoes.toml; "
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

    def so_sem_tarefas(grupo: str, nome: str, origem: Origem) -> type:
        if grupo == montagem.GRUPO_TAREFAS:
            raise AssertionError("o plugin da fonte de tarefas foi carregado")
        return carregar_plugin(grupo, nome, origem)

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
    repo = _repo_dir(tmp_path)
    with open(f"{repo}/.monitor-versoes.toml", "w", encoding="utf-8") as f:
        f.write(config)

    main(["atualizar", "13.34.0", "--repo", repo, "--abort"])

    assert capsys.readouterr().out == "abortado\n"


def test_abort_usa_a_branch_da_versao_da_config(bordas, tmp_path, capsys):
    git, _ = bordas
    git.set_branch("release/13.34.0", "m0")
    repo = _repo_dir(tmp_path)
    with open(f"{repo}/.monitor-versoes.toml", "w", encoding="utf-8") as f:
        f.write(
            '[versao]\nesquema = "naoexiste"\n[branches]\nversao = "release/{versao}"\n'
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
    assert "WORKTREES_MANTIDAS invalido: 'tres'" in caplog.text


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
    fonte (vazia no env.example) travaria justamente o comando que se usa
    quando algo ja esta quebrado.
    """
    # "" e nao delenv: o que se testa aqui e credencial vazia, o caso do
    # env.example — nao a variavel ausente.
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


def test_flags_do_bitbucket_vencem_o_ambiente(bordas, tmp_path, monkeypatch):
    # a TUI prova o caminho do ambiente; este prova a flag do CLI chegando ate a
    # fonte de PR, e vencendo o ambiente quando os dois existem.
    monkeypatch.setenv("BITBUCKET_TOKEN", "tok-ambiente")
    monkeypatch.setenv("BITBUCKET_EMAIL", "ambiente@x.com")
    capturado: list[Deps] = []
    monkeypatch.setattr(cli, "_despachar", lambda args, deps: capturado.append(deps))

    main(
        [
            "verificar",
            "13.34.0",
            "--repo",
            _repo_dir(tmp_path),
            "--bitbucket-token",
            "tok-flag",
            "--bitbucket-email",
            "flag@x.com",
        ]
    )

    fonte = capturado[0].commit_source
    assert isinstance(fonte, ChainCommitSource)
    pr = fonte.sources[0]
    assert isinstance(pr, BitbucketPRCommitSource)
    assert (pr.token, pr.email) == ("tok-flag", "flag@x.com")


def test_repr_de_deps_nao_vaza_credencial_do_bitbucket():
    # a credencial mora dentro do CommitSource, e o repr default de Deps
    # atravessa o ChainCommitSource ate ela: um dump de deps sob --debug
    # imprimiria tudo em claro se o adapter nao tivesse repr=False.
    deps = Deps(
        versionamento=ESCALONADO_COMPOSTA,
        git=_git(),
        tasks=FakeTaskSource(),
        estado=FakeEstado(),
        repo="r",
        commit_source=montagem.montar_commit_source(
            _git(),
            referencia=lambda: REFERENCIA_CH,
            bitbucket=CredenciaisBitbucket("tok123", "dev@x.com"),
        ),
    )

    assert "tok123" not in repr(deps)
    assert "dev@x.com" not in repr(deps)


# -- _resolver_repo -----------------------------------------------------------


def test_resolver_repo_caminho_literal(tmp_path):
    alvo = tmp_path / "meurepo"
    alvo.mkdir()
    assert _resolver_repo(str(alvo)) == str(alvo)


def test_resolver_repo_via_projects_dir(tmp_path, monkeypatch):
    projetos = tmp_path / "projetos"
    (projetos / "webapp").mkdir(parents=True)
    monkeypatch.setenv("PROJECTS_DIR", str(projetos))

    resolvido = _resolver_repo("webapp")

    assert resolvido == os.path.join(str(projetos), "webapp")


def test_resolver_repo_tira_a_barra_final(tmp_path, monkeypatch):
    # tab-completion do shell manda "webapp/", e o basename disso e "" —
    # o nome do repo e a chave do estado inteiro.
    projetos = tmp_path / "projetos"
    (projetos / "webapp").mkdir(parents=True)
    monkeypatch.setenv("PROJECTS_DIR", str(projetos))

    assert os.path.basename(_resolver_repo("webapp/")) == "webapp"


def test_resolver_repo_nao_encontrado(tmp_path, monkeypatch):
    monkeypatch.delenv("PROJECTS_DIR", raising=False)
    with pytest.raises(SystemExit):
        _resolver_repo(str(tmp_path / "nao-existe"))


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
    repo = _repo_dir(tmp_path)
    with open(f"{repo}/.monitor-versoes.toml", "w", encoding="utf-8") as f:
        f.write('[versao]\npiso = "13.34.0"\n')

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
        lambda *a, **k: [Resultado("Postgres", estado, "x", "docker compose up -d")],
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
    assert fonte.origem == "central"


# -- migrar-estado ------------------------------------------------------------


def test_migrar_estado_exige_de_e_para():
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["migrar-estado", "--de", "sqlite:///a.db"])


def test_migrar_estado_copia_e_nao_avisa_do_backend_padrao(
    monkeypatch, capsys, tmp_path
):
    from sqlalchemy import insert

    from motor.adapters.estado.engine import criar_engine, garantir_esquema
    from motor.adapters.estado.models import Repo

    origem = f"sqlite:///{tmp_path / 'a.db'}"
    garantir_esquema(origem)
    engine = criar_engine(origem)
    with engine.begin() as con:
        con.execute(insert(Repo).values(nome="r"))
    engine.dispose()
    monkeypatch.setattr(cli, "load_dotenv", None)
    monkeypatch.setattr(
        cli, "abrir_sessao", lambda: pytest.fail("migrar-estado não abre sessão")
    )
    # as cinco partes sem DATABASE_BACKEND dispararia o aviso se a config fosse lida
    for parte, valor in {
        "HOST": "h",
        "PORT": "1",
        "NAME": "n",
        "USER": "u",
        "PASSWORD": "p",
    }.items():
        monkeypatch.setenv(f"DATABASE_{parte}", valor)
    monkeypatch.delenv("DATABASE_BACKEND", raising=False)

    main(["migrar-estado", "--de", origem, "--para", f"sqlite:///{tmp_path / 'b.db'}"])

    captured = capsys.readouterr()
    assert "repo: 1" in captured.out
    assert "DATABASE_BACKEND" not in captured.err


def test_migrar_estado_recusa_sai_com_codigo_de_erro_e_mensagem(
    monkeypatch, caplog, tmp_path
):
    monkeypatch.setattr(cli, "load_dotenv", None)
    url = f"sqlite:///{tmp_path / 'a.db'}"

    with pytest.raises(SystemExit) as saida:
        main(["migrar-estado", "--de", url, "--para", url])

    assert saida.value.code == 1
    assert "mesmo banco" in caplog.text


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
    notificador = FakeNotificador()
    monkeypatch.setattr(cli, "montar_notificador", lambda: notificador)
    return arquivo, notificador


def _inscrever_clone(clone: str) -> None:
    main(["inscricao", "adicionar", _Inscr.VERSAO, "--repo", clone])


def test_inscricao_adicionar_por_nome_e_por_caminho_dao_a_mesma(
    inscricoes_env, monkeypatch, tmp_path
):
    from motor.inscricoes import carregar

    arquivo, _ = inscricoes_env
    clone = _repo_dir(tmp_path)
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path))
    _inscrever_clone(clone)
    _inscrever_clone(os.path.basename(clone))
    assert [i.clone for i in carregar(arquivo)] == [clone]


def test_inscricao_adicionar_avisa_sem_agendador(inscricoes_env, tmp_path, capsys):
    _inscrever_clone(_repo_dir(tmp_path))
    assert "agendador não instalado" in capsys.readouterr().err


def test_inscricao_listar(inscricoes_env, tmp_path, capsys):
    clone = _repo_dir(tmp_path)
    _inscrever_clone(clone)
    capsys.readouterr()
    main(["inscricao", "listar"])
    saida = capsys.readouterr().out
    assert _Inscr.VERSAO in saida
    assert clone in saida
    assert "nunca rodou" in saida


def test_inscricao_listar_mostra_a_mensagem_do_erro(inscricoes_env, tmp_path, capsys):
    from motor.domain.inscricao import Desfecho, UltimaExecucao
    from motor.inscricoes import carregar, salvar

    arquivo, _ = inscricoes_env
    _inscrever_clone(_repo_dir(tmp_path))
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

    _inscrever_clone(_repo_dir(tmp_path))
    capsys.readouterr()
    main(["inscricao", "listar"])
    padrao = formatar_intervalo(parse_intervalo(INTERVALO_PADRAO))
    assert f"a cada {padrao}  " in capsys.readouterr().out


def test_inscricao_rodar_nao_vaza_o_env_carregado_do_dotenv(
    inscricoes_env, monkeypatch, tmp_path
):
    chave = "CHAVE_SO_DO_DOTENV"
    monkeypatch.setenv(chave, "")  # registra a limpeza do que o .env vai pôr
    monkeypatch.delenv(chave)
    (tmp_path / ".env").write_text(f"{chave}=x\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_dotenv", dotenv.load_dotenv)
    visto: dict[str, Any] = {}
    monkeypatch.setattr(
        cli, "rodar", lambda c, a, disparar, n: visto.update(d=disparar)
    )
    monkeypatch.setattr(cli, "montar_notificador", lambda: None)
    main(["inscricao", "rodar"])
    assert os.environ[chave] == "x"
    capturado: dict[str, Any] = {}

    def falso(cmd, **kw):
        capturado.update(kw)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", falso)
    inscricao = Inscricao(
        str(tmp_path),
        _Inscr.VERSAO,
        datetime.timedelta(minutes=1),
        str(tmp_path),
        "production",
    )
    visto["d"](inscricao)
    assert chave not in capturado["env"]


def _preparar_execucao(monkeypatch, tmp_path, executar):
    clone = _repo_dir(tmp_path)
    _inscrever_clone(clone)
    monkeypatch.setattr(cli, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(cli, "montar_deps", lambda *a, **k: None)
    monkeypatch.setattr(cli, "executar_inscricao", executar)
    return clone


def test_inscricao_executar_grava_resultado(inscricoes_env, monkeypatch, tmp_path):
    from motor.domain.inscricao import Desfecho, Resultado
    from motor.inscricoes import carregar

    arquivo, _ = inscricoes_env
    clone = _preparar_execucao(
        monkeypatch, tmp_path, lambda deps, versao: Resultado(Desfecho.NADA)
    )
    main(["inscricao", "executar", _Inscr.VERSAO, "--repo", clone])
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
    clone = _preparar_execucao(monkeypatch, tmp_path, bug)
    with pytest.raises(SystemExit):
        main(["inscricao", "executar", _Inscr.VERSAO, "--repo", clone])
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
    _inscrever_clone(_repo_dir(tmp_path))
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
    daemon_app.servir("development", porta)
    assert rodou == [porta]
