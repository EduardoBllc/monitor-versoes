# O corte por projeto acontece na fonte

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [016](016-multi-projeto-premissas.md)

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
