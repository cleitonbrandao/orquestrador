#!/usr/bin/env bash
# Valida a instalação da orquestração do OpenCode (Linux/macOS).
set -uo pipefail

EXPECTED_MODEL="qwen3-12k:latest"
SMOKE=0

for arg in "$@"; do
  case "$arg" in
    --smoke) SMOKE=1 ;;
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
for cmd in opencode ollama node; do
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
      for (const id of ["orquestrador","decompositor","executor","exec-backend","exec-dados","exec-frontend","exec-docs","local-helper","qwen-testes"])
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
EXPECTED = ("orquestrador", "decompositor", "executor", "exec-backend", "exec-dados", "exec-frontend", "exec-docs", "local-helper", "qwen-testes")
for i in EXPECTED:
    print(("  ok  agente presente: " if i in ag else "  x   agente ausente: ") + i)
orc = (cfg.get("agents") or {}).get("orquestrador") or {}
if orc.get("model"):
    print("  !   orquestrador tem model fixo (%s); /models nao governa" % orc["model"])
elif orc:
    print("  ok  orquestrador sem model fixo (segue o /models)")
if cfg.get("model"):
    print("  !   chave model no topo fixa o padrao: " + str(cfg["model"]))
sys.exit(0 if all(i in ag for i in EXPECTED) else 1)
PY
    then :; else bad "config inválido ou agentes faltando"; fi
  fi
fi

step "Variável de ambiente OPENCODE_CONFIG_CONTENT"
if [ -n "${OPENCODE_CONFIG_CONTENT:-}" ]; then
  warn "definida (${#OPENCODE_CONFIG_CONTENT} chars) e sobrepõe o arquivo"
  warn "limpe antes de reiniciar: unset OPENCODE_CONFIG_CONTENT"
else
  ok "ausente"
fi

step "Modelo local no Ollama"
if command -v ollama >/dev/null 2>&1; then
  list="$(ollama list 2>&1 || true)"
  if printf '%s\n' "$list" | awk '{print $1}' | grep -qx "$EXPECTED_MODEL"; then
    ok "modelo presente: $EXPECTED_MODEL"
    mf="$(ollama show "$EXPECTED_MODEL" --modelfile 2>&1 || true)"
    ctx="$(printf '%s\n' "$mf" | awk '/^PARAMETER[[:space:]]+num_ctx/ {print $3; exit}')"
    if [ -n "$ctx" ]; then
      ok "num_ctx: $ctx"
      [ "$ctx" -lt 8192 ] && warn "contexto baixo para leitura de código (recomendado >= 8192)"
    else
      bad "modelo sem PARAMETER num_ctx (contexto cai para o padrão do Ollama)"
      echo "     recrie: ./install.sh --force"
    fi
  else
    bad "modelo não encontrado: $EXPECTED_MODEL (rode ./install.sh)"
  fi
fi

