# Redesenho Tickio + Postgres — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trocar o ClickUp pelo Tickio, implementar a distribuição automática de tarefas entre as versões em construção das majors 13 e 14, e mover o estado do `VERSAO.lock` em arquivo para Postgres.

**Architecture:** Portas-e-adaptadores, núcleo puro (já existente). A regra de distribuição entra como três funções puras em `motor/domain/version.py`. O estado vira uma porta nova (`EstadoRepo`) com adapter Postgres (SQLAlchemy) e fake em memória — a suíte continua rodando sem banco e sem rede. Versão com tag é congelada por trigger no banco, não por `if` em Python.

**Tech Stack:** Python 3.14, httpx, SQLAlchemy 2.x, Alembic, psycopg 3, Postgres 18, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-08-07-redesenho-tickio-design.md`

## Global Constraints

- Python `>=3.14` (já em `pyproject.toml`).
- **`motor/domain/` nunca importa `sqlalchemy`.** Modelos ORM vivem só em `motor/adapters/estado/`. Violar isso quebra a suíte sem banco e esvazia a porta `EstadoRepo`.
- **A suíte roda sem git, sem rede e sem banco.** Única exceção: os testes marcados `@pytest.mark.integracao`, que são pulados quando `DATABASE_HOST` não está no ambiente.
- Identidade de tarefa é **só o número do chamado**. Nada de `VB-xxxx`, nada de título.
- Mensagens de erro do usuário em português sem acento (padrão do código atual).
- Toda `MotorError` é mensagem limpa com exit 1; qualquer outra exceção é bug com traceback (`__main__.py:204-209`).
- Ordem de versão é semver sobre `(x, y, z)`.
- Commits em português, prefixo convencional (`feat:`, `fix:`, `refactor:`, `chore:`, `docs:`, `test:`).

## Desvios deliberados da spec

Registrados aqui porque a leitura do código os motivou:

1. **`GitRepo.list_tags()` vira `list_version_tags()`.** Simetria com `list_version_branches()`, que já existe e já filtra pelo formato `X.Y.Z`.
2. **`list_version_branches()` não muda.** Ele já devolve `refs/heads/ ∪ refs/tags/` de propósito (`subprocess.py:333-354`, para o `inferir_base` enxergar versão fechada cuja branch foi apagada). Logo `versoes_abertas(todas, tags) = todas − tags` funciona direto.
3. **`sincronizar_versoes` quebra em `registrar_versao` + `marcar_liberadas` + `versao`.** A assinatura única da spec obrigaria a resolver `base` de toda versão aberta a cada comando. Só a versão operada precisa de `base` — e ela é resolvida **uma vez**, na primeira gravação: recomputar `BaseResolver` a cada run faria a base de uma `X.0.0` seguir o tip atual do `master` em vez do ponto onde a branch foi cortada, e o oráculo passaria a considerar presente tudo que entrou no master depois. É por isso que o código de hoje lê `lock.base.commit` (`verificar.py:86`) em vez de recalcular.

4. **A CLI usa `TICKIO_USER`/`TICKIO_PASSWORD`, não `--tickio-token`.** A spec §4 tem as duas coisas: a seção `TickioRest` decide autenticação por credencial, e a linha "CLI" no fim de §4 ficou com `--tickio-token`, resquício da simetria com o ClickUp. Vale a credencial — um token colado no `.env` precisa ser refeito a cada expiração do JWT.

5. **`FakeGit` fica fiel ao adapter real em dois pontos** (Task 1): `list_version_branches` passa a filtrar pelo formato `X.Y.Z`, e `resolve_ref` passa a aceitar `refs/tags/<X>`. Sem o primeiro, `master` entra no conjunto aberto e `chave("master")` estoura; sem o segundo, o `BaseResolver` (que qualifica com `refs/tags/` em `base_resolver.py:23`) não resolve contra o fake.

## Estrutura de arquivos

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `motor/domain/version.py` | ordem semver, tipo, base, conjunto aberto, fontes do alvo | modificar |
| `motor/domain/types.py` | dataclasses puros do domínio | modificar |
| `motor/domain/commits.py` | regex de chamado, match exato, ordenação | modificar |
| `motor/domain/reconcile.py` | cruzamento alvo × estado × git | modificar |
| `motor/ports.py` | Protocols | modificar |
| `motor/config.py` | `database_url()` a partir do `.env` | **criar** |
| `motor/services/target_resolver.py` | união multi-fonte + ambiguidade | modificar |
| `motor/services/publication_gate.py` | trava de versão publicada | modificar |
| `motor/services/lock_store.py` | store em arquivo | **deletar** |
| `motor/services/reconstrutor.py` | varredura de trailers `base..HEAD` | **criar** (extraído do lock_store) |
| `motor/adapters/estado/models.py` | modelos SQLAlchemy | **criar** |
| `motor/adapters/estado/postgres.py` | `PostgresEstado` | **criar** |
| `motor/adapters/estado/fake.py` | `FakeEstado` em memória | **criar** |
| `motor/adapters/tasksource/tickio.py` | `TickioRest` | **criar** |
| `motor/adapters/tasksource/rest.py` | `ClickUpRest` | **deletar** |
| `motor/adapters/tasksource/{manuallist,fake}.py` | fallback e double | modificar |
| `motor/adapters/commitsource/{grep,chain,bitbucket,fake}.py` | descoberta de commits | modificar |
| `motor/adapters/git/{subprocess,fake}.py` | `list_version_tags` | modificar |
| `motor/engine/{deps,verificar,atualizar,criar}.py` | operações | modificar |
| `motor/engine/reconstruir_lock.py` | → `reconstruir_estado.py` | renomear + modificar |
| `motor/__main__.py` | CLI | modificar |
| `compose.yml`, `.env.example`, `alembic.ini`, `alembic/` | infra | **criar** |
| `ferramenta_versoes_design.md` | desenho antigo | reescrever |

---

### Task 1: Ordem de versão e conjunto de versões em construção

Puramente aditivo — nada existente muda de comportamento, a suíte continua verde do começo ao fim.

**Files:**
- Modify: `motor/domain/version.py`
- Modify: `motor/ports.py` (adicionar `list_version_tags` ao Protocol `GitRepo`)
- Modify: `motor/adapters/git/fake.py:231` (adicionar `list_version_tags`)
- Modify: `motor/adapters/git/subprocess.py:333` (adicionar `list_version_tags`)
- Test: `tests/test_version.py`, `tests/test_git_fake.py`

**Interfaces:**
- Consumes: `_parse_versao(numero) -> tuple[int,int,int]` (já existe em `version.py:9`)
- Produces:
  - `chave(numero: str) -> tuple[int, int, int]`
  - `versoes_abertas(todas: list[str], tags: list[str]) -> list[str]`
  - `fontes_de_alvo(alvo: str, abertas: list[str]) -> list[str]`
  - `GitRepo.list_version_tags(self) -> list[str]`

- [ ] **Step 1: Escrever os testes que falham**

Adicionar ao fim de `tests/test_version.py`:

```python
from motor.domain.version import chave, fontes_de_alvo, versoes_abertas


def test_chave_ordena_semver():
    assert chave("13.33.1") < chave("13.34.0")
    assert chave("13.34.0") < chave("14.0.0")
    assert chave("14.0.0") < chave("14.0.1")
    assert chave("14.0.1") < chave("14.1.0")
    # ordem lexicografica erraria aqui: "13.9.0" > "13.10.0" como texto
    assert chave("13.9.0") < chave("13.10.0")


def test_versoes_abertas_e_branch_sem_tag():
    todas = ["13.33.0", "13.33.1", "13.34.0", "14.0.0"]
    tags = ["13.33.0"]
    assert versoes_abertas(todas, tags) == ["13.33.1", "13.34.0", "14.0.0"]


def test_versoes_abertas_ordena_por_semver_nao_por_texto():
    todas = ["13.10.0", "13.9.0"]
    assert versoes_abertas(todas, []) == ["13.9.0", "13.10.0"]


def test_versoes_abertas_sem_nenhuma_aberta():
    assert versoes_abertas(["13.33.0"], ["13.33.0"]) == []


# Cenario canonico da spec §2. Cada linha e um passo do fluxo real.
CENARIO = [
    # (alvo, abertas, fontes esperadas)
    ("13.34.0", ["13.33.1", "13.34.0", "14.0.0"], ["13.33.1", "13.34.0"]),
    ("14.0.0", ["13.33.1", "13.34.0", "14.0.0"], ["13.33.1", "13.34.0", "14.0.0"]),
    ("13.33.1", ["13.33.1", "13.34.0", "14.0.0"], ["13.33.1"]),
    # passo 3: 13.34.0 liberada, 13.35.0 inaugurada
    ("13.35.0", ["13.33.1", "13.35.0", "14.0.0"], ["13.33.1", "13.35.0"]),
    ("14.0.0", ["13.33.1", "13.35.0", "14.0.0"], ["13.33.1", "13.35.0", "14.0.0"]),
    # passo 5: 14.0.0 liberada, 14.0.1 e 14.1.0 inauguradas
    ("13.35.0", ["13.33.1", "13.35.0", "14.0.1", "14.1.0"], ["13.33.1", "13.35.0"]),
    ("14.0.1", ["13.33.1", "13.35.0", "14.0.1", "14.1.0"],
     ["13.33.1", "13.35.0", "14.0.1"]),
    ("14.1.0", ["13.33.1", "13.35.0", "14.0.1", "14.1.0"],
     ["13.33.1", "13.35.0", "14.0.1", "14.1.0"]),
]


@pytest.mark.parametrize("alvo,abertas,esperado", CENARIO)
def test_fontes_de_alvo_cenario_canonico(alvo, abertas, esperado):
    assert fontes_de_alvo(alvo, abertas) == esperado


def test_fontes_de_alvo_inclui_o_proprio_alvo_quando_ainda_nao_tem_branch():
    # `criar` chama antes da branch existir: o alvo entra por uniao
    abertas = ["13.33.1", "14.0.0"]
    assert fontes_de_alvo("14.1.0", sorted({*abertas, "14.1.0"}, key=chave)) == [
        "13.33.1",
        "14.0.0",
        "14.1.0",
    ]
```

Se `tests/test_version.py` ainda não importa `pytest`, adicionar `import pytest` no topo.

Adicionar a `tests/test_git_fake.py`:

```python
def test_fake_list_version_tags_so_devolve_tags():
    git = FakeGit(branches={"13.34.0": "aaa", "14.0.0": "bbb"},
                  tags={"13.34.0": True})
    assert git.list_version_tags() == ["13.34.0"]


def test_fake_list_version_branches_filtra_por_formato():
    # Espelha o adapter real (subprocess.py:352). Sem o filtro, 'master' entra
    # no conjunto e versoes_abertas estoura em chave("master").
    git = FakeGit(branches={"master": "m", "13.34.0": "aaa"}, tags={"13.33.0": True})
    assert git.list_version_branches() == ["13.33.0", "13.34.0"]
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/test_version.py tests/test_git_fake.py -v`
Expected: FAIL com `ImportError: cannot import name 'chave'` e `AttributeError: 'FakeGit' object has no attribute 'list_version_tags'`.

- [ ] **Step 3: Implementar**

Adicionar ao fim de `motor/domain/version.py`:

```python
def chave(numero: str) -> tuple[int, int, int]:
    """Ordem semver. Existe porque ordenacao textual erra em '13.9.0' vs
    '13.10.0' — o unico bug de ordenacao que nao aparece nos testes de
    fixture pequeno e aparece em producao no mes seguinte.
    """
    return _parse_versao(numero)


def versoes_abertas(todas: list[str], tags: list[str]) -> list[str]:
    """Em construcao = existe como versao e nao tem tag homonima.

    `todas` vem de GitRepo.list_version_branches(), que ja devolve
    refs/heads/ UNIAO refs/tags/ filtrado por X.Y.Z; `tags` vem de
    list_version_tags(). A diferenca e o conjunto aberto.
    """
    return sorted(set(todas) - set(tags), key=chave)


def fontes_de_alvo(alvo: str, abertas: list[str]) -> list[str]:
    """Versoes cujas tarefas caem no alvo: toda aberta <= alvo, alvo incluso.

    E a regra de distribuicao vista pelo lado da versao (spec §2).
    """
    k = chave(alvo)
    return [v for v in abertas if chave(v) <= k]
```

Adicionar ao Protocol `GitRepo` em `motor/ports.py`, logo depois de `list_version_branches` (linha 145):

```python
    def list_version_tags(self) -> list[str]:
        """Tags no formato X.Y.Z. Versao com tag = liberada (§6)."""
        ...
```

Em `motor/adapters/git/fake.py`, substituir `list_version_branches` (linha 231) e adicionar `list_version_tags`. O `import re` e a constante vão no topo do arquivo:

```python
_PADRAO_VERSAO = re.compile(r"^\d+\.\d+\.\d+$")
```

```python
    def list_version_branches(self) -> list[str]:
        # Espelha o adapter real: heads UNIAO tags, filtrado por X.Y.Z. Sem o
        # filtro, 'master' entra no conjunto e versoes_abertas estoura em
        # chave("master") — o fake nao pode ser mais permissivo que o real.
        return sorted(
            {n for n in (*self.branches, *self.tags) if _PADRAO_VERSAO.match(n)}
        )

    def list_version_tags(self) -> list[str]:
        return sorted(
            t
            for t, existe in self.tags.items()
            if existe and _PADRAO_VERSAO.match(t)
        )
```

E fazer `resolve_ref` (linha 137) aceitar ref qualificada, como o git real: `refs/tags/13.34.0` e `13.34.0` apontam para o mesmo commit quando a tag existe. Sem isso, o `BaseResolver` (que qualifica com `refs/tags/` em `base_resolver.py:23`) e o congelamento da Task 9 quebram contra o fake:

```python
    def resolve_ref(self, ref: str) -> str:
        nome = ref.removeprefix("refs/tags/").removeprefix("refs/heads/")
        if nome in self.branches:
            return self.branches[nome]
        if nome in self.commits:
            return nome
        raise MotorError(f"ref {ref} nao encontrada")
```

Adicionar em `motor/adapters/git/subprocess.py`, depois de `list_version_branches` (linha 354):

```python
    def list_version_tags(self) -> list[str]:
        # So refs/tags/ — diferente de list_version_branches, que inclui heads
        # tambem de proposito (para inferir_base achar versao fechada cuja
        # branch ja foi apagada).
        out = self._output(
            self.repo_path, "for-each-ref", "--format=%(refname)", "refs/tags/"
        )
        if out == "":
            return []
        nomes = set()
        for linha in out.split("\n"):
            nome = linha.removeprefix("refs/tags/")
            if _PADRAO_BRANCH_VERSAO.match(nome):
                nomes.add(nome)
        return sorted(nomes)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `uv run pytest -v`
Expected: PASS — todos, inclusive os que já existiam.

- [ ] **Step 5: Commit**

```bash
git add motor/domain/version.py motor/ports.py motor/adapters/git/fake.py \
        motor/adapters/git/subprocess.py tests/test_version.py tests/test_git_fake.py
git commit -m "feat(domain): ordem semver e conjunto de versoes em construcao

chave/versoes_abertas/fontes_de_alvo implementam a regra de distribuicao da
spec §2. list_version_tags completa o par com list_version_branches, que ja
devolve heads UNIAO tags de proposito."
```

---

### Task 2: Identidade da tarefa passa a ser só o número do chamado

Mudança mecânica e ampla: remove `VB-xxxx` e título de todo o caminho. Fica numa task só porque dividir deixaria a suíte vermelha no meio.

**Files:**
- Modify: `motor/domain/commits.py:9-30,43-48`
- Modify: `motor/domain/types.py:36-56`
- Modify: `motor/ports.py:27-46`
- Modify: `motor/adapters/tasksource/{manuallist,fake}.py`
- Modify: `motor/adapters/commitsource/{grep,chain,fake,bitbucket}.py`
- Modify: `motor/services/{target_resolver,lock_store}.py`
- Modify: `motor/__main__.py:89-110`
- Delete: `motor/adapters/tasksource/rest.py`, `tests/test_tasksource_rest.py`
- Test: `tests/test_commits.py`, `tests/test_tasksource_manuallist.py`, `tests/test_commitsource_grep.py`, `tests/test_target_resolver.py`

**Interfaces:**
- Consumes: nada de tasks anteriores.
- Produces:
  - `TaskTarget(chamado: str, marcada: str = "", commits: list[CommitRef] = [])`
  - `CommitRef(hash_origem, parent, chamado, commit_date, msg)` — sem `task`, sem `titulo`
  - `TaskSource.fetch(versao: str) -> list[str]`
  - `CommitSource.resolve(chamados: list[str]) -> dict[str, list[CommitRef]]`
  - `match_exato(candidatos: list[CommitRef], chamado: str) -> list[CommitRef]`

