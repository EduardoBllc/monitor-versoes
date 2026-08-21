"""Transcrição de internal/adapters/git/subprocess_test.go.

Usa git real em tmp_path (o Go não pula esses testes, então este também não).
"""

from __future__ import annotations

import os
import subprocess

import pytest

from motor.adapters.git.subprocess import (
    GitSubprocess,
    _progresso_de_quadro,
    _quadros,
    new_git_subprocess,
)
from motor.domain.version import versoes_abertas
from motor.errors import MotorError
from motor.progresso import Progresso
from motor.ports import CherryPickOutcome


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "teste",
            "GIT_AUTHOR_EMAIL": "teste@example.com",
            "GIT_COMMITTER_NAME": "teste",
            "GIT_COMMITTER_EMAIL": "teste@example.com",
        }
    )
    return env


def _run_git(dir_: str, *args: str) -> None:
    proc = subprocess.run(
        ["git", *args], cwd=dir_, env=_git_env(), capture_output=True, text=True
    )
    if proc.returncode != 0:
        pytest.fail(f"git {args}: {proc.returncode}: {proc.stdout}{proc.stderr}")


def _config_identidade_local(dir_: str) -> None:
    # ponytail: config local (nao --global) pra nao depender do ambiente ter
    # git user.name/email configurados - GitSubprocess nao propaga os envs
    # GIT_AUTHOR_*/GIT_COMMITTER_* pros comandos que ele mesmo dispara (só
    # este helper de teste os usa), entao a identidade precisa vir do
    # repo-config (compartilhado com as worktrees via git dir comum).
    _run_git(dir_, "config", "user.name", "teste")
    _run_git(dir_, "config", "user.email", "teste@example.com")


def init_repo_de_teste(tmp_path) -> str:
    dir_ = str(tmp_path)
    _run_git(dir_, "init", "-b", "master")
    _config_identidade_local(dir_)
    (tmp_path / "arquivo.txt").write_text("v1\n")
    _run_git(dir_, "add", "arquivo.txt")
    _run_git(dir_, "commit", "-m", "fix: ch255514 corrige logs")
    return dir_


def test_git_subprocess_remote_url(tmp_path):
    repo_dir = init_repo_de_teste(tmp_path)
    _run_git(repo_dir, "remote", "add", "origin", "git@bitbucket.org:acme/monitor.git")

    g = new_git_subprocess(repo_dir)

    assert g.remote_url("origin") == "git@bitbucket.org:acme/monitor.git"


_FALHA_AUTENTICACAO = (
    "fatal: Authentication failed for "
    "'https://usuario:token-secreto@bitbucket.org/acme/monitor.git'"
)


def _assertar_sem_credencial(mensagem: str) -> None:
    assert "bitbucket.org/acme/monitor.git" in mensagem
    assert "token-secreto" not in mensagem
    assert "usuario" not in mensagem


def test_git_subprocess_erro_nao_expoe_credencial_da_url(tmp_path, monkeypatch):
    def falhar(*args, **kwargs):
        return subprocess.CompletedProcess(args, 128, "", _FALHA_AUTENTICACAO)

    monkeypatch.setattr(subprocess, "run", falhar)

    with pytest.raises(MotorError) as erro:
        GitSubprocess(str(tmp_path)).remote_branch_exists("origin", "13.34.0")

    _assertar_sem_credencial(str(erro.value))


def test_git_subprocess_erro_com_progresso_nao_expoe_credencial_da_url(
    tmp_path, monkeypatch
):
    """Os tres comandos que carregam credencial — fetch, push e pull — sao
    justamente os que passam pelo runner com progresso, entao a mascara tem de
    valer nele tambem, e nao so no `_run`.
    """

    class PopenFalso:
        def __init__(self, *args, **kwargs):
            leitura, escrita = os.pipe()
            os.write(escrita, _FALHA_AUTENTICACAO.encode())
            os.close(escrita)
            self.stdout = os.fdopen(leitura, "rb")

        def wait(self) -> int:
            return 128

    monkeypatch.setattr(subprocess, "Popen", PopenFalso)

    with pytest.raises(MotorError) as erro:
        GitSubprocess(str(tmp_path)).push_branch("origin", "13.34.0")

    _assertar_sem_credencial(str(erro.value))


