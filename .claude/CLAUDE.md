# monitor-versoes — armadilhas do ambiente

Duas coisas que fazem comandos corretos falharem por motivo que não é o código.

## `uv run` não funciona nesta máquina

Há um `VIRTUAL_ENV` de outro projeto (`vendabemweb`, Python 2.7) vazando para o
shell. O `uv` o prefere sobre o `.venv` do projeto e o pytest morre na coleta com
`SyntaxError: future feature annotations is not defined` — que **não** é erro de
código.

```bash
./.venv/bin/python -m pytest        # use isto
./.venv/bin/python -m alembic upgrade head
```

Se o `.venv` não existir: `unset VIRTUAL_ENV; uv sync --all-extras`.

## Testes e o `.env`

A suíte roda sem git, sem rede e sem banco. Exceção: os marcados
`@pytest.mark.integracao`, que precisam do Postgres do `compose.yml`.

- Sem `.env` (clone novo, CI) → `DATABASE_HOST` ausente → pulam.
- Com `.env` e container parado → pulam pela guarda de `OperationalError` no
  fixture.
- `env -u DATABASE_HOST` **não** faz pular: o `tests/conftest.py` chama
  `load_dotenv()` e repõe a variável. Para simular ausência, use `DATABASE_HOST=`
  vazia.

**Nunca use `monkeypatch.delenv` para testar variável ausente em teste que chama
`main()`.** O `main()` chama `load_dotenv()` a cada invocação, então a variável
volta do `.env` de verdade e o teste sai para a rede — já aconteceu. Use
`monkeypatch.setenv(VAR, "")`. Existe uma guarda autouse no `conftest.py` que
desliga esse `load_dotenv()`, mas o teste dela só discrimina em máquina com `.env`.

## Banco de desenvolvimento

```bash
docker compose up -d                       # porta 5433, não 5432
./.venv/bin/python -m alembic upgrade head
```

O fixture de integração dá `TRUNCATE` nas sete tabelas **no setup**, nunca no
teardown — toda rodada deixa as linhas do último teste. Se precisar do banco limpo,
trunque à mão.

## Ao mexer em `EstadoRepo`

`FakeEstado` e `PostgresEstado` têm de concordar. O contrato está em
`tests/test_estado_contrato.py`, que roda as mesmas asserções contra os dois — a
assertion nova vai para lá, não para uma das duas suítes. Fake mais permissivo que
o banco deixa a suíte verde num caminho que quebra em produção, e este projeto já
pagou por isso três vezes.
