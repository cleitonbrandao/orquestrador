#!/usr/bin/env bash
# Tema visual compartilhado (use com `source`): estilo powerline / oh-my-posh, cores truecolor,
# ícones Nerd Font e título em pixel art. Variáveis de ambiente:
#   NO_COLOR=1                    sem cores nem ícones (texto puro)
#   ORQ_ICONS=nerd|unicode|ascii  força o conjunto de ícones (padrão: detecta Nerd Font)
# Os glifos Nerd Font estão em bytes UTF-8 (\x..) para funcionar em qualquer locale.

V_COR=1
{ [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; } || V_COR=0

# --- paleta (r;g;b), tons de pixel art ---
P_BASE="30;30;46";   P_TEXTO="205;214;244"; P_CINZA="88;91;112";  P_ESCURO="49;50;68"
P_ROXO="137;88;245"; P_CIANO="34;211;238";  P_VERDE="74;222;128"; P_AMAR="250;204;21"
P_ROSA="244;114;182"; P_VERM="248;113;113"; P_LARANJA="251;146;60"; P_AZUL="96;165;250"

fg() { [ "$V_COR" = 1 ] && printf '\033[38;2;%sm' "$1"; return 0; }
bg() { [ "$V_COR" = 1 ] && printf '\033[48;2;%sm' "$1"; return 0; }
rs() { [ "$V_COR" = 1 ] && printf '\033[0m'; return 0; }
neg() { [ "$V_COR" = 1 ] && printf '\033[1m'; return 0; }
dim() { [ "$V_COR" = 1 ] && printf '\033[2m'; return 0; }

# --- ícones ---
_icones_modo() {
  [ -n "${ORQ_ICONS:-}" ] && { echo "$ORQ_ICONS"; return; }
  # captura antes do grep: `grep -q` fecha o pipe cedo e, com pipefail, daria falso negativo
  local fontes=""
  command -v fc-list >/dev/null 2>&1 && fontes="$(fc-list 2>/dev/null)"
  [[ "${fontes,,}" == *nerd* ]] && { echo nerd; return; }
  case "${LC_ALL:-${LANG:-}}" in *UTF-8*|*utf8*) echo unicode ;; *) echo ascii ;; esac
}
case "$(_icones_modo)" in
  nerd)
  I_CAP_E=$'\xee\x82\xb6'
  I_SEP=$'\xee\x82\xb0'
  I_CAP_D=$'\xee\x82\xb4'
  I_CHIP=$'\xef\x8b\x9b'
  I_BOLT=$'\xef\x83\xa7'
  I_TROFEU=$'\xef\x82\x91'
  I_CHECK=$'\xef\x80\x8c'
  I_XIS=$'\xef\x80\x8d'
  I_FRASCO=$'\xef\x83\x83'
  I_DOCKER=$'\xee\x9e\xb0'
  I_BANCO=$'\xef\x87\x80'
  I_RELOGIO=$'\xef\x80\x97'
  I_CODIGO=$'\xef\x84\xa1'
  I_ENGR=$'\xef\x82\x85'
  I_PAINEL=$'\xef\x83\xa4'
  S_CAP_E="$I_CAP_E"; S_SEP="$I_SEP"; S_CAP_D="$I_SEP"
  I_OK="$I_CHECK"; I_FALHA="$I_XIS"; I_RAM="$I_CHIP"; I_RAPIDO="$I_BOLT"; I_NOTA="$I_TROFEU"
  I_TESTE="$I_FRASCO"; I_PRONTO="$I_CHECK"
  ;;
  unicode)
  S_CAP_E="▐"; S_SEP="▌"; S_CAP_D="▌"
  I_OK="✔"; I_FALHA="✘"; I_RAM="▣"; I_RAPIDO="▲"; I_NOTA="★"; I_TESTE="◆"; I_PRONTO="✔"
  I_DOCKER="▤"; I_BANCO="▤"; I_RELOGIO="◷"; I_CODIGO="‹›"; I_ENGR="⚙"; I_PAINEL="▦"
  I_FRASCO="◆"; I_BOLT="▲"; I_TROFEU="★"; I_CHIP="▣"; I_CHECK="✔"; I_XIS="✘"
  ;;
  *)
  S_CAP_E="["; S_SEP=""; S_CAP_D="]"
  I_OK="+"; I_FALHA="x"; I_RAM="#"; I_RAPIDO="^"; I_NOTA="*"; I_TESTE="*"; I_PRONTO="+"
  I_DOCKER="d"; I_BANCO="d"; I_RELOGIO="t"; I_CODIGO="c"; I_ENGR="o"; I_PAINEL="="
  I_FRASCO="*"; I_BOLT="^"; I_TROFEU="*"; I_CHIP="#"; I_CHECK="+"; I_XIS="x"
  ;;
esac

