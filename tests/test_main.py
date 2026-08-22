"""Testes do composition root.

Os testes de ponta a ponta chamam `main()` de verdade e trocam so as tres
bordas de IO (git, sessao do banco, adapter de estado). Um teste que so
importa helpers nao prova nada sobre a entrada: foi assim que um
`Deps(lock_dir=...)` invalido sobreviveu quatro tasks.
"""

from __future__ import annotations

import contextlib
import datetime
import os
from dataclasses import dataclass

import pytest

import motor.__main__ as cli
import motor.montagem as montagem
from motor.__main__ import (
    _build_parser,
    _resolver_repo,
    imprimir_atualizacao,
    imprimir_status,
    main,
)
from motor.adapters.estado.fake import FakeEstado
from motor.adapters.git.fake import FakeGit
from motor.adapters.tasksource.fake import FakeTaskSource
from motor.domain.types import (
    Atribuicao,
    CommitRef,
    RepoInfo,
    VersaoInfo,
    VersionStatus,
    VersionType,
)
from motor.engine.atualizar import AtualizarResult, AtualizarStatus
from motor.engine.deps import Deps
from motor.errors import MotorError

D = datetime.datetime(2026, 1, 1)


# -- parser -------------------------------------------------------------------


def test_task_source_default_e_tickio():
    args = _build_parser().parse_args(["criar", "1.0.0", "--repo", "."])
    assert args.fonte_flag == "tickio"


@pytest.mark.parametrize(("argv", "arquivo"), [
    (["tui"], ".env.development"),
    (["--env", "production", "tui"], ".env"),
])
def test_tui_despacha_sem_abrir_banco_no_cli(monkeypatch, argv, arquivo):
    chamadas: list[str] = []
    ambientes: list[str] = []
    monkeypatch.setattr(
        cli,
        "load_dotenv",
        lambda caminho, **opcoes: ambientes.append(os.path.basename(caminho)),
    )
    monkeypatch.setattr(cli, "_iniciar_tui", lambda: chamadas.append("tui"))
    monkeypatch.setattr(
        cli,
        "abrir_sessao",
        lambda: pytest.fail("o CLI nao deve abrir banco antes da TUI"),
    )

    main(argv)

    assert chamadas == ["tui"]
    assert ambientes == [arquivo]


def test_help_descreve_as_acoes_da_tui():
    ajuda = " ".join(_build_parser().format_help().split())

    assert "consulta, verificacao e atualizacao" in ajuda


@pytest.mark.parametrize(("argv", "arquivo"), [
    (["--help"], ".env.development"),
    (["--env", "production", "--help"], ".env"),
])
def test_main_carrega_o_ambiente_escolhido_antes_do_parser(
    monkeypatch, argv, arquivo
):
    chamadas = []

    def carregar(caminho=None, **opcoes):
        nome = os.path.basename(caminho) if caminho else None
        chamadas.append((nome, opcoes))

    monkeypatch.setattr(cli, "load_dotenv", carregar)

    with pytest.raises(SystemExit) as saida:
        main(argv)

    assert saida.value.code == 0
    assert chamadas == [(arquivo, {"override": True})]


def test_fonte_de_tasks_disponivel_em_todos_os_subcomandos():
    # --task-source/--lista vivem no parser pai 'comum': se ficassem so no
    # 'criar', os outros comandos leriam args.lista_manual inexistente —
    # AttributeError com traceback, nao mensagem.
    for comando in ("verificar", "criar", "atualizar", "reconstruir-estado"):
        args = _build_parser().parse_args(
            [comando, "13.34.0", "--repo", "/tmp",
             "--task-source", "manual", "--lista", "x.txt"]
        )
        assert (args.fonte_flag, args.lista_manual) == ("manual", "x.txt")


def test_reconstruir_estado_esta_no_parser():
    subparsers = _build_parser()._subparsers
    assert subparsers is not None
    acoes = subparsers._group_actions[0].choices
    assert acoes is not None
    assert "reconstruir-estado" in acoes
    assert "reconstruir-lock" not in acoes


def test_comando_desconhecido_sai_com_erro():
    with pytest.raises(SystemExit) as saida:
        main(["inexistente", "13.34.0", "--repo", "/tmp"])
    assert saida.value.code != 0


