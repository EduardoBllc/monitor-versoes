# Quando as três fontes divergem

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [002](002-oraculo-tres-fontes.md), [004](004-estado-descartavel.md)

| Caso                                  | Sinal                     | Ação                                                          |
| ------------------------------------- | ------------------------- | ------------------------------------------------------------- |
| Task nova marcada p/ versão           | no alvo, fora do estado   | aplica + registra                                             |
| Task desmarcada do alvo               | no estado, fora do alvo   | **avisa**; remoção é decisão humana (reverter é destrutivo)   |
| Commit do estado sumiu                | no estado, fora do git    | **alerta forte** — estado corrompido/rebase; não auto-corrige |
| Pick manual sem o tool                | no git, fora do estado    | **avisa**; oferece regularizar o estado                       |
| Grep pegou commit que não deve entrar | candidato                 | vira exclusão, com motivo                                     |

**"Commit do estado sumiu" só vale para atribuição já `aplicado`.** Uma `pendente` — tarefa
marcada, commit ainda não cherry-pickado — está ausente do git por definição normal. Contá-la
como sumida faria toda versão recém-criada reportar estado divergente entre um `verificar` e o
`atualizar` seguinte, sem nada de errado ter acontecido: veredito certo, diagnóstico errado.

**O alerta persiste até o commit voltar a estar presente no alvo.** A regravação do estado não
rebaixa para `pendente` a atribuição com commit sumido: isso seria auto-corrigir, e o sinal
duraria uma execução só. Quando o commit volta (o `atualizar` o reaplica, por exemplo), o
alerta some sozinho, sem comando de reconhecimento.

Aplicar o que falta: [013](013-conflito-e-checkpoint.md),
[014](014-ordem-de-aplicacao-pelo-grafo.md), [015](015-estado-regravado-ao-final-do-lote.md).
