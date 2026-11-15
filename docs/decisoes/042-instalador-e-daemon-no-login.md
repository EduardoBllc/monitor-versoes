# Instalador, configurar e daemon no login

- **Status:** aceita
- **Data:** 2026-11-15
- **Depende de:** [039](039-versionamento-por-tag.md), [040](040-instalacao-pelo-registro-do-uv.md),
  [041](041-disparo-das-inscricoes-pelo-daemon.md)

Instalar exigia `uv`, `uv tool install` com a tag certa, plugins à mão e subir o `serve`
sempre que a máquina ligava. Um script de uma linha e um assistente cobrem isso.

**O script é fino; o assistente é Python.** O `install.sh` só garante git e `uv`, instala a
última release e chama o motor (`configurar`, `atualizar-motor`, `desinstalar`). Perguntas,
validação e escrita da config ficam no `motor.assistente`, com o `questionary`: as regras
ficam num só lugar, testável, em vez de repartidas entre `sh` e Python. O script só repete o
que precisa antes de o motor existir.

**O daemon sobe no login, sem root.** Serviço de usuário no systemd e LaunchAgent no macOS,
rodando `serve --sem-navegador` pelo executável do ambiente do `uv` (nunca pelo `PATH`, que o
login não tem). Reinstalar troca o ambiente de onde o `serve` importa o código
([040](040-instalacao-pelo-registro-do-uv.md)), então toda reinstalação reinicia o serviço.
Subir no boot sem login exigiria root e fica fora; no Windows não há serviço.

**Plugin do repo do motor fica na tag do motor.** Um plugin cuja origem é o próprio repo do
motor (git, mesma URL, subdiretório `plugins/`) tem de ser da mesma versão dele: versões
diferentes quebrariam a interface entre os dois, e por isso quem o move é o motor.

**Pasta local é exceção à fixação da [040](040-instalacao-pelo-registro-do-uv.md).** Não há
tag nem commit para fixar, e toda reinstalação reconstrói o ambiente a partir da pasta, que
precisa continuar no lugar. O instalador editável continua recusado.
