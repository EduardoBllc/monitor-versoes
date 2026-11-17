# Plugins por host

- **Status:** aceita
- **Data:** 2026-11-17
- **Depende de:** [036](036-fonte-de-pr-plugavel.md)

A [036](036-fonte-de-pr-plugavel.md) fez do host de PR um plugin, mas deixou o Bitbucket
no pacote do motor. Com isso o núcleo continuava conhecendo um host, e cada host novo
abria a dúvida de onde morar: um pacote para as tarefas do GitHub e outro para as PRs do
mesmo GitHub repetiriam URL base, credencial e paginação.

**O núcleo não conhece host.** O Bitbucket sai do motor e vira o pacote
[`plugins/bitbucket`](../../plugins/bitbucket/README.md), instalado e atualizado como os
outros plugins do repo.

**Os plugins se organizam por host, não por papel.** Cada pacote em `plugins/` é um host e
registra os grupos de entry point que atende (`monitor_versoes.tarefas`,
`monitor_versoes.prs`). Instalar não liga nada: a `fonte` de cada seção escolhe a parte
usada, então quem usa um host só para tarefas ou só para PRs instala o mesmo pacote. O
código do host fica compartilhado entre as partes. A alternativa, um pacote por papel,
duplicaria esse código e obrigaria a instalar dois pacotes para um host.

**Sem migração automática.** Quem usava o Bitbucket instala o plugin; até lá,
`[prs] fonte = "bitbucket"` cai no erro de fonte não instalada na primeira busca, que,
como em toda fonte ([036](036-fonte-de-pr-plugavel.md), "Montar não é usar"), não impede
`atualizar --abort` nem `reconstruir-estado`. O nome da fonte não muda, então a marca de
varredura gravada continua valendo e o histórico não é baixado de novo. Instalar sozinho
no `atualizar` ou nos instaladores foi descartado: o aviso fica na nota de release, com o
comando.
