# Redesenho: Tickio, distribuição entre versões e estado em Postgres

> Status: **desenho aprovado**, sem implementação.
> Substitui premissas de `ferramenta_versoes_design.md`: ClickUp como fonte, lock JSON
> por versão, e `atualizar` permitido em versão tagueada. As três caem.
> Decisões travadas: fonte = Tickio REST; identidade = número do chamado; estado =
> Postgres 18 com SQLAlchemy + Alembic; versões abertas derivadas do git; versão com tag
> é imutável; versão continua o eixo de execução.

## 1. O que mudou no mundo

1. **ClickUp saiu, Tickio entrou** (`http://tickio.vendabem.com.br/`). Mesmo modelo: kanban
   com tarefas marcadas para versões e sistemas.
2. **Identidade da tarefa é só o número do chamado.** Some o `custom_id` `VB-xxxx` (artefato
   do ClickUp) e some o título. O commit continua trazendo `ch123456`.
3. **Duas majors em manutenção simultânea (13 e 14).** A tarefa recebe **apenas a versão em
   que será liberada**; a ferramenta deriva todos os outros destinos.

## 2. A regra de distribuição

**Enunciado.** Uma tarefa marcada para a versão `V` deve estar em `V` e em toda versão **em
construção** (sem tag) cujo número seja maior que `V`.

```
distribuicao(tarefa marcada para V) = { W : W em construcao, W >= V }
```

Vista pelo lado da versão, que é como o motor precisa:

```
alvo(W) = ∪ tasks(V), para toda V em construcao com V <= W
```

Só versões **em construção** entram na união. As liberadas ficam de fora — seu conteúdo
chega igual, por ancestralidade do `base`.

**Por que a união pode ser bounded assim.** Ninguém marca tarefa para versão já tagueada.
Logo toda tarefa marcada para uma versão hoje liberada foi marcada enquanto ela estava
aberta, e naquele momento propagou para todas as abertas à frente. O que sobra de gap é
exatamente o conjunto das abertas — 2 a 4 versões, não o histórico inteiro.

**Ordem** é semver sobre `(x, y, z)`: `13.33.1 < 13.34.0 < 14.0.0 < 14.0.1 < 14.1.0`.

### Cenário canônico (vira o fixture dos testes)

| # | Evento | Abertas depois do evento | Distribuição |
|---|---|---|---|
| 1 | `ch123456` marcada p/ 13.34.0 | 13.33.1, 13.34.0, 14.0.0 | 13.34.0, 14.0.0 |
| 2 | `ch123123` marcada p/ 13.33.1 | 13.33.1, 13.34.0, 14.0.0 | 13.33.1, 13.34.0, 14.0.0 |
| 3 | 13.34.0 liberada; 13.35.0 inaugurada | 13.33.1, 13.35.0, 14.0.0 | — |
| 4 | `ch321321` marcada p/ 13.33.1 | 13.33.1, 13.35.0, 14.0.0 | 13.33.1, 13.35.0, 14.0.0 |
| 5 | 14.0.0 liberada; 14.0.1 e 14.1.0 inauguradas | 13.33.1, 13.35.0, 14.0.1, 14.1.0 | — |
| 6 | `ch999111` marcada p/ 13.35.0 | idem | 13.35.0, 14.0.1, 14.1.0 |

No passo 4, `ch321321` **não** vai para a 13.34.0: ela já tem tag, e alteração na branch não
reflete no que a tag aponta.

### Implementação (domínio puro, `motor/domain/version.py`)

```python
def chave(numero: str) -> tuple[int, int, int]:
    """Ordem semver."""
    return _parse_versao(numero)

def versoes_abertas(branches: list[str], tags: list[str]) -> list[str]:
    """Em construcao = branch de versao existe e tag homonima nao.
    Ambas as listas ja chegam filtradas para o formato X.Y.Z — `list_tags` do
    GitRepo descarta tag que nao e numero de versao (`v1.0`, `release-x`),
    senao lixo do repositorio contamina o conjunto.
    """
    return sorted(set(branches) - set(tags), key=chave)

def fontes_de_alvo(alvo: str, abertas: list[str]) -> list[str]:
    """Versoes cujas tarefas caem no alvo: toda aberta <= alvo, o alvo incluso."""
    k = chave(alvo)
    return [v for v in abertas if chave(v) <= k]
```