- [ ] **Step 1: Escrever os testes que falham**

Substituir o conteúdo de `tests/test_commits.py` por:

```python
from __future__ import annotations

import datetime

from motor.domain.commits import extrair_chamado, match_exato, ordenar_por_data
from motor.domain.types import CommitRef


def test_extrair_chamado():
    assert extrair_chamado("ch123456 corrige calculo de frete") == "123456"
    assert extrair_chamado("sem identificador nenhum") is None


def test_match_exato_respeita_word_boundary():
    candidatos = [
        CommitRef(hash_origem="a", msg="ch5514 alfa"),
        CommitRef(hash_origem="b", msg="ch255514 beta"),
    ]
    achados = match_exato(candidatos, "5514")
    assert [c.hash_origem for c in achados] == ["a"]


def test_match_exato_sem_chamado_nao_casa_nada():
    candidatos = [CommitRef(hash_origem="a", msg="ch5514 alfa")]
    assert match_exato(candidatos, "") == []


def test_ordenar_por_data_asc():
    d = datetime.datetime(2026, 1, 1)
    commits = [
        CommitRef(hash_origem="novo", commit_date=d + datetime.timedelta(days=2)),
        CommitRef(hash_origem="velho", commit_date=d),
    ]
    assert [c.hash_origem for c in ordenar_por_data(commits)] == ["velho", "novo"]
```

Substituir `tests/test_tasksource_manuallist.py` por:

```python
from __future__ import annotations

import pytest

from motor.adapters.tasksource.manuallist import ManualList
from motor.errors import MotorError


def test_manuallist_le_um_chamado_por_linha(tmp_path):
    arquivo = tmp_path / "lista.txt"
    arquivo.write_text("# comentario\n123456\n\n999111\n", encoding="utf-8")

    assert ManualList(caminho=str(arquivo)).fetch("13.34.0") == ["123456", "999111"]


def test_manuallist_recusa_linha_que_nao_e_numero(tmp_path):
    arquivo = tmp_path / "lista.txt"
    arquivo.write_text("VB-2354\n", encoding="utf-8")

    with pytest.raises(MotorError, match="linha invalida"):
        ManualList(caminho=str(arquivo)).fetch("13.34.0")
```

Substituir `tests/test_commitsource_grep.py` por:

```python
from __future__ import annotations

import datetime

from motor.adapters.commitsource.grep import GrepCommitSource
from motor.adapters.git.fake import FakeGit
from motor.domain.types import CommitRef


def _git_com_commits(*mensagens: str) -> FakeGit:
    """FakeGit e baseado em grafo: add_commit encadeia pelo parent e set_branch
    posiciona o tip que search_commits varre."""
    d = datetime.datetime(2026, 1, 1)
    git = FakeGit()
    parent = ""
    for i, msg in enumerate(mensagens):
        hash_ = f"c{i}"
        git.add_commit(hash_, parent, msg, d)
        parent = hash_
    if mensagens:
        git.set_branch("origin/master", f"c{len(mensagens) - 1}")
    return git


def test_grep_agrupa_por_chamado_e_carimba():
    git = _git_com_commits("ch123456 alfa", "ch999111 beta")

    achados = GrepCommitSource(git=git).resolve(["123456", "999111"])

    assert set(achados) == {"123456", "999111"}
    assert [c.hash_origem for c in achados["123456"]] == ["c0"]
    assert achados["123456"][0].chamado == "123456"


def test_grep_nao_casa_chamado_como_substring():
    git = _git_com_commits("ch255514 alfa")

    assert GrepCommitSource(git=git).resolve(["5514"]) == {}


def test_grep_omite_chamado_sem_commit():
    git = _git_com_commits("ajuste sem identificador")

    assert GrepCommitSource(git=git).resolve(["123456"]) == {}
```

`CommitRef` deixa de ser usado neste arquivo — remover o import se o linter reclamar.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/test_commits.py tests/test_tasksource_manuallist.py tests/test_commitsource_grep.py -v`
Expected: FAIL — `TypeError` de assinatura em `match_exato` e `resolve`, e `ManualList` devolvendo `TaskTarget` em vez de `str`.

- [ ] **Step 3: Implementar — domínio**

`motor/domain/commits.py`, substituir das linhas 9 a 48:

```python
padrao_chamado = re.compile(r"\bch(\d+)\b")


def match_exato(candidatos: list[CommitRef], chamado: str) -> list[CommitRef]:
    """Filtra candidatos de grep por word-boundary: `ch5514` nao pode casar
    dentro de `ch255514`. search_commits do GitRepo so traz candidatos brutos.
    """
    if not chamado:
        return []
    padrao = re.compile(r"\bch" + re.escape(chamado) + r"\b")
    return [c for c in candidatos if padrao.search(c.msg)]


def extrair_chamado(msg: str) -> str | None:
    """Acha o numero do chamado na mensagem. Usado na reconstrucao do estado,
    para reagrupar por chamado a partir do trailer de cherry-pick.
    """
    m = padrao_chamado.search(msg)
    return None if m is None else m.group(1)
```

`motor/domain/types.py`, substituir `CommitRef` e `TaskTarget` (linhas 36-56):

```python
@dataclass(frozen=True)
class CommitRef:
    hash_origem: str = ""
    parent: str = ""  # pai do commit na origem (necessario pro predict_merge)
    chamado: str = ""  # "255514"
    commit_date: datetime.datetime = field(default_factory=lambda: datetime.datetime.min)
    msg: str = ""


@dataclass(frozen=True)
class TaskTarget:
    chamado: str = ""  # numero do chamado — identidade unica da tarefa
    marcada: str = ""  # versao para a qual o Tickio marcou
    commits: list[CommitRef] = field(default_factory=list)


# TargetSet = chamado -> TaskTarget resolvido.
TargetSet = dict[str, TaskTarget]
```

- [ ] **Step 4: Implementar — portas e adapters**

`motor/ports.py`, substituir os Protocols `TaskSource` e `CommitSource` (linhas 27-46):

```python
class TaskSource(Protocol):
    """Fonte de tarefas (Tickio, lista manual)."""

    def fetch(self, versao: str) -> list[str]:
        """Numeros de chamado marcados para a versao."""
        ...


class CommitSource(Protocol):
    """Fonte de commits de uma tarefa (grep em master, PR do Bitbucket).

    Recebe o lote inteiro para permitir uma varredura unica — grep com o
    --grep de todos os chamados juntos. Pode omitir chamado sem commit; a
    completude e garantida pelo TargetResolver.
    """

    def resolve(self, chamados: list[str]) -> dict[str, list[CommitRef]]:
        """Acha os commits de cada chamado."""
        ...
```

`motor/adapters/tasksource/manuallist.py`, substituir inteiro:

```python
"""ManualList: fallback sempre disponivel quando a API do Tickio nao responde.

Arquivo texto com um numero de chamado por linha; `#` comenta.
"""

from __future__ import annotations

from dataclasses import dataclass

from motor.errors import MotorError


@dataclass
class ManualList:
    caminho: str

    def fetch(self, versao: str) -> list[str]:
        try:
            with open(self.caminho, encoding="utf-8") as f:
                linhas = f.read().splitlines()
        except OSError as e:
            raise MotorError(f"abrindo lista manual {self.caminho}: {e}") from e

        chamados: list[str] = []
        for linha in linhas:
            linha = linha.strip()
            if linha == "" or linha.startswith("#"):
                continue
            if not linha.isdigit():
                raise MotorError(
                    f"linha invalida em {self.caminho}: {linha!r} "
                    "(esperado so o numero do chamado)"
                )
            chamados.append(linha)
        return chamados
