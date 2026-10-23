#Requires -Version 5.1
<#
.SYNOPSIS
    Instala a configuração global de orquestração do OpenCode (Windows).

.DESCRIPTION
    Copia opencode/opencode.json para %USERPROFILE%\.config\opencode\opencode.json,
    com backup do arquivo atual, e garante o modelo derivado do Ollama
    (qwen3-12k = qwen3:8b + num_ctx 12288), os agentes do Claude Code e as variáveis
    OLLAMA_* que dão 2 slots paralelos.

.PARAMETER BaseModel
    Modelo base do Ollama usado para derivar o modelo dos subagentes. Padrão: qwen3:8b

.PARAMETER Context
    Valor de num_ctx do modelo derivado. Padrão: 12288 (2 slots cabem 100% na GPU de 8 GB).
    O nome do modelo segue o contexto: 12288 -> qwen3-12k, 16384 -> qwen3-16k.

.PARAMETER SkipModel
    Não mexe no Ollama (a config é instalada do mesmo jeito).

.PARAMETER Link
    Tenta criar symlink em vez de copiar (exige modo Desenvolvedor ou admin).

.PARAMETER Force
    Recria o modelo derivado mesmo que já exista e sobrescreve variáveis OLLAMA_* já
    definidas com outro valor.

.PARAMETER OllamaParallel
    Requisições simultâneas por modelo no Ollama (OLLAMA_NUM_PARALLEL). Padrão: 2

.PARAMETER SkipOllamaEnv
    Não grava as variáveis OLLAMA_* de usuário.

.PARAMETER SkipClaude
    Não instala os agentes e a skill /orquestrar do Claude Code em ~/.claude.

.EXAMPLE
    .\install.ps1
    .\install.ps1 -Context 8192 -Force
    .\install.ps1 -SkipModel
    .\install.ps1 -OllamaParallel 3