`criar` chama `fontes_de_alvo(alvo, abertas | {alvo})` — a branch ainda não existe, então o
alvo entra por união em vez de virar caso especial.

**O que não muda:** a inferência de base do §7 antigo já atende as duas linhas sem alteração
(`14.0.0`→master, `14.1.0`→`14.0.0`, `13.35.0`→`13.34.0`, `14.0.1`→`14.0.0`). O oráculo de
presença também fica intacto — é ele que absorve "já veio por herança do base", que é o que
permite a união ser generosa sem gerar cherry-pick redundante.

## 3. Estado

**Princípio:** o que é derivável é reescrito a cada run; o que é julgamento humano nunca é
tocado pelo recálculo; o que foi liberado nunca é tocado por nada.

O banco **não é fonte de verdade sobre versão aberta** — é projeção materializada, e o
próximo `verificar` corrige qualquer divergência. Sobre versão liberada, é o único registro.

### Schema

O DDL abaixo é a **forma alvo**, escrita em SQL por clareza. A fonte real são os modelos
declarativos do §5 — as migrações saem do `--autogenerate` do Alembic, com a exceção da
trigger, que é `op.execute()` à mão. Ninguém escreve este SQL num arquivo de migração.

```sql
create table repo (
  id                serial primary key,
  nome              text not null unique,   -- basename do --repo resolvido
  tickio_sistema_id int  not null           -- ID do sistema NO TICKIO, vai em ?sistema=
);

create table versao (
  id          serial primary key,
  repo_id     int  not null references repo(id),
  numero      text not null,                -- '13.34.0'
  tipo        text not null,                -- fechada | ajustada | cliente
  base_ref    text not null,
  base_commit text not null,
  liberada_em timestamptz,                  -- null = em construcao
  unique (repo_id, numero)
);

create table atribuicao (
  versao_id int  not null references versao(id),
  chamado   text not null,
  marcada   text not null,                  -- versao para a qual o Tickio marcou
  estado    text not null,                  -- pendente | aplicado
  primary key (versao_id, chamado)
);

create table atribuicao_commit (
  versao_id   int  not null,
  chamado     text not null,
  hash_origem text not null,
  primary key (versao_id, chamado, hash_origem),
  foreign key (versao_id, chamado) references atribuicao on delete cascade
);

-- julgamento humano: a unica coisa que o recalculo nunca apaga
create table exclusao (
  id            serial primary key,
  repo_id       int  not null references repo(id),
  hash_origem   text not null,
  versao_numero text,                       -- null = vale para toda versao do repo
  motivo        text not null
);
create unique index exclusao_unica
  on exclusao (repo_id, hash_origem, coalesce(versao_numero, ''));

create table sem_entrega (
  repo_id int  not null references repo(id),
  chamado text not null,
  motivo  text not null,
  primary key (repo_id, chamado)
);
```

**Por que `marcada` está dentro de `atribuicao` e não numa tabela `tarefa` global.** Uma
tabela global faria o snapshot congelado apontar para linhas vivas: renomeia-se algo no
Tickio em 2027 e o registro do que saiu em 2026 muda junto. Mesma razão, mais grave, para
`atribuicao_commit` ser por versão e não por tarefa. **O snapshot da versão liberada é
auto-contido.**

**Por que `atribuicao` existe com 4 colunas.** É ela que registra tarefa marcada para a
versão que **não tem commit nenhum** neste repo — o falso-verde que o `tasks_sem_commits`
pega hoje. Sem a tabela, esse caso sumiria do estado.

### Congelamento

Todo run observa as tags. Achou tag para versão com `liberada_em IS NULL`, grava — usando a
**data do commit apontado pela tag**, não `now()`: senão a data registrada é a de quando o
comando rodou, não a da liberação.

A imutabilidade é constraint de banco, não `if` de aplicação:

