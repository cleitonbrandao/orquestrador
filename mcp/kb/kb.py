#!/usr/bin/env python3
"""Base de conhecimento local por aplicação (BM25 + embeddings opcionais) e servidor MCP.

  kb.py index [<app> [<dir>]] [--no-embed]   indexa (incremental). Sem args: diretório atual,
                                             app = nome da raiz git (ou da pasta)
  kb.py search [<app>] <consulta> [-k 5]     sem <app>: app do diretório atual
  kb.py apps                                 apps, arquivos, chunks e embeddings
  kb.py forget <app>                         apaga um app do índice
  kb.py serve                                servidor MCP (stdio): search_kb, list_apps

Só biblioteca padrão. Embeddings via Ollama (ORQ_EMBED_MODEL, padrão nomic-embed-text)
são usados automaticamente quando o modelo existe; sem ele, a busca é só BM25 (SQLite FTS5).
Banco: ORQ_KB_DB (padrão ~/.local/share/orquestrador/kb.sqlite).
"""
import array
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import urllib.request

DB_PATH = os.environ.get("ORQ_KB_DB") or os.path.expanduser("~/.local/share/orquestrador/kb.sqlite")
EMBED_MODEL = os.environ.get("ORQ_EMBED_MODEL", "nomic-embed-text")
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
if not OLLAMA.startswith("http"):
    OLLAMA = "http://" + OLLAMA

EXTS = {".md", ".txt", ".php", ".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".json", ".yml", ".yaml",
        ".sql", ".sh", ".go", ".rs", ".java", ".cs", ".rb", ".css", ".html", ".toml", ".ini", ".xml"}
SKIP_DIRS = {".git", "node_modules", "vendor", "storage", "bootstrap", "dist", "build", ".venv", "venv",
             "__pycache__", ".next", ".cache", "coverage", ".idea", ".vscode"}
SECRET = re.compile(r"(^|/)(\.env[^/]*|[^/]*\.(key|pem|p12|pfx)|[^/]*id_rsa[^/]*|[^/]*secrets?[^/]*|"
                    r"[^/]*credentials?[^/]*|[^/]*accounts?[^/]*\.json|package-lock\.json|composer\.lock)$", re.I)
SECRET_OK = re.compile(r"\.env\.example$")
MAX_BYTES, WINDOW, OVERLAP, MAX_CHARS = 300_000, 60, 8, 1800


