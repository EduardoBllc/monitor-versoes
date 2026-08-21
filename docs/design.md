# Desenho do monitor de versões

Por que o sistema é assim. Estrutura (schema, assinaturas, comandos) não está aqui —
essa o código responde melhor e sem apodrecer. Uso: `README.md`.

## 1. O problema

Uma versão de release é uma **branch**; quando é liberada, o HEAD dela recebe uma **tag**
homônima. Quem cria a tag é o processo de release, externo — a ferramenta apenas **lê** a tag
existente. Três tipos, pelo número:

| Tipo                    | Número  | Sai de                          |
| ----------------------- | ------- | ------------------------------- |
| Fechada                 | `X.0.0` | `master`                        |
| Ajustada                | `X.Y.0` | fechada ou ajustada anterior    |
| Específica de cliente   | `X.Y.Z` | qualquer versão anterior        |

A pergunta que a ferramenta responde é sempre a mesma: _"esta versão está com **todos** os
commits que deveria?"_. E ela é difícil por um motivo só: **cherry-pick troca o hash**.
Comparar hashes não responde nada.

O escopo do oráculo é **completude de commits**, não integridade do código resultante — essa
é a skill `validar-versao` (sintaxe Python, validação Django, migrations South faltantes).
Checagens ortogonais: rodar as duas.

## 2. O oráculo de presença: três fontes de verdade

Como o hash muda, a presença é respondida cruzando três camadas:

| Fonte                  | Representa                                            | Muda quando                                       |
| ---------------------- | ----------------------------------------------------- | ------------------------------------------------- |
| **Tickio**             | o que _deveria_ estar (alvo)                          | task marcada para uma versão (§4)                 |
| **estado (Postgres)**  | o que o tool _declarou_ colocar (intenção auditável)  | `verificar`/`atualizar` sobrescrevem; versão liberada nunca muda (§6) |
| **git (trailer `-x`)** | o que está _fisicamente_ aplicado (prova)             | um cherry-pick acontece                           |

Verde só quando `Tickio = estado = git`. Cada camada pega o que a outra não pega:

- **estado × Tickio** → task nova esquecida, ou task desmarcada do alvo.
- **estado × git** → estado "mentindo" (commit sumiu num rebase, ou `UPDATE`/`DELETE` manual
  na tabela).
- **git × estado** → cherry-pick feito à mão sem o tool (regularizar o estado).

**Por que não comparar só Tickio × git?** Porque o mapa task → commits é derivado por grep na
mensagem (`ch<num>`) — é _fuzzy_. Duas execuções podem derivar coisas diferentes. O estado
congela essa derivação numa decisão explícita e auditável, em vez de re-derivar a cada
operação. É o motivo de existir a camada do meio; sem ela sobram duas fontes e nenhuma
memória do que foi decidido.

### Definição de "presente"

```
presente(commit_origem, branch):
  1. hash exato é ancestral da branch?         (git merge-base --is-ancestor)  → sim
  2. algum commit da branch tem trailer         (git log --grep)
     "cherry picked from commit <commit_origem>"?                              → sim
  3. [legado] patch-id(commit_origem) ∈ patch-ids(base..branch)?               → sim
  senão → ausente
```

Item **2** é o principal: resiste a conflito resolvido, que muda o diff. Item **1** cobre
merge direto. Item **3** existe só para commits anteriores à convenção `-x`.

## 3. O estado: por que existe e por que é descartável

Mora em Postgres, escopado por repo. Guarda duas coisas de natureza diferente:

**Projeção, recuperável** — a derivação task → commits. `reconstruir-estado` regenera:
número, tipo e base saem do nome da branch mais a inferência (§5); as atribuições saem dos
trailers `cherry picked from <hash>` em `base..HEAD`, reagrupados por `ch<num>`.

**Julgamento humano, não recuperável** — exclusões ("esse commit o grep pegou mas não entra")
e registros de "não houve entrega". Só existe no banco. Para commit sem `ch<num>` na mensagem,
`reconstruir-estado` devolve `PENDING_JUDGMENT{orfaos}` e para; quem pergunta ao humano é o
front-end, nunca o motor (§9).

Três consequências que valem gravar:

