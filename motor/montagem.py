"""Montagem do front-end: transforma ambiente e entrada do operador em `Deps`.

Esta e a unica camada que conhece adapters concretos ao mesmo tempo que conhece
o `Deps`. O CLI e a TUI importam daqui em vez de um do outro, e o engine volta a
ver so `motor.ports`.

**Montar nao e usar.** Nada aqui faz I/O de rede, nem valida credencial, nem
consulta o git: `atualizar --abort` e `reconstruir-estado` recebem as mesmas
fontes e nunca as chamam. Quem cobra credencial e o adapter, na primeira busca.
O plugin da fonte de tarefas nem e carregado aqui: a `FonteDaConfig` o carrega
na primeira busca ou na primeira resolucao da referencia.
Unica excecao deliberada: `garantir_repo`, que cria a linha do repo no estado.
O I/O do `monitor-versoes diagnostico` vive em `motor/diagnostico.py` e nos metodos de verificacao dos adapters, nao aqui.
"""

from __future__ import annotations

import functools
import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from motor.adapters.commitsource.bitbucket import BitbucketPRCommitSource
from motor.adapters.commitsource.chain import ChainCommitSource
from motor.adapters.commitsource.grep import GrepCommitSource
from motor.adapters.estado.engine import criar_engine, garantir_esquema
from motor.adapters.estado.sqlite import Estado
from motor.adapters.git.subprocess import new_git_subprocess
from motor.adapters.notificador.desktop import NotificadorDesktop
from motor.adapters.tasksource.manuallist import ManualList
from motor.config import (
    ConfigProjeto,
    Escolhido,
    carregar_config_repo,
    database_url,
    worktrees_mantidas,
)
from motor.domain.referencia import (
    FonteReferencia,
    Referencia,
    resolver_referencia,
)
from motor.engine.deps import Deps
from motor.errors import ErroDeEntrada, MotorError
from motor.plugins import carregar_plugin
from motor.ports import (
    CommitSource,
    EsquemaVersao,
    EstadoRepo,
    GitRepo,
    Notificador,
    PoliticaAtribuicao,
    TaskSource,
)
from motor.progresso import RelatorProgresso, silencioso
from motor.services.versionamento import (
    BRANCH_VERSAO_PADRAO,
    PRINCIPAL_PADRAO,
    FonteVersionamento,
    Versionamento,
    nomes_sem_esquema,
    versionamento_padrao,
)


@dataclass(frozen=True)
class CredenciaisBitbucket:
    """Token e email da conta do Bitbucket. Vazios desligam a fonte de PR."""

    # repr=False: um log do objeto imprimiria a credencial em claro.
    token: str = field(default="", repr=False)
    email: str = field(default="", repr=False)


@dataclass(frozen=True)
class FonteTasks:
    """Escolha do operador para a fonte de tasks (`--task-source`/`--lista`)."""

    fonte: str = "config"
    lista_manual: str = ""


# defaults dos parametros: os dataclasses sao congelados, entao compartilhar e seguro.
_SEM_BITBUCKET = CredenciaisBitbucket()
_DA_CONFIG = FonteTasks()

#: Grupo de entry points das fontes de tarefas. O nucleo nao registra nenhuma.
GRUPO_TAREFAS = "monitor_versoes.tarefas"
GRUPO_ESQUEMAS = "monitor_versoes.esquemas"
GRUPO_ATRIBUICOES = "monitor_versoes.atribuicoes"


@contextmanager
def abrir_sessao(garantir: bool = True) -> Iterator[Session]:
    """Ciclo de vida do banco: uma engine e uma sessao por comando.

    O CLI e um processo de segundos, entao nao ha o que reaproveitar de um pool
    — a engine nasce aqui, e descartada no fim e a sessao fecha com o `with`.
    Nada disso vive em nivel de modulo: a suite roda sem banco, e uma sessao
    montada no import (ou na construcao do parser) exigiria banco de pe so
    para rodar `--help`.

    `garantir` aplica as migrations se o banco ainda nao tem esquema (primeiro
    uso, sem o usuario rodar `alembic`). O `monitor-versoes diagnostico` passa `False`:
    ele so olha.
    """
    url = database_url()
    if garantir:
        garantir_esquema(url)
    engine = criar_engine(url)
    try:
        with Session(engine) as sessao:
            yield sessao
    finally:
        engine.dispose()


def instanciar_fonte_tarefas(config: ConfigProjeto) -> TaskSource:
    """Carrega o plugin de `[tarefas] fonte` e o instancia.

    O construtor recebe so argumentos nomeados: o `[tarefas]` mesclado e os
    arquivos de config lidos, para que o erro de config cite o arquivo. Erro que
    nao e `MotorError` vira `ErroDeEntrada`: e config apontando para um plugin
    quebrado, nao bug do motor.
    """
    escolhido = config.fonte_tarefas
    if escolhido is None:
        onde = " e ".join(config.arquivos) or "a config"
        raise ErroDeEntrada(
            f"faltando [tarefas] fonte em {onde}; "
            "ou use --task-source manual --lista <arquivo>"
        )
    classe = carregar_plugin(GRUPO_TAREFAS, escolhido.valor)
    try:
        fonte: TaskSource = classe(tarefas=config.tarefas, arquivos=config.arquivos)
    except MotorError:
        raise
    except Exception as e:
        raise ErroDeEntrada(
            f"fonte de tarefas {escolhido.valor!r}: construtor falhou ({e})"
        ) from e
    return fonte


