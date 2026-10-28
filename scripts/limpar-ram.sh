#!/usr/bin/env bash
# Libera RAM antes dos testes de modelos, para a medição de tok/s não ser distorcida.
#
# Uso: scripts/limpar-ram.sh [limpar [modelo-alvo] | restaurar | estado]
#   limpar     descarrega modelos do Ollama (automático) e pergunta antes de parar
#              containers Docker, fechar apps e limpar cache/swap (sudo)
#   restaurar  religa os containers que este script parou
#   estado     mostra o que está parado por este script
#
# Também pode ser carregado com `source` para usar as funções (limpar, restaurar, mem_disp_mb).
#
# Só age sobre o que lista e o usuário aprova. Nunca mexe em opencode, claude, ollama,
# gnome-shell nem no terminal: apps só entram se estiverem em APPS_LIMPAVEIS.
set -u -o pipefail

API="${OLLAMA_HOST_URL:-http://localhost:11434}"
ESTADO="${XDG_STATE_HOME:-$HOME/.local/state}/orq-limpeza.state"
APPS_LIMPAVEIS=(teams-linux chrome)

# gera_texto <modelo>: sucesso se o modelo gera texto; falha para embeddings (ex.: nomic-embed-text).
gera_texto() {
  curl -s --max-time 5 "$API/api/show" -d "$(jq -n --arg m "$1" '{model:$m}')" \
    | jq -e '(.capabilities // ["completion"]) | index("completion")' >/dev/null
}

# tem_decisao <modelo>: sucesso para modelos de decisão (/v1/systemone: d3, tev1, strands-decider).
tem_decisao() {
  curl -s --max-time 5 "$API/api/show" -d "$(jq -n --arg m "$1" '{model:$m}')" \
    | jq -e '.capabilities // [] | index("decision")' >/dev/null
}

# nomes_testaveis: modelos instalados que geram texto ou decidem, um por linha.
nomes_testaveis() {
  local n
  while read -r n; do
    { gera_texto "$n" || tem_decisao "$n"; } && echo "$n"
  done < <(curl -s --max-time 5 "$API/api/tags" | jq -r '.models[].name')
}

mem_disp_mb() { awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo; }
swap_usado_mb() { awk '/^SwapTotal:/{t=$2} /^SwapFree:/{f=$2} END{print int((t-f)/1024)}' /proc/meminfo; }

# confirmar <pergunta>: padrão é não; sem terminal (EOF) também é não.
confirmar() {
  local r
  read -r -p "$1 [s/N] " r || r=n
  [[ "$r" =~ ^[sSyY]$ ]]
}

situacao_ram() {
  printf 'RAM disponível: %s MB | swap em uso: %s MB\n' "$(mem_disp_mb)" "$(swap_usado_mb)"
}

limpar_ollama() {
  local alvo="${1:-}" nome
  curl -s --max-time 3 "$API/api/ps" >/dev/null || return 0
  while read -r nome; do
    [ -n "$nome" ] || continue
    [ "${nome%:latest}" = "${alvo%:latest}" ] && continue
    curl -s "$API/api/generate" -d "$(jq -n --arg m "$nome" '{model:$m, keep_alive:0}')" >/dev/null
    echo "  Ollama: descarregado $nome"
  done < <(curl -s "$API/api/ps" | jq -r '.models[]?.name')
}

limpar_docker() {
  command -v docker >/dev/null || return 0
  docker ps >/dev/null 2>&1 || { echo "  Docker: indisponível, etapa ignorada."; return 0; }
  local linhas nome mem escolhidos=() depois=()
  linhas="$(docker stats --no-stream --format '{{.Name}}	{{.MemUsage}}' 2>/dev/null)"
  [ -n "$linhas" ] || return 0
  echo "  Docker: containers em execução (serão religados no fim):"
  # a lista vai pelo fd 3; o fd 0 continua livre para as respostas do usuário
  while IFS=$'\t' read -r -u 3 nome mem; do
    if confirmar "    parar $nome (${mem%% /*})?"; then escolhidos+=("$nome"); fi
  done 3<<< "$linhas"
  # bancos por último na parada; religam primeiro (restaurar lê o estado de trás para frente)
  for nome in "${escolhidos[@]}"; do
    if [[ "$nome" =~ (postgres|sql|db|mysql|maria|redis) ]]; then depois+=("$nome"); fi
  done
  for nome in "${escolhidos[@]}"; do
    [[ "$nome" =~ (postgres|sql|db|mysql|maria|redis) ]] && continue
    parar_container "$nome"
  done
  for nome in "${depois[@]}"; do parar_container "$nome"; done
}