- **Identidade da tarefa é só o número do chamado.** Os hashes gravados são sempre os de
  **origem**, nunca os pós-cherry-pick — esses se derivam dos trailers.
- **Atribuição tem dois estados, `pendente` e `aplicado`, e a diferença importa.** Tarefa
  marcada sem nenhum commit achado nunca vira `aplicado`: marcar como entregue algo que não
  foi aplicado registraria uma entrega que não aconteceu. Fica `pendente` e aparece como
  faltante até alguém achar o commit ou registrar que não houve entrega.
- **Dependência dura: todo pick usa `-x`.** O trailer é o backbone durável; o estado é a
  camada rápida por cima. Um cherry-pick sem trailer vira um buraco que `reconstruir-estado`
  não preenche.

### Reconstruir sobre uma versão liberada

O congelamento (§6) recusa a escrita. A via é zerar a data de liberação:

```sql
update versao set liberada_em = null where repo_id = … and numero = '13.34.0';
```

**Não é `delete from versao`:** a FK de `atribuicao` foi declarada sem `ondelete`, então o
`delete` é recusado justamente quando a versão tem atribuições — o caso em que se quer
reconstruir — e apagar os filhos primeiro bate na trigger de congelamento. Zerar
`liberada_em` também preserva a base já gravada.

## 4. O alvo: distribuição entre versões

Uma tarefa marcada para a versão `V` no Tickio vale para `V` **e para toda versão em
construção (sem tag) cujo número seja maior**. Não é preciso remarcar a tarefa a cada versão
nova que abre. Visto do lado da versão, que é como o motor precisa:

```
versoes_abertas(branches, tags) = branches sem tag homônima, em ordem semver
fontes_de_alvo(V, abertas)      = { W em abertas : W <= V }        # V incluso
alvo(V) = ∪ tickio.fetch(W), para todo W em fontes_de_alvo(V, abertas)
```

Só versões **em construção** entram na união — a liberada fica de fora, seu conteúdo chega a
`V` por ancestralidade da base (§5), não pela distribuição. A ordem é semver sobre `(x, y, z)`,
não textual: `13.9.0` vem antes de `13.10.0`.

Resolvidos os chamados, os commits saem numa **varredura só para todo o lote**, nunca uma por
versão-fonte.

**O match exato é do domínio, não da busca.** O `CommitSource` (grep em `master`, ou PR do
Bitbucket) só traz **candidatos** — é `contains`, não exato, e casar `5514` sem cuidado pega
`255514`, substring de outro chamado. A confirmação com word-boundary (`\bch5514\b`) roda no
domínio: mais portável, e testável com o git fake.

**Tarefa marcada em duas versões abertas é dado inconsistente, não erro fatal.** O motor
sinaliza e pinta vermelho, mas o comando termina normal.

### Autenticação, e o custo do erro tardio

A autenticação no Tickio é por **credencial, não token**: o adapter troca usuário e senha por
um `access` a cada execução. Não existe flag de token. O CLI vive segundos, e reautenticar a
cada run sai mais barato do que reeditar o `.env` toda vez que o JWT expira.

As variáveis do Tickio são cobradas **na primeira busca, não na construção do adapter**. Isso
é deliberado: deixa `reconstruir-estado` e `atualizar --abort` rodarem sem credencial
configurada — são comandos de recuperação que nunca consultam o Tickio. O custo aceito: em
`criar` e `atualizar`, uma credencial faltante só aparece **depois** que o fetch de refs, a
worktree e o registro inicial da versão já aconteceram. O erro chega tarde.

Sem credencial, o alvo não é determinístico; o fallback é a lista manual.

## 5. Inferência de base

```
X.0.0        → master
X.Y.0 (Y>0)  → maior X.(Y-1..0).0 existente         (13.7.0 → 13.6.0)
X.Y.Z (Z>0)  → X.Y.(Z-1) se existir, senão X.Y.0    (específica de cliente)
```

## 6. Duas travas: `publicada` e `liberada`

```
liberada(X.Y.Z):   a tag X.Y.Z existe?                                 # SÓ a tag
publicada(X.Y.Z):  liberada(X.Y.Z) OU existe branch remota X.Y.Z?
```

