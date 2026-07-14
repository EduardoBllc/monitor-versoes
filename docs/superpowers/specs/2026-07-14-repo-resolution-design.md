# Design: default --task-source=rest e resolução de --repo via PROJECTS_DIR

## Contexto

CLI `motor` hoje exige `--repo <path>` literal e usa `--task-source=manual` como
default. Objetivo: reduzir digitação no dia a dia (múltiplos repos em
`/Volumes/ESSD/Projetos/`) e tornar `rest` (ClickUp) o modo padrão.

## Mudança 1 — default de --task-source

`motor/__main__.py`: `default="manual"` → `default="rest"` no argumento
`--task-source`. Validação existente (exige `--lista` só quando
`--task-source=manual`) não muda.

## Mudança 2 — resolução de --repo via PROJECTS_DIR

Nova função `_resolver_repo(valor: str) -> str` em `motor/__main__.py`,
chamada logo após o parse dos args e antes de `new_git_subprocess`.

Ordem de resolução:
1. Se `valor` já existe como caminho (absoluto ou relativo ao cwd) → usa
   direto (`os.path.abspath(valor)`).
2. Senão, se env var `PROJECTS_DIR` estiver setada → tenta
   `os.path.join(PROJECTS_DIR, valor)`; se existir, usa esse caminho.
3. Senão → erro em stderr citando os dois caminhos tentados, `sys.exit(1)`.

Exemplo: com `PROJECTS_DIR=/Volumes/ESSD/Projetos/`, `--repo=vendabemweb`
resolve para `/Volumes/ESSD/Projetos/vendabemweb`.

Sem classe/plugin de resolvers — função pura, testável isoladamente com
`tmp_path` e `monkeypatch.setenv`.

## Testes

- `--task-source` sem flag → default vira `rest`.
- `_resolver_repo`: caminho literal existente, resolução via PROJECTS_DIR,
  erro quando nenhum dos dois existe (mensagem cita ambos os caminhos).

## Fora de escopo

- Não valida se o caminho resolvido é de fato um repo git (isso já é
  responsabilidade de `new_git_subprocess`).
- Não adiciona busca recursiva/fuzzy dentro de PROJECTS_DIR — só join direto
  do nome informado.
