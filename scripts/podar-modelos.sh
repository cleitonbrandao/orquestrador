#!/usr/bin/env bash
# Desinstala do Ollama os modelos que reprovaram nos testes (docs/resultados/resultados.csv).
#
# Uso: scripts/podar-modelos.sh [--dry-run] [--min-qualidade N] [--min-toks N]
#   --dry-run          só mostra o que seria removido
#   --min-qualidade N  reprova com menos de N pontos de qualidade, de 60 (padrão 30)
#   --min-toks N       reprova abaixo de N tok/s de geração (padrão 8)
#
# Reprovado = melhor teste do modelo com qualidade < mínimo OU tok/s < mínimo.
# Nunca são candidatos: modelos usados no opencode.json, o modelo de embeddings do kb, modelos que
# não geram texto e modelos sem teste salvo. Pergunta antes de remover cada um; sem terminal
# interativo não remove nada. O histórico no CSV é mantido.
set -u -o pipefail

RAIZ="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
RELATORIO="$RAIZ/scripts/relatorio.py"
# shellcheck source=visual.sh
source "$RAIZ/scripts/visual.sh"
# shellcheck source=limpar-ram.sh
source "$RAIZ/scripts/limpar-ram.sh"

DRY=0; MIN_Q=30; MIN_T=8
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --min-qualidade) MIN_Q="${2:-}"; shift ;;
    --min-toks) MIN_T="${2:-}"; shift ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
  shift
done
[[ "$MIN_Q" =~ ^[0-9]+([.][0-9]+)?$ && "$MIN_T" =~ ^[0-9]+([.][0-9]+)?$ ]] || { echo "os mínimos devem ser números" >&2; exit 2; }

for cmd in ollama jq python3 curl; do command -v "$cmd" >/dev/null || { echo "faltando: $cmd" >&2; exit 1; }; done
curl -s --max-time 5 "$API/api/version" >/dev/null || { echo "Ollama não responde em $API." >&2; exit 1; }

# modelo em uso nas configs do OpenCode (ollama/<nome>)
em_uso() {
  local f
  for f in "$RAIZ/opencode/opencode.json" "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json"; do
    [ -f "$f" ] && jq -r '.. | .model? // empty | select(type=="string" and startswith("ollama/")) | ltrimstr("ollama/")' "$f" 2>/dev/null
  done | sort -u
}

# size_mb "1.1 GB" -> MB inteiros
size_mb() { awk -v s="$1" 'BEGIN{split(s,a," "); v=a[1]+0; u=a[2]; if(u=="GB")v*=1024; else if(u=="KB")v/=1024; printf "%d", v}'; }
# blob_de <modelo>: linha FROM (caminho do blob) do modelfile
blob_de() { ollama show "$1" --modelfile 2>/dev/null | awk '/^FROM /{print $2; exit}'; }
disco_livre_mb() { df -BM --output=avail "${OLLAMA_MODELS_DIR:-/usr/share/ollama}" 2>/dev/null | awk 'NR==2{gsub("M","",$1); print $1+0}'; }

mapfile -t INSTALADOS < <(ollama list | awk 'NR>1{print $1}')
declare -A TAM
while read -r nome t1 t2; do TAM["$nome"]="$t1 $t2"; done < <(ollama list | awk 'NR>1{print $1, $3, $4}')

REPROVADOS="$(python3 -I "$RELATORIO" reprovados --min-qualidade "$MIN_Q" --min-toks "$MIN_T" \
  --instalados "$(IFS=,; echo "${INSTALADOS[*]}")")"

mapfile -t USO < <(em_uso)
EMBED="${ORQ_EMBED_MODEL:-nomic-embed-text}"

