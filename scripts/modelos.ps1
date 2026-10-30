#Requires -Version 5.1
<#
.SYNOPSIS
    Terminal interativo para testar modelos do Ollama. Digite /help para ver os comandos.
    Equivale a scripts/modelos.sh.

.EXAMPLE
    .\scripts\modelos.ps1
    scripts\modelos.cmd          # abre sem mexer na política de execução do PowerShell

    $env:NO_COLOR = "1" desliga as cores; $env:ORQ_ICONS = "nerd|unicode|ascii" troca os ícones.
#>
[CmdletBinding()]
param()

$RAIZ = Split-Path $PSScriptRoot -Parent
$TESTAR = Join-Path $PSScriptRoot "testar-modelo.ps1"
$PODAR = Join-Path $PSScriptRoot "podar-modelos.ps1"
$LIMPARTESTES = Join-Path $PSScriptRoot "limpar-testes.ps1"
$RELATORIO = Join-Path $PSScriptRoot "relatorio.py"
$CUSTO = Join-Path $PSScriptRoot "custo_agentes.py"
$CTX = Join-Path $PSScriptRoot "contexto_local.py"
$DIR_RESULTADOS = if ($env:ORQ_RESULTADOS) { $env:ORQ_RESULTADOS } else { Join-Path $RAIZ "docs\resultados" }
$CSV_ATUAL = Join-Path $DIR_RESULTADOS "resultados.csv"
$env:ORQ_CLI = "1"   # o testar-modelo.ps1 não abre outro terminal por cima deste

. (Join-Path $PSScriptRoot "visual.ps1")
. (Join-Path $PSScriptRoot "limpar-ram.ps1")

$script:LIMPO = $false

function Instalados { return ((NomesTestaveis) -join ",") }

# CmdLinha <ícone> <cor> <comando> <descrição>
function CmdLinha([string]$icone, [string]$cor, [string]$cmd, [string]$desc) {
    Write-Host ("  {0}{1}  {2}{3,-17}{4} {5}{6}{4}" -f (Fg $cor), $icone, (Neg), $cmd, (Rs), (Dim), $desc)
}

function Banner {
    Write-Host ""
    TituloPixel "MODELOS"
    Write-Host ""
    Pl $PAL.Roxo $PAL.Texto "$($ICO.Codigo)  Testador de modelos locais" $PAL.Escuro $PAL.Ciano "Ollama"
    Write-Host ""
    CmdLinha $ICO.Frasco $PAL.Verde "/test <modelo>" "teste completo: velocidade, qualidade e nota"
    CmdLinha $ICO.Bolt $PAL.Amar "/bench <modelo>" "só velocidade (tok/s)"
    CmdLinha $ICO.Chip $PAL.Laranja "/omni <modelo>" "benchmark multimodal: texto, imagem, áudio, fala"
    CmdLinha $ICO.Trofeu $PAL.Rosa "/rank" "ranking por tok/s, com a nota ao lado"
    CmdLinha $ICO.Trofeu $PAL.Rosa "/nota" "ranking por nota, com o tok/s ao lado"
    CmdLinha $ICO.Painel $PAL.Ciano "/list" "testados com nota e pendentes"
    CmdLinha $ICO.Trofeu $PAL.Rosa   "/list-fluxo-ia" "melhores duplas gerador + revisor"
    CmdLinha $ICO.Relogio $PAL.Rosa "/custo" "uso local vs pago por dia"
    CmdLinha $ICO.Frasco $PAL.Verde "/ctx [arquivos]" "resume contexto local antes da sessão paga"
    CmdLinha $ICO.Painel $PAL.Ciano "/report" "relatório visual (HTML)"
    CmdLinha $ICO.Engr $PAL.Laranja "/clean" "libera RAM antes de testar"
    CmdLinha $ICO.Codigo $PAL.Azul "/help  /quit" "todos os comandos · sair"
    Write-Host ""
}

