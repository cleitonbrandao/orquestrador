#!/usr/bin/env bash
# Instala a configuração global de orquestração do OpenCode (Linux/macOS).
#
# Copia opencode/opencode.json e opencode/plugins/ollama-nothink.ts para
# ${XDG_CONFIG_HOME:-$HOME/.config}/opencode, com backup do arquivo atual, e
# garante os modelos derivados do Ollama usados pelos subagentes:
#   qwen3.5-4b-16k  = qwen3.5:4b + num_ctx 16384   (decompositor, local-helper)
#   qwen3.5-2b-16k  = qwen3.5:2b + num_ctx 16384   (revisor)
#   qwen3.5-08b-8k  = qwen3.5:0.8b + num_ctx 8192  (local-mini)
#   gemma4-e4b-16k  = gemma4:e4b + num_ctx 16384   (exec-local, exec-docs)
set -euo pipefail

BASE_MODEL="qwen3.5:4b"
CONTEXT=16384
SKIP_MODEL=0
LINK=0
FORCE=0
CLAUDE=0

usage() {
  cat <<EOF
Uso: ./install.sh [opções]

  --model <modelo>   base do qwen3.5-4b-16k (padrão: $BASE_MODEL)
  --ctx <n>          num_ctx do qwen3.5-4b-16k (padrão: $CONTEXT)
  --no-model         não mexe no Ollama
  --link             cria symlink em vez de copiar (recomendado para editar no repo)
  --claude           registra MCP e subagente no Claude Code (escopo user)
  --force            recria o modelo derivado mesmo que já exista
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
    --claude)   CLAUDE=1; shift ;;
    -h|--help)  usage; exit 0 ;;
    *) echo "Opção desconhecida: $1" >&2; usage >&2; exit 1 ;;
  esac
done

MODEL_NAMES=("qwen3.5-4b-16k" "qwen3.5-2b-16k" "qwen3.5-08b-8k" "gemma4-e4b-16k")
MODEL_BASES=("$BASE_MODEL" "qwen3.5:2b" "qwen3.5:0.8b" "gemma4:e4b")
MODEL_CTXS=("$CONTEXT" "16384" "8192" "16384")

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

step "Instalando o plugin de thinking do Ollama"
PLUGIN_DIR="$CONFIG_DIR/plugins"
mkdir -p "$PLUGIN_DIR"
PLUGIN_SOURCE="$REPO_DIR/opencode/plugins/ollama-nothink.ts"
if [ -f "$PLUGIN_SOURCE" ]; then
  cp "$PLUGIN_SOURCE" "$PLUGIN_DIR/ollama-nothink.ts"
  ok "plugin copiado: $PLUGIN_DIR/ollama-nothink.ts"
else
  warn "plugin não encontrado: $PLUGIN_SOURCE"
fi

step "Instalando o servidor MCP run_tests"
BIN_DIR="${HOME}/.local/bin"
mkdir -p "$BIN_DIR"
chmod +x "$REPO_DIR/mcp/run_tests/server.py"
ln -sf "$REPO_DIR/mcp/run_tests/server.py" "$BIN_DIR/orq-run-tests"
ok "launcher: $BIN_DIR/orq-run-tests -> mcp/run_tests/server.py"
chmod +x "$REPO_DIR/mcp/kb/kb.py"
ln -sf "$REPO_DIR/mcp/kb/kb.py" "$BIN_DIR/orq-kb"
ok "launcher: $BIN_DIR/orq-kb -> mcp/kb/kb.py"
chmod +x "$REPO_DIR/mcp/decisao/server.py"
ln -sf "$REPO_DIR/mcp/decisao/server.py" "$BIN_DIR/orq-decisor"
ok "launcher: $BIN_DIR/orq-decisor -> mcp/decisao/server.py"
command -v python3 >/dev/null 2>&1 || fail "python3 não encontrado (necessário para o run_tests)"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "$BIN_DIR não está no PATH; o OpenCode não achará orq-run-tests/orq-kb/orq-decisor" ;; esac

if [ "$SKIP_MODEL" -eq 1 ]; then
  step "Ollama: ignorado (--no-model)"
  warn "os subagentes esperam qwen3.5-4b-16k, qwen3.5-2b-16k, qwen3.5-08b-8k e gemma4-e4b-16k"
