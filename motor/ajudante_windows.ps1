<#
.SYNOPSIS
Reinstala o monitor-versoes pelo uv depois que o motor sai (decisão 043).

.DESCRIPTION
O motor grava antes.json e comando.json em -Pasta e dispara este script fora
do ambiente. O uv só troca o ambiente sem nenhum processo dele vivo; por isso
o script espera o motor sair, encerra o serviço de login, espera o ambiente
ficar livre, roda o uv, mostra as mudanças, sobe o serviço de novo e grava
0 ou 1 em -Pasta\resultado.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Pasta,
    [Parameter(Mandatory = $true)][string]$Motor,
    [Parameter(Mandatory = $true)][string]$Ambiente,
    [Parameter(Mandatory = $true)][string]$Bin,
    [Parameter(Mandatory = $true)][string]$Pids,
    [Parameter(Mandatory = $true)][int]$PrazoProcessos
)

# Os mesmos nomes de motor/agendador.py.
$SCHTASKS = 'schtasks'
$ACAO_ALTERAR = '/change'
$FLAG_DESATIVAR = '/disable'
$FLAG_ATIVAR = '/enable'
$TAREFA_SERVE = 'monitor-versoes-serve'
$COMANDO_POS_REINSTALAR = 'pos-reinstalar'
$ARQUIVO_COMANDO = 'comando.json'
$ARQUIVO_RESULTADO = 'resultado'
$EXECUTAVEIS_DO_MOTOR = 'monitor-versoes*.exe'
$RESULTADO_OK = 0
$RESULTADO_FALHA = 1
$INTERVALO_MS = 500

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

$codificacaoAnterior = [Console]::OutputEncoding
$codificacaoTrocada = $false
try {
    [Console]::OutputEncoding = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false
    $codificacaoTrocada = $true
} catch {
    # Sem console (saída redirecionada sem janela), a codificação não se troca.
    Write-Verbose -Message "Codificação do console mantida: $($_.Exception.Message)"
}

$resultado = $RESULTADO_FALHA
$servicoLigado = $false
# Um prazo só para a espera dos PIDs e a do ambiente.
$limite = (Get-Date).AddSeconds($PrazoProcessos)
try {
    foreach ($id in ($Pids -split ',')) {
        $restante = [Math]::Max(1, [int][Math]::Ceiling(($limite - (Get-Date)).TotalSeconds))
        Wait-Process -Id ([int]$id) -Timeout $restante -ErrorAction SilentlyContinue
    }

    & $SCHTASKS /query /tn $TAREFA_SERVE *> $null
    $servicoLigado = $LASTEXITCODE -eq 0
    if ($servicoLigado) {
        # Desativada, o gatilho de 1 min não sobe o serve no meio do uv.
        & $SCHTASKS $ACAO_ALTERAR /tn $TAREFA_SERVE $FLAG_DESATIVAR *> $null
        & $SCHTASKS /end /tn $TAREFA_SERVE *> $null
    }

    $vivos = @(Wait-AmbienteLivre -Ambiente $Ambiente -Bin $Bin -Executaveis $EXECUTAVEIS_DO_MOTOR -Limite $limite -IntervaloMs $INTERVALO_MS)
    if ($vivos.Count -gt 0) {
        Write-Output 'A reinstalação não começou: estes processos ainda usam o monitor-versoes.'
        foreach ($processo in $vivos) {
            Write-Output "  $($processo.Id) $($processo.Path)"
        }
        Write-Output 'Feche-os e rode o comando de novo.'
    } else {
        # Em duas linhas: no 5.1, o ConvertFrom-Json devolve a lista inteira como um objeto só.
        $json = Get-Content -LiteralPath (Join-Path -Path $Pasta -ChildPath $ARQUIVO_COMANDO) -Raw -Encoding UTF8 | ConvertFrom-Json
        $comando = @($json)
        $argumentos = @($comando | Select-Object -Skip 1)
        $linha = ($comando | ForEach-Object { if ($_ -match '\s') { '"{0}"' -f $_ } else { $_ } }) -join ' '
        try {
            & $comando[0] @argumentos
            $codigoUv = $LASTEXITCODE
        } catch {
            Write-Output $_.Exception.Message
            $codigoUv = $RESULTADO_FALHA
        }
        if ($codigoUv -eq 0) {
            $resultado = $RESULTADO_OK
            & $Motor $COMANDO_POS_REINSTALAR
            if ($LASTEXITCODE -ne 0) {
                Write-Output 'A reinstalação deu certo, mas não deu para listar o que mudou (o erro está acima).'
            }
        } else {
            Write-Output 'A reinstalação falhou (o erro do uv está acima). Para tentar à mão:'
            Write-Output "  $linha"
        }
    }
} finally {
    if ($servicoLigado) {
        & $SCHTASKS $ACAO_ALTERAR /tn $TAREFA_SERVE $FLAG_ATIVAR *> $null
        & $SCHTASKS /run /tn $TAREFA_SERVE *> $null
    }
    Set-Content -LiteralPath (Join-Path -Path $Pasta -ChildPath $ARQUIVO_RESULTADO) -Value $resultado -NoNewline -Encoding Ascii
    if ($codificacaoTrocada) {
        [Console]::OutputEncoding = $codificacaoAnterior
    }
}
