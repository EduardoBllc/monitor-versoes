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

## Desenvolvimento é o padrão do CLI, produção é o padrão de tudo o mais

O CLI usa `.env.development` (porta **5434**) por padrão; produção exige
`--env production`. O `compose.yml` e o `alembic/env.py` fazem o contrário: leem
`.env`, ou seja **produção** (porta 5433). `docker compose up -d` sozinho sobe o
container de produção — não é o banco que a suíte usa.

```bash
docker compose --env-file .env.development up -d
set -a; . ./.env.development; set +a; ./.venv/bin/python -m alembic upgrade head
```

O `set -a` é o que redireciona o Alembic: o `load_dotenv()` dele não sobrescreve
variável já presente no ambiente.

## Testes e o arquivo de ambiente

A suíte roda sem git, sem rede e sem banco. Exceção: os marcados
`@pytest.mark.integracao`, que precisam do Postgres de **desenvolvimento** de pé.
O `tests/conftest.py` carrega `.env.development` com `override=True` no import —
o `.env` de produção não participa da suíte.

- Sem `.env.development` (clone novo, CI) → `DATABASE_HOST` ausente → pulam.
- Com `.env.development` e container parado → pulam pela guarda de
  `OperationalError` no fixture.
- `env -u DATABASE_HOST` **não** faz pular: o `conftest.py` repõe a variável.
  Para simular ausência, use `DATABASE_HOST=` vazia.

**Nunca use `monkeypatch.delenv` para testar variável ausente em teste que chama
`main()`.** O `main()` chama `load_dotenv()` a cada invocação, então a variável
volta do arquivo de ambiente e o teste sai para a rede — já aconteceu. Use
`monkeypatch.setenv(VAR, "")`. Existe uma guarda autouse no `conftest.py` que
desliga esse `load_dotenv()`, mas o teste dela só discrimina em máquina com
`.env`.

O fixture `sessao_postgres` dá `TRUNCATE` nas sete tabelas **no setup e no
teardown**, e `_exigir_banco_development` **recusa rodar** contra qualquer banco
que não seja exatamente o do `.env.development` — sem essa checagem um
`.env` mal apontado truncaria produção.

## Ao mexer em `EstadoRepo`

`FakeEstado` e `PostgresEstado` têm de concordar. O contrato está em
`tests/test_estado_contrato.py`, que roda as mesmas asserções contra os dois — a
assertion nova vai para lá, não para uma das duas suítes. Fake mais permissivo que
o banco deixa a suíte verde num caminho que quebra em produção, e este projeto já
pagou por isso três vezes.
