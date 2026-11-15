#!/bin/sh
# Instala, atualiza ou desinstala o monitor-versoes. As perguntas e as regras
# ficam no motor (`configurar`, `atualizar-motor`, `desinstalar`); este script só
# prepara o git, o uv e o executável.
#
#   curl -fsSL https://raw.githubusercontent.com/EduardoBllc/monitor-versoes/main/install.sh | sh
#   … | sh -s -- --sem-configurar
#   … | sh -s -- --desinstalar
set -eu

URL_REPO="https://github.com/EduardoBllc/monitor-versoes"
URL_WINDOWS="$URL_REPO#windows"
URL_INSTALADOR_UV="https://astral.sh/uv/install.sh"
PACOTE="monitor-versoes"
EXECUTAVEL="monitor-versoes"
CMD_ATUALIZAR="atualizar-motor"
CMD_CONFIGURAR="configurar"
CMD_DESINSTALAR="desinstalar"
CMD_PLUGIN_INSTALAR="plugin instalar"
# Os mesmos nomes de motor/servico.py e do timer antigo em motor/agendador.py.
SERVICO_SYSTEMD="monitor-versoes-serve.service"
ROTULO_LAUNCHD="monitor-versoes.serve"
PLIST_LAUNCHD="$ROTULO_LAUNCHD.plist"
TIMER_SERVICE="monitor-versoes-inscricoes.service"
TIMER_TIMER="monitor-versoes-inscricoes.timer"
TIMER_PLIST="monitor-versoes.inscricoes.plist"
# Os de CodigoSaida em motor/errors.py.
SAIDA_OK=0
SAIDA_ERRO=1
SAIDA_USO=2
SAIDA_ORIGEM_RECUSADA=3
SAIDA_INTERROMPIDO=130
SISTEMA_LINUX="Linux"
SISTEMA_MACOS="Darwin"

PASTA_SYSTEMD="$HOME/.config/systemd/user"
PASTA_LAUNCHD="$HOME/Library/LaunchAgents"
PATH_ORIGINAL="$PATH"

ok() { printf '✔ %s\n' "$1"; }
aviso() { printf '✖ %s\n' "$1"; }
falha() {
	aviso "$1"
	exit "$SAIDA_ERRO"
}

USO="uso: install.sh [--sem-configurar | --desinstalar]"

tem_terminal() {
	[ -t 1 ] && (: </dev/tty) 2>/dev/null
}

reiniciar_servico() {
	if [ "$sistema" = "$SISTEMA_MACOS" ]; then
		[ -f "$PASTA_LAUNCHD/$PLIST_LAUNCHD" ] || return 0
		alvo="gui/$(id -u)/$ROTULO_LAUNCHD"
		if launchctl kickstart -k "$alvo"; then
			ok "serviço do login reiniciado"
		else
			aviso "não consegui reiniciar o serviço; rode: launchctl kickstart -k $alvo"
		fi
		return 0
	fi
	[ -f "$PASTA_SYSTEMD/$SERVICO_SYSTEMD" ] || return 0
	if systemctl --user restart "$SERVICO_SYSTEMD"; then
		ok "serviço do login reiniciado"
	else
		aviso "não consegui reiniciar o serviço; rode: systemctl --user restart $SERVICO_SYSTEMD"
	fi
}

remover_servicos() {
	if [ "$sistema" = "$SISTEMA_MACOS" ]; then
		for plist in "$PASTA_LAUNCHD/$PLIST_LAUNCHD" "$PASTA_LAUNCHD/$TIMER_PLIST"; do
			[ -f "$plist" ] || continue
			launchctl unload -w "$plist" || true
			rm -f "$plist"
		done
	else
		for unit in "$SERVICO_SYSTEMD" "$TIMER_TIMER"; do
			[ -f "$PASTA_SYSTEMD/$unit" ] || continue
			systemctl --user disable --now "$unit" || true
		done
		rm -f "$PASTA_SYSTEMD/$SERVICO_SYSTEMD" "$PASTA_SYSTEMD/$TIMER_SERVICE" "$PASTA_SYSTEMD/$TIMER_TIMER"
		systemctl --user daemon-reload || true
	fi
	ok "serviços do monitor-versoes removidos"
	printf '%s\n' "Os dados ficaram, nos caminhos padrão:" \
		"  ${XDG_CONFIG_HOME:-$HOME/.config}/monitor-versoes" \
		"  $HOME/.local/share/monitor-versoes" \
		"  ${XDG_CACHE_HOME:-$HOME/.cache}/monitor-versoes" \
		"Um DATABASE_SQLITE_PATH fora do padrão não foi conferido."
}