@dataclass
class FonteDaConfig:
    """Fonte de tarefas da config, carregada so por quem a usa.

    Montar nao e usar: um plugin inexistente nao pode derrubar `atualizar
    --abort`. A instancia fica em cache depois da primeira carga que deu certo;
    a que falha nao fica, e a proxima chamada tenta de novo.
    """

    config: ConfigProjeto
    _carregada: TaskSource | None = field(default=None, init=False, repr=False)

    def carregar(self) -> TaskSource:
        if self._carregada is None:
            self._carregada = instanciar_fonte_tarefas(self.config)
        return self._carregada

    def fetch(self, versao: str, /) -> list[str]:
        return self.carregar().fetch(versao)

    def proposta(self) -> Referencia | None:
        """A referencia que o plugin propoe; sem `fonte`, nenhuma."""
        if self.config.fonte_tarefas is None:
            return None
        return _proposta(self.carregar())


def montar_task_source(
    config: ConfigProjeto, *, fonte: str = "config", lista_manual: str = ""
) -> TaskSource:
    """`manual` le a lista do operador; o resto e a fonte de `[tarefas] fonte`.

    Sem carregar o plugin aqui: quem o carrega e a `FonteDaConfig`, na
    primeira busca.
    """
    if fonte == "manual":
        return ManualList(caminho=lista_manual)
    return FonteDaConfig(config)


def _proposta(tasks: TaskSource) -> Referencia | None:
    """A referencia que a fonte de tarefas propoe, se propoe alguma.

    Atributo proprio do plugin, fora da porta: o nucleo nao sabe qual rastreador
    e, e a lista manual, que nao propoe nada, nao precisa declarar ausencia.
    """
    proposta = getattr(tasks, "referencia", None)
    return proposta if isinstance(proposta, Referencia) else None


def _proposta_de(tasks: TaskSource) -> Referencia | None:
    """A proposta, carregando o plugin so se a fonte e a da config."""
    if isinstance(tasks, FonteDaConfig):
        return tasks.proposta()
    return _proposta(tasks)


def _identidade_das_entradas(
    tasks: TaskSource, commits: CommitSource, config: ConfigProjeto
) -> str:
    """O que alimenta a resolucao do alvo: trocar qualquer parte invalida o
    carimbo da verificacao."""
    fonte_tasks = type(tasks).__name__
    if isinstance(tasks, FonteDaConfig):
        escolhido = config.fonte_tarefas
        fonte_tasks = "config:" + ("" if escolhido is None else escolhido.valor)
    elif isinstance(tasks, ManualList):
        try:
            with open(tasks.caminho, "rb") as f:
                fonte_tasks += ":" + hashlib.sha256(f.read()).hexdigest()
        except OSError:
            pass  # a propria ManualList cobra a falta na primeira busca
    return repr(
        (
            fonte_tasks,
            type(commits).__name__,
            _proposta_de(tasks),
            # `[tarefas]` alimenta o plugin da fonte de tarefas.
            sorted(config.tarefas.items()),
            config.padrao_referencia,
            config.piso,
            # Esquema e politica decidem as fontes do alvo; liberacao e branches,
            # quais versoes sao abertas e liberadas.
            [
                None if e is None else e.valor
                for e in (
                    config.esquema,
                    config.atribuicao,
                    config.tag_liberacao,
                    config.branch_versao,
                    config.branch_principal,
                )
            ],
        )
    )


ESQUEMA_PADRAO = "semver"
ATRIBUICAO_PADRAO = "exata"


def _plugin(grupo: str, escolhido: Escolhido | None, padrao: str) -> type:
    """A classe escolhida na config, ou a do padrao embutido."""
    return carregar_plugin(grupo, padrao if escolhido is None else escolhido.valor)


def resolver_versionamento(config: ConfigProjeto) -> Versionamento:
    """Esquema, politica, piso e nomes nas camadas config > esquema > padrao.

    O piso e validado aqui, pelo esquema em uso, e nao na leitura da config: um
    piso que o esquema nao reconhece falha so em quem usa o versionamento.
    """
    esquema: EsquemaVersao = _plugin(GRUPO_ESQUEMAS, config.esquema, ESQUEMA_PADRAO)()
    politica: PoliticaAtribuicao = _plugin(
        GRUPO_ATRIBUICOES, config.atribuicao, ATRIBUICAO_PADRAO
    )()
    piso = config.piso
    if piso is not None:
        try:
            piso = esquema.validar(piso)
        except ErroDeEntrada as e:
            raise ErroDeEntrada(
                f"{config.arquivo_piso}: [versao] piso invalido: {config.piso!r} ({e})"
            ) from e
    return Versionamento(
        esquema=esquema,
        politica=politica,
        piso=piso,
        branch_versao=_camada(
            config.branch_versao, esquema.branch_versao, BRANCH_VERSAO_PADRAO
        ),
        principal=_camada(
            config.branch_principal, esquema.branch_principal, PRINCIPAL_PADRAO
        ),
        tag_liberacao=None
        if config.tag_liberacao is None
        else config.tag_liberacao.valor,
    )


