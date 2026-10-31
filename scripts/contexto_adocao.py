#!/usr/bin/env python3
"""Adoção do Context Manager: quem chamou o MCP `contexto` em vez de ler arquivo.

Lê o histórico do OpenCode (`opencode.db`, V2 `session_message`) e conta, por
sessão, as chamadas de ferramenta:

  contexto  contexto_*            (context_build, context_get_file, ...)
  leitura   read, grep, glob      + kb_* e trail_* (busca também lê)
  outros    shell, edit, run_tests, ...

A taxa de adoção é a fração de sessões com trabalho de ferramenta que usaram o
MCP de contexto. Ela mede **escolha**, não resultado — o efeito na qualidade é
a Fase 6 do roadmap.

Uso:
  python3 scripts/contexto_adocao.py                 # projeto atual, últimos 7 dias
  python3 scripts/contexto_adocao.py --todos --dias 30
  python3 scripts/contexto_adocao.py --desde 2026-10-01 --json
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

STORAGE_PADRAO = Path.home() / ".local" / "share" / "opencode"
PREFIXO_CONTEXTO = "contexto_"
LEITURA = {"read", "grep", "glob"}


def _int(valor) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def categoria(nome: str) -> str:
    """Classifica o nome da ferramenta como aparece no banco."""
    nome = str(nome or "")
    if nome.startswith(PREFIXO_CONTEXTO):
        return "contexto"
    if nome in LEITURA or nome.startswith("kb_") or nome.startswith("trail_"):
        return "leitura"
    return "outros"


def _conexao(base: Path) -> sqlite3.Connection:
    banco = base if base.is_file() else base / "opencode.db"
    if not banco.is_file():
        raise SystemExit(f"histórico não encontrado: {banco}")
    con = sqlite3.connect(f"file:{banco}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def chamadas(base: Path, projeto=None, desde=None, ate=None) -> list[dict]:
    """Uma linha por chamada de ferramenta, com sessão, projeto e arquivo."""
    con = _conexao(base)
    sessoes = {}
    try:
        for r in con.execute("SELECT id, title, directory FROM session_v2"):
            sessoes[r["id"]] = {"titulo": r["title"] or r["id"], "dir": r["directory"] or ""}
    except sqlite3.Error:
        pass
    saida = []
    try:
        for r in con.execute(
            "SELECT session_id, time_created, data FROM session_message WHERE type = 'assistant'"
        ):
            try:
                dados = json.loads(r["data"])
            except (TypeError, json.JSONDecodeError):
                continue
            quando = _int((dados.get("time") or {}).get("created")) or _int(r["time_created"])
            if desde is not None and quando < desde:
                continue
            if ate is not None and quando > ate:
                continue
            sessao = r["session_id"] or ""
            info = sessoes.get(sessao) or {"titulo": sessao, "dir": ""}
            for parte in dados.get("content") or []:
                if parte.get("type") != "tool":
                    continue
                entrada = (parte.get("state") or {}).get("input") or {}
                arquivo = entrada.get("path") or entrada.get("filePath") or entrada.get("file") or ""
                saida.append({
                    "sessao": sessao,
                    "projeto": info["dir"],
                    "titulo": info["titulo"],
                    "quando": quando,
                    "ferramenta": parte.get("name") or "?",
                    "categoria": categoria(parte.get("name")),
                    "arquivo": str(arquivo),
                })
    finally:
        con.close()
    if projeto:
        prefixo = projeto.rstrip("/").lower()
        saida = [c for c in saida if c["projeto"].lower().startswith(prefixo)]
    return saida


def por_sessao(itens: list[dict]) -> dict:
    """Agrupa por sessão com contagem por categoria e arquivos lidos."""
    sessoes: dict[str, dict] = {}
    for c in itens:
        s = sessoes.setdefault(c["sessao"], {
            "sessao": c["sessao"], "titulo": c["titulo"], "quando": c["quando"],
            "contexto": 0, "leitura": 0, "outros": 0, "arquivos": set(),
        })
        s[c["categoria"]] += 1
        s["quando"] = max(s["quando"], c["quando"])
        if c["categoria"] == "leitura" and c["arquivo"]:
            s["arquivos"].add(c["arquivo"])
    for s in sessoes.values():
        s["arquivos"] = len(s["arquivos"])
    return sessoes


def resumo(itens: list[dict]) -> dict:
    sessoes = por_sessao(itens)
    total = len(sessoes)
    com = [s for s in sessoes.values() if s["contexto"]]
    leituras = sum(s["leitura"] for s in sessoes.values())
    contexto = sum(s["contexto"] for s in sessoes.values())
    return {
        "sessoes": total,
        "sessoes_com_contexto": len(com),
        "adocao_pct": round(100 * len(com) / total, 1) if total else 0.0,
        "chamadas_contexto": contexto,
        "chamadas_leitura": leituras,
        "leituras_por_sessao": round(leituras / total, 1) if total else 0.0,
        "arquivos_lidos_distintos": len({c["arquivo"] for c in itens
                                         if c["categoria"] == "leitura" and c["arquivo"]}),
    }


def relatorio(itens: list[dict], top: int = 8) -> str:
    if not itens:
        return "  (nenhuma chamada de ferramenta no período)"
    r = resumo(itens)
    linhas = [
        f"  sessões com ferramenta      {r['sessoes']}",
        f"  usaram o MCP de contexto    {r['sessoes_com_contexto']} ({r['adocao_pct']}%)",
        f"  chamadas de contexto        {r['chamadas_contexto']}",
        f"  leituras diretas            {r['chamadas_leitura']} "
        f"({r['leituras_por_sessao']} por sessão)",
        f"  arquivos distintos lidos    {r['arquivos_lidos_distintos']}",
    ]
    sessoes = sorted(por_sessao(itens).values(), key=lambda s: (-s["contexto"], -s["leitura"]))[:top]
    if sessoes:
        linhas += ["", f"  {'CTX':>4} {'LEIT':>5} {'ARQ':>4}  SESSÃO"]
        for s in sessoes:
            linhas.append(f"  {s['contexto']:>4} {s['leitura']:>5} {s['arquivos']:>4}  {s['titulo'][:46]}")
    return "\n".join(linhas)


def _ms(texto: str, fim: bool = False) -> int:
    try:
        d = datetime.strptime(texto, "%Y-%m-%d")
    except ValueError as exc:
        raise SystemExit(f"data inválida: {texto} (use AAAA-MM-DD)") from exc
    if fim:
        d = d + timedelta(days=1)
    return int(d.timestamp() * 1000)


def principal(argv=None) -> int:
    p = argparse.ArgumentParser(description="Adoção do MCP de contexto por sessão.")
    p.add_argument("--storage", type=Path,
                   default=Path(os.environ.get("OPENCODE_STORAGE") or STORAGE_PADRAO),
                   help="diretório do histórico ou o opencode.db")
    p.add_argument("--projeto", default=None, help="prefixo do caminho (padrão: diretório atual)")
    p.add_argument("--todos", action="store_true", help="não filtra por projeto")
    p.add_argument("--dias", type=int, default=7, help="janela que termina hoje (padrão 7)")
    p.add_argument("--desde", help="AAAA-MM-DD (inclusive)")
    p.add_argument("--ate", help="AAAA-MM-DD (inclusive)")
    p.add_argument("--json", action="store_true", help="saída estruturada")
    args = p.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    desde = _ms(args.desde) if args.desde else None
    ate = _ms(args.ate, fim=True) if args.ate else None
    if desde is None:
        desde = int((datetime.now() - timedelta(days=max(1, args.dias))).timestamp() * 1000)
    projeto = None if args.todos else (args.projeto or os.getcwd())

    itens = chamadas(Path(args.storage), projeto, desde, ate)
    if args.json:
        print(json.dumps({"projeto": projeto or "(todos)", "resumo": resumo(itens),
                          "sessoes": list(por_sessao(itens).values())}, ensure_ascii=False,
                         indent=2, default=list))
        return 0
    print(f"\n  PROJETO: {projeto or '(todos)'}")
    print(f"  janela:  {datetime.fromtimestamp(desde / 1000).date()} → hoje\n")
    print(relatorio(itens))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(principal())
