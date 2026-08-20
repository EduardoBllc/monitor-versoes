# TUI para verificar versões

**Status:** design aprovado em conversa em 2026-08-20

## Objetivo

Adicionar uma interface Textual ao processo atual para que o operador selecione um
repositório cadastrado, selecione automaticamente uma versão Git e execute
`verificar`, vendo o `VersionStatus` de forma estruturada. A TUI é uma nova fachada
do mesmo motor usado pelo CLI; ela não replica regras de domínio nem interpreta a
saída textual de `motor verificar`.

## Escopo

O primeiro recorte contém somente:

- entrada por `uv run motor tui` e `uv run motor --env production tui`;
- repositórios cadastrados no banco;
- versões descobertas automaticamente nas referências Git `X.Y.Z`;
- execução de `verificar` com Tickio;
- leitura normal do snapshot de uma versão liberada e auditoria explícita da tag;
- apresentação estruturada do resultado e dos erros.

Ficam fora deste recorte:

- `criar`, `atualizar` e `reconstruir-estado`;
- fonte manual de tasks;
- cadastro ou edição de repos pela TUI;
- histórico de execuções, filtros e persistência da última seleção;
- caminhos de repo fora de `PROJECTS_DIR`;
- daemon, API HTTP ou qualquer outro processo auxiliar.

## Decisões de arquitetura

### Um único processo

`MotorTUI`, Git, Tickio e Postgres executam no mesmo processo. Operações de banco,
rede e subprocessos Git rodam em workers do Textual para não bloquear o loop da
interface. Não existe daemon local.

```text
MotorTUI ──worker──> verificar(Deps, versão, auditar)
                         │
                         ├── GitRepo
                         ├── TaskSource (Tickio)
                         └── EstadoRepo (Postgres)
```

O worker abre e fecha sua própria sessão SQLAlchemy. Nenhuma sessão atravessa a
fronteira entre a thread da interface e a thread de trabalho.

### Nova leitura no estado

`EstadoRepo` ganha apenas o método necessário para montar o seletor:

```python
def listar_repos(self) -> list[RepoInfo]: ...
```

O adapter Postgres consulta as linhas de `repo`; o fake devolve seu dicionário de
repos. O resultado é determinístico, ordenado por nome canônico. Nenhuma nova
porta, tabela ou camada de serviço é criada.

### Reaproveitamento do motor

A TUI chama `motor.engine.verificar.verificar()` e renderiza o `VersionStatus`
retornado. O CLI continua responsável apenas por argparse e impressão. O motor e
seus tipos não ganham conceitos de widget, cor ou interação.

## Descoberta de repositórios

Na inicialização, um worker:

1. abre o estado e chama `listar_repos()`;
2. examina apenas os filhos diretos de `PROJECTS_DIR` que contenham `.git` como
   arquivo ou diretório;
3. usa `EstadoRepo.resolver_repo(basename)` para associar nomes canônicos e aliases;
4. produz uma opção por repo canônico cadastrado.

Se mais de uma pasta local resolver para o mesmo repo, a pasta cujo basename seja
o nome canônico tem prioridade; sem ela, vence o alias de menor ordem alfabética.
O seletor sempre exibe o nome canônico. Um repo sem checkout local continua
visível, mas desabilitado com `checkout local não encontrado`.

Pastas não cadastradas no banco nunca aparecem. Se `PROJECTS_DIR` estiver ausente
ou não existir, todos os repos cadastrados aparecem desabilitados e a interface
mostra uma única mensagem operacional explicando a configuração ausente.

## Descoberta de versões

Ao selecionar um repo habilitado, um worker:

1. executa `git.fetch("origin")`;
2. chama `list_version_branches()`, cuja implementação já reúne heads locais,
   tags e referências `origin` no padrão `X.Y.Z`;
3. chama `list_version_tags()` para identificar quais opções estão liberadas;
4. remove duplicatas e ordena numericamente por `(X, Y, Z)`, da maior para a menor.

Falha no fetch deixa o seletor de versão vazio, mantém `Executar` desabilitado e
mostra o `MotorError`. Não há fallback silencioso para referências possivelmente
desatualizadas.

## Interface e interação

A composição segue a direção visual “barra de execução” aprovada:

```text
┌────────────────────────────────────────────────────────────────────┐
│ MOTOR                                            ? ajuda   q sair  │
├────────────────────────────────────────────────────────────────────┤
│ Repo [──────────▾]  Ação [Verificar]  Versão [────────▾] [Executar]│
├────────────────────────────────────────────────────────────────────┤
│ banner e contadores                                                │
│ resultado estruturado                                             │
└────────────────────────────────────────────────────────────────────┘
```

- A TUI inicia sem repo e versão selecionados.
- `Ação` é texto fixo `Verificar`, não um seletor com uma única opção. Ele só vira
  seletor quando uma segunda ação for implementada.