def test_git_subprocess_write_file_noop_quando_conteudo_igual(tmp_path):
    """Cobre o achado da tarefa 21: WriteFile grava, `git add` e comita sem
    checar se há algo de fato staged. Quando o conteúdo escrito é
    byte-idêntico ao já commitado (ex: Criar grava o lock inicial,
    atualizar tenta gravar o mesmo lock de novo por não ter Faltantes),
    `git commit` sem --allow-empty falha com "nothing to commit, working
    tree clean" e aborta a operação inteira.
    """
    repo_dir = init_repo_de_teste(tmp_path)

    g = new_git_subprocess(repo_dir)
    g.worktree_add("13.8.0", "master")

    g.write_file("13.8.0", "VERSAO.lock", b"{}", "lock inicial")
    primeiro_hash = g._output(g._worktree_dir("13.8.0"), "rev-parse", "HEAD")

    # 2a chamada com o MESMO conteudo: nada staged apos o `git add`, entao
    # `git commit` deve ser evitado (sem --allow-empty ele falharia aqui).
    g.write_file("13.8.0", "VERSAO.lock", b"{}", "lock inalterado")
    segundo_hash = g._output(g._worktree_dir("13.8.0"), "rev-parse", "HEAD")
    assert segundo_hash == primeiro_hash, (
        f"2a WriteFile com conteudo igual criou commit novo: HEAD mudou de "
        f"{primeiro_hash} para {segundo_hash}"
    )
    conteudo = g.read_file("13.8.0", "VERSAO.lock")
    assert conteudo == b"{}"

    # 3a chamada com conteudo DIFERENTE: precisa gerar commit real, provando
    # que a checagem de "nada staged" nao suprime commits legitimos.
    g.write_file("13.8.0", "VERSAO.lock", b'{"v":1}', "lock atualizado")
    terceiro_hash = g._output(g._worktree_dir("13.8.0"), "rev-parse", "HEAD")
    assert terceiro_hash != segundo_hash, (
        "3a WriteFile com conteudo diferente nao criou commit novo"
    )
    conteudo3 = g.read_file("13.8.0", "VERSAO.lock")
    assert conteudo3 == b'{"v":1}'


def test_git_subprocess_search_commits_ignora_merge(tmp_path):
    """Merge commits do PR (ex.: "Merged in VB-2687 (pull request #948)")
    citam a task no texto auto-gerado pelo Bitbucket so por causa do nome da
    branch, mas nao carregam mudanca propria pra aplicar - search_commits nao
    deve traze-los como candidatos (senao viram faltantes/conflitantes
    fantasmas em TargetResolver).
    """
    dir_ = str(tmp_path)
    _run_git(dir_, "init", "-b", "master")
    _config_identidade_local(dir_)
    (tmp_path / "arquivo.txt").write_text("v1\n")
    _run_git(dir_, "add", "arquivo.txt")
    _run_git(dir_, "commit", "-m", "base")

    _run_git(dir_, "checkout", "-b", "VB-2687")
    (tmp_path / "arquivo.txt").write_text("v2\n")
    _run_git(dir_, "add", "arquivo.txt")
    _run_git(dir_, "commit", "-m", "ch256308. corrige algo")

    _run_git(dir_, "checkout", "master")
    _run_git(dir_, "merge", "--no-ff", "VB-2687", "-m", "Merged in VB-2687 (pull request #948)")

    g = new_git_subprocess(dir_)
    candidatos = g.search_commits(["ch256308", "VB-2687"], "master")

    msgs = [c.msg.splitlines()[0] for c in candidatos]
    assert msgs == ["ch256308. corrige algo"], (
        f"esperava so o commit de conteudo, veio {msgs!r}"
    )


