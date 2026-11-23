# Changelog

## [0.6.0](https://github.com/EduardoBllc/monitor-versoes/compare/v0.5.0...v0.6.0) (2026-11-23)


### ⚠ BREAKING CHANGES

* comando daemon no lugar do serve ([#243](https://github.com/EduardoBllc/monitor-versoes/issues/243))

### Novidades

* comando daemon no lugar do serve ([#243](https://github.com/EduardoBllc/monitor-versoes/issues/243)) ([c5c9b90](https://github.com/EduardoBllc/monitor-versoes/commit/c5c9b90476b77a1b2402bda1ea23a6d32eb053b0))


### Correções

* alerta de commit sumido persiste até o commit voltar ([#242](https://github.com/EduardoBllc/monitor-versoes/issues/242)) ([22e534f](https://github.com/EduardoBllc/monitor-versoes/commit/22e534f406ed8b2207a33cb2217361ae2627e7d9))

## [0.5.0](https://github.com/EduardoBllc/monitor-versoes/compare/v0.4.1...v0.5.0) (2026-11-19)


### ⚠ BREAKING CHANGES

* a fonte de PR bitbucket saiu do pacote do motor; instale com monitor-versoes plugin instalar 'git+https://github.com/EduardoBllc/monitor-versoes#subdirectory=plugins/bitbucket'

### Novidades

* backend da web nova com atualizada_em e listagem com resumo da verificação ([#232](https://github.com/EduardoBllc/monitor-versoes/issues/232)) ([8718fa4](https://github.com/EduardoBllc/monitor-versoes/commit/8718fa4d9339f0cbf3a7ac35e9c48c8732b97317))
* Bitbucket vira plugin em plugins/bitbucket ([9713f6b](https://github.com/EduardoBllc/monitor-versoes/commit/9713f6b61e87fdb156ba5bcacbc1edc0af412dd2))
* consulta aos plugins instalados sem reler os pacotes a cada chamada ([#236](https://github.com/EduardoBllc/monitor-versoes/issues/236)) ([9f44de3](https://github.com/EduardoBllc/monitor-versoes/commit/9f44de3d75ad7b596bdb455076cccfd4ca069d1a))
* fonte de PR do GitLab ([#240](https://github.com/EduardoBllc/monitor-versoes/issues/240)) ([b6f9c63](https://github.com/EduardoBllc/monitor-versoes/commit/b6f9c63d617975e4992023b483beed59b5f52c12))
* **github:** fonte de PR do GitHub ([#239](https://github.com/EduardoBllc/monitor-versoes/issues/239)) ([4df24aa](https://github.com/EduardoBllc/monitor-versoes/commit/4df24aa4a403d74457da0dc6943e7c5abde35876))
* instalador PowerShell e serviço de login no Windows ([#220](https://github.com/EduardoBllc/monitor-versoes/issues/220)) ([588de64](https://github.com/EduardoBllc/monitor-versoes/commit/588de6401c17f7b56c5ccd12bad266d65cc02f3c))
* **web:** interface nova com páginas de início, repo e versão ([#237](https://github.com/EduardoBllc/monitor-versoes/issues/237)) ([4c61729](https://github.com/EduardoBllc/monitor-versoes/commit/4c6172969d7dc676433606f930c16d140ef3a960))


### Correções

* commit fora do clone não é ancestral em vez de derrubar a verificação ([#238](https://github.com/EduardoBllc/monitor-versoes/issues/238)) ([4c37163](https://github.com/EduardoBllc/monitor-versoes/commit/4c3716323c27cad3001400df92b08adc1ce75065))
* reabrir a configuração na web não descarta a seção escolhida ([#227](https://github.com/EduardoBllc/monitor-versoes/issues/227)) ([b92e098](https://github.com/EduardoBllc/monitor-versoes/commit/b92e098744ed49343aea4fd417a562dbfdb433e6))

## [0.4.1](https://github.com/EduardoBllc/monitor-versoes/compare/v0.4.0...v0.4.1) (2026-11-16)


### Correções

* plugin instalar ignora o [tool.uv.sources] dos plugins ([#217](https://github.com/EduardoBllc/monitor-versoes/issues/217)) ([75ef790](https://github.com/EduardoBllc/monitor-versoes/commit/75ef790251a6f537f9a05933d5cce12bbcd70cc3))

## [0.4.0](https://github.com/EduardoBllc/monitor-versoes/compare/v0.3.0...v0.4.0) (2026-11-16)


### Novidades

* instalador sh, configurar interativo e daemon no login ([#212](https://github.com/EduardoBllc/monitor-versoes/issues/212)) ([39c3b14](https://github.com/EduardoBllc/monitor-versoes/commit/39c3b14de398364eabbf63c604215701f6390ad9))
* plugins de fonte de tarefas do GitHub Issues e do GitLab Issues ([#204](https://github.com/EduardoBllc/monitor-versoes/issues/204)) ([c10e9f2](https://github.com/EduardoBllc/monitor-versoes/commit/c10e9f23f93272a8e715424c2441634da7e74ee2))

## [0.3.0](https://github.com/EduardoBllc/monitor-versoes/compare/v0.2.0...v0.3.0) (2026-11-14)


### Novidades

* daemon dispara as inscrições e a web avisa o resultado ([#193](https://github.com/EduardoBllc/monitor-versoes/issues/193)) ([ec0fec2](https://github.com/EduardoBllc/monitor-versoes/commit/ec0fec24b7a10af633219cb57fca6200f66433a4))
* gerenciar plugins e atualizar o motor pelo próprio comando ([#192](https://github.com/EduardoBllc/monitor-versoes/issues/192)) ([97cad19](https://github.com/EduardoBllc/monitor-versoes/commit/97cad191e20d4bc2531643f7f60a3e62a3a04e98))
* plugin de fonte de tarefas do Jira Cloud ([#194](https://github.com/EduardoBllc/monitor-versoes/issues/194)) ([263b3f3](https://github.com/EduardoBllc/monitor-versoes/commit/263b3f3e4a69316fa19a1c033ab906c2e4144e06))

## [0.2.0](https://github.com/EduardoBllc/monitor-versoes/compare/v0.1.0...v0.2.0) (2026-11-13)


### Novidades

* estado das propostas de resolução na web ([#174](https://github.com/EduardoBllc/monitor-versoes/issues/174)) ([e555202](https://github.com/EduardoBllc/monitor-versoes/commit/e5552026dda0021103b7f188007f5f163f11902f))
* IA para sugerir resolução de conflitos ([#174](https://github.com/EduardoBllc/monitor-versoes/issues/174)) ([3c9938a](https://github.com/EduardoBllc/monitor-versoes/commit/3c9938a2df79a515a98ae7540821696e1ab75fef))
* motor roda nativo no Windows ([#136](https://github.com/EduardoBllc/monitor-versoes/issues/136)) ([#184](https://github.com/EduardoBllc/monitor-versoes/issues/184)) ([7567330](https://github.com/EduardoBllc/monitor-versoes/commit/7567330e9644696ac339cc88a6ff9e9bfe1c8eef))
* sugerir resolução no editor de conflito da web ([#174](https://github.com/EduardoBllc/monitor-versoes/issues/174)) ([3593058](https://github.com/EduardoBllc/monitor-versoes/commit/3593058922e5918d9931751aa0476aa5ab39de2d))
* versionamento por tag e release-please ([#146](https://github.com/EduardoBllc/monitor-versoes/issues/146)) ([#183](https://github.com/EduardoBllc/monitor-versoes/issues/183)) ([624e23f](https://github.com/EduardoBllc/monitor-versoes/commit/624e23ff17178a378875972c85a770f118f65d4f))


### Correções

* ajustes da revisão final da sugestão de resolução ([#174](https://github.com/EduardoBllc/monitor-versoes/issues/174)) ([eb6757d](https://github.com/EduardoBllc/monitor-versoes/commit/eb6757d13ca9cf21c1548fd779c1295a4e1cbc38))
* propostas da web sem retrato velho nem estados do arquivo anterior ([#174](https://github.com/EduardoBllc/monitor-versoes/issues/174)) ([17b206f](https://github.com/EduardoBllc/monitor-versoes/commit/17b206f0eddc33c0e7edd8e4b89188a0ac06726e))

## 0.1.0

Primeira versão numerada; o changelog começa aqui.
