# O problema: completude de commits

- **Status:** aceita
- **Data:** 2026-08-21

Uma versão de release é uma **branch**; quando é liberada, o HEAD dela recebe uma **tag**
homônima. Quem cria a tag é o processo de release, externo — a ferramenta apenas **lê** a tag
existente. Três tipos, pelo número:

| Tipo                  | Número  | Sai de                       |
| --------------------- | ------- | ---------------------------- |
| Fechada               | `X.0.0` | `master`                     |
| Ajustada              | `X.Y.0` | fechada ou ajustada anterior |
| Específica de cliente | `X.Y.Z` | qualquer versão anterior     |

A pergunta que a ferramenta responde é sempre a mesma: _"esta versão está com **todos** os
commits que deveria?"_. E ela é difícil por um motivo só: **cherry-pick troca o hash**.
Comparar hashes não responde nada.

O escopo do oráculo é **completude de commits**, não integridade do código resultante — essa
é a skill `validar-versao` (sintaxe Python, validação Django, migrations South faltantes).
Checagens ortogonais: rodar as duas.