```

`motor/adapters/tasksource/fake.py`, substituir inteiro:

```python
"""Double em memoria de TaskSource, para testes de services/engine."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeTaskSource:
    # versao -> chamados marcados para ela
    chamados: dict[str, list[str]] = field(default_factory=dict)
    err: Exception | None = None

    def fetch(self, versao: str) -> list[str]:
        if self.err is not None:
            raise self.err
        return list(self.chamados.get(versao, []))
```

`motor/adapters/commitsource/grep.py`, substituir o `resolve` (linhas 24-49):

```python
    def resolve(self, chamados: list[str]) -> dict[str, list[CommitRef]]:
        if not chamados:
            return {}

        candidatos = self.git.search_commits(["ch" + c for c in chamados], self.ref)

        resultado: dict[str, list[CommitRef]] = {}
        for chamado in chamados:
            commits = ordenar_por_data(match_exato(candidatos, chamado))
            if not commits:
                continue
            # search_commits nao sabe de chamado — carimba aqui.
            resultado[chamado] = [replace(c, chamado=chamado) for c in commits]
        return resultado
```

Ajustar os imports do topo do arquivo para `from motor.domain.types import CommitRef`.

`motor/adapters/commitsource/chain.py`, substituir o `resolve` (linhas 21-32):

```python
    def resolve(self, chamados: list[str]) -> dict[str, list[CommitRef]]:
        resultado: dict[str, list[CommitRef]] = {}
        pendentes = list(chamados)
        for src in self.sources:
            if not pendentes:
                break
            for chamado, commits in src.resolve(pendentes).items():
                if commits:
                    resultado[chamado] = commits
            pendentes = [c for c in pendentes if c not in resultado]
        return resultado
```

`motor/adapters/commitsource/fake.py`, substituir o `resolve`:

```python
    def resolve(self, chamados: list[str]) -> dict[str, list[CommitRef]]:
        if self.err is not None:
            raise self.err
        return {
            c: self.por_chamado[c] for c in chamados if self.por_chamado.get(c)
        }
```

`motor/adapters/commitsource/bitbucket.py`: trocar a assinatura de `resolve` para `(self, chamados: list[str]) -> dict[str, list[CommitRef]]` e remover toda referência a `t.task`/`t.titulo` — os padrões de busca de PR passam a ser só `ch<chamado>`, e o retorno passa a ser `dict[chamado, commits]` em vez de `TargetSet`.

- [ ] **Step 5: Implementar — call sites**

`motor/services/target_resolver.py`, substituir o `resolve` para casar com as assinaturas novas (a regra de distribuição entra só na Task 3):

```python
    def resolve(self, versao: str) -> TargetSet:
        try:
            chamados = self.tasks.fetch(versao)
        except Exception as e:
            raise MotorError(f"buscando tasks: {e}") from e

        if not chamados:
            return {}

        try:
            achados = self.commits.resolve(chamados)
        except Exception as e:
            raise MotorError(f"buscando commits das tasks: {e}") from e

        return {
            ch: TaskTarget(chamado=ch, marcada=versao, commits=achados.get(ch, []))
            for ch in chamados
        }
```

`motor/services/lock_store.py`: remover o import de `extrair_vb_id`; em `reconstruir` (linhas 131-151), o commit sem `ch<num>` deixa de ter fallback e é ignorado:

```python
            chamado = extrair_chamado(origem_meta.msg)
            if chamado is None:
                continue

            tt = tasks.get(chamado, TaskTarget())
            novo_commit = CommitRef(
                hash_origem=origem_hash,
                chamado=chamado,
                commit_date=origem_meta.commit_date,
                msg=origem_meta.msg,
            )
            tasks[chamado] = replace(
                tt, chamado=chamado, commits=[*tt.commits, novo_commit]
            )
```

E em `ler`/`escrever`, remover `task` e `titulo` do JSON (o arquivo será descartado na Task 9; aqui só precisa compilar e passar nos testes).

`motor/__main__.py:89-110`, a chave de agrupamento vira só o chamado:

```python
def _agrupar_por_task(commits: list) -> dict[str, list]:
    """Agrupa preservando a ordem de 1a aparicao de cada chamado."""
    grupos: dict[str, list] = {}
    for c in commits:
        chave = c.chamado or c.hash_origem[:8]
        grupos.setdefault(chave, []).append(c)
    return grupos
```

Remover o bloco `if getattr(args, "fonte_flag", "rest") == "rest": tasks = ClickUpRest(...)` (linhas 165-171) e deixar só o `ManualList`. Para a CLI não ficar incoerente até a Task 11, o parser acompanha — sem isso o default `"rest"` cairia no ramo do `ManualList` e passaria a exigir `--lista` sem dizer por quê:

```python
    p_criar.add_argument("--task-source", dest="fonte_flag", default="manual",
                         choices=["manual"],
                         help="fonte das tasks (tickio volta na integracao)")
```

Remover também `--clickup-token`. A Task 11 devolve `tickio` como default.

- [ ] **Step 6: Deletar o que era do ClickUp**

```bash
git rm motor/adapters/tasksource/rest.py tests/test_tasksource_rest.py
```

- [ ] **Step 7: Rodar a suíte inteira**

Run: `uv run pytest -v`
Expected: PASS. Se algum teste antigo referenciar `task=` ou `titulo=` em `CommitRef`/`TaskTarget`, atualizá-lo — o campo não existe mais.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: identidade da tarefa passa a ser so o numero do chamado

Sai o custom_id VB-xxxx e o titulo, ambos artefatos do ClickUp. TaskSource
devolve list[str], CommitSource recebe list[str] e devolve dict[chamado,
commits]. ClickUpRest deletado."
```

---

### Task 3: TargetResolver aplica a regra de distribuição

**Files:**
- Modify: `motor/services/target_resolver.py`
- Modify: `motor/domain/types.py` (adicionar `Alvo`)
- Modify: `motor/engine/verificar.py:56-57` (passar `abertas`)
- Test: `tests/test_target_resolver.py`

**Interfaces:**
- Consumes: `fontes_de_alvo` (Task 1); `TaskSource.fetch -> list[str]`, `CommitSource.resolve` (Task 2)
- Produces:
  - `Alvo(tasks: TargetSet, ambiguas: list[str])`
  - `TargetResolver.resolve(alvo: str, abertas: list[str]) -> Alvo`

- [ ] **Step 1: Escrever os testes que falham**

Substituir `tests/test_target_resolver.py` por:

```python
from __future__ import annotations

import datetime

import pytest

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import CommitRef
from motor.errors import MotorError
from motor.services.target_resolver import TargetResolver


def _commit(hash_: str, chamado: str) -> CommitRef:
    return CommitRef(
        hash_origem=hash_, chamado=chamado, commit_date=datetime.datetime(2026, 1, 1)
    )


def test_resolve_une_as_versoes_abertas_menores_ou_iguais():
    # Cenario da spec §2 passo 2: ch123123 marcada p/ 13.33.1 cai na 14.0.0.
    tasks = FakeTaskSource(chamados={"13.33.1": ["123123"], "13.34.0": ["123456"],
                                     "14.0.0": []})
    commits = FakeCommitSource(por_chamado={
        "123123": [_commit("aaa", "123123")],
        "123456": [_commit("bbb", "123456")],
    })
    resolver = TargetResolver(tasks=tasks, commits=commits)

    alvo = resolver.resolve("14.0.0", ["13.33.1", "13.34.0", "14.0.0"])

    assert set(alvo.tasks) == {"123123", "123456"}
    assert alvo.tasks["123123"].marcada == "13.33.1"
    assert alvo.tasks["123456"].marcada == "13.34.0"
    assert alvo.ambiguas == []


def test_resolve_ignora_versao_aberta_maior_que_o_alvo():
    tasks = FakeTaskSource(chamados={"13.33.1": ["123123"], "14.1.0": ["999111"]})
    commits = FakeCommitSource(por_chamado={"123123": [_commit("aaa", "123123")]})
    resolver = TargetResolver(tasks=tasks, commits=commits)

    alvo = resolver.resolve("13.33.1", ["13.33.1", "14.1.0"])

    assert set(alvo.tasks) == {"123123"}


def test_resolve_mantem_chamado_sem_commit_no_alvo():
    # Falso-verde: tarefa marcada sem nenhum commit tem que sobreviver ao alvo
    # para o verificar poder pinta-la vermelha.
    tasks = FakeTaskSource(chamados={"13.34.0": ["123456"]})
    resolver = TargetResolver(tasks=tasks, commits=FakeCommitSource())

    alvo = resolver.resolve("13.34.0", ["13.34.0"])

    assert alvo.tasks["123456"].commits == []


def test_resolve_reporta_chamado_marcado_em_duas_versoes():
    tasks = FakeTaskSource(chamados={"13.33.1": ["123123"], "13.34.0": ["123123"]})
    commits = FakeCommitSource(por_chamado={"123123": [_commit("aaa", "123123")]})
    resolver = TargetResolver(tasks=tasks, commits=commits)

    alvo = resolver.resolve("13.34.0", ["13.33.1", "13.34.0"])

    assert alvo.ambiguas == ["123123"]


def test_resolve_nao_reporta_ambiguidade_por_repeticao_na_mesma_versao():
    tasks = FakeTaskSource(chamados={"13.34.0": ["123123", "123123"]})
    commits = FakeCommitSource(por_chamado={"123123": [_commit("aaa", "123123")]})
    resolver = TargetResolver(tasks=tasks, commits=commits)

    alvo = resolver.resolve("13.34.0", ["13.34.0"])

    assert alvo.ambiguas == []


def test_resolve_propaga_erro_da_fonte_como_motorerror():
    tasks = FakeTaskSource(err=RuntimeError("timeout"))
    resolver = TargetResolver(tasks=tasks, commits=FakeCommitSource())

    with pytest.raises(MotorError, match="buscando tasks"):
        resolver.resolve("13.34.0", ["13.34.0"])
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/test_target_resolver.py -v`
Expected: FAIL com `TypeError: resolve() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Implementar**

Adicionar a `motor/domain/types.py`, depois de `TargetSet`:

```python
@dataclass(frozen=True)
class Alvo:
    """Resultado da resolucao de alvo: as tarefas mais o que deu errado nelas."""

    tasks: TargetSet = field(default_factory=dict)
    # chamado marcado em mais de uma versao — dado inconsistente no Tickio.
    ambiguas: list[str] = field(default_factory=list)
```

Substituir `motor/services/target_resolver.py` inteiro:

```python
"""Resolucao do alvo: aplica a regra de distribuicao da spec §2."""

from __future__ import annotations

from dataclasses import dataclass

from motor.domain.types import Alvo, TaskTarget
from motor.domain.version import fontes_de_alvo
from motor.errors import MotorError
from motor.ports import CommitSource, TaskSource


@dataclass
class TargetResolver:
    tasks: TaskSource
    commits: CommitSource

    def resolve(self, alvo: str, abertas: list[str]) -> Alvo:
        """Une as tarefas de toda versao em construcao <= alvo e casa cada uma
        com seus commits.

        Toda tarefa buscada aparece no resultado mesmo sem commit — e o que
        permite o `verificar` pintar de vermelho a tarefa sem entrega em vez
        de dar falso-verde.
        """
        marcada_de: dict[str, str] = {}
        ambiguas: list[str] = []

        for v in fontes_de_alvo(alvo, abertas):
            try:
                chamados = self.tasks.fetch(v)
            except Exception as e:
                raise MotorError(f"buscando tasks da versao {v}: {e}") from e
            for ch in chamados:
                # `get(ch, v) != v` so acusa quando a versao anterior e OUTRA:
                # repeticao dentro da mesma fetch e dedup, nao ambiguidade.
                if marcada_de.get(ch, v) != v:
                    ambiguas.append(ch)
                marcada_de[ch] = v

        if not marcada_de:
            return Alvo()

        try:
            achados = self.commits.resolve(list(marcada_de))
        except Exception as e:
            raise MotorError(f"buscando commits das tasks: {e}") from e

        return Alvo(
            tasks={
                ch: TaskTarget(chamado=ch, marcada=v, commits=achados.get(ch, []))
                for ch, v in marcada_de.items()
            },
            ambiguas=sorted(set(ambiguas)),
        )
```

O teste `test_resolve_propaga_erro_da_fonte_como_motorerror` espera a mensagem `buscando tasks`; a implementação usa `buscando tasks da versao 13.34.0`, que contém a substring — o `match` do pytest é `re.search`, então passa.

- [ ] **Step 4: Ajustar o chamador**

`motor/engine/verificar.py`, substituir as linhas 56-57:

```python
    abertas = versoes_abertas(deps.git.list_version_branches(), deps.git.list_version_tags())
    resolver = TargetResolver(tasks=deps.tasks, commits=_montar_commit_source(deps))
    resultado_alvo = resolver.resolve(versao, sorted({*abertas, versao}, key=chave))
    alvo = resultado_alvo.tasks
```

Adicionar ao topo: `from motor.domain.version import chave, versoes_abertas`.

- [ ] **Step 5: Rodar a suíte**

Run: `uv run pytest -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add motor/services/target_resolver.py motor/domain/types.py \
        motor/engine/verificar.py tests/test_target_resolver.py
git commit -m "feat(services): TargetResolver aplica a regra de distribuicao

alvo(W) = uniao das tarefas de toda versao em construcao <= W. Chamado
marcado em duas versoes vira Alvo.ambiguas, nao excecao."
```

---

### Task 4: Configuração, compose e dependências

**Files:**
- Create: `motor/config.py`, `compose.yml`, `.env.example`
- Modify: `pyproject.toml`, `.gitignore`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `database_url() -> str`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_config.py`:

```python
from __future__ import annotations

import pytest

from motor.config import database_url
from motor.errors import MotorError

COMPLETO = {
    "DATABASE_HOST": "localhost",
    "DATABASE_PORT": "5433",
    "DATABASE_NAME": "monitor_versoes",
    "DATABASE_USER": "motor",
    "DATABASE_PASSWORD": "motor",
}


def _ambiente(monkeypatch, valores):
    for chave in COMPLETO:
        monkeypatch.delenv(chave, raising=False)
    for chave, valor in valores.items():
        monkeypatch.setenv(chave, valor)


def test_database_url_monta_a_partir_das_partes(monkeypatch):
    _ambiente(monkeypatch, COMPLETO)
    assert database_url() == (
        "postgresql+psycopg://motor:motor@localhost:5433/monitor_versoes"
    )


def test_database_url_escapa_caractere_que_quebraria_a_url(monkeypatch):
    # Sem quote, "s@nha" faria a URL apontar para o host "nha" e o erro
    # observado seria "conexao recusada", nao "senha invalida".
    _ambiente(monkeypatch, {**COMPLETO, "DATABASE_PASSWORD": "s@nha//#"})
    assert "@localhost:5433/" in database_url()
    assert "s%40nha%2F%2F%23" in database_url()


def test_database_url_lista_todas_as_variaveis_faltando(monkeypatch):
    _ambiente(monkeypatch, {"DATABASE_HOST": "localhost"})
    with pytest.raises(MotorError) as erro:
        database_url()
    assert "DATABASE_PORT" in str(erro.value)
    assert "DATABASE_PASSWORD" in str(erro.value)
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'motor.config'`.

- [ ] **Step 3: Implementar**

Criar `motor/config.py`:

```python
"""Configuracao lida do ambiente (.env carregado pelo __main__)."""

from __future__ import annotations

import os
from urllib.parse import quote

from motor.errors import MotorError

_CAMPOS_BANCO = ("HOST", "PORT", "NAME", "USER", "PASSWORD")


def database_url() -> str:
    """Monta a URL do Postgres a partir das partes.

    As partes existem separadas porque o compose.yml le as mesmas variaveis do
    mesmo .env — uma fonte so para aplicacao e container.
    """
    v = {c: os.environ.get(f"DATABASE_{c}", "") for c in _CAMPOS_BANCO}
    if faltando := [f"DATABASE_{c}" for c, valor in v.items() if not valor]:
        raise MotorError(f"faltando no .env: {', '.join(faltando)}")

    # quote em usuario e senha: um '@' na senha monta uma URL sintaticamente
    # valida apontando para outro host, e o erro que aparece e "conexao
    # recusada", nao "senha invalida".
    return (
        f"postgresql+psycopg://{quote(v['USER'], safe='')}:"
        f"{quote(v['PASSWORD'], safe='')}@{v['HOST']}:{v['PORT']}/{v['NAME']}"
    )
```

Criar `compose.yml`:

```yaml
services:
  db:
    image: postgres:18-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${DATABASE_NAME}
      POSTGRES_USER: ${DATABASE_USER}
      POSTGRES_PASSWORD: ${DATABASE_PASSWORD}
    ports: ["${DATABASE_PORT}:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 5s
      timeout: 3s
      retries: 10

volumes:
  pgdata:
```

Criar `.env.example`:

```bash
# Banco — o compose.yml le estas mesmas variaveis
DATABASE_HOST=localhost
DATABASE_PORT=5433
DATABASE_NAME=monitor_versoes
DATABASE_USER=motor
DATABASE_PASSWORD=motor

# Tickio
TICKIO_BASE_URL=http://tickio.vendabem.com.br
TICKIO_USER=
TICKIO_PASSWORD=

# Bitbucket (opcional — ativa descoberta de commits por PR)
BITBUCKET_TOKEN=
BITBUCKET_EMAIL=

# Raiz onde --repo <nome> e procurado
PROJECTS_DIR=/Volumes/ESSD/Projetos
```

`pyproject.toml`, substituir `dependencies` e `optional-dependencies`:

```toml
dependencies = [
    "httpx",
    "python-dotenv",
    "textual>=8.2.8",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg[binary]>=3.2",
]

[project.optional-dependencies]
dev = ["pytest"]
```

Adicionar a `[tool.pytest.ini_options]`:

```toml
markers = [
    "integracao: exige Postgres de pe (pulado sem DATABASE_HOST no ambiente)",
]
```

`.gitignore`, remover a linha 12 (`locks/`) — o diretório deixa de existir. Manter `conflitos/`.

- [ ] **Step 4: Instalar e rodar**

```bash
uv sync
uv run pytest tests/test_config.py -v
```
Expected: PASS.

- [ ] **Step 5: Subir o banco e confirmar**

```bash
cp .env.example .env
docker compose up -d
docker compose ps
```
Expected: serviço `db` com status `healthy`.

- [ ] **Step 6: Commit**

```bash
git add motor/config.py compose.yml .env.example pyproject.toml uv.lock \
        .gitignore tests/test_config.py
git commit -m "feat(config): database_url a partir das partes do .env, compose com Postgres 18

Aplicacao e compose leem o mesmo .env — uma fonte so. quote em usuario e
senha: sem ele um '@' na senha aponta a URL para outro host e o erro vira
'conexao recusada'."
```

---

### Task 5: Modelos SQLAlchemy, Alembic e a trigger de congelamento

**Files:**
- Create: `motor/adapters/estado/__init__.py`, `motor/adapters/estado/models.py`
- Create: `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/`
- Test: `tests/test_estado_models.py`

**Interfaces:**
- Consumes: `database_url()` (Task 4)
- Produces: `Base`, `Repo`, `RepoAlias`, `Versao`, `Atribuicao` (modelo), `AtribuicaoCommit`, `Exclusao`, `SemEntrega` em `motor.adapters.estado.models`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_estado_models.py`:

```python
from __future__ import annotations

from motor.adapters.estado.models import Base


def test_metadata_tem_todas_as_tabelas():
    assert set(Base.metadata.tables) == {
        "repo",
        "repo_alias",
        "versao",
        "atribuicao",
        "atribuicao_commit",
        "exclusao",
        "sem_entrega",
    }


def test_naming_convention_esta_configurada():
    # Sem isso o autogenerate nomeia constraints por reflexao e as migracoes
    # de indice/FK ficam instaveis entre maquinas.
    assert "pk" in Base.metadata.naming_convention
    assert "fk" in Base.metadata.naming_convention


def test_dominio_nao_importa_sqlalchemy():
    # A regra que sustenta a suite sem banco: modelo ORM so no adapter.
    import pathlib

    dominio = pathlib.Path("motor/domain")
    for arquivo in dominio.glob("*.py"):
        assert "sqlalchemy" not in arquivo.read_text(encoding="utf-8"), arquivo
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/test_estado_models.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'motor.adapters.estado'`.

- [ ] **Step 3: Implementar os modelos**

Criar `motor/adapters/estado/__init__.py` vazio e `motor/adapters/estado/models.py`:

```python
"""Modelos SQLAlchemy. Vivem SO aqui — o dominio nunca importa sqlalchemy.

Traducao modelo <-> dataclass acontece em postgres.py, na fronteira.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Nomes deterministicos de constraint: sem isso o autogenerate do Alembic
# nomeia por reflexao e as migracoes ficam instaveis entre maquinas.
CONVENCAO = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCAO)


class Repo(Base):
    __tablename__ = "repo"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(unique=True)  # basename do --repo
    tickio_sistema_id: Mapped[int]  # ID do sistema NO TICKIO, vai em ?sistema=


class RepoAlias(Base):
    """Basename alternativo do diretorio.

    Existe porque repo.nome chaveia todo o estado: o mesmo repositorio clonado
    como 'vb2web' numa maquina e 'vb2' noutra criaria duas linhas em repo e
    dois estados paralelos, sem erro nenhum aparecer.
    """

    __tablename__ = "repo_alias"

    nome: Mapped[str] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repo.id"))


class Versao(Base):
    __tablename__ = "versao"
    __table_args__ = (UniqueConstraint("repo_id", "numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repo.id"))
    numero: Mapped[str]  # '13.34.0'
    tipo: Mapped[str]  # fechada | ajustada | cliente
    base_ref: Mapped[str]
    base_commit: Mapped[str]
    # null = em construcao. Preenchida com a data do commit apontado pela tag.
    liberada_em: Mapped[datetime.datetime | None] = mapped_column(default=None)


class Atribuicao(Base):
    """Tarefa x versao destino.

    Guarda `marcada` desnormalizado de proposito: uma tabela `tarefa` global
    faria o snapshot congelado apontar para linha viva, e o registro do que
    saiu em 2026 mudaria ao editarem algo no Tickio em 2027.
    """

    __tablename__ = "atribuicao"

    versao_id: Mapped[int] = mapped_column(ForeignKey("versao.id"), primary_key=True)
    chamado: Mapped[str] = mapped_column(primary_key=True)
    marcada: Mapped[str]  # versao para a qual o Tickio marcou
    estado: Mapped[str]  # pendente | aplicado


class AtribuicaoCommit(Base):
    __tablename__ = "atribuicao_commit"
    __table_args__ = (
        ForeignKeyConstraint(
            ["versao_id", "chamado"],
            ["atribuicao.versao_id", "atribuicao.chamado"],
            ondelete="CASCADE",
        ),
    )

    versao_id: Mapped[int] = mapped_column(primary_key=True)
    chamado: Mapped[str] = mapped_column(primary_key=True)
    hash_origem: Mapped[str] = mapped_column(primary_key=True)


