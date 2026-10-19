# monitor-versoes — armadilhas do ambiente

Coisas que fazem comandos corretos falharem por motivo que não é o código.
Setup e comandos: `README.md`. Desenho: `docs/design.md`.

## `uv run` não funciona nesta máquina

Há um `VIRTUAL_ENV` de outro projeto (`vendabemweb`, Python 2.7) vazando para o
shell. O `uv` o prefere sobre o `.venv` do projeto e o pytest morre na coleta com
`SyntaxError: future feature annotations is not defined` — que **não** é erro de
código.

```bash
./.venv/bin/python -m pytest        # use isto
./.venv/bin/python -m mypy          # idem — le files/strict do pyproject
```

Se o `.venv` não existir: `unset VIRTUAL_ENV; uv sync --all-extras`.

## `mypy` faz parte do portão, não é opcional

`motor/` roda em `--strict`; `tests/` roda o strict inteiro menos a exigência de
assinatura em função de teste. **Sem CI neste repo** — rodar é manual, junto do
pytest.

O que ele existe para pegar: `Protocol` é estrutural, então adapter que não
cumpre a porta só aparece no ponto de atribuição.
`tests/test_conformidade.py` é esse ponto — declara cada adapter (real **e**
fake) na sua porta. Adapter novo entra lá. Ele pega método faltando e tipo de
parâmetro ou retorno trocado; **não** pega renome de parâmetro, porque toda
chamada de porta aqui é posicional.

## Produção é o padrão em tudo; desenvolvimento é explícito

CLI, `compose.yml` e `alembic/env.py` leem `.env`, ou seja **produção** (porta
5433). Desenvolvimento (`.env.development`, porta **5434**) exige
`--env development` no CLI, e existe para a suíte automatizada — `docker compose
up -d` sozinho sobe o container de produção, que não é o banco que a suíte usa.

```bash
docker compose --env-file .env.development up -d
set -a; . ./.env.development; set +a; ./.venv/bin/python -m alembic upgrade head
```

O `set -a` é o que redireciona o Alembic: o `load_dotenv()` dele não sobrescreve
variável já presente no ambiente.

## Testes e o arquivo de ambiente

A suíte roda sem git, sem rede e sem banco de pé. Os marcados
`@pytest.mark.integracao` sobem um Postgres **efêmero** (testcontainers), migram
com `alembic upgrade head` e o derrubam no fim da sessão. Sem Docker, pulam.

O `tests/conftest.py` continua carregando `.env.development` com `override=True`
no import — mas só pelo `PROJECTS_DIR` e pelas credenciais externas vazias. Os
`DATABASE_*` de lá são sobrescritos pelas coordenadas do container assim que ele
sobe, e o `.env` de produção não participa da suíte.

- O `_postgres_efemero` é **lazy**: rodar só `tests/test_git.py` não toca no
  Docker. Rodada completa paga um start + migrate (~9s).
- Consequência do sobrescrito: teste que aponte `DATABASE_*` para outro lugar
  **antes** de pedir o banco não testa nada — o container repõe as variáveis. Se
  o ponto é o ambiente divergir, peça `_postgres_efemero` primeiro
  (`tests/test_config.py::test_sessao_postgres_ignora_o_ambiente`).

**Nunca use `monkeypatch.delenv` para testar variável ausente em teste que chama
`main()`.** O `main()` chama `load_dotenv()` a cada invocação, então a variável
volta do arquivo de ambiente e o teste sai para a rede — já aconteceu. Use
`monkeypatch.setenv(VAR, "")`. Existe uma guarda autouse no `conftest.py` que
desliga esse `load_dotenv()`, mas o teste dela só discrimina em máquina com
`.env`.

O fixture `sessao_postgres` dá `TRUNCATE` nas sete tabelas **no setup e no
teardown**, e monta o engine com `_postgres_efemero.get_connection_url()`, não
com `database_url()`. Não é estilo: enquanto a URL saía do ambiente, um `.env`
mal apontado truncaria produção, e o que segurava isso era uma checagem
(`_exigir_banco_development`) que alguém tinha de lembrar de manter. Trocar para
a URL do container tira o ambiente do caminho — **não reintroduza
`create_engine(database_url())` ali**.

## Ao mexer em `EstadoRepo`

`FakeEstado` e `PostgresEstado` têm de concordar. O contrato está em
`tests/test_estado_contrato.py`, que roda as mesmas asserções contra os dois — a
assertion nova vai para lá, não para uma das duas suítes. Fake mais permissivo que
o banco deixa a suíte verde num caminho que quebra em produção, e este projeto já
pagou por isso três vezes.

## Erro novo escolhe classe, não só mensagem

`motor/errors.py` tem cinco classes. `raise MotorError(...)` puro só quando o
site genuinamente não sabe o que falhou — em `GitSubprocess._run`, por exemplo.
Nos outros, escolha: `RecusaDeInvariante`, `NaoEncontrado`,
`BackendIndisponivel`, `RespostaInvalida` (portas) ou `ErroDeEntrada` (operador).
Bug de programação é `AssertionError`, não `MotorError`.

**Teste de erro assere tipo, não substring de mensagem.** Exceção: quando o
*texto* é o requisito (a dica do `docker compose up -d`, a instrução `motor repo
adicionar`) — aí valem os dois.

## No adapter de git, não chame `subprocess` direto

Use `_rodar_git` (saída textual) ou `_rodar_git_bytes`. Os dois traduzem `OSError`
em `BackendIndisponivel` — git fora do PATH, `cwd` que sumiu — e o textual passa
`errors="replace"`, porque `text=True` decodifica em modo **estrito** e um byte
inválido no histórico mataria a varredura inteira.

Chamar `subprocess.run` na mão reabre os dois buracos, e o contrato de
`motor.ports` promete que adapter só levanta `MotorError` ou subclasse. Os dois
`Popen` que sobraram têm a guarda escrita à mão, pelo mesmo motivo.
