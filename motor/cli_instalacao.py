"""Comandos `plugin` e `atualizar-motor`: reinstalam o `uv tool` a partir do registro."""

from __future__ import annotations

import argparse
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import replace
from enum import StrEnum
from itertools import groupby
from pathlib import Path
from urllib.parse import urlsplit

from motor.config import diretorio_cache
from motor.errors import ErroDeEntrada
from motor.instalacao import (
    PACOTE_MOTOR,
    PREFIXO_GIT,
    SHA_COMPLETO,
    UV,
    Origem,
    Registro,
    Requisito,
    TipoOrigem,
    comando_reinstalar,
    fixar_soltos,
    ler_registro,
    normalizar,
    origens_instaladas,
    plugins_instalados,
)
from motor.novidades import (
    ARQUIVO_CACHE,
    TAMANHO_COMMIT_CURTO,
    linha_aviso,
    ls_remote,
    novidade,
    novidades_para_exibir,
    ref_mais_nova,
    rodar_git,
)

COMANDO_PLUGIN = "plugin"
COMANDO_ATUALIZAR_MOTOR = "atualizar-motor"
URL_INSTALAR_UV = "https://docs.astral.sh/uv/getting-started/installation/"
# `git@host:caminho`: o git aceita, o `uv` só aceita como `ssh://git@host/caminho`.
_SCP = re.compile(r"([^@/:]+@[^/:]+):(?!//)(.+)")
_SEPARADORES = ("/", "\\", ":")


class AcaoPlugin(StrEnum):
    LISTAR = "listar"
    INSTALAR = "instalar"
    REMOVER = "remover"
    ATUALIZAR = "atualizar"


def executar_uv(cmd: list[str]) -> int:
    return subprocess.run(cmd, check=False).returncode


def _ref_curta(ref: str | None) -> str:
    if ref and SHA_COMPLETO.fullmatch(ref):
        return ref[:TAMANHO_COMMIT_CURTO]
    return ref or ""


def _descrever(origem: Origem) -> str:
    if origem.tipo is TipoOrigem.GIT:
        return f"git {origem.url}@{_ref_curta(origem.ref or origem.commit)}"
    return str(origem.tipo)


def _listar() -> None:
    todas = novidades_para_exibir()
    for n in todas:
        if n.pacote == PACOTE_MOTOR:
            print(linha_aviso(n))
    novas = {normalizar(n.pacote): n.nova for n in todas}
    for grupo, plugins in groupby(plugins_instalados(), key=lambda p: p.grupo):
        print(grupo.name.lower())
        for p in plugins:
            nova = novas.get(normalizar(p.pacote))
            # O embutido é o motor: a versão nova dele já saiu na primeira linha.
            embutido = p.origem.tipo is TipoOrigem.EMBUTIDO
            seta = f" → {nova}" if nova and not embutido else ""
            print(f"  {p.nome}: {p.pacote} {p.versao}, {_descrever(p.origem)}{seta}")


def _preparar() -> tuple[Registro, dict[str, Origem]]:
    reg = ler_registro()
    if reg is None:
        raise ErroDeEntrada(
            f"o {PACOTE_MOTOR} não está instalado como `uv tool` (checkout de "
            "desenvolvimento ou `uv run`); aqui, plugins e atualização são pelo "
            "próprio git e `uv sync`"
        )
    if shutil.which(UV) is None:
        raise ErroDeEntrada(
            f"`uv` não encontrado no PATH; instale-o: {URL_INSTALAR_UV}"
        )
    origens = origens_instaladas()
    commits = {nome: o.commit for nome, o in origens.items() if o.commit}
    return fixar_soltos(reg, commits), origens


def _de_fora(reg: Registro, pacote: str) -> Requisito:
    if normalizar(pacote) == PACOTE_MOTOR:
        raise ErroDeEntrada(f"{pacote} é embutido no {PACOTE_MOTOR}; não se remove")
    achado = next(
        (p for p in reg.plugins if normalizar(p.nome) == normalizar(pacote)), None
    )
    if achado is None:
        raise ErroDeEntrada(
            f"{pacote} não instalado; veja `{PACOTE_MOTOR} plugin listar`"
        )
    return achado


def _mudancas(antes: Registro, depois: Registro) -> list[str]:
    de = {normalizar(r.nome): r for r in (antes.motor, *antes.plugins)}
    para = {normalizar(r.nome): r for r in (depois.motor, *depois.plugins)}
    linhas = []
    for nome, r in para.items():
        novo = _ref_curta(r.ref) or r.especificador or ""
        if nome not in de:
            linhas.append(
                f"  {r.nome}: instalado ({novo})" if novo else f"  {r.nome}: instalado"
            )
            continue
        velho = _ref_curta(de[nome].ref) or de[nome].especificador or ""
        if velho != novo:
            linhas.append(f"  {r.nome}: {velho} → {novo}")
    linhas += [f"  {r.nome}: removido" for nome, r in de.items() if nome not in para]
    return linhas