#>
[CmdletBinding()]
param(
    [string]$BaseModel = "qwen3:8b",
    [int]$Context = 12288,
    [switch]$SkipModel,
    [switch]$Link,
    [switch]$Force,
    [ValidateRange(1, 8)]
    [int]$OllamaParallel = 2,
    [switch]$SkipOllamaEnv,
    [switch]$SkipClaude
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$ModelName = "qwen3-{0}k" -f [int]($Context / 1024)

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

if (-not (Select-String -LiteralPath $Target -SimpleMatch "`"ollama/${ModelName}:latest`"" -Quiet)) {
    Write-Warn2 "o config não aponta para ollama/${ModelName}:latest; ajuste agents.<id>.model"
}

if ($SkipModel) {
    Write-Step "Ollama: ignorado (-SkipModel)"
    Write-Warn2 "os subagentes esperam o modelo '$ModelName' já existente"
} else {
    Write-Step "Garantindo o modelo local '$ModelName' (ctx $Context)"
    $list = (& ollama list 2>&1 | Out-String)
    $prefix = "(?m)^\s*"
    $exists = $list -match ($prefix + [regex]::Escape($ModelName))

    if ($exists -and -not $Force) {
        Write-Ok "modelo '$ModelName' já existe (use -Force para recriar)"
    } elseif ($list -notmatch ($prefix + [regex]::Escape($BaseModel))) {
        Write-Warn2 "modelo base '$BaseModel' não encontrado no Ollama"
        Write-Host "  1) ollama pull $BaseModel"
        Write-Host "  2) .\install.ps1            # cria o $ModelName"
        Write-Host "  (a configuração do OpenCode já foi instalada)"
    } else {
        $mf = Join-Path $env:TEMP ("Modelfile-orquestrador-{0}" -f (Get-Random))
        "FROM $BaseModel`nPARAMETER num_ctx $Context" | Out-File -LiteralPath $mf -Encoding ascii
        try {
            # o ollama escreve o progresso no stderr; com "Stop" o PowerShell 5.1 aborta nisso
            $prevPref = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            & ollama create $ModelName -f $mf 2>$null | Out-Null
            $code = $LASTEXITCODE
            $ErrorActionPreference = $prevPref
            if ($code -ne 0) { throw "ollama create retornou $code" }
            Remove-Item -LiteralPath $mf -Force -ErrorAction SilentlyContinue
            Write-Ok "modelo '$ModelName' criado com num_ctx $Context"
        } catch {
            Remove-Item -LiteralPath $mf -Force -ErrorAction SilentlyContinue
            Write-Fail "falha ao criar o modelo: $($_.Exception.Message)"
            Write-Host "  Crie manualmente:"
            Write-Host "    FROM $BaseModel"
            Write-Host "    PARAMETER num_ctx $Context"
            Write-Host "    ollama create $ModelName -f <arquivo>"
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

# Slots do pipeline: o Ollama atende N requisições do mesmo modelo e enfileira o resto.
# KV cache em q8_0 (exige flash attention): 2 slots de 12k = 6,9 GB, 100% GPU na RX 7600.
$ollamaEnvChanged = $false
if ($SkipOllamaEnv) {
    Write-Step "Variáveis OLLAMA_*: ignorado (-SkipOllamaEnv)"
} else {
    Write-Step "Variáveis OLLAMA_* de usuário (slots = $OllamaParallel)"
    $wanted = [ordered]@{
        OLLAMA_NUM_PARALLEL      = "$OllamaParallel"
        OLLAMA_MAX_LOADED_MODELS = "1"
        OLLAMA_FLASH_ATTENTION   = "1"
        OLLAMA_KV_CACHE_TYPE     = "q8_0"
    }
    foreach ($name in $wanted.Keys) {
        $current = [Environment]::GetEnvironmentVariable($name, "User")
        if ($current -eq $wanted[$name]) {
            Write-Ok "$name=$current"
        } elseif ($current -and -not $Force) {
            Write-Warn2 "$name=$current mantido (esperado $($wanted[$name]); use -Force para trocar)"
        } else {
            [Environment]::SetEnvironmentVariable($name, $wanted[$name], "User")
            Write-Ok "$name=$($wanted[$name]) gravado"
            $ollamaEnvChanged = $true
        }
    }
}

function Install-Item {
    param([string]$From, [string]$To)
    if (Test-Path -LiteralPath $To) {
        $same = (Get-FileHash -LiteralPath $From).Hash -eq (Get-FileHash -LiteralPath $To).Hash
        if ($same) { Write-Ok "já atualizado: $To"; return }
        $bak = "{0}.bak.{1}" -f $To, (Get-Date -Format "yyyyMMdd-HHmmss")
        Copy-Item -LiteralPath $To -Destination $bak -Force
        Write-Ok "backup: $bak"
        Remove-Item -LiteralPath $To -Force
    }
    if ($Link) {
        try {
            New-Item -ItemType SymbolicLink -Path $To -Target $From -ErrorAction Stop | Out-Null
            Write-Ok "symlink: $To"
            return
        } catch {
            Write-Warn2 "symlink falhou ($($_.Exception.Message)); usando cópia"
        }
    }
    Copy-Item -LiteralPath $From -Destination $To -Force
    Write-Ok "copiado: $To"
}

if ($SkipClaude) {
    Write-Step "Claude Code: ignorado (-SkipClaude)"
} else {
    Write-Step "Instalando agentes e skill /orquestrar do Claude Code"
    $ClaudeDir = Join-Path $env:USERPROFILE ".claude"
    $AgentsDir = Join-Path $ClaudeDir "agents"
    $SkillDir  = Join-Path $ClaudeDir "skills\orquestrar"
    foreach ($d in @($AgentsDir, $SkillDir)) {
        if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
    }
    Get-ChildItem -LiteralPath (Join-Path $RepoDir "claude\agents") -Filter *.md | ForEach-Object {
        Install-Item -From $_.FullName -To (Join-Path $AgentsDir $_.Name)
    }
    Install-Item -From (Join-Path $RepoDir "claude\skills\orquestrar\SKILL.md") -To (Join-Path $SkillDir "SKILL.md")
}

Write-Step "Pronto"
Write-Host "  1. Reinicie o OpenCode:  opencode service restart"
Write-Host "  2. Escolha o modelo do orquestrador com /models"
Write-Host "  3. Valide o ambiente:    .\verify.ps1"
Write-Host ""
Write-Host "  Se os subagentes já estavam rodando, o Ollama vai recarregar o modelo no próximo uso."
if ($ollamaEnvChanged) {
    Write-Host "  Variáveis OLLAMA_* mudaram: feche o Ollama na bandeja e abra de novo para aplicar."
}
if (-not $SkipClaude) {
    Write-Host "  Claude Code: abra uma sessão nova e use /orquestrar <pedido>."
}
