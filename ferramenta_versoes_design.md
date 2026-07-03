# Ferramenta de versões — desenho

> Status: **desenho** (sem implementação). Decisões travadas: oráculo = manifesto + trailer;
> rebuild proibido em versão tagueada; formato = motor + daemon localhost em etapas (§13);
> stack = **Go** (§13).
> Complementa `VERSOES.md` (o fluxo manual atual). Quem cria a tag é o processo de release
> (mecanismo ainda não definido) — a ferramenta apenas **lê** a tag existente (§6).

## 1. Objetivo

Uma ferramenta com três operações sobre versões do VendaBem Web:

1. **`criar`** — cria uma versão do zero a partir da base correta.
2. **`verificar`** — diz se a versão está com **todos** os commits que deveria (read-only).
3. **`incrementar`** — aplica os commits que faltam, lidando com conflitos.

(Existe uma quarta operação, `reconstruir_lock` — de **recuperação**, não do fluxo principal;
regenera o `VERSAO.lock` a partir do git quando ele é apagado ou corrompido. Ver §3, §14.)

Tipos de versão (de `VERSOES.md`): **Fechada** `X.0.0` (da master), **Ajustada** `X.Y.0`
(de fechada/ajustada anterior), **Específica de cliente** `X.Y.Z` (de qualquer anterior).
Cada versão é uma **branch**; ao liberar, o HEAD recebe uma **tag** git homônima.

## 2. O oráculo de presença: 3 fontes de verdade

A pergunta central das três operações é *"o commit X já está nesta versão?"*. Como
cherry-pick troca o hash, ela é respondida cruzando três fontes:

| Fonte | Representa | Onde vive | Muda quando |
|---|---|---|---|
| **ClickUp** | o que *deveria* estar (alvo) | externo | task marcada com "Versão de destino" = X.Y.Z |
| **`VERSAO.lock`** | o que o tool *declarou* colocar (intenção auditável) | commitado na branch | o tool aplica/atualiza |
| **git (trailer `-x`)** | o que está *fisicamente* aplicado (prova) | histórico da branch | um cherry-pick acontece |

Verificação só dá **verde** quando `ClickUp = lock = git`. Cada camada pega o que a outra
não pega:

- **lock × ClickUp** → task nova esquecida, ou task desmarcada do alvo.
- **lock × git** → lock "mentindo" (commit sumiu num rebase, ou edição manual do arquivo).
- **git × lock** → cherry-pick feito à mão sem o tool (regularizar o lock).

Por que não comparar só ClickUp × git? Porque o mapa **task → commits** é derivado por grep
na mensagem (`ch<num>` / `VB-xxxx`) — é *fuzzy*. O lock **congela essa derivação numa decisão
explícita e revisável no PR**, em vez de re-derivar (possivelmente diferente) a cada operação.

### Definição de "presente"

```
presente(commit_origem, branch):
  1. hash exato é ancestral da branch?         (git merge-base --is-ancestor)  → sim
  2. algum commit da branch tem trailer         (git log --grep)
     "cherry picked from commit <commit_origem>"?                              → sim
  3. [legado] patch-id(commit_origem) ∈ patch-ids(base..branch)?               → sim
  senão → ausente
```

Item **2** é o principal (resiste a conflito resolvido, que muda o diff). Item **1** cobre
merge direto. Item **3** só para commits antigos anteriores à convenção `-x`
(ex.: as 3 commits de ch251099 de fev/mai que já estavam na 13.6.0).

## 3. Formato do `VERSAO.lock`

JSON na raiz da branch da versão. **O tool é o único que escreve.** Hashes são sempre os de
**origem** (não os pós-cherry-pick — esses se derivam dos trailers).

```json
{
  "versao": "13.7.0",
  "tipo": "ajustada",
  "base": { "ref": "13.6.0", "commit": "571fea583e" },
  "tasks": {
    "255514": { "task": "VB-2354", "titulo": "Logs pedidos ecommerce",
                "commits": ["d1a0ff9450","e652424ecf","5505b93d69","3989974386"] },
    "255074": { "task": "VB-2391", "titulo": "Uappi status pedido",
                "commits": ["e193dffe89"] },
    "255081": { "task": "VB-2214", "titulo": "UF minuscula pre-venda",
                "commits": ["7f8169a02a","002447dc2a"] },
    "255959": { "task": "VB-2546", "titulo": "Configurar captcha",
                "commits": ["9b99316fa8"] },
    "250995": { "task": "VB-2494", "titulo": "Integrar produtos Uappi",
                "commits": ["dc26aaaf09"] },
    "251099": { "task": "VB-2549", "titulo": "Uappi precos (SKU)",
                "commits": ["7ebaefe049"] }
  },
  "excluidos": [
    { "commit": "83cd5cb8a2", "chamado": "251099", "motivo": "ja presente na base 13.6.0" },
    { "commit": "dfd9577c2f", "chamado": "251099", "motivo": "ja presente na base 13.6.0" },
    { "commit": "fb91371e88", "chamado": "251099", "motivo": "ja presente na base 13.6.0" }
  ]
}
```

