"""Hierarquia de erro do motor.

Duas familias, por eixo. As quatro primeiras subclasses sao o vocabulario das
**portas**: e o que um adapter — inclusive um de terceiro — pode levantar, e o
que a suite de contrato assere por tipo em vez de casar substring de mensagem em
portugues. `ErroDeEntrada` (com a subclasse `RepoOcupado`) e `VersaoDesatualizada`
sao do eixo do **operador**, e nao saem de porta nenhuma.

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

    Banco fora do ar, binario do git ausente ou velho demais, HTTP do rastreador ou
    do host de PR. E o unico ramo em que o CLI imprime dica de conserto de
    ambiente (por exemplo, conferir `DATABASE_SQLITE_PATH`).
    """


class RespostaInvalida(MotorError):
    """Respondeu, fora do contrato.

    JSON que nao casa nenhuma forma esperada, data impossivel de parsear, saida
    de git em formato inesperado, coluna com valor fora do dominio. E a
    categoria da issue #42 — o corpo de resposta do rastreador nunca foi
    observado — e a que um adapter de terceiro mais usa.
    """


# -- eixo do operador -------------------------------------------------------


class ErroDeEntrada(MotorError):
    """O que o operador passou nao serve.

    Variavel faltando no .env, flag incompativel, numero de versao malformado,
    campo de formulario invalido na TUI. Nao sai de porta nenhuma.
    """


class RepoOcupado(ErroDeEntrada):
    """Outra operação do motor segura o lock do clone (decisão 032).

    Tem classe própria porque dois chamadores ramificam nela: o daemon responde
    `409 ocupado` em vez do `422` de entrada, e a inscrição sai `PULADA` em vez
    de `ERRO`. `pid` é de quem segura, ou `None` se não deu para ler.
    """

    def __init__(self, nome: str, pid: int | None) -> None:
        detalhe = f" (pid {pid})" if pid is not None else ""
        super().__init__(f"repo {nome} ocupado por outra operação{detalhe}")
        self.pid = pid


class VersaoDesatualizada(MotorError):
    """O arquivo mudou fora da web depois da leitura; recarregue.

    A web ramifica nela para oferecer o recarregar em vez de sobrescrever.
    """


def formatar_com_notas(e: MotorError) -> str:
    """Linha para o operador: contexto (add_note, se houver) antes da causa.

    `__notes__` so aparece em traceback renderizado, e os dois front-ends
    imprimem MotorError como mensagem limpa, nunca traceback — sem isto o
    contexto que os services agregam nas fronteiras (task 7) nao chegava ao
    operador.
    """
    return ": ".join([*getattr(e, "__notes__", []), str(e)])