class Exclusao(Base):
    """Julgamento humano. A unica coisa que o recalculo nunca apaga."""

    __tablename__ = "exclusao"
    __table_args__ = (
        Index(
            "uq_exclusao_repo_hash_versao",
            "repo_id",
            "hash_origem",
            text("coalesce(versao_numero, '')"),
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repo.id"))
    hash_origem: Mapped[str]
    # null = vale para toda versao do repo (ex.: commit revertido).
    versao_numero: Mapped[str | None] = mapped_column(default=None)
    motivo: Mapped[str]


class SemEntrega(Base):
    """Chamado sem entrega NESTE repo. Por repo, nao por versao: os commits
    sao os mesmos para todas as versoes."""

    __tablename__ = "sem_entrega"

    repo_id: Mapped[int] = mapped_column(ForeignKey("repo.id"), primary_key=True)
    chamado: Mapped[str] = mapped_column(primary_key=True)
    motivo: Mapped[str]
```

- [ ] **Step 4: Rodar o teste dos modelos**

Run: `uv run pytest tests/test_estado_models.py -v`
Expected: PASS.

- [ ] **Step 5: Inicializar o Alembic**

```bash
uv run alembic init alembic
```

Editar `alembic.ini`: deixar `sqlalchemy.url` vazio (`sqlalchemy.url =`). A URL vem do `env.py`, senão a senha vira segunda fonte de verdade num arquivo versionado.

Substituir o corpo de `alembic/env.py` por:

```python
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from motor.adapters.estado.models import Base

load_dotenv()

config = context.config
# A URL vem do .env, nunca do alembic.ini: o ini e versionado.
from motor.config import database_url  # noqa: E402

config.set_main_option("sqlalchemy.url", database_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 6: Gerar a migração inicial**

```bash
docker compose up -d
uv run alembic revision --autogenerate -m "schema inicial"
```

Abrir o arquivo gerado em `alembic/versions/` e conferir que o `upgrade()` cria as sete tabelas. Se o `Index` com `coalesce` não tiver sido gerado, adicioná-lo à mão:

```python
    op.create_index(
        "uq_exclusao_repo_hash_versao",
        "exclusao",
        ["repo_id", "hash_origem", sa.text("coalesce(versao_numero, '')")],
        unique=True,
    )
```

- [ ] **Step 7: Escrever a migração da trigger à mão**

O autogenerate reflete tabelas, não PL/pgSQL. Criar a revisão:

```bash
uv run alembic revision -m "trigger de congelamento de versao liberada"
```

Preencher o arquivo gerado:

```python
def upgrade() -> None:
    op.execute("""
        create or replace function trava_versao_liberada() returns trigger as $$
        declare vid int;
        begin
          if tg_op = 'DELETE' then vid := old.versao_id; else vid := new.versao_id; end if;
          if exists (select 1 from versao where id = vid and liberada_em is not null) then
            raise exception 'versao liberada e imutavel (versao_id=%)', vid;
          end if;
          if tg_op = 'DELETE' then return old; else return new; end if;
        end $$ language plpgsql;
    """)
    op.execute("""
        create trigger atribuicao_congelada
          before insert or update or delete on atribuicao
          for each row execute function trava_versao_liberada();
    """)
    op.execute("""
        create trigger atribuicao_commit_congelada
          before insert or update or delete on atribuicao_commit
          for each row execute function trava_versao_liberada();
    """)


def downgrade() -> None:
    op.execute("drop trigger if exists atribuicao_commit_congelada on atribuicao_commit")
    op.execute("drop trigger if exists atribuicao_congelada on atribuicao")
    op.execute("drop function if exists trava_versao_liberada()")
```

- [ ] **Step 8: Aplicar e verificar no banco**

```bash
uv run alembic upgrade head
docker compose exec db psql -U motor -d monitor_versoes -c "\dt"
docker compose exec db psql -U motor -d monitor_versoes \
  -c "select tgname from pg_trigger where not tgisinternal;"
```
Expected: sete tabelas listadas e os dois triggers (`atribuicao_congelada`, `atribuicao_commit_congelada`).

- [ ] **Step 9: Commit**

```bash
git add motor/adapters/estado alembic alembic.ini tests/test_estado_models.py
git commit -m "feat(estado): modelos SQLAlchemy, Alembic e trigger de congelamento

Versao com tag e imutavel por constraint de banco, nao por if em Python: o
Postgres foi escolhido para ser consultado via psql, e guard em Python nao
protege de um DELETE digitado a mao."
```

---

### Task 6: Porta EstadoRepo e fake em memória

**Files:**
- Modify: `motor/domain/types.py` (adicionar `Atribuicao`, `VersaoInfo`, `RepoInfo`; reformar `Exclusion`)
- Modify: `motor/ports.py` (adicionar Protocol `EstadoRepo`)
- Create: `motor/adapters/estado/fake.py`
- Test: `tests/test_estado_fake.py`

**Interfaces:**
- Consumes: nada de tasks anteriores além dos dataclasses do domínio.
- Produces:
  - `Atribuicao(chamado: str, marcada: str, estado: str, commits: list[str])`
  - `VersaoInfo(numero: str, tipo: VersionType, base_ref: str, base_commit: str, liberada_em: datetime | None)`
  - `RepoInfo(nome: str, tickio_sistema_id: int)`
  - `Exclusion(hash_origem: str, versao_numero: str | None, motivo: str)`
  - `EstadoRepo` Protocol com: `resolver_repo`, `registrar_versao`, `marcar_liberadas`, `versao`, `atribuicoes`, `substituir_atribuicoes`, `exclusoes`, `sem_entrega`
  - `FakeEstado`

> **`versao()` devolve o `VersaoInfo` inteiro, não só `liberada_em`.** A `base` gravada no `registrar_versao` é a única correta: recomputar `BaseResolver.resolve` a cada run faria a base de uma versão `X.0.0` seguir o tip atual do master em vez do ponto onde a branch foi cortada, e o oráculo passaria a considerar presente tudo que entrou no master depois. O código de hoje lê `lock.base.commit` pelo mesmo motivo.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/test_estado_fake.py`:

```python
from __future__ import annotations

import datetime

import pytest

from motor.adapters.estado.fake import FakeEstado
from motor.domain.types import Atribuicao, RepoInfo, VersaoInfo, VersionType
from motor.errors import MotorError


def _info(numero: str, liberada=None) -> VersaoInfo:
    return VersaoInfo(
        numero=numero,
        tipo=VersionType.AJUSTADA,
        base_ref="13.33.0",
        base_commit="aaa",
        liberada_em=liberada,
    )


def test_resolver_repo_por_nome_e_por_alias():
    estado = FakeEstado(
        repos={"vb2web": RepoInfo(nome="vb2web", tickio_sistema_id=2)},
        aliases={"vb2": "vb2web"},
    )
    assert estado.resolver_repo("vb2web").tickio_sistema_id == 2
    # o alias resolve para o nome canonico, nao cria repo novo
    assert estado.resolver_repo("vb2").nome == "vb2web"


def test_resolver_repo_desconhecido_e_erro_com_o_insert_pronto():
    with pytest.raises(MotorError, match="insert into repo"):
        FakeEstado().resolver_repo("desconhecido")


def test_substituir_atribuicoes_sobrescreve():
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})
    estado.registrar_versao("r", _info("13.34.0"))

    estado.substituir_atribuicoes("r", "13.34.0", [
        Atribuicao(chamado="1", marcada="13.34.0", estado="pendente", commits=["a"]),
    ])
    estado.substituir_atribuicoes("r", "13.34.0", [
        Atribuicao(chamado="2", marcada="13.34.0", estado="aplicado", commits=["b"]),
    ])

    assert [a.chamado for a in estado.atribuicoes("r", "13.34.0")] == ["2"]


def test_substituir_atribuicoes_recusa_versao_liberada():
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})
    estado.registrar_versao("r", _info("13.34.0"))
    estado.marcar_liberadas("r", {"13.34.0": datetime.datetime(2026, 8, 1)})

    with pytest.raises(MotorError, match="imutavel"):
        estado.substituir_atribuicoes("r", "13.34.0", [])


def test_marcar_liberadas_ignora_versao_que_nao_esta_no_estado():
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})
    estado.marcar_liberadas("r", {"9.9.9": datetime.datetime(2026, 8, 1)})
    assert estado.versao("r", "9.9.9") is None


def test_marcar_liberadas_nao_reescreve_data_ja_gravada():
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})
    estado.registrar_versao("r", _info("13.34.0"))
    primeira = datetime.datetime(2026, 8, 1)
    estado.marcar_liberadas("r", {"13.34.0": primeira})
    estado.marcar_liberadas("r", {"13.34.0": datetime.datetime(2026, 9, 1)})
    assert estado.versao("r", "13.34.0").liberada_em == primeira


def test_registrar_versao_nao_sobrescreve_a_base_ja_gravada():
    # A base e gravada uma vez, na criacao. Recomputar faria a base de uma
    # X.0.0 seguir o tip atual do master.
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})
    estado.registrar_versao("r", _info("14.0.0"))
    estado.registrar_versao(
        "r",
        VersaoInfo(numero="14.0.0", tipo=VersionType.FECHADA,
                   base_ref="master", base_commit="OUTRO"),
    )
    assert estado.versao("r", "14.0.0").base_commit == "aaa"
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/test_estado_fake.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'motor.adapters.estado.fake'`.

- [ ] **Step 3: Implementar os tipos de domínio**

> **Esta task é puramente aditiva.** Nada sai de `types.py` aqui. `Lock`, `ExclusionReason`, o `Exclusion` antigo e os campos atuais de `VersionStatus` continuam existindo, porque `criar.py:5`, `atualizar.py:9`, `reconcile.py:7` e `lock_store.py:14-15` os importam **em nível de módulo** — removê-los agora daria `ImportError` na coleta do pytest, e a suíte inteira pararia de rodar até a Task 9. Cada remoção viaja junto do último consumidor reescrito: `Exclusion`/`ExclusionReason` e os campos de `VersionStatus` na Task 8, `Lock` na Task 9.

Adicionar a `motor/domain/types.py`:

```python
@dataclass(frozen=True)
class Atribuicao:
    chamado: str = ""
    marcada: str = ""  # versao para a qual o Tickio marcou
    estado: str = "pendente"  # pendente | aplicado
    commits: list[str] = field(default_factory=list)  # hashes de origem


@dataclass(frozen=True)
class VersaoInfo:
    numero: str = ""
    tipo: VersionType = VersionType.FECHADA
    base_ref: str = ""
    base_commit: str = ""
    liberada_em: datetime.datetime | None = None


@dataclass(frozen=True)
class RepoInfo:
    nome: str = ""  # canonico, nunca o alias
    tickio_sistema_id: int = 0
```

`VersionStatus` não muda nesta task — a troca de `lock_integro` por `estado_integro` e o campo `tasks_ambiguas` entram na Task 8, junto com a reescrita do único código que os produz e consome.

- [ ] **Step 4: Implementar a porta**

Adicionar a `motor/ports.py`:

```python
class EstadoRepo(Protocol):
    """Estado persistente. Projecao materializada para versao em construcao;
    registro unico e imutavel para versao liberada.
    """

    def resolver_repo(self, basename: str) -> RepoInfo:
        """Resolve nome ou alias para o repo canonico. MotorError se
        desconhecido — nunca cria linha sozinho, senao um clone com nome
        diferente fragmenta o estado."""
        ...

    def registrar_versao(self, repo: str, info: VersaoInfo) -> None:
        """Upsert da versao operada. Nao toca `liberada_em`."""
        ...

    def marcar_liberadas(self, repo: str, liberadas: dict[str, datetime]) -> None:
        """Grava a data de liberacao das versoes que ganharam tag. Ignora
        versao ausente do estado e nao reescreve data ja gravada."""
        ...

    def versao(self, repo: str, numero: str) -> VersaoInfo | None:
        """A versao como esta no estado. A `base` daqui e a autoritativa —
        recomputar BaseResolver a cada run faria a base de uma X.0.0 seguir o
        tip atual do master em vez do ponto onde a branch foi cortada."""
        ...

    def atribuicoes(self, repo: str, versao: str) -> list[Atribuicao]: ...

    def substituir_atribuicoes(
        self, repo: str, versao: str, novas: list[Atribuicao]
    ) -> None:
        """Apaga e reinsere. MotorError se a versao ja estiver liberada."""
        ...

    def exclusoes(self, repo: str) -> list[Exclusion]: ...

    def sem_entrega(self, repo: str) -> dict[str, str]:
        """chamado -> motivo."""
        ...
```

Ajustar os imports do topo de `ports.py` para incluir `Atribuicao`, `Exclusion`, `RepoInfo`, `VersaoInfo` e `datetime`.

- [ ] **Step 5: Implementar o fake**

Criar `motor/adapters/estado/fake.py`:

```python
"""Double em memoria de EstadoRepo. Mantem a suite rodando sem banco."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from motor.domain.types import Atribuicao, Exclusion, RepoInfo, VersaoInfo
from motor.errors import MotorError


@dataclass
class FakeEstado:
    repos: dict[str, RepoInfo] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)  # alias -> nome canonico
    versoes: dict[tuple[str, str], VersaoInfo] = field(default_factory=dict)
    _atribuicoes: dict[tuple[str, str], list[Atribuicao]] = field(default_factory=dict)
    _exclusoes: dict[str, list[Exclusion]] = field(default_factory=dict)
    _sem_entrega: dict[str, dict[str, str]] = field(default_factory=dict)

    def resolver_repo(self, basename: str) -> RepoInfo:
        nome = self.aliases.get(basename, basename)
        info = self.repos.get(nome)
        if info is None:
            raise MotorError(
                f"repo '{basename}' desconhecido. Cadastre com:\n"
                f"  insert into repo (nome, tickio_sistema_id) "
                f"values ('{basename}', <id do sistema no tickio>);"
            )
        return info

    def registrar_versao(self, repo: str, info: VersaoInfo) -> None:
        # Idempotente e nao-destrutivo: base e liberada_em so entram na
        # primeira gravacao. A base e o ponto onde a branch foi cortada, nao
        # algo a recomputar.
        if (repo, info.numero) in self.versoes:
            return
        self.versoes[(repo, info.numero)] = info

    def marcar_liberadas(
        self, repo: str, liberadas: dict[str, datetime.datetime]
    ) -> None:
        for numero, quando in liberadas.items():
            atual = self.versoes.get((repo, numero))
            if atual is None or atual.liberada_em is not None:
                continue
            self.versoes[(repo, numero)] = VersaoInfo(
                numero=atual.numero,
                tipo=atual.tipo,
                base_ref=atual.base_ref,
                base_commit=atual.base_commit,
                liberada_em=quando,
            )

    def versao(self, repo: str, numero: str) -> VersaoInfo | None:
        return self.versoes.get((repo, numero))

    def atribuicoes(self, repo: str, versao: str) -> list[Atribuicao]:
        return list(self._atribuicoes.get((repo, versao), []))

    def substituir_atribuicoes(
        self, repo: str, versao: str, novas: list[Atribuicao]
    ) -> None:
        # Espelha a trigger do Postgres: o fake nao pode aceitar o que o banco
        # recusa, senao os testes de engine validam um comportamento que nao
        # existe em producao.
        atual = self.versao(repo, versao)
        if atual is not None and atual.liberada_em is not None:
            raise MotorError(f"versao {versao} liberada e imutavel")
        self._atribuicoes[(repo, versao)] = list(novas)

    def exclusoes(self, repo: str) -> list[Exclusion]:
        return list(self._exclusoes.get(repo, []))

    def sem_entrega(self, repo: str) -> dict[str, str]:
        return dict(self._sem_entrega.get(repo, {}))
```

- [ ] **Step 6: Rodar**

Run: `uv run pytest -v -m "not integracao"`
Expected: PASS, suíte inteira. A task é aditiva — nenhum teste existente deve quebrar. Se algum quebrou, algo foi removido que não devia.

- [ ] **Step 7: Commit**

```bash
git add motor/domain/types.py motor/ports.py motor/adapters/estado/fake.py \
        tests/test_estado_fake.py
git commit -m "feat(ports): porta EstadoRepo e FakeEstado em memoria

Aditivo: Lock e ExclusionReason continuam ate o ultimo consumidor ser
reescrito. O fake espelha a trigger do Postgres e recusa escrita em versao
liberada — se aceitasse, os testes de engine validariam um comportamento que
nao existe em producao."
```

---

### Task 7: PostgresEstado e o teste de integração da trigger

**Files:**
- Create: `motor/adapters/estado/postgres.py`
- Create: `tests/test_estado_postgres.py`, `tests/conftest.py` (fixture do banco)

**Interfaces:**
- Consumes: `EstadoRepo` Protocol e dataclasses (Task 6); modelos (Task 5); `database_url()` (Task 4)
- Produces: `PostgresEstado(session: Session)` implementando `EstadoRepo`

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/conftest.py` (o arquivo `conftest.py` da raiz está vazio; este é o de `tests/`):

```python
from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

load_dotenv()


@pytest.fixture
def sessao_postgres():
    """Sessao contra o Postgres real. Pula quando o banco nao esta configurado."""
    if not os.environ.get("DATABASE_HOST"):
        pytest.skip("DATABASE_HOST ausente — banco nao configurado")

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from motor.config import database_url

    engine = create_engine(database_url())
    with engine.connect() as conn:
        conn.execute(
            text(
                "truncate atribuicao_commit, atribuicao, versao, exclusao, "
                "sem_entrega, repo_alias, repo restart identity cascade"
            )
        )
        conn.commit()

    fabrica = sessionmaker(engine)
    with fabrica() as sessao:
        yield sessao
    engine.dispose()
```

Criar `tests/test_estado_postgres.py`:

```python
from __future__ import annotations

import datetime

import pytest
from sqlalchemy import text

from motor.adapters.estado.postgres import PostgresEstado
from motor.domain.types import Atribuicao, VersaoInfo, VersionType
from motor.errors import MotorError

pytestmark = pytest.mark.integracao


def _semear_repo(sessao) -> None:
    sessao.execute(
        text(
            "insert into repo (nome, tickio_sistema_id) values ('vendabemweb', 1)"
        )
    )
    sessao.execute(
        text(
            "insert into repo_alias (nome, repo_id) select 'vbweb', id from repo"
        )
    )
    sessao.commit()


def _info(numero: str) -> VersaoInfo:
    return VersaoInfo(
        numero=numero,
        tipo=VersionType.AJUSTADA,
        base_ref="13.33.0",
        base_commit="aaa111",
    )


def test_resolver_repo_por_alias(sessao_postgres):
    _semear_repo(sessao_postgres)
    estado = PostgresEstado(sessao=sessao_postgres)

    assert estado.resolver_repo("vbweb").nome == "vendabemweb"
    assert estado.resolver_repo("vbweb").tickio_sistema_id == 1


def test_resolver_repo_desconhecido(sessao_postgres):
    estado = PostgresEstado(sessao=sessao_postgres)
    with pytest.raises(MotorError, match="insert into repo"):
        estado.resolver_repo("nunca-visto")


def test_ciclo_de_atribuicoes(sessao_postgres):
    _semear_repo(sessao_postgres)
    estado = PostgresEstado(sessao=sessao_postgres)
    estado.registrar_versao("vendabemweb", _info("13.34.0"))

    estado.substituir_atribuicoes("vendabemweb", "13.34.0", [
        Atribuicao(chamado="123456", marcada="13.34.0", estado="aplicado",
                   commits=["aaa", "bbb"]),
    ])

    lidas = estado.atribuicoes("vendabemweb", "13.34.0")
    assert len(lidas) == 1
    assert lidas[0].chamado == "123456"
    assert sorted(lidas[0].commits) == ["aaa", "bbb"]


def test_trigger_recusa_escrita_em_versao_liberada(sessao_postgres):
    """A invariante central do congelamento. Um fake nao prova isto — a trigger
    tem que existir no banco de verdade."""
    _semear_repo(sessao_postgres)
    estado = PostgresEstado(sessao=sessao_postgres)
    estado.registrar_versao("vendabemweb", _info("13.34.0"))
    estado.substituir_atribuicoes("vendabemweb", "13.34.0", [
        Atribuicao(chamado="123456", marcada="13.34.0", estado="aplicado",
                   commits=["aaa"]),
    ])
    estado.marcar_liberadas("vendabemweb", {"13.34.0": datetime.datetime(2026, 8, 1)})

    with pytest.raises(MotorError, match="imutavel"):
        estado.substituir_atribuicoes("vendabemweb", "13.34.0", [
            Atribuicao(chamado="999111", marcada="13.34.0", estado="pendente",
                       commits=["ccc"]),
        ])

    # e o snapshot antigo continua intacto
    assert [a.chamado for a in estado.atribuicoes("vendabemweb", "13.34.0")] == ["123456"]


def test_marcar_liberadas_nao_reescreve_data(sessao_postgres):
    _semear_repo(sessao_postgres)
    estado = PostgresEstado(sessao=sessao_postgres)
    estado.registrar_versao("vendabemweb", _info("13.34.0"))
    primeira = datetime.datetime(2026, 8, 1)
    estado.marcar_liberadas("vendabemweb", {"13.34.0": primeira})
    estado.marcar_liberadas("vendabemweb", {"13.34.0": datetime.datetime(2026, 9, 1)})

    assert estado.versao("vendabemweb", "13.34.0").liberada_em == primeira


def test_registrar_versao_nao_sobrescreve_a_base(sessao_postgres):
    _semear_repo(sessao_postgres)
    estado = PostgresEstado(sessao=sessao_postgres)
    estado.registrar_versao("vendabemweb", _info("13.34.0"))
    estado.registrar_versao(
        "vendabemweb",
        VersaoInfo(numero="13.34.0", tipo=VersionType.AJUSTADA,
                   base_ref="master", base_commit="OUTRO"),
    )

    assert estado.versao("vendabemweb", "13.34.0").base_commit == "aaa111"
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/test_estado_postgres.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'motor.adapters.estado.postgres'`.

- [ ] **Step 3: Implementar**

Criar `motor/adapters/estado/postgres.py`:

```python
"""PostgresEstado: traduz modelo ORM <-> dataclass do dominio na fronteira."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import DatabaseError, OperationalError
from sqlalchemy.orm import Session

