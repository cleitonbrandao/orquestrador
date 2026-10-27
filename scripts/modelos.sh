#!/usr/bin/env bash
# Terminal interativo para testar modelos do Ollama. Digite /help para ver os comandos.
# Uso: scripts/modelos.sh      (NO_COLOR=1 desliga cores; ORQ_ICONS=unicode|ascii troca os ícones)
set -u

RAIZ="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
TESTAR="$RAIZ/scripts/testar-modelo.sh"
RELATORIO="$RAIZ/scripts/relatorio.py"
HIST="${XDG_STATE_HOME:-$HOME/.local/state}/orq-modelos.history"
CSV_ATUAL="${ORQ_RESULTADOS:-$RAIZ/docs/resultados}/resultados.csv"
export ORQ_CLI=1   # o testar-modelo.sh não abre outro terminal por cima deste
# shellcheck source=visual.sh
source "$RAIZ/scripts/visual.sh"
# shellcheck source=limpar-ram.sh
source "$RAIZ/scripts/limpar-ram.sh"

LIMPO=0

instalados() {
  nomes_testaveis | paste -sd, -
}

# cmd_linha <ícone> <cor> <comando> <descrição>
cmd_linha() { printf '  %s%s  %s%-17s%s %s%s%s\n' "$(fg "$2")" "$1" "$(neg)" "$3" "$(rs)" "$(dim)" "$4" "$(rs)"; }

banner() {
  echo
  titulo_pixel "MODELOS"
  echo
  pl_linha "$P_ROXO" "$P_TEXTO" "$I_CODIGO  Testador de modelos locais" "$P_ESCURO" "$P_CIANO" "Ollama · CPU"
  echo
  cmd_linha "$I_FRASCO" "$P_VERDE"  "/test <modelo>"  "teste completo: velocidade, qualidade e nota"
  cmd_linha "$I_BOLT"   "$P_AMAR"   "/bench <modelo>" "só velocidade (tok/s)"
  cmd_linha "$I_TROFEU" "$P_ROSA"   "/rank"           "ranking por tok/s, com a nota ao lado"
  cmd_linha "$I_TROFEU" "$P_ROSA"   "/nota"           "ranking por nota, com o tok/s ao lado"
  cmd_linha "$I_PAINEL" "$P_CIANO"  "/list"           "testados com nota e pendentes"
  cmd_linha "$I_PAINEL" "$P_CIANO"  "/report"         "relatório visual (HTML)"
  cmd_linha "$I_TROFEU" "$P_ROSA"   "/list-fluxo-ia"  "melhores duplas gerador + revisor"
  cmd_linha "$I_ENGR"   "$P_LARANJA" "/clean"         "libera RAM antes de testar"
  cmd_linha "$I_CODIGO" "$P_AZUL"   "/help  /quit"    "todos os comandos · sair"
  echo
}

# status: linha powerline mostrada antes de cada prompt.
status() {
  local ram n=0 melhor cor_ram parados args=()
  ram="$(mem_disp_mb)"
  cor_ram="$P_VERDE"; [ "$ram" -lt 5000 ] && cor_ram="$P_AMAR"; [ "$ram" -lt 3000 ] && cor_ram="$P_VERM"
  [ -f "$CSV_ATUAL" ] && n=$(( $(wc -l < "$CSV_ATUAL") - 1 ))
  args+=("$P_ROXO" "$P_TEXTO" "$I_CODIGO modelos")
  args+=("$cor_ram" "$P_BASE" "$I_RAM $(awk -v m="$ram" 'BEGIN{printf "%.1f", m/1024}')G livre")
  args+=("$P_ESCURO" "$P_CIANO" "$I_FRASCO $n teste(s)")
  if [ "$n" -gt 0 ]; then
    melhor="$(awk -F, 'NR>1 && $15+0>b {b=$15+0; m=$2} END{if(m) print m " " b}' "$CSV_ATUAL")"
    [ -n "$melhor" ] && args+=("$P_ESCURO" "$P_AMAR" "$I_TROFEU $melhor")
  fi
  if [ -s "$ESTADO" ]; then
    parados="$(wc -l < "$ESTADO")"
    args+=("$P_LARANJA" "$P_BASE" "$I_DOCKER $parados parado(s)")
  fi
  pl_linha "${args[@]}"
}