`excluidos` documenta commits que o grep associou ao chamado mas foram deixados de fora — sem
isso, todo `verificar` os reportaria como faltantes eternamente. São de **dois tipos**:

- **Automáticas** (ex.: `"ja presente na base"`): recomputáveis por `presente(commit, base)`.
  Persistidas só por conveniência/diff; o tool sabe re-derivar.
- **Por julgamento** (revertido, superado, decisão humana): **estado irredutível** — não
  existe em nenhum outro lugar além do lock.

### Recuperação do lock

O lock **não é sagrado**: é uma projeção rápida e auditável dos trailers + um núcleo de
decisões. Se apagado, um comando `reconstruir-lock` (ou `verificar --reconstruir`) regenera:

| Parte | Recuperada de |
|---|---|
| `versao`, `tipo` | nome/formato da branch |
| `base` | `git merge-base <branch> <base inferida>` (§7) |
| `tasks → commits` | trailers `cherry picked from <hash>` em `base..HEAD`, reagrupados por `ch`/`VB` |
| `excluidos` automáticas | recomputadas via `presente(commit, base)` |
| `excluidos` por julgamento | **não recuperável** — `reconstruir_lock` retorna `PendingJudgment{orfaos}` (mesmo padrão de `Blocked` do `incrementar`, §14); quem pergunta ao humano é o front-end, não o motor |

Isso reforça a escolha manifesto+trailer: o **trailer é o backbone durável**; o lock é a camada
rápida por cima. **Dependência dura:** todo pick usa `-x` — um cherry-pick sem trailer vira um
buraco não-reconstruível (pick manual à mão fura isso; §9 avisa).

## 4. Resolução do alvo (ClickUp → commits)

```
alvo(versao):
  tasks = clickup.tasks(custom_field["Versao de destino"] == versao)
          # sem filtro de status: qualquer task com o campo == versao entra
  para cada task:
    ch   = task.custom_field["Numero do chamado"]        # a4211489-...
    vbid = task.custom_id                                 # VB-xxxx
    commits = git log master --grep=<ch> --grep=<vbid>    # só master: evita commit não revisado/mesclado por PR
  retorna { ch -> {task, titulo, commits[]} }
```

**Precisão do match:** `git log --grep` aqui é só pra trazer **candidatos** (contains, não
exato) — casar `5514` sem cuidado pega `255514` como falso positivo (substring de outro
chamado). O match exato (`\bch5514\b` / `\bVB-2354\b`, com word-boundary) é feito no domínio
(regex da linguagem do motor), não na regex do git — mais portável e testável com `FakeGit`.

**Bloqueador conhecido:** o MCP do ClickUp **não filtra por custom field**. Opções, em ordem
de preferência:
1. **API REST do ClickUp** com filtro `custom_fields` (precisa de token) — determinístico.
2. View salva do ClickUp filtrada por "Versão de destino".
3. Lista manual de chamados passada ao tool (fallback sempre disponível).

O campo é `de0124a4-a15d-401e-ab48-417803082562` ("Versão de destino", short_text).

## 5. As três operações

Núcleo compartilhado: `alvo()` (§4) + `presente()` (§2) + `worktree isolada` + `git rerere on`.

### `verificar X.Y.Z` (read-only)

```
tgt   = alvo(X.Y.Z)
lock  = lê VERSAO.lock da branch
faltam_no_git   = [c for c in tgt.commits if not presente(c, branch)]
divergencia_lock = tgt.tasks Δ lock.tasks          # simetrica
lock_integro     = todos os commits do lock estão presente() no git
conflitam        = [c for c in faltam_no_git if merge_tree_conflita(base, branch, c)]

relatorio:
  ClickUp vs lock:   tasks novas / removidas
  lock  vs git:      lock integro? (senão: commit sumiu)
  faltantes:         N commits, quais, quais conflitam
  → status VERDE só se ClickUp == lock == git
```