def test_git_subprocess_list_version_branches_branch_e_tag_homonimos(tmp_path):
    """Quando uma versao tem tag com o mesmo nome da branch (ex.: fechada mas
    ainda nao limpa), `%(refname:short)` fica ambigua entre refs/heads/X e
    refs/tags/X e o git devolve "heads/X" em vez de "X" - a branch some da
    lista por nao bater mais no padrao \\d+\\.\\d+\\.\\d+. list_version_branches
    precisa continuar enxergando a branch (e tambem versoes so-com-tag, cuja
    branch ja foi apagada apos o fechamento).
    """
    dir_ = str(tmp_path)
    _run_git(dir_, "init", "-b", "master")
    _config_identidade_local(dir_)
    (tmp_path / "arquivo.txt").write_text("v1\n")
    _run_git(dir_, "add", "arquivo.txt")
    _run_git(dir_, "commit", "-m", "base")

    _run_git(dir_, "branch", "13.13.0")
    _run_git(dir_, "tag", "13.13.0")

    (tmp_path / "arquivo.txt").write_text("v2\n")
    _run_git(dir_, "add", "arquivo.txt")
    _run_git(dir_, "commit", "-m", "so tag, branch ja apagada")
    _run_git(dir_, "tag", "13.12.0")

    g = new_git_subprocess(dir_)
    versoes = g.list_version_branches()

    assert "13.13.0" in versoes, f"branch com tag homonima sumiu da lista: {versoes!r}"
    assert "13.12.0" in versoes, f"versao so-com-tag sumiu da lista: {versoes!r}"


def test_quadros_separa_por_cr_e_traduz_a_fase():
    """O git separa os quadros de progresso com `\\r`; um `readline` leria o
    fetch inteiro como uma linha so e o painel nunca sairia do zero.
    """
    r, w = os.pipe()
    os.write(w, b"remote: Counting objects:  25% (1/4)\rremote: Counting objects: 100% (4/4)\n")
    os.write(w, b"Receiving objects:  50% (3/6)\rFrom /tmp/origem\n")
    # O checkout do `worktree add` conta arquivo, e num pipe, sem --progress.
    os.write(w, b"Updating files:  97% (29100/30000)\r")
    os.close(w)

    quadros = list(_quadros(r))
    relatos = [p for p in map(_progresso_de_quadro, quadros) if p is not None]

    assert relatos == [
        Progresso("contando objetos", 1, 4),
        Progresso("contando objetos", 4, 4),
        Progresso("recebendo objetos", 3, 6),
        Progresso("escrevendo os arquivos da worktree", 29100, 30000),
    ], f"quadros lidos: {quadros!r}"


def test_git_subprocess_fetch_relata_o_progresso(tmp_path):
    """O fetch e a espera mais longa do motor — e a unica que o proprio git sabe
    contar, com `--progress`. Sem isso o painel fica so com o pulso.
    """
    origem = tmp_path / "origem"
    origem.mkdir()
    _run_git(str(origem), "init", "-b", "master")
    _config_identidade_local(str(origem))
    (origem / "arquivo.txt").write_text("v1\n")
    _run_git(str(origem), "add", "arquivo.txt")
    _run_git(str(origem), "commit", "-m", "base")

    clone = tmp_path / "clone"
    clone.mkdir()
    _run_git(str(clone), "init", "-b", "master")
    _config_identidade_local(str(clone))
    _run_git(str(clone), "remote", "add", "origin", str(origem))

    relatos: list[Progresso] = []
    new_git_subprocess(str(clone), progresso=relatos.append).fetch("origin")

    assert relatos, "o fetch nao relatou fase nenhuma"
    assert all(p.total > 0 for p in relatos), f"fase sem contagem: {relatos!r}"
    assert all(p.fase == p.fase.lower() for p in relatos), (
        f"fase nao traduzida: {relatos!r}"
    )


def test_git_subprocess_versao_so_como_ref_de_rastreamento_e_vista_como_aberta(tmp_path):
    """`git fetch origin` cria refs/remotes/origin/X e NENHUM head local (tag
    chega por tag-following, branch nao). Sem refs/remotes/ na varredura, uma
    versao aberta e empurrada de outra maquina fica invisivel mesmo depois do
    fetch: `versoes_abertas` viraria uma visao local do conjunto aberto e
    `fontes_de_alvo` omitiria essa versao em silencio (spec §2).
    """
    origem = tmp_path / "origem"
    origem.mkdir()
    _run_git(str(origem), "init", "-b", "master")
    _config_identidade_local(str(origem))
    (origem / "arquivo.txt").write_text("v1\n")
    _run_git(str(origem), "add", "arquivo.txt")
    _run_git(str(origem), "commit", "-m", "base")
    _run_git(str(origem), "branch", "13.35.0")

    clone = tmp_path / "clone"
    clone.mkdir()
    _run_git(str(clone), "init", "-b", "master")
    _config_identidade_local(str(clone))
    _run_git(str(clone), "remote", "add", "origin", str(origem))

    g = new_git_subprocess(str(clone))
    g.fetch("origin")

    # A premissa do teste, nao um detalhe: se o fetch criasse head local o
    # teste passaria sem provar nada sobre refs/remotes/.
    refs = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname)"],
        cwd=str(clone),
        capture_output=True,
        text=True,
    ).stdout
    assert "refs/heads/13.35.0" not in refs, f"o fetch criou head local: {refs!r}"
    assert "refs/remotes/origin/13.35.0" in refs, f"refs apos o fetch: {refs!r}"

    assert "13.35.0" in g.list_version_branches()
    assert versoes_abertas(g.list_version_branches(), g.list_version_tags()) == [
        "13.35.0"
    ]