step "Agentes e permissões efetivas"
if command -v opencode >/dev/null 2>&1; then
  raw="$(opencode debug agents 2>&1 || true)"
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
          for (const id of ["local-helper", "qwen-testes"]) {
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
          const qt = g("qwen-testes");
          if (qt) {
            const p = qt.permissions || [];
            const blocks = p.filter(x => x.action === "shell" && x.effect === "deny" && /^(composer \*|npm \*|docker \*)/.test(x.resource));
            if (blocks.length >= 3) console.log("  ok  qwen-testes: composer/npm/docker negados");
            else { console.log("  x   qwen-testes: faltam negacoes de shell (composer/npm/docker)"); fails++; }
            if (p.some(x => x.action === "shell" && x.resource === "*" && x.effect === "ask")) console.log("  ok  qwen-testes: shell em modo ask");
            else console.log("  !   qwen-testes: shell nao esta em ask");
          }
          const orc = g("orquestrador");
          if (orc) {
            const n = (orc.permissions || []).filter(x => x.action === "subagent" && x.effect === "allow").length;
            console.log("  ok  orquestrador: " + n + " delegacoes permitidas");
            if (n === 0) { console.log("  x   orquestrador: nenhuma delegacao permitida"); fails++; }
            for (const id of ["decompositor", "executor", "exec-backend", "exec-dados", "exec-frontend", "exec-docs"]) {
              if ((orc.permissions || []).some(x => x.action === "subagent" && x.resource === id && x.effect === "allow")) console.log("  ok  orquestrador: pode delegar ao " + id);
              else { console.log("  x   orquestrador: delegacao ao " + id + " nao permitida"); fails++; }
            }
          }
          // Pipeline: decompositor só lê; executor edita mas não roda shell e só aciona o qwen-testes.
          const dec = g("decompositor");
          if (!dec) { console.log("  x   agente não carregado: decompositor"); fails++; }
          else {
            const p = dec.permissions || [];
            for (const act of ["edit", "shell"]) {
              if (p.some(x => x.action === act && x.resource === "*" && x.effect === "deny")) console.log("  ok  decompositor: " + act + " negado");
              else { console.log("  x   decompositor: " + act + " NAO negado"); fails++; }
            }
          }
          for (const id of ["executor", "exec-backend", "exec-dados", "exec-frontend"]) {
            const exe = g(id);
            if (!exe) { console.log("  x   agente não carregado: " + id); fails++; continue; }
            const p = exe.permissions || [];
            if (p.some(x => x.action === "shell" && x.resource === "*" && x.effect === "deny")) console.log("  ok  " + id + ": shell negado");
            else { console.log("  x   " + id + ": shell NAO negado"); fails++; }
            const subs = p.filter(x => x.action === "subagent");
            const last = subs[subs.length - 1];
            if (last && last.resource === "qwen-testes" && last.effect === "allow") console.log("  ok  " + id + ": só delega ao qwen-testes");
            else { console.log("  x   " + id + ": regra de subagente diferente de qwen-testes allow no fim"); fails++; }
          }
          // exec-docs: modelo local, edita só Markdown, sem shell e sem subagente
          const doc = g("exec-docs");
          if (!doc) { console.log("  x   agente não carregado: exec-docs"); fails++; }
          else {
            const p = doc.permissions || [];
            const edits = p.filter(x => x.action === "edit");
            const lastEdit = edits[edits.length - 1];
            if (p.some(x => x.action === "edit" && x.resource === "*" && x.effect === "deny") && lastEdit && lastEdit.resource === "*.md" && lastEdit.effect === "allow") console.log("  ok  exec-docs: edita só *.md");
            else { console.log("  x   exec-docs: edit não está restrito a *.md"); fails++; }
            for (const act of ["shell", "subagent"]) {
              if (p.some(x => x.action === act && x.resource === "*" && x.effect === "deny")) console.log("  ok  exec-docs: " + act + " negado");
              else { console.log("  x   exec-docs: " + act + " NAO negado"); fails++; }
            }
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
for i in ("local-helper", "qwen-testes"):
    ag = g.get(i)
    if not ag:
        print("  x   agente nao carregado: " + i); fails += 1; continue
    m = ag.get("model") or {}
    print(("  ok  %s: %s/%s" % (i, m.get("providerID"), m.get("id"))) if m else ("  !   %s sem modelo" % i))
    p = ag.get("permissions") or []
    has = lambda act, eff, rx=None: any(x["action"] == act and x["effect"] == eff and (rx is None or re.search(rx, x["resource"])) for x in p)
    print(("  ok  %s: execute negado" % i) if has("execute","deny") else ("  x   %s: execute NAO negado" % i)); fails += 0 if has("execute","deny") else 1
    print(("  ok  %s: edit negado" % i) if has("edit","deny") else ("  x   %s: edit NAO negado" % i)); fails += 0 if has("edit","deny") else 1
qt = g.get("qwen-testes")
if qt:
    p = qt.get("permissions") or []
    n = len([x for x in p if x["action"] == "shell" and x["effect"] == "deny" and re.match(r"(composer \*|npm \*|docker \*)", x["resource"])])
    print("  ok  qwen-testes: composer/npm/docker negados" if n >= 3 else "  x   qwen-testes: faltam negacoes")
    fails += 0 if n >= 3 else 1
sys.exit(1 if fails else 0)
'
    fi
  else
    printf '%s' "$raw" | grep -q '"id": "local-helper"' && ok "local-helper carregado" || bad "local-helper não carregado"
    printf '%s' "$raw" | grep -q '"id": "qwen-testes"' && ok "qwen-testes carregado" || bad "qwen-testes não carregado"
    printf '%s' "$raw" | grep -q '"id": "orquestrador"' && ok "orquestrador carregado" || bad "orquestrador não carregado"
    warn "node/python3 ausentes: permissões não foram verificadas em detalhe"
  fi
fi

step "Slots do Ollama"
if [ -n "${OLLAMA_NUM_PARALLEL:-}" ]; then
  ok "OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL neste shell"
else
  warn "OLLAMA_NUM_PARALLEL não está neste shell (confira no serviço: systemctl show ollama -p Environment)"
fi
if command -v ollama >/dev/null 2>&1 && ollama ps 2>&1 | grep -q "CPU"; then
  warn "ollama ps mostra uso de CPU: modelo não coube inteiro na VRAM"
fi

step "Claude Code (~/.claude)"
for f in agents/decompositor.md agents/executor.md agents/exec-backend.md agents/exec-dados.md agents/exec-frontend.md agents/exec-docs.md agents/testador.md skills/orquestrar/SKILL.md; do
  if [ -f "$HOME/.claude/$f" ]; then ok "presente: $f"; else warn "ausente: $HOME/.claude/$f (rode ./install.sh)"; fi
done

step "Scripts verificadores (~/.orquestrador/scripts)"
SCRIPTS_DIR="$HOME/.orquestrador/scripts"
for f in verificar.sh verificar.ps1 verificar_docs.py redigir_docs.py; do
  if [ -f "$SCRIPTS_DIR/$f" ]; then ok "presente: $f"; else bad "ausente: $SCRIPTS_DIR/$f (rode ./install.sh)"; fi
done
if [ -f "$SCRIPTS_DIR/verificar.sh" ]; then
  out="$(bash "$SCRIPTS_DIR/verificar.sh" "git --version" 2>&1)"
  if printf '%s' "$out" | grep -q "git version" && printf '%s' "$out" | grep -q "RESULTADO: bloqueado"; then
    ok "verificar.sh: git --version -> bloqueado (correto: não é teste)"
  else
    bad "verificar.sh não devolveu o contrato esperado"; printf '%s\n' "$out"
  fi
  # captura antes do grep: o verificador sai com 2 (bloqueado) e o pipefail derrubaria o pipe
  out="$(bash "$SCRIPTS_DIR/verificar.sh" "composer install" 2>&1)"
  if printf '%s' "$out" | grep -q "recusado"; then
    ok "verificar.sh: composer install recusado sem rodar"
  else
    bad "verificar.sh não recusou composer install"
  fi
fi
# no Windows, "python3" pode ser o atalho da Microsoft Store, que não roda nada
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" --version 2>&1 | grep -q "^Python 3"; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  warn "Python 3 não encontrado: a rota docs cai no exec-docs e o verificador de docs não roda"
elif [ -f "$SCRIPTS_DIR/verificar_docs.py" ]; then
  tmp="$(mktemp -d)"
  printf '# Teste\n\nVeja [x](nao-existe.md).\n' > "$tmp/LEIAME.md"
  : > "$tmp/vazio.md"
  out="$("$PY" "$SCRIPTS_DIR/verificar_docs.py" "$tmp/LEIAME.md" --original "$tmp/vazio.md" --raiz "$tmp" 2>&1)"
  rm -rf "$tmp"
  if printf '%s' "$out" | grep -q "RESULTADO: falhou" && printf '%s' "$out" | grep -q "nao-existe.md"; then
    ok "verificar_docs.py: link quebrado detectado ($("$PY" --version 2>&1))"
  else
    bad "verificar_docs.py não acusou o link quebrado"; printf '%s\n' "$out"
  fi
fi

if [ "$SMOKE" -eq 1 ]; then
  step "Teste real de delegação (qwen-testes)"
  if ! command -v opencode >/dev/null 2>&1; then
    bad "opencode indisponível para o teste"
  else
    # o mesmo pedido que os executores mandam: o verificador com o comando dentro
    pedido="rode exatamente: bash ~/.orquestrador/scripts/verificar.sh 'git --version'"
    echo "  rodando: opencode run --agent qwen-testes --model ollama/$EXPECTED_MODEL \"$pedido\""
    start=$(date +%s)
    out="$(opencode run --agent qwen-testes --model "ollama/$EXPECTED_MODEL" "$pedido" 2>&1 || true)"
    end=$(date +%s)
    printf '%s\n' "$out"
    if printf '%s' "$out" | grep -q "git version" && printf '%s' "$out" | grep -q "RESULTADO: bloqueado"; then
      ok "verificador executado pelo qwen-testes ($((end-start))s)"
    else
      bad "a saída não contém 'git version' com RESULTADO: bloqueado — o verificador pode não ter rodado"
    fi
  fi
fi

step "Resultado"
if [ "$FAILURES" -eq 0 ]; then
  printf '  \033[32mPASSOU\033[0m — %d aviso(s)\n' "$WARNINGS"
  exit 0
else
  printf '  \033[31mFALHOU\033[0m — %d erro(s), %d aviso(s)\n' "$FAILURES" "$WARNINGS"
  exit 1
fi