CAND=(); PROT=()
declare -A Q T MOTIVO LIBERA
while IFS=$'\t' read -r nome q t motivo; do
  [ -n "$nome" ] || continue
  prot=""
  for u in "${USO[@]}"; do [ "${u%:latest}" = "${nome%:latest}" ] && prot="usado no opencode.json"; done
  [ "${nome%:latest}" = "${EMBED%:latest}" ] && prot="modelo de embeddings do kb"
  gera_texto "$nome" || prot="não gera texto"
  Q[$nome]="$q"; T[$nome]="$t"; MOTIVO[$nome]="$motivo"
  if [ -n "$prot" ]; then PROT+=("$nome|$prot"); continue; fi
  # pesos compartilhados com outro modelo instalado: remover não libera espaço
  mine="$(blob_de "$nome")"; LIBERA[$nome]="${TAM[$nome]}"
  for o in "${INSTALADOS[@]}"; do
    [ "$o" = "$nome" ] && continue
    [ -n "$mine" ] && [ "$(blob_de "$o")" = "$mine" ] && { LIBERA[$nome]="0 (pesos compartilhados com $o)"; break; }
  done
  CAND+=("$nome")
done <<< "$REPROVADOS"

echo
pl_linha "$P_VERM" "$P_BASE" "$I_FALHA  Modelos reprovados" "$P_ESCURO" "$P_CIANO" "qualidade < $MIN_Q/60 ou < $MIN_T tok/s"
echo
if [ ${#CAND[@]} -eq 0 ]; then
  echo "  Nenhum modelo instalado reprovou (ou todos os reprovados estão protegidos)."
else
  printf "  %s%-26s %9s %7s  %-9s  %s%s\n" "$(neg)" "MODELO" "QUALID." "TOK/S" "TAMANHO" "MOTIVO" "$(rs)"
  for nome in "${CAND[@]}"; do
    printf "  %-26s %6s/60 %7s  %-9s  %s%s%s\n" "$nome" "${Q[$nome]}" "${T[$nome]}" "${TAM[$nome]}" "$(dim)" "${MOTIVO[$nome]}" "$(rs)"
    case "${LIBERA[$nome]}" in 0*) printf "  %s%s não libera espaço: %s%s\n" "$(dim)" "└─" "${LIBERA[$nome]#0 }" "$(rs)" ;; esac
  done
fi
if [ ${#PROT[@]} -gt 0 ]; then
  echo
  echo "  ${DIM}Reprovados, mas protegidos (não serão removidos):${N}"
  for p in "${PROT[@]}"; do printf "  %s%s %-24s %s%s\n" "$(dim)" "•" "${p%%|*}" "${p#*|}" "$(rs)"; done
fi

[ ${#CAND[@]} -gt 0 ] || exit 0
if [ "$DRY" = 1 ]; then
  echo; echo "${DIM}  --dry-run: nada foi removido.${N}"; exit 0
fi
if [ ! -t 0 ]; then
  echo; echo "  Sem terminal interativo: nada foi removido (use --dry-run para só listar)."; exit 0
fi

echo
ESCOLHIDOS=(); total=0
for nome in "${CAND[@]}"; do
  read -r -p "  Remover $nome? [s/N] " r || r=n
  if [[ "$r" =~ ^[sSyY]$ ]]; then
    ESCOLHIDOS+=("$nome")
    case "${LIBERA[$nome]}" in 0*) ;; *) total=$(( total + $(size_mb "${LIBERA[$nome]}") )) ;; esac
  fi
done
if [ ${#ESCOLHIDOS[@]} -eq 0 ]; then echo; echo "  Nada selecionado. Nada foi removido."; exit 0; fi

echo
echo "  Serão removidos: ${ESCOLHIDOS[*]}  (libera ~${total} MB)"
read -r -p "  Confirmar a remoção? [s/N] " r || r=n
[[ "$r" =~ ^[sSyY]$ ]] || { echo "  Cancelado. Nada foi removido."; exit 0; }

antes="$(disco_livre_mb)"; falhas=0
for nome in "${ESCOLHIDOS[@]}"; do
  if ollama rm "$nome" >/dev/null 2>&1; then echo "  ${VERDE}${I_OK}${N} removido: $nome"
  else echo "  ${VERM}${I_FALHA}${N} falhou ao remover: $nome" >&2; falhas=$((falhas+1)); fi
done
depois="$(disco_livre_mb)"
echo
echo "  ${DIM}Espaço livre: ${antes:-?} MB → ${depois:-?} MB. Histórico dos testes mantido em docs/resultados/resultados.csv.${N}"
[ "$falhas" -eq 0 ]
