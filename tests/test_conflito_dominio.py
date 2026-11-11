import pytest

from motor.domain.conflito import (
    Estagios,
    TipoArquivo,
    marcadores_restantes,
    tipo_do_arquivo,
)

BLOCO_2_VIAS = "antes\n<<<<<<< ours\nA\n=======\nB\n>>>>>>> theirs\n"
BLOCO_3_VIAS = "<<<<<<< ours\nA\n||||||| base\nB\n=======\nC\n>>>>>>> theirs\n"


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
