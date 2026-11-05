# Fonte de tarefas plugável

- **Status:** aceita
- **Data:** 2026-11-05
- **Depende de:** [008](008-autenticacao-tickio.md), [018](018-portas-e-adaptadores.md),
  [024](024-config-por-projeto.md), [025](025-reaproveitamento-da-verificacao.md),
  [026](026-esquema-e-atribuicao-plugaveis.md)

A [026](026-esquema-e-atribuicao-plugaveis.md) tirou do núcleo as regras de versão e de
atribuição, mas a fonte de tarefas continuava escolhida por um valor fixo da CLI, com o
adapter do rastreador da VendaBem embutido. Para publicar a ferramenta, o núcleo não pode
depender de rastreador nenhum. O esquema `vendabem` e o adapter do rastreador saíram para
um pacote separado, que se registra por entry point; a [008](008-autenticacao-tickio.md) e
a [009](009-inferencia-de-base.md) seguem valendo para ele.

## A fonte é plugin, sem padrão

- **Escolha:** `[tarefas] fonte`, com as regras do carregador da
  [024](024-config-por-projeto.md): nome sem `:` é entry point do grupo
  `monitor_versoes.tarefas`; `modulo:Classe` só no `config.toml` central; nome não
  instalado falha listando os instalados.
- **Sem padrão no núcleo.** Diferente do esquema (`semver`) e da atribuição (`exata`), não
  existe fonte neutra que sirva a qualquer fluxo. Sem `fonte`, a primeira busca falha
  pedindo a chave ou a lista manual, que continua no núcleo (`--task-source manual`).
- **`[tarefas]` segue opaco**, salvo `fonte`: as demais chaves chegam ao plugin como estão.

## Contrato do construtor

O plugin é instanciado só com argumentos nomeados: `tarefas` (o `[tarefas]` mesclado, com
`fonte`) e `arquivos` (os arquivos de config lidos, para o erro citar onde corrigir). O
construtor não valida, não lê credencial e não faz I/O: quem cobra é a primeira busca, pelo
mesmo motivo da [008](008-autenticacao-tickio.md). Exceção do construtor que não é
`MotorError` vira erro de entrada citando a fonte, para não sair como bug com traceback.

Dois atributos são opcionais e lidos só se existirem: `referencia`, o padrão proposto, e
`verificar_credenciais()`, usado pelo `motor diagnostico`. A suíte de conformidade não
cobre a fonte: a porta é um método só.

## Montar não é usar

A montagem entrega uma fonte preguiçosa, que carrega o plugin na primeira busca ou na
primeira vez que alguém precisa da referência. A referência e a identidade das entradas do
carimbo ([025](025-reaproveitamento-da-verificacao.md)) também viram cálculos sob demanda,
porque dependem da proposta do plugin. Assim, plugin ausente ou `fonte` inválida não
impedem `atualizar --abort`, e `reconstruir-estado` roda sem fonte quando há
`[referencia] padrao`. O carimbo continua invalidado quando muda a fonte, o `[tarefas]` ou
a referência efetiva.

O diagnóstico não tem repo: avalia a fonte só com o `config.toml` central.

## As colunas do rastreador caem

Desde a [024](024-config-por-projeto.md), `sistema` e `piso` vêm da config e as colunas
`repo.tickio_sistema_id` e `repo.piso_versao` eram ignoradas. Elas caem: a config é a fonte
única, e `motor repo adicionar` pede só o nome. O downgrade recria as colunas com valores
fixos, sem os originais, que estão nos arquivos de config.

A migração não confere se os valores foram levados para a config, porque não enxerga os
repos-alvo. Quem vem de um banco antigo roda antes, com o checkout antigo intacto, o script
autocontido `scripts/migrar_banco_para_config.py`, que lê o banco e escreve os
`.monitor-versoes.toml`; a ordem dos passos está na ajuda dele.