def test_git_subprocess_commits_meta_concorda_com_commit_meta(tmp_path):
    """O lote existe para substituir `commit_meta` em laco — se divergir num
    campo, a consulta de versao passa a mostrar outra coisa que a verificacao.
    """
    repo_dir = init_repo_de_teste(tmp_path)
    (tmp_path / "arquivo.txt").write_text("v2\n")
    _run_git(repo_dir, "commit", "-am", "ch123456 segundo")
    (tmp_path / "arquivo.txt").write_text("v3\n")
    _run_git(repo_dir, "commit", "-am", "ch654321 terceiro")

    g = new_git_subprocess(repo_dir)
    hashes = [c.hash_origem for c in g.commits_in_range("master~2", "master")]
    assert len(hashes) == 2

    lote = g.commits_meta(hashes)

    assert set(lote) == set(hashes)
    for h in hashes:
        assert lote[h] == g.commit_meta(h)


def test_git_subprocess_commits_meta_ignora_hash_ausente_e_lote_vazio(tmp_path):
    """Hash que o repo nao tem (rebase, gc) nao pode derrubar o lote — e lote
    vazio nao pode virar `git log` sem revisao, que assume HEAD.
    """
    repo_dir = init_repo_de_teste(tmp_path)
    g = new_git_subprocess(repo_dir)
    existente = g.resolve_ref("master")
    ausente = "0" * 40

    assert set(g.commits_meta([existente, ausente])) == {existente}
    assert g.commits_meta([ausente]) == {}
    assert g.commits_meta([]) == {}


def test_git_subprocess_commits_meta_nao_anda_pelos_ancestrais(tmp_path):
    """`git log <hash>` sem `--no-walk` devolveria o historico inteiro a partir
    dele — o lote tem de devolver so o que foi pedido.
    """
    repo_dir = init_repo_de_teste(tmp_path)
    (tmp_path / "arquivo.txt").write_text("v2\n")
    _run_git(repo_dir, "commit", "-am", "ch123456 segundo")

    g = new_git_subprocess(repo_dir)
    tip = g.resolve_ref("master")

    lote = g.commits_meta([tip])

    assert set(lote) == {tip}
    assert lote[tip].parent != "", "esperava o primeiro pai preenchido"


