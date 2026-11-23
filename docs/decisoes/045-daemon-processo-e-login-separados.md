# Daemon: processo e login separados

- **Status:** aceita
- **Data:** 2026-11-23
- **Depende de:** [021](021-motor-nao-interativo.md), [042](042-instalador-e-daemon-no-login.md),
  [043](043-reinstalacao-no-windows-por-ajudante.md)

A [042](042-instalador-e-daemon-no-login.md) amarrou duas coisas numa peça só: o serviço de
login era, ao mesmo tempo, o jeito de manter o `serve` de pé e o de subi-lo ao entrar. Não havia
como deixar o daemon rodando em segundo plano sem que ele também subisse no próximo login, nem
como pará-lo sem desligar o login; e a reinstalação religava o serviço sempre que ele existia,
mesmo parado de propósito.

**Duas peças por sistema: o processo e o login.** O processo é o que mantém o daemon rodando
agora; o login só decide se ele sobe ao entrar. O comando `daemon` dirige as duas (`iniciar`,
`parar`, `reiniciar`, `estado`), e `daemon rodar` roda em primeiro plano, fora delas.

- **Linux:** uma unit de usuário só, `monitor-versoes-serve.service`. `start`/`stop` são o
  processo; `enable`/`disable` são o login. O systemd já separa as duas coisas.
- **macOS:** o processo é o plist `monitor-versoes.daemon`, com `KeepAlive`, gravado na pasta de
  dados e não no `LaunchAgents`, para o launchd não carregá-lo sozinho no login. O login é o
  plist `monitor-versoes.login` no `LaunchAgents`, que no login só roda
  `daemon iniciar --sem-perguntas`.
- **Windows:** o processo é a tarefa `monitor-versoes-daemon`, com o gatilho de 1 minuto da
  [042](042-instalador-e-daemon-no-login.md); ativada quer dizer "deve rodar", desativada é um
  `daemon parar`. O login é a tarefa `monitor-versoes-login`, que existe sempre que o daemon já
  foi configurado e roda `daemon iniciar --sem-perguntas` (login ligado) ou
  `daemon parar --sem-perguntas` (login desligado).

**No Windows, o login é a ação da tarefa de logon, não uma marca de boot.** O gatilho de 1 minuto
religaria no logon seguinte um daemon iniciado sem login, porque a tarefa continua ativada. A
alternativa era gravar o horário do boot ao iniciar e ignorar a tarefa num boot novo, mas a
Inicialização Rápida do Windows hiberna o kernel no desligamento: o uptime não zera e o "boot
novo" não aparece. Uma tarefa de logon que sempre existe e cuja ação é `iniciar` ou `parar`
resolve no próprio logon, sem depender do relógio.

**A reinstalação respeita o estado do processo.** No Linux e no macOS, o motor reinicia só o
daemon que está rodando e, parado, apenas regrava a peça com o executável novo. No Windows, o
ajudante da [043](043-reinstalacao-no-windows-por-ajudante.md) e o `install.ps1` guardam se a
tarefa do processo estava ativada e só a religam nesse caso. O `install.sh` usa `try-restart` no
systemd e, no macOS, só reinicia o rótulo que o launchd tem carregado.

**As peças antigas migram sozinhas.** Todo `daemon` (menos o `rodar`), a reinstalação e o
`pos-reinstalar` do Windows trocam o plist `monitor-versoes.serve` e a tarefa
`monitor-versoes-serve` pelas peças novas, com o login ligado, porque era o que a peça antiga
fazia. No Windows quem migra é o `pos-reinstalar`: na primeira atualização ainda roda o ajudante
antigo, que só conhece a tarefa antiga.

**O `serve --sem-navegador` vira uma ponte.** O comando `serve` sai, mas essa linha exata é o que
as peças instaladas por versões antigas chamam. Ela continua subindo o daemon até a migração
trocar a peça; no Linux, a própria ponte regrava a unit. Nos outros sistemas ela não migra, porque
derrubaria o serviço que a chamou.

**As perguntas ficam no front-end da CLI.** "Iniciar também no login?", "Salvar essa escolha?" e
"Parar de iniciar no login também?" são do `daemon` na CLI, só com terminal e sem
`--sem-perguntas`; `servico` só executa. A [021](021-motor-nao-interativo.md) segue valendo. A
escolha "nunca iniciar no login" fica salva em `[daemon] nunca_iniciar_login` e só o `configurar`
a desfaz, ao responder Sim; a porta passada a `iniciar` ou `reiniciar` fica salva em
`[daemon] porta`.