```sql
create or replace function trava_versao_liberada() returns trigger as $$
declare vid int;
begin
  if tg_op = 'DELETE' then vid := old.versao_id; else vid := new.versao_id; end if;
  if exists (select 1 from versao where id = vid and liberada_em is not null) then
    raise exception 'versao liberada e imutavel (versao_id=%)', vid;
  end if;
  if tg_op = 'DELETE' then return old; else return new; end if;
end $$ language plpgsql;

create trigger atribuicao_congelada
  before insert or update or delete on atribuicao
  for each row execute function trava_versao_liberada();

create trigger atribuicao_commit_congelada
  before insert or update or delete on atribuicao_commit
  for each row execute function trava_versao_liberada();
```

Podia ser um `if` no store. Mas o Postgres foi escolhido justamente para ser consultado via
`psql`, e guard em Python não protege de um `DELETE` digitado à mão. Invariante de dado mora
no banco.

### Consultas que o estado precisa responder

```sql
-- onde a tarefa caiu
select v.numero, a.estado from atribuicao a
  join versao v on v.id = a.versao_id
 where a.chamado = '123456' order by v.numero;

-- o que saiu na 13.34.0
select a.chamado from atribuicao a
  join versao v on v.id = a.versao_id join repo r on r.id = v.repo_id
 where r.nome = 'vendabemweb' and v.numero = '13.34.0';
```

Não há comando de CLI para isso: o SQL **é** a superfície de consulta. Consequência assumida:
"o que saiu na 13.34.0" devolve lista de chamados; para virar release note legível, cruza-se
com o Tickio na hora.

### Simplificações em relação ao lock de hoje

1. `tasks_sem_entrega` era por versão, vira **por repo**. "Não tem entrega no vendabemweb" é
   fato do repositório — os commits são os mesmos para todas as versões. Hoje se marcaria a
   mesma coisa 4 vezes.
2. As exclusões **automáticas** ("já presente na base") somem. Eram recomputáveis por
   definição e quem responde isso é o oráculo de presença. Sobra só julgamento.

## 4. Arquitetura

### Portas

```python
class TaskSource(Protocol):
    def fetch(self, versao: str) -> list[str]: ...       # chamados marcados para a versao

class CommitSource(Protocol):
    def resolve(self, chamados: list[str]) -> dict[str, list[CommitRef]]: ...

class EstadoRepo(Protocol):                              # NOVA
    def sincronizar_versoes(self, repo: str, abertas: list[str],
                            liberadas: dict[str, datetime]) -> None: ...
    def atribuicoes(self, repo: str, versao: str) -> list[Atribuicao]: ...
    def substituir_atribuicoes(self, repo: str, versao: str,
                               novas: list[Atribuicao]) -> None: ...
    def exclusoes(self, repo: str) -> list[Exclusion]: ...
    def sem_entrega(self, repo: str) -> dict[str, str]: ...

class GitRepo(Protocol):
    def list_tags(self) -> list[str]: ...                # unico metodo novo
```

`TaskSource.fetch` devolve `list[str]` porque, sem `task` e sem `titulo`, não sobrou estrutura
para carregar. Quem monta `TaskTarget` é o resolver.

Tipo novo no domínio, atravessando a porta (dataclass puro, como todo o resto de
`domain/types.py`):

```python
@dataclass(frozen=True)
class Atribuicao:
    chamado: str
    marcada: str                    # versao para a qual o Tickio marcou
    estado: str                     # pendente | aplicado
    commits: list[str]              # hashes de origem
```

Quem monta o `liberadas: dict[str, datetime]` de `sincronizar_versoes` é o **engine**, não o
adapter de estado: para cada versão com tag, resolve a tag e lê a data do commit apontado
(`resolve_ref` + `commit_meta`, ambos já existentes no `GitRepo`). O `EstadoRepo` só persiste
o que recebe — assim a regra "a data é a da liberação, não a do run" fica no núcleo testável
e não dentro do SQL.

### Adapters

| Entra | Sai | Fica |
|---|---|---|
| `TickioRest` | `ClickUpRest` | `ManualList`, `FakeTaskSource` |
| `PostgresEstado`, `FakeEstado` | `LockStore` (arquivo) | `GrepCommitSource`, `BitbucketPRCommitSource`, `ChainCommitSource`, `GitSubprocess`, `FakeGit` |