def _camada(config: Escolhido | None, do_esquema: str | None, padrao: str) -> str:
    if config is not None:
        return config.valor
    return padrao if do_esquema is None else do_esquema


# Seis parametros, cinco deles nomeados e com default salvo a referencia: e
# configuracao da montagem, nao uma funcao que faz cinco coisas.
def montar_commit_source(  # noqa: PLR0913
    git: GitRepo,
    *,
    referencia: FonteReferencia,
    bitbucket: CredenciaisBitbucket = _SEM_BITBUCKET,
    estado: EstadoRepo | None = None,
    repo: str = "",
    progresso: RelatorProgresso = silencioso,
    versionamento: FonteVersionamento = versionamento_padrao,
) -> CommitSource:
    """Grep na branch principal e o fallback sempre disponivel. Com token do Bitbucket, a
    PR (merged) vira a fonte primaria: ordem da lista = prioridade.

    O `workspace/repo` do Bitbucket nao e resolvido aqui: sai do
    `git.remote_url("origin")` na primeira busca, dentro do adapter. Resolver
    agora faria todo comando pagar uma chamada de git — e `atualizar --abort`
    num clone sem `origin` passaria a falhar na montagem.
    """

    # Fonte, nao valor: a principal sai do esquema, e resolve-lo aqui faria um
    # plugin inexistente derrubar a montagem, e com ela `atualizar --abort`.
    def ref_principal() -> str:
        return f"origin/{versionamento().principal}"

    grep = GrepCommitSource(
        git=git,
        progresso=progresso,
        referencia=referencia,
        ref_principal=ref_principal,
    )
    # sem estado nao ha indice local de PRs, e a fonte de PR depende dele.
    if not bitbucket.token or estado is None:
        return grep
    pr = BitbucketPRCommitSource(
        token=bitbucket.token,
        email=bitbucket.email,
        git=git,
        progresso=progresso,
        # indice local de PRs + cache de `PR -> commits`: uma varredura
        # incremental no lugar de uma busca por chamado.
        estado=estado,
        repo_estado=repo,
        referencia=referencia,
        ref_principal=ref_principal,
    )
    return ChainCommitSource(sources=[pr, grep])


def montar_notificador() -> Notificador:
    return NotificadorDesktop()


def montar_deps(
    nome_repo: str,
    sessao: Session,
    *,
    tasks: FonteTasks = _DA_CONFIG,
    bitbucket: CredenciaisBitbucket = _SEM_BITBUCKET,
    progresso: RelatorProgresso = silencioso,
) -> Deps:
    """O `Deps` completo, com as quatro portas montadas.

    Token e email vazios caem no ambiente: e assim que a TUI, que nao tem flag
    nenhuma, liga a fonte de PR do Bitbucket.
    """
    config = carregar_config_repo(nome_repo)
    assert config.caminho is not None  # carregar_config_repo sempre o preenche
    git = new_git_subprocess(config.caminho, progresso=progresso)
    estado = Estado(sessao=sessao)
    estado.garantir_repo(nome_repo)
    fonte_tasks = montar_task_source(
        config, fonte=tasks.fonte, lista_manual=tasks.lista_manual
    )

    # Fonte, nao valor: resolver aqui faria a falta de padrao, ou um plugin
    # inexistente, derrubar a montagem, e com ela `atualizar --abort`.
    @functools.cache
    def referencia() -> Referencia:
        return resolver_referencia(
            _proposta_de(fonte_tasks), config.padrao_referencia, config.arquivos
        )

    # Cache: resolvido uma vez por invocacao, na primeira vez que alguem usa.
    versionamento: FonteVersionamento = functools.cache(
        functools.partial(resolver_versionamento, config)
    )
    commit_source = montar_commit_source(
        git,
        referencia=referencia,
        bitbucket=CredenciaisBitbucket(
            token=bitbucket.token or os.environ.get("BITBUCKET_TOKEN", ""),
            email=bitbucket.email or os.environ.get("BITBUCKET_EMAIL", ""),
        ),
        estado=estado,
        repo=nome_repo,
        progresso=progresso,
        versionamento=versionamento,
    )
    return Deps(
        git=git,
        tasks=fonte_tasks,
        estado=estado,
        repo=nome_repo,
        commit_source=commit_source,
        progresso=progresso,
        worktrees_mantidas=worktrees_mantidas(),
        versionamento=versionamento,
        nomes_abort=nomes_sem_esquema(config),
        referencia=referencia,
        # Fonte: calcula-la exige a proposta do plugin, que montar nao carrega.
        identidade_das_entradas=functools.cache(
            functools.partial(
                _identidade_das_entradas, fonte_tasks, commit_source, config
            )
        ),
    )