def test_git_subprocess_resolve_ref_descasca_tag_anotada(tmp_path):
    """As tags de release deste projeto sao anotadas: `rev-parse refs/tags/X`
    devolve o SHA do OBJETO DE TAG, nao do commit. Sem descascar, o
    BaseResolver gravaria esse SHA em versao.base_commit — coluna de auditoria
    que entao nao nomeia commit nenhum — e commit_meta devolveria
    "tag X\\nTagger: ...".
    """
    repo_dir = init_repo_de_teste(tmp_path)
    _run_git(repo_dir, "tag", "-a", "13.34.0", "-m", "release 13.34.0")

    g = new_git_subprocess(repo_dir)
    commit_de_master = g.resolve_ref("master")

    # Sem isto o teste seria vacuo com tag leve, em que os dois SHAs coincidem.
    sha_do_objeto_de_tag = subprocess.run(
        ["git", "rev-parse", "refs/tags/13.34.0"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert sha_do_objeto_de_tag != commit_de_master, "tag nao ficou anotada"

    assert g.resolve_ref("refs/tags/13.34.0") == commit_de_master
    # e o que sai serve como commit de verdade (e o que BaseResolver grava)
    meta = g.commit_meta(g.resolve_ref("refs/tags/13.34.0"))
    assert meta.hash_origem == commit_de_master
    assert "Tagger" not in meta.msg


def test_git_subprocess_worktree_cherry_pick_e_arquivo(tmp_path):
    repo_dir = init_repo_de_teste(tmp_path)

    g = new_git_subprocess(repo_dir)
    tip = g.resolve_ref("master")

    g.worktree_add("13.7.0", "master")

    g.write_file("13.7.0", "VERSAO.lock", b"{}", "lock inicial")
    conteudo = g.read_file("13.7.0", "VERSAO.lock")
    assert conteudo == b"{}"

    ok = g.is_ancestor(tip, "13.7.0")
    assert ok, "esperava tip de master como ancestral de 13.7.0"

    existe = g.tag_exists("13.7.0")
    assert not existe, "nao esperava tag 13.7.0 ainda"


def test_git_subprocess_use_worktree_adota_branch_existente(tmp_path):
    """Branch de versao criada por fora do motor (ex: manualmente no
    Bitbucket) nunca passou por `worktree_add` - use_worktree precisa adotar
    a branch existente em vez de exigir que a worktree ja esteja em disco.
    """
    repo_dir = init_repo_de_teste(tmp_path)
    _run_git(repo_dir, "branch", "14.0.0")

    g = new_git_subprocess(repo_dir)
    assert not os.path.exists(g._worktree_dir("14.0.0"))

    g.use_worktree("14.0.0")

    assert os.path.exists(g._worktree_dir("14.0.0"))
    assert g.resolve_ref("14.0.0") == g.resolve_ref("master")


def test_git_subprocess_list_version_tags(tmp_path):
    """list_version_tags devolve so tags (nao branches) no formato X.Y.Z.
    Diferente de list_version_branches que inclui heads tambem.
    Cobre todos os casos: tag-only, branch-only, both, non-version.
    """
    dir_ = str(tmp_path)
    _run_git(dir_, "init", "-b", "master")
    _config_identidade_local(dir_)
    (tmp_path / "arquivo.txt").write_text("v1\n")
    _run_git(dir_, "add", "arquivo.txt")
    _run_git(dir_, "commit", "-m", "base")

    # Case 1: Tag no formato X.Y.Z (tag-only)
    _run_git(dir_, "tag", "13.33.0")

    # Case 2: Branch de versao sem tag (branch-only)
    _run_git(dir_, "branch", "13.34.0")

    # Case 3: Branch com tag homonima (both branch and tag)
    _run_git(dir_, "branch", "13.36.0")
    _run_git(dir_, "tag", "13.36.0")

    # Case 4: Outra tag no formato X.Y.Z (tag-only)
    _run_git(dir_, "tag", "13.35.0")

    # Case 5: Tags nao-version (nao devem aparecer)
    _run_git(dir_, "tag", "v1.0")
    _run_git(dir_, "tag", "release-2024-01")

    g = new_git_subprocess(dir_)
    tags = g.list_version_tags()
    branches = g.list_version_branches()

    # Apenas tags X.Y.Z aparecem em list_version_tags
    assert tags == ["13.33.0", "13.35.0", "13.36.0"], f"tags = {tags!r}"

    # Branch-only aparecem em list_version_branches mas nao em list_version_tags
    assert "13.34.0" in branches, f"branch 13.34.0 deve estar em branches: {branches!r}"
    assert "13.34.0" not in tags, f"branch 13.34.0 nao deve estar em tags: {tags!r}"

    # Branch+tag aparecem em ambos, mas list_version_tags deve devolver exatamente uma vez
    assert "13.36.0" in branches, f"13.36.0 deve estar em branches: {branches!r}"
    assert tags.count("13.36.0") == 1, f"13.36.0 deve aparecer exatamente uma vez em tags: {tags!r}"

    # Non-version tags nao aparecem em nenhum
    assert "v1.0" not in tags, f"tag v1.0 nao deve estar em tags: {tags!r}"
    assert "release-2024-01" not in tags, f"tag release-2024-01 nao deve estar em tags: {tags!r}"
    assert "v1.0" not in branches, f"tag v1.0 nao deve estar em branches: {branches!r}"


def test_git_subprocess_use_worktree_falha_quando_branch_nao_existe(tmp_path):
    repo_dir = init_repo_de_teste(tmp_path)
    g = new_git_subprocess(repo_dir)

    with pytest.raises(Exception):
        g.use_worktree("99.0.0")


def test_git_subprocess_cherry_pick_x_rerere_auto_resolvido(tmp_path):
    """Cobre o achado crítico da revisão da tarefa 18: quando
    rerere.autoUpdate resolve e re-stagea o conflito sozinho, `git
    cherry-pick` ainda sai com erro (git nunca chama --continue por conta
    própria) e ConflictedPaths() fica vazio. CherryPickX precisa classificar
    isso como (Conflito, nil) - não como erro - usando PendingCherryPick
    (CHERRY_PICK_HEAD) em vez de ConflictedPaths para decidir.
    """
    dir_ = str(tmp_path)
    _run_git(dir_, "init", "-b", "master")
    _config_identidade_local(dir_)
    (tmp_path / "arquivo.txt").write_text("linha1\nlinha2\nlinha3\n")
    _run_git(dir_, "add", "arquivo.txt")
    _run_git(dir_, "commit", "-m", "base")

    g = new_git_subprocess(dir_)
    base_hash = g.resolve_ref("master")

    (tmp_path / "arquivo.txt").write_text("linha1\nlinha2-X\nlinha3\n")
    _run_git(dir_, "add", "arquivo.txt")
    _run_git(dir_, "commit", "-m", "muda linha2 para X")
    commit_x = g.resolve_ref("master")

    # 1a tentativa: conflito real, resolvido a mao - grava a resolucao no rerere.
    g.worktree_add("13.7.0", base_hash)
    g.write_file("13.7.0", "arquivo.txt", b"linha1\nlinha2-Y\nlinha3\n", "muda linha2 para Y")

    outcome = g.cherry_pick_x(commit_x)
    assert outcome == CherryPickOutcome.CONFLITO
    paths = g.conflicted_paths()
    assert len(paths) != 0, "esperava conflito real com arquivo ainda nao resolvido"

    with open(os.path.join(g._worktree_dir("13.7.0"), "arquivo.txt"), "w") as f:
        f.write("linha1\nlinha2-X\nlinha3\n")
    g.continue_cherry_pick()

    # 2a tentativa: mesmo conflito em branch equivalente - rerere.autoUpdate
    # deve resolver e re-stagear o arquivo sozinho, mas o cherry-pick continua
    # pendente (git nao chama --continue por conta propria).
    g.worktree_add("13.7.1", base_hash)
    g.write_file("13.7.1", "arquivo.txt", b"linha1\nlinha2-Y\nlinha3\n", "muda linha2 para Y")

    outcome2 = g.cherry_pick_x(commit_x)
    assert (
        outcome2 == CherryPickOutcome.CONFLITO
    ), "outcome2 deveria ser Conflito (git ainda espera --continue mesmo com rerere resolvendo)"
    paths2 = g.conflicted_paths()
    assert paths2 == [], f"esperava rerere ter resolvido e deixado ConflictedPaths vazio, veio {paths2}"
    _, pendente = g.pending_cherry_pick()
    assert pendente, "esperava cherry-pick pendente apos rerere auto-resolver"

    g.continue_cherry_pick()


def test_git_subprocess_predict_merge_encadeia_commits_dependentes(tmp_path):
    """O segundo commit modifica uma linha criada pelo primeiro.

    Aplicado sozinho contra a base, ele conflita por modify/delete; aplicado
    sobre a arvore prevista do primeiro, deve ser limpo como o cherry-pick real.
    """
    dir_ = str(tmp_path)
    _run_git(dir_, "init", "-b", "master")
    _config_identidade_local(dir_)
    (tmp_path / "arquivo.txt").write_text("base\n")
    _run_git(dir_, "add", "arquivo.txt")
    _run_git(dir_, "commit", "-m", "base")
    g = new_git_subprocess(dir_)
    base = g.resolve_ref("master")

    (tmp_path / "arquivo.txt").write_text("base\nprimeira\n")
    _run_git(dir_, "add", "arquivo.txt")
    _run_git(dir_, "commit", "-m", "primeiro")
    primeiro = g.resolve_ref("master")

    (tmp_path / "arquivo.txt").write_text("base\nsegunda\n")
    _run_git(dir_, "add", "arquivo.txt")
    _run_git(dir_, "commit", "-m", "segundo")
    segundo = g.resolve_ref("master")

    assert g.predict_merge(primeiro, base, segundo).conflita

    primeira = g.predict_merge(base, base, primeiro)
    arvore = primeira.arvore_resultante
    assert arvore, "previsao limpa precisa devolver a arvore para o proximo commit"
    assert not g.predict_merge(primeiro, arvore, segundo).conflita


def test_git_subprocess_versao_de_outro_remoto_nao_entra_no_conjunto_aberto(tmp_path):
    """A varredura e o BaseResolver tem de concordar sobre QUAL remoto conta.

    A varredura le refs/remotes/origin/ e o BaseResolver so tenta
    refs/remotes/origin/<ref>. Se a varredura aceitasse qualquer remoto, uma
    versao visivel so num segundo remoto (upstream, fork, espelho) entraria no
    conjunto aberto, o `inferir_base` a escolheria como base e ela falharia a
    resolver — erro limpo, mas desconcertante, e uma versao fantasma no alvo.
    """
    def _repo_com_branch(caminho, branch=None):
        caminho.mkdir()
        _run_git(str(caminho), "init", "-b", "master")
        _config_identidade_local(str(caminho))
        (caminho / "arquivo.txt").write_text("v1\n")
        _run_git(str(caminho), "add", "arquivo.txt")
        _run_git(str(caminho), "commit", "-m", "base")
        if branch:
            _run_git(str(caminho), "branch", branch)

    _repo_com_branch(tmp_path / "origem", "13.35.0")
    _repo_com_branch(tmp_path / "outro", "13.99.0")

    clone = tmp_path / "clone"
    _repo_com_branch(clone)
    _run_git(str(clone), "remote", "add", "origin", str(tmp_path / "origem"))
    _run_git(str(clone), "remote", "add", "upstream", str(tmp_path / "outro"))

    g = new_git_subprocess(str(clone))
    g.fetch("origin")
    _run_git(str(clone), "fetch", "upstream")

    refs = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname)"],
        cwd=str(clone),
        capture_output=True,
        text=True,
    ).stdout
    # premissa: as duas refs existem, so em remotos diferentes
    assert "refs/remotes/origin/13.35.0" in refs, f"refs: {refs!r}"
    assert "refs/remotes/upstream/13.99.0" in refs, f"refs: {refs!r}"

    assert g.list_version_branches() == ["13.35.0"], (
        f"list_version_branches() = {g.list_version_branches()!r}; 13.99.0 vive so "
        "em refs/remotes/upstream/ e o BaseResolver nunca a resolveria"
    )


