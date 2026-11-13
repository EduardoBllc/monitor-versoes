# Decisões

Uma decisão por arquivo, `NNN-slug.md`, em prosa livre. Cada arquivo abre com o
status (`aceita` ou `substituída por NNN`) e a data, e linka as decisões de que
depende.

Aqui fica o porquê do sistema. Estrutura (schema, assinaturas, comandos) não está
aqui — essa o código responde melhor e sem apodrecer. Uso: [README.md](../../README.md).

## Ordem de leitura

Uma linha por decisão, na ordem em que a narrativa se encadeia.

1. [001](001-problema-completude-de-commits.md) — o problema: cherry-pick troca o hash; o escopo é completude de commits.
2. [002](002-oraculo-tres-fontes.md) — presença cruza Tickio, estado e git; verde só quando os três concordam.
3. [003](003-definicao-de-presente.md) — "presente" em três níveis: ancestral, trailer `-x`, patch-id legado.
4. [004](004-estado-descartavel.md) — o estado é projeção recuperável mais julgamento humano que só existe no banco.
5. [005](005-alvo-distribuicao-entre-versoes.md) — política `composta`: tarefa marcada em `V` vale para as abertas maiores e para liberadas após o corte.
6. [006](006-match-exato-no-dominio.md) — a busca traz candidatos; o match por word-boundary é do domínio.
7. [007](007-tarefa-em-duas-abertas.md) — tarefa em duas abertas pinta vermelho mas não aborta.
8. [008](008-autenticacao-tickio.md) — Tickio por credencial, cobrada na primeira busca; o erro chega tarde.
9. [009](009-inferencia-de-base.md) — esquema `vendabem`: base inferida pelo número; o commit gravado é o ponto de corte.
10. [010](010-travas-publicada-e-liberada.md) — `publicada` trava o rebuild; `liberada` congela.
11. [011](011-congelamento-no-banco.md) — o congelamento é trigger de banco mais recusa no adapter.
12. [012](012-divergencia-entre-fontes.md) — o que fazer em cada divergência entre as três fontes.
13. [013](013-conflito-e-checkpoint.md) — conflito: `rerere` com `autoUpdate`, nunca auto-resolve, checkpoint resumível.
14. [014](014-ordem-de-aplicacao-pelo-grafo.md) — o lote se aplica na ordem do grafo; data não entra.
15. [015](015-estado-regravado-ao-final-do-lote.md) — o estado é regravado uma vez, ao final do lote.
16. [016](016-multi-projeto-premissas.md) — multi-projeto barato (o ponto "sem config por projeto" foi revogado pela [024](024-config-por-projeto.md)).
17. [017](017-corte-por-projeto-na-fonte.md) — o Tickio já separa o alvo por projeto; o nome do repo vem do path.
18. [018](018-portas-e-adaptadores.md) — portas-e-adaptadores com núcleo puro e fakes fiéis.
19. [019](019-montagem-no-front-end.md) — `motor/montagem.py` monta os adapters, sem I/O.
20. [020](020-contrato-de-erro-por-tipo.md) — adapter só levanta `MotorError`; o contrato é por tipo.
21. [021](021-motor-nao-interativo.md) — o motor nunca pergunta: retorna um valor.
22. [022](022-fetch-origin-em-todo-entry-point.md) — todo entry point faz `git fetch origin` antes de ler refs.
23. [023](023-onde-nao-se-abstrai.md) — sem clock, sem cache de tag, sem trigger em `versao` (o "sem config por projeto" foi revogado pela [024](024-config-por-projeto.md) e o "sem clock" pela [025](025-reaproveitamento-da-verificacao.md)).
24. [024](024-config-por-projeto.md) — config por projeto em duas camadas (global e repo), piso sem padrão, import path só no central.
25. [025](025-reaproveitamento-da-verificacao.md) — `atualizar` reaproveita a verificação de até 5 minutos se tip e impressão não mudaram; o carimbo é cache.
26. [026](026-esquema-e-atribuicao-plugaveis.md) — esquema de versão e política de atribuição plugáveis; liberada e nomes de branch em camadas (config > esquema > padrão), com `semver`, `exata`, `main` e tag `{versao}` como padrão.
27. [027](027-fonte-de-tarefas-plugavel.md) — fonte de tarefas plugável e sem padrão no núcleo, carregada só no uso; `sistema` e `piso` saem do banco e ficam só na config.
28. [028](028-inscricoes-fora-do-estado.md) — inscrições num arquivo local fora do estado (o clone é da máquina); um processo por inscrição isola o ambiente (o "sem lock contra um `atualizar` manual" foi substituído pela [032](032-lock-por-repo-entre-processos.md)).
29. [029](029-repos-na-config-central.md) — repos são seções `[repos.<nome>]` do `config.toml` central, com `caminho`; saem `.monitor-versoes.toml`, aliases e `PROJECTS_DIR`; a linha `repo` nasce no primeiro uso.
30. [030](030-front-end-web-spa-com-dist-versionado.md) — `motor serve`: daemon local em `127.0.0.1` e SPA React/TS com build versionado (instalar não exige Node) e contrato tipado pelo OpenAPI (o lock de uma operação por repo dentro do daemon foi substituído pela [032](032-lock-por-repo-entre-processos.md)).
31. [031](031-ambiente-na-config-central.md) — banco e credenciais na tabela `[ambiente]` do `config.toml` central, só no topo; precedência central > `.env` > shell; inscrição sem diretório (o `motor init` saiu com a [035](035-estado-local-em-sqlite.md)).
32. [032](032-lock-por-repo-entre-processos.md) — um lock por clone (`flock` fora do clone) entre todos os processos do motor, pela operação inteira de quem escreve no clone; o segundo não espera: recusa com o pid, e a inscrição sai `PULADA`.
33. [033](033-config-editavel-pelas-interfaces.md) — TUI e web editam o `config.toml` central: plugins declaram `campos_config`, escrita com `tomlkit` preserva o arquivo, `[ambiente]` reaplicado sem reiniciar; salvar não consulta o lock do clone.
34. [034](034-julgamento-de-orfao.md) — o julgamento de órfão tem registro próprio, por versão; o `reconstruir-estado` e o `verificar` o aplicam como commit da tarefa do alvo, sem pôr tarefa no alvo, e a exclusão vence; listar e julgar não tomam o lock do clone.
35. [035](035-estado-local-em-sqlite.md) — o estado é local e mora só em SQLite; configuração antiga com Postgres dá erro, e a saída é o `migrar-estado` de um commit fixado.
36. [036](036-fonte-de-pr-plugavel.md) — host de PR plugável em `[prs] fonte`, sem padrão (sem ela, só o grep); o plugin só fala com o host e o pipeline de PR fica no núcleo; o estado de PR é por host e trocar de host o zera.
37. [037](037-teste-da-config-em-subprocesso.md) — a web testa uma peça da config sobre o rascunho não salvo num subprocesso com `XDG_CONFIG_HOME` temporário, para a credencial digitada não entrar no ambiente do daemon; timeout de 30 s, correção citando o `config.toml` real.
38. [038](038-sugestao-de-resolucao-por-ia.md) — a web pede à IA uma proposta por bloco aberto e o operador aplica ou descarta (só o **Marcar resolvido** grava); provedor plugável sem padrão em `[sugestao]`, `anthropic` como extra opcional com a chave só do `[ambiente]`; pedido sem lock.
39. [039](039-versionamento-por-tag.md) — versão pelos commits convencionais (squash merge, título do PR convencional), num PR de release que cria a tag `vX.Y.Z` e a Release; sem PyPI até o nome definitivo; checagem de atualização por `git ls-remote --tags`; `0.x` até a renomeação.