- **`publicada`** trava o **rebuild**: `criar` recusa se a versão já tem tag ou já existe como
  branch remota — impede recriar do zero uma branch que outra máquina já tem. Enquanto a
  branch é nova e não publicada, recriar do zero a cada tentativa é permitido e útil (o
  `rerere` replica as resoluções), então dá para refazer a composição antes do primeiro build.
- **`liberada`** **congela**: `atualizar` recusa por completo, e o snapshot das atribuições
  vira imutável. Tag só nasce quando a versão sai em produção, então "com tag" = imutável.
  Tarefa esquecida vai para a **próxima versão em construção** (§4), nunca para a que já saiu.

A recusa do `atualizar` roda **antes** de tocar a worktree ou a branch, e o `--continue` a
reavalia — a versão pode ter sido liberada enquanto um conflito estava aberto. Nenhum commit
entra na branch de uma versão liberada por essa via.

Para recalcular uma versão liberada sem descongelar o snapshot dela existe o modo de
auditoria: usa a tag como alvo e pula toda escrita no estado e na worktree.

### O congelamento é constraint de banco, não `if` de aplicação

Uma trigger recusa `INSERT`/`UPDATE`/`DELETE` em `atribuicao`/`atribuicao_commit` que toque
versão com data de liberação preenchida. Dois detalhes que custaram para acertar:

- **A trigger olha `old.versao_id` e `new.versao_id`, não só o novo.** Checando só `new`,
  um `UPDATE ... SET versao_id = <versão aberta> WHERE versao_id = <versão liberada>` passa: o
  novo id cai numa versão aberta, o guard não vê nada de errado, e a linha some em silêncio do
  snapshot congelado.
- **O adapter também recusa, antes de chegar no banco — e não é redundante.** Se os `DELETE`s
  da regravação afetam zero linhas (snapshot já vazio) e a lista nova também vem vazia, nenhum
  `INSERT` dispara a trigger, e o commit passaria em silêncio. A recusa que garante o
  invariante é a do adapter; a trigger é o cinto para quem escreve SQL à mão.

A data de liberação é a **data do commit apontado pela tag**, não `now()` — senão o registro
diria quando o comando rodou, não quando a versão saiu.

**Não existe trigger na tabela `versao` — limitação conhecida, não buraco.** Zerar
`liberada_em` levanta o congelamento e deixa as triggers filhas inertes. Foi deixado assim de
propósito: zerar uma coluna com esse nome não é acidente, é a via de escape para o operador
que sabe o que faz (§3), e uma trigger ali arriscaria travar o próprio upsert que registra a
versão. O invariante de imutabilidade é forte um degrau só: as duas tabelas de atribuição são
protegidas; a tabela que as trava não é.

## 7. Quando as três fontes divergem

| Caso                                  | Sinal                     | Ação                                                          |
| ------------------------------------- | ------------------------- | ------------------------------------------------------------- |
| Task nova marcada p/ versão           | em Tickio, fora do estado | aplica + registra                                             |
| Task desmarcada do alvo               | no estado, fora do Tickio | **avisa**; remoção é decisão humana (reverter é destrutivo)    |
| Commit do estado sumiu                | no estado, fora do git    | **alerta forte** — estado corrompido/rebase; não auto-corrige  |
| Pick manual sem o tool                | no git, fora do estado    | **avisa**; oferece regularizar o estado                       |
| Grep pegou commit que não deve entrar | candidato                 | vira exclusão, com motivo                                     |

**"Commit do estado sumiu" só vale para atribuição já `aplicado`.** Uma `pendente` — tarefa
marcada, commit ainda não cherry-pickado — está ausente do git por definição normal. Contá-la
como sumida faria toda versão recém-criada reportar estado divergente entre um `verificar` e o
`atualizar` seguinte, sem nada de errado ter acontecido: veredito certo, diagnóstico errado.

### Conflito

1. **`git rerere` ligado, com `rerere.autoUpdate` também** — grava a resolução uma vez e
   replica em reincrementos e rebuilds. O `autoUpdate` não é opcional: sem ele, a resolução
   conhecida é reaplicada no working tree mas o arquivo continua "unmerged" até um `git add`
   explícito, e o "resolveu automaticamente, segue o pick" nunca dispara sozinho.
