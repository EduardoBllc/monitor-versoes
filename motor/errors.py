"""Hierarquia de erro do motor.

Duas familias, por eixo. As quatro primeiras subclasses sao o vocabulario das
**portas**: e o que um adapter — inclusive um de terceiro — pode levantar, e o
que a suite de contrato assere por tipo em vez de casar substring de mensagem em
portugues. A ultima e do eixo do **operador**, e nao sai de porta nenhuma.

Todas herdam de MotorError: `except MotorError` continua pegando tudo, entao
reclassificar um raise nunca muda o comportamento de quem captura generico.

Criterio de admissao, para nao virar enum morto: subclasse nova precisa de um
chamador que ramifica nela OU de uma assercao de contrato que a use.

O que deliberadamente NAO tem classe:

- **Falha generica de passagem** (`git ...: exit status N`). O site do raise nao
  sabe o que falhou, e adivinhar ali e pior que nao classificar. Fica MotorError.
- **Bug de programacao.** Nao e erro do motor: levanta AssertionError, que o
  `main()` ja roteia para o caminho de traceback.
"""


class MotorError(Exception):
    """Base de tudo o que o motor levanta de proposito."""


# -- eixo das portas: o que um adapter pode levantar -------------------------


class RecusaDeInvariante(MotorError):
    """A operacao e ilegal; o dado esta integro.

    Versao liberada e imutavel, versao ja publicada, repo ja cadastrado. Nao e
    "deu errado" — e "nao, e nao vai dar". A distincao contra NaoEncontrado e a
    que a suite de contrato precisa fazer por tipo.
    """


class NaoEncontrado(MotorError):
    """O que foi pedido nao existe.

    Commit, branch, ref, repo, versao, base. Vale tambem no dominio: a classe
    nao e exclusiva de adapter.
    """


class BackendIndisponivel(MotorError):
    """O servico nao respondeu, ou respondeu que nao da.

    Banco fora do ar, binario do git ausente ou velho demais, HTTP do Tickio ou
    do Bitbucket. E o unico ramo em que o CLI imprime dica de conserto de
    ambiente (`docker compose up -d`).
    """


class RespostaInvalida(MotorError):
    """Respondeu, fora do contrato.

    JSON que nao casa nenhuma forma esperada, data impossivel de parsear, saida
    de git em formato inesperado, coluna com valor fora do dominio. E a
    categoria da secao 10 do desenho — o corpo de resposta do Tickio nunca foi
    observado — e a que um adapter de terceiro mais usa.
    """


# -- eixo do operador -------------------------------------------------------


class ErroDeEntrada(MotorError):
    """O que o operador passou nao serve.

    Variavel faltando no .env, flag incompativel, numero de versao malformado,
    campo de formulario invalido na TUI. Nao sai de porta nenhuma.
    """
