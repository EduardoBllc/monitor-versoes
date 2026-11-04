# O match exato é do domínio, não da busca

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [005](005-alvo-distribuicao-entre-versoes.md),
  [018](018-portas-e-adaptadores.md)

O `CommitSource` (grep em `master`, ou PR do Bitbucket) só traz **candidatos** — é
`contains`, não exato, e casar `5514` sem cuidado pega `255514`, substring de outro chamado.
A confirmação com fronteira de palavra roda no domínio: mais portável, e testável com o git
fake.

A confirmação usa o padrão de referência recebido (um template com `{id}`, proposto pelo
adapter do tracker e sobrescrito pela [024](024-config-por-projeto.md)) e o alfabeto do id. A
fronteira vale por lado, com um conjunto *S*: se a ponta da referência é caractere de *S*, o
vizinho daquele lado não pode ser de *S*; se não é (como o `[` de `[{id}]`), o lado fica livre.

- **Domínio** (`match_exato`, `extrair_chamado`): *S* são os caracteres de palavra mais os do
  alfabeto. No Tickio (`ch{id}`, só dígitos), é o `\b` de `\bch5514\b`.
- **Bitbucket** (título e branch da PR): *S* são só os caracteres do alfabeto. No Tickio, o
  `c` à esquerda fica livre e a direita vira "sem dígito depois".
