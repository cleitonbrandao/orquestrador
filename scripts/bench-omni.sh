#!/usr/bin/env bash
# Benchmark multimodal de um modelo do Ollama: texto, imagem, áudio e fala.
# Equivale a scripts/bench-omni.ps1; a medição fica em scripts/bench_omni.py.
#
# Uso: scripts/bench-omni.sh <modelo> [--only text,image,audio,speech]
#                                   [--num-predict N] [--image IMG] [--audio WAV]
#                                   [--sem-salvar] [--listar]
#
# Diferente de scripts/testar-modelo.sh, que só mede texto: aqui cada etapa roda
# apenas se o modelo declarar a capacidade em /api/show (completion, vision,
# audio, speech). Modelos da família LFM3 exigem o runtime MLX e, no Ollama
# 0.40.12, só rodam em Apple Silicon — o script sai com código 3 e explica.
#
# Requisitos: ollama em execução, python3.
set -u -o pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=limpar-ram.sh
source "$RAIZ/scripts/limpar-ram.sh"

MODELO=""
ARGS=()
LISTAR=0

while [ $# -gt 0 ]; do
  case "$1" in
    --listar|-l) LISTAR=1; shift ;;
    --only|--num-predict|--image|--audio|--out)
      [ $# -ge 2 ] || { echo "faltou valor para $1" >&2; exit 2; }
      ARGS+=("$1" "$2"); shift 2 ;;
    -h|--help) sed -n '2,15p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*) ARGS+=("$1"); shift ;;
    *) if [ -z "$MODELO" ]; then MODELO="$1"; else ARGS+=("$1"); fi; shift ;;
  esac
done

command -v python3 >/dev/null || { echo "faltando: python3" >&2; exit 1; }
curl -s --max-time 5 "$API/api/version" >/dev/null || {
  echo "Ollama não responde em $API. Inicie com 'ollama serve'." >&2; exit 1; }

if [ "$LISTAR" = 1 ] || [ -z "$MODELO" ]; then
  echo
  echo "  Modelos instalados"
  echo
  for nome in $(curl -s "$API/api/tags" | python3 -c \
      'import json,sys; [print(m["name"]) for m in json.load(sys.stdin)["models"]]'); do
    caps=$(curl -s "$API/api/show" -d "{\"model\":\"$nome\"}" |
      python3 -c 'import json,sys; print(", ".join(json.load(sys.stdin).get("capabilities") or []))')
    printf '  %-28s %s\n' "$nome" "$caps"
  done
  echo
  echo "  benchmark: scripts/bench-omni.sh <modelo>"
  echo "  só texto:  scripts/testar-modelo.sh <modelo>"
  exit 0
fi

python3 -X utf8 -I "$RAIZ/scripts/bench_omni.py" --model "$MODELO" ${ARGS[@]+"${ARGS[@]}"}
codigo=$?

if [ "$codigo" -eq 3 ]; then
  echo ""
  echo "modelo Apple-only nesta versão do Ollama."
  echo "  A família LFM3 usa quantização nvfp4 e exige o runtime MLX."
  echo "  O Ollama 0.40.12 só a executa em Apple Silicon (release notes de 27/10/2026)."
  echo "  Detalhes em docs/TROUBLESHOOTING.md#modelo-exige-mlx."
fi
exit "$codigo"
