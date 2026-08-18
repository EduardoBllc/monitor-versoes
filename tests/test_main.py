"""Testes do composition root.

Os testes de ponta a ponta chamam `main()` de verdade e trocam so as tres
bordas de IO (git, sessao do banco, adapter de estado). Um teste que so
importa helpers nao prova nada sobre a entrada: foi assim que um
`Deps(lock_dir=...)` invalido sobreviveu quatro tasks.
"""

from __future__ import annotations

import contextlib
import datetime
import os
from dataclasses import dataclass

import pytest

import motor.__main__ as cli
from motor.__main__ import _build_parser, _resolver_repo, imprimir_status, main
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.domain.types import RepoInfo, VersionStatus
from motor.errors import MotorError

D = datetime.datetime(2026, 1, 1)


# -- parser -------------------------------------------------------------------


def test_task_source_default_e_tickio():
    args = _build_parser().parse_args(["criar", "1.0.0", "--repo", "."])
    assert args.fonte_flag == "tickio"


def test_fonte_de_tasks_disponivel_em_todos_os_subcomandos():
    # --task-source/--lista vivem no parser pai 'comum': se ficassem so no
    # 'criar', os outros comandos leriam args.lista_manual inexistente —
    # AttributeError com traceback, nao mensagem.
    for comando in ("verificar", "criar", "atualizar", "reconstruir-estado"):
        args = _build_parser().parse_args(
            [comando, "13.34.0", "--repo", "/tmp",
             "--task-source", "manual", "--lista", "x.txt"]
        )
        assert (args.fonte_flag, args.lista_manual) == ("manual", "x.txt")


def test_reconstruir_estado_esta_no_parser():
    acoes = _build_parser()._subparsers._group_actions[0].choices
    assert "reconstruir-estado" in acoes
    assert "reconstruir-lock" not in acoes


def test_comando_desconhecido_sai_com_erro():
    with pytest.raises(SystemExit) as saida:
        main(["inexistente", "13.34.0", "--repo", "/tmp"])
    assert saida.value.code != 0


def test_nao_existe_flag_de_token_do_tickio():
    # autenticacao e por TICKIO_USER/TICKIO_PASSWORD do ambiente: token colado
    # no .env teria de ser refeito a cada expiracao do JWT.
    with pytest.raises(SystemExit):
        _build_parser().parse_args(
            ["criar", "1.0.0", "--repo", ".", "--tickio-token", "xyz"]
        )


# -- impressao ----------------------------------------------------------------


def test_imprimir_status_mostra_as_ambiguas(capsys):
    # tasks_ambiguas derruba o verde; sem imprimi-las o operador ve
    # "verde: False" com todas as secoes vazias e nenhuma explicacao.
    imprimir_status(VersionStatus(estado_integro=True, tasks_ambiguas=["123456"]))

    saida = capsys.readouterr().out
    assert "123456" in saida
    assert "mais de uma versao" in saida


def test_imprimir_status_aponta_sem_entrega_no_banco(capsys):
    imprimir_status(VersionStatus(estado_integro=True, tasks_sem_commits=["123456"]))

    saida = capsys.readouterr().out
    assert "sem_entrega" in saida
    assert "lock" not in saida  # sem_entrega vive no banco, nao num lock


# -- main() ponta a ponta -----------------------------------------------------


def _repo_dir(tmp_path, nome: str = "vendabemweb") -> str:
    caminho = tmp_path / nome
    caminho.mkdir()
    return str(caminho)


def _git() -> FakeGit:
    """m0 e a raiz das versoes; a0 so existe no master (logo, faltante)."""
    git = FakeGit()
    git.add_commit("m0", "", "raiz", D)
    git.add_commit("a0", "m0", "ch123456 alfa", D)
    git.set_branch("master", "a0")
    git.set_branch("origin/master", "a0")
    # 13.33.0 e a base inferida da 13.34.0 (§7)
    for versao in ("13.33.0", "13.34.0"):
        git.set_branch(versao, "m0")
    return git


@pytest.fixture
def bordas(monkeypatch):
    """Troca as tres bordas de IO do composition root e devolve os doubles.

    Todo o resto de main() roda de verdade: parse, resolucao do repo, montagem
    de Deps, escolha da fonte de tasks, despacho e impressao.
    """
    git = _git()
    estado = FakeEstado(
        repos={"vendabemweb": RepoInfo(nome="vendabemweb", tickio_sistema_id=7)}
    )
    monkeypatch.setattr(cli, "new_git_subprocess", lambda repo: git)
    monkeypatch.setattr(cli, "_abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(cli, "PostgresEstado", lambda sessao: estado)
    return git, estado


def test_verificar_ponta_a_ponta_com_lista_manual(bordas, tmp_path, capsys):
    git, estado = bordas
    lista = tmp_path / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")

    main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path),
          "--task-source", "manual", "--lista", str(lista)])

    saida = capsys.readouterr().out
    assert "verde:" in saida
    # a0 saiu como faltante: Deps foi montada com o repo canonico e o estado,
    # e o verificar rodou de ponta a ponta em cima deles.
    assert "a0" in saida
    assert git.fetched == ["origin"]


