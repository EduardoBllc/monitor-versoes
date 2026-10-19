# Arquitetura: portas-e-adaptadores com núcleo puro

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [011](011-congelamento-no-banco.md)

**Portas-e-adaptadores com núcleo puro.** Quatro portas: fonte de tasks, fonte de commits,
git e estado. Cada uma tem um adapter fake, e é por isso que a suíte roda sem git, sem rede e
sem banco.

O domínio é só dados e funções determinísticas — nada nele toca git, rede ou banco. As regras
que vivem lá: inferência de tipo e de base ([009](009-inferencia-de-base.md)), distribuição
entre versões ([005](005-alvo-distribuicao-entre-versoes.md)), reconciliação três-vias
([012](012-divergencia-entre-fontes.md)), o match exato por word-boundary
([006](006-match-exato-no-dominio.md)) e a ordenação do lote
([014](014-ordem-de-aplicacao-pelo-grafo.md)). A tradução entre modelo de banco e dataclass
do domínio acontece na fronteira do adapter: **o domínio nunca importa `sqlalchemy`**.

O estado fake **espelha as mesmas recusas da trigger de congelamento**
([011](011-congelamento-no-banco.md)). Não é zelo: um fake mais permissivo que o banco deixa
a suíte verde num caminho que quebra em produção.

O que sustenta essa arquitetura: [021](021-motor-nao-interativo.md). Quem monta os adapters:
[019](019-montagem-no-front-end.md). O que eles podem levantar:
[020](020-contrato-de-erro-por-tipo.md).
