#Requires -Version 5.1
<#
.SYNOPSIS
    Valida a instalação da orquestração do OpenCode (Windows).

.DESCRIPTION
    Confere binários, versões, local e validade do config, o modelo derivado do
    Ollama (num_ctx) e as permissões efetivas dos agentes, segundo
    "opencode debug agents".

.PARAMETER Smoke
    Também roda um teste real de delegação ao qwen-testes. Leva ~1 min.

.EXAMPLE
    .\verify.ps1
    .\verify.ps1 -Smoke
#>
[CmdletBinding()]
param(
    [switch]$Smoke,
    [string]$ExpectedModel = "qwen3-16k:latest"
)

$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$script:Failures = 0
$script:Warnings = 0

function Step  { param($m) Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Ok    { param($m) Write-Host "  ok  $m" -ForegroundColor Green }
function Warn2 { param($m) Write-Host "  !   $m" -ForegroundColor Yellow; $script:Warnings++ }
function Bad   { param($m) Write-Host "  x   $m" -ForegroundColor Red; $script:Failures++ }

Step "Binários"
$bins = @{}
foreach ($cmd in @("opencode", "ollama", "node")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $ver = (& $cmd --version 2>&1 | Select-Object -First 1) -join ""
        $bins[$cmd] = $ver
        Ok ("{0}: {1}" -f $cmd, $ver)
    } elseif ($cmd -eq "node") {
        Warn2 "node não encontrado (só importa se o OpenCode veio do npm)"
    } else {
        Bad "$cmd não encontrado no PATH"
    }
}

Step "Config global"
$Target = Join-Path $env:USERPROFILE ".config\opencode\opencode.json"
if (-not (Test-Path -LiteralPath $Target)) {
    Bad "config não encontrado: $Target (rode .\install.ps1)"
} else {
    Ok "arquivo: $Target"
    try {
        $cfg = Get-Content -LiteralPath $Target -Raw -Encoding UTF8 | ConvertFrom-Json
        Ok "JSON válido"
        if ($cfg.default_agent) { Ok "default_agent: $($cfg.default_agent)" } else { Warn2 "default_agent não definido" }
        $names = @()
        if ($cfg.agents) { $names = @($cfg.agents.PSObject.Properties.Name) }
        foreach ($expected in @("orquestrador", "local-helper", "qwen-testes")) {
            if ($names -contains $expected) { Ok "agente presente: $expected" } else { Bad "agente ausente: $expected" }
        }
        if ($cfg.agents.orquestrador -and $cfg.agents.orquestrador.model) {
            Warn2 "orquestrador tem model fixo ($($cfg.agents.orquestrador.model)); o /models não vai governar a sessão"
        } elseif ($cfg.agents.orquestrador) {
            Ok "orquestrador sem model fixo (segue o /models)"
        }
        if ($cfg.model) { Warn2 "chave 'model' no topo do config fixa o modelo padrão ($($cfg.model))" }
    } catch {
        Bad "JSON inválido: $($_.Exception.Message)"
    }
}

Step "Variável de ambiente OPENCODE_CONFIG_CONTENT"
if ($env:OPENCODE_CONFIG_CONTENT) {
    Warn2 "definida ($($env:OPENCODE_CONFIG_CONTENT.Length) chars) e sobrepõe o arquivo"
    try {
        $snap = $env:OPENCODE_CONFIG_CONTENT | ConvertFrom-Json
        if ($snap.model) { Warn2 "snapshot fixa model: $($snap.model)" }
    } catch { }
    Warn2 "limpe antes de reiniciar: Remove-Item Env:OPENCODE_CONFIG_CONTENT"
} else {
    Ok "ausente"
}

Step "Modelo local no Ollama"
if ($bins.ContainsKey("ollama")) {
    $list = (& ollama list 2>&1 | Out-String)
    if ($list -match ("(?m)^\s*" + [regex]::Escape($ExpectedModel))) {
        Ok "modelo presente: $ExpectedModel"
        $mf = (& ollama show $ExpectedModel --modelfile 2>&1 | Out-String)
        $m = [regex]::Match($mf, "(?m)^PARAMETER\s+num_ctx\s+(\d+)")
        if ($m.Success) {
            Ok "num_ctx: $($m.Groups[1].Value)"
            if ([int]$m.Groups[1].Value -lt 8192) { Warn2 "contexto baixo para leitura de código (recomendado >= 8192)" }
        } else {
            Bad "modelo sem PARAMETER num_ctx (contexto cai para o padrão do Ollama)"
            Write-Host "     recrie: .\install.ps1 -Force"
        }
    } else {
        Bad "modelo não encontrado: $ExpectedModel (rode .\install.ps1)"
    }
}