Predição de conflito **sem tocar a working tree**:
`git merge-tree --write-tree --merge-base=<parent(c)> <branch-tip> <c>` (Git ≥ 2.38).
Reporta os arquivos que conflitariam **antes** de aplicar.

> Complemento: após `verificar` dar verde em commits, chamar a skill **`validar-versao`**
> (sintaxe Python, validação Django, migrations South faltantes). São checagens ortogonais —
> `verificar` = completude de commits; `validar-versao` = integridade do código resultante.

### `incrementar X.Y.Z` (in-place — seguro para versão publicada/tagueada)

```
faltam ordenados por commit-date asc, agrupados por task
para cada commit em faltam:
  git cherry-pick -x <commit>
  se conflito:
    rerere tenta replicar resolução conhecida
    se resolveu automaticamente → git cherry-pick --continue
    senão → PARA: mostra arquivos + "resolva e rode: <tool> incrementar --continue"
atualiza VERSAO.lock (tasks + excluidos), commita o lock
```

**Ordenação:** `git log` lista do mais novo pro mais antigo por padrão — a ordenação por
commit-date asc não vem de flag do git (`--reverse` seria frágil a mudanças de critério); é
feita explicitamente no domínio, ordenando `CommitRef.CommitDate` (testável com `FakeGit`,
sem depender do comportamento do CLI, §14).

**Lock em lote:** o commit do `VERSAO.lock` acontece **uma vez, ao final** do lote, não por
commit aplicado — simplicidade deliberada. Se o processo for interrompido no meio, os
cherry-picks já feitos ficam com trailer (prova em git) mas o lock atrasado; a próxima rodada
detecta isso como "pick manual sem o tool" (§9) e oferece regularizar. Aceitável porque a
interrupção é rara e sempre recuperável — não compensa a complexidade de commitar o lock a
cada task.

**Só adiciona história** — nunca reescreve. É o único modo permitido quando a versão já tem
tag (ver §6).

### `criar X.Y.Z`

```
base = infere_base(X.Y.Z)                 # §7
proíbe se branch/tag X.Y.Z já existe
git worktree add -b X.Y.Z <base>
escreve VERSAO.lock inicial (tasks vazias, base preenchida)
incrementar X.Y.Z                         # reusa o fluxo acima
```

Como a branch é nova e não publicada, aqui o rebuild idempotente (recriar do zero a cada
tentativa, com `rerere` replicando resoluções) é permitido — útil se você quer refazer a
composição antes do primeiro build. Deixa de ser permitido assim que a versão é publicada.

## 6. Regra de publicação (trava do rebuild)

```
publicada(X.Y.Z):
  git tag -l X.Y.Z            → existe? SIM (processo de release já tagueou)
  git ls-remote --heads origin X.Y.Z → existe? SIM (branch compartilhada)

se publicada → APENAS incremento in-place. Rebuild/force-push BLOQUEADO.
se local WIP  → rebuild permitido.
```

A tag só nasce quando a versão é liberada em produção (mecanismo de release ainda não
definido). Portanto "tagueada" = liberada em produção = história imutável.

## 7. Inferência de base

```
X.0.0        → master
X.Y.0 (Y>0)  → maior X.(Y-1..0).0 existente         (13.7.0 → 13.6.0)
X.Y.Z (Z>0)  → X.Y.(Z-1) se existir, senão X.Y.0    (específica de cliente)
```

## 8. Fluxo de conflito (transversal)

1. **`git rerere` ligado** (`rerere.enabled=true` **e** `rerere.autoUpdate=true`) — grava a
   resolução de cada conflito uma vez e replica em reincrementos/rebuilds. `autoUpdate` é
   obrigatório: sem ele, uma resolução conhecida é reaplicada no working tree mas o arquivo
   continua "unmerged" até um `git add` explícito — sem essa config, o "resolveu
   automaticamente → `--continue`" do §5 não dispara sozinho.
2. **Nunca auto-resolve** heurísticamente — em conflito novo, para e entrega o controle.
3. **Checkpoint resumível** — a worktree fica no estado do conflito; `--continue` retoma,
   `--abort` restaura.
4. **Worktree isolada** — sua árvore de trabalho principal nunca é tocada.

## 9. Reconciliação quando as 3 fontes divergem

