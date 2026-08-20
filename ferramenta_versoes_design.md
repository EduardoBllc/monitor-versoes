# Ferramenta de versões — desenho

> **Atualizado em 2026-08-07** pelo redesenho descrito em
> `docs/superpowers/specs/2026-08-07-redesenho-tickio-design.md`, que trocou o
> ClickUp pelo Tickio, introduziu a distribuição automática entre versões e moveu
> o estado do `VERSAO.lock` para Postgres. Onde os dois documentos divergirem, a
> spec do redesenho manda.

> Status: **implementado** (`motor/`, suíte verde). Decisões travadas: oráculo = manifesto +
> trailer; versão liberada é imutável — `atualizar` passa a ser recusado nela, não só o
> rebuild (§6); formato = motor + daemon localhost em etapas (§13); stack = **Python**.
> Complementa `VERSOES.md` (o fluxo manual atual). Quem cria a tag é o processo de release
> (mecanismo ainda não definido) — a ferramenta apenas **lê** a tag existente (§6).

## 1. Objetivo

Uma ferramenta com três operações sobre versões do VendaBem Web:

1. **`criar`** — cria uma versão do zero a partir da base correta.
1. **`verificar`** — diz se a versão está com **todos** os commits que deveria (read-only).
2. **`atualizar`** — aplica os commits que faltam, lidando com conflitos.

(Existe uma quarta operação, `reconstruir-estado` — de **recuperação**, não do fluxo
principal; regenera o estado (Postgres) a partir do git quando ele é apagado ou corrompido.
Ver §3, §14.)

Tipos de versão (de `VERSOES.md`): **Fechada** `X.0.0` (da master), **Ajustada** `X.Y.0`
(de fechada/ajustada anterior), **Específica de cliente** `X.Y.Z` (de qualquer anterior).
Cada versão é uma **branch**; ao liberar, o HEAD recebe uma **tag** git homônima.

## 2. O oráculo de presença: 3 fontes de verdade

A pergunta central das três operações é _"o commit X já está nesta versão?"_. Como
cherry-pick troca o hash, ela é respondida cruzando três fontes:

| Fonte                  | Representa                                           | Onde vive                                 | Muda quando                                                                      |
| ---------------------- | ----------------------------------------------------- | ------------------------------------------ | ----------------------------------------------------------------------------------- |
| **Tickio**             | o que _deveria_ estar (alvo)                         | externo                                    | task marcada para uma versão (distribuída para as demais em construção — §4)      |
| **estado (Postgres)**  | o que o tool _declarou_ colocar (intenção auditável) | tabelas `atribuicao` + `atribuicao_commit` | `verificar`/`atualizar` sobrescrevem a cada run; versão liberada nunca muda (§6) |
| **git (trailer `-x`)** | o que está _fisicamente_ aplicado (prova)            | histórico da branch                        | um cherry-pick acontece                                                            |

Verificação só dá **verde** quando `Tickio = estado = git`. Cada camada pega o que a outra
não pega:

- **estado × Tickio** → task nova esquecida, ou task desmarcada do alvo.
- **estado × git** → estado "mentindo" (commit sumiu num rebase, ou `UPDATE`/`DELETE` manual
  na tabela).
- **git × estado** → cherry-pick feito à mão sem o tool (regularizar o estado).

Por que não comparar só Tickio × git? Porque o mapa **task → commits** é derivado por grep
na mensagem (`ch<num>`) — é _fuzzy_. O estado **congela essa derivação numa decisão explícita
e auditável** (a tabela substitui o lock commitado no PR), em vez de re-derivar (possivelmente
diferente) a cada operação.

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

## 3. Formato do estado

O que antes era um JSON `VERSAO.lock` commitado na raiz da branch da versão agora é **estado
em Postgres**. Schema completo (tabelas `repo`, `versao`, `atribuicao`, `atribuicao_commit`,
`exclusao`, `sem_entrega`) e DDL: `docs/superpowers/specs/2026-08-07-redesenho-tickio-design.md`
§3. Aqui só o que muda na leitura deste documento:

- **Identidade da tarefa é só o número do chamado** (`ch<num>`) — sem `task`/`título` do
  ClickUp, sem `VB-<num>`. Hashes continuam sempre os de **origem** (não os pós-cherry-pick —
  esses se derivam dos trailers).
- **`atribuicao.marcada`** grava a versão para a qual o Tickio marcou a tarefa — é o que
  sustenta a regra de distribuição do §4.
- **`atribuicao.estado`** é `pendente` ou `aplicado`. Uma tarefa marcada sem nenhum commit
  achado nunca vira `aplicado` — ela fica `pendente` e aparece como faltante em vez de dar
  falso-verde (§9).