def test_repo_adicionar_cadastra_sem_checkout_git(monkeypatch, capsys):
    estado = FakeEstado()
    monkeypatch.setattr(cli, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(cli, "PostgresEstado", lambda sessao: estado)

    main(["repo", "adicionar", "backend", "--tickio-sistema-id", "42"])

    assert estado.resolver_repo("backend") == RepoInfo(
        nome="backend", tickio_sistema_id=42
    )
    assert capsys.readouterr().out == "repo 'backend' adicionado\n"


@pytest.mark.parametrize(("argumentos", "mensagem"), [
    (["pasta/backend", "--tickio-sistema-id", "42"], "nome simples"),
    (["backend", "--tickio-sistema-id", "0"], "inteiro positivo"),
])
def test_repo_adicionar_recusa_argumentos_invalidos(argumentos, mensagem, capsys):
    with pytest.raises(SystemExit) as saida:
        _build_parser().parse_args(["repo", "adicionar", *argumentos])

    assert saida.value.code != 0
    assert mensagem in capsys.readouterr().err


def test_nao_existe_flag_de_token_do_tickio():
    # autenticacao e por TICKIO_USER/TICKIO_PASSWORD do ambiente: token colado
    # no .env teria de ser refeito a cada expiracao do JWT.
    with pytest.raises(SystemExit):
        _build_parser().parse_args(
            ["criar", "1.0.0", "--repo", ".", "--tickio-token", "xyz"]
        )


# -- impressao ----------------------------------------------------------------


def test_imprimir_status_mostra_as_ambiguas(capsys):
    # tasks_ambiguas derruba o verde; sem imprimi-las o operador ve
    # "verde: False" com todas as secoes vazias e nenhuma explicacao.
    imprimir_status(VersionStatus(estado_integro=True, tasks_ambiguas=["123456"]))

    saida = capsys.readouterr().out
    assert "123456" in saida
    assert "mais de uma versao" in saida


def test_imprimir_status_aponta_sem_entrega_no_banco(capsys):
    imprimir_status(VersionStatus(estado_integro=True, tasks_sem_commits=["123456"]))

    saida = capsys.readouterr().out
    assert "sem_entrega" in saida
    assert "lock" not in saida  # sem_entrega vive no banco, nao num lock


def test_imprimir_status_de_versao_liberada_marca_o_snapshot(capsys):
    """Spec §4: "se W liberada: imprime snapshot do banco e sai". Sem cabecalho
    e sem chamados a saida sai byte-a-byte igual a de uma versao verde em
    construcao — e um snapshot vazio ainda diria "verde: True", porque all([])
    e True. Esta e a unica superficie de leitura do que so o banco registra.
    """
    imprimir_status(VersionStatus(
        verde=True,
        estado_integro=True,
        liberada_em=datetime.datetime(2026, 8, 7, 14, 22),
        chamados=["255514", "256308"],
    ))

    saida = capsys.readouterr().out
    assert "liberada em 2026-08-07 14:22" in saida
    assert "snapshot congelado, nao recalculado" in saida
    assert "255514, 256308" in saida
    # nao imprime secao que nao foi recalculada: seria mentira dizer "faltantes"
    assert "faltantes" not in saida


def test_imprimir_atualizacao_mostra_as_secoes_vermelhas_do_verificar(capsys):
    """O lote e empurrado mesmo sem verde (todo commit sai de status.faltantes
    depois de filtrar_excluidos, e travar em tasks_sem_commits emperraria o
    fluxo toda vez que um chamado nao tem codigo), mas tasks_ambiguas,
    tasks_sem_commits e commits_sumidos eram calculados e descartados: o run
    imprimia "concluido" e nada mais. commits_sumidos e o pior — historico
    reescrito debaixo de um commit ja aplicado, e o verificar ja sobrescreveu a
    linha de estado que guardava a evidencia.
    """
    imprimir_atualizacao(AtualizarResult(
        status=AtualizarStatus.DONE,
        status_versao=VersionStatus(
            estado_integro=False,
            tasks_ambiguas=["123456"],
            tasks_sem_commits=["999111"],
            commits_sumidos=["deadbeefcafe"],
        ),
    ))

    saida = capsys.readouterr().out
    assert "123456" in saida and "mais de uma versao" in saida
    assert "999111" in saida and "sem_entrega" in saida
    assert "deadbeef" in saida and "commits sumidos" in saida
    # o push aconteceu: o defeito nunca foi o push, era o operador nao saber
    assert "concluido" in saida


# -- main() ponta a ponta -----------------------------------------------------


def _repo_dir(tmp_path, nome: str = "vendabemweb") -> str:
    caminho = tmp_path / nome
    caminho.mkdir()
    return str(caminho)


def _git() -> FakeGit:
    """m0 e a raiz das versoes; a0 so existe no master (logo, faltante)."""
    git = FakeGit()
    git.add_commit("m0", "", "raiz", D)
    git.add_commit("a0", "m0", "ch123456 alfa", D)
    git.set_branch("master", "a0")
    git.set_branch("origin/master", "a0")
    # 13.33.0 e a base inferida da 13.34.0 (§7)
    for versao in ("13.33.0", "13.34.0"):
        git.set_branch(versao, "m0")
    return git


@pytest.fixture
def bordas(monkeypatch):
    """Troca as tres bordas de IO da montagem e devolve os doubles.

    Duas delas moram em `motor.montagem` (git e adapter de estado), que e onde o
    Deps e montado; a sessao ainda e aberta pelo `main()`.

    Todo o resto de main() roda de verdade: parse, resolucao do repo, montagem
    de Deps, escolha da fonte de tasks, despacho e impressao.
    """
    git = _git()
    estado = FakeEstado(
        repos={"vendabemweb": RepoInfo(nome="vendabemweb", tickio_sistema_id=7)}
    )
    for var, valor in (("TICKIO_BASE_URL", "http://tickio.exemplo"),
                       ("TICKIO_USER", "u"), ("TICKIO_PASSWORD", "p")):
        monkeypatch.setenv(var, valor)
    monkeypatch.setattr(montagem, "new_git_subprocess", lambda repo, **_: git)
    monkeypatch.setattr(cli, "abrir_sessao", lambda: contextlib.nullcontext(None))
    monkeypatch.setattr(montagem, "PostgresEstado", lambda sessao: estado)
    return git, estado


def test_verificar_ponta_a_ponta_com_lista_manual(bordas, tmp_path, capsys):
    git, estado = bordas
    lista = tmp_path / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")

    main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path),
          "--task-source", "manual", "--lista", str(lista)])

    saida = capsys.readouterr().out
    assert "verde:" in saida
    # a0 saiu como faltante: Deps foi montada com o repo canonico e o estado,
    # e o verificar rodou de ponta a ponta em cima deles.
    assert "a0" in saida
    assert git.fetched == ["origin"]


