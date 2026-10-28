#!/usr/bin/env bash
# Testa um modelo de DECISÃO do Ollama (d3, tev1, strands-decider...): acerto em casos
# rotulados, taxa de escalada, latência e nota. Não mede tok/s — esses modelos não geram texto.
#
# Uso: scripts/testar-decisor.sh [modelo] [--casos ARQ] [--split dev|teste|todos]
#                                [--amostra N] [--limiar 0.7] [--instrucoes "pergunta"]
#                                [--torneio] [--visao IMG] [--limpar]
#
# O trabalho é feito por scripts/testar_decisor.py (o mesmo no Windows). Este script só
# cuida do --limpar, que depende da máquina.
# Método e critérios: docs/PLANO-TESTES-SUPORTE.md (trilha E).
# Requisitos: ollama em execução, python3.
set -u -o pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=limpar-ram.sh
source "$RAIZ/scripts/limpar-ram.sh"

LIMPAR=0
MODELO=""
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --limpar) LIMPAR=1; shift ;;
    --casos|--split|--amostra|--limiar|--instrucoes|--visao|--p50-escalada|--baseline-ms|--saida)
      ARGS+=("$1")
      [ $# -ge 2 ] && ARGS+=("$2")
      shift 2 ;;
    -h|--help) sed -n '2,14p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) if [ -z "$MODELO" ] && [[ "$1" != -* ]]; then MODELO="$1"; fi
       ARGS+=("$1"); shift ;;
  esac
done

command -v python3 >/dev/null || { echo "faltando: python3" >&2; exit 1; }
curl -s --max-time 5 "$API/api/version" >/dev/null || {
  echo "Ollama não responde em $API. Inicie com 'ollama serve'." >&2; exit 1; }

if [ "$LIMPAR" = 1 ]; then
  echo
  limpar "$MODELO"
  trap 'restaurar' EXIT
fi

python3 -I "$RAIZ/scripts/testar_decisor.py" "${ARGS[@]}"
