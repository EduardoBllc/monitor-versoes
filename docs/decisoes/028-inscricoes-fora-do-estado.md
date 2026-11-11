# Inscrições fora do estado, um processo por inscrição

- **Status:** aceita; o ponto "cada inscrição roda com o diretório e o `--env` dela" foi
  revisto pela [031](031-ambiente-na-config-central.md); o parágrafo "Sem lock contra um
  `atualizar` manual" foi substituído pela [032](032-lock-por-repo-entre-processos.md)
- **Data:** 2026-11-05
- **Depende de:** [004](004-estado-descartavel.md), [021](021-motor-nao-interativo.md)

As inscrições (rodar `atualizar` periodicamente numa versão) ficam num **arquivo JSON local**
em `~/.local/share/monitor-versoes/`, não no estado. O caminho do clone e o `.env` são da
máquina, e o estado pode ser um Postgres compartilhado entre máquinas: uma inscrição gravada
lá apareceria em máquinas onde o clone não existe. O estado é projeção recuperável
([004](004-estado-descartavel.md)); a inscrição é configuração do operador e não se recupera
do git. Guarda só a última execução, sem histórico, e grava de forma atômica para que uma
execução interrompida não corrompa o arquivo.

Cada inscrição roda **em processo separado**, com o diretório e o ambiente (`--env`) dela.
Assim usa as próprias credenciais e o próprio banco, sem vazar ambiente para a seguinte, e a
falha de uma (inclusive um bug) não derruba as outras. O motor continua não interativo
([021](021-motor-nao-interativo.md)): uma execução que esbarra em conflito não pergunta,
devolve `BLOQUEADA` e as seguintes saem `PULADA` até o operador resolver.

Sem lock contra um `atualizar` manual na mesma versão: o `index.lock` do git faz uma das duas
falhar, e se for a agendada ela vira `ERRO`.