# Status: linha powerline mostrada antes de cada prompt.
function Status {
    $ram = MemDispMB
    $corRam = $PAL.Verde
    if ($ram -lt 5000) { $corRam = $PAL.Amar }
    if ($ram -lt 3000) { $corRam = $PAL.Verm }
    $linhas = @()
    if (Test-Path $CSV_ATUAL) { $linhas = @(Import-Csv $CSV_ATUAL) }
    $segs = @($PAL.Roxo, $PAL.Texto, "$($ICO.Codigo) modelos")
    $segs += @($corRam, $PAL.Base, ("{0} {1}G livre" -f $ICO.Chip, ($ram / 1024).ToString("0.0", [Globalization.CultureInfo]::InvariantCulture)))
    $segs += @($PAL.Escuro, $PAL.Ciano, "$($ICO.Frasco) $($linhas.Count) teste(s)")
    if ($linhas.Count -gt 0) {
        $melhor = $linhas | Sort-Object { [double]$_.nota } -Descending | Select-Object -First 1
        $segs += @($PAL.Escuro, $PAL.Amar, "$($ICO.Trofeu) $($melhor.modelo) $($melhor.nota)")
    }
    if ((Test-Path $script:ESTADO) -and (Get-Item $script:ESTADO).Length -gt 0) {
        $parados = @(Get-Content $script:ESTADO | Where-Object { $_ }).Count
        $segs += @($PAL.Laranja, $PAL.Base, "$($ICO.Docker) $parados parado(s)")
    }
    Pl @segs
}

function Titulo([string]$cor, [string]$texto) { Write-Host ""; Write-Host ("  " + (Fg $cor) + (Neg) + $texto + (Rs)) }

function Ajuda {
    Titulo $PAL.Verde "$($ICO.Frasco)  Testar"
    CmdLinha " " $PAL.Verde "/test [modelo]" "teste completo (--think, --rapido, --sem-limpeza)"
    CmdLinha " " $PAL.Verde "/decisao [modelo]" "modelo de decisão (d3, tev1): acerto, escalada e nota"
    CmdLinha " " $PAL.Amar "/bench [modelo]" "só velocidade, sem salvar (também /benchmark)"
    CmdLinha " " $PAL.Laranja "/omni [modelo]" "benchmark multimodal (--only, --audio, --image, --num-predict)"
    Titulo $PAL.Rosa "$($ICO.Trofeu)  Ver resultados"
    CmdLinha " " $PAL.Rosa "/rank" "ranking por tok/s, com barra e a nota ao lado"
    CmdLinha " " $PAL.Rosa "/rank-decisao" "ranking dos decisores: acerto, escalada e erro confiante"
    CmdLinha " " $PAL.Rosa "/nota" "ranking por nota, com tok/s, A-D e etapas em que serve"
    CmdLinha " " $PAL.Ciano "/list" "testados (com a nota) e instalados ainda sem teste"
    CmdLinha " " $PAL.Ciano "/ver <modelo>" "histórico completo de um modelo"
    CmdLinha " " $PAL.Rosa   "/list-fluxo-ia" "lista as melhores duplas gerador + revisor"
    CmdLinha " " $PAL.Rosa   "/custo [--dias N]" "uso local vs pago por dia, com gráfico e economia"
    CmdLinha " " $PAL.Verde  "/ctx [arquivos]" "resume arquivos no modelo local e grava um Markdown para o pago ler"
    CmdLinha " " $PAL.Ciano "/report" "gera docs\resultados\relatorio.html e abre no navegador"
    Titulo $PAL.Laranja "$($ICO.Engr)  Máquina"
    CmdLinha " " $PAL.Laranja "/clean" "libera RAM: Ollama, Docker e apps (pergunta antes)"
    CmdLinha " " $PAL.Laranja "/restore" "religa os containers que a limpeza parou (também ao sair)"
    CmdLinha " " $PAL.Laranja "/ram" "RAM disponível e o que está parado"
    CmdLinha " " $PAL.Laranja "/prune" "desinstala modelos reprovados (--dry-run, --min-qualidade, --min-toks)"
    CmdLinha " " $PAL.Laranja "/reset [modelo]" "apaga os resultados dos testes desta máquina (ou só de um modelo)"
    Titulo $PAL.Azul "$($ICO.Codigo)  Geral"
    CmdLinha " " $PAL.Azul "/help" "esta lista"
    CmdLinha " " $PAL.Azul "/quit" "sair (ou Ctrl+Z e Enter); Ctrl+C encerra o terminal"
    Write-Host ""
    Write-Host ("  " + (Dim) + "Atalhos: /t /b /r /n /l /v /c /u /h /q. A limpeza roda uma vez por sessão, antes do primeiro")
    Write-Host ("  /test ou /bench. Ao sair (inclusive com Ctrl+C) os containers parados são religados." + (Rs))
}

