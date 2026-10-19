# Padrões de código

Como escrever código neste repo. O porquê das decisões de arquitetura está em
[../decisoes/](../decisoes/); aqui fica só o que o código tem de fazer para
respeitá-las. Regras de teste: [testes.md](testes.md).

## Ferramentas

`ruff format`, `ruff check` e `mypy` fazem parte do portão; a configuração está
no `pyproject.toml` (`[tool.ruff]` e `[tool.mypy]`) e não se repete aqui. O que
eles garantem — formatação, imports, tipos em `--strict` — não vira regra
escrita: regra copiada da config diverge dela no primeiro ajuste.

## Idioma

Identificadores em português **sem acento**; comentários e docstrings com acento
liberado.

Por quê: o nome é o que todo mundo tem de digitar — na chamada, no `grep`, no
terminal. Sem acento, ninguém depende de teclado ou locale para achar e chamar
o símbolo. Comentário só se lê, então pode ser escrito direito.

## Portas e adapters

- **Porta é `Protocol`, e conformidade se declara.** Como o `Protocol` é
  estrutural, o mypy só confere um adapter no ponto de atribuição. Todo adapter
  novo — real **e** fake — entra em `tests/test_conformidade.py`, declarado na
  sua porta. Sem isso, adapter com método faltando ou tipo trocado só aparece
  quando algum teste por acaso o passa adiante.
- **Chamada de porta é posicional.** As assinaturas em `motor/ports.py` marcam
  os parâmetros com `/`, porque nem o mypy nem a declaração de conformidade pegam
  renome de parâmetro. Não chame porta com argumento nomeado.
- **Quem monta adapter é o front-end, nunca o engine.** Adapter concreto só se
  importa em `motor/montagem.py`; o engine enxerga apenas `motor.ports`. Engine
  que importa `motor.adapters` passa a decidir infraestrutura, e montar em cada
  front-end duplica a regra. A decisão está em [../decisoes/](../decisoes/).

## Erros

Adapter levanta `MotorError` ou subclasse, e nada mais. Erro novo escolhe uma
classe de `motor/errors.py`, não só uma mensagem:

| Situação | Classe |
| --- | --- |
| Operação ilegal, dado íntegro | `RecusaDeInvariante` |
| O que foi pedido não existe | `NaoEncontrado` |
| O serviço não respondeu | `BackendIndisponivel` |
| Respondeu fora do contrato | `RespostaInvalida` |
| O que o operador passou não serve | `ErroDeEntrada` |
| O site genuinamente não sabe o que falhou | `MotorError` puro |
| Bug de programação | `AssertionError`, nunca `MotorError` |

Por quê: chamador e suíte de contrato distinguem por tipo, não por texto.
`MotorError` puro onde dava para classificar tira do chamador a distinção de que
ele precisa; classificar onde não dá (`git …: exit status N`) é adivinhar, o que
é pior. E bug levantado como `MotorError` seria absorvido pelos services, que
degradam em `MotorError`, em vez de chegar ao traceback do `main()`. A decisão
está em [../decisoes/](../decisoes/).

## Adapter de git: nunca `subprocess` direto

Em `motor/adapters/git/subprocess.py`, use `_rodar_git` (saída textual) ou
`_rodar_git_bytes`.

Por quê: os dois traduzem `OSError` em `BackendIndisponivel` — git fora do
`PATH`, `cwd` que sumiu —, e o textual decodifica com `errors="replace"`, porque
`text=True` decodifica em modo estrito e um byte inválido no histórico mataria a
varredura inteira. `subprocess.run` na mão reabre os dois buracos e quebra a
promessa de `motor.ports` de que adapter só levanta `MotorError`. Os `Popen` que
não cabem nos helpers levam a mesma guarda escrita à mão.

## Comentários

Comentário explica o porquê, não o quê.

Por quê: o quê o código já diz, e o comentário que o repete fica desatualizado
na primeira mudança sem que nada acuse. O porquê — a alternativa descartada, o
defeito que a linha evita — é o que não dá para reconstruir lendo o código.
