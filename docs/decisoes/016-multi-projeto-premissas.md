# Multi-projeto: as premissas que tornam isso barato

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [009](009-inferencia-de-base.md)

A ferramenta é apartada e opera sobre múltiplos repositórios. Quatro premissas do ambiente:

- Todo projeto é um **sistema cadastrado no Tickio**, com seu próprio id de sistema.
- O **esquema de versionamento é sempre o mesmo** ([009](009-inferencia-de-base.md)) — não
  varia por projeto.
- A **convenção de mensagem é a mesma** (`ch<num>`) para todos.
- **Build está fora** — a ferramenta monta e verifica, não constrói.

## Consequência: quase nada é "config por projeto"

O que define o projeto é qual repositório a ferramenta aponta. O que muda por repo é **uma
linha numa tabela** (nome + id do sistema no Tickio), não config de aplicação. Não há arquivo
de config por projeto, nem hook de build, nem regra de base por repo. Se um dia um projeto
divergir — outro esquema, outra convenção — aí se introduz config; **não antes**. Abstrai-se
no caso que quebra a premissa, não por antecipação.

Como o alvo se separa por projeto: [017](017-corte-por-projeto-na-fonte.md).