from motor.adapters.estado import models
from motor.domain.types import Atribuicao, Exclusion, RepoInfo, VersaoInfo, VersionType
from motor.errors import MotorError

_TIPO_PARA_TEXTO = {
    VersionType.FECHADA: "fechada",
    VersionType.AJUSTADA: "ajustada",
    VersionType.CLIENTE: "cliente",
}
_TEXTO_PARA_TIPO = {v: k for k, v in _TIPO_PARA_TEXTO.items()}


@dataclass
class PostgresEstado:
    sessao: Session

    def resolver_repo(self, basename: str) -> RepoInfo:
        linha = self.sessao.scalar(
            select(models.Repo).where(models.Repo.nome == basename)
        )
        if linha is None:
            alias = self.sessao.scalar(
                select(models.RepoAlias).where(models.RepoAlias.nome == basename)
            )
            if alias is not None:
                linha = self.sessao.get(models.Repo, alias.repo_id)
        if linha is None:
            raise MotorError(
                f"repo '{basename}' desconhecido. Cadastre com:\n"
                f"  insert into repo (nome, tickio_sistema_id) "
                f"values ('{basename}', <id do sistema no tickio>);"
            )
        return RepoInfo(nome=linha.nome, tickio_sistema_id=linha.tickio_sistema_id)

    def registrar_versao(self, repo: str, info: VersaoInfo) -> None:
        # Idempotente e nao-destrutivo: a base e o ponto onde a branch foi
        # cortada, gravado uma vez. Reescreve-la faria a base de uma X.0.0
        # seguir o tip atual do master.
        repo_id = self._repo_id(repo)
        if self._versao(repo_id, info.numero) is not None:
            return
        self.sessao.add(
            models.Versao(
                repo_id=repo_id,
                numero=info.numero,
                tipo=_TIPO_PARA_TEXTO[info.tipo],
                base_ref=info.base_ref,
                base_commit=info.base_commit,
                liberada_em=info.liberada_em,
            )
        )
        self._commit()

    def marcar_liberadas(
        self, repo: str, liberadas: dict[str, datetime.datetime]
    ) -> None:
        repo_id = self._repo_id(repo)
        for numero, quando in liberadas.items():
            linha = self._versao(repo_id, numero)
            # ignora versao ausente do estado e nao reescreve data ja gravada:
            # a primeira observacao da tag e a boa.
            if linha is None or linha.liberada_em is not None:
                continue
            linha.liberada_em = quando
        self._commit()

    def versao(self, repo: str, numero: str) -> VersaoInfo | None:
        linha = self._versao(self._repo_id(repo), numero)
        if linha is None:
            return None
        return VersaoInfo(
            numero=linha.numero,
            tipo=_TEXTO_PARA_TIPO[linha.tipo],
            base_ref=linha.base_ref,
            base_commit=linha.base_commit,
            liberada_em=linha.liberada_em,
        )

    def atribuicoes(self, repo: str, versao: str) -> list[Atribuicao]:
        versao_id = self._versao_id(repo, versao)
        if versao_id is None:
            return []
        commits: dict[str, list[str]] = {}
        for linha in self.sessao.scalars(
            select(models.AtribuicaoCommit).where(
                models.AtribuicaoCommit.versao_id == versao_id
            )
        ):
            commits.setdefault(linha.chamado, []).append(linha.hash_origem)
        return [
            Atribuicao(
                chamado=a.chamado,
                marcada=a.marcada,
                estado=a.estado,
                commits=sorted(commits.get(a.chamado, [])),
            )
            for a in self.sessao.scalars(
                select(models.Atribuicao).where(
                    models.Atribuicao.versao_id == versao_id
                )
            )
        ]

    def substituir_atribuicoes(
        self, repo: str, versao: str, novas: list[Atribuicao]
    ) -> None:
        versao_id = self._versao_id(repo, versao)
        if versao_id is None:
            raise MotorError(f"versao {versao} nao registrada no estado")

        self.sessao.execute(
            delete(models.AtribuicaoCommit).where(
                models.AtribuicaoCommit.versao_id == versao_id
            )
        )
        self.sessao.execute(
            delete(models.Atribuicao).where(models.Atribuicao.versao_id == versao_id)
        )
        for a in novas:
            self.sessao.add(
                models.Atribuicao(
                    versao_id=versao_id,
                    chamado=a.chamado,
                    marcada=a.marcada,
                    estado=a.estado,
                )
            )
            for hash_origem in a.commits:
                self.sessao.add(
                    models.AtribuicaoCommit(
                        versao_id=versao_id,
                        chamado=a.chamado,
                        hash_origem=hash_origem,
                    )
                )
        self._commit()

    def exclusoes(self, repo: str) -> list[Exclusion]:
        repo_id = self._repo_id(repo)
        return [
            Exclusion(
                hash_origem=e.hash_origem,
                versao_numero=e.versao_numero,
                motivo=e.motivo,
            )
            for e in self.sessao.scalars(
                select(models.Exclusao).where(models.Exclusao.repo_id == repo_id)
            )
        ]

    def sem_entrega(self, repo: str) -> dict[str, str]:
        repo_id = self._repo_id(repo)
        return {
            s.chamado: s.motivo
            for s in self.sessao.scalars(
                select(models.SemEntrega).where(models.SemEntrega.repo_id == repo_id)
            )
        }

    # -- internos --------------------------------------------------------

    def _repo_id(self, repo: str) -> int:
        linha = self.sessao.scalar(
            select(models.Repo).where(models.Repo.nome == repo)
        )
        if linha is None:
            raise MotorError(f"repo '{repo}' nao encontrado no estado")
        return linha.id

    def _versao(self, repo_id: int, numero: str) -> models.Versao | None:
        return self.sessao.scalar(
            select(models.Versao).where(
                models.Versao.repo_id == repo_id, models.Versao.numero == numero
            )
        )

    def _versao_id(self, repo: str, numero: str) -> int | None:
        linha = self._versao(self._repo_id(repo), numero)
        return None if linha is None else linha.id

    def _commit(self) -> None:
        """Traduz erro do banco em MotorError.

        A trigger de congelamento chega aqui como DatabaseError; deixa-la subir
        crua imprimiria traceback de psycopg em vez de mensagem util.
        """
        try:
            self.sessao.commit()
        except OperationalError as e:
            self.sessao.rollback()
            raise MotorError(
                f"banco inacessivel: {e.orig}. Suba com: docker compose up -d"
            ) from e
        except DatabaseError as e:
            self.sessao.rollback()
            if "imutavel" in str(e.orig):
                raise MotorError(
                    "versao liberada e imutavel — remarque a tarefa para a proxima versao"
                ) from e
            raise MotorError(f"erro do banco: {e.orig}") from e
```

- [ ] **Step 4: Rodar o teste de integração**

```bash
docker compose up -d
uv run alembic upgrade head
uv run pytest tests/test_estado_postgres.py -v
```
Expected: PASS, 5 testes.

- [ ] **Step 5: Confirmar que a suíte pula sem banco**

Run: `env -u DATABASE_HOST uv run pytest tests/test_estado_postgres.py -v`
Expected: 5 SKIPPED.

- [ ] **Step 6: Commit**

```bash
git add motor/adapters/estado/postgres.py tests/test_estado_postgres.py tests/conftest.py
git commit -m "feat(estado): adapter PostgresEstado e teste de integracao da trigger

O teste da trigger e obrigatorio: e a invariante central do congelamento e o
fake em memoria nao a prova. Erro de banco vira MotorError com mensagem util
em vez de traceback de psycopg."
```

---

### Task 8: Reconciliação e `verificar` contra o estado

> **Por que reconciliação e `verificar` são uma task só.** Esta task muda as assinaturas de `reconciliar` e `filtrar_excluidos`, e o único chamador das duas é `verificar.py:65,104`. Separá-las deixaria a suíte vermelha entre elas — não há ponto de corte em que uma esteja pronta e a outra não. É também aqui que `Exclusion`, `ExclusionReason` e os campos de `VersionStatus` mudam de forma, porque este é o commit em que o último código que os usa é reescrito.

**Files:**
- Modify: `motor/domain/reconcile.py`, `motor/domain/types.py`, `motor/engine/verificar.py`, `motor/engine/deps.py`
- Modify: `motor/engine/atualizar.py`, `motor/services/lock_store.py` (só o suficiente para seguirem importáveis)
- Create: `motor/services/reconstrutor.py` (a varredura de trailers, extraída do lock_store)
- Test: `tests/test_reconcile.py`, `tests/test_verificar.py`

**Interfaces:**
- Consumes: `Atribuicao`, `Exclusion`, `Alvo`, `EstadoRepo` (Tasks 3, 6)
- Produces:
  - `Exclusion(hash_origem: str, versao_numero: str | None, motivo: str)` — forma nova
  - `VersionStatus.estado_integro` (era `lock_integro`) e `VersionStatus.tasks_ambiguas`
  - `filtrar_excluidos(alvo: TargetSet, excluidos: list[Exclusion], versao: str) -> TargetSet`
  - `diff_tasks(alvo: TargetSet, anteriores: list[Atribuicao]) -> tuple[list[str], list[str]]`
  - `reconciliar(alvo: Alvo, anteriores: list[Atribuicao], sem_entrega: dict[str,str], presentes: dict[str,Presence], conflitantes: list[CommitRef], suspeitos_conteudo: list[CommitRef]) -> VersionStatus`
  - `atribuicoes_de(alvo: TargetSet, presentes: dict[str, Presence]) -> list[Atribuicao]`
  - `Deps(git, tasks, estado: EstadoRepo, repo: str, bitbucket_token, bitbucket_email, _commit_source)`
  - `verificar(deps: Deps, versao: str) -> VersionStatus`
  - `reconstruir_atribuicoes(git: GitRepo, base_commit: str, branch: str) -> tuple[list[Atribuicao], list[str]]` — o segundo elemento são os órfãos (commits sem `ch<num>`)
  - `extrair_trailer(msg: str) -> str | None`

- [ ] **Step 1: Escrever os testes que falham**

Substituir `tests/test_reconcile.py` por:

```python
from __future__ import annotations

from motor.domain.reconcile import (
    atribuicoes_de,
    diff_tasks,
    filtrar_excluidos,
    reconciliar,
)
from motor.domain.types import (
    Alvo,
    Atribuicao,
    CommitRef,
    Exclusion,
    Presence,
    TaskTarget,
)


def _alvo(**tasks) -> dict:
    return {
        ch: TaskTarget(chamado=ch, marcada="13.34.0",
                       commits=[CommitRef(hash_origem=h, chamado=ch) for h in hashes])
        for ch, hashes in tasks.items()
    }


def test_filtrar_excluidos_remove_exclusao_global_e_da_versao():
    alvo = _alvo(**{"1": ["aaa", "bbb", "ccc"]})
    excluidos = [
        Exclusion(hash_origem="aaa", versao_numero=None, motivo="revertido"),
        Exclusion(hash_origem="bbb", versao_numero="13.34.0", motivo="nao se aplica"),
        Exclusion(hash_origem="ccc", versao_numero="14.0.0", motivo="outra versao"),
    ]

    filtrado = filtrar_excluidos(alvo, excluidos, "13.34.0")

    assert [c.hash_origem for c in filtrado["1"].commits] == ["ccc"]


def test_diff_tasks_acusa_nova_e_removida():
    alvo = _alvo(**{"1": ["aaa"], "2": ["bbb"]})
    anteriores = [
        Atribuicao(chamado="2", marcada="13.34.0", estado="aplicado", commits=["bbb"]),
        Atribuicao(chamado="3", marcada="13.34.0", estado="aplicado", commits=["ccc"]),
    ]

    novas, removidas = diff_tasks(alvo, anteriores)

    assert novas == ["1"]
    assert removidas == ["3"]


def test_reconciliar_verde_quando_tudo_bate():
    alvo = Alvo(tasks=_alvo(**{"1": ["aaa"]}))
    anteriores = [
        Atribuicao(chamado="1", marcada="13.34.0", estado="aplicado", commits=["aaa"])
    ]
    status = reconciliar(alvo, anteriores, {}, {"aaa": Presence.TRAILER}, [], [])

    assert status.verde is True
    assert status.faltantes == []


def test_reconciliar_nao_fica_verde_com_tarefa_ambigua():
    alvo = Alvo(tasks=_alvo(**{"1": ["aaa"]}), ambiguas=["1"])
    anteriores = [
        Atribuicao(chamado="1", marcada="13.34.0", estado="aplicado", commits=["aaa"])
    ]
    status = reconciliar(alvo, anteriores, {}, {"aaa": Presence.TRAILER}, [], [])

    assert status.verde is False
    assert status.tasks_ambiguas == ["1"]


def test_reconciliar_acusa_tarefa_sem_commit_e_aceita_sem_entrega():
    alvo = Alvo(tasks=_alvo(**{"1": []}))
    assert reconciliar(alvo, [], {}, {}, [], []).tasks_sem_commits == ["1"]

    reconhecida = reconciliar(alvo, [], {"1": "so backend"}, {}, [], [])
    assert reconhecida.tasks_sem_commits == []


def test_reconciliar_acusa_commit_que_sumiu_do_git():
    alvo = Alvo(tasks=_alvo(**{"1": ["aaa"]}))
    anteriores = [
        Atribuicao(chamado="1", marcada="13.34.0", estado="aplicado",
                   commits=["aaa", "sumido"])
    ]
    status = reconciliar(alvo, anteriores, {}, {"aaa": Presence.TRAILER}, [], [])

    assert status.estado_integro is False
    assert status.commits_sumidos == ["sumido"]


