#!/usr/bin/env python3
"""Servidor MCP (stdio) que roda testes de forma determinística.

Substitui o agente LLM `qwen-testes`: executa um comando de teste permitido e devolve
comando, saída, exit code e veredito. Só biblioteca padrão, sem dependências.

  passou    -> exit code 0
  falhou    -> exit code != 0
  bloqueado -> comando recusado, inexistente ou estourou o timeout (nada foi confirmado)

Allowlist extra: ORQ_TESTS_ALLOW="regex1;;regex2" (casa com o comando inteiro).
"""
import json
import locale
import os
import re
import shlex
import subprocess
import sys

NAME, VERSION = "run_tests", "1.0.1"
PROTOCOL = "2024-11-05"
MAX_TIMEOUT = 1800
TAIL_BYTES = 16000

ALLOW = [
    r"(\./)?vendor/bin/(phpunit|pest)( .*)?",
    r"php artisan test( .*)?",
    r"composer (run(-script)? )?test( .*)?",
    r"(npm|pnpm|yarn|bun) (run )?test( .*)?",
    r"(npx )?(vitest|jest)( .*)?",
    r"(python3? -m )?pytest( .*)?",
    r"(.*[\\/])?python3?(\.exe)? -m pytest( .*)?",
    r"python3? -m unittest( .*)?",
    r"(.*[\\/])?python3?(\.exe)? -m unittest( .*)?",
    r"(.*[\\/])?python3?(\.exe)? .*[\\/]\.orquestrador[\\/]scripts[\\/]verificar_docs\.py( .*)?",
    r"go test( .*)?",
    r"cargo test( .*)?",
    r"(\./)?(mvnw?|gradlew?) (-\S+ )*test( .*)?",
    r"dotnet test( .*)?",
    r"(\./)?vendor/bin/pint --test( .*)?",
    r"git --version",
]
DENY = [
    r"(^| )(rm|sudo|curl|wget|ssh|scp|docker|kubectl)( |$)",
    r"migrate|db:|--env-file|install|publish",
]
FAIL_MARK = re.compile(
    r"FAIL|ERROR|Error|Exception|✘|✗|×|FAILURES!|ERRORS!|There (was|were) \d+|Assertion|"
    r"Expected|Failed asserting|panic:|Traceback|^\s*at .+:\d+|Tests:|passed|failed", re.I)
CONTEXT, SUMMARY_LINES = 2, 8
META = re.compile(r"[;&|`<>\n\r]|\$\(")

TOOL = {
    "name": "run_tests",
    "description": (
        "Roda UM comando de teste permitido (phpunit, pest, php artisan test, npm/pnpm test, "
        "pytest, go test, cargo test, mvn/gradle test, dotnet test) e devolve a saída real, o "
        "exit code e o veredito; por padrão condensa a saída (só falhas + resumo) (passou = exit 0, falhou = exit != 0, bloqueado = recusado, "
        "inexistente ou timeout). Sem shell: pipes, ; & > e $() são recusados."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Comando literal, ex.: php artisan test --filter=UserTest"},
            "cwd": {"type": "string", "description": "Diretório do projeto (padrão: diretório do servidor)"},
            "only_failures": {"type": "boolean", "description": "Padrão true: devolve só falhas + resumo (economiza tokens). false = saída completa (até 16 KB)"},
            "max_lines": {"type": "integer", "description": "Máximo de linhas quando only_failures=true (padrão 80)"},
            "timeout": {"type": "integer", "description": "Segundos (padrão 300, máx %d)" % MAX_TIMEOUT},
        },
        "required": ["command"],
    },
}


def allowed(command):
    extra = [p for p in os.environ.get("ORQ_TESTS_ALLOW", "").split(";;") if p]
    if META.search(command):
        return "metacaracteres de shell não são permitidos"
    if any(re.search(p, command) for p in DENY):
        return "comando recusado pela lista de negação"
    if not any(re.fullmatch(p, command) for p in ALLOW + extra):
        return "comando fora da allowlist (ORQ_TESTS_ALLOW para estender)"
    return None


def _encoding_local():
    """Encoding do console/locale: no Windows é o code page ANSI (cp1252...) mesmo em modo UTF-8."""
    try:
        return locale.getencoding()  # 3.11+
    except AttributeError:
        return locale.getpreferredencoding(False)


def decode_output(data):
    """Decodifica a saída do comando de teste testando os encodings prováveis.

    Sem `text=True` no subprocess: ele decodifica no encoding do locale e, no Windows,
    o runner (phpunit, vitest, go, pytest) costuma escrever UTF-8 enquanto o Python
    local pode estar em cp1252 — e vice-versa. Aqui a decodificação nunca estoura.
    """
    if isinstance(data, str):
        return data
    if not data:
        return ""
    for codificacao in ("utf-8", _encoding_local()):
        try:
            return data.decode(codificacao)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", "replace")


def tail(text):
    data = text.encode("utf-8", "replace")
    if len(data) <= TAIL_BYTES:
        return text
    return "[... truncado ...]\n" + data[-TAIL_BYTES:].decode("utf-8", "replace")