def _cenario_culpado(tmp_path, linhas_iniciais: str = "l1\nl2\nl3\nl4\nl5\n"):
    """Monta o cenario de atribuicao de conflito.

    base -> ch200 (mexe linha 3) -> ch300 (mexe linha 5) -> ch400 (mexe linha 3
    de novo). O commit a cherry-pickar e o ch400; o culpado por linha e o ch200,
    e o ch300 e o distrator que so o filtro por linha descarta.
    """
    dir_ = str(tmp_path)
    _run_git(dir_, "init", "-b", "master")
    _config_identidade_local(dir_)
    arquivo = tmp_path / "a.txt"

    arquivo.write_text(linhas_iniciais)
    _run_git(dir_, "add", "a.txt")
    _run_git(dir_, "commit", "-m", "feat: ch100 primeira versao")
    base = _rev(dir_, "HEAD")

    arquivo.write_text(linhas_iniciais.replace("l3\n", "l3-ch200\n"))
    _run_git(dir_, "commit", "-am", "fix: ch200 mexe a linha 3")

    arquivo.write_text(
        linhas_iniciais.replace("l3\n", "l3-ch200\n").replace("l5\n", "l5-ch300\n")
    )
    _run_git(dir_, "commit", "-am", "fix: ch300 mexe a linha 5")
    parent = _rev(dir_, "HEAD")

    arquivo.write_text(
        linhas_iniciais.replace("l3\n", "l3-ch400\n").replace("l5\n", "l5-ch300\n")
    )
    _run_git(dir_, "commit", "-am", "fix: ch400 mexe a linha 3 de novo")
    commit = _rev(dir_, "HEAD")

    return dir_, base, parent, commit


