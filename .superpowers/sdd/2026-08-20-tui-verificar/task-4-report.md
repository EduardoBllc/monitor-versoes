# Relatório — Task 4

## Implementação

- Adicionada `MotorTUI(carregar_repos, carregar_versoes, executar)` em `motor/tui.py`, preservando `RepoOption`, `VersionOption`, descoberta e renderização existentes.
- A composição inclui seleção de repositório/versão, auditoria condicional para tags, resultado rolável, atalhos e controles bloqueados conforme o estado.
- Os três callbacks injetados executam exclusivamente em `@work(thread=True)`; atualizações de widgets retornam pela thread da UI com `call_from_thread`.
- Execuções são bloqueadas enquanto ocupadas, impedindo auditorias concorrentes. `MotorError` é apresentado ao usuário; erros inesperados registram traceback e mostram mensagem genérica.

## Arquivos

- `motor/tui.py`
- `tests/test_tui.py`
- `.superpowers/sdd/2026-08-20-tui-verificar/task-4-report.md`

## Evidências TDD

- RED: `rtk uv run pytest tests/test_tui.py -k 'app_' -q` falhou na coleta com `ImportError: cannot import name 'MotorTUI'`.
- GREEN piloto: `rtk uv run pytest tests/test_tui.py -k 'app_' -q` — `5 passed, 7 deselected`.
- GREEN TUI: `rtk uv run pytest tests/test_tui.py -q` — `12 passed`.
- Suíte completa antes do commit: `rtk uv run pytest -q` — `231 passed, 34 skipped`.
- Checagem de whitespace: `rtk git diff --check` sem saída.

## Adaptações Textual 8.2.8

- `Static.renderable`, usado no código ilustrativo, não existe nesta versão; os testes verificam a propriedade pública `Static.content`.
- A alteração programática de `Select.value` enfileira `Select.Changed`; os testes fazem `await pilot.pause()` antes de aguardar o worker de versões. Sem essa pausa, `wait_for_complete()` pode observar a fila antes do evento iniciar o worker.
- O resultado é aplicado por `_mostrar_resultado()` na thread da UI; isso evita resolver widgets no worker antes de chamar `call_from_thread`.

## Auto-revisão

- Revisados correção, concorrência, erros e limites de thread do diff completo.
- Nenhuma descoberta bloqueante: callbacks de borda estão em workers exclusivos, o botão fica desabilitado durante execução e os testes cobrem sucesso, ambos os tipos de erro, checkout ausente e clique duplicado.
- Sem dependências, abstrações ou arquivos de produção adicionais.

## Preocupações

- Nenhuma conhecida dentro do escopo. A ligação dos callbacks reais à entrada de CLI permanece para a task de integração subsequente.
