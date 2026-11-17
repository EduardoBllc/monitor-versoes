# monitor-versoes-bitbucket

Host de PR do [monitor-versoes](../../README.md) para o **Bitbucket Cloud**.

Busca as PRs mergeadas do repo e os commits de cada uma, sem os merge commits. O
`workspace/repo` sai da URL do `origin`. Varredura, casamento com a referência e cache
ficam no motor ([036](../../docs/decisoes/036-fonte-de-pr-plugavel.md)).

## Instalação

Escolha o Bitbucket no `monitor-versoes configurar`, ou:

```bash
monitor-versoes plugin instalar "git+https://github.com/EduardoBllc/monitor-versoes#subdirectory=plugins/bitbucket"
```

O plugin acompanha a tag do motor, e o `monitor-versoes atualizar-motor` o atualiza junto
(veja "Instalação" no [README principal](../../README.md)).

## Configuração

| Onde | Chave | Obrigatória | Significado |
| --- | --- | --- | --- |
| `[prs]` | `fonte = "bitbucket"` | sim | escolhe o plugin |
| `[ambiente]` | `BITBUCKET_EMAIL` | sim | e-mail da conta do Bitbucket |
| `[ambiente]` | `BITBUCKET_TOKEN` | sim | API token da conta |

O plugin não lê outras chaves de `[prs]`. O formato do config está no
[README principal](../../README.md).

```toml
[prs]
fonte = "bitbucket"

[ambiente]
BITBUCKET_EMAIL = "voce@empresa.com"
BITBUCKET_TOKEN = "..."
```

O `monitor-versoes diagnostico` valida a credencial com `GET /user`, que exige escopo de
leitura da conta no token.

## Erros

Credencial que falta é erro de entrada, citando o `config.toml` lido. URL do `origin` fora
do formato `workspace/repo` e resposta em formato inesperado são resposta inválida. Falha
de rede ou status diferente de 200 indicam o Bitbucket indisponível.
