# Esquema de versão e política de atribuição plugáveis

- **Status:** aceita
- **Data:** 2026-11-05
- **Depende de:** [005](005-alvo-distribuicao-entre-versoes.md),
  [009](009-inferencia-de-base.md), [010](010-travas-publicada-e-liberada.md),
  [018](018-portas-e-adaptadores.md), [024](024-config-por-projeto.md)

O núcleo nasceu com o fluxo da VendaBem embutido: número `X.Y.Z`, base pela
[009](009-inferencia-de-base.md), branch com o número puro, principal `master`, liberada por
tag homônima e o alvo da [005](005-alvo-distribuicao-entre-versoes.md). Com a ferramenta
aberta a terceiros, cada uma dessas regras passa a ser escolha, e o núcleo fica com o que
não depende do fluxo: ponto de corte, oráculo, travas e congelamento.

## Esquema de versão

Porta (`EsquemaVersao`, em `motor/ports.py`) que diz o que é um número (validação), a ordem,
a ref-base de uma versão dadas as existentes e a principal, as próximas sugeridas e,
opcionalmente, o tipo (rótulo livre que o estado grava e a TUI mostra sem interpretar), os
nomes de branch e um critério de liberação.

- O **ponto de corte continua do núcleo**: `merge-base` entre a ref-base e a versão, ou o
  tip da ref-base no `criar` ([009](009-inferencia-de-base.md)). O esquema só escolhe a ref.
- Embutidos: `semver` (padrão; `X.Y.0` sai da principal, `X.Y.Z` da `X.Y.(Z-1)` se existir,
  senão da `X.Y.0`; sem tipo) e `vendabem` (a [009](009-inferencia-de-base.md), tipos
  fechada/ajustada/cliente, principal `master`).
- O tipo deixou de ser enum do domínio e check do banco: versão sem tipo é gravada sem tipo,
  e versão gravada antes mantém o tipo que tinha.
- **Conformidade:** `motor/conformidade.py` publica uma suíte pytest que um pacote de fora
  roda contra o seu esquema: ordem total e coerente com a validação, base que é versão
  existente ou a principal e, havendo critério de liberação, datas que não mudam quando só
  o relógio muda.

## Liberada e nomes de branch, em camadas

Três camadas, **config > esquema > padrão do núcleo**, com um só critério valendo por vez:

| O quê | Config | Esquema | Padrão |
| --- | --- | --- | --- |
| liberada | `[liberacao] tag` (template) | `liberacoes(git, versoes)` → `{versão: data}` | tag `{versao}` |
| branch da versão | `[branches] versao` | `branch_versao` | `{versao}` |
| principal | `[branches] principal` | `branch_principal` | `main` |

Todos os consumidores usam o mesmo critério (o `Catalogo`): trava de escrita e de
publicação ([010](010-travas-publicada-e-liberada.md)), congelamento
([011](011-congelamento-no-banco.md)), conjunto de abertas, auditoria e as liberadas que a
política consome. As proteções valem em qualquer camada:

- a data vem do repositório, nunca do relógio;
- `liberada_em` gravada nunca é reescrita, nem quando o critério muda e deixa de reconhecer
  a versão: gravada continua liberada;
- "aberta" é derivada pelo núcleo: tem branch da versão e não está liberada.

## Política de atribuição

Porta (`PoliticaAtribuicao`) que decide de quais versões vêm as tarefas do alvo de `V`. Recebe
do núcleo, já resolvidos, a ordem, as abertas, as liberadas com data, o corte de `V` e o piso;
não acessa git nem tracker.

- `exata` (padrão): só `V`, se não estiver abaixo do piso. Tarefa marcada em duas versões vale
  em cada uma e não é ambígua.
- `composta`: a regra da [005](005-alvo-distribuicao-entre-versoes.md), com a ambiguidade da
  [007](007-tarefa-em-duas-abertas.md).

A ambiguidade, a varredura única de commits e "tarefa sem commit aparece" seguem no núcleo.

## Resolução tardia

Esquema e política são plugins ([024](024-config-por-projeto.md): nome sem `:` é entry point
instalado em `monitor_versoes.esquemas` / `monitor_versoes.atribuicoes`; `modulo:Classe` só
no arquivo central) e são resolvidos onde são usados, não na montagem. O `piso` é validado
pelo esquema em uso. Por isso `atualizar --abort` funciona com plugin inexistente ou piso
inválido: usa só os nomes de branch da config e do padrão e limpa a worktree atual.
