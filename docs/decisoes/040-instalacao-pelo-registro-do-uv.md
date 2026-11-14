# Instalação pelo registro do uv

- **Status:** aceita
- **Data:** 2026-11-14
- **Depende de:** [039](039-versionamento-por-tag.md)

Instalar, atualizar ou remover um plugin exigia remontar à mão o `uv tool install` com o extra
e todos os `--with`, e esquecer um deles desinstalava o plugin em silêncio. Os comandos
`plugin` e `atualizar-motor` montam essa linha pelo usuário.

**A instalação parte do registro do `uv`, sem lista paralela.** O `uv tool` já grava no
`uv-receipt.toml` cada requisito com extra e origem. Uma lista própria do motor divergiria do
registro no primeiro `uv tool install` feito à mão, e não haveria como saber qual das duas
vale. Lendo o registro, `uv tool list` e `plugin listar` concordam por construção, e quem
instalou à mão entra nos comandos sem migrar nada.

**Toda origem fica fixada numa tag ou num commit.** Qualquer ação reinstala o ambiente
inteiro, e uma origem que aponta para uma branch puxaria a versão nova daquele plugin sem
pedido. Fixada, instalar o plugin B não muda o A. A origem ainda solta, de instalações
antigas, é fixada no commit já instalado na próxima ação que de fato reinstala: um "tudo em
dia" não reinstala nada e a deixa como está. Só uma versão nova move uma origem, inclusive a
do motor no `atualizar-motor`. Um commit à frente da última tag conta pela versão do pacote
e não volta para a tag, então atualizar nunca rebaixa. Um plugin publicado por nome só
reinstala com `plugin atualizar <pacote>`: no índice não há como saber se mudou, e contá-lo
em toda atualização em lote impediria o "tudo em dia".

**A checagem de versão nova roda fora do caminho do comando, com cache.** Um `git ls-remote`
por origem custa rede a cada comando. O resultado fica num cache em arquivo de 24 h, e um
processo destacado o renova: o comando nunca espera, e o aviso pode sair só na execução
seguinte. O git roda sem prompt e com prazo curto, porque uma origem privada sem credencial
travaria o processo. Sem resposta, a origem fica sem resultado, sem erro. O mesmo vale para
o `diagnostico`: a peça "Versão" é aviso, nunca falha, e um `[atualizacoes]` inválido a deixa
"não verificada" em vez de derrubá-la. Versão velha não é defeito da instalação.

**A web só mostra.** Reinstalar troca o ambiente de onde o próprio `serve` importa o código, e
o processo que pediu a troca continuaria rodando o código antigo até reiniciar. A web exibe os
plugins, as versões e o aviso com o comando a rodar no terminal.

**Sem checagem para plugin publicado por nome.** O mecanismo é o `git ls-remote` da
[039](039-versionamento-por-tag.md), que não alcança um índice de pacotes. O plugin por nome
instala e atualiza pelo `uv`, só sem o aviso de versão nova.

**Reinstalação que falha preserva a anterior.** O `uv tool install --reinstall` resolve e
constrói tudo antes de trocar o ambiente: conferido com `pyproject.toml` inválido e com
conflito de dependência, e nos dois o motor continuou respondendo. Por isso não há uma
resolução prévia separada. Se o `uv` falhar, o comando imprime a linha completa para
rodar à mão, que é a saída no Windows quando o executável em uso trava a troca.