motor_do_uv() {
	command -v uv >/dev/null 2>&1 && MOTOR="$(uv tool dir --bin)/$EXECUTAVEL"
}

motor_instalado_no_uv() {
	uv tool list 2>/dev/null </dev/null | grep -q "^$PACOTE "
}

desinstalar() {
	MOTOR=""
	motor_do_uv || true
	if [ -n "$MOTOR" ] && [ -x "$MOTOR" ]; then
		if tem_terminal; then
			"$MOTOR" "$CMD_DESINSTALAR" </dev/tty && codigo=$SAIDA_OK || codigo=$?
		else
			"$MOTOR" "$CMD_DESINSTALAR" </dev/null && codigo=$SAIDA_OK || codigo=$?
		fi
	else
		codigo=$SAIDA_ERRO
	fi
	if [ "$codigo" -eq "$SAIDA_INTERROMPIDO" ]; then
		aviso "desinstalação interrompida; nada foi removido pelo script"
		exit "$SAIDA_INTERROMPIDO"
	fi
	# O motor pode estar quebrado (config inválida): sem ele, o script faz o mínimo.
	[ "$codigo" -eq "$SAIDA_OK" ] || remover_servicos
	command -v uv >/dev/null 2>&1 || exit "$SAIDA_OK"
	if motor_instalado_no_uv; then
		uv tool uninstall "$PACOTE" </dev/null || falha "uv tool uninstall $PACOTE falhou; rode-o de novo à mão"
		ok "monitor-versoes e plugins removidos"
	else
		ok "monitor-versoes não estava instalado pelo uv"
	fi
	echo "O uv continua instalado; para removê-lo, veja https://docs.astral.sh/uv/getting-started/installation/#uninstallation"
	exit "$SAIDA_OK"
}

reinstalar() {
	linha="$(uv tool list --show-with --show-extras 2>/dev/null </dev/null | grep "^$PACOTE " || true)"
	uv tool install --reinstall "$REQUISITO" </dev/null || falha "uv tool install --reinstall falhou"
	ok "monitor-versoes reinstalado em $tag"
	reiniciar_servico
	plugins="$(printf '%s\n' "$linha" | sed -n 's/.*\[with: \([^]]*\)\].*/\1/p')"
	[ -n "$plugins" ] || return 0
	printf '%s\n' "A instalação anterior era:" "  $linha" \
		"Os plugins dela não foram mantidos; reinstale com:"
	# Item do uv: `nome git+URL`, `nomefile:///caminho` ou só o nome publicado.
	printf '%s\n' "$plugins" | tr ',' '\n' |
		sed 's/^ *//; s/^.*\(git+\)/\1/; s|^.*file://||' |
		while IFS= read -r origem; do
			printf "  %s %s '%s'\n" "$EXECUTAVEL" "$CMD_PLUGIN_INSTALAR" "$origem"
		done
}

