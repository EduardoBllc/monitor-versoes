# Teste da config em subprocesso

- **Status:** aceita
- **Data:** 2026-11-13
- **Depende de:** [031](031-ambiente-na-config-central.md),
  [033](033-config-editavel-pelas-interfaces.md), [036](036-fonte-de-pr-plugavel.md)

A web testa a fonte de PR, a fonte de tarefas e o caminho de um repo antes de salvar, com
a config como ficaria se o formulário fosse salvo. O teste é a mesma checagem do
`monitor-versoes diagnostico` para aquela peça, e passa pela mesma validação do salvar:
o que o salvar recusaria, o teste recusa com o mesmo erro.

Os plugins leem credencial do `os.environ` ([036](036-fonte-de-pr-plugavel.md)), e o
`[ambiente]` da [031](031-ambiente-na-config-central.md) chega a eles aplicado no processo.
O daemon é multi-thread. Aplicar o `[ambiente]` do rascunho no próprio daemon, mesmo que
por um instante, deixaria uma credencial digitada e não salva visível para uma verificação
concorrente, que a usaria como se estivesse salva. Por isso o teste roda num subprocesso
(`python -P -m motor.teste_config`) com o ambiente base do daemon (shell e `.env`, sem o
`[ambiente]` aplicado) e o `XDG_CONFIG_HOME` apontado para um diretório temporário com o
rascunho. O subprocesso aplica o `[ambiente]` do rascunho só para si e devolve o resultado
em JSON. O `-P` tira o diretório corrente do `sys.path`: um módulo homônimo de um da
biblioteca padrão, largado onde o daemon foi iniciado, não roda com o segredo no ambiente.

O diretório temporário é privado (0700) e some ao fim do teste, também em timeout. O
`stderr` do subprocesso é descartado, porque um traceback de plugin pode carregar o segredo
digitado. Um plugin que não responde é cortado em 30 s e vira falha com "tempo esgotado".
O detalhe e a correção sugerida citam o `config.toml` real, que é onde o operador vai
corrigir, e nunca o arquivo temporário.
