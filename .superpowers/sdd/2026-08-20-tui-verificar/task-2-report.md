# Relatório — Task 2

## Implementação

- Criado `motor/tui.py` com `RepoOption`, `VersionOption`, `descobrir_repos()` e `descobrir_versoes()`.
- `descobrir_repos()` usa a lista canônica ordenada do estado, ignora diretórios sem `.git`/não cadastrados, prefere checkout canônico ao alias e mantém repos ausentes com `caminho=None`.
- `descobrir_versoes()` faz `fetch("origin")`, remove duplicatas, ordena versões numericamente em ordem decrescente e marca tags como liberadas.

## Arquivos

- `motor/tui.py`
- `tests/test_tui.py`

## Evidências TDD

- RED repos: `rtk uv run pytest tests/test_tui.py -q` falhou na coleta com `ModuleNotFoundError: No module named 'motor.tui'`.
- GREEN repos: `3 passed`.
- RED versões: teste direcionado falhou na coleta com `ImportError: cannot import name 'descobrir_versoes'`.
- GREEN final direcionado: `4 passed` no arquivo `tests/test_tui.py`.
- Suíte completa antes do commit: `223 passed, 34 skipped`.

## Auto-revisão

- Assinaturas e valores seguem literalmente o brief.
- O diff está restrito aos dois arquivos de implementação/testes previstos, além deste relatório exigido.
- Nenhuma abstração ou dependência nova foi adicionada.

## Preocupações

- `_chave_versao()` pressupõe versões estritamente no formato `X.Y.Z`, conforme contrato das branches/tags do projeto.
