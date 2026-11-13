# Fonte de PR plugável

- **Status:** aceita
- **Data:** 2026-11-13
- **Depende de:** [024](024-config-por-projeto.md), [025](025-reaproveitamento-da-verificacao.md),
  [027](027-fonte-de-tarefas-plugavel.md)

A [027](027-fonte-de-tarefas-plugavel.md) tirou do núcleo o rastreador, mas a fonte de
commits continuava presa a um host: a montagem ligava a busca por PR do Bitbucket sempre
que havia token, e o núcleo conhecia o Bitbucket na montagem, na CLI, no `[ambiente]`, na
modal de configuração e no diagnóstico. Para publicar a ferramenta, o host de PR vira
plugin, e o Bitbucket passa a ser só um plugin que vem no pacote.

## A fonte é plugin, sem padrão

- **Escolha:** `[prs] fonte`, com as regras do carregador da
  [024](024-config-por-projeto.md): nome sem `:` é entry point do grupo
  `monitor_versoes.prs`; `modulo:Classe` só no `config.toml` central; nome não instalado
  falha listando os instalados.
- **Sem padrão.** Sem `fonte`, os commits saem só do grep na branch principal, que fica no
  núcleo como fallback sempre disponível e roda depois da PR na cadeia. O token não decide
  mais nada: quem usava `BITBUCKET_TOKEN` sozinho passa a declarar
  `[prs] fonte = "bitbucket"`. Ligar o Bitbucket pelo token manteria na montagem
  justamente o `if` por host que esta decisão tira.
- **`[prs]` segue opaco**, salvo `fonte`, e se mescla central + repo chave a chave, como o
  `[tarefas]`.

## A porta é fina

O plugin implementa `HostPr`: "PRs mergeadas desde X" e "commits da PR, sem merge
commits". Varredura incremental, índice, casamento com a referência, cache `PR -> commits`
e filtro pela principal ficam no núcleo, no `PrCommitSource`.

A alternativa era o plugin ser um `CommitSource` inteiro, recebendo git, estado e
referência. Mudaria menos código agora, mas cada host repetiria o pipeline, perderia as
correções já feitas nele (caixa do título, fronteira do ID, marca no início da varredura) e
o contrato exporia ao plugin portas internas. Um plugin genérico por URL e template de
JSON também foi descartado: autenticação, paginação e filtro por data diferem demais entre
hosts.

A porta tem suíte de conformidade, real e fake, como as demais: diferente da fonte de
tarefas, ela tem dois métodos e alimenta o estado.

## Contrato do construtor

O mesmo da [027](027-fonte-de-tarefas-plugavel.md), com outros argumentos nomeados: `prs`
(o `[prs]` mesclado, com `fonte`), `arquivos` (para o erro citar onde corrigir) e
`remote_url` (uma função que devolve a URL do `origin`; o host deriva dela a identidade do
repo). O construtor não valida, não lê credencial e não faz I/O; exceção dele que não é
`MotorError` vira erro de entrada citando a fonte. Credencial é assunto do plugin: ele a lê
do ambiente na primeira chamada e declara as chaves em `campos_config`. O
`verificar_credenciais()` é opcional e lido só pelo `monitor-versoes diagnostico`, que avalia a fonte
com o `config.toml` central.

## Montar não é usar

A montagem entrega um host preguiçoso, carregado na primeira busca. Plugin ausente,
`fonte` inválida ou credencial faltando não impedem `atualizar --abort` nem
`reconstruir-estado`. O carimbo da [025](025-reaproveitamento-da-verificacao.md) inclui a
`fonte` e o `[prs]` mesclado: trocar o host invalida a verificação.

## O estado de PR é por host

A marca da varredura guarda o host que a gravou. A marca de outro host vale como ausente,
e gravar a varredura de um host diferente apaga o índice e o cache `PR -> commits` do repo
na mesma transação que grava o índice novo e a marca. Sem isso, a marca antiga faria o
host novo pular o histórico, e um `pr_id` igual traria commits do host antigo. As marcas
anteriores a esta decisão ficam com `bitbucket`, o único host que existia, para o operador
atual não baixar o histórico de novo.

Limite aceito: o mesmo plugin apontando para outro repo do host (remote trocado) não é
detectado.