def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=60)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS files(app TEXT, path TEXT, hash TEXT, PRIMARY KEY(app, path));
    CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, app TEXT, path TEXT, start INTEGER, end INTEGER, text TEXT, vec BLOB);
    CREATE INDEX IF NOT EXISTS chunks_app_path ON chunks(app, path);
    CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(text, path, content='chunks', content_rowid='id', tokenize="unicode61 tokenchars '_'");
    """)
    return c


def walk(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            full = os.path.join(base, f)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if SECRET.search(rel) and not SECRET_OK.search(rel):
                continue
            if os.path.splitext(f)[1].lower() not in EXTS:
                continue
            try:
                if os.path.getsize(full) > MAX_BYTES:
                    continue
            except OSError:
                continue
            yield rel, full


def chunk(text):
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        part = lines[i:i + WINDOW]
        body = "\n".join(part)[:MAX_CHARS]
        if body.strip():
            yield i + 1, i + len(part), body
        if i + WINDOW >= len(lines):
            break
        i += WINDOW - OVERLAP


def embed(texts):
    req = urllib.request.Request(OLLAMA + "/api/embed", json.dumps({"model": EMBED_MODEL, "input": texts}).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["embeddings"]


_HAVE = {}


def have_embed_model():
    if "v" in _HAVE:
        return _HAVE["v"]
    _HAVE["v"] = _probe_embed_model()
    return _HAVE["v"]


def _probe_embed_model():
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=5) as r:
            names = [m["name"] for m in json.load(r)["models"]]
        return any(n == EMBED_MODEL or n.startswith(EMBED_MODEL + ":") for n in names)
    except Exception:
        return False


def git_root(path):
    p = os.path.abspath(path)
    while True:
        if os.path.isdir(os.path.join(p, ".git")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def default_app(cwd=None):
    """(app, raiz) do diretório atual: raiz git se houver, senão a própria pasta."""
    cwd = os.path.abspath(cwd or os.getcwd())
    root = git_root(cwd) or cwd
    return re.sub(r"[^\w.-]+", "-", os.path.basename(root)).strip("-").lower() or "root", root


def drop_file(c, app, path):
    for i, text in c.execute("SELECT id, text FROM chunks WHERE app=? AND path=?", (app, path)).fetchall():
        c.execute("INSERT INTO fts(fts, rowid, text, path) VALUES('delete', ?, ?, ?)", (i, text, path))
    c.execute("DELETE FROM chunks WHERE app=? AND path=?", (app, path))
    c.execute("DELETE FROM files WHERE app=? AND path=?", (app, path))


def embed_chunks(c, app, rel, ids_texts):
    """Calcula e grava vetores dos chunks (id, texto) de um arquivo."""
    for j in range(0, len(ids_texts), 16):
        part = ids_texts[j:j + 16]
        got = embed(["search_document: " + t for _, t in part])
        for (cid, _), v in zip(part, got):
            c.execute("UPDATE chunks SET vec=? WHERE id=?", (array.array("f", v).tobytes(), cid))


def cmd_index(app, root, with_embed):
    root = os.path.abspath(root)
    c = db()
    if with_embed and not have_embed_model():
        print("aviso: modelo '%s' ausente no Ollama (ollama pull %s); indexando só BM25" % (EMBED_MODEL, EMBED_MODEL), file=sys.stderr)
        with_embed = False
    seen, added, skipped = set(), 0, 0
    for rel, full in walk(root):
        seen.add(rel)
        try:
            data = open(full, "rb").read()
            text = data.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        h = hashlib.sha1(data).hexdigest()
        row = c.execute("SELECT hash FROM files WHERE app=? AND path=?", (app, rel)).fetchone()
        if row and row[0] == h:
            skipped += 1
            continue
        if row:
            drop_file(c, app, rel)
        new = []
        for (s_, e_, body) in chunk(text):
            cur = c.execute("INSERT INTO chunks(app, path, start, end, text, vec) VALUES(?,?,?,?,?,NULL)", (app, rel, s_, e_, body))
            c.execute("INSERT INTO fts(rowid, text, path) VALUES(?,?,?)", (cur.lastrowid, body, rel))
            new.append((cur.lastrowid, body))
        c.execute("INSERT OR REPLACE INTO files VALUES(?,?,?)", (app, rel, h))
        added += 1
        if with_embed and new:
            embed_chunks(c, app, rel, new)
            c.commit()
    for (p,) in c.execute("SELECT path FROM files WHERE app=?", (app,)).fetchall():
        if p not in seen:
            drop_file(c, app, p)
    filled = 0
    if with_embed:  # preenche vetores de chunks já indexados antes (ex.: índice BM25 antigo)
        todo = c.execute("SELECT id, text FROM chunks WHERE app=? AND vec IS NULL", (app,)).fetchall()
        for j in range(0, len(todo), 16):
            embed_chunks(c, app, "", todo[j:j + 16])
            filled += len(todo[j:j + 16])
            if (j // 16) % 20 == 19:
                c.commit()
                print("  ... %d/%d embeddings" % (filled, len(todo)), file=sys.stderr)
    c.commit()
    n = c.execute("SELECT count(*) FROM chunks WHERE app=?", (app,)).fetchone()[0]
    nv = c.execute("SELECT count(*) FROM chunks WHERE app=? AND vec IS NOT NULL", (app,)).fetchone()[0]
    print("app=%s arquivos novos/alterados=%d inalterados=%d chunks=%d com_embedding=%d" % (app, added, skipped, n, nv))


STOP = set("a o as os um uma de do da dos das em no na nos nas por para com sem que e ou se ao como mais the an of to in on for and or is are with by from this that how what where".split())


def fts_query(q, op="OR"):
    toks = [t for t in re.findall(r"[\w]+", q, re.UNICODE) if len(t) > 2 and t.lower() not in STOP]
    return (" %s " % op).join('"%s"' % t for t in toks[:24])


def cosine(a, b):
    d = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return d / (na * nb) if na and nb else 0.0


VEC_FULL_LIMIT = 12000  # até este nº de chunks com vetor, busca vetorial direta (sem depender do BM25)


def search(app, query, k=5):
    c = db()
    sql = """SELECT chunks.id, chunks.path, chunks.start, chunks.end, chunks.text, bm25(fts, 1.0, 3.0)
             FROM fts JOIN chunks ON chunks.id = fts.rowid
             WHERE fts MATCH ? AND chunks.app = ? ORDER BY bm25(fts, 1.0, 3.0) LIMIT 40"""
    bm = []
    for op in ("AND", "OR"):  # AND primeiro (precisão); OR só se faltar resultado
        q = fts_query(query, op)
        if not q:
            break
        bm = c.execute(sql, (q, app)).fetchall()
        if len(bm) >= k:
            break
    scores, info = {}, {}
    for i, r in enumerate(bm):
        scores[r[0]] = scores.get(r[0], 0) + 1.0 / (60 + i)
        info[r[0]] = r[1:5]
    nvec = c.execute("SELECT count(*) FROM chunks WHERE app=? AND vec IS NOT NULL", (app,)).fetchone()[0]
    if nvec and have_embed_model():
        try:
            qv = embed(["search_query: " + query])[0]
            if nvec <= VEC_FULL_LIMIT:
                rows = c.execute("SELECT id, path, start, end, text, vec FROM chunks WHERE app=? AND vec IS NOT NULL", (app,)).fetchall()
            else:
                ids = list(scores) or [0]
                rows = c.execute("SELECT id, path, start, end, text, vec FROM chunks WHERE id IN (%s) AND vec IS NOT NULL" % ",".join("?" * len(ids)), ids).fetchall()
            sem = sorted(((cosine(qv, array.array("f", r[5]).tolist()), r) for r in rows), key=lambda x: -x[0])[:40]
            for i, (_, r) in enumerate(sem):
                scores[r[0]] = scores.get(r[0], 0) + 1.0 / (60 + i)
                info[r[0]] = r[1:5]
        except Exception as e:
            print("aviso: busca semântica indisponível (%r); usando só BM25" % e, file=sys.stderr)
    out = []
    for cid, _ in sorted(scores.items(), key=lambda x: -x[1])[:k]:
        path, st, en, text = info[cid]
        out.append({"path": path, "lines": "%d-%d" % (st, en), "snippet": text[:700]})
    return out


def apps_summary():
    rows = db().execute("""SELECT app, count(DISTINCT path), count(*), count(vec) FROM chunks GROUP BY app ORDER BY app""").fetchall()
    return "\n".join("%s: %d arquivos, %d chunks, %d com embedding" % r for r in rows) or "nenhum app indexado"


def fmt(results):
    if not results:
        return "nenhum resultado"
    return "\n\n".join("%s:%s\n%s" % (r["path"], r["lines"], r["snippet"]) for r in results)


# ---------- MCP ----------
TOOLS = [
    {"name": "search_kb", "description": "Busca trechos na base de conhecimento local de uma aplicação (docs, código, runbooks). Use antes de ler muitos arquivos. Devolve caminho:linhas + trecho.",
     "inputSchema": {"type": "object", "properties": {"app": {"type": "string", "description": "Opcional: padrão = app do diretório de trabalho (raiz git)"}, "query": {"type": "string"}, "k": {"type": "integer", "description": "resultados (padrão 5, máx 15)"}}, "required": ["query"]}},
    {"name": "list_apps", "description": "Lista os apps indexados e o número de chunks.", "inputSchema": {"type": "object", "properties": {}}},
]


def reply(i, result=None, error=None):
    m = {"jsonrpc": "2.0", "id": i}
    m.update({"error": error} if error else {"result": result})
    sys.stdout.write(json.dumps(m, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(msg):
    method, i = msg.get("method"), msg.get("id")
    if i is None:
        return
    if method == "initialize":
        reply(i, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "kb", "version": "1.0.0"}})
    elif method == "tools/list":
        reply(i, {"tools": TOOLS})
    elif method == "tools/call":
        p = msg.get("params") or {}
        a = p.get("arguments") or {}
        try:
            if p.get("name") == "search_kb":
                app = a.get("app") or default_app()[0]
                known = [r[0] for r in db().execute("SELECT DISTINCT app FROM chunks")]
                if app not in known:
                    text = "app '%s' não está indexado (indexados: %s). Rode `orq-kb index` na raiz do projeto." % (app, ", ".join(known) or "nenhum")
                else:
                    text = fmt(search(app, a["query"], max(1, min(int(a.get("k") or 5), 15))))
            elif p.get("name") == "list_apps":
                text = apps_summary()
            else:
                return reply(i, error={"code": -32602, "message": "tool desconhecida"})
            reply(i, {"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as e:
            reply(i, {"content": [{"type": "text", "text": "erro: %r" % e}], "isError": True})
    elif method == "ping":
        reply(i, {})
    else:
        reply(i, error={"code": -32601, "message": "método desconhecido"})


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    flags = [x for x in rest if x.startswith("-") and x != "-k"]
    k = 5
    if "-k" in rest:
        i = rest.index("-k")
        k = int(rest[i + 1])
        rest = rest[:i] + rest[i + 2:]
    pos = [x for x in rest if not x.startswith("-")]
    if cmd == "index":
        if len(pos) >= 2:
            app, root = pos[0], pos[1]
        elif len(pos) == 1:
            app, root = pos[0], default_app()[1]
        else:
            app, root = default_app()
        cmd_index(app, root, "--no-embed" not in flags and have_embed_model())
    elif cmd == "search" and pos:
        if len(pos) >= 2:
            app, query = pos[0], " ".join(pos[1:])
        else:
            app, query = default_app()[0], pos[0]
        print(fmt(search(app, query, k)))
    elif cmd == "apps":
        print(apps_summary())
    elif cmd == "forget" and pos:
        c = db()
        for (p,) in c.execute("SELECT DISTINCT path FROM chunks WHERE app=?", (pos[0],)).fetchall():
            drop_file(c, pos[0], p)
        c.commit()
        print("app '%s' removido" % pos[0])
    elif cmd == "serve":
        for line in sys.stdin:
            if line.strip():
                try:
                    handle(json.loads(line))
                except json.JSONDecodeError:
                    reply(None, error={"code": -32700, "message": "JSON inválido"})
    else:
        print(__doc__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
