#Requires -Version 5.1
<#
.SYNOPSIS
    Instala a configuração global de orquestração do OpenCode (Windows).

.DESCRIPTION
    Copia opencode/opencode.json e opencode/plugins/ollama-nothink.ts para
    %USERPROFILE%\.config\opencode, com backup do arquivo atual, e garante os
    modelos derivados do Ollama usados pelos subagentes:
      qwen3.5-4b-16k  = qwen3.5:4b + num_ctx 16384   (decompositor, local-helper)
      qwen3.5-2b-16k  = qwen3.5:2b + num_ctx 16384   (revisor)
      qwen3.5-08b-8k  = qwen3.5:0.8b + num_ctx 8192  (local-mini)
      gemma4-e4b-16k  = gemma4:e4b + num_ctx 16384   (exec-local, exec-docs)

.PARAMETER BaseModel
    Modelo base do Ollama usado no qwen3.5-4b-16k. Padrão: qwen3.5:4b

.PARAMETER Context
    Valor de num_ctx do qwen3.5-4b-16k. Padrão: 16384

.PARAMETER SkipModel
    Não mexe no Ollama (a config é instalada do mesmo jeito).

.PARAMETER Link
    Tenta criar symlink em vez de copiar (exige modo Desenvolvedor ou admin).

.PARAMETER Force
    Recria o modelo derivado mesmo que já exista.

.EXAMPLE
    .\install.ps1
    .\install.ps1 -Context 8192 -Force
    .\install.ps1 -SkipModel
#>
[CmdletBinding()]
param(
    [string]$BaseModel = "qwen3.5:4b",
    [int]$Context = 16384,
    [switch]$SkipModel,
    [switch]$Link,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$Models = @(
    @{ Name = "qwen3.5-4b-16k"; Base = $BaseModel; Context = $Context },
    @{ Name = "qwen3.5-2b-16k"; Base = "qwen3.5:2b"; Context = 16384 },
    @{ Name = "qwen3.5-08b-8k"; Base = "qwen3.5:0.8b"; Context = 8192 },
    @{ Name = "gemma4-e4b-16k"; Base = "gemma4:e4b"; Context = 16384 }
)

function Write-Step { param($m) Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok   { param($m) Write-Host "  ok  $m" -ForegroundColor Green }
function Write-Warn2 { param($m) Write-Host "  !   $m" -ForegroundColor Yellow }
function Write-Fail { param($m) Write-Host "  x   $m" -ForegroundColor Red }

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source  = Join-Path $RepoDir "opencode\opencode.json"

Write-Step "Verificando o repositório"
if (-not (Test-Path -LiteralPath $Source)) {
    Write-Fail "config não encontrada: $Source"
    Write-Host "  Rode este script de dentro do repositório clonado."
    exit 1
}
Write-Ok "config: $Source"

Write-Step "Verificando pré-requisitos"
$missing = @()
foreach ($cmd in @("opencode", "ollama")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        Write-Ok ("{0}: {1}" -f $cmd, ((& $cmd --version 2>&1 | Select-Object -First 1) -join ""))
    } else {
        Write-Fail "$cmd não encontrado no PATH"
        $missing += $cmd
    }
}
if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "Instale antes de continuar:"
    if ($missing -contains "opencode") { Write-Host "  npm install -g @opencode/cli    # ou o instalador oficial" }
    if ($missing -contains "ollama")   { Write-Host "  https://ollama.com/download" }
    exit 1
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Warn2 "node não encontrado (só é necessário se o OpenCode foi instalado via npm)"
}

Write-Step "Instalando a configuração global"
$ConfigDir = Join-Path $env:USERPROFILE ".config\opencode"
$Target    = Join-Path $ConfigDir "opencode.json"
if (-not (Test-Path -LiteralPath $ConfigDir)) {
    New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
}

$Backup = ""
if (Test-Path -LiteralPath $Target) {
    $Backup = "{0}.bak.{1}" -f $Target, (Get-Date -Format "yyyyMMdd-HHmmss")
    Copy-Item -LiteralPath $Target -Destination $Backup -Force
    Write-Ok "backup do config atual: $Backup"
}

$linked = $false
if ($Link) {
    try {
        if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Force }
        New-Item -ItemType SymbolicLink -Path $Target -Target $Source -ErrorAction Stop | Out-Null
        Write-Ok "symlink: $Target -> $Source"
        $linked = $true
    } catch {
        Write-Warn2 "symlink falhou ($($_.Exception.Message)); usando cópia"
    }
}
if (-not $linked) {
    Copy-Item -LiteralPath $Source -Destination $Target -Force
    Write-Ok "config copiada: $Target"
}

# valida o JSON recém-instalado
try {
    $cfg = Get-Content -LiteralPath $Target -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $cfg.agents) { throw "bloco 'agents' ausente" }
    $names = @($cfg.agents.PSObject.Properties.Name)
    Write-Ok ("JSON válido, agentes: {0}" -f ($names -join ", "))
} catch {
    Write-Fail "o config instalado não é um JSON válido: $($_.Exception.Message)"
    if ($Backup -and (Test-Path -LiteralPath $Backup)) {
        Copy-Item -LiteralPath $Backup -Destination $Target -Force
        Write-Warn2 "config anterior restaurado de $Backup"
    }
    exit 1
}

