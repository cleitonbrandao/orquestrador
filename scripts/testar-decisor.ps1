# Testa um modelo de DECISÃO do Ollama (d3, tev1, strands-decider...): acerto em casos
# rotulados, taxa de escalada, latência e nota. Equivale a scripts/testar-decisor.sh.
#
# Uso: .\scripts\testar-decisor.ps1 d3:2b [-Casos ARQ] [-Split dev|teste|todos]
#                                        [-Amostra N] [-Limiar 0.7] [-Instrucoes "pergunta"]
#                                        [-Torneio] [-Visao IMG] [-Limpar]
#
# O trabalho é feito por scripts/testar_decisor.py (o mesmo no Linux). Método:
# docs/PLANO-TESTES-SUPORTE.md (trilha E).
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Resto
)

$RAIZ = Split-Path $PSScriptRoot -Parent
$PY = Join-Path $PSScriptRoot "testar_decisor.py"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) { Write-Host "python não encontrado no PATH."; exit 1 }

& $python.Source -I $PY @Resto
exit $LASTEXITCODE