| Caso | Sinal | Ação do tool |
|---|---|---|
| Task nova marcada p/ versão | em ClickUp, fora do lock | `incrementar` aplica + registra no lock |
| Task desmarcada do alvo | no lock, fora do ClickUp | **avisa**; remoção é decisão humana (reverter é destrutivo) |
| Commit do lock sumiu | no lock, fora do git | **alerta forte** — lock corrompido/rebase; não auto-corrige |
| Pick manual sem o tool | no git, fora do lock | **avisa**; oferece regularizar o lock |
| Grep pegou commit que não deve entrar | candidato | mover para `excluidos` com motivo |

## 10. Dependências / decisões em aberto

- **Token da API do ClickUp** — sem ele, alvo não é determinístico (fallback: lista manual).
- **Convenção de mensagem (decidido)** — grep casa `ch<num>` **e** `VB-<num>`; hoje o
  vendabemweb usa `ch000000`, no futuro passará a `VB-0000` (o tool já suporta ambos, sem
  troca). Para o oráculo ser 100% confiável em commits novos, o ideal é `/dev-flow` /
  `/executar-task` injetarem também um trailer; commits antigos ficam no fallback patch-id.
- **Formato do tool (decidido)** — motor + daemon localhost, em etapas. Ver §13.
- **Operação futura `liberar`** — hoje fora de escopo (§12); consideração para depois da Etapa 1:
  incorporar a liberação (hoje manual: tag na HEAD da branch + mover as tasks do lock pra
  "finalizado" no ClickUp) como 4ª operação. Implicações a resolver quando entrar no escopo:
  - Pré-condição natural: só libera se `verificar` estiver **verde**.
  - `TaskSource` hoje só lê (`fetch`); marcar task como finalizada exige escrita — só o adapter
    REST (com token) suporta isso, `SavedView`/`ManualList` não.
  - Overlap com o processo de release externo que hoje cria a tag (mecanismo ainda não
    definido, §6) — definir quem passa a ser dono da tag (a ferramenta cria e o release
    fica só leitura, ou o inverso).

## 11. Multi-projeto

A ferramenta é apartada e opera sobre **múltiplos repositórios** (hoje `vendabemweb`;
próximo, `vb2web`), seguindo a mesma lógica. As premissas do ambiente tornam isso barato:

- Todos os projetos ficam **na mesma sprint** do ClickUp e usam o **mesmo custom field**
  ("Versão de destino").
- O **esquema de versionamento é sempre igual** (§7) — não varia por projeto.
- A **convenção de mensagem é a mesma** (`ch<num>` hoje, `VB-<num>` no futuro para ambos).
- **Build está fora de escopo** — a ferramenta só monta/verifica a versão.

### Consequência: quase nada é "config por projeto"

Como ClickUp, esquema e convenção são compartilhados, o motor é **único** e o único parâmetro
que define o "projeto" é **qual repositório git ele aponta**:

```
tool verificar   13.7.0 --repo /Volumes/.../vendabemweb
tool verificar   13.7.0 --repo /Volumes/.../vb2web
tool incrementar 13.7.0 --repo /Volumes/.../vb2web
```

Não há `.versao.toml` por projeto, hook de build, nem regras de base por repo. Se um dia um
projeto divergir (outro campo, outro esquema), aí sim se introduz um arquivo de config —
**não antes** (rule of three: abstrai-se no caso que quebra a premissa, não por antecipação).

### Desambiguação: um alvo "13.7.0" compartilhado → conjunto certo por repo

O `alvo(13.7.0)` no ClickUp retorna tasks de **todos** os projetos (sprint compartilhada). O
tool não precisa de um campo "projeto": ele opera sobre **um repo por vez** e o mapa
task→commits (§4) só encontra commits **que existem naquele repo**. Logo:

- Task só de vb2web → zero commits no `vendabemweb` → **ignorada automaticamente** ali, e
  incluída ao rodar com `--repo vb2web`.
- Task *fullstack* (toca os dois) → contribui seus commits de front no repo de front e os de
  back no repo de back — correto nos dois `VERSAO.lock`.

Cada projeto tem sua **própria sequência** de versões, mas mantidas **equiparadas** (na
prática os números tendem a coincidir). A desambiguação é robusta a isso: mesmo que os dois
cheguem ao mesmo `13.7.0`, o query do ClickUp traz as duas tasks e cada `--repo` fica só com
as que têm commits naquele repo. A resolução é sempre **relativa ao repo apontado**, nunca ao
número — por isso funciona tanto na colisão quanto na divergência de numeração. Cada repo tem
sua branch `X.Y.Z` e seu `VERSAO.lock` próprios.

### Estado por projeto

