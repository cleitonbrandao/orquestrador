# Libera RAM antes dos testes de modelos e utilitários do Ollama (dot-source). Equivale a limpar-ram.sh.
#
# Uso direto: .\scripts\limpar-ram.ps1 [limpar [modelo-alvo] | restaurar | estado]
#   limpar     descarrega modelos do Ollama (automático) e pergunta antes de parar containers
#              Docker e fechar apps (Teams, Chrome)
#   restaurar  religa os containers que este script parou
#   estado     mostra o que está parado por este script
#
# Só age sobre o que lista e o usuário aprova. Nunca mexe em Ollama, terminal, Docker Desktop nem
# processos de sistema: apps só entram se estiverem em $script:AppsLimpaveis.
# No Windows não há "limpar cache e swap": o cache de arquivos é liberado sozinho sob pressão de RAM.

# Nomes longos de propósito: quando carregado com dot-source, os parâmetros viram variáveis do chamador.
param(
    [Parameter(Position = 0)][string]$AcaoLimpeza = "",
    [Parameter(Position = 1)][string]$AlvoLimpeza = ""
)

$script:API = if ($env:OLLAMA_HOST_URL) { $env:OLLAMA_HOST_URL } else { "http://localhost:11434" }
$baseEstado = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-Path $HOME ".local\state" }
$script:ESTADO = Join-Path $baseEstado "orquestrador\orq-limpeza.state"
$script:AppsLimpaveis = @("ms-teams", "Teams", "chrome")

# Python: "python" ou "py -3"; -X utf8 faz o Python imprimir em UTF-8 mesmo com -I (que ignora variáveis).
function Get-Python {
    if (Get-Command python -ErrorAction SilentlyContinue) { return @("python") }
    if (Get-Command py -ErrorAction SilentlyContinue) { return @("py", "-3") }
    return $null
}
function Invoke-Py {
    $py = @(Get-Python)   # @(): sem isso, um único valor vira string e $py[0] seria só a 1ª letra
    if ($py.Count -eq 0 -or -not $py[0]) { throw "python não encontrado (necessário para o avaliador e os rankings)" }
    $exe = $py[0]
    $pre = @()
    if ($py.Count -gt 1) { $pre = $py[1..($py.Count - 1)] }
    # o PowerShell captura a saída num pipe (isatty falso): FORCE_COLOR pede as cores ao Python
    if ($script:V_COR) { $env:FORCE_COLOR = "1" } else { Remove-Item Env:\FORCE_COLOR -ErrorAction SilentlyContinue }
    & $exe @pre -X utf8 -I @args
}

# Chamada à API do Ollama; devolve o objeto JSON ($null em erro de conexão). A resposta é lida
# como bytes e decodificada em UTF-8 (o Windows PowerShell 5.1 decodifica errado sem charset).
function Invoke-Ollama {
    param([string]$Caminho, $Corpo = $null, [int]$Timeout = 900, [switch]$Get)
    $uri = "$($script:API)$Caminho"
    try {
        if ($Get -or $null -eq $Corpo) {
            $r = Invoke-WebRequest -Uri $uri -Method Get -UseBasicParsing -TimeoutSec $Timeout -ErrorAction Stop
        } else {
            $json = $Corpo | ConvertTo-Json -Depth 10 -Compress
            $bytes = [Text.Encoding]::UTF8.GetBytes($json)
            $r = Invoke-WebRequest -Uri $uri -Method Post -Body $bytes -ContentType "application/json; charset=utf-8" -UseBasicParsing -TimeoutSec $Timeout -ErrorAction Stop
        }
        $texto = [Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray())
        return ($texto | ConvertFrom-Json)
    } catch {
        # erros HTTP 4xx/5xx trazem o JSON {"error": "..."} no corpo
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            try { return ($_.ErrorDetails.Message | ConvertFrom-Json) } catch { }
        }
        $resp = $_.Exception.Response
        if ($resp) {
            try {
                $sr = New-Object IO.StreamReader($resp.GetResponseStream(), [Text.Encoding]::UTF8)
                $t = $sr.ReadToEnd()
                if ($t) { return ($t | ConvertFrom-Json) }
            } catch { }
        }
        return $null
    }
}

function Test-Ollama {
    $v = Invoke-Ollama "/api/version" -Get -Timeout 5
    return ($null -ne $v)
}

# GeraTexto <modelo>: $true se o modelo gera texto; $false para embeddings (ex.: nomic-embed-text).
function GeraTexto([string]$modelo) {
    $r = Invoke-Ollama "/api/show" @{ model = $modelo } -Timeout 10
    if ($null -eq $r) { return $false }
    if ($null -eq $r.capabilities) { return $true }
    return (@($r.capabilities) -contains "completion")
}

# NomesTestaveis: modelos instalados que geram texto.
function NomesTestaveis {
    $tags = Invoke-Ollama "/api/tags" -Get -Timeout 5
    if ($null -eq $tags) { return @() }
    $saida = @()
    foreach ($m in @($tags.models)) { if (GeraTexto $m.name) { $saida += $m.name } }
    return $saida
}

function MemDispMB {
    $so = Get-CimInstance Win32_OperatingSystem
    return [int]($so.FreePhysicalMemory / 1024)
}

function SituacaoRam { return ("RAM disponível: {0} MB" -f (MemDispMB)) }

# Confirmar <pergunta>: padrão é não; sem terminal também é não.
function Confirmar([string]$pergunta) {
    try { $r = Read-Host "$pergunta [s/N]" } catch { return $false }
    return ($r -match '^[sSyY]$')
}

