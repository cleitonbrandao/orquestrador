#Requires -Version 5.1
<#
.SYNOPSIS
    Desinstala do Ollama os modelos que reprovaram nos testes (docs\resultados\resultados.csv).
    Equivale a scripts/podar-modelos.sh.

.DESCRIPTION
    Reprovado = melhor teste do modelo com qualidade < mínimo OU tok/s < mínimo.
    Nunca são candidatos: modelos usados no opencode.json, o modelo de embeddings do kb, modelos que
    não geram texto e modelos sem teste salvo. Pergunta antes de remover cada um; sem terminal
    interativo não remove nada. O histórico no CSV é mantido.

.PARAMETER DryRun
    Só mostra o que seria removido.
.PARAMETER MinQualidade
    Reprova com menos de N pontos de qualidade, de 60 (padrão 30).
.PARAMETER MinToks
    Reprova abaixo de N tok/s de geração (padrão 8).

.EXAMPLE
    .\scripts\podar-modelos.ps1 -DryRun
    .\scripts\podar-modelos.ps1 -MinQualidade 25 -MinToks 5
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [double]$MinQualidade = 30,
    [double]$MinToks = 8
)

$RAIZ = Split-Path $PSScriptRoot -Parent
$RELATORIO = Join-Path $PSScriptRoot "relatorio.py"
$inv = [Globalization.CultureInfo]::InvariantCulture

. (Join-Path $PSScriptRoot "visual.ps1")
. (Join-Path $PSScriptRoot "limpar-ram.ps1")

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { Write-Host "faltando: ollama" -ForegroundColor Red; exit 1 }
if (-not (Get-Python)) { Write-Host "python não encontrado." -ForegroundColor Red; exit 1 }
if (-not (Test-Ollama)) { Write-Host "Ollama não responde em $($script:API)." -ForegroundColor Red; exit 1 }

function Tamanho-Legivel([double]$bytes) {
    if ($bytes -ge 1e9) { return ("{0} GB" -f ($bytes / 1e9).ToString("0.0", $inv)) }
    return ("{0} MB" -f [int]($bytes / 1e6))
}

# modelos usados nas configs do OpenCode (ollama/<nome>)
function Modelos-Em-Uso {
    $arquivos = @(
        (Join-Path $RAIZ "opencode\opencode.json"),
        (Join-Path $HOME ".config\opencode\opencode.json")
    )
    if ($env:XDG_CONFIG_HOME) { $arquivos += (Join-Path $env:XDG_CONFIG_HOME "opencode\opencode.json") }
    $achados = @()
    foreach ($f in $arquivos) {
        if (-not (Test-Path $f)) { continue }
        $texto = [IO.File]::ReadAllText($f, [Text.Encoding]::UTF8)
        foreach ($m in [regex]::Matches($texto, '"model"\s*:\s*"ollama/([^"]+)"')) { $achados += $m.Groups[1].Value }
    }
    return ($achados | Sort-Object -Unique)
}

# blob (linha FROM do modelfile): quem tem o mesmo blob compartilha os pesos
function Blob-De([string]$modelo) {
    $linha = ollama show $modelo --modelfile 2>$null | Where-Object { $_ -match '^FROM ' } | Select-Object -First 1
    if ($linha) { return ($linha -replace '^FROM\s+', '') }
    return ""
}

function Disco-Livre-MB {
    $dir = if ($env:OLLAMA_MODELS) { $env:OLLAMA_MODELS } else { Join-Path $HOME ".ollama" }
    try {
        $letra = (Split-Path $dir -Qualifier).TrimEnd(":")
        return [int]((Get-PSDrive -Name $letra).Free / 1MB)
    } catch { return 0 }
}

$tags = Invoke-Ollama "/api/tags" -Get -Timeout 5
$INSTALADOS = @($tags.models | ForEach-Object { [string]$_.name })
$TAM = @{}
foreach ($m in @($tags.models)) { $TAM[[string]$m.name] = [double]$m.size }

$saidaPy = @(Invoke-Py $RELATORIO reprovados --min-qualidade ($MinQualidade.ToString($inv)) --min-toks ($MinToks.ToString($inv)) --instalados ($INSTALADOS -join ","))
$USO = @(Modelos-Em-Uso)
$EMBED = if ($env:ORQ_EMBED_MODEL) { $env:ORQ_EMBED_MODEL } else { "nomic-embed-text" }

