# O match exato é do domínio, não da busca

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [005](005-alvo-distribuicao-entre-versoes.md),
  [018](018-portas-e-adaptadores.md)

O `CommitSource` (grep em `master`, ou PR do Bitbucket) só traz **candidatos** — é
`contains`, não exato, e casar `5514` sem cuidado pega `255514`, substring de outro chamado.
A confirmação com word-boundary (`\bch5514\b`) roda no domínio: mais portável, e testável com
o git fake.