def _rev(dir_: str, ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=dir_, capture_output=True, text=True
    ).stdout.strip()


def test_culpados_por_linha_acha_quem_tocou_as_mesmas_linhas(tmp_path):
    dir_, base, parent, commit = _cenario_culpado(tmp_path)

    g = new_git_subprocess(dir_)
    culpados = g.culpados_por_linha(base, parent, commit, ["a.txt"])

    msgs = [c.msg for c in culpados["a.txt"]]
    assert len(msgs) == 1, f"culpados = {msgs!r}"
    assert "ch200" in msgs[0]


def test_culpados_por_linha_ignora_quem_tocou_outras_linhas(tmp_path):
    dir_, base, parent, commit = _cenario_culpado(tmp_path)

    g = new_git_subprocess(dir_)
    culpados = g.culpados_por_linha(base, parent, commit, ["a.txt"])

    msgs = " ".join(c.msg for c in culpados["a.txt"])
    assert "ch300" not in msgs, (
        f"ch300 mexeu na linha 5, o conflito e na 3; atribuicao por arquivo "
        f"traria ele. culpados = {msgs!r}"
    )


def test_culpados_por_linha_com_insercao_pura(tmp_path):
    """Hunk `@@ -3,0 +4 @@` tem comprimento zero e nao e range valido pro -L."""
    dir_ = str(tmp_path)
    _run_git(dir_, "init", "-b", "master")
    _config_identidade_local(dir_)
    arquivo = tmp_path / "a.txt"

    arquivo.write_text("l1\nl2\nl3\nl4\nl5\n")
    _run_git(dir_, "add", "a.txt")
    _run_git(dir_, "commit", "-m", "feat: ch100 primeira versao")
    base = _rev(dir_, "HEAD")

    arquivo.write_text("l1\nl2\nl3-ch200\nl4\nl5\n")
    _run_git(dir_, "commit", "-am", "fix: ch200 mexe a linha 3")
    parent = _rev(dir_, "HEAD")

    arquivo.write_text("l1\nl2\nl3-ch200\nNOVA\nl4\nl5\n")
    _run_git(dir_, "commit", "-am", "feat: ch400 insere depois da linha 3")
    commit = _rev(dir_, "HEAD")

    g = new_git_subprocess(dir_)
    culpados = g.culpados_por_linha(base, parent, commit, ["a.txt"])

    msgs = [c.msg for c in culpados["a.txt"]]
    assert len(msgs) == 1, f"culpados = {msgs!r}"
    assert "ch200" in msgs[0]