# Alvo-De <tokens>: primeiro argumento que não é opção (o modelo), se houver.
function Alvo-De([string[]]$tokens) {
    foreach ($t in $tokens) { if ($t -and -not $t.StartsWith("--")) { return $t } }
    return ""
}

# Preparar <tokens>: roda a limpeza uma vez por sessão, a menos que --sem-limpeza.
function Preparar([string[]]$tokens) {
    if ($tokens -contains "--sem-limpeza") { return }
    if ($script:LIMPO) { return }
    Limpar (Alvo-De $tokens)
    $script:LIMPO = $true
    Write-Host ""
}

# Para-Splat <tokens>: converte "modelo --think --rapido" em hashtable para o testar-modelo.ps1.
function Para-Splat([string[]]$tokens) {
    $h = @{}
    foreach ($t in $tokens) {
        switch ($t) {
            "--think" { $h["Think"] = $true }
            "--rapido" { $h["Rapido"] = $true }
            "--sem-limpeza" { }
            default { if (-not $t.StartsWith("--") -and -not $h.ContainsKey("Modelo")) { $h["Modelo"] = $t } }
        }
    }
    return $h
}

# Para-Splat-Omni <tokens>: "modelo --only audio --audio fala.wav --sem-salvar"
function Para-Splat-Omni([string[]]$tokens) {
    $h = @{}
    for ($i = 0; $i -lt $tokens.Count; $i++) {
        switch ($tokens[$i]) {
            "--sem-salvar" { $h["SemSalvar"] = $true }
            "--listar" { $h["Listar"] = $true }
            "--only" { if ($i + 1 -lt $tokens.Count) { $h["Somente"] = $tokens[$i + 1]; $i++ } }
            "--image" { if ($i + 1 -lt $tokens.Count) { $h["Imagem"] = $tokens[$i + 1]; $i++ } }
            "--audio" { if ($i + 1 -lt $tokens.Count) { $h["Audio"] = $tokens[$i + 1]; $i++ } }
            "--num-predict" { if ($i + 1 -lt $tokens.Count) { $h["NumPredict"] = [int]$tokens[$i + 1]; $i++ } }
            "--sem-limpeza" { }
            default { if (-not $tokens[$i].StartsWith("--") -and -not $h.ContainsKey("Modelo")) { $h["Modelo"] = $tokens[$i] } }
        }
    }
    return $h
}

# Para-Splat-Prune <tokens>: "--dry-run --min-qualidade 25 --min-toks 5"
function Para-Splat-Prune([string[]]$tokens) {
    $h = @{}
    for ($i = 0; $i -lt $tokens.Count; $i++) {
        switch ($tokens[$i]) {
            "--dry-run" { $h["DryRun"] = $true }
            "--min-qualidade" { if ($i + 1 -lt $tokens.Count) { $h["MinQualidade"] = [double]::Parse($tokens[$i + 1], [Globalization.CultureInfo]::InvariantCulture); $i++ } }
            "--min-toks" { if ($i + 1 -lt $tokens.Count) { $h["MinToks"] = [double]::Parse($tokens[$i + 1], [Globalization.CultureInfo]::InvariantCulture); $i++ } }
        }
    }
    return $h
}

if (-not (Test-Path $TESTAR)) { Write-Host "não achei $TESTAR" -ForegroundColor Red; exit 1 }