def test_repo_alias_vira_o_nome_canonico_na_deps(bordas, tmp_path):
    git, estado = bordas
    estado.aliases["vbweb"] = "vendabemweb"
    lista = tmp_path / "lista.txt"
    lista.write_text("", encoding="utf-8")

    main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path, "vbweb"),
          "--task-source", "manual", "--lista", str(lista)])

    # gravou sob o nome canonico, nao sob o basename do diretorio
    assert ("vendabemweb", "13.34.0") in estado.versoes


def test_tickio_recebe_o_sistema_id_do_repo(bordas, tmp_path, monkeypatch):
    monkeypatch.setenv("TICKIO_BASE_URL", "http://tickio.exemplo")
    monkeypatch.setenv("TICKIO_USER", "u")
    monkeypatch.setenv("TICKIO_PASSWORD", "p")
    construidos: list = []

    @dataclass
    class TickioSpy:
        base_url: str
        usuario: str
        senha: str
        sistema_id: int

        def __post_init__(self) -> None:
            construidos.append(self)

        def fetch(self, versao: str) -> list[str]:
            return []

    monkeypatch.setattr(cli, "TickioRest", TickioSpy)

    # sem --task-source: prova que o default do CLI e tickio
    main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert len(construidos) == 1
    # 7 e o tickio_sistema_id da linha `repo`, lida pelo adapter de estado
    assert construidos[0].sistema_id == 7
    assert construidos[0].base_url == "http://tickio.exemplo"
    assert (construidos[0].usuario, construidos[0].senha) == ("u", "p")


def test_reconstruir_estado_ponta_a_ponta(bordas, tmp_path, capsys):
    git, estado = bordas
    # commit na branch da versao sem ch<num> na mensagem: orfao
    git.add_commit("p1", "m0", "ajuste sem numero", D)
    git.set_branch("13.34.0", "p1")

    main(["reconstruir-estado", "13.34.0", "--repo", _repo_dir(tmp_path)])

    saida = capsys.readouterr().out
    assert "status: PENDING_JUDGMENT, orfaos: 1" in saida
    assert "p1" in saida and "sem ch<num> na mensagem" in saida


def test_criar_ponta_a_ponta(bordas, tmp_path, capsys):
    lista = tmp_path / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")

    main(["criar", "13.35.0", "--repo", _repo_dir(tmp_path),
          "--task-source", "manual", "--lista", str(lista)])

    saida = capsys.readouterr().out
    assert "cherry-picks aplicados" in saida
    assert "a0" in saida and "concluido" in saida


def test_atualizar_abort_ponta_a_ponta(bordas, tmp_path, capsys):
    # pina o despacho de --abort: a flag e lida como args.abortar, e o comando
    # nem chega a precisar de fonte de tasks.
    git, _ = bordas

    main(["atualizar", "13.34.0", "--repo", _repo_dir(tmp_path), "--abort"])

    assert capsys.readouterr().out == "abortado\n"
    assert git.removed_worktrees == ["13.34.0"]


def test_manual_sem_lista_sai_1(bordas, tmp_path, capsys):
    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path),
              "--task-source", "manual"])

    assert saida.value.code == 1
    assert "--lista" in capsys.readouterr().err


def test_erro_operacional_sai_1_sem_traceback(bordas, tmp_path, monkeypatch, caplog):
    def sem_banco():
        raise MotorError("banco inacessivel na fixture")

    monkeypatch.setattr(cli, "_abrir_sessao", sem_banco)

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert saida.value.code == 1
    assert caplog.messages == ["banco inacessivel na fixture"]
    assert "Traceback" not in caplog.text


def test_bug_sai_1_com_traceback(bordas, tmp_path, monkeypatch, caplog):
    def bug():
        raise RuntimeError("isto e um bug")

    monkeypatch.setattr(cli, "_abrir_sessao", bug)

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert saida.value.code == 1
    assert "Traceback" in caplog.text


# -- _resolver_repo -----------------------------------------------------------


def test_resolver_repo_caminho_literal(tmp_path):
    alvo = tmp_path / "meurepo"
    alvo.mkdir()
    assert _resolver_repo(str(alvo)) == str(alvo)


def test_resolver_repo_via_projects_dir(tmp_path, monkeypatch):
    projetos = tmp_path / "projetos"
    (projetos / "vendabemweb").mkdir(parents=True)
    monkeypatch.setenv("PROJECTS_DIR", str(projetos))

    resolvido = _resolver_repo("vendabemweb")

    assert resolvido == os.path.join(str(projetos), "vendabemweb")


def test_resolver_repo_nao_encontrado(tmp_path, monkeypatch):
    monkeypatch.delenv("PROJECTS_DIR", raising=False)
    with pytest.raises(SystemExit):
        _resolver_repo(str(tmp_path / "nao-existe"))