2. **Nunca auto-resolve heurísticamente.** Conflito novo para e entrega o controle.
3. **Checkpoint resumível** — a worktree fica no estado do conflito.
4. **Worktree isolada** — a árvore de trabalho principal nunca é tocada.

A predição de conflito não toca a working tree:
`git merge-tree --write-tree --merge-base=<parent(c)> <branch-tip> <c>` (Git ≥ 2.38) reporta
os arquivos que conflitariam **antes** de aplicar.

**Ordem de aplicação: commit-date ascendente, ordenada no domínio.** Sem agrupar por task —
commits de tasks diferentes intercalam se as datas intercalarem. A ordenação não vem de flag
do git: `--reverse` seria frágil a mudança de critério, e no domínio ela é testável com o git
fake.

**O estado é regravado uma vez, ao final do lote**, não por commit aplicado. Se o processo for
interrompido no meio, os cherry-picks já feitos ficam com trailer (prova em git) e o estado
atrasado; a próxima rodada lê isso como "pick manual sem o tool" e oferece regularizar.
Aceitável porque a interrupção é rara e sempre recuperável.

`atualizar` **só adiciona história** — nunca reescreve.

## 8. Multi-projeto: as premissas que tornam isso barato

A ferramenta é apartada e opera sobre múltiplos repositórios. Quatro premissas do ambiente:

- Todo projeto é um **sistema cadastrado no Tickio**, com seu próprio id de sistema.
- O **esquema de versionamento é sempre o mesmo** (§5) — não varia por projeto.
- A **convenção de mensagem é a mesma** (`ch<num>`) para todos.
- **Build está fora** — a ferramenta monta e verifica, não constrói.

### Consequência: quase nada é "config por projeto"

O que define o projeto é qual repositório a ferramenta aponta. O que muda por repo é **uma
linha numa tabela** (nome + id do sistema no Tickio), não config de aplicação. Não há arquivo
de config por projeto, nem hook de build, nem regra de base por repo. Se um dia um projeto
divergir — outro esquema, outra convenção — aí se introduz config; **não antes**. Abstrai-se
no caso que quebra a premissa, não por antecipação.

### O corte por projeto acontece na fonte

A requisição ao Tickio já filtra por sistema e versão, então o alvo chega separado por projeto
**antes** de qualquer commit ser resolvido. A checagem "este commit existe neste repo" não
desaparece, mas deixa de ser o mecanismo principal: fica como rede de segurança para a tarefa
_fullstack_, marcada num sistema só mas com commits nos dois repos.

**O nome do repo vem do basename do path**, com aliases cobrindo nome alternativo de
diretório. Sem isso, clonar o mesmo repositório com outro nome fragmentaria o estado em duas
linhas paralelas — sem erro nenhum aparecer.

Cada projeto tem sua própria sequência de versões, mas mantidas equiparadas: na prática os
números tendem a coincidir. `rerere` e worktrees são por repo, cada um sendo um checkout
distinto.

**Edge aberto:** tarefa _fullstack_ que precise de **números diferentes** em cada projeto
(front `13.7.0`, back `4.2.0`) não é expressável numa marcação de versão só. As sequências são
independentes; como são mantidas equiparadas isso raramente aparece. Se aparecer, exige duas
marcações. Anotado, não resolvido.

## 9. Arquitetura: portas e o invariante

**Portas-e-adaptadores com núcleo puro.** Quatro portas: fonte de tasks, fonte de commits,
git e estado. Cada uma tem um adapter fake, e é por isso que a suíte roda sem git, sem rede e
sem banco.

O domínio é só dados e funções determinísticas — nada nele toca git, rede ou banco. As regras
que vivem lá: inferência de tipo e de base (§5), distribuição entre versões (§4),
reconciliação três-vias (§7), o match exato por word-boundary (§4) e a ordenação por data
(§7). A tradução entre modelo de banco e dataclass do domínio acontece na fronteira do
adapter: **o domínio nunca importa `sqlalchemy`**.

O estado fake **espelha as mesmas recusas da trigger de congelamento**. Não é zelo: um fake
mais permissivo que o banco deixa a suíte verde num caminho que quebra em produção.

### Quem monta os adapters é o front-end, nunca o engine

