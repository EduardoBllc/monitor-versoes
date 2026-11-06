# Config por projeto, em duas camadas

- **Status:** substituída por [029](029-repos-na-config-central.md) nas camadas, no import
  path e na identidade do repo; vale nos demais pontos
- **Data:** 2026-11-03
- **Depende de:** [016](016-multi-projeto-premissas.md), [019](019-montagem-no-front-end.md),
  [023](023-onde-nao-se-abstrai.md)

A ferramenta vai virar open source. A [016](016-multi-projeto-premissas.md) e a
[023](023-onde-nao-se-abstrai.md) diziam "sem config por projeto" porque só a VendaBem a
usava; com terceiros instalando o monitor, o piso de versão (`13.0.0` era da VendaBem) e o
sistema do tracker não cabem mais numa coluna com padrão embutido. Esta decisão revoga as
duas **nesse ponto**; nos demais elas seguem valendo.

- **Duas camadas, mescladas chave a chave, o repo vencendo:**
  `~/.config/monitor-versoes/config.toml` (padrão do operador; respeita `XDG_CONFIG_HOME`) e
  `.monitor-versoes.toml` na raiz do repo-alvo. Credenciais continuam no `.env`.
- **Chaves lidas:** `[versao] piso`, `[tarefas] sistema`, `[referencia] padrao` e as do
  versionamento ([026](026-esquema-e-atribuicao-plugaveis.md)), abaixo. O resto é
  ignorado. `[tarefas]` é opaco ao núcleo: quem lê as chaves é o adapter do tracker.

  | Chave | O que é | Sem config |
  | --- | --- | --- |
  | `[versao] esquema` | esquema de versão (plugin) | `semver` |
  | `[versao] atribuicao` | política de atribuição (plugin) | `exata` |
  | `[liberacao] tag` | template, com um `{versao}`, da tag que libera | critério do esquema, senão tag `{versao}` |
  | `[branches] versao` | template, com um `{versao}`, da branch da versão | do esquema, senão `{versao}` |
  | `[branches] principal` | branch principal | do esquema, senão `main` |
- **O piso é validado pelo esquema em uso**, quando ele é resolvido, não na leitura.
- **Piso sem padrão.** Sem `piso` em nenhuma camada, nenhuma versão é cortada.
- **`sistema` é cobrado pelo adapter Tickio, na primeira busca**, como as credenciais
  ([008](008-autenticacao-tickio.md)). A montagem ([019](019-montagem-no-front-end.md)) só
  carrega a config e nunca falha por isso, para não quebrar `atualizar --abort` nem
  `reconstruir-estado`.
- **`[referencia] padrao` sobrescreve o padrão proposto pelo adapter do tracker.** É um
  template com um `{id}` (Tickio: `ch{id}`); a precedência é adapter < global < repo. A falta
  em todas as origens é cobrada no uso (busca de commits, `reconstruir-estado`, `verificar`,
  impressão de culpados), não na montagem; valor inválido falha na leitura, como o `piso`. O
  alfabeto do id vem do adapter (default letras, dígitos, `_` e `-`) e a config não o muda.
- **Import path só no arquivo central.** O carregador de plugins aceita um nome sem `:`
  (entry point instalado) ou `modulo:Classe` (import direto). O `.monitor-versoes.toml` só
  escolhe entre entry points já instalados: rodar o monitor num repo não pode executar código
  escolhido por quem controla aquele repo.
- **Identidade do repo não muda:** basename mais aliases, no banco. As colunas
  `tickio_sistema_id` e `piso_versao` ficam, ignoradas, até a #117.