def test_atribuicoes_de_marca_aplicado_so_quando_presente():
    alvo = _alvo(**{"1": ["aaa"], "2": ["bbb"]})
    presentes = {"aaa": Presence.TRAILER, "bbb": Presence.AUSENTE}

    por_chamado = {a.chamado: a for a in atribuicoes_de(alvo, presentes)}

    assert por_chamado["1"].estado == "aplicado"
    assert por_chamado["2"].estado == "pendente"
    assert por_chamado["1"].commits == ["aaa"]
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/test_reconcile.py -v`
Expected: FAIL — `ImportError: cannot import name 'atribuicoes_de'`.

- [ ] **Step 3: Implementar**

Substituir `motor/domain/reconcile.py` inteiro:

```python
"""Cruzamento das tres fontes: Tickio (alvo) x estado x git."""

from __future__ import annotations

from dataclasses import replace

from motor.domain.types import (
    Alvo,
    Atribuicao,
    CommitRef,
    Exclusion,
    Presence,
    TargetSet,
    VersionStatus,
)


def filtrar_excluidos(
    alvo: TargetSet, excluidos: list[Exclusion], versao: str
) -> TargetSet:
    """Tira do alvo os commits marcados como excluidos.

    `versao_numero` None vale para todo o repo (ex.: commit revertido); com
    valor, so para aquela versao. Sem isso, todo verificar reportaria o mesmo
    falso-positivo para sempre.
    """
    fora = {
        e.hash_origem
        for e in excluidos
        if e.versao_numero is None or e.versao_numero == versao
    }
    return {
        chamado: replace(
            tt, commits=[c for c in tt.commits if c.hash_origem not in fora]
        )
        for chamado, tt in alvo.items()
    }


def diff_tasks(
    alvo: TargetSet, anteriores: list[Atribuicao]
) -> tuple[list[str], list[str]]:
    """Diferenca simetrica entre o alvo de agora e o estado gravado no run
    anterior. E o que detecta tarefa desmarcada no Tickio — comparar depois de
    sobrescrever apagaria a propria evidencia.
    """
    antes = {a.chamado for a in anteriores}
    novas = [ch for ch, tt in alvo.items() if ch not in antes and tt.commits]
    removidas = [ch for ch in antes if ch not in alvo]
    return sorted(novas), sorted(removidas)


def atribuicoes_de(
    alvo: TargetSet, presentes: dict[str, Presence]
) -> list[Atribuicao]:
    """Projeta o alvo resolvido no formato que vai para o estado."""
    return [
        Atribuicao(
            chamado=tt.chamado,
            marcada=tt.marcada,
            estado=(
                "aplicado"
                if tt.commits
                and all(
                    presentes.get(c.hash_origem, Presence.AUSENTE) != Presence.AUSENTE
                    for c in tt.commits
                )
                else "pendente"
            ),
            commits=[c.hash_origem for c in tt.commits],
        )
        for tt in alvo.values()
    ]


def reconciliar(
    alvo: Alvo,
    anteriores: list[Atribuicao],
    sem_entrega: dict[str, str],
    presentes: dict[str, Presence],
    conflitantes: list[CommitRef],
    suspeitos_conteudo: list[CommitRef] = (),
) -> VersionStatus:
    """Produz o VersionStatus. Funcao pura: `presentes`, `conflitantes` e
    `suspeitos_conteudo` chegam pre-computados pelo chamador.
    """
    novas, removidas = diff_tasks(alvo.tasks, anteriores)

    faltantes: list[CommitRef] = []
    ancestrais: list[CommitRef] = []
    for tt in alvo.tasks.values():
        for c in tt.commits:
            if presentes.get(c.hash_origem, Presence.AUSENTE) == Presence.AUSENTE:
                faltantes.append(c)
            else:
                ancestrais.append(c)

    sumidos = sorted(
        {
            h
            for a in anteriores
            for h in a.commits
            if presentes.get(h, Presence.AUSENTE) == Presence.AUSENTE
        }
    )
    estado_integro = not sumidos

    # Tarefa marcada sem nenhum commit achado nao pode passar despercebida
    # (falso-verde). So sai da lista se reconhecida em sem_entrega.
    sem_commits = sorted(
        ch for ch, tt in alvo.tasks.items() if not tt.commits and ch not in sem_entrega
    )

    verde = (
        not novas
        and not removidas
        and estado_integro
        and not faltantes
        and not sem_commits
        and not alvo.ambiguas
    )

    return VersionStatus(
        verde=verde,
        tasks_novas=novas,
        tasks_removidas=removidas,
        tasks_ambiguas=list(alvo.ambiguas),
        estado_integro=estado_integro,
        commits_sumidos=sumidos,
        faltantes=faltantes,
        ancestrais=ancestrais,
        conflitantes=conflitantes,
        suspeitos_conteudo=list(suspeitos_conteudo),
        tasks_sem_commits=sem_commits,
    )
```

- [ ] **Step 4: Reformar os tipos e manter os legados importáveis**

Em `motor/domain/types.py`, substituir `Exclusion` e remover `ExclusionReason`:

```python
@dataclass(frozen=True)
class Exclusion:
    """Julgamento humano: commit que nao entra. Estado irredutivel — nao e
    re-derivavel do Tickio nem do git.

    As exclusoes automaticas ("ja presente na base") sumiram: eram
    recomputaveis por definicao e quem responde isso e o oraculo de presenca.
    """

    hash_origem: str = ""
    versao_numero: str | None = None  # None = vale para toda versao do repo
    motivo: str = ""
```

Em `VersionStatus`, renomear `lock_integro` para `estado_integro` e adicionar `tasks_ambiguas`:

```python
    estado_integro: bool = False
    tasks_ambiguas: list[str] = field(default_factory=list)
```

`Lock` **fica** — `criar.py:5`, `atualizar.py:9` e `lock_store.py:15` ainda o importam em nível de módulo e só são reescritos na Task 9. Removê-lo agora dá `ImportError` na coleta do pytest.

Dois consumidores de `ExclusionReason` precisam de um retoque mínimo para seguirem importáveis:

`motor/engine/atualizar.py` — remover `Exclusion, ExclusionReason` do import da linha 9 e apagar o bloco `if status.ancestrais:` (linhas 55-68) inteiro. Ele gravava exclusões automáticas no lock; o oráculo de presença responde isso a cada run, então o bloco deixou de ter função.

`motor/services/lock_store.py` — remover `Exclusion` e `ExclusionReason` do import (linhas 13-14), apagar a construção de `Exclusion` em `ler` (linhas 55-63, `excluidos` passa a `[]`) e trocar o filtro de órfãos da linha 160 por `orfaos = []`. O arquivo e deletado no Step 9 desta mesma task; aqui só precisa importar e passar nos testes.

- [ ] **Step 5: Escrever os testes de `verificar` que falham**

Substituir `tests/test_verificar.py` por:

```python
from __future__ import annotations

import datetime

import pytest

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import Atribuicao, CommitRef, RepoInfo, VersaoInfo, VersionType
from motor.engine.deps import Deps
from motor.engine.verificar import verificar


D = datetime.datetime(2026, 1, 1)


def _deps(git, tasks, commits, estado) -> Deps:
    return Deps(git=git, tasks=tasks, estado=estado, repo="r", _commit_source=commits)


def _estado_com_repo() -> FakeEstado:
    return FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})


def _git(tags: dict[str, bool] | None = None) -> FakeGit:
    """Grafo: m0 e a raiz; a0 e um commit que so existe no master.

    As versoes ficam em m0, entao a0 e faltante em todas elas — e o que
    permite afirmar que o commit foi cobrado, e nao herdado da base.
    """
    git = FakeGit(tags=tags or {})
    git.add_commit("m0", "", "raiz", D)
    git.add_commit("a0", "m0", "ch123123 alfa", D)
    git.set_branch("master", "a0")
    git.set_branch("origin/master", "a0")
    for versao in ("13.33.1", "13.34.0", "14.0.0"):
        git.set_branch(versao, "m0")
    return git


def test_verificar_une_tarefas_das_versoes_abertas_menores():
    git = _git()
    tasks = FakeTaskSource(chamados={"13.33.1": ["123123"], "14.0.0": []})
    commits = FakeCommitSource(por_chamado={
        "123123": [CommitRef(hash_origem="a0", parent="m0", chamado="123123",
                             commit_date=D, msg="ch123123 alfa")]
    })
    estado = _estado_com_repo()
    # base gravada na criacao: m0. Sem isso o BaseResolver resolveria "master",
    # que hoje aponta para a0 — e o commit apareceria como ja presente.
    estado.registrar_versao("r", VersaoInfo(numero="14.0.0", tipo=VersionType.FECHADA,
                                            base_ref="master", base_commit="m0"))

    status = verificar(_deps(git, tasks, commits, estado), "14.0.0")

    # marcada para 13.33.1, cobrada na 14.0.0
    assert [c.hash_origem for c in status.faltantes] == ["a0"]


def test_verificar_congela_versao_quando_a_tag_aparece():
    git = _git(tags={"13.34.0": True})
    estado = _estado_com_repo()
    estado.registrar_versao("r", VersaoInfo(numero="13.34.0", tipo=VersionType.AJUSTADA,
                                            base_ref="13.33.0", base_commit="m0"))
    estado.substituir_atribuicoes("r", "13.34.0", [
        Atribuicao(chamado="123456", marcada="13.34.0", estado="aplicado",
                   commits=["a0"])
    ])

    status = verificar(_deps(git, FakeTaskSource(), FakeCommitSource(), estado),
                       "13.34.0")

    assert estado.versao("r", "13.34.0").liberada_em is not None
    # devolve o snapshot congelado, nao recalcula
    assert status.verde is True
    assert status.tasks_novas == []


def test_verificar_nao_grava_em_versao_liberada():
    git = _git(tags={"13.34.0": True})
    estado = _estado_com_repo()
    estado.registrar_versao("r", VersaoInfo(numero="13.34.0", tipo=VersionType.AJUSTADA,
                                            base_ref="13.33.0", base_commit="m0"))
    tasks = FakeTaskSource(chamados={"13.34.0": ["999111"]})

    verificar(_deps(git, tasks, FakeCommitSource(), estado), "13.34.0")

    # a trava do fake nao disparou => nao tentou escrever
    assert estado.atribuicoes("r", "13.34.0") == []


def test_verificar_ignora_tag_de_versao_que_o_motor_nunca_viu():
    git = _git(tags={"13.33.1": True})
    estado = _estado_com_repo()
    estado.registrar_versao("r", VersaoInfo(numero="14.0.0", tipo=VersionType.FECHADA,
                                            base_ref="master", base_commit="m0"))

    verificar(_deps(git, FakeTaskSource(), FakeCommitSource(), estado), "14.0.0")

    # nada a congelar: sem linha no estado, nao ha snapshot para proteger
    assert estado.versao("r", "13.33.1") is None
```

- [ ] **Step 6: Rodar e confirmar que falha**

Run: `uv run pytest tests/test_verificar.py -v`
Expected: FAIL — `Deps` não aceita `estado`.

- [ ] **Step 7: Extrair a varredura de trailers**

Criar `motor/services/reconstrutor.py` com a lógica que estava em `LockStore.reconstruir` (`lock_store.py:103-162`):

```python
"""Reconstrucao do estado a partir dos trailers de cherry-pick no git.

O trailer `-x` e o backbone duravel: o estado no banco e uma projecao rapida
por cima dele. Se o banco for perdido, isto regenera as atribuicoes.
"""

from __future__ import annotations

from motor.domain.commits import extrair_chamado
from motor.domain.types import Atribuicao
from motor.errors import MotorError
from motor.ports import GitRepo

_MARCA = "(cherry picked from commit "


def extrair_trailer(msg: str) -> str | None:
    i = msg.find(_MARCA)
    if i < 0:
        return None
    resto = msg[i + len(_MARCA) :]
    fim = resto.find(")")
    return None if fim < 0 else resto[:fim]


def reconstruir_atribuicoes(
    git: GitRepo, base_commit: str, branch: str
) -> tuple[list[Atribuicao], list[str]]:
    """Varre base..branch e reagrupa por chamado.

    Devolve (atribuicoes, orfaos) — orfao e commit sem `ch<num>` na mensagem,
    que nao e atribuivel a tarefa nenhuma e precisa de julgamento humano.
    """
    try:
        commits = git.commits_in_range(base_commit, branch)
    except Exception as e:
        raise MotorError(f"varrendo commits: {e}") from e

    por_chamado: dict[str, list[str]] = {}
    orfaos: list[str] = []

    for c in commits:
        origem = extrair_trailer(c.msg)
        if origem is None:
            # commit direto na branch: ele mesmo e a origem
            origem, meta = c.hash_origem, c
        else:
            try:
                meta = git.commit_meta(origem)
            except Exception:
                continue  # origem sumiu do historico

        chamado = extrair_chamado(meta.msg)
        if chamado is None:
            orfaos.append(origem)
            continue
        por_chamado.setdefault(chamado, []).append(origem)

    atribuicoes = [
        Atribuicao(
            chamado=chamado, marcada="", estado="aplicado", commits=sorted(hashes)
        )
        for chamado, hashes in sorted(por_chamado.items())
    ]
    return atribuicoes, sorted(set(orfaos))
```

- [ ] **Step 8: Reescrever `Deps` e `verificar`**

`motor/engine/deps.py`:

```python
"""Dependencias injetadas nas operacoes."""

from __future__ import annotations

from dataclasses import dataclass

from motor.ports import CommitSource, EstadoRepo, GitRepo, TaskSource


@dataclass
class Deps:
    git: GitRepo
    tasks: TaskSource
    estado: EstadoRepo
    repo: str = ""  # nome canonico do repo, resolvido no __main__
    bitbucket_token: str = ""  # se presente, PR do Bitbucket vira fonte primaria
    bitbucket_email: str = ""  # email da conta dona do token (Basic auth)
    # injetavel nos testes; em producao e montado por _montar_commit_source
    _commit_source: CommitSource | None = None
```

`motor/engine/verificar.py`, substituir a função `verificar` (linhas 43-104):

```python
def verificar(deps: Deps, versao: str) -> VersionStatus:
    """Cruza Tickio x estado x git e devolve o VersionStatus.

    Versao com tag e congelada: devolve o snapshot do banco sem recalcular
    nada. Nao muta dados do usuario — so avanca a branch local ate o que ja
    esta publicado, para nao cruzar contra estado desatualizado.
    """
    inicio = time.monotonic()

    todas = deps.git.list_version_branches()
    tags = deps.git.list_version_tags()
    abertas = versoes_abertas(todas, tags)

    # Congela o que ganhou tag desde o ultimo run. A data e a do commit
    # apontado pela tag, nao a de agora: senao registraria quando o comando
    # rodou, nao quando a versao foi liberada.
    liberadas: dict[str, datetime.datetime] = {}
    for numero in tags:
        conhecida = deps.estado.versao(deps.repo, numero)
        # Versao que o motor nunca operou nao tem snapshot a proteger.
        if conhecida is not None and conhecida.liberada_em is None:
            meta = deps.git.commit_meta(deps.git.resolve_ref(f"refs/tags/{numero}"))
            liberadas[numero] = meta.commit_date
    if liberadas:
        deps.estado.marcar_liberadas(deps.repo, liberadas)

    info = deps.estado.versao(deps.repo, versao)
    if info is not None and info.liberada_em is not None:
        return _snapshot_congelado(deps, versao)

    deps.git.fetch("origin")
    deps.git.use_worktree(versao)
    if deps.git.remote_branch_exists("origin", versao):
        deps.git.pull_branch("origin", versao)

    if info is None:
        # Primeira vez que o motor ve esta versao: resolve e grava a base.
        resolvida = BaseResolver(git=deps.git).resolve(versao)
        deps.estado.registrar_versao(
            deps.repo,
            VersaoInfo(
                numero=versao,
                tipo=inferir_tipo(versao),
                base_ref=resolvida.ref,
                base_commit=resolvida.commit,
            ),
        )
        base_commit = resolvida.commit
    else:
        # A base gravada e a autoritativa. Recomputar faria a base de uma
        # X.0.0 seguir o tip atual do master em vez do ponto de corte, e o
        # oraculo passaria a considerar presente tudo que entrou depois.
        base_commit = info.base_commit

    fonte = deps._commit_source or _montar_commit_source(deps)
    resolver = TargetResolver(tasks=deps.tasks, commits=fonte)
    resultado = resolver.resolve(versao, sorted({*abertas, versao}, key=chave))
    logger.debug("resolver.resolve: %.3fs", time.monotonic() - inicio)

    alvo = filtrar_excluidos(
        resultado.tasks, deps.estado.exclusoes(deps.repo), versao
    )

    # ANTES de sobrescrever: e o que detecta tarefa desmarcada no Tickio.
    anteriores = deps.estado.atribuicoes(deps.repo, versao)

    todos_os_hashes: dict[str, CommitRef] = {}
    candidatos_conflito: set[str] = set()
    for tt in alvo.values():
        for c in tt.commits:
            todos_os_hashes[c.hash_origem] = c
            candidatos_conflito.add(c.hash_origem)
    for a in anteriores:
        for h in a.commits:
            todos_os_hashes.setdefault(h, CommitRef(hash_origem=h))

    oracle = PresenceOracle(git=deps.git)
    tip = deps.git.resolve_ref(versao)

    t = time.monotonic()
    presentes: dict[str, Presence] = {}
    conflitantes: list[CommitRef] = []
    suspeitos_conteudo: list[CommitRef] = []
    for hash_, c in todos_os_hashes.items():
        p = oracle.presente(hash_, base_commit, versao)
        presentes[hash_] = p
        if p == Presence.AUSENTE and hash_ in candidatos_conflito:
            if oracle.suspeita_por_conteudo(hash_, base_commit, versao) is not None:
                suspeitos_conteudo.append(c)
            meta = deps.git.commit_meta(hash_)
            pred = deps.git.predict_merge(meta.parent, tip, hash_)
            if pred.conflita:
                conflitantes.append(c)
    logger.debug(
        "oraculo de presenca: %.3fs (%d commits)",
        time.monotonic() - t,
        len(todos_os_hashes),
    )

    status = reconciliar(
        replace(resultado, tasks=alvo),
        anteriores,
        deps.estado.sem_entrega(deps.repo),
        presentes,
        conflitantes,
        suspeitos_conteudo,
    )

    deps.estado.substituir_atribuicoes(
        deps.repo, versao, atribuicoes_de(alvo, presentes)
    )

    logger.debug("verificar total: %.3fs", time.monotonic() - inicio)
    return status