O Bitbucket nunca soube do ClickUp; o `CommitSource` inteiro segue intacto fora da remoção do
padrão `VB-`.

### TickioRest

```
POST /api/v1/ws/token/                              {username, password} -> {access, refresh}
GET  /api/v1/ws/versoes/chamados/?sistema=<id>&versao=<X.Y.Z>
Authorization: Bearer <access>
```

**Autenticação por credencial, não por token colado no `.env`.** O adapter faz o `POST
/token/` no início de cada run e usa o `access` obtido. Custa uma chamada HTTP; evita
refazer o `.env` toda vez que o JWT expira.

O `refresh` fica **de fora**. Ele existe para processo longo que não quer reter credencial —
um comando que vive dois segundos re-autentica mais barato do que gerencia ciclo de refresh.

**`sistema` não entra na porta.** É parâmetro de construção do `TickioRest`, lido de
`repo.tickio_sistema_id` e injetado no `__main__`, que já monta o adapter por repo. A
assinatura `fetch(versao) -> list[str]` fica intacta.

O valor é o **ID numérico do sistema no Tickio** — chave de lá, sem significado do lado do
motor. Coluna `int`: o tipo recusa dedo errado que `text` deixaria virar um `?sistema=abc`
silencioso. Se o Tickio trocar o formato do ID um dia, isso é uma migração, e o Alembic está
aí para isso.

Repo desconhecido no primeiro run → `MotorError` pedindo a linha. Sem comando de CLI para
isso: é uma linha, uma vez por repositório.

```sql
insert into repo (nome, tickio_sistema_id) values
  ('vendabemweb', 1),   -- VB Web    (slug vb_web)
  ('vb2web',      3);   -- VB Web 2  (slug vb_web2)
```

**Simplificação futura, não hoje.** O endpoint de sistemas do Tickio devolve um campo
`repositorios` por sistema — hoje vazio em todos. Se ele for populado, o mapeamento
repo→sistema passa a vir da fonte e esta coluna deixa de ter razão de existir. Vale
reavaliar quando isso acontecer; enquanto o array estiver vazio, não há de onde derivar.

**Efeito no multi-projeto.** O `?sistema=` corta na fonte o que o §11 antigo cortava depois,
por "commit existe neste repo". A checagem de existência continua como rede — tarefa
fullstack marcada para um sistema mas com commits nos dois repos —, mas deixa de ser o
mecanismo principal de desambiguação.

### Limpeza no domínio

| Sai | Onde |
|---|---|
| `padrao_vb`, `extrair_vb_id` | `domain/commits.py:10,43` |
| segundo ramo do `match_exato` | `domain/commits.py:21` — sobra só `\bch<num>\b` |
| `TaskTarget.task`, `TaskTarget.titulo` | `domain/types.py:50-51` |
| `CommitRef.task`, `CommitRef.titulo` | `domain/types.py:41-42` |
| chave de agrupamento `f"{chamado} {task}"` | `__main__.py:93` — vira só `chamado` |
| reconciliação `chamado` ausente via `vb_id` | `services/lock_store.py:131-136` |

`TaskTarget` fica `{chamado, marcada, commits}`. `VersionStatus` ganha `tasks_ambiguas`.

### TargetResolver

```python
def resolve(self, alvo: str, abertas: list[str]) -> Alvo:
    marcada_de: dict[str, str] = {}
    ambiguas: list[str] = []
    for v in fontes_de_alvo(alvo, abertas):
        for ch in self.tasks.fetch(v):
            if marcada_de.get(ch, v) != v:
                ambiguas.append(ch)          # marcada em duas versoes = dado inconsistente
            marcada_de[ch] = v
    achados = self.commits.resolve(list(marcada_de))
    return Alvo(
        tasks={ch: TaskTarget(chamado=ch, marcada=v, commits=achados.get(ch, []))
               for ch, v in marcada_de.items()},
        ambiguas=ambiguas,
    )
```

