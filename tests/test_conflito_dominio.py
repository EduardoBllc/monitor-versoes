import pytest

from motor.domain.conflito import (
    Estagios,
    LadosDoBloco,
    TipoArquivo,
    blocos,
    marcadores_restantes,
    tipo_do_arquivo,
)

BLOCO_2_VIAS = "antes\n<<<<<<< ours\nA\n=======\nB\n>>>>>>> theirs\n"
BLOCO_3_VIAS = "<<<<<<< ours\nA\n||||||| base\nB\n=======\nC\n>>>>>>> theirs\n"
DOIS_BLOCOS = (
    "x\r\n<<<<<<< ours\r\nA1\r\n=======\r\nB1\r\n>>>>>>> theirs\r\nmeio\r\n"
    "<<<<<<< ours\r\nA2\r\n||||||| base\r\nO2\r\n=======\r\nB2\r\n>>>>>>> theirs\r\nfim"
)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("a\nb\n", []),
        (BLOCO_2_VIAS, [2, 4, 6]),
        (BLOCO_3_VIAS, [1, 3, 5, 7]),
        ("========\n", []),
        ("a <<<<<<< b\n", []),
        ("a\r\n=======\r\nb\r\n", [2]),
        (BLOCO_2_VIAS.replace("\n", "\r\n"), [2, 4, 6]),
    ],
)
def test_marcadores_restantes(texto: str, esperado: list[int]) -> None:
    assert marcadores_restantes(texto) == esperado


def _e(
    base: str | None, ours: str | None, theirs: str | None, binario: bool = False
) -> Estagios:
    return Estagios(base=base, ours=ours, theirs=theirs, disco=None, binario=binario)


@pytest.mark.parametrize(
    ("estagios", "esperado"),
    [
        (_e("b", "o", "t"), TipoArquivo.CONTEUDO),
        (_e(None, "o", "t"), TipoArquivo.CONTEUDO),
        (_e("b", None, "t"), TipoArquivo.MODIFICADO_APAGADO),
        (_e("b", "o", None), TipoArquivo.MODIFICADO_APAGADO),
        (_e(None, "o", None), TipoArquivo.OUTRO),
        (_e("b", None, None), TipoArquivo.OUTRO),
        (_e(None, None, None, binario=True), TipoArquivo.OUTRO),
    ],
)
def test_tipo_do_arquivo(estagios: Estagios, esperado: TipoArquivo) -> None:
    assert tipo_do_arquivo(estagios) is esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        (BLOCO_2_VIAS, [LadosDoBloco(ordem=0, base=None, ours="A\n", theirs="B\n")]),
        (BLOCO_3_VIAS, [LadosDoBloco(ordem=0, base="B\n", ours="A\n", theirs="C\n")]),
        (
            DOIS_BLOCOS,
            [
                LadosDoBloco(ordem=0, base=None, ours="A1\r\n", theirs="B1\r\n"),
                LadosDoBloco(ordem=1, base="O2\r\n", ours="A2\r\n", theirs="B2\r\n"),
            ],
        ),
    ],
)
def test_blocos_espelham_os_da_web(texto: str, esperado: list[LadosDoBloco]) -> None:
    assert blocos(texto) == esperado


def test_bloco_sem_fim_nao_conta() -> None:
    assert blocos("<<<<<<< a\nx\n=======\ny\n") == []
