#!/usr/bin/env bash
# Valida a instalação da orquestração do OpenCode (Linux/macOS).
set -uo pipefail

EXPECTED_MODELS=("qwen3.5-2b-32k:latest" "gemma4-e2b-32k:latest" "qwen3.5-08b-32k:latest")

for arg in "$@"; do
  case "$arg" in
    --smoke) ;; # mantido por compatibilidade; o teste do run_tests agora é sempre executado
    -h|--help)
      echo "Uso: ./verify.sh [--smoke]"
      exit 0 ;;
    *) echo "Opção desconhecida: $arg" >&2; exit 1 ;;
  esac
done

FAILURES=0
WARNINGS=0

step()  { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
ok()    { printf '  \033[32mok\033[0m  %s\n' "$1"; }
warn()  { printf '  \033[33m!\033[0m   %s\n' "$1"; WARNINGS=$((WARNINGS+1)); }
bad()   { printf '  \033[31mx\033[0m   %s\n' "$1" >&2; FAILURES=$((FAILURES+1)); }

step "Binários"
OPENCODE=""
for cand in opencode2 opencode; do
  if command -v "$cand" >/dev/null 2>&1; then OPENCODE="$cand"; break; fi
done
for cmd in "${OPENCODE:-opencode}" ollama node; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$cmd: $("$cmd" --version 2>&1 | head -n 1)"
  elif [ "$cmd" = "node" ]; then
    warn "node não encontrado (só importa se o OpenCode veio do npm)"
  else
    bad "$cmd não encontrado no PATH"
  fi
done

step "Config global"
TARGET="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json"
if [ ! -f "$TARGET" ]; then
  bad "config não encontrado: $TARGET (rode ./install.sh)"
else
  ok "arquivo: $TARGET"
  JSON_TOOL=""
  command -v node >/dev/null 2>&1 && JSON_TOOL="node"
  [ -z "$JSON_TOOL" ] && command -v python3 >/dev/null 2>&1 && JSON_TOOL="python3"

  if [ -z "$JSON_TOOL" ]; then
    warn "nem node nem python3 disponíveis; não dá para validar o JSON"
  elif [ "$JSON_TOOL" = "node" ]; then
    if node -e '
      const c = require(process.argv[1]);
      const ag = Object.keys(c.agents || {});
      console.log("  \x1b[32mok\x1b[0m  JSON válido");
      console.log("  \x1b[32mok\x1b[0m  default_agent: " + (c.default_agent || "(nao definido)"));
      for (const id of ["orquestrador","local-helper"])
        console.log((ag.includes(id) ? "  \x1b[32mok\x1b[0m  agente presente: " : "  \x1b[31mx\x1b[0m   agente ausente: ") + id);
      if (c.agents && c.agents.orquestrador && c.agents.orquestrador.model)
        console.log("  \x1b[33m!\x1b[0m   orquestrador tem model fixo (" + c.agents.orquestrador.model + "); /models nao governa");
      else if (c.agents && c.agents.orquestrador)
        console.log("  \x1b[32mok\x1b[0m  orquestrador sem model fixo (segue o /models)");
      if (c.model) console.log("  \x1b[33m!\x1b[0m   chave model no topo fixa o padrao: " + c.model);
    ' "$TARGET"; then
      :
    else
      bad "JSON inválido em $TARGET"
    fi
  else
    if python3 - "$TARGET" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
ag = list((cfg.get("agents") or {}).keys())
print("  ok  JSON válido")
print("  ok  default_agent: " + str(cfg.get("default_agent") or "(nao definido)"))
for i in ("orquestrador", "local-helper"):
    print(("  ok  agente presente: " if i in ag else "  x   agente ausente: ") + i)
orc = (cfg.get("agents") or {}).get("orquestrador") or {}
if orc.get("model"):
    print("  !   orquestrador tem model fixo (%s); /models nao governa" % orc["model"])
elif orc:
    print("  ok  orquestrador sem model fixo (segue o /models)")
if cfg.get("model"):
    print("  !   chave model no topo fixa o padrao: " + str(cfg["model"]))
sys.exit(0 if all(i in ag for i in ("orquestrador","local-helper")) else 1)
PY
    then :; else bad "config inválido ou agentes faltando"; fi
  fi
fi

step "Plugin de thinking do Ollama"
PLUGIN="$(dirname "$TARGET")/plugins/ollama-nothink.ts"
if [ -f "$PLUGIN" ]; then
  ok "plugin presente: $PLUGIN"
else
  warn "plugin ausente: $PLUGIN (rode ./install.sh)"
fi

step "Variável de ambiente OPENCODE_CONFIG_CONTENT"
if [ -n "${OPENCODE_CONFIG_CONTENT:-}" ]; then
  warn "definida (${#OPENCODE_CONFIG_CONTENT} chars) e sobrepõe o arquivo"
  warn "limpe antes de reiniciar: unset OPENCODE_CONFIG_CONTENT"
else
  ok "ausente"
fi

step "Modelos locais no Ollama"
if command -v ollama >/dev/null 2>&1; then
  list="$(ollama list 2>&1 || true)"
  for model in "${EXPECTED_MODELS[@]}"; do
    if printf '%s\n' "$list" | awk '{print $1}' | grep -qx "$model"; then
      ok "modelo presente: $model"
      mf="$(ollama show "$model" --modelfile 2>&1 || true)"
      ctx="$(printf '%s\n' "$mf" | awk '/^PARAMETER[[:space:]]+num_ctx/ {print $3; exit}')"
      if [ -n "$ctx" ]; then
        ok "num_ctx: $ctx"
        [ "$ctx" -lt 32768 ] && warn "contexto < 32k: a auto-compactacao do OpenCode degenera (keep fixo de 15000 tokens)"
      else
        bad "modelo sem PARAMETER num_ctx (contexto cai para o padrão do Ollama)"
        echo "     recrie: ./install.sh --force"
      fi
    else
      bad "modelo não encontrado: $model (rode ./install.sh)"
    fi
  done
fi

step "Agentes e permissões efetivas"
if [ -n "$OPENCODE" ]; then
  raw="$("$OPENCODE" debug agents 2>&1 || true)"
  if [ -n "${JSON_TOOL:-}" ]; then
    if [ "$JSON_TOOL" = "node" ]; then
      printf '%s' "$raw" | node -e '
        let s = "";
        process.stdin.on("data", d => s += d).on("end", () => {
          const a = s.indexOf("["), b = s.lastIndexOf("]");
          if (a < 0 || b <= a) { console.error("  x   saída não contém JSON"); process.exit(1); }
          let list;
          try { list = JSON.parse(s.slice(a, b + 1)); }
          catch (e) { console.error("  x   JSON inválido: " + e.message); process.exit(1); }
          console.log("  ok  " + list.length + " agentes carregados");
          let fails = 0;
          const g = id => list.find(x => x.id === id);
          for (const id of ["local-helper"]) {
            const ag = g(id);
            if (!ag) { console.log("  x   agente não carregado: " + id); fails++; continue; }
            if (ag.model) console.log("  ok  " + id + ": " + ag.model.providerID + "/" + ag.model.id);
            else { console.log("  !   " + id + " sem modelo resolvido"); }
            const p = ag.permissions || [];
            const has = (action, effect, re) => p.some(x => x.action === action && x.effect === effect && (!re || re.test(x.resource)));
            if (has("execute", "deny")) console.log("  ok  " + id + ": execute negado"); else { console.log("  x   " + id + ": execute NAO negado"); fails++; }
            if (has("edit", "deny")) console.log("  ok  " + id + ": edit negado"); else { console.log("  x   " + id + ": edit NAO negado"); fails++; }
            if (has("read", "deny", /(^|\*)\.env$/)) console.log("  ok  " + id + ": leitura de *.env negada"); else console.log("  !   " + id + ": *.env nao negado");
          }
          const orc = g("orquestrador");
          if (orc) {
            const n = (orc.permissions || []).filter(x => x.action === "subagent" && x.effect === "allow").length;
            console.log("  ok  orquestrador: " + n + " delegacoes permitidas");
            if (n === 0) { console.log("  x   orquestrador: nenhuma delegacao permitida"); fails++; }
          }
          process.exit(fails > 0 ? 1 : 0);
        });
      ' || bad "permissões efetivas divergentes"
    else
      printf '%s' "$raw" | python3 -c '
import json, sys, re
s = sys.stdin.read()
a, b = s.find("["), s.rfind("]")
if a < 0 or b <= a:
    print("  x   saída não contém JSON"); sys.exit(1)
list_ = json.loads(s[a:b+1])
print("  ok  %d agentes carregados" % len(list_))
g = {x["id"]: x for x in list_}
fails = 0
for i in ("local-helper",):
    ag = g.get(i)
    if not ag:
        print("  x   agente nao carregado: " + i); fails += 1; continue
    m = ag.get("model") or {}
    print(("  ok  %s: %s/%s" % (i, m.get("providerID"), m.get("id"))) if m else ("  !   %s sem modelo" % i))
    p = ag.get("permissions") or []
    has = lambda act, eff, rx=None: any(x["action"] == act and x["effect"] == eff and (rx is None or re.search(rx, x["resource"])) for x in p)
    print(("  ok  %s: execute negado" % i) if has("execute","deny") else ("  x   %s: execute NAO negado" % i)); fails += 0 if has("execute","deny") else 1
    print(("  ok  %s: edit negado" % i) if has("edit","deny") else ("  x   %s: edit NAO negado" % i)); fails += 0 if has("edit","deny") else 1
sys.exit(1 if fails else 0)
'
    fi
  else
    printf '%s' "$raw" | grep -q '"id": "local-helper"' && ok "local-helper carregado" || bad "local-helper não carregado"
    printf '%s' "$raw" | grep -q '"id": "orquestrador"' && ok "orquestrador carregado" || bad "orquestrador não carregado"
    warn "node/python3 ausentes: permissões não foram verificadas em detalhe"
  fi
fi

step "Servidor MCP run_tests"
RT="$(command -v orq-run-tests || true)"
if [ -z "$RT" ]; then
  bad "orq-run-tests não está no PATH (rode ./install.sh)"
elif ! command -v python3 >/dev/null 2>&1; then
  bad "python3 ausente"
else
  ok "launcher: $RT"
  rt_call() { # $1 = comando a testar
    printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
      "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"run_tests\",\"arguments\":{\"command\":\"$1\"}}}" \
      | "$RT" | tail -n 1
  }
  rt_call "git --version" | grep -q '"verdict": "passou"' && ok "git --version -> passou (exit 0 real)" || bad "run_tests não executou comando permitido"
  rt_call "composer install" | grep -q '"verdict": "bloqueado"' && ok "composer install -> bloqueado" || bad "run_tests deixou passar comando negado"
  rt_call "git --version; rm -rf x" | grep -q '"verdict": "bloqueado"' && ok "encadeamento com ; -> bloqueado" || bad "run_tests aceitou metacaracteres"
fi

step "Servidor MCP decisao"
DC="$(command -v orq-decisor || true)"
if [ -z "$DC" ]; then
  bad "orq-decisor não está no PATH (rode ./install.sh)"
elif [ ! -x "$DC" ]; then
  bad "orq-decisor sem permissão de execução (chmod +x mcp/decisao/server.py)"
else
  ok "launcher: $DC"
  resp="$(printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"verify","version":"1"}}}' | timeout 20 "$DC" 2>&1 | head -n 1)"
  if printf '%s' "$resp" | grep -q '"serverInfo"'; then
    ok "initialize respondeu (stdio ok)"
  else
    bad "initialize não respondeu: $(printf '%s' "$resp" | cut -c1-120)"
  fi
  if command -v ollama >/dev/null 2>&1; then
    if ollama list 2>/dev/null | grep -q '^d3:2b'; then ok "modelo d3:2b presente"
    else warn "d3:2b ausente: o decisor não consegue decidir (ollama pull d3:2b)"; fi
  fi
fi

step "Base de conhecimento (kb e embeddings)"
KB="$(command -v orq-kb || true)"
if [ -z "$KB" ]; then
  bad "orq-kb não está no PATH (rode ./install.sh)"
else
  ok "launcher: $KB"
  if command -v ollama >/dev/null 2>&1 && ollama list 2>/dev/null | grep -q '^nomic-embed-text'; then
    ok "nomic-embed-text instalado (busca semântica)"
  else
    warn "nomic-embed-text ausente: a busca do kb fica só em BM25 (ollama pull nomic-embed-text)"
  fi
  if [ -n "$OPENCODE" ]; then
    mcp_out="$(timeout 60 "$OPENCODE" mcp list 2>&1 | sed 's/\x1b\[[0-9;]*m//g' || true)"
    if printf '%s' "$mcp_out" | grep -Eq '✓ kb .*connected|kb +connected'; then ok "OpenCode: MCP kb conectado"
    else bad "OpenCode: MCP kb não conectado (confira mcp.kb em opencode.json)"; fi
  fi
  # apps indexados sem embedding: a busca semântica não os cobre
  while IFS= read -r linha; do
    case "$linha" in
      *" 0 com embedding"*) warn "kb: ${linha%%:*} sem embeddings (rode 'orq-kb index' na raiz desse projeto)" ;;
    esac
  done < <("$KB" apps 2>/dev/null)
fi

step "Resultado"
if [ "$FAILURES" -eq 0 ]; then
  printf '  \033[32mPASSOU\033[0m — %d aviso(s)\n' "$WARNINGS"
  exit 0
else
  printf '  \033[31mFALHOU\033[0m — %d erro(s), %d aviso(s)\n' "$FAILURES" "$WARNINGS"
  exit 1
fi
