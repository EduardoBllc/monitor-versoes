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
    [int]$PrazoProcessos = 60
)

$SCHTASKS = 'schtasks'
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
        [int]$Prazo,
        [int]$IntervaloMs
    )
    $raiz = [IO.Path]::GetFullPath($Ambiente).TrimEnd('\') + '\'
    $pastaBin = [IO.Path]::GetFullPath($Bin).TrimEnd('\')
    $limite = (Get-Date).AddSeconds($Prazo)
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
        if ($vivos.Count -eq 0 -or (Get-Date) -ge $limite) {
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
try {
    foreach ($id in ($Pids -split ',')) {
        Wait-Process -Id ([int]$id) -Timeout $PrazoProcessos -ErrorAction SilentlyContinue
    }

    & $SCHTASKS /query /tn $TAREFA_SERVE *> $null
    $servicoLigado = $LASTEXITCODE -eq 0
    if ($servicoLigado) {
        & $SCHTASKS /end /tn $TAREFA_SERVE *> $null
    }

    $vivos = @(Wait-AmbienteLivre -Ambiente $Ambiente -Bin $Bin -Executaveis $EXECUTAVEIS_DO_MOTOR -Prazo $PrazoProcessos -IntervaloMs $INTERVALO_MS)
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
            & $Motor $COMANDO_POS_REINSTALAR
            $resultado = $RESULTADO_OK
        } else {
            Write-Output 'A reinstalação falhou (o erro do uv está acima). Para tentar à mão:'
            Write-Output "  $linha"
        }
    }
} finally {
    if ($servicoLigado) {
        & $SCHTASKS /run /tn $TAREFA_SERVE *> $null
    }
    Set-Content -LiteralPath (Join-Path -Path $Pasta -ChildPath $ARQUIVO_RESULTADO) -Value $resultado -NoNewline -Encoding Ascii
    if ($codificacaoTrocada) {
        [Console]::OutputEncoding = $codificacaoAnterior
    }
}