else
  list="$(ollama list 2>&1 || true)"
  for i in "${!MODEL_NAMES[@]}"; do
    name="${MODEL_NAMES[$i]}"
    base="${MODEL_BASES[$i]}"
    ctx="${MODEL_CTXS[$i]}"
    step "Garantindo o modelo local '$name' (ctx $ctx)"
    if printf '%s\n' "$list" | awk '{print $1}' | grep -qx "$name\(:latest\)\?" && [ "$FORCE" -eq 0 ]; then
      ok "modelo '$name' já existe (use --force para recriar)"
      continue
    fi
    if ! printf '%s\n' "$list" | awk '{print $1}' | grep -qx "$base\(:latest\)\?"; then
      warn "modelo base '$base' não encontrado no Ollama"
      echo "  1) ollama pull $base"
      echo "  2) ./install.sh            # cria o $name"
      continue
    fi
    mf="$(mktemp)"
    printf 'FROM %s\nPARAMETER num_ctx %s\n' "$base" "$ctx" > "$mf"
    if ollama create "$name" -f "$mf"; then
      rm -f "$mf"
      ok "modelo '$name' criado com num_ctx $ctx"
    else
      rm -f "$mf"
      fail "falha ao criar o modelo '$name'"
      echo "  Crie manualmente:" >&2
      echo "    FROM $base" >&2
      echo "    PARAMETER num_ctx $ctx" >&2
      echo "    ollama create $name -f <arquivo>" >&2
      exit 1
    fi
  done
fi

if [ "$CLAUDE" -eq 1 ]; then
  step "Integrando com o Claude Code"
  if ! command -v claude >/dev/null 2>&1; then
    warn "claude não encontrado no PATH; pulando"
  else
    mkdir -p "$HOME/.claude/agents"
    cp "$REPO_DIR/claude/agents/triagem.md" "$HOME/.claude/agents/triagem.md"
    ok "subagente: ~/.claude/agents/triagem.md"
    claude mcp remove --scope user run_tests >/dev/null 2>&1 || true
    claude mcp remove --scope user kb >/dev/null 2>&1 || true
    claude mcp add --scope user run_tests -- "$BIN_DIR/orq-run-tests" >/dev/null && ok "MCP run_tests registrado (user)" || warn "falha ao registrar run_tests"
    claude mcp add --scope user kb -- "$BIN_DIR/orq-kb" serve >/dev/null && ok "MCP kb registrado (user)" || warn "falha ao registrar kb"
    if command -v python3 >/dev/null 2>&1; then
      REPO_DIR="$REPO_DIR" python3 - <<'PY'
import json, os, re
home, repo = os.path.expanduser("~"), os.environ["REPO_DIR"]
sp = os.path.join(home, ".claude", "settings.json")
d = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
allow = d.setdefault("permissions", {}).setdefault("allow", [])
for x in ("mcp__run_tests__run_tests", "mcp__kb__search_kb", "mcp__kb__list_apps"):
    if x not in allow:
        allow.append(x)
json.dump(d, open(sp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
open(sp, "a").write("\n")
print("  ok  permissões MCP em ~/.claude/settings.json")
mp = os.path.join(home, ".claude", "CLAUDE.md")
block = "<!-- orquestrador:begin -->\n" + open(os.path.join(repo, "claude", "CLAUDE.snippet.md"), encoding="utf-8").read().strip() + "\n<!-- orquestrador:end -->\n"
cur = open(mp, encoding="utf-8").read() if os.path.exists(mp) else ""
if "orquestrador:begin" in cur:
    cur = re.sub(r"<!-- orquestrador:begin -->.*?<!-- orquestrador:end -->\n", lambda m: block, cur, flags=re.S)
else:
    cur = (cur.rstrip() + "\n\n" if cur.strip() else "") + block
open(mp, "w", encoding="utf-8").write(cur)
print("  ok  bloco do orquestrador em ~/.claude/CLAUDE.md (idempotente)")
PY
    else
      warn "python3 ausente: adicione manualmente as permissões e o claude/CLAUDE.snippet.md"
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

step "Pronto"
echo "  1. Reinicie o OpenCode:  opencode service restart"
echo "  2. Escolha o modelo do orquestrador com /models"
echo "  3. Valide o ambiente:    ./verify.sh"
echo ""
echo "  Se os subagentes já estavam rodando, o Ollama vai recarregar o modelo no próximo uso."