Step "Agentes e permissões efetivas"
if ($bins.ContainsKey("opencode")) {
    # "debug agents" pode devolver [] por alguns instantes enquanto o serviço
    # recarrega a configuração — vale tentar mais de uma vez antes de acusar erro.
    $raw = ""
    $agents = $null
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $raw = (& opencode debug agents 2>&1 | Out-String)
        $agents = $null
        try {
            $start = $raw.IndexOf("[")
            $end   = $raw.LastIndexOf("]")
            if ($start -ge 0 -and $end -gt $start) {
                $parsed = $raw.Substring($start, $end - $start + 1) | ConvertFrom-Json
                if (@($parsed).Count -gt 0) { $agents = $parsed }
            }
        } catch { }
        if ($agents) { break }
        if ($attempt -lt 3) { Start-Sleep -Seconds 2 }
    }

    if (-not $agents) {
        Bad "não consegui interpretar a saída de 'opencode debug agents'"
        Write-Host ($raw.Substring(0, [Math]::Min(400, $raw.Length)))
    } else {
        Ok ("{0} agentes carregados" -f @($agents).Count)
        foreach ($id in @("local-helper", "qwen-testes")) {
            $a = $agents | Where-Object { $_.id -eq $id } | Select-Object -First 1
            if (-not $a) { Bad "agente não carregado: $id"; continue }
            if ($a.model) {
                $ref = "$($a.model.providerID)/$($a.model.id)"
                Ok "${id}: $ref"
            } else {
                Warn2 "$id sem modelo resolvido"
            }
            $perms = @($a.permissions)
            $execDeny = $perms | Where-Object { $_.action -eq "execute" -and $_.effect -eq "deny" }
            if ($execDeny) { Ok "${id}: execute negado" } else { Bad "${id}: execute NÃO negado" }

            $editDeny = $perms | Where-Object { $_.action -eq "edit" -and $_.effect -eq "deny" }
            if ($editDeny) { Ok "${id}: edit negado" } else { Bad "${id}: edit NÃO negado" }

            $envDeny = $perms | Where-Object { $_.action -eq "read" -and $_.resource -eq "*.env" -and $_.effect -eq "deny" }
            if ($envDeny) { Ok "${id}: leitura de *.env negada" } else { Warn2 "${id}: *.env não está negado" }
        }

        $qt = $agents | Where-Object { $_.id -eq "qwen-testes" } | Select-Object -First 1
        if ($qt) {
            $blocked = @(
                $qt.permissions | Where-Object {
                    $_.action -eq "shell" -and $_.effect -eq "deny" -and $_.resource -match "^(composer \*|npm \*|docker \*)"
                }
            )
            if ($blocked.Count -ge 3) { Ok "qwen-testes: composer/npm/docker negados" }
            else { Bad "qwen-testes: faltam negações de shell (composer/npm/docker)" }

            $shellAsk = $qt.permissions | Where-Object { $_.action -eq "shell" -and $_.resource -eq "*" -and $_.effect -eq "ask" }
            if ($shellAsk) { Ok "qwen-testes: shell em modo ask" } else { Warn2 "qwen-testes: shell não está em ask" }
        }

        $orc = $agents | Where-Object { $_.id -eq "orquestrador" } | Select-Object -First 1
        if ($orc) {
            $subAllow = @($orc.permissions | Where-Object { $_.action -eq "subagent" -and $_.effect -eq "allow" })
            Ok ("orquestrador: {0} delegações permitidas" -f $subAllow.Count)
        }
    }
}

if ($Smoke) {
    Step "Teste real de delegação (qwen-testes)"
    if (-not $bins.ContainsKey("opencode")) {
        Bad "opencode indisponível para o teste"
    } else {
        Write-Host "  rodando: opencode run --agent qwen-testes --model ollama/$ExpectedModel 'rode exatamente: git --version'"
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $out = (& opencode run --agent qwen-testes --model "ollama/$ExpectedModel" "rode exatamente: git --version") 2>&1 | Out-String
        $sw.Stop()
        Write-Host $out
        if ($out -match "git version") {
            Ok ("comando real executado ({0:N1}s)" -f $sw.Elapsed.TotalSeconds)
        } else {
            Bad "a saída não contém 'git version' — o comando pode não ter sido executado"
        }
    }
}

Step "Resultado"
if ($script:Failures -eq 0) {
    Write-Host ("  PASSOU — {0} aviso(s)" -f $script:Warnings) -ForegroundColor Green
    exit 0
} else {
    Write-Host ("  FALHOU — {0} erro(s), {1} aviso(s)" -f $script:Failures, $script:Warnings) -ForegroundColor Red
    exit 1
}