def _snapshot_congelado(deps: Deps, versao: str) -> VersionStatus:
    """Versao liberada nao recalcula: o alvo dela congelou na tag. Se algo
    ficou de fora, a tarefa e remarcada para a proxima versao (spec §2).
    """
    anteriores = deps.estado.atribuicoes(deps.repo, versao)
    return VersionStatus(
        verde=all(a.estado == "aplicado" for a in anteriores),
        estado_integro=True,
    )
```

Imports novos no topo de `verificar.py`:

```python
import datetime
from dataclasses import replace

from motor.domain.reconcile import atribuicoes_de, filtrar_excluidos, reconciliar
from motor.domain.types import CommitRef, Presence, VersaoInfo, VersionStatus
from motor.domain.version import chave, inferir_tipo, versoes_abertas
from motor.services.base_resolver import BaseResolver
```

- [ ] **Step 9: Deletar o lock store**

```bash
git rm motor/services/lock_store.py tests/test_lock_store.py
```

- [ ] **Step 10: Rodar**

Run: `uv run pytest tests/test_verificar.py tests/test_reconcile.py -v`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat(engine): verificar cruza contra o estado e congela versao com tag

Versao liberada devolve o snapshot do banco sem recalcular. O estado anterior
e lido ANTES de sobrescrever — e o que detecta tarefa desmarcada no Tickio.
LockStore deletado; a varredura de trailers vira services/reconstrutor.py."
```

---

### Task 9: `atualizar`, `criar` e a recusa em versão com tag

**Files:**
- Modify: `motor/engine/atualizar.py`, `motor/engine/criar.py`, `motor/services/publication_gate.py`
- Test: `tests/test_incrementar.py`, `tests/test_criar.py`, `tests/test_publication_gate.py` (remover os skips)

**Interfaces:**
- Consumes: `verificar`, `Deps`, `PublicationGate` (Task 8)
- Produces:
  - `PublicationGate.liberada(versao: str) -> bool`
  - `PublicationGate.publicada(versao: str) -> bool` (mantida: tag OU branch remota)
  - `atualizar(deps, versao) -> AtualizarResult` — recusa versão com tag

- [ ] **Step 1: Escrever os testes que falham**

Adicionar a `tests/test_publication_gate.py`:

```python
def test_liberada_e_so_a_tag_nao_a_branch_remota():
    git = FakeGit(tags={"13.34.0": True}, remotes={"14.0.0": True})
    gate = PublicationGate(git=git)

    assert gate.liberada("13.34.0") is True
    # branch remota nao e liberacao: e so trabalho compartilhado
    assert gate.liberada("14.0.0") is False
    assert gate.publicada("14.0.0") is True
```

Adicionar a `tests/test_incrementar.py`:

```python
def test_atualizar_recusa_versao_com_tag():
    git = FakeGit(branches={"13.34.0": "b1"}, tags={"13.34.0": True})
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})
    deps = Deps(git=git, tasks=FakeTaskSource(), estado=estado, repo="r",
                _commit_source=FakeCommitSource())

    with pytest.raises(MotorError, match="liberada"):
        atualizar(deps, "13.34.0")
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/test_publication_gate.py tests/test_incrementar.py -v`
Expected: FAIL — `PublicationGate` não tem `liberada`; `atualizar` não recusa.

- [ ] **Step 3: Implementar o gate**

`motor/services/publication_gate.py`, substituir inteiro:

```python
"""Travas de publicacao (spec §2, §6)."""

from __future__ import annotations

from dataclasses import dataclass

from motor.ports import GitRepo


@dataclass
class PublicationGate:
    git: GitRepo

    def liberada(self, versao: str) -> bool:
        """Tag existe = versao liberada = congelada.

        So a tag conta. Branch remota e trabalho compartilhado, nao liberacao —
        confundir os dois travaria uma versao ainda em construcao.
        """
        return self.git.tag_exists(versao)

    def publicada(self, versao: str) -> bool:
        """Tag OU branch remota: proibe rebuild, que reescreveria historia que
        outra maquina ja tem."""
        if self.git.tag_exists(versao):
            return True
        return self.git.remote_branch_exists("origin", versao)
```

- [ ] **Step 4: Implementar a recusa e adaptar `atualizar`**

`motor/engine/atualizar.py`: no topo de `atualizar`, antes do `verificar`:

```python
def atualizar(deps: Deps, versao: str) -> AtualizarResult:
    """Aplica os commits faltantes por commit-date asc.

    Versao com tag e recusada: o alvo dela congelou na liberacao, e alteracao
    na branch nao reflete no que a tag aponta. Esquecimento vai para a proxima
    versao (spec §2).
    """
    if PublicationGate(git=deps.git).liberada(versao):
        raise MotorError(
            f"versao {versao} ja liberada (tem tag) — remarque a tarefa "
            "para a proxima versao em construcao"
        )

    status = verificar(deps, versao)
```

Remover o bloco `if status.ancestrais:` (linhas 55-68) — as exclusões automáticas deixaram de existir; o oráculo de presença responde isso a cada run.

Substituir o registro de lock por registro de atribuições. `_registrar_commit` sai; no lugar, ao fim do lote bem-sucedido:

```python
    # O estado ja foi gravado pelo verificar no comeco; regrava com os picks
    # aplicados para o `estado` das atribuicoes refletir a realidade.
    aplicadas = [
        replace(a, estado="aplicado")
        for a in deps.estado.atribuicoes(deps.repo, versao)
    ]
    deps.estado.substituir_atribuicoes(deps.repo, versao, aplicadas)

    deps.git.push_branch("origin", versao)
    deps.git.worktree_remove(versao)
    return AtualizarResult(
        status=AtualizarStatus.DONE, aplicados=aplicados, ja_presentes=ja_presentes
    )
```

`atualizar_continue`: substituir a reconstrução via `LockStore` (linhas 132-142) por `verificar`, que já regrava o estado a partir do git:

```python
def atualizar_continue(deps: Deps, versao: str) -> AtualizarResult:
    """Retoma um cherry-pick resolvido manualmente.

    Invocacao nova do CLI, sem contexto em memoria de quais commits do lote ja
    foram aplicados. Nao precisa reconstruir nada a mao: o `atualizar` abaixo
    chama `verificar`, que reprojeta o estado a partir do git de verdade.
    """
    deps.git.use_worktree(versao)
    _, ok = deps.git.pending_cherry_pick()
    if not ok:
        raise MotorError("nenhum cherry-pick pendente pra continuar")

    deps.git.continue_cherry_pick()
    return atualizar(deps, versao)
```

- [ ] **Step 5: Adaptar `criar`**

`motor/engine/criar.py`, substituir o corpo:

```python
def criar(deps: Deps, versao: str) -> AtualizarResult:
    """Monta uma versao do zero. Branch nova e nao publicada."""
    gate = PublicationGate(git=deps.git)
    if gate.publicada(versao):
        raise MotorError(f"versao {versao} ja publicada - use atualizar")

    base = BaseResolver(git=deps.git).resolve(versao)

    deps.git.worktree_add(versao, base.commit)
    deps.git.write_file(
        versao, "VERSAO", f"{versao}\n".encode(), f"Atualiza VERSAO para {versao}"
    )

    # A versao entra no estado aqui; o verificar dentro do atualizar preenche
    # as atribuicoes.
    deps.estado.registrar_versao(
        deps.repo,
        VersaoInfo(
            numero=versao,
            tipo=inferir_tipo(versao),
            base_ref=base.ref,
            base_commit=base.commit,
        ),
    )

    return atualizar(deps, versao)
```

- [ ] **Step 6: Remover `Lock` do domínio**

Este é o commit em que o último consumidor de `Lock` é reescrito, então é aqui que ele sai. Em `motor/domain/types.py`, apagar a dataclass `Lock` (linha 73 do arquivo original) e conferir que nenhum import sobrou:

Run: `grep -rn "\bLock\b" motor tests | grep -v "\.lock"`
Expected: nenhuma saída.

Se `TargetSet` ou `BaseRef` tiverem ficado sem uso depois disso, deixá-los — ambos continuam sendo usados por `TaskTarget` e `VersaoInfo`.

- [ ] **Step 7: Rodar**

Run: `uv run pytest -v -m "not integracao"`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(engine): atualizar recusa versao com tag; criar registra no estado

Inverte o §6 antigo: in-place em versao tagueada era o modo permitido, agora
e o proibido. PublicationGate ganha `liberada` (so tag) ao lado de `publicada`
(tag ou branch remota) — confundir os dois travaria versao em construcao."
```

---

### Task 10: `reconstruir-estado`

**Files:**
- Rename: `motor/engine/reconstruir_lock.py` → `motor/engine/reconstruir_estado.py`
- Test: `tests/test_reconstruir_lock.py` → `tests/test_reconstruir_estado.py`

**Interfaces:**
- Consumes: `reconstruir_atribuicoes` (Task 8), `Deps`, `BaseResolver`
- Produces: `reconstruir_estado(deps: Deps, versao: str) -> ReconstructResult` com `ReconstructResult(status, orfaos: list[str])`

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_reconstruir_estado.py`:

```python
from __future__ import annotations

import datetime

from motor.adapters.commitsource.fake import FakeCommitSource
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import CommitRef, RepoInfo
from motor.engine.deps import Deps
from motor.engine.reconstruir_estado import ReconstructStatus, reconstruir_estado


def _deps(git, estado) -> Deps:
    return Deps(git=git, tasks=FakeTaskSource(), estado=estado, repo="r",
                _commit_source=FakeCommitSource())


D = datetime.datetime(2026, 1, 1)


def _git_com_pick(msg_do_pick: str, msg_da_origem: str | None = None) -> FakeGit:
    """13.33.0 e a base; 13.34.0 tem um commit acima dela.

    commits_in_range para em base, entao so o commit do pick e varrido.
    """
    git = FakeGit(tags={"13.33.0": True})
    git.add_commit("base", "", "raiz", D)
    git.add_commit("p1", "base", msg_do_pick, D)
    if msg_da_origem is not None:
        git.add_commit("aaa", "", msg_da_origem, D)
    git.set_branch("13.33.0", "base")
    git.set_branch("13.34.0", "p1")
    return git


def test_reconstroi_atribuicoes_dos_trailers():
    git = _git_com_pick(
        "ch123456 alfa\n\n(cherry picked from commit aaa)",
        msg_da_origem="ch123456 alfa",
    )
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})

    resultado = reconstruir_estado(_deps(git, estado), "13.34.0")

    assert resultado.status == ReconstructStatus.DONE
    atribuicoes = estado.atribuicoes("r", "13.34.0")
    assert [a.chamado for a in atribuicoes] == ["123456"]
    # guarda o hash de ORIGEM, nao o do pick — o pick e local desta branch
    assert atribuicoes[0].commits == ["aaa"]


def test_commit_direto_na_branch_e_sua_propria_origem():
    git = _git_com_pick("ch123456 alfa")
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})

    reconstruir_estado(_deps(git, estado), "13.34.0")

    assert estado.atribuicoes("r", "13.34.0")[0].commits == ["p1"]


def test_commit_sem_chamado_vira_orfao():
    git = _git_com_pick("ajuste solto sem identificador")
    estado = FakeEstado(repos={"r": RepoInfo(nome="r", tickio_sistema_id=1)})

    resultado = reconstruir_estado(_deps(git, estado), "13.34.0")

    assert resultado.status == ReconstructStatus.PENDING_JUDGMENT
    assert resultado.orfaos == ["p1"]
```

`CommitRef` não é usado neste arquivo — remover o import se o linter reclamar. A base de `13.34.0` sai do `inferir_base` (`13.33.0`, que existe como tag), então o `BaseResolver` resolve `refs/tags/13.33.0` — daí o `resolve_ref` da Task 1 precisar aceitar ref qualificada.

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/test_reconstruir_estado.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'motor.engine.reconstruir_estado'`.

- [ ] **Step 3: Implementar**

```bash
git mv motor/engine/reconstruir_lock.py motor/engine/reconstruir_estado.py
git rm tests/test_reconstruir_lock.py
```

Substituir o conteúdo de `motor/engine/reconstruir_estado.py`:

```python
"""Regenera as atribuicoes a partir do git quando o estado e perdido.

Operacao de recuperacao, fora do fluxo principal. Nunca interativa:
PENDING_JUDGMENT e valor de retorno, quem pergunta ao humano e o front-end.
Nao recupera exclusoes nem sem_entrega — julgamento humano so vive no banco.

Numa versao ja congelada (liberada_em preenchida) a trigger recusa a escrita.
Recuperar o snapshot de uma versao liberada exige apagar a linha primeiro:
  delete from versao where repo_id = ... and numero = '13.34.0';
Depois rode reconstruir-estado e so entao verificar, que reobserva a tag e
congela de novo. A ordem importa: verificar antes congelaria o estado vazio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from motor.domain.types import VersaoInfo
from motor.domain.version import inferir_tipo
from motor.engine.deps import Deps
from motor.services.base_resolver import BaseResolver
from motor.services.reconstrutor import reconstruir_atribuicoes


class ReconstructStatus(IntEnum):
    DONE = 0
    PENDING_JUDGMENT = 1


@dataclass
class ReconstructResult:
    status: ReconstructStatus
    orfaos: list[str] = field(default_factory=list)


def reconstruir_estado(deps: Deps, versao: str) -> ReconstructResult:
    info = deps.estado.versao(deps.repo, versao)
    if info is None:
        resolvida = BaseResolver(git=deps.git).resolve(versao)
        deps.estado.registrar_versao(
            deps.repo,
            VersaoInfo(
                numero=versao,
                tipo=inferir_tipo(versao),
                base_ref=resolvida.ref,
                base_commit=resolvida.commit,
            ),
        )
        base_commit = resolvida.commit
    else:
        # Mesma regra do verificar: a base gravada manda.
        base_commit = info.base_commit

    atribuicoes, orfaos = reconstruir_atribuicoes(deps.git, base_commit, versao)
    deps.estado.substituir_atribuicoes(deps.repo, versao, atribuicoes)

    if orfaos:
        return ReconstructResult(status=ReconstructStatus.PENDING_JUDGMENT, orfaos=orfaos)
    return ReconstructResult(status=ReconstructStatus.DONE)
```

- [ ] **Step 4: Rodar**

Run: `uv run pytest -v -m "not integracao"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(engine): reconstruir-lock vira reconstruir-estado

Mesma varredura de trailers, destino diferente. Commit sem ch<num> vira orfao
reportado — sem o VB-xxxx nao ha mais fallback de identidade."
```

---

### Task 11: Adapter TickioRest

**Files:**
- Create: `motor/adapters/tasksource/tickio.py`
- Test: `tests/test_tasksource_tickio.py`

**Interfaces:**
- Consumes: `TaskSource` Protocol (Task 2)
- Produces: `TickioRest(base_url, usuario, senha, sistema_id, client=None)` com `fetch(versao) -> list[str]`

> **Pendência conhecida:** o corpo de `GET /api/v1/ws/versoes/chamados/` ainda não foi visto. A implementação abaixo isola a leitura em `_extrair_chamados`, que aceita as três formas plausíveis (lista de números, lista de objetos com `chamado`, ou envelope paginado com `results`). Quando a resposta real aparecer, **só essa função muda** — e o teste correspondente vira o formato confirmado.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/test_tasksource_tickio.py`:

```python
from __future__ import annotations

import httpx
import pytest

from motor.adapters.tasksource.tickio import TickioRest
from motor.errors import MotorError


def _fonte(handler, **kwargs) -> TickioRest:
    client = httpx.Client(transport=httpx.MockTransport(handler),
                          base_url="http://testserver")
    return TickioRest(base_url="http://testserver", usuario="u", senha="p",
                      sistema_id=1, client=client, **kwargs)


def test_autentica_e_busca_chamados():
    chamadas = []

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append(str(request.url))
        if request.url.path == "/api/v1/ws/token/":
            return httpx.Response(200, json={"access": "tok", "refresh": "ref"})
        assert request.headers["Authorization"] == "Bearer tok"
        assert request.url.params["sistema"] == "1"
        assert request.url.params["versao"] == "13.34.0"
        return httpx.Response(200, json=[{"chamado": "123456"}, {"chamado": "999111"}])

    assert _fonte(handler).fetch("13.34.0") == ["123456", "999111"]
    assert chamadas[0].endswith("/api/v1/ws/token/")


def test_aceita_lista_crua_de_numeros():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ws/token/":
            return httpx.Response(200, json={"access": "tok"})
        return httpx.Response(200, json=[123456, "999111"])

    assert _fonte(handler).fetch("13.34.0") == ["123456", "999111"]


def test_aceita_envelope_paginado():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ws/token/":
            return httpx.Response(200, json={"access": "tok"})
        return httpx.Response(200, json={"results": [{"chamado": "123456"}],
                                         "next": None})

    assert _fonte(handler).fetch("13.34.0") == ["123456"]


def test_autentica_uma_vez_so_por_instancia():
    tokens = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ws/token/":
            tokens.append(1)
            return httpx.Response(200, json={"access": "tok"})
        return httpx.Response(200, json=[])

    fonte = _fonte(handler)
    fonte.fetch("13.34.0")
    fonte.fetch("14.0.0")
    assert len(tokens) == 1


def test_credencial_invalida_vira_motorerror():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="credenciais invalidas")

    with pytest.raises(MotorError, match="autenticando no Tickio"):
        _fonte(handler).fetch("13.34.0")


def test_erro_na_listagem_vira_motorerror():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/ws/token/":
            return httpx.Response(200, json={"access": "tok"})
        return httpx.Response(500, text="boom")

    with pytest.raises(MotorError, match="500"):
        _fonte(handler).fetch("13.34.0")
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/test_tasksource_tickio.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'motor.adapters.tasksource.tickio'`.

- [ ] **Step 3: Implementar**

Criar `motor/adapters/tasksource/tickio.py`:

```python
"""TickioRest: fonte de tarefas do Tickio.

