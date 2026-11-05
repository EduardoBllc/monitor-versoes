# Inferência de base

- **Status:** aceita
- **Data:** 2026-08-21 (revista em 2026-08-31: o commit gravado é o ponto de corte, não o tip)
- **Depende de:** [001](001-problema-completude-de-commits.md),
  [004](004-estado-descartavel.md), [005](005-alvo-distribuicao-entre-versoes.md),
  [026](026-esquema-e-atribuicao-plugaveis.md)

O código que implementa esta decisão mora no pacote monitor-versoes-vendabem.

A tabela abaixo é o esquema de versão `vendabem` (`[versao] esquema = "vendabem"`), não regra
do núcleo: o padrão é o `semver`, e cada esquema escolhe a ref-base
([026](026-esquema-e-atribuicao-plugaveis.md)). O ponto de corte, mais abaixo, vale para
qualquer esquema.

```
X.0.0        → master
X.Y.0 (Y>0)  → maior X.(Y-1..0).0 existente         (13.7.0 → 13.6.0)
X.Y.Z (Z>0)  → X.Y.(Z-1) se existir, senão X.Y.0    (específica de cliente)
```

Isso resolve a **ref**. O **commit** gravado em `versao.base_commit` é o **ponto de
corte**, não o tip dessa ref:

```
base_commit(V) = merge-base(ref_base, V)   se V já existe como ref
                 tip(ref_base)             se não existe — é o `criar`, e a branch nasce dele agora
```

A ref-base anda depois do corte: o `master` todo dia, e uma ajustada sempre que recebe
hotfix. Resolver só a ref gravava o tip do dia em que o motor viu a versão pela primeira
vez, e essa data vira o `corte` de `liberadas_no_alvo`
([005](005-alvo-distribuicao-entre-versoes.md)) — na `15.0.0` do vendabemweb foram 20 dias
de erro, que tiraram do alvo dez `14.x` liberadas no intervalo e 85 chamados com elas, sem
nada ficar vermelho. Base errada também alarga `base..branch` no nível 3 do oráculo
([003](003-definicao-de-presente.md)) e desloca o pai da simulação de conflito
([013](013-conflito-e-checkpoint.md)).

**`merge-base` que falha não cai para o tip.** Histórico sem ancestral comum diz que a
ref-base está errada; cair para o tip devolveria o mesmo veneno silencioso, que dura a vida
inteira da versão porque a base é gravada uma vez e depois é autoritativa
([004](004-estado-descartavel.md)).
