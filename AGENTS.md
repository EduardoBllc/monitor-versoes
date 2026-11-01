# monitor-versoes — instruções para agentes

Este arquivo é índice: diz onde cada coisa vive e as regras que valem para toda
a documentação. O conteúdo está nas fontes abaixo, não aqui.

## Onde cada coisa vive

| Conteúdo | Fonte canônica |
| --- | --- |
| Instruções para agentes (índice e regras gerais) | este `AGENTS.md` |
| O quê, como instalar, usar, problemas comuns | [README.md](README.md) |
| Como contribuir | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Ciclo da issue e significado das labels | [CONTRIBUTING.md](CONTRIBUTING.md#ciclo-da-issue) |
| Como o agente processa issues | [.claude/skills/agente/](.claude/skills/agente/SKILL.md) |
| Por quê (decisões) | [docs/decisoes/](docs/decisoes/) — ordem de leitura no `README.md` de lá |
| Padrões de código | [docs/padroes/codigo.md](docs/padroes/codigo.md) |
| Padrões de teste | [docs/padroes/testes.md](docs/padroes/testes.md) |
| Estado mutável, pendências, dívidas | issues do GitHub — nunca em `docs/` |
| Spec e plano de um trabalho | a issue: spec em comentário fixado, plano em comentário |

## Regras

- **Não duplicar.** Cada regra tem uma fonte canônica; os outros lugares linkam
  para ela. Se a informação já existe, aponte — não copie.
- **Documento permanente não descreve o estágio atual** do projeto. O que muda
  com o tempo (o que falta, o que está em andamento, dívida) vai para issue.
- **Trabalho nasce e termina na issue.** Spec e plano em comentários; o PR
  descreve o que foi feito e fecha a issue. `docs/superpowers/` não é versionado.
- **Idioma:** documentação em português com acento; identificadores em português
  sem acento; comentários com acento liberado.
- **Sem `CLAUDE.md`**, em nenhum nível do repo. O Claude Code só lê o `AGENTS.md`
  quando não há `CLAUDE.md`.
- **Antes de dar um trabalho por pronto, rode o portão** (`make check`, ver
  [CONTRIBUTING.md](CONTRIBUTING.md#verificações)) e relate o resultado. Falha
  de ambiente se declara, não se esconde nem se contorna.
- **Código e doc divergem?** Não escolha um lado por reflexo: investigue a
  intenção (histórico, issue, decisão) e corrija o que estiver errado.
