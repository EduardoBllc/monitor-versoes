# Instalador, configurar e daemon no login

- **Status:** substituída por [045](045-daemon-processo-e-login-separados.md) nos pontos "uma
  peça só para manter o daemon de pé e subi-lo no login" e "toda reinstalação reinicia o
  serviço"; vale nos demais pontos
- **Data:** 2026-11-15
- **Depende de:** [039](039-versionamento-por-tag.md), [040](040-instalacao-pelo-registro-do-uv.md),
  [041](041-disparo-das-inscricoes-pelo-daemon.md)

Instalar exigia `uv`, `uv tool install` com a tag certa, plugins à mão e subir o `serve`
sempre que a máquina ligava. Um script de uma linha e um assistente cobrem isso.

**O script é fino; o assistente é Python.** O `install.sh` (e o `install.ps1`, no Windows) só garante git e `uv`, instala a
última release e chama o motor (`configurar`, `atualizar-motor`, `desinstalar`). Perguntas,
validação e escrita da config ficam no `motor.assistente`, com o `questionary`: as regras
ficam num só lugar, testável, em vez de repartidas entre `sh` e Python. O script só repete o
que precisa antes de o motor existir.

**O daemon sobe no login, sem root.** Serviço de usuário no systemd, LaunchAgent no macOS e tarefa do Agendador de Tarefas no Windows,
rodando `serve --sem-navegador` pelo executável do ambiente do `uv` (nunca pelo `PATH`, que o
login não tem). Reinstalar troca o ambiente de onde o `serve` importa o código
([040](040-instalacao-pelo-registro-do-uv.md)), então toda reinstalação reinicia o serviço.
Subir no boot sem login exigiria root (no Windows, senha guardada) e fica fora. No Windows a tarefa
tem o logon e um gatilho repetido a cada minuto, sem nova instância: o "reiniciar em falha" do
Agendador só age quando a tarefa não consegue iniciar, e o repetido religa um `serve` que caiu.
Sem limite de tempo (o padrão mataria o `serve` em 72 h) e sem condição de bateria. O `serve`
roda por um executável sem console e grava o próprio log, truncado a cada subida; ao subir, apaga
a tarefa manual `monitor-versoes-inscricoes` que o README antigo mandava criar, para não disparar
em dobro. A reinstalação no Windows é da [043](043-reinstalacao-no-windows-por-ajudante.md).

**Plugin do repo do motor fica na tag do motor.** Um plugin cuja origem é o próprio repo do
motor (git, mesma URL, subdiretório `plugins/`) tem de ser da mesma versão dele: versões
diferentes quebrariam a interface entre os dois, e por isso quem o move é o motor.

**Pasta local é exceção à fixação da [040](040-instalacao-pelo-registro-do-uv.md).** Não há
tag nem commit para fixar, e toda reinstalação reconstrói o ambiente a partir da pasta, que
precisa continuar no lugar. O instalador editável continua recusado.
