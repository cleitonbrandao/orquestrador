#!/usr/bin/env bash
# Apaga os resultados dos testes desta máquina (CSV e respostas brutas em docs/resultados).
#
# Uso: scripts/limpar-testes.sh [modelo] [--sim]
#   (sem modelo)  apaga todos os testes: o CSV, o relatório HTML e as pastas de respostas
#   modelo        apaga só os testes desse modelo (linhas do CSV e a pasta de respostas dele)
#   --sim         não pergunta antes (sem terminal interativo, nada é apagado sem --sim)
#
# Só mexe em resultados.csv, relatorio.html e nas pastas <modelo>/<data-hora> criadas pelos testes;
# não apaga mais nada, mesmo que ORQ_RESULTADOS aponte para outra pasta. Não desinstala modelos
# (para isso use /prune) e não pode ser desfeito.
set -u -o pipefail

RAIZ="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
SAIDA="${ORQ_RESULTADOS:-$RAIZ/docs/resultados}"
CSV="$SAIDA/resultados.csv"
# shellcheck source=visual.sh
source "$RAIZ/scripts/visual.sh"

MODELO=""; SIM=0
for arg in "$@"; do
  case "$arg" in
    --sim) SIM=1 ;;
    -h|--help) sed -n '2,12p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*) echo "opção desconhecida: $arg" >&2; exit 2 ;;
    *) MODELO="$arg" ;;
  esac
done

TS='^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}$'
# é pasta de resultados de teste: só tem subpastas com nome data-hora
pasta_de_teste() {
  local d="$1" c n=0
  for c in "$d"/*; do
    [ -e "$c" ] || return 1
    [ -d "$c" ] && [[ "$(basename "$c")" =~ $TS ]] || return 1
    n=$((n+1))
  done
  [ "$n" -gt 0 ]
}

if [ ! -d "$SAIDA" ]; then echo "Nenhum resultado salvo (${SAIDA})."; exit 0; fi

PASTAS=(); LINHAS=0
if [ -z "$MODELO" ]; then
  [ -f "$CSV" ] && LINHAS=$(( $(wc -l < "$CSV") - 1 ))
  for d in "$SAIDA"/*/; do
    d="${d%/}"; [ -d "$d" ] && pasta_de_teste "$d" && PASTAS+=("$d")
  done
  ALVO="todos os testes"
else
  norm="${MODELO%:latest}"
  # nomes exatos gravados no CSV para esse modelo (com e sem :latest, com e sem thinking)
  mapfile -t NOMES < <([ -f "$CSV" ] && awk -F, -v n="$norm" 'NR>1 { m=$2; sub(/:latest$/,"",m); if (m==n) print $2 }' "$CSV" | sort -u)
  LINHAS=$([ -f "$CSV" ] && awk -F, -v n="$norm" 'NR>1 { m=$2; sub(/:latest$/,"",m); if (m==n) c++ } END{print c+0}' "$CSV" || echo 0)
  for nome in "${NOMES[@]}"; do
    d="$SAIDA/${nome//[:\/]/_}"; [ -d "$d" ] && pasta_de_teste "$d" && PASTAS+=("$d")
  done
  ALVO="os testes de $MODELO"
fi

if [ "$LINHAS" -eq 0 ] && [ ${#PASTAS[@]} -eq 0 ]; then
  echo "Nada a apagar${MODELO:+ para $MODELO}."; exit 0
fi

echo
pl_linha "$P_VERM" "$P_BASE" "$I_FALHA  Limpar testes" "$P_ESCURO" "$P_CIANO" "${MODELO:-todos}"
echo
echo "  Serão apagados $ALVO: $LINHAS linha(s) no CSV e ${#PASTAS[@]} pasta(s) de respostas em ${SAIDA}."
echo "  ${DIM}Não pode ser desfeito. Modelos instalados não são afetados (use /prune para isso).${N}"
if [ "$SIM" != 1 ]; then
  [ -t 0 ] || { echo "  Sem terminal interativo: nada foi apagado (use --sim)."; exit 0; }
  read -r -p "  Apagar? [s/N] " r || r=n
  [[ "$r" =~ ^[sSyY]$ ]] || { echo "  Cancelado. Nada foi apagado."; exit 0; }
fi

for d in "${PASTAS[@]}"; do rm -rf -- "$d"; done
if [ -z "$MODELO" ]; then
  rm -f -- "$CSV" "$SAIDA/relatorio.html"
else
  if [ -f "$CSV" ]; then
    awk -F, -v n="${MODELO%:latest}" 'NR==1 { print; next } { m=$2; sub(/:latest$/,"",m); if (m!=n) print }' "$CSV" > "$CSV.tmp" && mv "$CSV.tmp" "$CSV"
    [ "$(wc -l < "$CSV")" -le 1 ] && rm -f -- "$CSV"
  fi
fi
rmdir "$SAIDA" 2>/dev/null
echo "  ${VERDE}${I_OK}${N} apagado: $ALVO."
