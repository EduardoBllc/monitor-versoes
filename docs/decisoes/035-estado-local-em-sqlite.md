# O estado é local e mora só em SQLite

- **Status:** aceita
- **Data:** 2026-11-12
- **Depende de:** [004](004-estado-descartavel.md), [011](011-congelamento-no-banco.md),
  [028](028-inscricoes-fora-do-estado.md), [031](031-ambiente-na-config-central.md)

O estado ([004](004-estado-descartavel.md)) é de uma máquina só e mora num arquivo SQLite
local, `~/.local/share/monitor-versoes/estado.db` ou o caminho de `DATABASE_SQLITE_PATH`. O
primeiro uso cria o arquivo e as tabelas. Não há outro backend.

O Postgres entrou como opção para um estado compartilhado entre máquinas que nunca existiu: a
ferramenta tem um usuário, e o que o estado projeta depende de clones que são da máquina
([028](028-inscricoes-fora-do-estado.md)). O custo, por outro lado, era de todo dia: duas
variantes de trigger e de migração ([011](011-congelamento-no-banco.md)), a suíte de
contrato rodando nos dois, testes de integração com Docker, `compose.yml`, alvos de Makefile,
o `migrar-estado` e as cinco `DATABASE_*`. Com um backend só, o portão roda inteiro sem
Docker e nada fica pulado.

- **Configuração antiga dá erro, não cai no SQLite.** `DATABASE_BACKEND=postgres`, ou as
  cinco `DATABASE_HOST/PORT/NAME/USER/PASSWORD` preenchidas, fazem o motor parar antes de
  abrir o estado, com uma mensagem que explica a saída. Cair no SQLite em silêncio criaria um
  estado vazio e esconderia o julgamento humano, que só existe no banco antigo
  ([004](004-estado-descartavel.md)). Uma `DATABASE_*` solta não dispara o erro: sozinha ela
  não configurava Postgres nenhum.
- **A saída é o `migrar-estado` de um commit fixado.** O comando saiu junto com o backend.
  Quem tem estado em Postgres roda, antes de atualizar, o `migrar-estado` do último commit
  que o tinha (o SHA está na mensagem de erro e no README) para um SQLite, e depois tira as
  variáveis da configuração.
- **Sem dialeto nas migrações.** Revisão nova é escrita e testada só no SQLite. As antigas
  ficam como estão; o ramo de Postgres delas não roda mais.
