#!/usr/bin/env bash
# Instala a configuração global de orquestração do OpenCode (Linux/macOS).
#
# Copia opencode/opencode.json para ${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json
# com backup do arquivo atual, e garante o modelo derivado do Ollama
# (qwen3-12k = qwen3:8b + num_ctx 12288) e os agentes do Claude Code.
set -euo pipefail

BASE_MODEL="qwen3:8b"
CONTEXT=12288
SKIP_MODEL=0
LINK=0
FORCE=0
PARALLEL=2
SKIP_CLAUDE=0

usage() {
  cat <<EOF
Uso: ./install.sh [opções]

  --model <modelo>   modelo base do Ollama (padrão: $BASE_MODEL)
  --ctx <n>          num_ctx do modelo derivado (padrão: $CONTEXT)
  --no-model         não mexe no Ollama
  --link             cria symlink em vez de copiar (recomendado para editar no repo)
  --force            recria o modelo derivado mesmo que já exista
  --parallel <n>     slots simultâneos no Ollama (OLLAMA_NUM_PARALLEL, padrão: $PARALLEL)
  --no-claude        não instala os agentes e a skill /orquestrar do Claude Code
  -h, --help         esta ajuda
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --model)    BASE_MODEL="${2:?--model exige um valor}"; shift 2 ;;
    --ctx)      CONTEXT="${2:?--ctx exige um valor}"; shift 2 ;;
    --no-model) SKIP_MODEL=1; shift ;;
    --link)     LINK=1; shift ;;
    --force)    FORCE=1; shift ;;
    --parallel) PARALLEL="${2:?--parallel exige um valor}"; shift 2 ;;
    --no-claude) SKIP_CLAUDE=1; shift ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "Opção desconhecida: $1" >&2; usage >&2; exit 1 ;;
  esac
done

# o nome segue o contexto: 12288 -> qwen3-12k, 16384 -> qwen3-16k
MODEL_NAME="qwen3-$((CONTEXT / 1024))k"

