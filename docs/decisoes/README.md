# Decisões

Uma decisão por arquivo, `NNN-slug.md`, em prosa livre. Cada arquivo abre com o
status (`aceita` ou `substituída por NNN`) e a data, e linka as decisões de que
depende.

Aqui fica o porquê do sistema. Estrutura (schema, assinaturas, comandos) não está
aqui — essa o código responde melhor e sem apodrecer. Uso: [README.md](../../README.md).

## Ordem de leitura

Uma linha por decisão, na ordem em que a narrativa se encadeia.

1. [001](001-problema-completude-de-commits.md) — o problema: cherry-pick troca o hash; o escopo é completude de commits.
2. [002](002-oraculo-tres-fontes.md) — presença cruza Tickio, estado e git; verde só quando os três concordam.
3. [003](003-definicao-de-presente.md) — "presente" em três níveis: ancestral, trailer `-x`, patch-id legado.
4. [004](004-estado-descartavel.md) — o estado é projeção recuperável mais julgamento humano que só existe no banco.
5. [005](005-alvo-distribuicao-entre-versoes.md) — tarefa marcada em `V` vale para as abertas maiores e para liberadas após o corte.
6. [006](006-match-exato-no-dominio.md) — a busca traz candidatos; o match por word-boundary é do domínio.
7. [007](007-tarefa-em-duas-abertas.md) — tarefa em duas abertas pinta vermelho mas não aborta.
8. [008](008-autenticacao-tickio.md) — Tickio por credencial, cobrada na primeira busca; o erro chega tarde.
9. [009](009-inferencia-de-base.md) — base inferida pelo número; o commit gravado é o ponto de corte.
10. [010](010-travas-publicada-e-liberada.md) — `publicada` trava o rebuild; `liberada` congela.
11. [011](011-congelamento-no-banco.md) — o congelamento é trigger de banco mais recusa no adapter.
12. [012](012-divergencia-entre-fontes.md) — o que fazer em cada divergência entre as três fontes.
13. [013](013-conflito-e-checkpoint.md) — conflito: `rerere` com `autoUpdate`, nunca auto-resolve, checkpoint resumível.
14. [014](014-ordem-de-aplicacao-pelo-grafo.md) — o lote se aplica na ordem do grafo; data não entra.
15. [015](015-estado-regravado-ao-final-do-lote.md) — o estado é regravado uma vez, ao final do lote.
16. [016](016-multi-projeto-premissas.md) — multi-projeto barato: o projeto é uma linha de tabela, não config.
17. [017](017-corte-por-projeto-na-fonte.md) — o Tickio já separa o alvo por projeto; o nome do repo vem do path.
18. [018](018-portas-e-adaptadores.md) — portas-e-adaptadores com núcleo puro e fakes fiéis.
19. [019](019-montagem-no-front-end.md) — `motor/montagem.py` monta os adapters, sem I/O.
20. [020](020-contrato-de-erro-por-tipo.md) — adapter só levanta `MotorError`; o contrato é por tipo.
21. [021](021-motor-nao-interativo.md) — o motor nunca pergunta: retorna um valor.
22. [022](022-fetch-origin-em-todo-entry-point.md) — todo entry point faz `git fetch origin` antes de ler refs.
23. [023](023-onde-nao-se-abstrai.md) — sem clock, sem config por projeto, sem cache de tag, sem trigger em `versao`.
