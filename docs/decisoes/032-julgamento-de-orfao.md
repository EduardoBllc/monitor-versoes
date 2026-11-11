# Julgamento de órfão

- **Status:** aceita
- **Data:** 2026-11-11
- **Depende de:** [002](002-oraculo-tres-fontes.md), [004](004-estado-descartavel.md),
  [005](005-alvo-distribuicao-entre-versoes.md), [021](021-motor-nao-interativo.md)

Órfão é o commit de `base..branch` cuja mensagem de origem não tem referência de tarefa. O
`reconstruir-estado` o devolve em `PENDING_JUDGMENT` e para, porque quem pergunta ao humano
é o front-end ([021](021-motor-nao-interativo.md)). Faltava onde gravar a resposta: uma
atribuição manual gravada nas atribuições da versão seria apagada na reconstrução seguinte,
que as regrava. O julgamento ganhou um registro próprio, e o motor o aplica onde a
atribuição é recalculada.

- **O registro é próprio, separado da `exclusao`.** A exclusão diz "o grep pegou, mas não
  entra" e filtra commits que a fonte de commits já pôs numa tarefa. O órfão é o contrário:
  um commit que já está na branch e que nenhuma tarefa reclama. "Pertence a chX" não cabe na
  exclusão, e "não pertence a nenhum" nela mudaria o que a exclusão significa para o
  `verificar`. É julgamento humano, como a exclusão e o "sem entrega"
  ([004](004-estado-descartavel.md)): o `migrar-estado` o copia e a impressão do carimbo
  o inclui.
- **Vale só na versão em que foi feito.** O mesmo commit pode ser órfão em duas versões, e
  a resposta numa não responde a outra: o operador julga o que viu naquela branch.
- **No `verificar`, ele é uma fonte de commits das tarefas do alvo, ao lado da fonte de
  commits** ([002](002-oraculo-tres-fontes.md)). Sem isso, a atribuição que o
  `reconstruir-estado` dá ao órfão sumiria na verificação seguinte, que regrava as
  atribuições a partir da fonte de commits, e ela não acha órfão por definição. O órfão
  julgado conta na presença, nos faltantes e nas tarefas sem commits como qualquer commit de
  chX. Ele soma e não tira: se a fonte de commits já pôs o hash noutro chamado, ele fica nos
  dois.
- **Não põe tarefa no alvo.** O alvo vem da fonte de tarefas
  ([005](005-alvo-distribuicao-entre-versoes.md)). Um julgamento "pertence a chX" com chX
  fora do alvo da versão não tem efeito no `verificar`: dizer de quem é um commit não é dizer
  que a tarefa entra na versão.
- **Só vale para um órfão atual.** Um julgamento de hash que saiu da branch, ou que ganhou
  referência, fica no banco mas não aparece na lista nem é aplicado. Aplicado, ele viraria um
  faltante de chX que ninguém enxerga entre os órfãos.
- **A exclusão vence.** Uma exclusão do mesmo hash para a versão tira o commit de chX, como
  tira de qualquer tarefa.
- **Não passa pelo congelamento** ([011](011-congelamento-no-banco.md)). O julgamento não é
  atribuição: gravá-lo numa versão liberada não muda o snapshot, que só o `verificar
  --auditar` ou a recuperação do `reconstruir-estado` recalculam. Recusá-lo tornaria a
  recuperação de uma versão liberada impossível de concluir.
- **Varre só quando há o que aplicar.** O `verificar` só procura órfãos quando a versão tem
  julgamento "pertence a chX" com chX no alvo. Assim uma versão sem julgamento não paga a
  varredura nem passa a exigir o padrão de referência.