parar_container() {
  mkdir -p "$(dirname "$ESTADO")"
  if docker stop "$1" >/dev/null 2>&1; then
    echo "$1" >> "$ESTADO"
    echo "    parado: $1"
  else
    echo "    falhou ao parar: $1" >&2
  fi
}

limpar_apps() {
  local app pids kb mb
  for app in "${APPS_LIMPAVEIS[@]}"; do
    pids="$(pgrep -x "$app" | tr '\n' ',')"
    [ -n "$pids" ] || continue
    kb="$(ps -o rss= -p "${pids%,}" | awk '{s+=$1} END{print s+0}')"
    mb=$(( kb / 1024 ))
    echo "  App: $app usa ~${mb} MB (não será reaberto)."
    if confirmar "    fechar $app? Salve o trabalho antes."; then
      pkill -TERM -o -x "$app"
      sleep 3
      pgrep -x "$app" >/dev/null && echo "    $app ainda está fechando; feche manualmente se demorar."
    fi
  done
}

limpar_cache_swap() {
  confirmar "  Limpar cache de páginas e swap? (pede a senha do sudo)" || return 0
  sudo -v || { echo "    sem sudo, etapa ignorada."; return 0; }
  sync
  echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null && echo "    cache de páginas limpo"
  local swap disp
  swap="$(swap_usado_mb)"; disp="$(mem_disp_mb)"
  if [ "$swap" -le 0 ]; then
    echo "    swap já está vazio"
  elif [ "$swap" -lt $(( disp - 1024 )) ]; then
    echo "    esvaziando swap (${swap} MB)..."
    sudo swapoff -a && sudo swapon -a && echo "    swap esvaziado"
  else
    echo "    swap (${swap} MB) é grande demais para a RAM livre (${disp} MB); não esvaziado."
  fi
}

# limpar [modelo-alvo]: o modelo-alvo não é descarregado do Ollama.
limpar() {
  local antes depois
  antes="$(mem_disp_mb)"
  echo "Limpeza de RAM"
  echo "  Antes:  $(situacao_ram)"
  limpar_ollama "${1:-}"
  limpar_docker
  limpar_apps
  limpar_cache_swap
  depois="$(mem_disp_mb)"
  echo "  Depois: $(situacao_ram)"
  printf '  Ganho:  %+d MB de RAM disponível\n' "$(( depois - antes ))"
}

# restaurar: religa o que foi parado, bancos primeiro; mantém no estado o que falhar.
restaurar() {
  [ -s "$ESTADO" ] || { echo "Nada a restaurar."; return 0; }
  command -v docker >/dev/null && docker ps >/dev/null 2>&1 || {
    echo "Docker indisponível; containers continuam em $ESTADO" >&2; return 1; }
  local nome falhos=() esperas=()
  echo "Religando containers parados pela limpeza..."
  while read -r nome; do
    if docker start "$nome" >/dev/null 2>&1; then echo "  iniciado: $nome"; esperas+=("$nome")
    else echo "  falhou ao iniciar: $nome" >&2; falhos+=("$nome"); fi
  done < <(tac "$ESTADO")
  local i st
  for nome in "${esperas[@]}"; do
    for i in $(seq 1 30); do
      st="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}running{{end}}' "$nome" 2>/dev/null)"
      [ "$st" = "healthy" ] || [ "$st" = "running" ] && break
      sleep 2
    done
    echo "  $nome: ${st:-desconhecido}"
  done
  : > "$ESTADO"
  for nome in "${falhos[@]}"; do echo "$nome" >> "$ESTADO"; done
  [ ${#falhos[@]} -eq 0 ]
}

estado() {
  if [ -s "$ESTADO" ]; then
    echo "Parados por este script (use restaurar):"; sed 's/^/  /' "$ESTADO"
  else
    echo "Nada parado por este script."
  fi
  situacao_ram
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-limpar}" in
    limpar)    limpar "${2:-}" ;;
    restaurar) restaurar ;;
    estado)    estado ;;
    -h|--help) sed -n '2,13p' "${BASH_SOURCE[0]}" ;;
    *) echo "uso: limpar-ram.sh [limpar [modelo] | restaurar | estado]" >&2; exit 2 ;;
  esac
fi
