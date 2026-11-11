# Lock por repo entre processos

- **Status:** aceita
- **Data:** 2026-11-11
- **Depende de:** [019](019-montagem-no-front-end.md), [028](028-inscricoes-fora-do-estado.md),
  [030](030-front-end-web-spa-com-dist-versionado.md)

CLI, TUI, daemon web e a execução de inscrição são processos diferentes que operam o mesmo
clone. Dois `atualizar` simultâneos na mesma versão disputavam a worktree e o checkpoint de
cherry-pick, e um `verificar` em paralelo podia recolher a worktree que o outro usava. A
[028](028-inscricoes-fora-do-estado.md) contava com o `index.lock` do git para uma das duas
falhar, mas ele só protege um comando git por vez, não a operação. O lock de "uma operação por
repo" do daemon ([030](030-front-end-web-spa-com-dist-versionado.md)) só valia dentro do
próprio processo.

- **Um lock por clone, não por versão.** O `fetch` e o GC de worktrees são do clone inteiro, e
  um lock por versão não os cobriria. O custo, aceito, é que duas versões do mesmo repo não
  andam em paralelo. Dois nomes de repo com o mesmo `caminho` compartilham o lock.
- **Entre processos, e o mesmo em todos os front-ends.** O daemon deixa de ter um lock
  próprio: dois mecanismos dariam duas respostas para "o repo está ocupado?". Cada front-end
  trava no seu ponto de entrada, como já monta as dependências
  ([019](019-montagem-no-front-end.md)); o engine não sabe do lock.
- **`flock` num arquivo fora do clone.** O lock é do descritor aberto e morre com o processo,
  inclusive por `kill -9` ou pelo tempo-limite da inscrição; o arquivo que sobra não trava
  nada, e não há o que o operador apagar. Fora do clone, ele não aparece no `git status` nem
  depende do layout do `.git`. O arquivo guarda o pid de quem segura, só para a mensagem. É um
  lock local: o estado pode ser um Postgres compartilhado, e escrita concorrente vinda de
  outra máquina continua como era.
- **Cobre o que toca a worktree, o checkpoint ou o GC, pela operação inteira.** São `criar`,
  `atualizar` (inclusive continuar e abortar), a prévia, o `verificar` sem `--auditar` e a
  execução de uma inscrição. Ficam de fora `consulta`, `verificar --auditar`,
  `reconstruir-estado` e a listagem de versões: no máximo fazem `fetch`, que o git já
  serializa nos refs, e uma colisão faz um deles falhar sem estado corrompido.
- **O segundo não espera.** Esperar deixaria um front-end parado sem dizer por quê, e uma
  inscrição empilhada atrás de um conflito à espera do operador. CLI, TUI e daemon recusam na
  hora com `RepoOcupado`, um erro do operador com o pid de quem segura; o daemon responde
  `409 ocupado`. A inscrição sai `PULADA`, sem notificação, e tenta de novo na próxima vez que
  vencer.
- **Prévia e `atualizar` confirmado são duas operações.** O lock é solto enquanto o operador
  decide: segurá-lo durante a confirmação travaria o repo pelo tempo que a pessoa levar. O
  `atualizar` confirmado pode então ser recusado, se outro processo entrou no meio.

Fica de fora a worktree criada à mão e o git rodado pelo operador fora do motor: o lock não os
vê.