def test_verificar_auditar_exibe_faltantes_de_versao_liberada(
    bordas, tmp_path, capsys
):
    git, estado = bordas
    git.tags["13.34.0"] = True
    estado.registrar_versao(
        "vendabemweb",
        VersaoInfo(
            numero="13.34.0",
            tipo=VersionType.AJUSTADA,
            base_ref="13.33.0",
            base_commit="m0",
        ),
    )
    estado.marcar_liberadas("vendabemweb", {"13.34.0": D})
    lista = tmp_path / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")

    main([
        "verificar", "13.34.0", "--repo", _repo_dir(tmp_path),
        "--task-source", "manual", "--lista", str(lista), "--auditar",
    ])

    saida = capsys.readouterr().out
    assert "auditoria da tag 13.34.0" in saida
    assert "faltantes" in saida and "a0" in saida
    assert estado.atribuicoes("vendabemweb", "13.34.0") == []
    assert git.removed_worktrees == []


def test_repo_alias_vira_o_nome_canonico_na_deps(bordas, tmp_path):
    git, estado = bordas
    estado.aliases["vbweb"] = "vendabemweb"
    lista = tmp_path / "lista.txt"
    lista.write_text("", encoding="utf-8")

    main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path, "vbweb"),
          "--task-source", "manual", "--lista", str(lista)])

    # gravou sob o nome canonico, nao sob o basename do diretorio
    assert ("vendabemweb", "13.34.0") in estado.versoes


def test_tickio_recebe_o_sistema_id_do_repo(bordas, tmp_path, monkeypatch):
    monkeypatch.setenv("TICKIO_BASE_URL", "http://tickio.exemplo")
    monkeypatch.setenv("TICKIO_USER", "u")
    monkeypatch.setenv("TICKIO_PASSWORD", "p")

    @dataclass
    class TickioSpy:
        base_url: str
        usuario: str
        senha: str
        sistema_id: int

        def __post_init__(self) -> None:
            construidos.append(self)

        def fetch(self, versao: str) -> list[str]:
            return []

    construidos: list[TickioSpy] = []
    monkeypatch.setattr(montagem, "TickioRest", TickioSpy)

    # sem --task-source: prova que o default do CLI e tickio
    main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert len(construidos) == 1
    # 7 e o tickio_sistema_id da linha `repo`, lida pelo adapter de estado
    assert construidos[0].sistema_id == 7
    assert construidos[0].base_url == "http://tickio.exemplo"
    assert (construidos[0].usuario, construidos[0].senha) == ("u", "p")