step()  { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
ok()    { printf '  \033[32mok\033[0m  %s\n' "$1"; }
warn()  { printf '  \033[33m!\033[0m   %s\n' "$1"; }
fail()  { printf '  \033[31mx\033[0m   %s\n' "$1" >&2; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$REPO_DIR/opencode/opencode.json"

step "Verificando o repositório"
if [ ! -f "$SOURCE" ]; then
  fail "config não encontrada: $SOURCE"
  echo "  Rode este script de dentro do repositório clonado." >&2
  exit 1
fi
ok "config: $SOURCE"

step "Verificando pré-requisitos"
missing=0
for cmd in opencode ollama; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$cmd: $("$cmd" --version 2>&1 | head -n 1)"
  else
    fail "$cmd não encontrado no PATH"
    missing=1
  fi
done
if [ "$missing" -ne 0 ]; then
  echo "" >&2
  echo "Instale antes de continuar:" >&2
  echo "  opencode: https://opencode.ai/docs (ou npm install -g @opencode/cli)" >&2
  echo "  ollama:   https://ollama.com/download" >&2
  exit 1
fi
command -v node >/dev/null 2>&1 || warn "node não encontrado (só é necessário se o OpenCode foi instalado via npm)"

step "Instalando a configuração global"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
TARGET="$CONFIG_DIR/opencode.json"
mkdir -p "$CONFIG_DIR"

BACKUP=""
if [ -f "$TARGET" ]; then
  BACKUP="$TARGET.bak.$(date +%Y%m%d-%H%M%S)"
  cp -p "$TARGET" "$BACKUP"
  ok "backup do config atual: $BACKUP"
fi

if [ "$LINK" -eq 1 ]; then
  rm -f "$TARGET"
  if ln -s "$SOURCE" "$TARGET" 2>/dev/null; then
    ok "symlink: $TARGET -> $SOURCE"
  else
    warn "symlink falhou; usando cópia"
    cp "$SOURCE" "$TARGET"
    ok "config copiada: $TARGET"
  fi
else
  cp "$SOURCE" "$TARGET"
  ok "config copiada: $TARGET"
fi

# valida o JSON recém-instalado
valid=0
if command -v node >/dev/null 2>&1; then
  if node -e 'const c=require(process.argv[1]);if(!c.agents)process.exit(1);console.log("  ok  JSON válido, agentes: "+Object.keys(c.agents).join(", "))' "$TARGET"; then
    valid=1
  fi
elif command -v python3 >/dev/null 2>&1; then
  if python3 - "$TARGET" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
assert cfg.get("agents"), "bloco 'agents' ausente"
print("  ok  JSON válido, agentes: " + ", ".join(cfg["agents"].keys()))
PY
  then
    valid=1
  fi
else
  warn "nem node nem python3 disponíveis para validar o JSON"
  valid=1
fi

if [ "$valid" -eq 0 ]; then
  fail "o config instalado não é um JSON válido"
  if [ -n "$BACKUP" ]; then
    cp "$BACKUP" "$TARGET"
    warn "config anterior restaurado de $BACKUP"
  fi
  exit 1
fi

grep -q "\"ollama/$MODEL_NAME:latest\"" "$TARGET" || warn "o config não aponta para ollama/$MODEL_NAME:latest; ajuste agents.<id>.model"

if [ "$SKIP_MODEL" -eq 1 ]; then
  step "Ollama: ignorado (--no-model)"
  warn "os subagentes esperam o modelo '$MODEL_NAME' já existente"
else
  step "Garantindo o modelo local '$MODEL_NAME' (ctx $CONTEXT)"
  list="$(ollama list 2>&1 || true)"
  if printf '%s\n' "$list" | awk '{print $1}' | grep -qx "$MODEL_NAME\(:latest\)\?" && [ "$FORCE" -eq 0 ]; then
    ok "modelo '$MODEL_NAME' já existe (use --force para recriar)"
  elif ! printf '%s\n' "$list" | awk '{print $1}' | grep -qx "$BASE_MODEL\(:latest\)\?"; then
    warn "modelo base '$BASE_MODEL' não encontrado no Ollama"
    echo "  1) ollama pull $BASE_MODEL"
    echo "  2) ./install.sh            # cria o $MODEL_NAME"
    echo "  (a configuração do OpenCode já foi instalada)"
  else
    mf="$(mktemp)"
    printf 'FROM %s\nPARAMETER num_ctx %s\n' "$BASE_MODEL" "$CONTEXT" > "$mf"
    if ollama create "$MODEL_NAME" -f "$mf"; then
      rm -f "$mf"
      ok "modelo '$MODEL_NAME' criado com num_ctx $CONTEXT"
    else
      rm -f "$mf"
      fail "falha ao criar o modelo"
      echo "  Crie manualmente:" >&2
      echo "    FROM $BASE_MODEL" >&2
      echo "    PARAMETER num_ctx $CONTEXT" >&2
      echo "    ollama create $MODEL_NAME -f <arquivo>" >&2
      exit 1
    fi
  fi
fi

step "Checando a variável OPENCODE_CONFIG_CONTENT"
if [ -n "${OPENCODE_CONFIG_CONTENT:-}" ]; then
  warn "OPENCODE_CONFIG_CONTENT está definida (${#OPENCODE_CONFIG_CONTENT} chars) e sobrepõe o arquivo"
  warn "antes de reiniciar, rode: unset OPENCODE_CONFIG_CONTENT"
else
  ok "variável ausente (o arquivo é a fonte de verdade)"
fi

# Claude Code: agentes e skill /orquestrar em ~/.claude
install_item() {
  local from="$1" to="$2"
  if [ -e "$to" ] || [ -L "$to" ]; then
    if cmp -s "$from" "$to"; then ok "já atualizado: $to"; return; fi
    local bak="$to.bak.$(date +%Y%m%d-%H%M%S)"
    cp -pL "$to" "$bak" 2>/dev/null && ok "backup: $bak"
    rm -f "$to"
  fi
  if [ "$LINK" -eq 1 ] && ln -s "$from" "$to" 2>/dev/null; then
    ok "symlink: $to"
  else
    cp "$from" "$to"
    ok "copiado: $to"
  fi
}

if [ "$SKIP_CLAUDE" -eq 1 ]; then
  step "Claude Code: ignorado (--no-claude)"
else
  step "Instalando agentes e skill /orquestrar do Claude Code"
  AGENTS_DIR="$HOME/.claude/agents"
  SKILL_DIR="$HOME/.claude/skills/orquestrar"
  mkdir -p "$AGENTS_DIR" "$SKILL_DIR"
  for f in "$REPO_DIR"/claude/agents/*.md; do
    install_item "$f" "$AGENTS_DIR/$(basename "$f")"
  done
  install_item "$REPO_DIR/claude/skills/orquestrar/SKILL.md" "$SKILL_DIR/SKILL.md"
fi

# Verificadores por regra e redator de docs: usados pelo Claude Code e pelo OpenCode.
step "Instalando os scripts em ~/.orquestrador/scripts"
SCRIPTS_DIR="$HOME/.orquestrador/scripts"
mkdir -p "$SCRIPTS_DIR"
for f in "$REPO_DIR"/scripts/*.sh "$REPO_DIR"/scripts/*.ps1 "$REPO_DIR"/scripts/*.py; do
  [ -f "$f" ] && install_item "$f" "$SCRIPTS_DIR/$(basename "$f")"
done
chmod +x "$SCRIPTS_DIR"/*.sh "$SCRIPTS_DIR"/*.py 2>/dev/null || true
# no Windows, "python3" pode ser o atalho da Microsoft Store, que não roda nada
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" --version 2>&1 | grep -q "^Python 3"; then PY="$c"; break; fi
done
if [ -n "$PY" ]; then
  ok "$PY: $("$PY" --version 2>&1)"
else
  warn "Python 3 não encontrado: o redator de docs e o verificador de docs não rodam (a rota docs cai no exec-docs)"
fi

# Slots do pipeline: o Ollama roda como serviço (systemd/launchd), então as variáveis
# precisam ir para o serviço. Só mostramos o comando, sem sudo automático.
step "Variáveis OLLAMA_* (slots = $PARALLEL)"
if [ "${OLLAMA_NUM_PARALLEL:-}" = "$PARALLEL" ]; then
  ok "OLLAMA_NUM_PARALLEL=$PARALLEL neste shell"
else
  warn "aplique no serviço do Ollama e reinicie-o:"
  if command -v systemctl >/dev/null 2>&1; then
    echo "    sudo systemctl edit ollama    # cole em [Service]:"
    echo "      Environment=\"OLLAMA_NUM_PARALLEL=$PARALLEL\""
    echo "      Environment=\"OLLAMA_MAX_LOADED_MODELS=1\""
    echo "      Environment=\"OLLAMA_FLASH_ATTENTION=1\""
    echo "      Environment=\"OLLAMA_KV_CACHE_TYPE=q8_0\""
    echo "    sudo systemctl restart ollama"
  else
    echo "    launchctl setenv OLLAMA_NUM_PARALLEL $PARALLEL"
    echo "    launchctl setenv OLLAMA_MAX_LOADED_MODELS 1"
    echo "    launchctl setenv OLLAMA_FLASH_ATTENTION 1"
    echo "    launchctl setenv OLLAMA_KV_CACHE_TYPE q8_0"
    echo "    # depois feche e abra o app do Ollama"
  fi
fi

step "Pronto"
echo "  1. Reinicie o OpenCode:  opencode service restart"
echo "  2. Escolha o modelo do orquestrador com /models"
echo "  3. Valide o ambiente:    ./verify.sh"
echo ""
echo "  Se os subagentes já estavam rodando, o Ollama vai recarregar o modelo no próximo uso."
[ "$SKIP_CLAUDE" -eq 0 ] && echo "  Claude Code: abra uma sessão nova e use /orquestrar <pedido>."
exit 0