Nada é compartilhado entre repos exceto o **motor** e a **fonte ClickUp**:

- `VERSAO.lock` mora na **branch de cada repo** (estado por-versão, por-projeto).
- `git rerere` (resoluções de conflito) é **por repo**.
- Worktrees isoladas são **por repo**.

### Aberto / edge

- Task *fullstack* que precise de **números diferentes** em cada projeto (ex.: front 13.7.0 e
  back 4.2.0) não é expressável num único short_text "Versão de destino". As sequências são
  independentes, mas como são mantidas equiparadas isso raramente aparece; se aparecer, exige
  um campo por projeto (ou duas tasks). Fica anotado, não resolvido.

## 12. Fora de escopo

- Criação de tag e atualização de status no ClickUp → **hoje** fora de escopo (a ferramenta
  apenas **lê** as tags, §6, para saber se a versão está publicada); candidatas a virar a
  operação `liberar` no futuro — ver §10.
- Deploy em cliente.
- Validação de integridade do código → skill `validar-versao` (chamada por `verificar`).
- Relatório HTML estático → descartado (não agrega sem ser interativo).

## 13. Roadmap de implementação

Projeto apartado, multi-projeto (§11). O motor é o núcleo chamável; o daemon é fachada por
cima — nunca duplica lógica. Segurança/complexidade só entram na etapa que **age** pelo git.

**Stack (decidido): Go.** `os/exec` cobre o `GitRepo` inteiro (git é sempre subprocess),
`encoding/json` o `VERSAO.lock`, `net/http` dá cliente (ClickUp REST) e servidor (daemon,
etapa 2/3) sem dependência externa. Interfaces do Go mapeiam direto pras portas do §14
(`TaskSource`, `GitRepo`), e binário único facilita manutenção solo.

**Etapa 1 — Motor.**
Núcleo chamável (biblioteca Go) + um CLI fino para exercê-lo antes de existir daemon.
Contém tudo que é correção: resolução do alvo (ClickUp §4), oráculo `presente()` (§2),
`VERSAO.lock` (§3) + `reconstruir-lock`, as 3 operações (§5), predição `merge-tree` (§5),
`rerere` e worktree isolada (§8), inferência de base (§7), trava de publicação (§6).
É aqui que ficam os testes.

**Etapa 2 — Daemon localhost, só visualização (read-only).**
Servidor em `127.0.0.1` que mostra o `verificar` de forma visual: cruzamento 3-vias
(ClickUp × lock × git), commits faltantes, quais conflitam, **os dois repos lado a lado**.
Nenhuma mutação. Mesmo read-only, bind restrito a `127.0.0.1` + token por requisição
(defesa contra CSRF de aba maliciosa — o footgun clássico de web local que executa comando).

**Etapa 3 — Execução das rotinas pelo daemon.**
`criar` / `incrementar` disparados pela UI. Orquestração de conflito: detecta → mostra o diff
→ "resolva no editor e clique Continuar" (a **edição** do merge fica no editor, não no
navegador; §8). Postura de segurança completa: CSRF token por ação, `127.0.0.1` apenas.

## 14. Arquitetura do motor

**Portas-e-adaptadores** com núcleo puro. Duas portas de verdade (fonte de tasks tem 3 formas;
git precisa ser fake-ável nos testes); o resto é módulo comum — sem catedral de interfaces.

```
                 front-ends (FORA do motor)
                 CLI  ·  daemon localhost
                        │  chamam a API de Operações
      ┌─────────────────┴───────────────────────────┐
      │            OPERAÇÕES (use-cases)             │
      │  criar · verificar · incrementar ·           │
      │  reconstruir_lock                            │
      ├──────────────────────────────────────────────┤
      │            SERVIÇOS DE NÚCLEO                 │
      │  TargetResolver · PresenceOracle · LockStore │
      │  BaseResolver · PublicationGate · Conflict…  │
      ├──────────────────────────────────────────────┤
      │        DOMÍNIO (dados + regras PURAS)         │
      │  Version · TargetSet · Lock · CommitRef ·    │
      │  VersionStatus · reconciliação · inferência  │
      └──────────────┬───────────────┬───────────────┘
                     │ portas        │
           ┌─────────┴──┐     ┌──────┴──────────┐
           │ TaskSource │     │    GitRepo      │
           ├────────────┤     ├─────────────────┤
  adapters:│ ClickUpRest│     │ GitSubprocess   │
           │ SavedView  │     │ FakeGit (testes)│
           │ ManualList │     └─────────────────┘
           └────────────┘
```