def test_reconstruir_estado_ponta_a_ponta(bordas, tmp_path, capsys):
    git, estado = bordas
    # commit na branch da versao sem ch<num> na mensagem: orfao
    git.add_commit("p1", "m0", "ajuste sem numero", D)
    git.set_branch("13.34.0", "p1")

    main(["reconstruir-estado", "13.34.0", "--repo", _repo_dir(tmp_path)])

    saida = capsys.readouterr().out
    assert "status: PENDING_JUDGMENT, orfaos: 1" in saida
    assert "p1" in saida and "sem ch<num> na mensagem" in saida


def test_consulta_ponta_a_ponta_le_snapshot_sem_recalcular(bordas, tmp_path, capsys):
    git, estado = bordas
    git.add_commit("c0ffee123456", "a0", "Título " + "longo " * 30 + "\ncorpo oculto", D)
    estado.registrar_versao(
        "vendabemweb",
        VersaoInfo(numero="13.34.0", tipo=VersionType.AJUSTADA),
    )
    estado.substituir_atribuicoes(
        "vendabemweb",
        "13.34.0",
        [
            Atribuicao(
                chamado="123456",
                marcada="13.34.0",
                estado="aplicado",
                commits=["c0ffee123456", "deadbeefcafe"],
            )
        ],
    )

    main(["consulta", "13.34.0", "--repo", _repo_dir(tmp_path)])

    saida = capsys.readouterr().out
    assert "123456" in saida and "APLICADO" in saida
    assert "c0ffee12" in saida and "…" in saida
    assert "corpo oculto" not in saida
    assert "deadbeef" in saida and "mensagem indisponível" in saida
    assert git.fetched == []


def test_criar_ponta_a_ponta(bordas, tmp_path, capsys):
    lista = tmp_path / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")

    main(["criar", "13.35.0", "--repo", _repo_dir(tmp_path),
          "--task-source", "manual", "--lista", str(lista)])

    saida = capsys.readouterr().out
    assert "cherry-picks aplicados" in saida
    assert "a0" in saida and "concluido" in saida


def test_atualizar_abort_ponta_a_ponta(bordas, tmp_path, capsys, monkeypatch):
    # pina o despacho de --abort: a flag e lida como args.abortar, e o comando
    # nem chega a precisar de fonte de tasks.
    git, _ = bordas
    # Pina o default: o conftest carrega .env.development na coleta, e um
    # WORKTREES_MANTIDAS=0 na maquina de alguem trocaria o resultado aqui.
    monkeypatch.setenv("WORKTREES_MANTIDAS", "")

    main(["atualizar", "13.34.0", "--repo", _repo_dir(tmp_path), "--abort"])

    assert capsys.readouterr().out == "abortado\n"
    # Default de WORKTREES_MANTIDAS (3): o checkout sobrevive ao abort, pra o
    # `atualizar` seguinte na mesma versao nao pagar `worktree add` de novo.
    assert git.removed_worktrees == []


def test_worktrees_mantidas_zero_descarta_o_checkout_no_fim(
    bordas, tmp_path, capsys, monkeypatch
):
    """Ponta a ponta do outro extremo: `WORKTREES_MANTIDAS=0` no ambiente
    chega ate o `worktree_gc` e reproduz o comportamento historico."""
    git, _ = bordas
    monkeypatch.setenv("WORKTREES_MANTIDAS", "0")

    main(["atualizar", "13.34.0", "--repo", _repo_dir(tmp_path), "--abort"])

    assert git.removed_worktrees == ["13.34.0"]


def test_worktrees_mantidas_invalido_sai_1(bordas, tmp_path, caplog, monkeypatch):
    """Erro de config nao pode virar default calado: o comando para, e a
    mensagem diz qual variavel esta errada."""
    monkeypatch.setenv("WORKTREES_MANTIDAS", "tres")

    with pytest.raises(SystemExit) as saida:
        main(["atualizar", "13.34.0", "--repo", _repo_dir(tmp_path), "--abort"])

    assert saida.value.code == 1
    assert "WORKTREES_MANTIDAS invalido: 'tres'" in caplog.text


def test_manual_sem_lista_sai_1(bordas, tmp_path, capsys):
    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path),
              "--task-source", "manual"])

    assert saida.value.code == 1
    assert "--lista" in capsys.readouterr().err