# pl_linha <bg> <fg> <texto> [<bg> <fg> <texto> ...]: segmentos powerline numa linha.
pl_linha() {
  local primeiro=1 bgp="" bgc fgc txt
  if [ "$V_COR" = 0 ]; then
    while [ $# -ge 3 ]; do printf '[%s] ' "$3"; shift 3; done
    echo; return
  fi
  while [ $# -ge 3 ]; do
    bgc="$1"; fgc="$2"; txt="$3"; shift 3
    if [ "$primeiro" = 1 ]; then fg "$bgc"; printf '%s' "$S_CAP_E"; primeiro=0
    else fg "$bgp"; bg "$bgc"; printf '%s' "$S_SEP"; fi
    bg "$bgc"; fg "$fgc"; neg; printf ' %s ' "$txt"; rs
    bgp="$bgc"
  done
  fg "$bgp"; printf '%s' "$S_CAP_D"; rs; echo
}

# pilula <bg> <fg> <texto>: um segmento isolado, sem quebra de linha.
pilula() {
  if [ "$V_COR" = 0 ]; then printf '[%s]' "$3"; return; fi
  fg "$1"; printf '%s' "$S_CAP_E"; bg "$1"; fg "$2"; neg; printf ' %s ' "$3"; rs; fg "$1"; printf '%s' "$S_CAP_D"; rs
}

# barra_v <valor> <máximo> <largura> <cor>: barra de blocos preenchida na cor dada.
barra_v() {
  awk -v v="$1" -v m="$2" -v w="${3:-20}" 'BEGIN{n=int(v/m*w+0.5); if(n>w)n=w; if(n<0)n=0; for(i=0;i<n;i++)printf "█"; print " " n}' \
    | { read -r cheio n; fg "${4:-$P_CIANO}"; printf '%s' "$cheio"; rs; dim; for ((i=n; i<${3:-20}; i++)); do printf '░'; done; rs; }
}

# cor_nota <0-100>: devolve a cor da paleta para a nota.
cor_nota() { if [ "$1" -ge 70 ]; then echo "$P_VERDE"; elif [ "$1" -ge 40 ]; then echo "$P_AMAR"; else echo "$P_VERM"; fi; }

# --- título em pixel art (fonte 3x5, pixels de 2 colunas, gradiente rosa → ciano) ---
declare -A _PX=(
  [M]="X.X XXX XXX X.X X.X" [O]="XXX X.X X.X X.X XXX" [D]="XX. X.X X.X X.X XX."
  [E]="XXX X.. XX. X.. XXX" [L]="X.. X.. X.. X.. XXX" [S]="XXX X.. XXX ..X XXX"
  [T]="XXX .X. .X. .X. .X." [N]="XX. X.X X.X X.X X.X" [A]="XXX X.X XXX X.X X.X"
  [R]="XX. X.X XX. X.X X.X" [K]="X.X X.X XX. X.X X.X" [I]="XXX .X. .X. .X. XXX"
  [B]="XX. X.X XX. X.X XX." [C]="XXX X.. X.. X.. XXX" [P]="XXX X.X XXX X.. X.."
  [H]="X.X X.X XXX X.X X.X" [Q]="XXX X.X X.X XXX ..X" [U]="X.X X.X X.X X.X XXX"
  [" "]="... ... ... ... ..."
)
_GRAD=("244;114;182" "206;125;214" "168;139;238" "110;172;240" "34;211;238")

# titulo_pixel <TEXTO>: desenha o texto (letras A-Z do conjunto acima) em 5 linhas.
titulo_pixel() {
  local texto="$1" linha ch i j px celula out
  for linha in 0 1 2 3 4; do
    out=""
    for ((i=0; i<${#texto}; i++)); do
      ch="${texto:i:1}"; px="${_PX[$ch]:-${_PX[" "]}}"
      read -r -a linhas_px <<< "$px"
      celula="${linhas_px[$linha]}"
      for ((j=0; j<3; j++)); do
        if [ "${celula:j:1}" = "X" ]; then out+="██"; else out+="  "; fi
      done
      out+="  "
    done
    [ "$V_COR" = 1 ] && { fg "${_GRAD[$linha]}"; neg; }
    printf '  %s' "$out"; rs; echo
  done
}

# cores_basicas: define N NEG DIM VERDE AMAR VERM CIANO ROXO ROSA para usar dentro de strings.
cores_basicas() {
  N="$(rs)"; NEG="$(neg)"; DIM="$(dim)"
  VERDE="$(fg "$P_VERDE")"; AMAR="$(fg "$P_AMAR")"; VERM="$(fg "$P_VERM")"
  CIANO="$(fg "$P_CIANO")"; ROXO="$(fg "$P_ROXO")"; ROSA="$(fg "$P_ROSA")"
}
cores_basicas
