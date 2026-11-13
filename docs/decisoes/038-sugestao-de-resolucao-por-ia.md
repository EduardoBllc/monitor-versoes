# Sugestão de resolução por IA

- **Status:** aceita
- **Data:** 2026-11-13
- **Depende de:** [013](013-conflito-e-checkpoint.md), [020](020-contrato-de-erro-por-tipo.md),
  [027](027-fonte-de-tarefas-plugavel.md), [031](031-ambiente-na-config-central.md),
  [032](032-lock-por-repo-entre-processos.md)

A web pode pedir a um modelo uma proposta para os blocos de conflito ainda abertos. Isso não
contradiz a [013](013-conflito-e-checkpoint.md): a IA só propõe, com justificativa por
bloco; o operador aplica bloco a bloco (como "Ambos" ou "Usar base") ou descarta, e só o
**Marcar resolvido** grava, com as recusas de sempre (marcador restante, disco alterado fora
da web). Pedir, aplicar e descartar não tocam a worktree nem o índice, então o pedido não
toma o lock do clone ([032](032-lock-por-repo-entre-processos.md)): esperar o provedor não
trava outras operações do repo.

## O que sai da máquina

Sai da máquina só o necessário para propor os blocos pedidos — os lados desses blocos e o
contexto do commit que os trouxe, nunca o resto do repo; o que vai e o que não vai está na
tabela do [README](../../README.md#sugestão-de-resolução-por-ia).

## Provedor plugável, sem padrão

O provedor é plugin do grupo `monitor_versoes.sugestao`, escolhido por `[sugestao] provedor`,
com o carregador e o contrato de construtor da [027](027-fonte-de-tarefas-plugavel.md).
Sem `[sugestao] provedor` não há sugestão, e `[sugestao]` vale só no topo do central, como o `[ambiente]`:
a sugestão é da instalação, não do repo. Montar não é usar: plugin ausente ou credencial
faltando não impedem o daemon de subir; o plugin ausente esconde os gatilhos, e a credencial
faltando aparece como erro ao pedir. Falha do provedor vira erro da API pela tabela da
[020](020-contrato-de-erro-por-tipo.md).

## O provedor `anthropic`

Usa o SDK oficial, como extra opcional `anthropic`, sem dependência obrigatória, com import
preguiçoso: sem o extra, o provedor não carrega, a sugestão some da tela e o diagnóstico
pede `monitor-versoes[anthropic]`. A chave vem só de `ANTHROPIC_API_KEY` (o `[ambiente]`,
[031](031-ambiente-na-config-central.md)) e é passada explicitamente ao SDK, que sozinho
cairia em outras credenciais da máquina, como um perfil OAuth em disco. Recusa do modelo é
erro, sem fallback para outro modelo: trocar de modelo em silêncio mudaria o que sai da
máquina e o custo sem o operador saber.
