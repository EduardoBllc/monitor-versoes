# O congelamento é constraint de banco, não `if` de aplicação

- **Status:** aceita
- **Data:** 2026-08-21
- **Depende de:** [004](004-estado-descartavel.md), [010](010-travas-publicada-e-liberada.md)

Uma trigger recusa `INSERT`/`UPDATE`/`DELETE` em `atribuicao`/`atribuicao_commit` que toque
versão com data de liberação preenchida. Dois detalhes que custaram para acertar:

- **A trigger olha `old.versao_id` e `new.versao_id`, não só o novo.** Checando só `new`,
  um `UPDATE ... SET versao_id = <versão aberta> WHERE versao_id = <versão liberada>` passa: o
  novo id cai numa versão aberta, o guard não vê nada de errado, e a linha some em silêncio do
  snapshot congelado.
- **O adapter também recusa, antes de chegar no banco — e não é redundante.** Se os `DELETE`s
  da regravação afetam zero linhas (snapshot já vazio) e a lista nova também vem vazia, nenhum
  `INSERT` dispara a trigger, e o commit passaria em silêncio. A recusa que garante o
  invariante é a do adapter; a trigger é o cinto para quem escreve SQL à mão.

A data de liberação é a **data do commit apontado pela tag**, não `now()` — senão o registro
diria quando o comando rodou, não quando a versão saiu.

**Não existe trigger na tabela `versao` — limitação conhecida, não buraco.** Zerar
`liberada_em` levanta o congelamento e deixa as triggers filhas inertes. Foi deixado assim de
propósito: zerar uma coluna com esse nome não é acidente, é a via de escape para o operador
que sabe o que faz ([004](004-estado-descartavel.md)), e uma trigger ali arriscaria travar o
próprio upsert que registra a versão. O invariante de imutabilidade é forte um degrau só: as
duas tabelas de atribuição são protegidas; a tabela que as trava não é.
