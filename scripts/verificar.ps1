#Requires -Version 5.1
<#
.SYNOPSIS
    Verificador de testes do /orquestrar (Windows): roda UM comando, uma vez, e dá o
    veredito por regra (código de saída + padrões de saída), sem LLM.

.DESCRIPTION
    Mesmo contrato do verificar.sh. Saída: COMANDO / CODIGO / SAIDA (últimas 40 linhas) /
    RESULTADO. Sai com 0 = passou, 1 = falhou, 2 = bloqueado.

.EXAMPLE
    .\verificar.ps1 "./vendor/bin/phpunit --filter UserTest"
#>
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Comando
)

$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

$cmd = ($Comando -join " ").Trim()
if (-not $cmd) {
    Write-Host 'Uso: verificar.ps1 "<comando>"'
    exit 2
}
$linhas = 40
if ($env:ORQ_LINHAS_SAIDA) { $linhas = [int]$env:ORQ_LINHAS_SAIDA }

function Relatar {
    param($Codigo, [string[]]$Saida, $Resultado)
    Write-Output "COMANDO: $cmd"
    Write-Output "CODIGO: $Codigo"
    Write-Output "SAIDA:"
    $Saida | Select-Object -Last $linhas | ForEach-Object { Write-Output $_ }
    Write-Output "RESULTADO: $Resultado"
}

# a mesma lista do testador: instalação, banco, containers e remoção nunca rodam aqui
$recusa = '(^|[;&|(])\s*(sudo\s+)?(composer|npm|npx|pnpm|yarn|docker|rm|rmdir|del|remove-item|ri)(\s|$)'
if ($cmd -imatch $recusa -or $cmd -imatch 'artisan\s+(migrate|db:)') {
    Relatar "-" @("comando recusado pelo verificador (instalação, banco, docker ou remoção)") "bloqueado"
    exit 2
}

# processo filho: isola o comando e devolve o código de saída real
$saida = @(& powershell.exe -NoProfile -NonInteractive -Command $cmd 2>&1 | ForEach-Object { "$_" })
$codigo = $LASTEXITCODE

# falha de teste vence o código de saída; "passou" exige código 0 e testes executados
$falha   = '(?m)FAILURES!|ERRORS!|(^|[^0-9])[1-9][0-9]* (failed|failing|errors?)([^a-z]|$)|^FAILED |^--- FAIL|test result: FAILED'
$sucesso = '(?m)OK \([0-9]+ tests?|(^|[^0-9])[1-9][0-9]* passed|^OK( |$)|^ok\s+\S|test result: ok\.|^PASS '
$texto = $saida -join "`n"

if ($texto -cmatch $falha) {
    Relatar $codigo $saida "falhou"
    exit 1
}
if ($codigo -eq 0 -and $texto -cmatch $sucesso) {
    Relatar $codigo $saida "passou"
    exit 0
}
Relatar $codigo $saida "bloqueado"
exit 2