- `Executar` permanece desabilitado até repo e versão válidos estarem selecionados.
- Trocar o repo limpa a versão e o resultado anterior antes de carregar as novas
  versões.
- Ao selecionar uma tag, aparece `Auditar tag agora`, desmarcado por padrão.
- Ao selecionar uma versão sem tag, a opção de auditoria some e volta a `False`.
- Durante uma carga ou verificação, os controles relevantes ficam bloqueados. A
  primeira operação precisa terminar antes de outra começar.
- A navegação padrão por teclado do Textual é preservada; `q` encerra a aplicação.

## Execução de `verificar`

Ao pressionar `Executar`, o worker:

1. abre uma sessão do banco;
2. cria `PostgresEstado` e resolve o basename da pasta para o `RepoInfo` canônico;
3. cria `GitRepo` para a pasta escolhida;
4. cria `TickioRest` com as variáveis do ambiente já carregado e o
   `tickio_sistema_id` do repo;
5. monta `Deps` com as credenciais opcionais do Bitbucket;
6. chama `verificar(deps, versao, auditar=auditar_tag)`;
7. fecha sessão e engine ao terminar, inclusive em erro.

O fluxo reutiliza a composição existente do CLI onde ela já for diretamente
aplicável. Não será criada uma fábrica genérica de dependências para um único caso.

## Apresentação do resultado

Cada execução substitui integralmente o conteúdo anterior. A área de resultado
mostra somente seções relevantes:

- banner verde quando `status.verde` for verdadeiro;
- banner vermelho `REQUER ATENÇÃO` nos demais casos;
- contadores de tasks novas, tasks removidas, commits faltantes e conflitos;
- alerta de estado divergente, incluindo hashes de commits sumidos;
- alertas de tasks ambíguas e tasks sem commits;
- commits faltantes agrupados por chamado e preservando sua ordem;
- hash curto, primeira linha da mensagem e badges `CONFLITANTE` e `SUSPEITO`;
- em snapshot liberado: data da liberação, aviso de snapshot congelado e chamados;
- em auditoria: indicação explícita de que a tag foi recalculada sem alterar o
  snapshot.

Listas e contadores vazios são omitidos, exceto os quatro contadores do resumo,
que permanecem visíveis para leitura rápida. A interface não inventa um total de
tasks que o `VersionStatus` não forneça de forma autoritativa.

## Erros

- `MotorError` é exibido em um painel vermelho como falha operacional, sem
  traceback.
- Exceções inesperadas exibem `Erro interno fatal` e são enviadas a
  `logging.exception`, preservando o traceback fora do conteúdo normal da TUI.
- Repo sem checkout é desabilitado antes da execução.
- Repo sem versões mostra `nenhuma branch ou tag X.Y.Z encontrada` e mantém
  `Executar` desabilitado.

Uma nova seleção ou execução bem-sucedida limpa o erro anterior.

## Arquivos previstos

- `motor/tui.py`: aplicação, workers e pequenas transformações de apresentação;
- `motor/__main__.py`: subcomando `tui` e despacho para a aplicação;
- `motor/ports.py`: contrato `listar_repos()`;
- `motor/adapters/estado/postgres.py`: consulta dos repos;
- `motor/adapters/estado/fake.py`: implementação fake;
- `tests/test_tui.py`: descoberta e fluxo principal da interface;
- testes de contrato/CLI existentes: cobertura do novo método e do subcomando.

Nenhuma mudança é prevista nos engines ou nos modelos do domínio.

## Estratégia de testes

1. O contrato de `EstadoRepo` prova que fake e Postgres listam somente repos
   canônicos e em ordem estável.
2. Testes pequenos provam a associação com pasta canônica, fallback para alias,
   repo sem checkout e ausência de `PROJECTS_DIR`.
3. Testes pequenos provam deduplicação, ordem numérica e identificação de tags.
4. Um teste com `App.run_test()` e bordas falsas percorre seleção de repo, seleção
   de versão, execução e renderização do resultado.
5. O mesmo fluxo prova que uma tag usa snapshot por padrão e passa `auditar=True`
   quando a opção estiver marcada.
6. Casos de `MotorError` e exceção inesperada verificam a mensagem adequada.
7. `rtk uv run pytest` executa a suíte inteira e garante que os comandos atuais do
   CLI continuam funcionando.

## Critérios de aceite

- `uv run motor tui` abre a interface sem acessar Git ou Tickio na thread da UI.
- O seletor contém somente repos canônicos cadastrados no banco.
- Repos cadastrados sem checkout aparecem desabilitados e explicados.
- Selecionar um repo habilitado carrega automaticamente versões `X.Y.Z` recentes.
- Executar chama o engine existente e apresenta claramente verde, pendências,
  conflitos, suspeitas e inconsistências.
- Tags mostram snapshot por padrão e permitem auditoria explícita sem alterar o
  snapshot.
- Nenhuma execução concorrente pode ser iniciada pela interface.
- O CLI existente e toda a suíte atual continuam passando.