### Camadas

**Domínio (puro, zero I/O — o coração testável).** Só dados + funções determinísticas; nada
toca git ou rede.
- Tipos: `Version{Numero, Tipo, Base}`, `CommitRef{HashOrigem, Chamado, Task, CommitDate, Msg}`,
  `TargetSet` (task→commits), `Lock`, `VersionStatus`.
- Regras: inferência de tipo pelo número, inferência de base (§7), `diff(target, lock)`,
  **reconciliação 3-vias** (ClickUp × lock × git → faltantes / extras / integridade), match
  exato de `ch<num>`/`VB-<num>` por word-boundary sobre candidatos do grep (§4), ordenação de
  commits por `CommitDate` asc antes de aplicar (§5).

**Portas (as 2 únicas fronteiras com o mundo).**
- `TaskSource.fetch(version) -> [TaskTarget]` — 3 adapters (REST / view salva / lista manual).
  Isola o bloqueador do ClickUp (§4).
- `GitRepo` — conjunto **enxuto**: `merge_base`, `is_ancestor`, `search_commits(padrões, refs)`,
  `commit_meta`, `patch_id`, `cherry_pick_x → Aplicado|Conflito`, `rerere/continue/abort`,
  `predict_merge` (merge-tree), `worktree_add/remove`, `tag_exists`, `remote_branch_exists`,
  `read/write_file`. Adapter real (subprocess) + `FakeGit` para testes.

**Serviços de núcleo (orquestram; dependem só de portas + domínio).**
- `TargetResolver` — TaskSource + `search_commits` → `TargetSet`. **Desambiguação multi-projeto
  mora aqui**: só entram commits que existem *neste* repo (§11). Aplica a regra de match exato
  do domínio sobre os candidatos brutos que `search_commits` do `GitRepo` traz (§4) — a regra em
  si é pura e vive no domínio, o serviço só a invoca.
- `PresenceOracle` — `presente()` (§2): hash-ancestral → trailer → patch-id.
- `LockStore` — lê/escreve/reconstrói o `Lock` via GitRepo (reconstrução = varre trailers de
  `base..HEAD`, §3).
- `BaseResolver` — número → commit-base (fork point, §7).
- `PublicationGate` — `tag_exists || remote_branch_exists` → trava o rebuild (§6).
- `ConflictSession` — máquina de estado resumível do conflito (abaixo).

**Operações (API que CLI e daemon chamam).** `criar` · `verificar` · `incrementar` ·
`reconstruir_lock`.
- `verificar` = TargetResolver + PresenceOracle + LockStore + reconciliação + `predict_merge`
  → `VersionStatus`. Read-only.
- `criar` = BaseResolver → `worktree_add(branch, base)` → LockStore.init → `incrementar`.
- `incrementar` = `verificar` → aplica faltantes por commit-date via `cherry_pick_x` → em conflito
  devolve `ConflictSession` → LockStore.update.
- `reconstruir_lock` = varre trailers `base..HEAD` (§3) → retorna `Done` ou
  `PendingJudgment{orfaos}` se houver `excluidos` por julgamento não recuperáveis.

### Invariante que sustenta tudo
**O motor é não-interativo e determinístico.** Nunca pergunta nem bloqueia esperando humano:
`incrementar` **retorna um valor** — `Done` ou `Blocked{commit, arquivos_em_conflito}`;
`reconstruir_lock` segue o mesmo padrão com `Done`/`PendingJudgment{orfaos}`. Quem dirige o
humano (resolver no editor → `--continue`; decidir os órfãos) é o front-end. Por isso **o mesmo
núcleo serve CLI e daemon** sem mudança, e — como todo efeito passa por porta — o domínio é
testável com `FakeGit`/`FakeTaskSource`, sem repo nem rede.

### Onde deliberadamente NÃO se abstrai
- Sem porta de "clock" — ordenação usa a data do commit (vem do git), não relógio.
- `LockStore` não é porta própria — módulo fino sobre `GitRepo` (o lock é read/write de arquivo
  numa branch).
- Sem camada de "config por projeto" — o projeto é só o `GitRepo` apontado (§11).
- Sem cache pra `tag_exists`/`remote_branch_exists` — checagem direta a cada chamada. Latência
  de rede é desprezível pra uso sob demanda solo, e esse gate trava rebuild: dado stale aqui é
  mais perigoso (permitiria rebuild sobre versão já publicada) do que o custo de mais uma
  chamada de rede.