instalar() {
	if ! command -v git >/dev/null 2>&1; then
		if [ "$sistema" = "$SISTEMA_MACOS" ]; then
			instalar_git="xcode-select --install"
		elif command -v apt-get >/dev/null 2>&1; then
			instalar_git="sudo apt install git"
		elif command -v dnf >/dev/null 2>&1; then
			instalar_git="sudo dnf install git"
		elif command -v pacman >/dev/null 2>&1; then
			instalar_git="sudo pacman -S git"
		else
			instalar_git="o gerenciador de pacotes do sistema"
		fi
		falha "git não encontrado. Instale com: $instalar_git"
	fi
	ok "git"

	if ! command -v uv >/dev/null 2>&1; then
		curl -LsSf "$URL_INSTALADOR_UV" | sh
		PATH="${XDG_BIN_HOME:-$HOME/.local/bin}:$PATH"
		command -v uv >/dev/null 2>&1 || falha "não consegui instalar o uv; veja $URL_INSTALADOR_UV"
	fi
	ok "uv"

	# Ordenação numérica sem `sort -V`, que não é POSIX; tag fora de vX.Y.Z fica de fora.
	tag="$(git ls-remote --tags --refs "$URL_REPO" </dev/null |
		sed -n 's|.*refs/tags/v\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\)$|\1|p' |
		sort -t. -k1,1n -k2,2n -k3,3n | tail -n 1)"
	[ -n "$tag" ] || falha "nenhuma release encontrada em $URL_REPO; confira a conexão"
	tag="v$tag"
	REQUISITO="$PACOTE @ git+$URL_REPO@$tag"

	motor_do_uv || falha "o uv não respondeu a \`uv tool dir --bin\`; confira a instalação dele ($URL_INSTALADOR_UV)"
	BIN_UV="$(dirname "$MOTOR")"

	if [ ! -x "$MOTOR" ]; then
		uv tool install "$REQUISITO" </dev/null || falha "uv tool install falhou"
		ok "monitor-versoes $tag instalado"
		reiniciar_servico
	else
		"$MOTOR" "$CMD_ATUALIZAR" --help </dev/null >/dev/null 2>&1 && sonda=$SAIDA_OK || sonda=$?
		if [ "$sonda" -eq "$SAIDA_OK" ]; then
			"$MOTOR" "$CMD_ATUALIZAR" </dev/null && codigo=$SAIDA_OK || codigo=$?
			if [ "$codigo" -eq "$SAIDA_OK" ]; then
				ok "monitor-versoes atualizado"
			elif [ "$codigo" -eq "$SAIDA_ORIGEM_RECUSADA" ]; then
				reinstalar
			else
				falha "$EXECUTAVEL $CMD_ATUALIZAR falhou; corrija o erro acima e rode o script de novo"
			fi
		elif [ "$sonda" -eq "$SAIDA_USO" ]; then
			reinstalar
		else
			# Reinstalar agora perderia os plugins; a config quebrada se corrige antes.
			falha "$MOTOR não roda; corrija o erro (rode \`$MOTOR $CMD_ATUALIZAR --help\`) e rode o script de novo"
		fi
	fi

	case ":$PATH_ORIGINAL:" in
	*":$BIN_UV:"*) ;;
	*) echo "$BIN_UV não está no PATH; rode \`uv tool update-shell\` e abra um terminal novo." ;;
	esac

	if [ "$configurar" = sim ] && tem_terminal; then
		"$MOTOR" "$CMD_CONFIGURAR" </dev/tty || falha "o $CMD_CONFIGURAR não terminou; rode \`$EXECUTAVEL $CMD_CONFIGURAR\` de novo"
	else
		echo "Para escolher as fontes e o início no login, rode: $EXECUTAVEL $CMD_CONFIGURAR"
	fi
}

principal() {
	configurar=sim
	modo=instalar
	for arg in "$@"; do
		case "$arg" in
		--sem-configurar) configurar=nao ;;
		--desinstalar) modo=desinstalar ;;
		*) falha "opção desconhecida: $arg. $USO" ;;
		esac
	done

	sistema="$(uname -s)"
	case "$sistema" in
	"$SISTEMA_LINUX" | "$SISTEMA_MACOS") ;;
	*) falha "sistema $sistema não suportado por este script; no Windows, veja $URL_WINDOWS" ;;
	esac

	"$modo"
}

# Chamada só na última linha: um download truncado pelo `curl | sh` não roda pela metade.
principal "$@"
