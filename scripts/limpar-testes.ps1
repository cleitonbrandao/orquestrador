#Requires -Version 5.1
<#
.SYNOPSIS
    Apaga os resultados dos testes desta máquina (CSV e respostas brutas em docs\resultados).
    Equivale a scripts/limpar-testes.sh.

.DESCRIPTION
    Só mexe em resultados.csv, relatorio.html e nas pastas <modelo>\<data-hora> criadas pelos testes;
    não apaga mais nada, mesmo que ORQ_RESULTADOS aponte para outra pasta. Não desinstala modelos
    (para isso use /prune) e não pode ser desfeito.

.PARAMETER Modelo
    Apaga só os testes desse modelo. Sem ele, apaga todos.
.PARAMETER Sim
    Não pergunta antes (sem terminal interativo, nada é apagado sem -Sim).

.EXAMPLE
    .\scripts\limpar-testes.ps1
    .\scripts\limpar-testes.ps1 qwen3.5:2b
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Modelo = "",
    [switch]$Sim
)

$RAIZ = Split-Path $PSScriptRoot -Parent
$SAIDA = if ($env:ORQ_RESULTADOS) { $env:ORQ_RESULTADOS } else { Join-Path $RAIZ "docs\resultados" }
$CSV = Join-Path $SAIDA "resultados.csv"
$utf8 = New-Object Text.UTF8Encoding($false)

. (Join-Path $PSScriptRoot "visual.ps1")

if (-not (Test-Path $SAIDA)) { Write-Host "Nenhum resultado salvo ($SAIDA)."; return }

# é pasta de resultados de teste: só tem subpastas com nome data-hora
function Pasta-De-Teste([string]$dir) {
    $filhos = @(Get-ChildItem -LiteralPath $dir -Force)
    if ($filhos.Count -eq 0) { return $false }
    foreach ($f in $filhos) {
        if (-not $f.PSIsContainer -or $f.Name -notmatch '^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$') { return $false }
    }
    return $true
}

function Normalizar([string]$nome) { return ($nome -replace ':latest$', '') }

$linhasCsv = @()
if (Test-Path $CSV) { $linhasCsv = @([IO.File]::ReadAllLines($CSV, $utf8)) }
$dados = @()
if ($linhasCsv.Count -gt 1) { $dados = @($linhasCsv[1..($linhasCsv.Count - 1)] | Where-Object { $_ }) }

$PASTAS = @(); $nLinhas = 0
if (-not $Modelo) {
    $nLinhas = $dados.Count
    foreach ($d in @(Get-ChildItem -LiteralPath $SAIDA -Directory -Force)) {
        if (Pasta-De-Teste $d.FullName) { $PASTAS += $d.FullName }
    }
    $alvo = "todos os testes"
} else {
    $norm = Normalizar $Modelo
    $nomes = @()
    foreach ($l in $dados) {
        $nome = $l.Split(",")[1]
        if ((Normalizar $nome) -eq $norm) { $nLinhas++; if ($nomes -notcontains $nome) { $nomes += $nome } }
    }
    foreach ($nome in $nomes) {
        $d = Join-Path $SAIDA ($nome -replace '[:/\\]', '_')
        if ((Test-Path -LiteralPath $d) -and (Pasta-De-Teste $d)) { $PASTAS += $d }
    }
    $alvo = "os testes de $Modelo"
}

if ($nLinhas -eq 0 -and $PASTAS.Count -eq 0) {
    if ($Modelo) { Write-Host "Nada a apagar para $Modelo." } else { Write-Host "Nada a apagar." }
    return
}

Write-Host ""
$rotulo = if ($Modelo) { $Modelo } else { "todos" }
Pl $PAL.Verm $PAL.Base "$($ICO.Xis)  Limpar testes" $PAL.Escuro $PAL.Ciano $rotulo
Write-Host ""
Write-Host "  Serão apagados ${alvo}: $nLinhas linha(s) no CSV e $($PASTAS.Count) pasta(s) de respostas em $SAIDA."
Write-Host ("  " + (Dim) + "Não pode ser desfeito. Modelos instalados não são afetados (use /prune para isso)." + (Rs))
if (-not $Sim) {
    if ([Console]::IsInputRedirected) { Write-Host "  Sem terminal interativo: nada foi apagado (use -Sim)."; return }
    $r = Read-Host "  Apagar? [s/N]"
    if ($r -notmatch '^[sSyY]$') { Write-Host "  Cancelado. Nada foi apagado."; return }
}

foreach ($d in $PASTAS) { Remove-Item -LiteralPath $d -Recurse -Force }
if (-not $Modelo) {
    Remove-Item -LiteralPath $CSV -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $SAIDA "relatorio.html") -Force -ErrorAction SilentlyContinue
} elseif ($linhasCsv.Count -gt 0) {
    $norm = Normalizar $Modelo
    $mantidas = @($linhasCsv[0])
    foreach ($l in $dados) { if ((Normalizar ($l.Split(",")[1])) -ne $norm) { $mantidas += $l } }
    if ($mantidas.Count -le 1) { Remove-Item -LiteralPath $CSV -Force }
    else { [IO.File]::WriteAllText($CSV, (($mantidas -join "`n") + "`n"), $utf8) }
}
if (-not (Get-ChildItem -LiteralPath $SAIDA -Force)) { Remove-Item -LiteralPath $SAIDA -ErrorAction SilentlyContinue }
Write-Host ("  " + (Fg $PAL.Verde) + $ICO.Check + (Rs) + " apagado: $alvo.")