Write-Step "Instalando o plugin de thinking do Ollama"
$PluginDir = Join-Path $ConfigDir "plugins"
New-Item -ItemType Directory -Path $PluginDir -Force | Out-Null
$PluginSource = Join-Path $RepoDir "opencode\plugins\ollama-nothink.ts"
if (Test-Path -LiteralPath $PluginSource) {
    Copy-Item -LiteralPath $PluginSource -Destination (Join-Path $PluginDir "ollama-nothink.ts") -Force
    Write-Ok "plugin copiado: $PluginDir\ollama-nothink.ts"
} else {
    Write-Warn2 "plugin não encontrado: $PluginSource"
}

Write-Step "Instalando os servidores MCP (run_tests e kb)"
$BinDir = Join-Path $HOME ".local\bin"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$Py = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } elseif (Get-Command py -ErrorAction SilentlyContinue) { "py -3" } else { $null }
if (-not $Py) { Write-Fail "python não encontrado (necessário para run_tests e kb)" }
$servers = @(
    @{ Name = "orq-run-tests"; Script = Join-Path $RepoDir "mcp\run_tests\server.py" },
    @{ Name = "orq-kb";        Script = Join-Path $RepoDir "mcp\kb\kb.py" },
    @{ Name = "orq-decisor";   Script = Join-Path $RepoDir "mcp\decisao\server.py" }
)
foreach ($s in $servers) {
    $launcher = Join-Path $BinDir ($s.Name + ".cmd")
    Set-Content -LiteralPath $launcher -Encoding ASCII -Value "@echo off`r`n$Py `"$($s.Script)`" %*"
    Write-Ok "launcher: $launcher"
}
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($userPath -split ";") -notcontains $BinDir) {
    [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $BinDir), "User")
    Write-Ok "PATH do usuário atualizado com $BinDir (reabra o OpenCode)"
} elseif (($env:PATH -split ";") -notcontains $BinDir) {
    Write-Warn2 "$BinDir está no PATH do usuário, mas não nesta sessão; reabra o OpenCode"
} else {
    Write-Ok "PATH já contém $BinDir"
}

if ($SkipModel) {
    Write-Step "Ollama: ignorado (-SkipModel)"
    Write-Warn2 "os subagentes esperam qwen3.5-4b-16k, qwen3.5-2b-16k, qwen3.5-08b-8k e gemma4-e4b-16k"
} else {
    $list = (& ollama list 2>&1 | Out-String)
    $prefix = "(?m)^\s*"
    foreach ($m in $Models) {
        $name = $m.Name
        $base = $m.Base
        $ctx  = $m.Context
        Write-Step "Garantindo o modelo local '$name' (ctx $ctx)"
        $exists = $list -match ($prefix + [regex]::Escape($name))
        if ($exists -and -not $Force) {
            Write-Ok "modelo '$name' já existe (use -Force para recriar)"
            continue
        }
        if ($list -notmatch ($prefix + [regex]::Escape($base))) {
            Write-Warn2 "modelo base '$base' não encontrado no Ollama"
            Write-Host "  1) ollama pull $base"
            Write-Host "  2) .\install.ps1            # cria o $name"
            continue
        }
        $mf = Join-Path $env:TEMP ("Modelfile-orquestrador-{0}" -f (Get-Random))
        "FROM $base`nPARAMETER num_ctx $ctx" | Out-File -LiteralPath $mf -Encoding ascii
        try {
            & ollama create $name -f $mf | Out-Host
            if ($LASTEXITCODE -ne 0) { throw "ollama create retornou $LASTEXITCODE" }
            Remove-Item -LiteralPath $mf -Force -ErrorAction SilentlyContinue
            Write-Ok "modelo '$name' criado com num_ctx $ctx"
        } catch {
            Remove-Item -LiteralPath $mf -Force -ErrorAction SilentlyContinue
            Write-Fail "falha ao criar o modelo '$name': $($_.Exception.Message)"
            Write-Host "  Crie manualmente:"
            Write-Host "    FROM $base"
            Write-Host "    PARAMETER num_ctx $ctx"
            Write-Host "    ollama create $name -f <arquivo>"
            exit 1
        }
    }
}

Write-Step "Checando a variável OPENCODE_CONFIG_CONTENT"
if ($env:OPENCODE_CONFIG_CONTENT) {
    Write-Warn2 "OPENCODE_CONFIG_CONTENT está definida ($($env:OPENCODE_CONFIG_CONTENT.Length) chars) e sobrepõe o arquivo"
    Write-Warn2 "antes de reiniciar, rode: Remove-Item Env:OPENCODE_CONFIG_CONTENT"
} else {
    Write-Ok "variável ausente (o arquivo é a fonte de verdade)"
}

Write-Step "Pronto"
Write-Host "  1. Reinicie o OpenCode:  opencode service restart"
Write-Host "  2. Escolha o modelo do orquestrador com /models"
Write-Host "  3. Valide o ambiente:    .\verify.ps1"
Write-Host ""
Write-Host "  Se os subagentes já estavam rodando, o Ollama vai recarregar o modelo no próximo uso."