def test_erro_operacional_sai_1_sem_traceback(bordas, tmp_path, monkeypatch, caplog):
    def sem_banco():
        raise MotorError("banco inacessivel na fixture")

    monkeypatch.setattr(cli, "abrir_sessao", sem_banco)

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert saida.value.code == 1
    assert caplog.messages == ["banco inacessivel na fixture"]
    assert "Traceback" not in caplog.text


def test_erro_com_nota_mostra_contexto_e_causa_na_linha(bordas, tmp_path, monkeypatch, caplog):
    """__notes__ so aparece em traceback renderizado, e MotorError nunca
    renderiza traceback aqui — sem concatenar a nota na linha visivel, o
    contexto que os services agregam via add_note (task 7) se perdia por
    completo para o operador.
    """
    def sem_banco():
        erro = MotorError("Tickio respondeu 503")
        erro.add_note("buscando tasks da versao 13.34.0")
        raise erro

    monkeypatch.setattr(cli, "abrir_sessao", sem_banco)

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert saida.value.code == 1
    assert "buscando tasks da versao 13.34.0" in caplog.text
    assert "Tickio respondeu 503" in caplog.text


def test_bug_sai_1_com_traceback(bordas, tmp_path, monkeypatch, caplog):
    def bug():
        raise RuntimeError("isto e um bug")

    monkeypatch.setattr(cli, "abrir_sessao", bug)

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert saida.value.code == 1
    assert "Traceback" in caplog.text


def test_main_nao_repovoa_variavel_que_o_teste_apagou(bordas, tmp_path, monkeypatch,
                                                      caplog):
    """Pina a guarda estrutural do "sem rede" (fixture _sem_dotenv_dentro_do_main
    no conftest): sem ela, o load_dotenv() de dentro do main() traz de volta toda
    variavel que o teste apagou — foi assim que um teste de credencial ausente
    saiu para o host real do Tickio na Task 12.

    """
    # Pin estrutural, nao comportamental: `load_dotenv()` procura o .env a partir
    # do arquivo que a chama, nao da CWD, entao nao da para plantar um .env de
    # teste e observar o efeito. E `main()` faz `if load_dotenv: load_dotenv()`,
    # logo "a guarda esta instalada" E o contrato inteiro. Antes a assercao era
    # so comportamental e ficava vazia em maquina sem .env — em clone novo ou CI
    # a guarda podia ser apagada sem nada ficar vermelho, que e exatamente a
    # classe de falha que ela existe para fechar.
    assert cli.load_dotenv is None, (
        "a fixture _sem_dotenv_dentro_do_main nao desligou o load_dotenv() do "
        "main(): variavel apagada por um teste volta do .env de verdade e o run "
        "sai para a rede"
    )

    monkeypatch.delenv("TICKIO_USER", raising=False)

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert saida.value.code == 1
    assert "faltando no .env: TICKIO_USER" in caplog.text
    assert "TICKIO_USER" not in os.environ, "load_dotenv() rodou dentro do main()"


def test_tickio_sem_variavel_no_env_nomeia_a_que_falta(bordas, tmp_path, monkeypatch,
                                                       caplog):
    # vazio e nao delenv: a variavel ausente e o outro teste; aqui o que importa
    # e a mensagem nomear a variavel.
    monkeypatch.setenv("TICKIO_BASE_URL", "")

    with pytest.raises(SystemExit) as saida:
        main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path)])

    assert saida.value.code == 1
    # o contexto ("buscando tasks da versao ...") chega na linha via nota
    # (formatar_com_notas), nao mais embutido na mensagem do erro; o que
    # importa aqui e a variavel nomeada, em vez da reclamacao de protocolo do
    # httpx.
    assert "faltando no .env: TICKIO_BASE_URL" in caplog.text


@pytest.mark.parametrize("comando,esperado", [
    (["atualizar", "13.34.0", "--abort"], "abortado"),
    (["reconstruir-estado", "13.34.0"], "status: DONE"),
])
def test_comando_que_nao_busca_tarefa_roda_sem_credencial_do_tickio(
    bordas, tmp_path, monkeypatch, capsys, comando, esperado
):
    """`atualizar --abort` e `reconstruir-estado` montam a fonte de tarefas mas
    nunca chamam fetch. Sao os comandos de recuperacao: exigir TICKIO_USER/
    TICKIO_PASSWORD (vazios no .env.example) travaria justamente o comando que
    se usa quando algo ja esta quebrado.
    """
    # "" e nao delenv: o que se testa aqui e credencial vazia, o caso do
    # .env.example — nao a variavel ausente.
    for var in ("TICKIO_USER", "TICKIO_PASSWORD"):
        monkeypatch.setenv(var, "")

    main([*comando, "--repo", _repo_dir(tmp_path)])

    # chegou ao fim do comando, nao so deixou de reclamar
    assert esperado in capsys.readouterr().out


