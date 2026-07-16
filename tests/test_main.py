import os

import pytest

from motor.__main__ import _build_parser, _resolver_repo


def test_task_source_default_e_rest():
    args = _build_parser().parse_args(["criar", "1.0.0", "--repo", "."])
    assert args.fonte_flag == "rest"


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