`motor/montagem.py` é o único módulo que conhece adapter concreto e `Deps` ao mesmo tempo.
CLI e TUI importam dele; o engine vê só `motor.ports`. A camada existe porque a alternativa
apareceu nas duas formas ruins: um `if token: PR senão grep` dentro do `verificar` (engine
importando `motor.adapters`), ou a mesma regra duplicada nos dois front-ends. Com dois
front-ends, "montar no chamador" precisa de um lugar só — e esse lugar não é o engine.

**Montar não é usar.** Nada na montagem faz I/O: não valida credencial, não consulta o git.
`atualizar --abort` e `reconstruir-estado` recebem as mesmas fontes e nunca as chamam — se a
montagem tocasse a rede ou o git, todo comando pagaria por elas, e um clone sem `origin`
passaria a falhar antes de começar. Por isso o `workspace/repo` do Bitbucket sai do remote na
primeira busca, dentro do adapter, e não na construção. Única exceção deliberada:
`resolver_repo`, porque o nome canônico e o `tickio_sistema_id` decidem *como* montar o resto.

Consequência de teste: as bordas de I/O se trocam em `motor.montagem`, não no front-end. Um
`monkeypatch` no módulo do CLI não alcança mais a montagem da TUI, e é justamente esse o
ponto — antes as duas se ligavam por um import de nome privado.

### O invariante que sustenta tudo

**O motor é não-interativo e determinístico. Nunca pergunta, nunca bloqueia esperando
humano — retorna um valor.** Conflito de cherry-pick vira `BLOCKED{commit, arquivos}`; commit
órfão vira `PENDING_JUDGMENT{orfaos}`. Quem dirige o humano (resolver no editor, decidir os
órfãos) é o front-end.

É o que faz o mesmo núcleo servir CLI e TUI sem uma linha de diferença, e o que faria um
daemon ser só mais um front-end. Também é o motivo de não existir objeto "sessão de conflito":
retomar reconstrói tudo do git e do estado a cada chamada, sem nada em memória entre
invocações.

### Todo entry point faz `git fetch origin` antes de ler qualquer ref

Sem isso, uma versão liberada em outra máquina fica invisível e o run sobrescreveria o
snapshot de uma versão que já saiu. O fetch resolve os dois casos por caminhos diferentes:
**tag** chega como `refs/tags/X`; **branch** chega como `refs/remotes/origin/X` e o fetch
**nunca** cria head local. Por isso a listagem de versões é `refs/heads/` ∪ `refs/tags/` ∪
`refs/remotes/origin/` — só com `refs/heads/`, uma versão aberta em outra máquina continuaria
invisível depois do fetch, e a distribuição do §4 a omitiria em silêncio.

**`origin`, não qualquer remoto**, de propósito: é o único que o motor usa e o único que a
resolução de base tenta. Aceitar qualquer remoto colocaria no conjunto aberto uma versão que
a resolução de base depois não resolve — versão fantasma no alvo e erro desconcertante na
base.

Custo aceito: um `refs/remotes/origin/X` velho, de branch apagada e nunca liberada, lê como
aberta até alguém rodar `git fetch --prune`.

### Onde deliberadamente não se abstrai

- **Sem porta de "clock".** A ordenação usa a data do commit, e a data de liberação vem do
  commit apontado pela tag — nunca de `now()` (§6). Não há relógio para injetar.
- **Sem camada de config por projeto** — o projeto é uma linha de tabela (§8).
- **Sem cache para as checagens de tag e branch remota.** Checagem direta a cada chamada,
  sempre depois do fetch. Latência de rede é desprezível para uso sob demanda, e esse gate
  trava rebuild e congelamento: dado stale aqui permitiria escrever numa versão já liberada —
  mais perigoso que uma chamada de rede a mais.
- **Sem trigger na tabela `versao`** — limitação conhecida, não simplicidade deliberada (§6).

## 10. Pendência viva

O corpo de resposta de `GET /api/v1/ws/versoes/chamados/` **nunca foi observado**. O parser
tolera três formas plausíveis — lista de números, lista de objetos com campo `chamado`, ou
envelope paginado com `results` — e levanta erro nomeando o que voltou para qualquer outra
forma. É uma suposição informada esperando confirmação contra a API real, não um contrato
validado. Melhor descobrir isso lendo este parágrafo do que por um erro em produção.