Autentica por credencial a cada processo em vez de usar um access token colado
no .env — o CLI vive segundos, entao re-autenticar sai mais barato que refazer
o .env toda vez que o JWT expira. O refresh token nao e usado pelo mesmo
motivo: ele existe para processo longo que nao quer reter credencial.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from motor.errors import MotorError

_ROTA_TOKEN = "/api/v1/ws/token/"
_ROTA_CHAMADOS = "/api/v1/ws/versoes/chamados/"


@dataclass
class TickioRest:
    base_url: str
    usuario: str
    senha: str
    sistema_id: int
    client: httpx.Client | None = None
    _access: str = field(default="", init=False)

    def fetch(self, versao: str) -> list[str]:
        cliente = self.client if self.client is not None else httpx.Client()
        token = self._autenticar(cliente)

        try:
            resp = cliente.get(
                f"{self.base_url}{_ROTA_CHAMADOS}",
                params={"sistema": self.sistema_id, "versao": versao},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as e:
            raise MotorError(f"buscando chamados da versao {versao} no Tickio: {e}") from e

        if resp.status_code != 200:
            raise MotorError(
                f"Tickio respondeu {resp.status_code} ao listar a versao {versao}: {resp.text}"
            )

        try:
            corpo = resp.json()
        except ValueError as e:
            raise MotorError(f"decodificando resposta do Tickio: {e}") from e

        return _extrair_chamados(corpo)

    def _autenticar(self, cliente: httpx.Client) -> str:
        if self._access:
            return self._access
        try:
            resp = cliente.post(
                f"{self.base_url}{_ROTA_TOKEN}",
                json={"username": self.usuario, "password": self.senha},
            )
        except httpx.HTTPError as e:
            raise MotorError(f"autenticando no Tickio: {e}") from e

        if resp.status_code != 200:
            raise MotorError(
                f"autenticando no Tickio: respondeu {resp.status_code}: {resp.text}"
            )

        access = (resp.json() or {}).get("access", "")
        if not access:
            raise MotorError("autenticando no Tickio: resposta sem campo 'access'")
        self._access = access
        return access


def _extrair_chamados(corpo) -> list[str]:
    """Le a lista de chamados do corpo da resposta.

    PENDENTE: o formato real ainda nao foi visto. Aceita as tres formas
    plausiveis; quando a resposta chegar, so esta funcao muda.
    """
    itens = corpo.get("results", []) if isinstance(corpo, dict) else corpo
    if not isinstance(itens, list):
        raise MotorError(f"resposta do Tickio em formato inesperado: {type(corpo)}")

    chamados: list[str] = []
    for item in itens:
        if isinstance(item, dict):
            valor = item.get("chamado") or item.get("numero")
        else:
            valor = item
        if valor is None:
            raise MotorError(f"item sem numero de chamado na resposta do Tickio: {item!r}")
        chamados.append(str(valor))
    return chamados
```

- [ ] **Step 4: Rodar**

Run: `uv run pytest tests/test_tasksource_tickio.py -v`
Expected: PASS, 6 testes.

- [ ] **Step 5: Commit**

```bash
git add motor/adapters/tasksource/tickio.py tests/test_tasksource_tickio.py
git commit -m "feat(adapters): TickioRest com autenticacao por credencial

POST /token/ uma vez por processo; refresh fora de escopo — o CLI vive
segundos. O parsing do corpo esta isolado em _extrair_chamados e aceita as
tres formas plausiveis ate a resposta real ser conhecida."
```

---

### Task 12: CLI

**Files:**
- Modify: `motor/__main__.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: tudo das tasks anteriores
- Produces: comandos `verificar`, `criar`, `atualizar`, `reconstruir-estado`

- [ ] **Step 1: Escrever os testes que falham**

Adicionar a `tests/test_main.py`:

```python
def test_comando_desconhecido_sai_com_erro(capsys):
    import pytest as _pytest

    from motor.__main__ import main

    with _pytest.raises(SystemExit) as saida:
        main(["inexistente", "13.34.0", "--repo", "/tmp"])
    assert saida.value.code != 0


def test_reconstruir_estado_esta_no_parser():
    from motor.__main__ import _build_parser

    acoes = _build_parser()._subparsers._group_actions[0].choices
    assert "reconstruir-estado" in acoes
    assert "reconstruir-lock" not in acoes
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `uv run pytest tests/test_main.py -v`
Expected: FAIL — `reconstruir-estado` ainda não existe no parser.

- [ ] **Step 3: Implementar**

`motor/__main__.py`, substituir os pontos abaixo.

Parser — trocar o subcomando e as flags de fonte:

```python
    sub.add_parser("reconstruir-estado", parents=[comum],
                   help="regenera as atribuicoes a partir do git")
```

Em `p_criar`, substituir `--clickup-token` e `--task-source`:

```python
    p_criar.add_argument("--task-source", dest="fonte_flag", default="tickio",
                         choices=["tickio", "manual"],
                         help="fonte das tasks (default: tickio)")
    p_criar.add_argument("--lista", dest="lista_manual", default="",
                         help="arquivo de lista (obrigatorio com --task-source=manual)")
```

Montagem das dependências, substituindo o bloco das linhas 160-183:

```python
    try:
        git_repo = new_git_subprocess(repo)

        engine = create_engine(database_url())
        with Session(engine) as sessao:
            estado = PostgresEstado(sessao=sessao)
            info = estado.resolver_repo(os.path.basename(repo))

            if getattr(args, "fonte_flag", "tickio") == "tickio":
                tasks = TickioRest(
                    base_url=os.environ.get("TICKIO_BASE_URL", ""),
                    usuario=os.environ.get("TICKIO_USER", ""),
                    senha=os.environ.get("TICKIO_PASSWORD", ""),
                    sistema_id=info.tickio_sistema_id,
                )
            else:
                if not args.lista_manual:
                    print("--lista e obrigatorio quando --task-source=manual",
                          file=sys.stderr)
                    sys.exit(1)
                tasks = ManualList(caminho=args.lista_manual)

            deps = Deps(
                git=git_repo,
                tasks=tasks,
                estado=estado,
                repo=info.nome,
                bitbucket_token=getattr(args, "bitbucket_token", ""),
                bitbucket_email=getattr(args, "bitbucket_email", ""),
            )
            _despachar(args, deps)
    except MotorError as e:
        logging.error(str(e))
        sys.exit(1)
    except Exception:
        logging.exception("Erro interno fatal (bug). Traceback completo:")
        sys.exit(1)
```

Extrair o despacho para `_despachar(args, deps)` com o corpo que hoje está nas linhas 185-203, trocando `reconstruir_lock` por `reconstruir_estado` e ajustando o print dos órfãos (agora `list[str]`):

```python
def _despachar(args, deps: Deps) -> None:
    inicio = time.monotonic()
    if args.comando == "verificar":
        imprimir_status(verificar(deps, args.versao))
    elif args.comando == "criar":
        imprimir_atualizacao(criar(deps, args.versao))
    elif args.comando == "atualizar":
        if args.abortar:
            atualizar_abort(deps, args.versao)
            print("abortado")
        elif args.continuar:
            imprimir_atualizacao(atualizar_continue(deps, args.versao))
        else:
            imprimir_atualizacao(atualizar(deps, args.versao))
    else:  # reconstruir-estado
        resultado = reconstruir_estado(deps, args.versao)
        print(f"status: {resultado.status.name}, orfaos: {len(resultado.orfaos)}")
        for hash_ in resultado.orfaos:
            print(f"  - {hash_[:8]} (sem ch<num> na mensagem)")
    logging.debug("comando '%s' concluido em %.3fs", args.comando,
                  time.monotonic() - inicio)
```

Em `imprimir_status`, trocar `lock` por `estado` e imprimir as ambíguas:

```python
def imprimir_status(s: VersionStatus) -> None:
    print(f"verde: {s.verde}")
    print(f"tasks novas: {s.tasks_novas}")
    print(f"tasks removidas: {s.tasks_removidas}")
    if s.tasks_ambiguas:
        print(f"tasks marcadas em mais de uma versao: {s.tasks_ambiguas}")
        print("  (dado inconsistente no Tickio - corrija a marcacao)")
    if s.tasks_sem_commits:
        print(f"tasks sem commits: {s.tasks_sem_commits}")
        print("  (nenhum commit/PR achado - registre em sem_entrega se for proposital)")
    if not s.estado_integro:
        print(f"estado: divergente do git ({len(s.commits_sumidos)} commits sumidos)")
        for hash_ in s.commits_sumidos:
            print(f"  - {hash_[:8]}")
    else:
        print("estado: integro")
    conflitantes = {c.hash_origem for c in s.conflitantes}
    suspeitos = {c.hash_origem for c in s.suspeitos_conteudo}
    _imprimir_commits_por_task("faltantes", s.faltantes, conflitantes, suspeitos)
```

Imports novos no topo:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from motor.adapters.estado.postgres import PostgresEstado
from motor.adapters.tasksource.tickio import TickioRest
from motor.config import database_url
from motor.engine.reconstruir_estado import reconstruir_estado
```

Remover os imports de `ClickUpRest` e `reconstruir_lock`.

- [ ] **Step 4: Rodar a suíte**

Run: `uv run pytest -v -m "not integracao"`
Expected: PASS.

- [ ] **Step 5: Fumaça de ponta a ponta**

```bash
docker compose up -d
uv run alembic upgrade head
docker compose exec db psql -U motor -d monitor_versoes -c \
  "insert into repo (nome, tickio_sistema_id) values ('vendabemweb', 1) on conflict do nothing;"
uv run python -m motor verificar 13.34.0 --repo vendabemweb --debug
```
Expected: o comando roda ponta a ponta. Se o Tickio recusar autenticação, conferir `TICKIO_USER`/`TICKIO_PASSWORD` no `.env`.

- [ ] **Step 6: Commit**

```bash
git add motor/__main__.py tests/test_main.py
git commit -m "feat(cli): liga Tickio, Postgres e reconstruir-estado

--task-source default vira tickio; o repo e resolvido no banco (nome ou
alias) e o tickio_sistema_id sai de la para o adapter."
```

---

### Task 13: Reescrever o documento de desenho

**Files:**
- Modify: `ferramenta_versoes_design.md`

`ferramenta_versoes_design.md` descreve ClickUp como fonte, `VERSAO.lock` commitado na branch e `atualizar` permitido em versão tagueada. As três premissas se invertem neste redesenho; deixá-lo como está é armadilha para quem ler primeiro.

- [ ] **Step 1: Atualizar as seções invertidas**

| Seção | O que muda |
|---|---|
| Cabeçalho | stack Go → Python; remover "sem implementação" |
| §2 (oráculo) | tabela de fontes: ClickUp → Tickio; `VERSAO.lock` → estado em Postgres |
| §3 (formato do lock) | substituir pelo schema da spec nova, com ponteiro para ela |
| §4 (resolução do alvo) | substituir pela regra de distribuição (spec §2); remover o bloqueador do MCP do ClickUp |
| §5 (operações) | `atualizar` deixa de ser permitido em versão tagueada |
| §6 (regra de publicação) | separar `liberada` (só tag, congela) de `publicada` (tag ou branch remota, proíbe rebuild) |
| §9 (reconciliação) | trocar "ClickUp" por "Tickio" e "lock" por "estado" nas cinco linhas da tabela |
| §10 (dependências) | remover token do ClickUp e a convenção `VB-<num>`; identidade é só `ch<num>` |
| §11 (multi-projeto) | `?sistema=` vira o corte principal; existência de commit no repo passa a ser rede |
| §13 (roadmap) | Etapa 1 concluída; stack Python |
| §14 (arquitetura) | adicionar a porta `EstadoRepo` ao diagrama e à lista de portas |

- [ ] **Step 2: Adicionar o ponteiro no topo**

```markdown
> **Atualizado em 2026-08-07** pelo redesenho descrito em
> `docs/superpowers/specs/2026-08-07-redesenho-tickio-design.md`, que trocou o
> ClickUp pelo Tickio, introduziu a distribuição automática entre versões e moveu
> o estado do `VERSAO.lock` para Postgres. Onde os dois documentos divergirem, a
> spec do redesenho manda.
```

- [ ] **Step 3: Conferir que não sobrou referência morta**

Run: `rg -i "clickup|VERSAO\.lock|VB-\d|lock_store|golang|\bGo\b" ferramenta_versoes_design.md`
Expected: nenhuma linha, exceto onde o texto descreve explicitamente o que mudou.

- [ ] **Step 4: Commit**

```bash
git add ferramenta_versoes_design.md
git commit -m "docs: alinha o desenho da ferramenta ao redesenho Tickio + Postgres

Tres premissas do documento se invertem: fonte, onde o estado mora e se
atualizar pode rodar em versao tagueada."
```

---

## Verificação final

- [ ] `uv run pytest -v` — verde, sem skip fora dos marcados `integracao`
- [ ] `uv run pytest -v -m integracao` com o banco de pé — verde, incluindo o teste da trigger
- [ ] `env -u DATABASE_HOST uv run pytest -v` — os de integração pulam, o resto passa
- [ ] `rg -n "sqlalchemy" motor/domain/` — nenhum resultado
- [ ] `rg -n "clickup|ClickUp|VB-|extrair_vb_id|lock_store|LockStore" motor/ tests/` — nenhum resultado
- [ ] `uv run python -m motor verificar <versao aberta> --repo vendabemweb` roda ponta a ponta
- [ ] `uv run alembic upgrade head` e `uv run alembic downgrade -1` funcionam nos dois sentidos
