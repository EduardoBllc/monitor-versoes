# Padrões de teste

Critério para escrever, revisar e remover testes. Regras de código de produção
ficam em [codigo.md](codigo.md); como rodar a suíte, no [README](../../README.md).

## O que merece um teste

- **Relevante:** protege comportamento observável, risco importante ou regressão
  plausível cujo impacto justifique o custo de rodar e manter.
- **Durável:** descreve contrato ou invariante que sobrevive a refatorações — não
  a organização interna, a chamada entre funções ou o formato acidental da
  implementação atual.
- **Conciso:** é o menor representante que demonstra a regressão sem repetir uma
  proteção que já existe.
- Não crie teste para elevar contagem ou cobertura. Uma correção específica só
  ganha caso próprio quando revela uma regra durável; senão, entra num
  representante existente ou fica fora da suíte.

Antes de adicionar ou preservar um teste, responda:

1. Qual regressão relevante ele detecta?
2. Um teste existente já falharia pela mesma razão?
3. O cenário pode ser demonstrado por uma fronteira pública mais estável?
4. Ele pode ser incorporado a outro teste sem esconder qual garantia falhou?

Cada teste representa uma garantia. Pode executar várias ações e ter várias
asserções, desde que todas demonstrem essa garantia. Variações da mesma regra
vão em `pytest.mark.parametrize`; riscos ou ramificações independentes ficam em
testes separados — senão a falha não diz o que quebrou.

## Escolha da camada

- Prefira a fronteira pública mais estável que demonstre a regressão: o caso de
  uso com `Deps` montado sobre fakes, a porta, o `main()` do CLI. Teste preso a
  detalhe interno quebra na refatoração sem que nada tenha regredido.
- Não replique a mesma garantia em várias camadas. Teste de camada inferior só
  fica quando protege uma invariante que a fronteira pública não mostra — o
  trigger do banco, a tradução de erro do adapter de git.
- Encadear operações num teste é legítimo para provar transição, repetição,
  idempotência e estado final.
- Não exponha interface de produção só para tornar um detalhe testável.

## Fakes e adapters

**Adapter novo, real ou fake, é declarado na sua porta em
`tests/test_conformidade.py`.** `Protocol` é estrutural: o mypy só confere
conformidade no ponto de atribuição, e esse arquivo é o ponto. Ele pega método
faltando e tipo de parâmetro ou retorno trocado; não pega renome de parâmetro,
porque toda chamada de porta aqui é posicional. Por isso o `mypy` faz parte do
portão tanto quanto o `pytest`.

**Comportamento novo de `EstadoRepo` é asserido em
`tests/test_estado_contrato.py`,** que roda as mesmas asserções contra
`FakeEstado`, `PostgresEstado` no Postgres e no SQLite. Teste que existe só num dos lados não é
contrato: fake mais permissivo que o banco deixa a suíte verde num caminho que
quebra em produção, e o projeto já pagou por isso três vezes (FK, ordem, fake de
git divergente).

## Erros

**Teste de erro assere o tipo, não substring da mensagem** —
`pytest.raises(NaoEncontrado)`, não `match="não encontrado"`. A classe é o
contrato que o chamador usa para decidir o que fazer; a mensagem muda por
redação sem que nada tenha regredido. Exceção: quando o *texto* é o requisito
(a dica de `docker compose up -d`, a instrução `motor repo adicionar`), asserir
tipo e texto.

## Ambiente e integração

A suíte roda sem rede, sem banco de pé e sem os repositórios reais: o adapter
de git é exercitado com git de verdade em repositório criado em `tmp_path`.

**O SQLite roda no portão comum.** O parâmetro `sqlite` do contrato usa o fixture
`sessao_sqlite` (arquivo em `tmp_path`, migrado como no primeiro uso), sem Docker e sem marca.

**Integração com Postgres usa Postgres efêmero.** Teste que precisa de banco pede o fixture
`sessao_postgres` e leva `@pytest.mark.integracao`. O `_postgres_efemero` sobe
um container (testcontainers), exporta `DATABASE_BACKEND=postgres`, migra com `alembic upgrade head` — não
`create_all`, que perderia as triggers — e o derruba no fim da sessão. É lazy:
quem não pede banco não toca no Docker. Sem Docker, esses testes pulam; pulado
não é verde, e a saída do portão diz qual dos dois aconteceu.

**`sessao_postgres` monta o engine com a URL do container, nunca com
`database_url()`.** Ele dá `TRUNCATE` em tudo no setup e no teardown; se a URL
saísse do ambiente, um `.env` mal apontado ou um `monkeypatch` truncaria
produção. Não reintroduza `create_engine(database_url())` ali.

**Teste que aponta `DATABASE_*` para outro lugar pede `_postgres_efemero`
antes.** O container sobrescreve essas variáveis quando sobe; mexer nelas antes
de pedir o banco não testa nada.

**Variável ausente em teste que chama `main()`: `monkeypatch.setenv(VAR, "")`,
nunca `delenv`.** O `main()` chama `load_dotenv()` a cada invocação, então a
variável apagada volta do arquivo de ambiente e o teste sai para a rede — já
aconteceu. A guarda autouse do `conftest.py` desliga esse `load_dotenv()`, mas
ela é rede de proteção, não licença.

## Qualidade e fluxo

- A suíte canônica é determinística, compreensível e durável: sem rede e sem
  depender de ordem de execução. Repetição e investigação de flakiness são
  opt-in e não legitimam instabilidade no portão.
- Mudança de comportamento começa pelo menor teste relevante na camada
  escolhida; implemente só o necessário para ele passar.
- Nomes descrevem cenário, ação e resultado observável, em português sem acento
  (`test_atualizar_bloqueia_com_suspeita_de_conteudo`).