Uma varredura de commits só para todas as fontes juntas — o `CommitSource` já recebe o lote
inteiro por design, então 4 versões-fonte não viram 4 greps.

### Operações

`verificar W`:

```
0. abertas = versoes_abertas(list_version_branches(), list_tags())
   EstadoRepo.sincronizar_versoes(...)          <- observa tags novas, congela
   se W liberada: imprime snapshot do banco e sai. NAO recalcula.
1. fetch/pull (como hoje)
2. alvo = TargetResolver.resolve(W, abertas)
3. filtra exclusoes (repo + versao)
4. anterior = EstadoRepo.atribuicoes(repo, W)   <- ANTES de sobrescrever
5. oraculo de presenca sobre a uniao            (intacto)
6. reconciliacao: alvo x anterior x git
7. EstadoRepo.substituir_atribuicoes(repo, W, novas)
```

O passo 4 é o que salva a reconciliação. Como o estado é sobrescrito a cada run, "tarefa que
estava e sumiu do Tickio" só é detectável comparando **antes** de gravar — sobrescrever
apagaria a própria evidência.

`atualizar` e `criar`: mesma cadeia, mais o cherry-pick. **`atualizar` numa versão com tag
passa a ser recusado** — antes era o modo permitido pelo §6, agora é o proibido. O
`PublicationGate` fica mais simples do que é hoje.

`reconstruir-lock` vira `reconstruir-estado`: mesma função (varre trailers `base..HEAD`),
destino diferente. Commit sem `ch<num>` na mensagem não é atribuível e vira órfão reportado.

**CLI:** `--clickup-token`/`$CLICKUP_TOKEN` → `--tickio-token`/`$TICKIO_TOKEN`;
`--task-source=rest` → `tickio`. `--repo`, `--debug`, `--continue`/`--abort` e os tokens do
Bitbucket ficam iguais.

## 5. Infra e configuração

### Compose

Aplicação e compose leem o mesmo `.env` — o `docker compose` já lê `.env` do diretório do
projeto sozinho, então há uma fonte só. Porta 5433 porque 5432 provavelmente já tem dono na
máquina de desenvolvimento.

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
volumes: { pgdata: }
```

`restart: unless-stopped` para o banco não virar um `docker compose up` antes de cada comando.

### Config

```bash
# .env
DATABASE_HOST=localhost
DATABASE_PORT=5433
DATABASE_NAME=monitor_versoes
DATABASE_USER=motor
DATABASE_PASSWORD=motor

TICKIO_BASE_URL=http://tickio.vendabem.com.br
TICKIO_USER=...
TICKIO_PASSWORD=...
```

```python
def database_url() -> str:
    campos = ("HOST", "PORT", "NAME", "USER", "PASSWORD")
    v = {c: os.environ.get(f"DATABASE_{c}", "") for c in campos}
    if faltando := [f"DATABASE_{c}" for c, val in v.items() if not val]:
        raise MotorError(f"faltando no .env: {', '.join(faltando)}")
    return (f"postgresql+psycopg://{quote(v['USER'])}:{quote(v['PASSWORD'])}"
            f"@{v['HOST']}:{v['PORT']}/{v['NAME']}")
```

O `quote` do `urllib.parse` não é preciosismo: senha com `@`, `/` ou `#` monta URL
sintaticamente válida apontando para **outro host**, e o erro observado é "conexão recusada",
não "senha inválida".

### ORM e migrações

Dependências novas: `sqlalchemy`, `alembic`, `psycopg[binary]`.

```
motor/adapters/estado/
  models.py      <- declarative: Repo, Versao, Atribuicao, AtribuicaoCommit, Exclusao, SemEntrega
  postgres.py    <- PostgresEstado(EstadoRepo): traduz modelo <-> dataclass
  fake.py        <- FakeEstado em memoria
alembic/
  env.py
  versions/
alembic.ini
```

**Regra que impede o ORM de corroer a arquitetura: os modelos SQLAlchemy vivem no adapter,
nunca no domínio.** `motor/domain/types.py` continua dataclass puro, sem importar
`sqlalchemy`; o `PostgresEstado` traduz na fronteira. Isso é o que mantém `verificar`
testável sem banco — no momento em que `VersionStatus` ou `TaskTarget` virarem entidade
mapeada, a suíte passa a exigir engine e a porta `EstadoRepo` perde a razão de existir.

