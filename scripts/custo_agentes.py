#!/usr/bin/env python3
"""Relatório de consumo de tokens do OpenCode, por agente e por sessão.

Lê o histórico local (`storage/message/*.json`), separa o que rodou em modelo
**local** (provider `ollama`) do que rodou em modelo **pago** e mostra a razão
entrada/saída — que é o que decide se vale delegar mais trabalho ao local.

Base do raciocínio: em trabalho agêntico a entrada domina (dezenas de tokens lidos
por token escrito). Economizar edição não move a conta; tirar contexto do pago, sim.

Uso:
    python scripts/custo_agentes.py                    # projeto atual
    python scripts/custo_agentes.py --projetos         # todos, resumido
    python scripts/custo_agentes.py --por-sessao       # top sessões
    python scripts/custo_agentes.py --desde 2026-10-01 --ate 2026-10-29
    python scripts/custo_agentes.py --json > custo.json

Só biblioteca padrão. Não chama rede nem o Ollama.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

STORAGE_PADRAO = Path.home() / ".local" / "share" / "opencode" / "storage"
PROVIDER_LOCAL = "ollama"


class Linha:
    """Agregado de um par (agente, modelo), de uma sessão ou de um projeto."""

    CAMPOS = ("msgs", "entrada", "cache_lido", "cache_escrito", "saida", "raciocinio", "custo")

    def __init__(self, chave=("", ""), origem=""):
        self.chave = chave
        self.origem = origem
        self.msgs = 0
        self.entrada = 0
        self.cache_lido = 0
        self.cache_escrito = 0
        self.saida = 0
        self.raciocinio = 0
        self.custo = 0.0

    def somar(self, msg):
        self.msgs += 1
        self.entrada += msg["entrada"]
        self.cache_lido += msg["cache_lido"]
        self.cache_escrito += msg["cache_escrito"]
        self.saida += msg["saida"]
        self.raciocinio += msg["raciocinio"]
        self.custo += msg["custo"]

    def como_dict(self):
        return {
            "chave": list(self.chave),
            "origem": self.origem,
            "msgs": self.msgs,
            "entrada": self.entrada,
            "cache_lido": self.cache_lido,
            "cache_escrito": self.cache_escrito,
            "saida": self.saida,
            "raciocinio": self.raciocinio,
            "custo": round(self.custo, 6),
        }


def _int(valor) -> int:
    """Token vem de histórico de várias versões: aceita int, float, string, None."""
    if isinstance(valor, bool) or valor is None:
        return 0
    try:
        return max(0, int(valor))
    except (TypeError, ValueError):
        return 0


def _float(valor) -> float:
    if isinstance(valor, bool) or valor is None:
        return 0.0
    try:
        return max(0.0, float(valor))
    except (TypeError, ValueError):
        return 0.0


def normalizar(cru: dict, sessao: str = "") -> dict | None:
    """Converte um arquivo de mensagem em registro plano. None se não for assistente."""
    if not isinstance(cru, dict) or cru.get("role") != "assistant":
        return None
    bruto = cru.get("tokens") or {}
    cache = bruto.get("cache") or {}
    return {
        "agente": cru.get("agent") or "(sem agente)",
        "modelo": cru.get("modelID") or cru.get("model") or "?",
        "provider": str(cru.get("providerID") or "?").lower(),
        "sessao": cru.get("sessionID") or sessao,
        "projeto": ((cru.get("path") or {}).get("cwd") or ""),
        "quando": _int((cru.get("time") or {}).get("created")),
        "entrada": _int(bruto.get("input")),
        "saida": _int(bruto.get("output")),
        "raciocinio": _int(bruto.get("reasoning")),
        "cache_lido": _int(cache.get("read")),
        "cache_escrito": _int(cache.get("write")),
        "custo": _float(cru.get("cost")),
    }


def carregar(base: Path) -> tuple[list[dict], dict[str, dict]]:
    """Lê mensagens e sessões. Arquivo corrompido é ignorado, não derruba o relatório."""
    mensagens: list[dict] = []
    for arq in (base / "message").rglob("*.json"):
        try:
            cru = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        reg = normalizar(cru, arq.parent.name)
        if reg:
            mensagens.append(reg)

    sessoes: dict[str, dict] = {}
    for arq in (base / "session").rglob("*.json"):
        try:
            s = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(s, dict) and s.get("id"):
            sessoes[s["id"]] = {
                "titulo": s.get("title") or s.get("slug") or s["id"],
                "dir": s.get("directory") or "",
            }
    return mensagens, sessoes


def mesmo_projeto(cwd: str, prefixo: str) -> bool:
    """Compara caminhos ignorando caixa e separador (Windows)."""
    if not cwd or not prefixo:
        return False
    a = cwd.replace("\\", "/").rstrip("/").lower()
    b = prefixo.replace("\\", "/").rstrip("/").lower()
    return a == b or a.startswith(b + "/")


def filtrar(mensagens, projeto=None, desde=None, ate=None):
    sel = mensagens
    if projeto:
        sel = [m for m in sel if mesmo_projeto(m["projeto"], projeto)]
    if desde is not None:
        sel = [m for m in sel if m["quando"] >= desde]
    if ate is not None:
        sel = [m for m in sel if m["quando"] <= ate]
    return sel


def eh_local(msg) -> bool:
    return msg["provider"] == PROVIDER_LOCAL


def somar(mensagens) -> Linha:
    total = Linha()
    for m in mensagens:
        total.somar(m)
    return total


def agregar(mensagens, chave_fn) -> list[Linha]:
    por: dict = defaultdict(Linha)
    for m in mensagens:
        chave = chave_fn(m)
        linha = por[chave]
        if not linha.origem:
            linha.chave = chave
            linha.origem = "local" if eh_local(m) else "pago"
        linha.somar(m)
    return sorted(por.values(), key=lambda l: -(l.entrada + l.cache_lido))


def totais(mensagens) -> dict:
    pagas = [m for m in mensagens if not eh_local(m)]
    locais = [m for m in mensagens if eh_local(m)]
    return {"pago": somar(pagas), "local": somar(locais), "msgs": len(mensagens)}


def razao(linha: Linha) -> float | None:
    if not linha.saida:
        return None
    return round((linha.entrada + linha.cache_lido) / linha.saida, 1)


def num(n: int) -> str:
    """1234567 -> 1.234.567 (sem depender de locale)."""
    return f"{int(n):,}".replace(",", ".")


def data(ms: int) -> str:
    if not ms:
        return "—"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def tabela(linhas: list[Linha], rotulo: str = "AGENTE") -> str:
    if not linhas:
        return "  (nada)"
    cab = (f"  {rotulo:<18}{'MODELO':<22}{'ORIG':<7}{'MSGS':>6}"
           f"{'ENTRADA':>12}{'CACHE':>12}{'SAIDA':>10}{'CUSTO':>9}")
    out = [cab, "  " + "-" * (len(cab) - 2)]
    for l in linhas:
        agente, modelo = l.chave
        out.append(
            f"  {str(agente)[:17]:<18}{str(modelo)[:21]:<22}{l.origem:<7}{l.msgs:>6}"
            f"{num(l.entrada):>12}{num(l.cache_lido):>12}{num(l.saida):>10}{l.custo:>9.2f}"
        )
    return "\n".join(out)


def relatorio(mensagens, sessoes, por_sessao=False) -> str:
    if not mensagens:
        return "Nenhuma mensagem de assistente encontrada para os filtros informados."

    t = totais(mensagens)
    pago, local = t["pago"], t["local"]
    por_agente = agregar(mensagens, lambda m: (m["agente"], m["modelo"]))

    partes = [
        f"  mensagens: {num(t['msgs'])}   sessões: {num(len({m['sessao'] for m in mensagens}))}",
        "",
        "POR AGENTE",
        tabela(por_agente),
        "",
        "TOTAIS",
        f"  pago   entrada {num(pago.entrada):>12}  cache {num(pago.cache_lido):>12}"
        f"  saída {num(pago.saida):>9}  razão {razao(pago) or '—'}:1",
        f"  local  entrada {num(local.entrada):>12}  cache {num(local.cache_lido):>12}"
        f"  saída {num(local.saida):>9}  razão {razao(local) or '—'}:1",
    ]
    total_ctx = pago.entrada + pago.cache_lido + local.entrada + local.cache_lido
    if total_ctx:
        partes.append(f"  contexto processado no local: "
                      f"{(local.entrada + local.cache_lido) / total_ctx:.1%}")

    if por_sessao:
        linhas = agregar(mensagens, lambda m: (m["sessao"], ""))
        partes += ["", "POR SESSÃO (top 15 por contexto)"]
        for l in linhas[:15]:
            s = sessoes.get(l.chave[0], {})
            titulo = (s.get("titulo") or l.chave[0])[:52]
            partes.append(
                f"  {titulo:<54}{l.msgs:>5} msgs  entrada {num(l.entrada):>10}"
                f"  cache {num(l.cache_lido):>10}  saída {num(l.saida):>8}"
            )
    return "\n".join(partes)


def projetos(mensagens) -> str:
    por = defaultdict(Linha)
    for m in mensagens:
        chave = m["projeto"] or "(sem caminho)"
        linha = por[chave]
        linha.chave = (chave, "")
        linha.somar(m)
    linhas = sorted(por.values(), key=lambda l: -(l.entrada + l.cache_lido))
    out = [f"  {'PROJETO':<58}{'MSGS':>6}{'ENTRADA':>12}{'SAIDA':>10}"]
    for l in linhas:
        out.append(f"  {l.chave[0][-57:]:<58}{l.msgs:>6}{num(l.entrada):>12}{num(l.saida):>10}")
    return "\n".join(out)


def dia(texto: str, fim=False) -> int:
    """'2026-10-01' -> ms epoch. fim=True devolve o último ms do dia."""
    d = datetime.strptime(texto, "%Y-%m-%d")
    if fim:
        d = d.replace(hour=23, minute=59, second=59, microsecond=999000)
    return int(d.timestamp() * 1000)


def principal(argv=None) -> int:
    p = argparse.ArgumentParser(description="Consumo de tokens do OpenCode por agente.")
    p.add_argument("--storage", type=Path,
                   default=Path(os.environ.get("OPENCODE_STORAGE") or STORAGE_PADRAO))
    p.add_argument("--projeto", default=None, help="prefixo do caminho (padrão: diretório atual)")
    p.add_argument("--todos", action="store_true", help="não filtra por projeto")
    p.add_argument("--projetos", action="store_true", help="resumo por projeto e sai")
    p.add_argument("--por-sessao", action="store_true", help="inclui o top de sessões")
    p.add_argument("--desde", help="AAAA-MM-DD (inclusive)")
    p.add_argument("--ate", help="AAAA-MM-DD (inclusive)")
    p.add_argument("--json", action="store_true", help="saída estruturada")
    args = p.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - console sem reconfiguração
        pass

    base = Path(args.storage)
    if not base.is_dir():
        print(f"histórico não encontrado: {base}", file=sys.stderr)
        return 2

    mensagens, sessoes = carregar(base)
    if not mensagens:
        print(f"nenhuma mensagem de assistente em {base}", file=sys.stderr)
        return 2

    if args.projetos:
        print("POR PROJETO\n" + projetos(mensagens))
        return 0

    projeto = None if args.todos else (args.projeto or os.getcwd())
    desde = dia(args.desde) if args.desde else None
    ate = dia(args.ate, fim=True) if args.ate else None

    sel = filtrar(mensagens, projeto, desde, ate)
    if projeto and not sel:
        print(f"nenhuma mensagem para o projeto '{projeto}'.\n"
              "Use --todos (todas as sessões) ou --projetos (lista).", file=sys.stderr)
        return 1

    if args.json:
        t = totais(sel)
        print(json.dumps({
            "projeto": projeto or "(todos)",
            "mensagens": len(sel),
            "sessoes": len({m["sessao"] for m in sel}),
            "por_agente": [l.como_dict() for l in agregar(sel, lambda m: (m["agente"], m["modelo"]))],
            "totais": {"pago": t["pago"].como_dict(), "local": t["local"].como_dict()},
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"\n  PROJETO: {projeto or '(todos)'}")
    if args.desde or args.ate:
        print(f"  PERÍODO: {args.desde or 'início'} → {args.ate or 'hoje'}")
    print()
    print(relatorio(sel, sessoes, args.por_sessao))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(principal())