$CAND = @(); $PROT = @()
$Qm = @{}; $Tm = @{}; $Motivo = @{}; $Libera = @{}; $Compart = @{}
foreach ($linha in $saidaPy) {
    if (-not $linha) { continue }
    $c = ([string]$linha) -split "`t"
    if ($c.Count -lt 4) { continue }
    $nome = $c[0]
    $Qm[$nome] = $c[1]; $Tm[$nome] = $c[2]; $Motivo[$nome] = $c[3]
    $protMotivo = ""
    foreach ($u in $USO) { if (($u -replace ':latest$', '') -eq ($nome -replace ':latest$', '')) { $protMotivo = "usado no opencode.json" } }
    if (($EMBED -replace ':latest$', '') -eq ($nome -replace ':latest$', '')) { $protMotivo = "modelo de embeddings do kb" }
    if (-not (GeraTexto $nome)) { $protMotivo = "não gera texto" }
    if ($protMotivo) { $PROT += ,@($nome, $protMotivo); continue }
    # pesos compartilhados com outro modelo instalado: remover não libera espaço
    $meu = Blob-De $nome
    $Libera[$nome] = $TAM[$nome]
    foreach ($o in $INSTALADOS) {
        if ($o -eq $nome) { continue }
        if ($meu -and ((Blob-De $o) -eq $meu)) { $Libera[$nome] = 0; $Compart[$nome] = $o; break }
    }
    $CAND += $nome
}

Write-Host ""
Pl $PAL.Verm $PAL.Base "$($ICO.Xis)  Modelos reprovados" $PAL.Escuro $PAL.Ciano "qualidade < $MinQualidade/60 ou < $MinToks tok/s"
Write-Host ""
if ($CAND.Count -eq 0) {
    Write-Host "  Nenhum modelo instalado reprovou (ou todos os reprovados estão protegidos)."
} else {
    Write-Host ("  " + (Neg) + ("{0,-26} {1,9} {2,7}  {3,-9}  {4}" -f "MODELO", "QUALID.", "TOK/S", "TAMANHO", "MOTIVO") + (Rs))
    foreach ($nome in $CAND) {
        Write-Host ("  {0,-26} {1,6}/60 {2,7}  {3,-9}  {4}{5}{6}" -f $nome, $Qm[$nome], $Tm[$nome], (Tamanho-Legivel $TAM[$nome]), (Dim), $Motivo[$nome], (Rs))
        if ($Compart.ContainsKey($nome)) {
            Write-Host ("  " + (Dim) + "└─ não libera espaço: pesos compartilhados com $($Compart[$nome])" + (Rs))
        }
    }
}
if ($PROT.Count -gt 0) {
    Write-Host ""
    Write-Host ("  " + (Dim) + "Reprovados, mas protegidos (não serão removidos):" + (Rs))
    foreach ($p in $PROT) { Write-Host ("  " + (Dim) + ("• {0,-24} {1}" -f $p[0], $p[1]) + (Rs)) }
}

if ($CAND.Count -eq 0) { return }
if ($DryRun) { Write-Host ""; Write-Host ((Dim) + "  -DryRun: nada foi removido." + (Rs)); return }
if ([Console]::IsInputRedirected) {
    Write-Host ""; Write-Host "  Sem terminal interativo: nada foi removido (use -DryRun para só listar)."; return
}

Write-Host ""
$ESCOLHIDOS = @(); $totalMb = 0
foreach ($nome in $CAND) {
    $r = Read-Host "  Remover $nome? [s/N]"
    if ($r -match '^[sSyY]$') {
        $ESCOLHIDOS += $nome
        $totalMb += [int]($Libera[$nome] / 1e6)
    }
}
if ($ESCOLHIDOS.Count -eq 0) { Write-Host ""; Write-Host "  Nada selecionado. Nada foi removido."; return }

Write-Host ""
Write-Host "  Serão removidos: $($ESCOLHIDOS -join ' ')  (libera ~$totalMb MB)"
$r = Read-Host "  Confirmar a remoção? [s/N]"
if ($r -notmatch '^[sSyY]$') { Write-Host "  Cancelado. Nada foi removido."; return }

$antes = Disco-Livre-MB; $falhas = 0
foreach ($nome in $ESCOLHIDOS) {
    ollama rm $nome *> $null
    if ($LASTEXITCODE -eq 0) { Write-Host ("  " + (Fg $PAL.Verde) + $ICO.Check + (Rs) + " removido: $nome") }
    else { Write-Host ("  " + (Fg $PAL.Verm) + $ICO.Xis + (Rs) + " falhou ao remover: $nome") -ForegroundColor Red; $falhas++ }
}
$depois = Disco-Livre-MB
Write-Host ""
Write-Host ((Dim) + "  Espaço livre: $antes MB → $depois MB. Histórico dos testes mantido em docs\resultados\resultados.csv." + (Rs))
if ($falhas -gt 0) { exit 1 }
