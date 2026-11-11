# Config editável pelas interfaces

- **Status:** aceita
- **Data:** 2026-11-10
- **Depende de:** [020](020-contrato-de-erro-por-tipo.md),
  [026](026-esquema-e-atribuicao-plugaveis.md), [027](027-fonte-de-tarefas-plugavel.md),
  [029](029-repos-na-config-central.md), [031](031-ambiente-na-config-central.md),
  [032](032-lock-por-repo-entre-processos.md)

Com repos e ambiente no `config.toml` central, editar o arquivo à mão era a única forma de
configurar a instalação. A TUI e a web passam a editá-lo, sem que o motor aprenda as chaves
de cada plugin.

- **Os plugins declaram o que se edita.** Uma classe de plugin pode ter o atributo opcional
  `campos_config`, uma tupla de `Campo` (escopo, tabela, chave, tipo, rótulo, segredo); no
  `[ambiente]` a tabela é sempre `TABELA_AMBIENTE`, para o segredo ser reconhecido. O
  motor varre os grupos `monitor_versoes.tarefas`, `.esquemas` e `.atribuicoes` e também o
  `modulo:Classe` em uso na config. Plugin sem o atributo, ou que falha ao carregar, não
  aparece: a tela não pode quebrar por causa de código de terceiro. Chave presente no arquivo
  e fora do catálogo continua visível, só que como texto livre.
- **A escrita preserva o arquivo.** Gravar com `tomllib` e um dump perderia comentários e
  ordem, e o `config.toml` é do usuário. A escrita usa `tomlkit`, é atômica, mantém o modo do
  arquivo (`0o600` se novo) e segue um symlink até o destino. Antes de gravar, valida com os
  mesmos leitores do motor, então a UI não grava o que o motor recusaria ao ler, e recusa se o
  arquivo mudou desde a leitura, para não sobrescrever edição feita por fora.
- **O `[ambiente]` vale sem reiniciar.** Reaplicar sobre o ambiente já mexido acumularia
  valores antigos. A base é o shell mais `.env`, capturada na primeira aplicação; cada
  aplicação parte dela, e uma chave removida do `[ambiente]` volta ao valor da base. O
  `XDG_CONFIG_HOME` nunca é aplicado, como na [031](031-ambiente-na-config-central.md).
- **Os erros seguem o contrato por tipo** ([020](020-contrato-de-erro-por-tipo.md)): entrada
  inválida é 422, recusa de invariante e arquivo alterado são 409, e operação em andamento é
  409 `ocupado`.
- **Salvar não consulta o lock do clone** ([032](032-lock-por-repo-entre-processos.md)).
  O lock protege a operação num clone, não o `config.toml`; a recusa `ocupado` ao salvar só
  enxerga execuções do próprio processo. Entre a TUI e o daemon, a única proteção é a checagem
  de "arquivo mudou", que deixa uma janela entre ler e gravar; para um operador por máquina o
  risco é aceito.
