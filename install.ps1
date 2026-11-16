<#
.SYNOPSIS
Instala, atualiza ou desinstala o monitor-versoes no Windows.

.DESCRIPTION
As perguntas e as regras ficam no motor (configurar, atualizar-motor,
desinstalar); este script só prepara o git, o uv e o executável.

  irm https://raw.githubusercontent.com/EduardoBllc/monitor-versoes/main/install.ps1 | iex
  & ([scriptblock]::Create((irm https://raw.githubusercontent.com/EduardoBllc/monitor-versoes/main/install.ps1))) -SemConfigurar
  & ([scriptblock]::Create((irm https://raw.githubusercontent.com/EduardoBllc/monitor-versoes/main/install.ps1))) -Desinstalar
#>
[CmdletBinding(DefaultParameterSetName = 'Instalar')]
param(
    [Parameter(ParameterSetName = 'Instalar')][switch]$SemConfigurar,
    [Parameter(ParameterSetName = 'Desinstalar')][switch]$Desinstalar
)
# No `iex` ele é vazio: só pelo `-File` uma falha termina o processo.
$comoArquivo = [bool]$PSCommandPath
# Pelo `iex`, o script roda na sessão do usuário: valem as preferências dela
# (`$ErrorActionPreference` e afins), e as funções e constantes ficam definidas lá.

$URL_REPO = 'https://github.com/EduardoBllc/monitor-versoes'
$URL_INSTALL_SH = 'https://raw.githubusercontent.com/EduardoBllc/monitor-versoes/main/install.sh'
$URL_GIT_WINDOWS = 'https://git-scm.com/download/win'
$URL_INSTALADOR_UV = 'https://astral.sh/uv/install.ps1'
$URL_DESINSTALAR_UV = 'https://docs.astral.sh/uv/getting-started/installation/#uninstallation'
$VAR_URL_INSTALADOR_UV = 'MONITOR_VERSOES_URL_INSTALADOR_UV'
$PASTA_BIN_INSTALADOR_UV = '.local\bin'
$VAR_PRAZO_PROCESSOS = 'MONITOR_VERSOES_PRAZO_PROCESSOS_S'
$INSTALAR_GIT_WINGET = 'winget install --id Git.Git -e'
$EDICAO_CORE = 'Core'
$GIT = 'git'
$UV = 'uv'
$WINGET = 'winget'
$POWERSHELL = 'powershell'
$PACOTE = 'monitor-versoes'
$EXECUTAVEL = 'monitor-versoes'
$CMD_ATUALIZAR = 'atualizar-motor'
$CMD_CONFIGURAR = 'configurar'
$CMD_DESINSTALAR = 'desinstalar'
$CMD_PLUGIN_INSTALAR = 'plugin instalar'
# Os mesmos nomes de motor/servico.py, motor/agendador.py e motor/ajudante.py.
$SCHTASKS = 'schtasks'
$TAREFA_SERVE = 'monitor-versoes-serve'
$TAREFA_INSCRICOES = 'monitor-versoes-inscricoes'
$VAR_AJUDANTE_ESTADO = 'MONITOR_VERSOES_AJUDANTE_ESTADO'
$PASTA_APP = 'monitor-versoes'
$PASTA_CACHE = 'cache'
$PASTA_REINSTALACAO = 'reinstalacao'
$ARQUIVO_RESULTADO = 'resultado'
$RESULTADO_OK = '0'
# O mesmo PRAZO_PROCESSOS_S de motor/ajudante.py.
$PRAZO_PROCESSOS_S = 60
$EXECUTAVEIS_DO_MOTOR = 'monitor-versoes*.exe'
$INTERVALO_MS = 500
# Os de CodigoSaida em motor/errors.py.
$SAIDA_OK = 0
$SAIDA_ERRO = 1
$SAIDA_USO = 2
$SAIDA_ORIGEM_RECUSADA = 3
$SAIDA_INTERROMPIDO = 130
$MARCA_OK = '✔'
$MARCA_FALHA = '✖'

function Test-Comando {
    param([string]$Nome)
    [bool](Get-Command -Name $Nome -CommandType Application -ErrorAction SilentlyContinue)
}

function Get-DirUv {
    param([switch]$Bin)
    $argumentos = @('tool', 'dir')
    if ($Bin) {
        $argumentos += '--bin'
    }
    $pasta = & $UV @argumentos 2> $null
    if ($LASTEXITCODE -eq $SAIDA_OK -and $pasta) {
        return ([string]($pasta | Select-Object -First 1)).Trim()
    }
    return $null
}

# Cópia do Wait-AmbienteLivre de motor/ajudante_windows.ps1: o `iex` não tem
# como importar, e o original mora no ambiente que o uv troca.
function Wait-AmbienteLivre {
    # Devolve os processos que ainda usam o ambiente quando o prazo acaba.
    param(
        [string]$Ambiente,
        [string]$Bin,
        [string]$Executaveis,
        [datetime]$Limite,
        [int]$IntervaloMs
    )
    $raiz = [IO.Path]::GetFullPath($Ambiente).TrimEnd('\') + '\'
    $pastaBin = [IO.Path]::GetFullPath($Bin).TrimEnd('\')
    while ($true) {
        $vivos = @(Get-Process | Where-Object {
                $caminho = $_.Path
                $caminho -and (
                    $caminho.StartsWith($raiz, [StringComparison]::OrdinalIgnoreCase) -or (
                        (Split-Path -Path $caminho -Parent) -eq $pastaBin -and
                        (Split-Path -Path $caminho -Leaf) -like $Executaveis
                    )
                )
            })
        if ($vivos.Count -eq 0 -or (Get-Date) -ge $Limite) {
            return $vivos
        }
        Start-Sleep -Milliseconds $IntervaloMs
    }
}

function Assert-AmbienteLivre {
    # O uv com um processo do ambiente vivo falha com `Access is denied` e deixa o ambiente pela metade.
    $prazo = [Environment]::GetEnvironmentVariable($VAR_PRAZO_PROCESSOS)
    if (-not $prazo) {
        $prazo = $PRAZO_PROCESSOS_S
    }
    $ferramentas = Get-DirUv
    $bin = Get-DirUv -Bin
    if (-not $ferramentas -or -not $bin) {
        return
    }
    $ambiente = Join-Path -Path $ferramentas -ChildPath $PACOTE
    $limite = (Get-Date).AddSeconds([int]$prazo)
    $vivos = @(Wait-AmbienteLivre -Ambiente $ambiente -Bin $bin -Executaveis $EXECUTAVEIS_DO_MOTOR -Limite $limite -IntervaloMs $INTERVALO_MS)
    if ($vivos.Count -gt 0) {
        $lista = ($vivos | ForEach-Object { "  $($_.Id) $($_.Path)" }) -join [Environment]::NewLine
        throw "estes processos ainda usam o monitor-versoes:$([Environment]::NewLine)$lista$([Environment]::NewLine)Feche-os e rode o script de novo."
    }
}

function Test-ServicoLigado {
    & $SCHTASKS /query /tn $TAREFA_SERVE *> $null
    return $LASTEXITCODE -eq $SAIDA_OK
}

function Invoke-UvComServico {
    # O uv não troca o ambiente com o serve vivo (decisão 043).
    param([string[]]$Argumentos, [string]$Falha)
    $ligado = Test-ServicoLigado
    if ($ligado) {
        & $SCHTASKS /end /tn $TAREFA_SERVE *> $null
    }
    try {
        Assert-AmbienteLivre
        & $UV @Argumentos
        if ($LASTEXITCODE -ne $SAIDA_OK) {
            throw $Falha
        }
    } finally {
        if ($ligado) {
            & $SCHTASKS /run /tn $TAREFA_SERVE *> $null
        }
    }
}

function Invoke-Reinstalacao {
    param([string]$Requisito, [string]$Tag)
    $linha = & $UV tool list --show-with --show-extras 2> $null |
        Where-Object { $_ -like "$PACOTE *" } | Select-Object -First 1
    Invoke-UvComServico -Argumentos @('tool', 'install', '--reinstall', $Requisito) -Falha 'uv tool install --reinstall falhou'
    Write-Output "$MARCA_OK monitor-versoes reinstalado em $Tag"
    if (-not ($linha -match '\[with: ([^\]]*)\]')) {
        return
    }
    Write-Output 'A instalação anterior era:'
    Write-Output "  $linha"
    Write-Output 'Os plugins dela não foram mantidos; reinstale com:'
    $doRepo = '^' + [regex]::Escape("git+$URL_REPO") + '(\.git)?@[^#]*#subdirectory=plugins/'
    foreach ($item in ($Matches[1] -split ',')) {
        # Item do uv: `nome git+URL`, `nomefile:///caminho` ou só o nome publicado.
        $origem = $item.Trim() -replace '^.*(git\+)', '$1' -replace '^.*file://', ''
        # Plugin do repo do motor segue a tag do motor; `plugin instalar` recusa outro @ref.
        if ($origem -match $doRepo) {
            $origem = $origem -replace '@[^#]*#', '#'
        }
        Write-Output "  $EXECUTAVEL $CMD_PLUGIN_INSTALAR '$origem'"
    }
}

function Invoke-Atualizacao {
    param([string]$Motor, [string]$Requisito, [string]$Tag)
    & $Motor $CMD_ATUALIZAR --help *> $null
    $sonda = $LASTEXITCODE
    if ($sonda -eq $SAIDA_USO) {
        Invoke-Reinstalacao -Requisito $Requisito -Tag $Tag
        return
    }
    if ($sonda -ne $SAIDA_OK) {
        # Reinstalar agora perderia os plugins; a config quebrada se corrige antes.
        throw "$Motor não roda; corrija o erro (rode ``$Motor $CMD_ATUALIZAR --help``) e rode o script de novo"
    }
    $estado = [IO.Path]::GetTempFileName()
    [Environment]::SetEnvironmentVariable($VAR_AJUDANTE_ESTADO, $estado)
    try {
        & $Motor $CMD_ATUALIZAR
        $codigo = $LASTEXITCODE
        $idAjudante = Get-Content -LiteralPath $estado -Raw
    } finally {
        [Environment]::SetEnvironmentVariable($VAR_AJUDANTE_ESTADO, $null)
        Remove-Item -LiteralPath $estado -ErrorAction SilentlyContinue
    }
    if ($codigo -eq $SAIDA_ORIGEM_RECUSADA) {
        Invoke-Reinstalacao -Requisito $Requisito -Tag $Tag
        return
    }
    if ($codigo -ne $SAIDA_OK) {
        throw "$EXECUTAVEL $CMD_ATUALIZAR falhou; corrija o erro acima e rode o script de novo"
    }
    # Sem PID, o motor não precisou reinstalar; com ele, o ajudante decide o resultado.
    if ($idAjudante) {
        Wait-Process -Id ([int]$idAjudante.Trim()) -ErrorAction SilentlyContinue
        $arquivo = Join-Path -Path $env:LOCALAPPDATA -ChildPath "$PASTA_APP\$PASTA_REINSTALACAO\$ARQUIVO_RESULTADO"
        $resultado = Get-Content -LiteralPath $arquivo -Raw -ErrorAction SilentlyContinue
        if ("$resultado".Trim() -ne $RESULTADO_OK) {
            throw 'a reinstalação não terminou (o motivo está acima); corrija e rode o script de novo'
        }
    }
    Write-Output "$MARCA_OK monitor-versoes atualizado"
}

function Invoke-Instalacao {
    param([switch]$SemConfigurar)
    $pathOriginal = $env:PATH
    if (-not (Test-Comando -Nome $GIT)) {
        if (Test-Comando -Nome $WINGET) {
            throw "git não encontrado. Instale com: $INSTALAR_GIT_WINGET e rode o script de novo num terminal novo"
        }
        throw "git não encontrado. Instale o Git for Windows ($URL_GIT_WINDOWS) e rode o script de novo num terminal novo"
    }
    Write-Output "$MARCA_OK git"

    $urlInstaladorUv = [Environment]::GetEnvironmentVariable($VAR_URL_INSTALADOR_UV)
    if (-not $urlInstaladorUv) {
        $urlInstaladorUv = $URL_INSTALADOR_UV
    }
    if (-not (Test-Comando -Nome $UV)) {
        # Num processo filho: um `exit` do instalador fecharia a janela de quem usou o `iex`.
        & $POWERSHELL -NoProfile -ExecutionPolicy Bypass -Command "Invoke-RestMethod -Uri '$urlInstaladorUv' | Invoke-Expression"
        $binInstalador = $env:UV_INSTALL_DIR
        if (-not $binInstalador) {
            $binInstalador = $env:XDG_BIN_HOME
        }
        if (-not $binInstalador) {
            $binInstalador = Join-Path -Path $env:USERPROFILE -ChildPath $PASTA_BIN_INSTALADOR_UV
        }
        $env:PATH = "$binInstalador;$env:PATH"
        if (-not (Test-Comando -Nome $UV)) {
            throw "não consegui instalar o uv; veja $urlInstaladorUv"
        }
    }
    Write-Output "$MARCA_OK uv"

    $tag = & $GIT ls-remote --tags --refs $URL_REPO |
        ForEach-Object { if ($_ -match 'refs/tags/(v\d+\.\d+\.\d+)$') { $Matches[1] } } |
        Sort-Object -Property { [version]$_.Substring(1) } | Select-Object -Last 1
    if (-not $tag) {
        throw "nenhuma release encontrada em $URL_REPO; confira a conexão"
    }
    Write-Output "$MARCA_OK última release: $tag"
    $requisito = "$PACOTE @ git+$URL_REPO@$tag"

    $bin = Get-DirUv -Bin
    if (-not $bin) {
        throw "o uv não respondeu a ``uv tool dir --bin``; confira a instalação dele ($urlInstaladorUv)"
    }
    $motor = Join-Path -Path $bin -ChildPath $EXECUTAVEL
    if (Test-Comando -Nome $motor) {
        Invoke-Atualizacao -Motor $motor -Requisito $requisito -Tag $tag
    } else {
        Invoke-UvComServico -Argumentos @('tool', 'install', $requisito) -Falha 'uv tool install falhou'
        Write-Output "$MARCA_OK monitor-versoes $tag instalado"
    }

    $noPath = @($pathOriginal -split ';' | ForEach-Object { $_.TrimEnd('\') }) -contains $bin.TrimEnd('\')
    if (-not $noPath) {
        Write-Output "$bin não está no PATH; rode ``uv tool update-shell`` e abra um terminal novo."
    }

    if (-not $SemConfigurar -and -not [Console]::IsInputRedirected -and -not [Console]::IsOutputRedirected) {
        & $motor $CMD_CONFIGURAR
        if ($LASTEXITCODE -ne $SAIDA_OK) {
            throw "o $CMD_CONFIGURAR não terminou; rode ``$EXECUTAVEL $CMD_CONFIGURAR`` de novo"
        }
    } else {
        Write-Output "Para escolher as fontes e o início no login, rode: $EXECUTAVEL $CMD_CONFIGURAR"
    }
}

function Invoke-Desinstalacao {
    $temUv = Test-Comando -Nome $UV
    $codigo = $SAIDA_ERRO
    if ($temUv) {
        $bin = Get-DirUv -Bin
        if ($bin) {
            $motor = Join-Path -Path $bin -ChildPath $EXECUTAVEL
            if (Test-Comando -Nome $motor) {
                & $motor $CMD_DESINSTALAR
                $codigo = $LASTEXITCODE
            }
        }
    }
    if ($codigo -eq $SAIDA_INTERROMPIDO) {
        throw (New-Object -TypeName System.OperationCanceledException -ArgumentList 'desinstalação interrompida; nada foi removido pelo script')
    }
    # O motor pode estar quebrado (config inválida): sem ele, o script faz o mínimo.
    if ($codigo -ne $SAIDA_OK) {
        foreach ($tarefa in @($TAREFA_SERVE, $TAREFA_INSCRICOES)) {
            & $SCHTASKS /end /tn $tarefa *> $null
            & $SCHTASKS /delete /tn $tarefa /f *> $null
        }
        Write-Output "$MARCA_OK tarefas do monitor-versoes removidas"
        $dados = Join-Path -Path $env:LOCALAPPDATA -ChildPath $PASTA_APP
        Write-Output 'Os dados ficaram, nos caminhos padrão:'
        Write-Output "  $(Join-Path -Path $env:APPDATA -ChildPath $PASTA_APP)"
        Write-Output "  $dados"
        Write-Output "  $(Join-Path -Path $dados -ChildPath $PASTA_CACHE)"
        Write-Output 'Um DATABASE_SQLITE_PATH fora do padrão não foi conferido.'
    }
    if (-not $temUv) {
        return
    }
    $instalado = & $UV tool list 2> $null | Where-Object { $_ -like "$PACOTE *" }
    if ($instalado) {
        Assert-AmbienteLivre
        & $UV tool uninstall $PACOTE
        if ($LASTEXITCODE -ne $SAIDA_OK) {
            throw "uv tool uninstall $PACOTE falhou; rode-o de novo à mão"
        }
        Write-Output "$MARCA_OK monitor-versoes e plugins removidos"
    } else {
        Write-Output "$MARCA_OK monitor-versoes não estava instalado pelo uv"
    }
    Write-Output "O uv continua instalado; para removê-lo, veja $URL_DESINSTALAR_UV"
}

# Tudo roda só a partir daqui: um download truncado pelo `irm | iex` não roda pela metade.
$codificacaoAnterior = [Console]::OutputEncoding
$codificacaoTrocada = $false
$codigoSaida = $SAIDA_OK
try {
    try {
        [Console]::OutputEncoding = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false
        $codificacaoTrocada = $true
    } catch {
        # Sem console (saída redirecionada sem janela), a codificação não se troca.
        Write-Verbose -Message "Codificação do console mantida: $($_.Exception.Message)"
    }
    if ($PSVersionTable.PSEdition -eq $EDICAO_CORE -and -not $IsWindows) {
        throw "este script é do Windows; no Linux e no macOS, use: curl -fsSL $URL_INSTALL_SH | sh"
    }
    if ($Desinstalar) {
        Invoke-Desinstalacao
    } else {
        Invoke-Instalacao -SemConfigurar:$SemConfigurar
    }
} catch [System.OperationCanceledException] {
    Write-Output "$MARCA_FALHA $($_.Exception.Message)"
    $codigoSaida = $SAIDA_INTERROMPIDO
} catch {
    Write-Output "$MARCA_FALHA $($_.Exception.Message)"
    $codigoSaida = $SAIDA_ERRO
} finally {
    # Pelo `iex`, a troca valeria para a sessão de quem rodou o script.
    if ($codificacaoTrocada) {
        [Console]::OutputEncoding = $codificacaoAnterior
    }
}
if ($comoArquivo -and $codigoSaida -ne $SAIDA_OK) {
    exit $codigoSaida
}