try {
    Banner
    if ((Test-Path $script:ESTADO) -and (Get-Item $script:ESTADO).Length -gt 0) {
        Write-Host ((Fg $PAL.Amar) + "$($ICO.Docker) Há containers parados por uma limpeza anterior:" + (Rs))
        Get-Content $script:ESTADO | Where-Object { $_ } | ForEach-Object { Write-Host "  $_" }
        Write-Host "Eles serão religados ao sair, ou use /restore agora."
        Write-Host ""
    }

    while ($true) {
        Status
        Write-Host ((Fg $PAL.Ciano) + (Neg) + "❯ " + (Rs)) -NoNewline
        $linha = [Console]::ReadLine()
        if ($null -eq $linha) { Write-Host ""; break }
        $linha = $linha.Trim()
        if (-not $linha) { continue }
        $partes = @($linha -split '\s+')
        $cmd = $partes[0]
        $resto = @()
        if ($partes.Count -gt 1) { $resto = @($partes[1..($partes.Count - 1)]) }

        # um erro em um comando não pode derrubar o terminal (e a restauração dos containers)
        try {
            switch -Regex ($cmd) {
                '^/(test|t)$' {
                    Preparar $resto
                    $h = Para-Splat $resto
                    & $TESTAR @h
                    break
                }
                '^/(bench|benchmark|b)$' {
                    Preparar $resto
                    $h = Para-Splat $resto
                    & $TESTAR -Velocidade @h
                    break
                }
                '^/(omni|multimodal)$' {
                    Preparar $resto
                    $h = Para-Splat-Omni $resto
                    & (Join-Path $PSScriptRoot "bench-omni.ps1") @h
                    break
                }
                '^/decisao$' {
                    Preparar $resto
                    $limpos = @($resto | Where-Object { $_ -ne "--sem-limpeza" })
                    & (Join-Path $PSScriptRoot "testar-decisor.ps1") @limpos
                    break
                }
                '^/(rank|r)$' { Invoke-Py $RELATORIO rank; break }
                '^/(rank-decisao|decisoes)$' { Invoke-Py $RELATORIO decisao; break }
                '^/(nota|n)$' { Invoke-Py $RELATORIO nota; break }
                '^/(list|l)$' { Invoke-Py $RELATORIO lista --instalados (Instalados); break }
                '^/(ver|v)$' { Invoke-Py $RELATORIO ver @resto; break }
                '^/(list-fluxo-ia|fluxo)$' { Invoke-Py "$RAIZ\scripts\fluxo_ia.py"; break }
                '^/(custo|uso|economia|u)$' { Invoke-Py $CUSTO --todos --economia --grafico @resto; break }
                '^/(ctx|contexto)$' { Invoke-Py $CTX @resto; break }
                '^/report$' { Invoke-Py $RELATORIO html --instalados (Instalados) --abrir; break }
                '^/(clean|c)$' { Limpar (Alvo-De $resto); $script:LIMPO = $true; break }
                '^/restore$' { $null = Restaurar; break }
                '^/ram$' { Estado; break }
                '^/(prune|remover)$' { $h = Para-Splat-Prune $resto; & $PODAR @h; break }
                '^/reset$' {
                    # hashtable + splat, como no /test: passar @(...) como argumento entregava um array ao [string]$Modelo
                    $h = @{}
                    $alvoReset = Alvo-De $resto
                    if ($alvoReset) { $h["Modelo"] = $alvoReset }
                    if ($resto -contains "--sim") { $h["Sim"] = $true }
                    & $LIMPARTESTES @h
                    break
                }
                '^/(help|h|\?)$' { Ajuda; break }
                '^/(quit|exit|q)$' { return }
                '^/' { Write-Host ((Fg $PAL.Verm) + "$($ICO.Xis) comando desconhecido: $cmd" + (Rs) + " (digite /help)"); break }
                default { Write-Host "os comandos começam com /. Digite /help." }
            }
        } catch {
            Write-Host ((Fg $PAL.Verm) + "$($ICO.Xis) erro: $($_.Exception.Message)" + (Rs))
        }
        Write-Host ""
    }
}
finally {
    $null = Restaurar
}
