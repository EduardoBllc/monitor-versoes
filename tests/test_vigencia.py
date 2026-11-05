from __future__ import annotations

import datetime

from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import (
    Exclusion,
    RepoInfo,
    Verificacao,
    VersaoInfo,
    VersionStatus,
    VersionType,
)
from motor.engine.deps import Deps
from motor.engine.vigencia import (
    VALIDADE_VERIFICACAO,
    impressao_da_verificacao,
    verificacao_vigente,
)

VERSAO = "13.7.0"
TIP = "t1"
HORA = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
UM_SEGUNDO = datetime.timedelta(seconds=1)
A = Exclusion(hash_origem="a", versao_numero=None, motivo="x")
A_NA_VERSAO = Exclusion(hash_origem="a", versao_numero=VERSAO, motivo="x")
B = Exclusion(hash_origem="b", versao_numero=VERSAO, motivo="y")
ENTRADAS = "tickio|bitbucket"


def _montar(
    *,
    agora: datetime.datetime,
    impressao: str | None = None,
    tip: str = TIP,
) -> Deps:
    git = FakeGit()
    git.add_commit(TIP, "", "raiz", HORA)
    git.set_branch(VERSAO, TIP)
    estado = FakeEstado(repos={"r": RepoInfo(nome="r")})
    estado.registrar_versao(
        "r",
        VersaoInfo(
            numero=VERSAO,
            tipo=VersionType.FECHADA,
            base_ref="master",
            base_commit=TIP,
        ),
    )
    estado.gravar_verificacao(
        "r",
        VERSAO,
        Verificacao(
            tip=tip,
            impressao=impressao or impressao_da_verificacao([], {}, ENTRADAS),
            verificado_em=HORA,
            status=VersionStatus(),
        ),
    )
    return Deps(
        git=git,
        tasks=FakeTaskSource(),
        estado=estado,
        repo="r",
        agora=lambda: agora,
        identidade_das_entradas=ENTRADAS,
    )


def test_impressao_muda_quando_exclusao_muda():
    assert impressao_da_verificacao([A], {}, ENTRADAS) != impressao_da_verificacao(
        [B], {}, ENTRADAS
    )


def test_impressao_muda_quando_sem_entrega_muda():
    assert impressao_da_verificacao(
        [], {"1": "m"}, ENTRADAS
    ) != impressao_da_verificacao([], {}, ENTRADAS)


def test_impressao_independe_da_ordem():
    assert impressao_da_verificacao([A, B], {}, ENTRADAS) == impressao_da_verificacao(
        [B, A], {}, ENTRADAS
    )


def test_impressao_aceita_exclusao_com_e_sem_versao():
    assert impressao_da_verificacao(
        [A, A_NA_VERSAO], {}, ENTRADAS
    ) == impressao_da_verificacao([A_NA_VERSAO, A], {}, ENTRADAS)
    assert impressao_da_verificacao(
        [A, A_NA_VERSAO], {}, ENTRADAS
    ) != impressao_da_verificacao([A], {}, ENTRADAS)


def test_vigente_dentro_da_validade_inclusive_no_limite():
    deps = _montar(agora=HORA + VALIDADE_VERIFICACAO)
    assert verificacao_vigente(deps, VERSAO) is not None


def test_vencida_apos_cinco_minutos():
    deps = _montar(agora=HORA + VALIDADE_VERIFICACAO + UM_SEGUNDO)
    assert verificacao_vigente(deps, VERSAO) is None


def test_carimbo_do_futuro_nao_vale():
    assert verificacao_vigente(_montar(agora=HORA - UM_SEGUNDO), VERSAO) is None


def test_tip_diferente_nao_vale():
    assert verificacao_vigente(_montar(agora=HORA, tip="outro"), VERSAO) is None


def test_impressao_diferente_nao_vale():
    assert verificacao_vigente(_montar(agora=HORA, impressao="x"), VERSAO) is None


def test_sem_carimbo_nao_vale():
    deps = _montar(agora=HORA)
    assert verificacao_vigente(deps, "14.0.0") is None