def _reinstalar(antes: Registro, cmd: list[str]) -> None:
    if executar_uv(cmd) != 0:
        print(
            "A reinstalação falhou (o erro do uv está acima). Para tentar à mão:\n"
            f"  {shlex.join(cmd)}",
            file=sys.stderr,
        )
        sys.exit(1)
    # O aviso guardado descreve a instalação que acabou de ser trocada.
    (Path(diretorio_cache()) / ARQUIVO_CACHE).unlink(missing_ok=True)
    depois = ler_registro()
    for linha in _mudancas(antes, depois) if depois else []:
        print(linha)
    print(f"Se o `{PACOTE_MOTOR} serve` estiver rodando, reinicie-o.")


def _instalar(reg: Registro, origem: str) -> list[str]:
    url = origem.removeprefix(PREFIXO_GIT)
    if scp := _SCP.fullmatch(url):
        url = f"ssh://{scp[1]}/{scp[2]}"
    if "://" not in url:
        # Nome publicado não tem barra, ":" nem começa com ponto (PEP 508).
        if origem.startswith(".") or any(c in origem for c in _SEPARADORES):
            raise ErroDeEntrada(
                f"{origem}: caminho local não é aceito; instale de uma URL git "
                "(https://… ou git@…) ou pelo nome publicado"
            )
        return comando_reinstalar(
            replace(reg, plugins=(*reg.plugins, Requisito(origem)))
        )
    # O "@" do usuário (git@host) fica no netloc; só o do caminho é ref.
    partes = urlsplit(url)
    caminho, arroba, ref_pedida = partes.path.rpartition("@")
    if arroba:
        url = partes._replace(path=caminho).geturl()
        return [*comando_reinstalar(reg), "--with", f"{PREFIXO_GIT}{url}@{ref_pedida}"]
    saida = ls_remote(url, rodar_git)
    ref = ref_mais_nova(saida) if saida else None
    if ref is None:
        raise ErroDeEntrada(
            f"não consegui ler {url}: sem rede, sem acesso ou não é um repositório git"
        )
    # Sem nome: o `uv` descobre o pacote e o grava no registro.
    return [*comando_reinstalar(reg), "--with", f"{PREFIXO_GIT}{url}@{ref}"]


def _atualizar(
    reg: Registro, origens: dict[str, Origem], nomes: set[str], pedido: bool
) -> None:
    publicados: list[str] = []

    def alvo(r: Requisito) -> Requisito:
        if normalizar(r.nome) not in nomes:
            return r
        if r.git is None:
            # Sem checagem no índice: contá-lo sempre impediria o "tudo em dia".
            if pedido:
                publicados.append(r.nome)
            return r
        saida = ls_remote(r.git, rodar_git)
        if saida is None:
            print(f"Sem resposta de {r.git}; {r.nome} fica como está.", file=sys.stderr)
            return r
        if novidade(r, origens, saida) is None:
            return r
        return replace(r, ref=ref_mais_nova(saida))

    novo = replace(reg, motor=alvo(reg.motor), plugins=tuple(map(alvo, reg.plugins)))
    if novo == reg and not publicados:
        print("Está tudo em dia; nada a reinstalar.")
        return
    extras = [arg for nome in publicados for arg in ("--upgrade-package", nome)]
    _reinstalar(reg, [*comando_reinstalar(novo), *extras])


def plugin(args: argparse.Namespace) -> None:
    acao = AcaoPlugin(args.acao_plugin)
    if acao is AcaoPlugin.LISTAR:
        _listar()
        return
    reg, origens = _preparar()
    match acao:
        case AcaoPlugin.INSTALAR:
            _reinstalar(reg, _instalar(reg, args.origem))
        case AcaoPlugin.REMOVER:
            removido = _de_fora(reg, args.pacote)
            restantes = tuple(p for p in reg.plugins if p is not removido)
            _reinstalar(reg, comando_reinstalar(replace(reg, plugins=restantes)))
        case AcaoPlugin.ATUALIZAR:
            pedidos = [_de_fora(reg, args.pacote)] if args.pacote else reg.plugins
            _atualizar(
                reg,
                origens,
                {normalizar(p.nome) for p in pedidos},
                pedido=bool(args.pacote),
            )


def atualizar_motor(_args: argparse.Namespace) -> None:
    reg, origens = _preparar()
    todos = (reg.motor, *reg.plugins)
    _atualizar(reg, origens, {normalizar(r.nome) for r in todos}, pedido=False)


def adicionar_parsers(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    p_plugin = sub.add_parser(COMANDO_PLUGIN, help="lista, instala e atualiza plugins")
    acoes = p_plugin.add_subparsers(dest="acao_plugin", required=True, metavar="acao")
    acoes.add_parser(AcaoPlugin.LISTAR, help="lista os plugins instalados, por grupo")
    acoes.add_parser(AcaoPlugin.INSTALAR, help="instala um plugin").add_argument(
        "origem",
        help="nome publicado ou URL git (https://… ou git@…), com @ref opcional",
    )
    acoes.add_parser(AcaoPlugin.REMOVER, help="remove um plugin").add_argument(
        "pacote", help="pacote, como o `plugin listar` mostra"
    )
    acoes.add_parser(AcaoPlugin.ATUALIZAR, help="atualiza os plugins").add_argument(
        "pacote", nargs="?", help="só este pacote (padrão: todos os de fora)"
    )
    sub.add_parser(
        COMANDO_ATUALIZAR_MOTOR,
        help="leva o motor à release mais nova e atualiza os plugins",
    )