function Limpar-Ollama([string]$alvo) {
    $ps = Invoke-Ollama "/api/ps" -Get -Timeout 3
    if ($null -eq $ps) { return }
    foreach ($m in @($ps.models)) {
        $nome = [string]$m.name
        if (($nome -replace ':latest$', '') -eq ($alvo -replace ':latest$', '')) { continue }
        $null = Invoke-Ollama "/api/generate" @{ model = $nome; keep_alive = 0 } -Timeout 30
        Write-Host "  Ollama: descarregado $nome"
    }
}

function Parar-Container([string]$nome) {
    $dir = Split-Path $script:ESTADO
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    docker stop $nome *> $null
    if ($LASTEXITCODE -eq 0) {
        Add-Content -Path $script:ESTADO -Value $nome -Encoding UTF8
        Write-Host "    parado: $nome"
    } else {
        Write-Host "    falhou ao parar: $nome" -ForegroundColor Red
    }
}

function Limpar-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return }
    docker ps *> $null
    if ($LASTEXITCODE -ne 0) { Write-Host "  Docker: indisponível, etapa ignorada."; return }
    $linhas = @(docker stats --no-stream --format "{{.Name}}`t{{.MemUsage}}" 2>$null)
    if ($linhas.Count -eq 0 -or -not $linhas[0]) { return }
    Write-Host "  Docker: containers em execução (serão religados no fim):"
    $escolhidos = @()
    foreach ($l in $linhas) {
        $p = $l -split "`t"
        $uso = ($p[1] -split " / ")[0]
        if (Confirmar "    parar $($p[0]) ($uso)?") { $escolhidos += $p[0] }
    }
    # bancos por último na parada; religam primeiro (Restaurar lê o estado de trás para frente)
    $rxBanco = 'postgres|sql|db|mysql|maria|redis'
    foreach ($n in $escolhidos) { if ($n -notmatch $rxBanco) { Parar-Container $n } }
    foreach ($n in $escolhidos) { if ($n -match $rxBanco) { Parar-Container $n } }
}

function Limpar-Apps {
    foreach ($app in $script:AppsLimpaveis) {
        $procs = @(Get-Process -Name $app -ErrorAction SilentlyContinue)
        if ($procs.Count -eq 0) { continue }
        $mb = [int](($procs | Measure-Object WorkingSet64 -Sum).Sum / 1MB)
        Write-Host "  App: $app usa ~$mb MB (não será reaberto)."
        if (Confirmar "    fechar ${app}? Salve o trabalho antes.") {
            foreach ($p in $procs) { if ($p.MainWindowHandle -ne 0) { $null = $p.CloseMainWindow() } }
            Start-Sleep -Seconds 3
            if (Get-Process -Name $app -ErrorAction SilentlyContinue) {
                Write-Host "    $app ainda está fechando; feche manualmente se demorar."
            }
        }
    }
}

# Limpar [modelo-alvo]: o modelo-alvo não é descarregado do Ollama.
function Limpar([string]$alvo = "") {
    $antes = MemDispMB
    Write-Host "Limpeza de RAM"
    Write-Host ("  Antes:  " + (SituacaoRam))
    Limpar-Ollama $alvo
    Limpar-Docker
    Limpar-Apps
    $depois = MemDispMB
    Write-Host ("  Depois: " + (SituacaoRam))
    Write-Host ("  Ganho:  {0:+#;-#;0} MB de RAM disponível" -f ($depois - $antes))
}

# Restaurar: religa o que foi parado, bancos primeiro; mantém no estado o que falhar.
function Restaurar {
    if (-not (Test-Path $script:ESTADO) -or (Get-Item $script:ESTADO).Length -eq 0) {
        Write-Host "Nada a restaurar."; return $true
    }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host "Docker indisponível; containers continuam em $($script:ESTADO)" -ForegroundColor Red; return $false
    }
    docker ps *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Docker indisponível; containers continuam em $($script:ESTADO)" -ForegroundColor Red; return $false
    }
    $nomes = @(Get-Content $script:ESTADO | Where-Object { $_ })
    [array]::Reverse($nomes)
    $falhos = @(); $esperas = @()
    Write-Host "Religando containers parados pela limpeza..."
    foreach ($n in $nomes) {
        docker start $n *> $null
        if ($LASTEXITCODE -eq 0) { Write-Host "  iniciado: $n"; $esperas += $n }
        else { Write-Host "  falhou ao iniciar: $n" -ForegroundColor Red; $falhos += $n }
    }
    foreach ($n in $esperas) {
        $st = ""
        for ($i = 0; $i -lt 30; $i++) {
            $st = (docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}running{{end}}' $n 2>$null)
            if ($st -eq "healthy" -or $st -eq "running") { break }
            Start-Sleep -Seconds 2
        }
        Write-Host "  ${n}: $st"
    }
    Set-Content -Path $script:ESTADO -Value $falhos -Encoding UTF8
    return ($falhos.Count -eq 0)
}

function Estado {
    if ((Test-Path $script:ESTADO) -and (Get-Item $script:ESTADO).Length -gt 0) {
        Write-Host "Parados por este script (use restaurar):"
        Get-Content $script:ESTADO | Where-Object { $_ } | ForEach-Object { Write-Host "  $_" }
    } else {
        Write-Host "Nada parado por este script."
    }
    Write-Host (SituacaoRam)
}

# Execução direta (não dot-source): InvocationName é "." quando carregado com dot-source.
if ($MyInvocation.InvocationName -ne ".") {
    switch ($AcaoLimpeza) {
        "" { Limpar $AlvoLimpeza }
        "limpar" { Limpar $AlvoLimpeza }
        "restaurar" { $null = Restaurar }
        "estado" { Estado }
        default { Write-Host "uso: limpar-ram.ps1 [limpar [modelo] | restaurar | estado]"; exit 2 }
    }
}