def test_culpados_por_linha_cai_para_o_arquivo_quando_ele_nao_existe_no_parent(tmp_path):
    """Conflito add/add: o commit *cria* o arquivo, entao ele nao existe no
    parent e nao ha linha a rastrear. O culpado e quem o apagou no meio.
    """
    dir_ = str(tmp_path)
    _run_git(dir_, "init", "-b", "master")
    _config_identidade_local(dir_)
    arquivo = tmp_path / "a.txt"

    arquivo.write_text("l1\nl2\n")
    _run_git(dir_, "add", "a.txt")
    _run_git(dir_, "commit", "-m", "feat: ch100 primeira versao")
    base = _rev(dir_, "HEAD")

    _run_git(dir_, "rm", "-q", "a.txt")
    _run_git(dir_, "commit", "-m", "refactor: ch200 apaga o a.txt")
    parent = _rev(dir_, "HEAD")

    arquivo.write_text("novo1\nnovo2\n")
    _run_git(dir_, "add", "a.txt")
    _run_git(dir_, "commit", "-m", "feat: ch400 recria o a.txt")
    commit = _rev(dir_, "HEAD")

    g = new_git_subprocess(dir_)
    culpados = g.culpados_por_linha(base, parent, commit, ["a.txt"])

    msgs = [c.msg for c in culpados["a.txt"]]
    assert len(msgs) == 1, f"culpados = {msgs!r}"
    assert "ch200" in msgs[0]
