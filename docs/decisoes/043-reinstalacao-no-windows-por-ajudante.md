# Reinstalação no Windows por ajudante

- **Status:** substituída por [045](045-daemon-processo-e-login-separados.md) no ponto "o
  serviço sobe de novo ao fim" (sobe só se estava ativado); vale nos demais pontos
- **Data:** 2026-11-16
- **Depende de:** [040](040-instalacao-pelo-registro-do-uv.md),
  [042](042-instalador-e-daemon-no-login.md)

A [040](040-instalacao-pelo-registro-do-uv.md) afirma que uma reinstalação que falha preserva a
instalação anterior. No Windows isso é falso, e a conferência num runner `windows-latest` mostrou
por quê: o `uv tool install --reinstall` com qualquer processo do ambiente da ferramenta vivo (o
`serve`, ou o próprio comando do motor que chamou o `uv`) falhou com `failed to remove directory
…\Scripts: Access is denied (os error 5)` e deixou o ambiente pela metade. Depois, todo comando
dava `ModuleNotFoundError: No module named 'motor'`. Sem nenhum processo do ambiente vivo, a mesma
reinstalação funcionou.

**No Windows, o `uv` é chamado por um ajudante destacado, fora do ambiente.** Os comandos que
reinstalam (`plugin instalar|remover|atualizar`, `atualizar-motor` e o `configurar` ao instalar
um plugin) conferem tudo como no Linux, montam a mesma linha do `uv` e entregam o trabalho a um
script PowerShell que roda fora do ambiente. O comando sai com 0; o resultado é o que o ajudante
mostra no console. Chamar o `uv` de dentro não funciona: o próprio processo trava a troca.

**A espera tem prazo.** O ajudante espera os processos que o chamaram terminarem, encerra o
`serve` do serviço e espera não restar processo do ambiente, tudo dentro de um prazo único de
60 s. Se algum sobrar (uma TUI aberta, um `serve` manual), ele não toca no ambiente: lista os
processos e pede para fechá-los e rodar o comando de novo. Sem prazo, um processo esquecido
travaria o ajudante para sempre. O serviço sobe de novo ao fim, inclusive quando o `uv` falhou ou
o prazo estourou. Encerrar só não basta: o gatilho de 1 minuto da tarefa subiria o `serve` no meio
do `uv`; por isso a tarefa fica desativada da parada até a volta.

**O `pos-reinstalar` roda no ambiente novo.** O resumo do que mudou depende do código novo, e o
processo antigo já saiu. O ajudante chama o `pos-reinstalar` do ambiente reinstalado, só quando o
`uv` teve sucesso.

**A inscrição em andamento é conferida antes, no comando.** Um filho do `serve` rodando uma
inscrição também trava a troca. A recusa vem antes de entregar ao ajudante, sem encerrar o
`serve` nem chamar o `uv`.

**O `configurar` termina sem gravar a fonte.** A fonte do plugin recém-instalado só existe num
processo novo; por isso, depois de entregar a instalação ao ajudante, o `configurar` termina e
pede para ser rodado de novo, quando a fonte já aparece como instalada.

**O `install.ps1` chama o `uv` direto.** Ele já roda fora do ambiente, como o `install.sh`; só
encerra o `serve` antes e o sobe depois.

Linux e macOS não mudam: lá a reinstalação segue a [040](040-instalacao-pelo-registro-do-uv.md).
