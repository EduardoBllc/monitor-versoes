# Versionamento por tag

- **Status:** aceita
- **Data:** 2026-11-13
- **Depende de:** [030](030-front-end-web-spa-com-dist-versionado.md)

O pacote ficou em `0.1.0` desde o início, e a instalação seguia a `main` por git. Sem
número, não há resposta para "existe atualização?", e o usuário não sabe o que tem
instalado. A versão passa a sair dos commits: os prefixos convencionais (`feat:`, `fix:`)
já usados no repo decidem o salto, e um PR de release mantido pelo release-please acumula
a versão nova e o `CHANGELOG.md`. O dono lança ao mergear esse PR, e o merge cria a tag
`vX.Y.Z` e a GitHub Release.

**Tag e Release, sem PyPI.** O nome do projeto ainda vai mudar. Publicar no PyPI agora
prenderia um nome provisório num índice onde nome não se devolve. A instalação fixa a tag
(`git+…@vX.Y.Z`), e passar a publicar no PyPI depois só acrescenta um passo à release: as
tags continuam valendo.

**Checagem de atualização por `git ls-remote --tags`, não pela API do GitHub.** Um só
mecanismo serve ao motor e aos plugins instalados por git, inclusive o de repositório
privado, com a credencial que o próprio usuário já usa. A API do GitHub não veria o repo
privado sem token e limita as chamadas sem autenticação.

**`0.x` até a renomeação.** Os grupos de entry point (`monitor_versoes.*`) e os caminhos
de config mudam com o nome, e quebram plugins de fora. Em `0.x`, uma quebra sobe só o minor.
A `1.0` é o momento em que a API de plugin passa a ser promessa, e vem depois do nome
definitivo.

**Squash merge, com o título do PR em formato convencional.** O release-please escreve
uma linha de changelog por commit da `main`. Com merge commit, cada commit do branch
entrava: um PR grande virava uma dúzia de itens, inclusive os `fix:` que só corrigiam a
revisão e nunca chegaram a uma versão lançada. Com squash, o PR é um commit só, e o título
dele é a linha do changelog. Os commits por tarefa continuam no PR. O título passa a ser
contrato: o tipo decide se há release e de que tamanho, e o texto é o que o usuário lê.

**O PR de release é aberto com o token do App do agente.** PR aberto pelo `GITHUB_TOKEN`
não dispara outros workflows, e a ruleset da `main` exige os checks do CI: o PR de release
ficaria sem eles. Como o App também é o autor dos PRs do agente, a Revisão IA ignora as
branches `release-please--*`, ou cada atualização do PR de release acordaria o agente para
corrigir um diff que é só número e changelog.