Três detalhes:

1. **`env.py` importa `database_url()`**; `sqlalchemy.url` no `alembic.ini` fica vazio. Senão
   a senha vira segunda fonte de verdade num arquivo versionado.
2. **`naming_convention` na `MetaData`.** Sem isso o autogenerate nomeia constraints por
   reflexão e as migrações de índice/FK ficam instáveis entre máquinas.
3. **A trigger não sai do autogenerate.** Alembic reflete tabelas; PL/pgSQL é `op.execute()`
   escrito à mão, com o `DROP FUNCTION` correspondente no `downgrade`.

**Sessão:** o CLI é one-shot — uma sessão por comando, `sessionmaker` montado no `__main__` e
injetado via `Deps`.

### Recuperação

Volume perdido: `reconstruir-estado` regenera `versao` e `atribuicao` das tags e dos trailers
do git. **`exclusao` e `sem_entrega` não voltam** — são o estado irredutível. `pg_dump` dessas
duas tabelas é a única cópia que importa.

## 6. Testes

A propriedade a preservar: a suíte de hoje roda inteira sem git e sem rede. Continua assim.

| Alvo | Como |
|---|---|
| `chave`, `versoes_abertas`, `fontes_de_alvo` | puro, table-driven — o cenário do §2 é o fixture canônico |
| `TargetResolver` | `FakeTaskSource` + fake de `CommitSource`; união multi-fonte e ambiguidade |
| engine (`verificar`/`atualizar`/`criar`) | `FakeEstado` em memória, como já é com `FakeGit` |
| `TickioRest` | `httpx.MockTransport`, padrão do `test_tasksource_rest.py` atual |
| `PostgresEstado` | **um** teste `@pytest.mark.integracao`, pulado sem `.env` de banco |

O teste de integração existe por um motivo e é obrigatório: verificar que a trigger recusa
escrita em versão liberada. É a invariante central do congelamento e um fake não a prova.

Não se usa SQLite em memória no lugar do fake: o schema tem trigger PL/pgSQL, e o teste
passaria a validar um banco diferente do que roda.

## 7. Erros

`__main__.py:204-209` já separa `MotorError` (mensagem limpa, exit 1) de bug (traceback). Os
casos novos entram na primeira categoria:

- banco fora do ar → `"banco inacessivel em <host>:<porta>: suba com docker compose up -d"`,
  não traceback de psycopg;
- Tickio 4xx/5xx → status + corpo, como o adapter atual faz (`rest.py:64`);
- violação da trigger → `MotorError` "versão liberada é imutável"; guarda contra bug, não
  deve disparar em fluxo normal.

**Tarefa marcada em duas versões não é exceção.** Vira `tasks_ambiguas` no `VersionStatus`,
pinta vermelho, comando termina normal. Dado inconsistente no Tickio não derruba o comando.

## 8. Pendências e fora de escopo

**Pendência única, restrita ao parsing:** o corpo da resposta de
`GET /api/v1/ws/versoes/chamados/`. Endpoints, autenticação e parâmetros estão definidos
(§4); falta só saber sob qual chave vem o número do chamado e se a listagem pagina. Uma
resposta de exemplo resolve. Tudo o mais — domínio, estado, engine, migrações — é
implementável e testável contra `FakeTaskSource` antes disso.

**Migração de dados: nenhuma.** `locks/` está em `.gitignore:12` e nunca foi criado. Primeira
rodada do `reconstruir-estado` popula do git.

**Fora de escopo, herdado:** daemon localhost (etapas 2 e 3), operação `liberar`, deploy em
cliente, validação de integridade do código (skill `validar-versao`).

**Documento a reescrever junto:** `ferramenta_versoes_design.md` descreve ClickUp, lock
commitado na branch e `atualizar` permitido em versão tagueada. As três premissas se invertem
aqui; deixá-lo como está é armadilha. Item do plano de implementação, não desta spec.