ajuda() {
  titulo() { printf '\n  %s%s%s\n' "$(fg "$1")$(neg)" "$2" "$(rs)"; }
  titulo "$P_VERDE" "$I_FRASCO  Testar"
  cmd_linha " " "$P_VERDE"  "/test [modelo]"  "teste completo (--think, --rapido, --sem-limpeza)"
  cmd_linha " " "$P_AMAR"   "/bench [modelo]" "só velocidade, sem salvar (também /benchmark)"
  titulo "$P_ROSA" "$I_TROFEU  Ver resultados"
  cmd_linha " " "$P_ROSA"   "/rank"           "ranking por tok/s, com barra e a nota ao lado"
  cmd_linha " " "$P_ROSA"   "/nota"           "ranking por nota, com tok/s, A-D e etapas em que serve"
  cmd_linha " " "$P_CIANO"  "/list"           "testados (com a nota) e instalados ainda sem teste"
  cmd_linha " " "$P_CIANO"  "/ver <modelo>"   "histórico completo de um modelo"
  cmd_linha " " "$P_CIANO"  "/report"         "gera docs/resultados/relatorio.html e abre no navegador"
  cmd_linha " " "$P_ROSA"   "/list-fluxo-ia"  "lista as melhores duplas gerador + revisor para o fluxo"
  titulo "$P_LARANJA" "$I_ENGR  Máquina"
  cmd_linha " " "$P_LARANJA" "/clean"         "libera RAM: Ollama, Docker, apps, cache e swap (pergunta antes)"
  cmd_linha " " "$P_LARANJA" "/restore"       "religa os containers que a limpeza parou (também ao sair)"
  cmd_linha " " "$P_LARANJA" "/ram"           "RAM disponível e o que está parado"
  cmd_linha " " "$P_LARANJA" "/prune"         "desinstala modelos reprovados (--dry-run, --min-qualidade, --min-toks)"
  cmd_linha " " "$P_LARANJA" "/reset [modelo]" "apaga os resultados dos testes desta máquina (ou só de um modelo)"
  titulo "$P_AZUL" "$I_CODIGO  Geral"
  cmd_linha " " "$P_AZUL"   "/help"           "esta lista"
  cmd_linha " " "$P_AZUL"   "/quit"           "sair (ou Ctrl-D); Ctrl-C interrompe o comando em andamento"
  printf '\n  %sAtalhos: /t /b /r /n /l /v /c /h /q. A limpeza roda uma vez por sessão, antes do primeiro\n  /test ou /bench. NO_COLOR=1 desliga cores; ORQ_ICONS=unicode|ascii troca os ícones.%s\n' "$(dim)" "$(rs)"
}

# alvo_de <args...>: primeiro argumento que não é opção (o modelo), se houver.
alvo_de() { local a; for a in "$@"; do [[ "$a" != -* ]] && { echo "$a"; return; }; done; }

# preparar <args...>: roda a limpeza uma vez por sessão, a menos que --sem-limpeza.
preparar() {
  local a
  for a in "$@"; do [ "$a" = "--sem-limpeza" ] && return 0; done
  [ "$LIMPO" = 1 ] && return 0
  limpar "$(alvo_de "$@")"
  LIMPO=1
  echo
}

sem_flag_limpeza() { local a; ARGS=(); for a in "$@"; do [ "$a" = "--sem-limpeza" ] || ARGS+=("$a"); done; }

sair() {
  history -w "$HIST" 2>/dev/null
  restaurar
}

[ -x "$TESTAR" ] || { echo "não achei $TESTAR" >&2; exit 1; }
mkdir -p "$(dirname "$HIST")"
history -r "$HIST" 2>/dev/null
trap 'echo' INT   # Ctrl-C interrompe o comando em andamento, não o terminal
trap sair EXIT

banner
if [ -s "$ESTADO" ]; then
  echo "${AMAR}${I_DOCKER} Há containers parados por uma limpeza anterior:${N}"
  sed 's/^/  /' "$ESTADO"
  echo "Eles serão religados ao sair, ou use /restore agora."
  echo
fi

# \001 e \002 marcam o que não ocupa coluna, para o readline não errar o cursor
PROMPT=$'\001'"$(fg "$P_CIANO")$(neg)"$'\002'"❯ "$'\001'"$(rs)"$'\002'
while true; do
  status
  read -e -r -p "$PROMPT" linha || { echo; break; }
  [ -n "$linha" ] || continue
  history -s "$linha"
  read -r -a partes <<< "$linha"
  cmd="${partes[0]}"
  args=("${partes[@]:1}")
  case "$cmd" in
    /test|/t)
      preparar "${args[@]}"; sem_flag_limpeza "${args[@]}"
      "$TESTAR" "${ARGS[@]}" ;;
    /bench|/benchmark|/b)
      preparar "${args[@]}"; sem_flag_limpeza "${args[@]}"
      "$TESTAR" --velocidade "${ARGS[@]}" ;;
    /rank|/r)   python3 -I "$RELATORIO" rank ;;
    /nota|/n)   python3 -I "$RELATORIO" nota ;;
    /list|/l)   python3 -I "$RELATORIO" lista --instalados "$(instalados)" ;;
    /ver|/v)    python3 -I "$RELATORIO" ver "${args[@]}" ;;
    /report)    python3 -I "$RELATORIO" html --instalados "$(instalados)" --abrir ;;
    /list-fluxo-ia | /fluxo) python "$RAIZ/scripts/fluxo_ia.py" ;;
    /clean|/c)  limpar "$(alvo_de "${args[@]}")"; LIMPO=1 ;;
    /restore)   restaurar ;;
    /ram)       estado ;;
    /prune|/remover) "$RAIZ/scripts/podar-modelos.sh" "${args[@]}" ;;
    /reset)     "$RAIZ/scripts/limpar-testes.sh" "${args[@]}" ;;
    /help|/h|/\?) ajuda ;;
    /quit|/exit|/q) break ;;
    /*)         echo "${VERM}${I_FALHA} comando desconhecido: $cmd${N} (digite /help)" ;;
    *)          echo "os comandos começam com /. Digite /help." ;;
  esac
  echo
done
