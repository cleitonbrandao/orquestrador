#Requires -Version 5.1
<#
.SYNOPSIS
    Valida a instalação da orquestração do OpenCode (Windows).

.DESCRIPTION
    Confere binários, versões, local e validade do config, o modelo derivado do
    Ollama (num_ctx) e as permissões efetivas dos agentes, segundo
    "opencode debug agents".

.PARAMETER Smoke
    Mantido por compatibilidade; o teste do run_tests agora sempre roda.

.EXAMPLE
    .\verify.ps1
    .\verify.ps1 -Smoke
#>
[CmdletBinding()]
param(
    [switch]$Smoke,
    [string]$ExpectedModel = "qwen3-12k:latest"
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
        foreach ($expected in @("orquestrador", "decompositor", "executor", "exec-backend", "exec-dados", "exec-frontend", "exec-docs", "local-helper")) {
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
        # durante o reload a lista pode vir parcial (só os agentes nativos)
        if ($agents -and (@($agents.id) -contains "decompositor")) { break }
        if ($attempt -lt 3) { Start-Sleep -Seconds 2 }
    }

    if (-not $agents) {
        Bad "não consegui interpretar a saída de 'opencode debug agents'"
        Write-Host ($raw.Substring(0, [Math]::Min(400, $raw.Length)))
    } else {
        Ok ("{0} agentes carregados" -f @($agents).Count)
        foreach ($id in @("local-helper")) {
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

        $orc = $agents | Where-Object { $_.id -eq "orquestrador" } | Select-Object -First 1
        if ($orc) {
            $subAllow = @($orc.permissions | Where-Object { $_.action -in @("subagent", "task") -and $_.effect -eq "allow" })
            Ok ("orquestrador: {0} delegações permitidas" -f $subAllow.Count)
            foreach ($id in @("decompositor", "executor", "exec-backend", "exec-dados", "exec-frontend", "exec-docs")) {
                if ($subAllow | Where-Object { $_.resource -eq $id }) { Ok "orquestrador: pode delegar ao $id" }
                else { Bad "orquestrador: delegação ao $id não permitida" }
            }
        }

        # Pipeline: decompositor só lê; executor edita, não roda shell nem subagente e testa pelo run_tests.
        $dec = $agents | Where-Object { $_.id -eq "decompositor" } | Select-Object -First 1
        if (-not $dec) { Bad "agente não carregado: decompositor" }
        else {
            $p = @($dec.permissions)
            if ($p | Where-Object { $_.action -eq "edit" -and $_.resource -eq "*" -and $_.effect -eq "deny" }) { Ok "decompositor: edit negado" } else { Bad "decompositor: edit NÃO negado" }
            if ($p | Where-Object { $_.action -in @("shell", "bash") -and $_.resource -eq "*" -and $_.effect -eq "deny" }) { Ok "decompositor: shell negado" } else { Bad "decompositor: shell NÃO negado" }
        }
        foreach ($id in @("executor", "exec-backend", "exec-dados", "exec-frontend")) {
            $exe = $agents | Where-Object { $_.id -eq $id } | Select-Object -First 1
            if (-not $exe) { Bad "agente não carregado: $id"; continue }
            $p = @($exe.permissions)
            if ($p | Where-Object { $_.action -in @("shell", "bash") -and $_.resource -eq "*" -and $_.effect -eq "deny" }) { Ok "${id}: shell negado" } else { Bad "${id}: shell NÃO negado" }
            if ($p | Where-Object { $_.action -in @("subagent", "task") -and $_.resource -eq "*" -and $_.effect -eq "deny" }) { Ok "${id}: subagente negado (testes pelo run_tests)" } else { Bad "${id}: subagente NÃO negado" }
        }

        # exec-docs: modelo local, edita só Markdown, sem shell e sem subagente
        $doc = $agents | Where-Object { $_.id -eq "exec-docs" } | Select-Object -First 1
        if (-not $doc) { Bad "agente não carregado: exec-docs" }
        else {
            $p = @($doc.permissions)
            if ($doc.model) { Ok "exec-docs: $($doc.model.providerID)/$($doc.model.id)" }
            $lastEdit = $p | Where-Object { $_.action -eq "edit" } | Select-Object -Last 1
            $editDeny = $p | Where-Object { $_.action -eq "edit" -and $_.resource -eq "*" -and $_.effect -eq "deny" }
            if ($editDeny -and $lastEdit.resource -eq "*.md" -and $lastEdit.effect -eq "allow") { Ok "exec-docs: edita só *.md" } else { Bad "exec-docs: edit não está restrito a *.md" }
            if ($p | Where-Object { $_.action -in @("shell", "bash") -and $_.resource -eq "*" -and $_.effect -eq "deny" }) { Ok "exec-docs: shell negado" } else { Bad "exec-docs: shell NÃO negado" }
            if ($p | Where-Object { $_.action -in @("subagent", "task") -and $_.resource -eq "*" -and $_.effect -eq "deny" }) { Ok "exec-docs: subagente negado" } else { Bad "exec-docs: subagente NÃO negado" }
        }
    }
}

Step "Slots do Ollama (variáveis de usuário)"
$parallel = [Environment]::GetEnvironmentVariable("OLLAMA_NUM_PARALLEL", "User")
if ($parallel) {
    Ok "OLLAMA_NUM_PARALLEL=$parallel"
    if ([int]$parallel -lt 2) { Warn2 "menos de 2 slots: o pipeline roda uma tarefa por vez" }
} else {
    Warn2 "OLLAMA_NUM_PARALLEL não definida (o Ollama decide sozinho; rode .\install.ps1)"
}
foreach ($pair in @(@("OLLAMA_FLASH_ATTENTION", "1"), @("OLLAMA_KV_CACHE_TYPE", "q8_0"))) {
    $v = [Environment]::GetEnvironmentVariable($pair[0], "User")
    if ($v -eq $pair[1]) { Ok "$($pair[0])=$v" } else { Warn2 "$($pair[0])=$v (esperado $($pair[1]); 2 slots podem não caber na VRAM)" }
}
if ($bins.ContainsKey("ollama")) {
    $ps = (& ollama ps 2>&1 | Out-String)
    if ($ps -match "CPU") { Warn2 "ollama ps mostra uso de CPU: modelo não coube inteiro na VRAM" }
}

Step "Claude Code (~/.claude)"
$ClaudeDir = Join-Path $env:USERPROFILE ".claude"
foreach ($f in @("agents\decompositor.md", "agents\executor.md", "agents\exec-backend.md", "agents\exec-dados.md", "agents\exec-frontend.md", "agents\exec-docs.md", "agents\testador.md", "skills\orquestrar\SKILL.md")) {
    $path = Join-Path $ClaudeDir $f
    if (Test-Path -LiteralPath $path) { Ok "presente: $f" } else { Warn2 "ausente: $path (rode .\install.ps1)" }
}

Step "Scripts verificadores (~/.orquestrador/scripts)"
$ScriptsDir = Join-Path $env:USERPROFILE ".orquestrador\scripts"
foreach ($f in @("verificar.ps1", "verificar.sh", "verificar_docs.py", "redigir_docs.py")) {
    if (Test-Path -LiteralPath (Join-Path $ScriptsDir $f)) { Ok "presente: $f" } else { Bad "ausente: $(Join-Path $ScriptsDir $f) (rode .\install.ps1)" }
}
$verificar = Join-Path $ScriptsDir "verificar.ps1"
if (Test-Path -LiteralPath $verificar) {
    $out = (& powershell -NoProfile -ExecutionPolicy Bypass -File $verificar "git --version" | Out-String)
    if ($out -match "git version" -and $out -match "RESULTADO: bloqueado") { Ok "verificar.ps1: git --version -> bloqueado (correto: não é teste)" }
    else { Bad "verificar.ps1 não devolveu o contrato esperado"; Write-Host $out }
    $out = (& powershell -NoProfile -ExecutionPolicy Bypass -File $verificar "composer install" | Out-String)
    if ($out -match "recusado") { Ok "verificar.ps1: composer install recusado sem rodar" } else { Bad "verificar.ps1 não recusou composer install" }
}
$pyVer = ""
if (Get-Command python -ErrorAction SilentlyContinue) { $pyVer = ((& python --version 2>&1) -join "") }
$verificarDocs = Join-Path $ScriptsDir "verificar_docs.py"
if ($pyVer -notmatch "Python 3") {
    Warn2 "Python 3 não encontrado: a rota docs cai no exec-docs e o verificador de docs não roda"
} elseif (Test-Path -LiteralPath $verificarDocs) {
    $tmp = Join-Path $env:TEMP ("orq-verify-{0}" -f (Get-Random))
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    "# Teste`n`nVeja [x](nao-existe.md).`n" | Out-File -LiteralPath (Join-Path $tmp "LEIAME.md") -Encoding utf8
    $vazio = Join-Path $tmp "vazio.md"
    New-Item -ItemType File -Path $vazio -Force | Out-Null
    $out = (& python $verificarDocs (Join-Path $tmp "LEIAME.md") --original $vazio --raiz $tmp 2>&1 | Out-String)
    Remove-Item -LiteralPath $tmp -Recurse -Force -Confirm:$false -ErrorAction SilentlyContinue
    if ($out -match "RESULTADO: falhou" -and $out -match "nao-existe.md") { Ok "verificar_docs.py: link quebrado detectado ($pyVer)" }
    else { Bad "verificar_docs.py não acusou o link quebrado"; Write-Host $out }
}

Step "Servidor MCP run_tests"
$rt = Get-Command orq-run-tests -ErrorAction SilentlyContinue
if (-not $rt) {
    Bad "orq-run-tests não está no PATH (rode .\install.ps1)"
} else {
    Ok "launcher: $($rt.Source)"
    function Invoke-RunTests([string]$cmd) {
        $init = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
        $call = (@{jsonrpc="2.0"; id=2; method="tools/call"; params=@{name="run_tests"; arguments=@{command=$cmd}}} | ConvertTo-Json -Depth 5 -Compress)
        (@($init, $call) | & orq-run-tests) | Select-Object -Last 1
    }
    if ((Invoke-RunTests "git --version") -match '"verdict":"passou"') { Ok "git --version -> passou (exit 0 real)" } else { Bad "run_tests não executou comando permitido" }
    if ((Invoke-RunTests "composer install") -match '"verdict":"bloqueado"') { Ok "composer install -> bloqueado" } else { Bad "run_tests deixou passar comando negado" }
}

Step "Base de conhecimento (kb e embeddings)"
$kb = Get-Command orq-kb -ErrorAction SilentlyContinue
if (-not $kb) {
    Bad "orq-kb não está no PATH (rode install.ps1)"
} else {
    Ok ("launcher: {0}" -f $kb.Source)
    if (Get-Command ollama -ErrorAction SilentlyContinue) {
        if ((ollama list 2>$null) -match '^nomic-embed-text') { Ok "nomic-embed-text instalado (busca semântica)" }
        else { Warn2 "nomic-embed-text ausente: a busca do kb fica só em BM25 (ollama pull nomic-embed-text)" }
    }
    if (Get-Command opencode -ErrorAction SilentlyContinue) {
        $mcpOut = (opencode mcp list 2>&1 | Out-String) -replace '\x1b\[[0-9;]*m',''
        if ($mcpOut -match 'kb\s+connected|✓ kb') { Ok "OpenCode: MCP kb conectado" } else { Bad "OpenCode: MCP kb não conectado (confira mcp.kb em opencode.json)" }
    }
    foreach ($linha in (& orq-kb apps 2>$null)) {
        if ($linha -match ' 0 com embedding') { Warn2 ("kb: {0} sem embeddings (rode 'orq-kb index' na raiz desse projeto)" -f ($linha -split ':')[0]) }
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