def test_lista_manual_nao_exige_variavel_do_tickio(bordas, tmp_path, monkeypatch,
                                                   capsys):
    # TICKIO_USER/TICKIO_PASSWORD sao vazios no .env.example: quem usa --lista
    # nao pode ser obrigado a preencher.
    for var in ("TICKIO_BASE_URL", "TICKIO_USER", "TICKIO_PASSWORD"):
        monkeypatch.setenv(var, "")
    lista = tmp_path / "lista.txt"
    lista.write_text("123456\n", encoding="utf-8")

    main(["verificar", "13.34.0", "--repo", _repo_dir(tmp_path),
          "--task-source", "manual", "--lista", str(lista)])

    assert "verde:" in capsys.readouterr().out


def test_repr_de_deps_nao_vaza_credencial_do_bitbucket():
    # a credencial mora dentro do CommitSource, e o repr default de Deps
    # atravessa o ChainCommitSource ate ela: um dump de deps sob --debug
    # imprimiria tudo em claro se o adapter nao tivesse repr=False.
    deps = Deps(
        git=_git(),
        tasks=FakeTaskSource(),
        estado=FakeEstado(),
        repo="r",
        commit_source=montagem.montar_commit_source(
            _git(), token="tok123", email="dev@x.com"
        ),
    )

    assert "tok123" not in repr(deps)
    assert "dev@x.com" not in repr(deps)


# -- _resolver_repo -----------------------------------------------------------


def test_resolver_repo_caminho_literal(tmp_path):
    alvo = tmp_path / "meurepo"
    alvo.mkdir()
    assert _resolver_repo(str(alvo)) == str(alvo)


def test_resolver_repo_via_projects_dir(tmp_path, monkeypatch):
    projetos = tmp_path / "projetos"
    (projetos / "vendabemweb").mkdir(parents=True)
    monkeypatch.setenv("PROJECTS_DIR", str(projetos))

    resolvido = _resolver_repo("vendabemweb")

    assert resolvido == os.path.join(str(projetos), "vendabemweb")


def test_resolver_repo_tira_a_barra_final(tmp_path, monkeypatch):
    # tab-completion do shell manda "vendabemweb/", e o basename disso e "" —
    # o nome do repo e a chave do estado inteiro.
    projetos = tmp_path / "projetos"
    (projetos / "vendabemweb").mkdir(parents=True)
    monkeypatch.setenv("PROJECTS_DIR", str(projetos))

    assert os.path.basename(_resolver_repo("vendabemweb/")) == "vendabemweb"


def test_resolver_repo_nao_encontrado(tmp_path, monkeypatch):
    monkeypatch.delenv("PROJECTS_DIR", raising=False)
    with pytest.raises(SystemExit):
        _resolver_repo(str(tmp_path / "nao-existe"))


def test_imprimir_status_nomeia_os_chamados_culpados_pelo_conflito(capsys):
    """"[CONFLITANTE]" sozinho diz que o commit trava, nao de que alteracao ele
    depende. Nomear os chamados e o que permite decidir entre puxar a
    dependencia para esta versao ou devolver o chamado.
    """
    faltante = CommitRef(hash_origem="a0a0a0a0a0", chamado="255514", msg="ch255514 alfa")
    imprimir_status(VersionStatus(
        estado_integro=True,
        faltantes=[faltante],
        conflitantes=[faltante],
        conflito_causado_por={"a0a0a0a0a0": ["255101", "254800"]},
    ))

    saida = capsys.readouterr().out
    assert "CONFLITANTE" in saida
    assert "ch255101" in saida
    assert "ch254800" in saida


def test_imprimir_status_sem_culpados_mantem_a_tag_seca(capsys):
    faltante = CommitRef(hash_origem="a0a0a0a0a0", chamado="255514", msg="ch255514 alfa")
    imprimir_status(VersionStatus(
        estado_integro=True,
        faltantes=[faltante],
        conflitantes=[faltante],
    ))

    saida = capsys.readouterr().out
    assert "[CONFLITANTE]" in saida
    assert "depende" not in saida