- **`exclusao`** guarda só julgamento humano agora. As exclusões automáticas ("já presente na
  base") do lock antigo somem: eram recomputáveis por definição, e quem responde isso hoje é
  o próprio oráculo de presença (§2).

### Recuperação do estado

O estado **não é sagrado** — mesma ideia do lock antigo, aplicada ao banco: é uma projeção
rápida e auditável dos trailers + um núcleo de decisões. Se as tabelas `versao`/`atribuicao`
forem perdidas, o comando `reconstruir-estado` (era `reconstruir-lock`) regenera:

| Parte                          | Recuperada de                                                                                                                                                              |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `versao`, `tipo`, `base`       | nome da branch + inferência de base (§7), gravado uma vez em `registrar_versao`                                                                                            |
| `atribuicao` (task → commits)  | trailers `cherry picked from <hash>` em `base..HEAD`, reagrupados por `ch<num>`                                                                                            |
| `exclusao`, `sem_entrega`      | **não recuperáveis** — julgamento humano, só existe no banco. `reconstruir-estado` retorna `PENDING_JUDGMENT{orfaos}` para commit sem `ch<num>` na mensagem (mesmo padrão de `Blocked` do `atualizar`, §14); quem pergunta ao humano é o front-end, não o motor |

Numa versão já liberada a trigger de congelamento (§6) recusa a escrita — recuperar o
snapshot dela exige levantar o congelamento antes de rodar `reconstruir-estado`:

```sql
update versao set liberada_em = null where repo_id = … and numero = '13.34.0';
```

**Não é `delete from versao`:** a FK `fk_atribuicao_versao_id_versao` foi declarada sem
`ondelete`, então o `delete` é recusado justamente quando a versão tem linhas em
`atribuicao` — o caso em que se quer reconstruir — e apagar os filhos primeiro bate na
trigger de congelamento. Zerar `liberada_em` também preserva a base já gravada, e
`reconstruir-estado` pula a re-resolução dela.

`motor/services/lock_store.py` e o tipo `Lock` do domínio não existem mais — a leitura e a
escrita do estado passam direto pela porta `EstadoRepo` (§14).

Isso reforça a escolha manifesto+trailer: o **trailer é o backbone durável**; o estado é a
camada rápida por cima. **Dependência dura:** todo pick usa `-x` — um cherry-pick sem trailer
vira um buraco não-reconstruível (pick manual à mão fura isso; §9 avisa).

## 4. Resolução do alvo (Tickio → commits, com distribuição entre versões)

Uma tarefa marcada para a versão `V` no Tickio vale para `V` **e para toda versão em
construção (sem tag) cujo número seja maior** — não é preciso marcar a tarefa de novo a cada
versão nova que abre. Visto do lado da versão, que é como o motor precisa:

```
versoes_abertas(branches, tags) = branches sem tag homônima, em ordem semver
fontes_de_alvo(V, abertas)      = { W em abertas : W <= V }        # V incluso
alvo(V) = ∪ tickio.fetch(W), para todo W em fontes_de_alvo(V, abertas)
```

Só versões **em construção** entram na união — a liberada fica de fora, seu conteúdo chega a
`V` por ancestralidade do `base` (§7), não pela distribuição. Ordem é semver sobre `(x, y, z)`,
não textual (`13.9.0` vem antes de `13.10.0`). Regra completa, com o cenário de 6 passos que é
o fixture dos testes: spec §2.

```
alvo(versao):
  para cada W em fontes_de_alvo(versao, abertas):
    chamados += tickio.fetch(W)      # GET /versoes/chamados/?sistema=<id>&versao=<W>
  commits = commit_source.resolve(chamados)   # uma varredura só p/ todo o lote, nunca 1 por versão-fonte
  retorna { ch -> {marcada: W, commits[]} }
```

**Precisão do match:** o `CommitSource` (grep em `master`, ou PR do Bitbucket) só traz
**candidatos** (contains, não exato) — casar `5514` sem cuidado pega `255514` como falso
positivo (substring de outro chamado). O match exato (`\bch5514\b`, com word-boundary) é feito
no domínio (`motor/domain/commits.py`), não na busca do git — mais portável e testável com
`FakeGit`. Hoje só existe o padrão `ch<num>`; o `VB-<num>` do ClickUp saiu, era artefato
daquela ferramenta (identidade da tarefa é só o chamado).

**Tarefa marcada em duas versões abertas é dado inconsistente, não erro fatal:** o motor
sinaliza (`tasks_ambiguas`) e pinta vermelho, mas o comando termina normal.

Sem bloqueador de API aqui: a REST do Tickio filtra por sistema e versão direto na
requisição (`?sistema=<id>&versao=<X.Y.Z>`) — o problema do MCP do ClickUp, que não filtrava
por custom field, não existe do lado do Tickio. Autenticação e formato da resposta: §10.

## 5. As três operações

Núcleo compartilhado: `alvo()` (§4) + `presente()` (§2) + `worktree isolada` + `git rerere on`
+ **`git fetch origin` antes de ler qualquer ref**. `tag_exists` e `list_version_branches` leem
o ref store **local**; sem buscar primeiro, uma versão liberada em outra máquina fica
invisível e o run sobrescreveria o snapshot de uma versão que já saiu. As quatro operações
(`verificar`, `atualizar`, `criar`, `reconstruir-estado`) fazem esse fetch como primeiro passo.

O fetch resolve os dois casos, mas por caminhos diferentes: **tag** chega como
`refs/tags/X` (tag-following), então `tag_exists` a vê; **branch** chega como
`refs/remotes/origin/X` e o fetch **nunca** cria head local, então `list_version_branches`
lista `refs/heads/` ∪ `refs/tags/` ∪ `refs/remotes/origin/` — só com `refs/heads/` uma
versão aberta em outra máquina continuaria invisível depois do fetch, `versoes_abertas` seria
uma visão local do conjunto aberto e `fontes_de_alvo` omitiria essa versão em silêncio (§2).

`origin` e não qualquer remoto, de propósito: é o único que o motor usa (todo entry point faz
`fetch("origin")`, e `push`/`pull`/`remote_branch_exists` passam o literal), e é o único que o
`BaseResolver` tenta. Aceitar qualquer remoto punha no conjunto aberto uma versão que a
resolução de base depois não resolve — versão fantasma no alvo e erro desconcertante na base.

Custo aceito: um `refs/remotes/origin/X` velho, de branch apagada e nunca liberada, lê como
aberta até alguém rodar `git fetch --prune`.

### `verificar X.Y.Z` (read-only)

```
fetch origin                                          # antes de ler qualquer ref
abertas = versoes_abertas(branches, tags)
congela toda versão com tag nova (liberada_em = data do commit da tag, não now())
se X.Y.Z já liberada: devolve o snapshot gravado no banco, não recalcula nada (§6)

tgt      = alvo(X.Y.Z, abertas)                       # §4, união das versões-fonte
anterior = estado.atribuicoes(repo, X.Y.Z)            # lido ANTES de sobrescrever
faltam_no_git = [c for c in tgt.commits if not presente(c, branch)]
sumidos       = commits de atribuição JÁ APLICADA que sumiram do git
                (atribuição pendente não conta — commit ainda não cherry-pickado é normal, §9)
conflitam     = [c for c in faltam_no_git if merge_tree_conflita(base, branch, c)]

relatorio:
  Tickio vs estado: tasks novas / removidas
  estado vs git:    estado íntegro? (senão: commit sumido de atribuição aplicada)
  faltantes:        N commits, quais, quais conflitam
  → status VERDE só se Tickio == estado == git (e sem tasks_ambiguas)

estado.substituir_atribuicoes(repo, X.Y.Z, novas)     # sobrescreve por último
```

Predição de conflito **sem tocar a working tree**:
`git merge-tree --write-tree --merge-base=<parent(c)> <branch-tip> <c>` (Git ≥ 2.38).
Reporta os arquivos que conflitariam **antes** de aplicar.

> Complemento: após `verificar` dar verde em commits, chamar a skill **`validar-versao`**
> (sintaxe Python, validação Django, migrations South faltantes). São checagens ortogonais —
> `verificar` = completude de commits; `validar-versao` = integridade do código resultante.

### `atualizar X.Y.Z` (in-place — recusado em versão liberada)

```
fetch origin; recusa se X.Y.Z tem tag (liberada, §6)  # antes de tocar branch ou worktree
faltam ordenados por commit-date asc (sem agrupar por task — commits de tasks diferentes
intercalam se suas datas intercalarem)
para cada commit em faltam:
  git cherry-pick -x <commit>
  se conflito:
    rerere tenta replicar resolução conhecida
    se resolveu automaticamente → git cherry-pick --continue
    senão → PARA: mostra arquivos + "resolva e rode: <tool> atualizar --continue"
regrava as atribuições com o lote aplicado (tarefa sem commit nenhum continua pendente, §9)
push da branch
```

**Ordenação:** `git log` lista do mais novo pro mais antigo por padrão — a ordenação por
commit-date asc não vem de flag do git (`--reverse` seria frágil a mudanças de critério); é
feita explicitamente no domínio, ordenando `CommitRef.commit_date` (testável com `FakeGit`,
sem depender do comportamento do CLI, §14).

**Versão liberada é recusada, não só o rebuild — a inversão central deste redesenho.** Antes,
`atualizar` era o único modo permitido numa versão tagueada (§6 antigo); agora tag = imutável
e `atualizar` recusa de cara — a tarefa esquecida vai para a próxima versão em construção
(§4), nunca para a que já saiu. A recusa roda **antes** de tocar a worktree ou a branch, tanto
no `atualizar` normal quanto no `--continue` (que reavalia a recusa de novo, para o caso de a
versão ter sido liberada enquanto um conflito estava aberto) — nenhum commit chega a entrar na
branch de uma versão liberada por essa via.

**Estado em lote:** a atribuição é regravada **uma vez, ao final** do lote, não por commit
aplicado — simplicidade deliberada. Se o processo for interrompido no meio, os cherry-picks já
feitos ficam com trailer (prova em git) mas o estado atrasado; a próxima rodada detecta isso
como "pick manual sem o tool" (§9) e oferece regularizar. Aceitável porque a interrupção é
rara e sempre recuperável — não compensa a complexidade de regravar o estado a cada task.

**Só adiciona história** — nunca reescreve.

### `criar X.Y.Z`

```
fetch origin; recusa se X.Y.Z já publicada (tag ou branch remota — §6)
base = infere_base(X.Y.Z)                 # §7
git worktree add -b X.Y.Z <base>
escreve VERSAO em arquivo na branch
registra a versão no estado (base preenchida)
atualizar X.Y.Z                         # reusa o fluxo acima
```

Como a branch é nova e não publicada, aqui o rebuild idempotente (recriar do zero a cada
tentativa, com `rerere` replicando resoluções) é permitido — útil se você quer refazer a
composição antes do primeiro build. Deixa de ser permitido assim que a versão é publicada
(tag ou branch remota — §6), e completamente vedado depois de liberada.

## 6. Regra de publicação (`liberada` vs. `publicada`)

O redesenho separa duas travas que a versão antiga confundia num só conceito ("tagueada"):

```
liberada(X.Y.Z):   git tag -l X.Y.Z existe?                          # SÓ a tag
publicada(X.Y.Z):  liberada(X.Y.Z) OU git ls-remote --heads origin X.Y.Z existe?
```

- **`publicada`** (tag OU branch remota) → trava o **rebuild**: `criar` recusa se a versão já
  tem tag ou já existe como branch remota — impede recriar do zero uma branch que outra
  máquina já tem. É a mesma trava de sempre (§13 antigo a chamava só de "trava do rebuild").
- **`liberada`** (só tag) → **congela** a versão: `atualizar` passa a recusar por completo
  (§5) — deixou de ser "o modo seguro para versão tagueada" e passou a ser o modo proibido. O
  snapshot das atribuições também vira imutável (abaixo).

A tag só nasce quando a versão é liberada em produção (mecanismo de release ainda não
definido). Portanto "com tag" = liberada em produção = estado imutável.

### O congelamento é constraint de banco, não `if` de aplicação

Uma trigger em Postgres recusa qualquer `INSERT`/`UPDATE`/`DELETE` em `atribuicao` ou
`atribuicao_commit` que toque uma versão com `liberada_em` preenchido. A trigger olha **tanto
`old.versao_id` quanto `new.versao_id`** — não só o novo. A primeira versão da trigger só
olhava `new`, o que deixava passar `UPDATE atribuicao SET versao_id = <versão aberta> WHERE
versao_id = <versão liberada>`: o `new.versao_id` cai numa versão aberta, o guard não vê nada
de errado, e a linha some silenciosamente do snapshot congelado. A intenção original da spec —
"guard em Python não protege de um `DELETE` digitado à mão" — só se sustenta checando os dois
lados; a trigger foi corrigida para isso.

`liberada_em` é `timestamptz`, e a data gravada é a **data do commit apontado pela tag**, não
`now()` — senão o registro diria quando o comando rodou, não quando a versão saiu.

`substituir_atribuicoes` (a única escrita em `atribuicao`/`atribuicao_commit`) recusa **antes**
de chegar no banco, tanto no adapter Postgres quanto no fake: versão liberada, e versão que
nunca foi registrada no estado. Isso não é redundante com a trigger — se os `DELETE`s do
`substituir_atribuicoes` afetam zero linhas (snapshot já vazio) e a lista nova também vem
vazia, nenhum `INSERT` chega a disparar a trigger, e o commit passaria em silêncio sem a
checagem explícita. A trigger fica como cinto-e-suspensórios para quem escreve SQL à mão; a
recusa que garante o invariante é a do adapter.

**Não existe trigger na tabela `versao` em si — limitação conhecida, não um buraco.**
`UPDATE versao SET liberada_em = NULL` levanta o congelamento e os triggers filhos ficam
inertes. Isso foi deixado assim de propósito: zerar uma coluna chamada `liberada_em` não é
acidente, é a via de escape para o operador que sabe o que está fazendo (ex.: zerar
`liberada_em` para rodar `reconstruir-estado` de novo sobre uma versão liberada, §3 — e é a
via, não uma entre duas: `delete from versao` é recusado pela FK de `atribuicao`); e uma trigger em
`versao` correria o risco de travar o próprio upsert que `registrar_versao` faz. Quem lê esta
seção deve saber que o invariante de imutabilidade é forte um degrau apenas: as tabelas
`atribuicao`/`atribuicao_commit` são protegidas, a tabela `versao` que as trava não é.

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
2. **Checkpoint resumível** — a worktree fica no estado do conflito; `--continue` retoma,
   `--abort` restaura.
3. **Worktree isolada** — sua árvore de trabalho principal nunca é tocada.

## 9. Reconciliação quando as 3 fontes divergem

| Caso                                  | Sinal                     | Ação do tool                                                 |
| -------------------------------------- | -------------------------- | --------------------------------------------------------------- |
| Task nova marcada p/ versão           | em Tickio, fora do estado | `atualizar` aplica + registra no estado                     |
| Task desmarcada do alvo               | no estado, fora do Tickio | **avisa**; remoção é decisão humana (reverter é destrutivo) |
| Commit do estado sumiu                | no estado, fora do git    | **alerta forte** — estado corrompido/rebase; não auto-corrige |
| Pick manual sem o tool                | no git, fora do estado    | **avisa**; oferece regularizar o estado                     |
| Grep pegou commit que não deve entrar | candidato                 | mover para `exclusao` com motivo                             |

**Duas ressalvas que a tabela sozinha não deixa explícitas, e que o redesenho precisou
acertar:**

- **"Commit do estado sumiu" só vale para atribuição já `aplicado`.** Uma atribuição
  `pendente` — tarefa marcada, commit ainda não cherry-pickado — está ausente do git por
  definição normal, não por corrupção. Contá-la como "sumida" faria toda versão recém-criada
  reportar `estado: divergente do git` entre um `verificar` e o `atualizar` seguinte, sem nada
  de errado ter acontecido.
- **Tarefa sem commit nenhum nunca vira `aplicado`.** Marcar como entregue algo que não foi
  aplicado registraria uma entrega que não aconteceu; a tarefa fica `pendente` e aparece como
  faltante (`tasks_sem_commits`) até alguém achar o commit ou registrar em `sem_entrega`.

## 10. Dependências / decisões em aberto

- **Autenticação no Tickio é por credencial, não por token (decidido).** `TICKIO_USER` /
  `TICKIO_PASSWORD` no `.env`; **não existe flag `--tickio-token`** — o adapter faz
  `POST /api/v1/ws/token/` a cada execução e usa o `access` recebido. O CLI vive segundos, e
  reautenticar a cada run sai mais barato do que reeditar o `.env` toda vez que o JWT expira.
  Sem credencial configurada, alvo não é determinístico (fallback: `--task-source manual` com
  `--lista`).
- **As variáveis `TICKIO_*` só são cobradas na primeira busca, não na construção do adapter.**
  Isso deixa `reconstruir-estado` e `atualizar --abort` rodarem sem credencial do Tickio
  configurada — são comandos de recuperação que nunca chamam `fetch`. O custo: em `criar` e em
  `atualizar` normal, uma credencial faltante só aparece **depois** que o fetch de refs, a
  worktree e o registro inicial da versão no estado já aconteceram — o erro chega tarde, não
  na entrada do comando.
- **`--task-source` aceita `tickio` ou `manual`** (não `rest`), default `tickio`, e vive no
  parser compartilhado com `--lista` — todo comando aceita as duas flags, mesmo os que nunca
  chegam a usar a fonte de tasks.
- **Convenção de mensagem (decidido)** — grep casa só `ch<num>`. O `VB-<num>` do ClickUp saiu
  junto com o `custom_id`: identidade da tarefa é hoje só o número do chamado.
- **Formato do tool (decidido)** — motor + daemon localhost, em etapas. Ver §13.
- **Pendência única, restrita ao parsing:** o corpo de resposta de
  `GET /api/v1/ws/versoes/chamados/` **nunca foi observado**. `_extrair_chamados`
  (`motor/adapters/tasksource/tickio.py`) tolera três formas plausíveis — lista de números,
  lista de objetos com campo `chamado`, ou envelope paginado com `results` — e levanta
  `MotorError` nomeando o que voltou para qualquer outra forma. É uma suposição informada
  esperando confirmação contra a API real, não um contrato validado; melhor descobrir isso
  lendo este parágrafo do que por um erro em produção.
- **Operação futura `liberar`** — hoje fora de escopo (§12); consideração para depois da Etapa 1:
  incorporar a liberação (hoje manual: tag na HEAD da branch) como 4ª operação. Implicações a
  resolver quando entrar no escopo:
  - Pré-condição natural: só libera se `verificar` estiver **verde**.
  - `TaskSource` hoje só lê (`fetch`); marcar task como finalizada no Tickio exige escrita —
    nenhum adapter atual suporta isso.
  - Overlap com o processo de release externo que hoje cria a tag (mecanismo ainda não
    definido, §6) — definir quem passa a ser dono da tag (a ferramenta cria e o release
    fica só leitura, ou o inverso).

## 11. Multi-projeto

A ferramenta é apartada e opera sobre **múltiplos repositórios** (hoje `vendabemweb`,
`vendabemweb2`, `vb2web`), seguindo a mesma lógica. As premissas do ambiente tornam isso
barato:

- Todos os projetos são **sistemas cadastrados no Tickio**, cada um com seu próprio
  `tickio_sistema_id` (tabela `repo`, spec §4).
- O **esquema de versionamento é sempre igual** (§7) — não varia por projeto.
- A **convenção de mensagem é a mesma** (`ch<num>`, para todos).
- **Build está fora de escopo** — a ferramenta só monta/verifica a versão.

### Consequência: quase nada é "config por projeto"

O único parâmetro que define o "projeto" é **qual repositório git a ferramenta aponta**; o
que muda por repo é uma linha na tabela `repo` (nome + `tickio_sistema_id`), não config de
aplicação:

```
motor verificar   13.7.0 --repo /Volumes/.../vendabemweb
motor verificar   13.7.0 --repo /Volumes/.../vb2web
motor atualizar   13.7.0 --repo /Volumes/.../vb2web
```

Não há `.versao.toml` por projeto, hook de build, nem regras de base por repo. Se um dia um
projeto divergir (outro esquema, outra convenção), aí sim se introduz um arquivo de config —
**não antes** (rule of three: abstrai-se no caso que quebra a premissa, não por antecipação).

### Desambiguação: `?sistema=` corta na fonte, não depois

Antes (ClickUp), o alvo compartilhado vinha por sprint e a separação por projeto era feita
**depois**, localmente: buscava-se a tarefa, e ela só entrava no repo cujo grep achasse commit
dela. Agora o adapter `TickioRest` já manda `?sistema=<tickio_sistema_id>&versao=<X.Y.Z>` na
requisição (§4, §10) — **o corte por projeto acontece na fonte**, antes de qualquer commit ser
resolvido. `--repo` decide qual `sistema_id` entra na chamada; o Tickio devolve só os chamados
daquele sistema.

A checagem "o commit existe neste repo" não desaparece, mas deixa de ser o mecanismo
**principal**: continua como rede de segurança para a tarefa _fullstack_ marcada para um só
sistema mas que também tem commits no outro repo — a distribuição fina de commits entre
projetos ainda passa pelo `CommitSource` de cada repo, só que a separação grossa já vem pronta
do `?sistema=`.

Cada projeto tem sua **própria sequência** de versões, mas mantidas **equiparadas** (na
prática os números tendem a coincidir); isso não muda com o redesenho.

### Estado por projeto

Nada é compartilhado entre repos exceto o **motor** e a **fonte Tickio** (o servidor — cada
repo consulta seu próprio `sistema_id`):

- O estado mora no Postgres, escopado por repo em toda tabela: `versao` e `exclusao`/
  `sem_entrega` têm `repo_id` direto; `atribuicao`/`atribuicao_commit` chegam ao repo
  transitivamente por `versao_id` (não têm `repo_id` próprio) — era por-branch no lock antigo,
  agora é por-linha no banco.
- `git rerere` (resoluções de conflito) é **por repo** (cada repo é um checkout distinto).
- Worktrees isoladas são **por repo**.
- **`repo.nome` é resolvido pelo basename do `--repo`**, com `repo_alias` cobrindo nomes
  alternativos de diretório (ex.: `vb2` apontando para o mesmo `repo_id` de `vb2web`) — sem
  isso, clonar o mesmo repositório com outro nome fragmentaria o estado em duas linhas
  paralelas, sem erro nenhum aparecer.

### Aberto / edge

- Task _fullstack_ que precise de **números diferentes** em cada projeto (ex.: front 13.7.0 e
  back 4.2.0) não é expressável numa marcação de versão só no Tickio. As sequências são
  independentes, mas como são mantidas equiparadas isso raramente aparece; se aparecer, exige
  duas marcações. Fica anotado, não resolvido.

## 12. Fora de escopo

- Criação de tag e atualização de status no Tickio → **hoje** fora de escopo (a ferramenta
  apenas **lê** as tags, §6, para saber se a versão está publicada); candidatas a virar a
  operação `liberar` no futuro — ver §10.
- Deploy em cliente.
- Validação de integridade do código → skill `validar-versao` (chamada por `verificar`).
- Relatório HTML estático → descartado (não agrega sem ser interativo).

## 13. Roadmap de implementação

Projeto apartado, multi-projeto (§11). O motor é o núcleo chamável; o daemon é fachada por
cima — nunca duplica lógica. Segurança/complexidade só entram na etapa que **age** pelo git.

**Stack (decidido, revisto): Python.** A escolha original era Go; o motor foi reescrito em
Python (`motor/`) durante o redesenho Tickio + Postgres. `subprocess` cobre o `GitRepo`
inteiro (git é sempre subprocess), `httpx` o cliente REST do Tickio, `sqlalchemy` + `alembic`
o estado (§3, §14). Protocolos do `typing` mapeiam direto pras portas do §14 (`TaskSource`,
`CommitSource`, `GitRepo`, `EstadoRepo`); `argparse` é o CLI fino do §5.

**Etapa 1 — Motor. Concluída.**
Núcleo chamável (`motor/`) + um CLI fino (`uv run motor`) para exercê-lo antes de existir
daemon. Contém tudo que é correção: resolução do alvo com distribuição entre versões (Tickio,
§4), oráculo `presente()` (§2), estado em Postgres (§3) + `reconstruir-estado`, as 3 operações
(§5), predição `merge-tree` (§5), `rerere` e worktree isolada (§8), inferência de base (§7),
travas de publicação e congelamento (§6). Suíte de testes cobre tudo isso sem git nem rede
reais (`FakeGit`, `FakeEstado`, `FakeTaskSource`); a suíte de integração em
`tests/test_estado_postgres.py` (dez testes, `pytestmark = pytest.mark.integracao` no módulo
inteiro) cobre o mesmo `EstadoRepo` contra Postgres real, incluindo a trigger de congelamento.
O CLI usa desenvolvimento por padrão (`uv run motor verificar ...`); produção exige
`uv run motor --env production verificar ...`. Produção carrega `.env`; desenvolvimento e
a suíte carregam `.env.development`. Os dois usam
o mesmo `compose.yml`, mas `COMPOSE_PROJECT_NAME`, porta, banco, usuário e volume diferentes.
Antes de qualquer `TRUNCATE`, a fixture recusa valores que não sejam exatamente os do banco
de desenvolvimento.

Repos são cadastrados sem SQL direto:

```
uv run motor repo adicionar vendabemweb --tickio-sistema-id 7
uv run motor --env production repo adicionar vendabemweb --tickio-sistema-id 7
```

**Etapa 2 — Daemon localhost, só visualização (read-only).** *Ainda não implementada.*
Servidor em `127.0.0.1` que mostra o `verificar` de forma visual: cruzamento 3-vias
(Tickio × estado × git), commits faltantes, quais conflitam, **os dois repos lado a lado**.
Nenhuma mutação. Mesmo read-only, bind restrito a `127.0.0.1` + token por requisição
(defesa contra CSRF de aba maliciosa — o footgun clássico de web local que executa comando).

**Etapa 3 — Execução das rotinas pelo daemon.** *Ainda não implementada.*
`criar` / `atualizar` disparados pela UI. Orquestração de conflito: detecta → mostra o diff
→ "resolva no editor e clique Continuar" (a **edição** do merge fica no editor, não no
navegador; §8). Postura de segurança completa: CSRF token por ação, `127.0.0.1` apenas.

## 14. Arquitetura do motor

**Portas-e-adaptadores** com núcleo puro. Quatro portas de verdade hoje — `TaskSource`,
`CommitSource`, `GitRepo` e `EstadoRepo` (**nova**, §3/§4 da spec) — cada uma com pelo menos
um adapter fake para a suíte rodar sem git, rede ou banco; o resto é módulo comum, sem
catedral de interfaces.

```
                 front-ends (FORA do motor)
                 CLI  ·  daemon localhost (futuro, §13)
                        │  chamam a API de Operações
      ┌─────────────────┴────────────────────────────┐
      │             OPERAÇÕES (use-cases)             │
      │   criar · verificar · atualizar ·             │
      │   reconstruir_estado                          │
      ├────────────────────────────────────────────────┤
      │             SERVIÇOS DE NÚCLEO                 │
      │   TargetResolver · PresenceOracle ·            │
      │   BaseResolver · PublicationGate ·             │
      │   reconstrutor (função, varre trailers)        │
      ├────────────────────────────────────────────────┤
      │         DOMÍNIO (dados + regras PURAS)         │
      │   Version · TargetSet · Atribuicao ·           │
      │   CommitRef · VersionStatus · reconciliação ·  │
      │   distribuição entre versões (§4) · inferência │
      └───────┬───────────┬────────────┬───────────────┘
              │           │  portas    │
     ┌────────┴──┐ ┌──────┴─────┐ ┌────┴─────────┐  ┌────────────────┐
     │ TaskSource │ │CommitSource│ │   GitRepo    │  │  EstadoRepo    │ ← NOVA
     ├────────────┤ ├────────────┤ ├──────────────┤  ├────────────────┤
adapt│ TickioRest │ │GrepCommit  │ │GitSubprocess │  │ PostgresEstado │
ers: │ ManualList │ │BitbucketPR │ │FakeGit(teste)│  │ FakeEstado     │
     │ FakeTaskSrc│ │Chain · Fake│ └──────────────┘  └────────────────┘
     └────────────┘ └────────────┘
```

### Camadas

**Domínio (puro, zero I/O — o coração testável).** Só dados + funções determinísticas; nada
toca git, rede ou banco.

- Tipos: `Version{Numero, Tipo, Base}`, `CommitRef{HashOrigem, Chamado, CommitDate, Msg}`,
  `TargetSet` (task→commits), `Atribuicao{Chamado, Marcada, Estado, Commits}` — o que vai para
  o estado —, `VersionStatus`. `Lock` não existe mais; nenhum tipo carrega `task`/`título`/
  `VB-<num>` — identidade é só o chamado.
- Regras: inferência de tipo pelo número, inferência de base (§7), **distribuição entre
  versões** (`versoes_abertas`, `fontes_de_alvo` — §4), **reconciliação 3-vias** (Tickio ×
  estado × git → faltantes / novas / removidas / sumidos), match exato de `ch<num>` por
  word-boundary sobre candidatos do `CommitSource` (§4), ordenação de commits por
  `commit_date` asc antes de aplicar (§5).

**Portas (as 4 fronteiras com o mundo).**

- `TaskSource.fetch(versao) -> list[str]` — números de chamado marcados para a versão.
  Adapters: `TickioRest` (produção), `ManualList` (fallback sem Tickio), `FakeTaskSource`
  (testes). O bloqueador de custom field do ClickUp saiu — o Tickio filtra por sistema+versão
  direto na REST (§4, §11).
- `CommitSource.resolve(chamados) -> dict[chamado, list[CommitRef]]` — acha os commits de um
  lote de chamados numa varredura só. Adapters: `GrepCommitSource` (grep em `master`, fallback
  sempre disponível), `BitbucketPRCommitSource` (commits de PR mesclada, fonte primária quando
  há token), `ChainCommitSource` (tenta PR, cai pro grep), fake para testes. Esta porta nunca
  soube do ClickUp — sobreviveu intacta ao redesenho, só perdeu o segundo padrão do
  `match_exato` (`VB-<num>`).
- `GitRepo` — conjunto **enxuto**: `merge_base`, `is_ancestor`, `commits_in_range`,
  `commit_meta`, `patch_id`, `cherry_pick_x → Aplicado|Conflito`, `rerere`/`continue`/`abort`,
  `predict_merge` (merge-tree), `worktree_add/remove`, `tag_exists`, `remote_branch_exists`,
  `push_branch`, `pull_branch`, `fetch`, `list_version_branches`, `list_version_tags`,
  `read/write_file`. Adapter real (subprocess) + `FakeGit` para testes. `fetch` e
  `list_version_tags` sustentam o congelamento (§6): sem o primeiro, uma tag liberada em outra
  máquina fica invisível; sem o segundo, não haveria como observar que uma versão ganhou tag.
- **`EstadoRepo` — porta nova.** Substitui o antigo `LockStore` (que era módulo fino sobre
  `GitRepo`, nunca uma porta própria) porque o estado agora mora num sistema externo de
  verdade (Postgres), não num arquivo dentro do próprio git: `resolver_repo`,
  `registrar_versao`, `marcar_liberadas`, `versao`, `atribuicoes`, `substituir_atribuicoes`,
  `exclusoes`, `sem_entrega`. Adapters: `PostgresEstado` (traduz modelo SQLAlchemy ↔ dataclass
  do domínio na fronteira — o domínio nunca importa `sqlalchemy`) e `FakeEstado` (dict em
  memória, espelha as mesmas recusas da trigger de congelamento para o teste de engine não
  validar um comportamento que não existe em produção).

**Serviços de núcleo (orquestram; dependem só de portas + domínio).**

- `TargetResolver` — TaskSource + CommitSource → `Alvo`. Aplica a regra de distribuição (§4):
  une as tarefas de toda versão em construção ≤ alvo antes de resolver os commits numa
  varredura só. A desambiguação multi-projeto (§11) hoje começa antes disso, no `?sistema=` da
  requisição — este serviço já recebe tarefas do sistema certo.
- `PresenceOracle` — `presente()` (§2): hash-ancestral → trailer → patch-id.
- `BaseResolver` — número → commit-base (fork point, §7).
- `PublicationGate` — `liberada()` (só tag, congela) e `publicada()` (tag OU branch remota,
  trava rebuild) — §6.
- `reconstrutor` (função, não um serviço com estado) — varre trailers `base..HEAD` e reagrupa
  por chamado; usado por `reconstruir_estado`. Não existe mais um `LockStore` nem um
  `ConflictSession` como objetos: leitura/escrita do estado vai direto pela porta `EstadoRepo`,
  e o conflito de cherry-pick é só um valor de retorno (`AtualizarResult` com `status=BLOCKED`,
  `blocked_commit`, `arquivos_conflito`) — não precisa de uma "sessão" própria porque
  `atualizar --continue` reconstrói tudo a partir do git e do estado a cada chamada, sem nada
  em memória entre invocações do CLI.

**Operações (API que CLI e daemon chamam).** `criar` · `verificar` · `atualizar` ·
`reconstruir_estado`.

- `verificar` = fetch + congela tags novas + TargetResolver + PresenceOracle + reconciliação +
  `predict_merge` → `VersionStatus`; devolve o snapshot do banco sem recalcular se a versão já
  estiver liberada (§6). Read-only sobre o git, mas escreve o estado — sobrescreve as
  atribuições da versão ainda aberta.
- `criar` = trava de `publicada` (§6) → BaseResolver → `worktree_add(branch, base)` →
  `registrar_versao` → `atualizar`.
- `atualizar` = recusa se `liberada` (§6) → `verificar` → aplica faltantes por commit-date via
  `cherry_pick_x` → em conflito devolve `BLOCKED{commit, arquivos}` → regrava as atribuições
  do lote → `push_branch`.
- `reconstruir_estado` = varre trailers `base..HEAD` (§3) → retorna `DONE` ou
  `PENDING_JUDGMENT{orfaos}` se houver commit sem `ch<num>` na mensagem.

### Invariante que sustenta tudo

**O motor é não-interativo e determinístico.** Nunca pergunta nem bloqueia esperando humano:
`atualizar` **retorna um valor** — `AtualizarResult` com `status=DONE` ou
`BLOCKED{commit, arquivos_conflito}`; `reconstruir_estado` segue o mesmo padrão com
`DONE`/`PENDING_JUDGMENT{orfaos}`. Quem dirige o humano (resolver no editor → `--continue`;
decidir os órfãos) é o front-end. Por isso **o mesmo núcleo serve CLI e daemon** sem mudança,
e — como todo efeito passa por porta — o domínio é testável com
`FakeGit`/`FakeTaskSource`/`FakeEstado`, sem repo, rede nem banco.

### Onde deliberadamente NÃO se abstrai

- Sem porta de "clock" — ordenação usa a data do commit (vem do git), não relógio; a data de
  liberação também vem do commit apontado pela tag, não de `now()` (§6).
- Sem `LockStore` nem `ConflictSession` como objetos — ver acima.
- Sem camada de "config por projeto" — o projeto é a linha `repo` (nome + `tickio_sistema_id`,
  §11), não um arquivo de config.
- Sem cache pra `tag_exists`/`remote_branch_exists` — checagem direta a cada chamada, sempre
  depois de um `fetch` (§5). Latência de rede é desprezível pra uso sob demanda solo, e esse
  gate trava rebuild e congelamento: dado stale aqui é mais perigoso (permitiria escrever numa
  versão já liberada) do que o custo de mais uma chamada de rede.
- **Sem trigger na tabela `versao`** — limitação conhecida, não abstração deliberada por
  simplicidade; ver §6.

## 15. Onde o código divergiu da spec, e o que ficou em aberto

Duas listas que existem para o próximo leitor não gastar tempo achando que encontrou
um bug. A primeira é código que **contradiz de propósito** a spec do redesenho
(`docs/superpowers/specs/2026-08-07-redesenho-tickio-design.md`); a segunda é
dívida conhecida.

### Divergências deliberadas — o código está certo, a spec é que precisa de emenda

As que já estão explicadas na seção que as governa não repetem aqui: trigger
checando `old` **e** `new` (§6), ausência de trigger em `versao` (§6), pré-checagem
de `liberada_em` no adapter em vez de confiar só na trigger (§6), `fetch` antes de
toda leitura de ref (§5), recusa de `atualizar` em versão com tag inclusive via
`--continue` (§5), credencial em vez de token (§10), validação das `TICKIO_*` na
primeira busca e não na construção (§10). As que faltavam:

- **`EstadoRepo` tem oito métodos, não os cinco da spec §4**, e o
  `sincronizar_versoes` de lá virou `registrar_versao` + `marcar_liberadas` +
  `versao` + `resolver_repo`. A assinatura única obrigaria a resolver `base` de toda
  versão aberta a cada comando; só a versão operada precisa, e ela é resolvida uma
  vez, na primeira gravação. A própria spec §4 também exige que o *engine*, não o
  adapter, calcule as datas de liberação a partir da tag — o que não cabe num
  método só.
- **`compose.yml` monta o volume em `/var/lib/postgresql`, não em
  `/var/lib/postgresql/data` como a spec §5 escreve.** No `postgres:18-alpine` o
  `PGDATA` é `/var/lib/postgresql/18/docker`; seguir a spec ao pé da letra montaria
  um diretório vazio irmão do PGDATA e **perderia os dados na recriação do
  volume**. Aqui a spec está simplesmente errada.
- **`resolve_ref` descasca a tag com `^{commit}`.** As tags de release deste repo
  são **anotadas**, então `rev-parse refs/tags/X` devolve o SHA do *objeto de tag*,
  não do commit. Sem descascar, `versao.base_commit` — coluna de auditoria — guarda
  algo que não é commit, `git show <base_commit>` mostra uma tag, e qualquer join
  contra `atribuicao_commit.hash_origem` não casa. `X^{commit}` é no-op quando `X`
  já é commit, então vale igual para branch, tag leve e hash cru.
- **Atribuição `pendente` não conta como commit sumido** (§9). Só atribuição já
  `aplicado` pode ter commit que desapareceu. Confundir "ainda não aplicado" com
  "foi aplicado e sumiu" fazia toda versão nova imprimir `estado: divergente do
  git` entre o `verificar` e o `atualizar` — veredito certo, diagnóstico errado.

### Dívida conhecida

Vazia. Os doze itens que estavam aqui foram fechados; ficam listados abaixo com
onde a correção mora, porque saber que algo *já* foi decidido é tão útil quanto
saber que falta.

- `status_versao` do retorno `BLOCKED` sem teste → asserção em
  `test_atualizar_para_em_conflito`.
- Pin do guard de rede vazio em máquina sem `.env` → virou pin **estrutural**
  (`cli.load_dotenv is None`). `load_dotenv()` procura o `.env` a partir do
  arquivo que a chama, não da CWD, então não dá para plantar um `.env` de teste e
  observar o efeito — e como `main()` faz `if load_dotenv: load_dotenv()`, "a
  guarda está instalada" é o contrato inteiro.
- `sessao_postgres` truncava só no setup → trunca também no teardown.
- `InterfaceError` no ramo genérico, `OperationalError` mais largo que a mensagem,
  e `"imutavel" in str(e.orig)` → os três eram o mesmo defeito: ramificar por tipo
  e por texto. `_traduzir_erro` agora ramifica por **SQLSTATE**. Sem SQLSTATE = o
  servidor nunca respondeu, o único caso em que "suba o container" ajuda; deadlock
  (40P01) e statement timeout (57014) caem no genérico; o congelamento é
  identificado por `errcode = 'MV001'`, que a trigger passa a levantar
  (`c31ffb4de7a1`), com fallback no texto para banco que ainda não migrou.
- `uq_versao_repo_id` nomeando por uma coluna uma constraint de duas → renomeada
  para `uq_versao_repo_id_numero`, com nome explícito no model.
- `tipo` e `estado` texto livre → `ck_versao_tipo` e `ck_atribuicao_estado`. Valor
  digitado errado via `psql` agora falha no `insert`, não como `KeyError` na
  leitura, longe da causa.
- `httpx.Client()` nunca fechado → `contextlib.ExitStack` nos dois adapters, que
  fecha só o cliente que o adapter criou; cliente injetado pertence a quem injetou.
- Conversão `timestamp ↔ timestamptz` dependendo do `TimeZone` da sessão →
  `postgresql_using="liberada_em at time zone 'UTC'"` nas duas direções.
- `%aI` onde a data de liberação quer `%cI` → `commit_meta` passou a `%cI`. As
  varreduras de range seguem em `%aI` porque `ordenar_por_data` quer a ordem de
  autoria; `commit_meta` é o único caminho que alimenta `liberada_em`.

Resta uma pendência, não dívida: o corpo de `GET /api/v1/ws/versoes/chamados/`
**nunca foi observado** (§10). Só uma chamada real ao Tickio fecha essa.