def condense(text, verdict, max_lines):
    """Reduz a saída: passou -> só o resumo final; falhou -> trechos com falha + resumo."""
    lines = text.splitlines()
    total = len(lines)
    if total <= max_lines:
        return text, False
    if verdict == "passou":
        keep = set(range(max(0, total - SUMMARY_LINES), total))
    else:
        keep = set(range(max(0, total - SUMMARY_LINES), total))
        for i, ln in enumerate(lines):
            if FAIL_MARK.search(ln):
                keep.update(range(max(0, i - CONTEXT), min(total, i + CONTEXT + 1)))
    idx = sorted(keep)
    if len(idx) > max_lines:  # estoura: fica com o começo das falhas e o resumo final
        idx = idx[: max_lines - SUMMARY_LINES] + idx[-SUMMARY_LINES:]
    out, prev = [], -1
    for i in idx:
        if prev != -1 and i != prev + 1:
            out.append("[... %d linhas omitidas ...]" % (i - prev - 1))
        out.append(lines[i])
        prev = i
    if idx and idx[0] > 0:
        out.insert(0, "[... %d linhas omitidas ...]" % idx[0])
    return "\n".join(out), True


def run_tests(args):
    command = (args.get("command") or "").strip()
    cwd = args.get("cwd") or os.getcwd()
    timeout = max(1, min(int(args.get("timeout") or 300), MAX_TIMEOUT))
    only_failures = args.get("only_failures", True)
    max_lines = max(10, min(int(args.get("max_lines") or 80), 2000))
    result = {"command": command, "cwd": cwd, "exit_code": None, "output": "", "verdict": "bloqueado"}

    reason = allowed(command)
    if reason:
        result["output"] = reason
        return result
    if not os.path.isdir(cwd):
        result["output"] = "cwd inexistente: " + cwd
        return result
    try:
<<<<<<< Updated upstream
        p = subprocess.run(shlex.split(command), cwd=cwd, capture_output=True,
                           timeout=timeout, stdin=subprocess.DEVNULL)
=======
        # No Windows, posix=True do shlex come as barras de caminho
        # (.venv\Scripts\python.exe -> .venvScriptspython.exe). posix=False
        # preserva o caminho; tiramos as aspas que ele mantém nos tokens.
        partes = shlex.split(command, posix=(os.name != "nt"))
        if os.name == "nt":
            partes = [
                t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t
                for t in partes
            ]
        p = subprocess.run(partes, cwd=cwd, capture_output=True, text=True,
                           errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
>>>>>>> Stashed changes
    except FileNotFoundError as e:
        result["output"] = "comando inexistente: %s" % e
        return result
    except subprocess.TimeoutExpired as e:
        result["output"] = tail(decode_output(e.stdout)) + "\n[timeout após %ds]" % timeout
        return result
    result["exit_code"] = p.returncode
    result["verdict"] = "passou" if p.returncode == 0 else "falhou"
    raw = decode_output(p.stdout) + decode_output(p.stderr)
    result["total_lines"] = len(raw.splitlines())
    if only_failures:
        raw, result["condensed"] = condense(raw, result["verdict"], max_lines)
    result["output"] = tail(raw)
    return result


def reply(msg_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": msg_id}
    msg.update({"error": error} if error else {"result": result})
    try:
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    except UnicodeEncodeError:  # stream sem UTF-8: o JSON escapado é ASCII e continua válido
        sys.stdout.write(json.dumps(msg, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def handle(msg):
    method, msg_id = msg.get("method"), msg.get("id")
    if msg_id is None:  # notificação
        return
    if method == "initialize":
        reply(msg_id, {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                       "serverInfo": {"name": NAME, "version": VERSION}})
    elif method == "tools/list":
        reply(msg_id, {"tools": [TOOL]})
    elif method == "tools/call":
        params = msg.get("params") or {}
        if params.get("name") != "run_tests":
            return reply(msg_id, error={"code": -32602, "message": "tool desconhecida"})
        try:
            r = run_tests(params.get("arguments") or {})
        except Exception as e:  # nunca derrubar o servidor
            r = {"verdict": "bloqueado", "exit_code": None, "output": "erro interno: %r" % e}
        text = "COMANDO: %s\nCODIGO DE SAIDA: %s\nRESULTADO: %s\nSAIDA:\n%s" % (
            r.get("command", ""), r["exit_code"], r["verdict"], r["output"])
        reply(msg_id, {"content": [{"type": "text", "text": text}],
                       "structuredContent": r, "isError": False})
    elif method == "ping":
        reply(msg_id, {})
    else:
        reply(msg_id, error={"code": -32601, "message": "método desconhecido: %s" % method})


def use_utf8_stdio():
    """O protocolo MCP é UTF-8. No Windows, sem isso, stdin/stdout usam o code page local:
    cwd com acento chega corrompido e saída com ✓/✘/setas derruba o `write` do protocolo."""
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main():
<<<<<<< Updated upstream
    use_utf8_stdio()
=======
    # MCP stdio é UTF-8; no Windows o padrão cp1252 quebra a saída com acentos
    # e símbolos (UnicodeEncodeError derruba o servidor).
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    except (AttributeError, ValueError):
        pass
>>>>>>> Stashed changes
    for line in sys.stdin:
        line = line.strip()
        if line:
            try:
                handle(json.loads(line))
            except json.JSONDecodeError:
                reply(None, error={"code": -32700, "message": "JSON inválido"})


if __name__ == "__main__":
    main()
