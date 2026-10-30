#!/usr/bin/env python3
"""Relatório de consumo de tokens do OpenCode, por agente e por sessão.

Lê o histórico local do OpenCode — `opencode.db` (SQLite, versões atuais) ou, na
falta dele, `storage/message/*.json` — separa o que rodou em modelo **local**
(provider `ollama`) do que rodou em modelo **pago** e mostra a razão entrada/saída,
que é o que decide se vale delegar mais trabalho ao local.

Base do raciocínio: em trabalho agêntico a entrada domina (dezenas de tokens lidos
por token escrito). Economizar edição não move a conta; tirar contexto do pago, sim.

Uso:
    python scripts/custo_agentes.py                    # projeto atual + resumo de economia
    python scripts/custo_agentes.py --economia          # só economia e tendência
    python scripts/custo_agentes.py --diario            # série dia a dia (tokens e economia)
    python scripts/custo_agentes.py --grafico            # 7 dias até hoje, local vs pago
    python scripts/custo_agentes.py --grafico --dias 60  # janela maior
    python scripts/custo_agentes.py --projetos         # todos, resumido
    python scripts/custo_agentes.py --por-sessao       # top sessões
    python scripts/custo_agentes.py --desde 2026-10-01 --ate 2026-10-29
    python scripts/custo_agentes.py --precos precos.json        # estima US$ evitados
    python scripts/custo_agentes.py --comparar experimentos.json  # A/B de configurações
    python scripts/custo_agentes.py --json > custo.json

Só biblioteca padrão. Não chama rede nem o Ollama.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

STORAGE_PADRAO = Path.home() / ".local" / "share" / "opencode"
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
    """Converte um arquivo/mensagem em registro plano. None se não for assistente."""
    papel = cru.get("role")
    if papel is not None and papel != "assistant":
        # V2 (session_message) não tem "role": o tipo vem da coluna.
        return None
    bruto = cru.get("tokens") or {}
    cache = bruto.get("cache") or {}
    modelo = cru.get("modelID") or cru.get("model") or "?"
    provider = cru.get("providerID")
    if isinstance(modelo, dict):
        provider = modelo.get("providerID") or provider
        modelo = modelo.get("id") or "?"
    return {
        "agente": cru.get("agent") or "(sem agente)",
        "modelo": modelo,
        "provider": str(provider or "?").lower(),
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
    """Lê o histórico do OpenCode: `opencode.db` (versões novas) ou `storage/message/*.json`.

    O banco é a fonte atual; o diretório `storage` só é usado quando não há banco.
    """
    base = Path(base)
    if base.is_file():
        return _carregar_db(base)
    banco = base / "opencode.db"
    if banco.is_file():
        return _carregar_db(banco)
    return _carregar_storage(base)


def _carregar_db(caminho: Path) -> tuple[list[dict], dict[str, dict]]:
    """Mensagens e sessões do SQLite do OpenCode (V2 `session_message` ou V1 `message`)."""
    mensagens: list[dict] = []
    sessoes: dict[str, dict] = {}
    try:
        con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error as exc:
        print(f"aviso: não abri {caminho} ({exc}); tentando storage", file=sys.stderr)
        return _carregar_storage(caminho.parent)
    try:
        con.row_factory = sqlite3.Row
        # session_v2 é a tabela recente; session cobre o histórico antigo.
        for tabela in ("session_v2", "session"):
            try:
                linhas = con.execute(f'SELECT id, title, directory FROM "{tabela}"')
            except sqlite3.Error:
                continue
            for r in linhas:
                sessao = sessoes.setdefault(r["id"], {"titulo": "", "dir": ""})
                if not sessao["titulo"] and r["title"]:
                    sessao["titulo"] = r["title"]
                if not sessao["dir"] and r["directory"]:
                    sessao["dir"] = r["directory"]

        try:
            total_v2 = con.execute(
                "SELECT count(*) FROM session_message WHERE type = 'assistant'"
            ).fetchone()[0]
        except sqlite3.Error:
            total_v2 = 0

        if total_v2:
            # V2: data não traz role nem cwd; o tipo vem da coluna e o diretório da sessão.
            # `compaction` também é uma chamada ao modelo e consome tokens. Numa sessão
            # interrompida, a mensagem do assistente fica vazia e sem `tokens`, e a linha
            # de compaction é a única que guarda a contagem — sem ela o uso some do relatório.
            for r in con.execute(
                "SELECT session_id, type, data FROM session_message "
                "WHERE type IN ('assistant', 'compaction')"
            ):
                try:
                    cru = json.loads(r["data"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(cru, dict):
                    continue
                if r["type"] == "compaction" and not cru.get("agent"):
                    cru["agent"] = "(compaction)"
                if not ((cru.get("path") or {}).get("cwd")):
                    diretorio = (sessoes.get(r["session_id"]) or {}).get("dir") or ""
                    cru["path"] = {"cwd": diretorio}
                reg = normalizar(cru, r["session_id"] or "")
                if reg:
                    mensagens.append(reg)
        else:
            for r in con.execute("SELECT session_id, data FROM message"):
                try:
                    cru = json.loads(r["data"])
                except (TypeError, json.JSONDecodeError):
                    continue
                reg = normalizar(cru, r["session_id"] or "")
                if reg:
                    mensagens.append(reg)
    except sqlite3.Error as exc:
        print(f"aviso: {caminho}: {exc}; tentando storage", file=sys.stderr)
        return _carregar_storage(caminho.parent)
    finally:
        con.close()
    for sid, sessao in sessoes.items():
        if not sessao["titulo"]:
            sessao["titulo"] = sid
    return mensagens, sessoes


def _carregar_storage(base: Path) -> tuple[list[dict], dict[str, dict]]:
    """Lê mensagens e sessões dos JSONs antigos. Arquivo corrompido é ignorado."""
    raiz = base / "storage" if (base / "storage").is_dir() else base
    mensagens: list[dict] = []
    for arq in (raiz / "message").rglob("*.json"):
        try:
            cru = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        reg = normalizar(cru, arq.parent.name)
        if reg:
            mensagens.append(reg)

    sessoes: dict[str, dict] = {}
    for arq in (raiz / "session").rglob("*.json"):
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


def tabela(linhas: list[Linha], rotulo: str = "AGENTE", precos=None) -> str:
    if not linhas:
        return "  (nada)"
    cab = (f"  {rotulo:<18}{'MODELO':<22}{'ORIG':<7}{'MSGS':>6}"
           f"{'ENTRADA':>12}{'CACHE':>12}{'SAIDA':>10}{'CUSTO':>9}")
    if precos:
        cab += f"{'EVITADO':>10}"
    out = [cab, "  " + "-" * (len(cab) - 2)]
    for l in linhas:
        agente, modelo = l.chave
        linha = (
            f"  {str(agente)[:17]:<18}{str(modelo)[:21]:<22}{l.origem:<7}{l.msgs:>6}"
            f"{num(l.entrada):>12}{num(l.cache_lido):>12}{num(l.saida):>10}{l.custo:>9.2f}"
        )
        if precos:
            evitado = custo_estimado(l, precos["preco"]) if l.origem == "local" else None
            linha += f"{valor_usd(evitado):>10}"
        out.append(linha)
    return "\n".join(out)


def relatorio(mensagens, sessoes, por_sessao=False, precos=None) -> str:
    if not mensagens:
        return "Nenhuma mensagem de assistente encontrada para os filtros informados."

    t = totais(mensagens)
    pago, local = t["pago"], t["local"]
    por_agente = agregar(mensagens, lambda m: (m["agente"], m["modelo"]))

    partes = [
        f"  mensagens: {num(t['msgs'])}   sessões: {num(len({m['sessao'] for m in mensagens}))}",
        "",
        "POR AGENTE",
        tabela(por_agente, precos=precos),
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


CAMPOS_PRECO = ("input", "cache_read", "cache_write", "output")


def dia_local(ms: int):
    """ms epoch -> date no fuso local. None quando o histórico não tem data."""
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone().date()


def data_dia(ms: int) -> str:
    d = dia_local(ms)
    return d.isoformat() if d else "—"


def contexto(linha: Linha) -> int:
    """Tokens de contexto processados: entrada nova + cache lido + cache escrito."""
    return linha.entrada + linha.cache_lido + linha.cache_escrito


def por_dia(mensagens) -> list[dict]:
    """Agrupa por dia local, do mais antigo para o mais recente."""
    por: dict[str, dict] = {}
    for m in mensagens:
        d = data_dia(m["quando"])
        item = por.setdefault(
            d, {"data": d, "pago": Linha(), "local": Linha(), "sessoes": set()}
        )
        item["local" if eh_local(m) else "pago"].somar(m)
        item["sessoes"].add(m["sessao"])
    return [por[d] for d in sorted(por)]


def fracao(parte: int, total: int):
    return parte / total if total else None


def pct(valor) -> str:
    return "—" if valor is None else f"{valor:.1%}"


def ponto_pct(valor) -> str:
    return "—" if valor is None else f"{valor:+.1f} p.p."


def dinheiro(valor) -> str:
    if valor is None:
        return "—"
    if 0 < valor < 0.01:
        return f"US$ {valor:.4f}"
    return f"US$ {valor:.2f}"


def valor_usd(valor) -> str:
    """Sem o prefixo, para caber nas colunas da tabela."""
    if valor is None:
        return "—"
    return f"{valor:.4f}" if 0 < valor < 0.01 else f"{valor:.2f}"


def carregar_precos(caminho) -> dict:
    """Tabela de preços em US$ por 1M de tokens: {"referencia": "m", "modelos": {"m": {...}}}.

    Sem preço inventado: quem informa o arquivo assume os valores. Levanta ValueError
    com mensagem apontando o campo com problema.
    """
    caminho = Path(caminho)
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"não foi possível ler {caminho}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{caminho}: JSON inválido ({exc})") from exc
    if not isinstance(dados, dict):
        raise ValueError(f"{caminho}: esperado um objeto JSON")
    modelos = dados.get("modelos")
    if not isinstance(modelos, dict) or not modelos:
        raise ValueError(f"{caminho}: campo 'modelos' vazio ou ausente")

    def ler(nome: str) -> dict:
        bruto = modelos.get(nome)
        if not isinstance(bruto, dict):
            raise ValueError(f"{caminho}: preço de '{nome}' ausente ou inválido")
        valores = {}
        for campo in CAMPOS_PRECO:
            bruto_campo = bruto.get(campo, 0.0)
            if isinstance(bruto_campo, bool):
                raise ValueError(f"{caminho}: '{nome}.{campo}' deve ser número, não booleano")
            try:
                valor = float(bruto_campo or 0.0)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{caminho}: '{nome}.{campo}' não é número") from exc
            if valor < 0:
                raise ValueError(f"{caminho}: '{nome}.{campo}' negativo")
            valores[campo] = valor
        return valores

    referencia = dados.get("referencia")
    if referencia is None:
        if len(modelos) != 1:
            raise ValueError(
                f"{caminho}: informe 'referencia' (há {len(modelos)} modelos)"
            )
        referencia = next(iter(modelos))
    if referencia not in modelos:
        raise ValueError(
            f"{caminho}: 'referencia' aponta para '{referencia}', que não está em 'modelos'"
        )
    return {"referencia": referencia, "preco": ler(referencia), "caminho": str(caminho)}


def custo_estimado(linha: Linha, preco: dict) -> float:
    """US$ para os tokens da linha, com preço por 1M de tokens."""
    total = (
        linha.entrada * preco["input"]
        + linha.cache_lido * preco["cache_read"]
        + linha.cache_escrito * preco["cache_write"]
        + linha.saida * preco["output"]
    )
    return total / 1_000_000


def economia(mensagens, precos=None) -> dict:
    """Resumo do que ficou fora do modelo pago e quanto isso custaria se fosse pago."""
    t = totais(mensagens)
    pago, local = t["pago"], t["local"]
    ctx_pago, ctx_local = contexto(pago), contexto(local)
    sessoes = len({m["sessao"] for m in mensagens})
    evitado = custo_estimado(local, precos["preco"]) if precos else None
    return {
        "msgs": t["msgs"],
        "sessoes": sessoes,
        "contexto_pago": ctx_pago,
        "contexto_local": ctx_local,
        "fracao_local": fracao(ctx_local, ctx_pago + ctx_local),
        "pago_entrada": pago.entrada,
        "pago_cache": pago.cache_lido,
        "pago_saida": pago.saida,
        "contexto_pago_por_sessao": (ctx_pago / sessoes) if sessoes else None,
        "custo_registrado": pago.custo,
        "custo_evitado": evitado,
        "custo_evitado_por_sessao": (evitado / sessoes) if evitado is not None and sessoes else None,
        "referencia": precos["referencia"] if precos else None,
    }


def secao_economia(mensagens, precos=None) -> str:
    e = economia(mensagens, precos)
    if not e["msgs"]:
        return "  (nada)"
    partes = [
        f"  contexto pago/sessão     {num(int(e['contexto_pago_por_sessao'] or 0))} tokens"
        f"   em {num(e['sessoes'])} sessões",
        f"  contexto pago            {num(e['contexto_pago'])} tokens"
        f"   (entrada {num(e['pago_entrada'])} · cache {num(e['pago_cache'])}"
        f" · saída {num(e['pago_saida'])})",
        f"  contexto no local        {num(e['contexto_local'])} tokens"
        f"   ({pct(e['fracao_local'])} do total)",
    ]
    if e["custo_registrado"] > 0:
        partes.append(f"  custo pago registrado    {dinheiro(e['custo_registrado'])}")
    if precos:
        partes.append(
            f"  custo evitado estimado   {dinheiro(e['custo_evitado'])}"
            f"   (referência: {e['referencia']})"
        )
        partes.append(
            f"  evitado por sessão       {dinheiro(e['custo_evitado_por_sessao'])}"
        )
    else:
        partes.append("  custo evitado estimado   —  (use --precos para estimar em US$)")
    if not e["contexto_local"]:
        partes.append("  aviso: nenhum token rodou no local no período; ainda não há economia a medir")
    return "\n".join(partes)


def _variacao(antes, depois) -> str:
    if antes is None or depois is None:
        return "—"
    if antes == 0:
        return "—" if depois == 0 else "novo"
    return f"{(depois - antes) / abs(antes):+.1%}"


def tendencia(mensagens, precos=None, dias: int = 7) -> str:
    """Compara os últimos N dias do histórico com os N anteriores (ancorado no último registro)."""
    datados = [(dia_local(m["quando"]), m) for m in mensagens]
    datados = [(d, m) for d, m in datados if d is not None]
    if not datados:
        return "  (nada)"
    fim = max(d for d, _ in datados)
    janelas = []
    for deslocamento in (0, dias):
        termina = fim - timedelta(days=deslocamento)
        comeca = termina - timedelta(days=dias - 1)
        sel = [m for d, m in datados if comeca <= d <= termina]
        janelas.append(economia(sel, precos))
    antes, depois = janelas[1], janelas[0]
    delta_local = (
        None
        if antes["fracao_local"] is None or depois["fracao_local"] is None
        else (depois["fracao_local"] - antes["fracao_local"]) * 100
    )
    linhas = [
        f"  TENDÊNCIA ({dias} dias até {fim.isoformat()} vs os {dias} anteriores)",
        f"  contexto pago/sessão     {num(int(antes['contexto_pago_por_sessao'] or 0))}"
        f" → {num(int(depois['contexto_pago_por_sessao'] or 0))}"
        f"   {_variacao(antes['contexto_pago_por_sessao'], depois['contexto_pago_por_sessao'])}",
        f"  contexto no local        {pct(antes['fracao_local'])} → {pct(depois['fracao_local'])}"
        f"   {ponto_pct(delta_local)}",
    ]
    if precos:
        linhas.append(
            f"  custo evitado            {dinheiro(antes['custo_evitado'])} → {dinheiro(depois['custo_evitado'])}"
            f"   {_variacao(antes['custo_evitado'], depois['custo_evitado'])}"
        )
    return "\n".join(linhas)


def secao_diario(mensagens, precos=None) -> str:
    linhas = por_dia(mensagens)
    if not linhas:
        return "  (nada)"
    cab = (f"  {'DATA':<12}{'MSGS':>6}{'SESS':>6}{'PAGO-ENT':>11}{'PAGO-CACHE':>12}"
           f"{'PAGO-SAI':>10}{'LOCAL-ENT':>11}{'LOCAL-SAI':>11}{'%LOCAL':>8}{'EVITADO':>10}")
    out = [cab, "  " + "-" * (len(cab) - 2)]
    for item in linhas:
        pago, local = item["pago"], item["local"]
        evitado = custo_estimado(local, precos["preco"]) if precos else None
        out.append(
            f"  {item['data']:<12}{pago.msgs + local.msgs:>6}{len(item['sessoes']):>6}"
            f"{num(pago.entrada):>11}{num(pago.cache_lido):>12}{num(pago.saida):>10}"
            f"{num(local.entrada):>11}{num(local.saida):>11}"
            f"{pct(fracao(contexto(local), contexto(pago) + contexto(local))):>8}"
            f"{valor_usd(evitado):>10}"
        )
    return "\n".join(out)


def barra(valor: int, maximo: int, largura: int = 20) -> str:
    """Barra horizontal sem cor: cheio/░, sempre com a mesma largura."""
    if maximo <= 0 or valor <= 0:
        return "░" * largura
    cheio = max(1, min(largura, round(valor / maximo * largura)))
    return "█" * cheio + "░" * (largura - cheio)


def secao_grafico(mensagens, precos=None, dias: int = 7, largura: int = 20) -> str:
    """Uso diário dos modelos locais contra o pago, na janela que termina hoje."""
    dias = min(366, max(1, int(dias or 1)))  # 1 dia a 1 ano; evita despejar milhares de linhas
    fim = datetime.now().date()
    inicio = fim - timedelta(days=dias - 1)
    dentro = [
        m for m in mensagens
        if (d := dia_local(m["quando"])) is not None and inicio <= d <= fim
    ]
    if not dentro:
        return f"  (sem uso nos últimos {dias} dia(s), até {fim.isoformat()})"

    por_data: dict = {}
    for m in dentro:
        d = dia_local(m["quando"])
        slot = por_data.setdefault(d, {"pago": Linha(), "local": Linha(), "sessoes": set()})
        slot["local" if eh_local(m) else "pago"].somar(m)
        slot["sessoes"].add(m["sessao"])

    periodo = []
    d = inicio
    while d <= fim:
        slot = por_data.get(d, {"pago": Linha(), "local": Linha(), "sessoes": set()})
        periodo.append((d, slot))
        d += timedelta(days=1)

    max_local = max(contexto(s["local"]) for _, s in periodo)
    max_pago = max(contexto(s["pago"]) for _, s in periodo)
    com_atividade = sum(1 for _, s in periodo if s["pago"].msgs + s["local"].msgs)

    cab = (f"  {'DATA':<12}{'LOCAL':<{largura + 11}}  {'PAGO':<{largura + 12}}"
           f"  {'%LOCAL':>7}")
    out = [
        f"  USO POR DIA — últimos {dias} dia(s), até {fim.isoformat()}"
        f"   ({com_atividade} com atividade; barras em escala própria)",
        cab,
        "  " + "-" * (len(cab) - 2),
    ]
    for d, s in periodo:
        ctx_local, ctx_pago = contexto(s["local"]), contexto(s["pago"])
        out.append(
            f"  {d.isoformat():<12}{barra(ctx_local, max_local, largura):<{largura}}"
            f"{num(ctx_local):>11}  {barra(ctx_pago, max_pago, largura):<{largura}}"
            f"{num(ctx_pago):>12}  {pct(fracao(ctx_local, ctx_local + ctx_pago)):>7}"
        )

    locais = [m for m in dentro if eh_local(m)]
    if locais:
        por_modelo = agregar(locais, lambda m: (m["modelo"], ""))
        out += ["", "  POR MODELO LOCAL"]
        cab2 = f"  {'MODELO':<28}{'MSGS':>6}{'CONTEXTO':>12}{'SAIDA':>11}"
        if precos:
            cab2 += f"{'EVITADO':>10}"
        out += [cab2, "  " + "-" * (len(cab2) - 2)]
        for l in por_modelo:
            linha = (f"  {str(l.chave[0])[:27]:<28}{l.msgs:>6}"
                     f"{num(contexto(l)):>12}{num(l.saida):>11}")
            if precos:
                linha += f"{valor_usd(custo_estimado(l, precos['preco'])):>10}"
            out.append(linha)
    else:
        out += ["", "  nenhum modelo local usado no período"]
    return "\n".join(out)


def carregar_experimentos(caminho) -> list[dict]:
    """Lista de janelas rotuladas: [{"nome": ..., "de": "AAAA-MM-DD", "ate": ..., "tag": ..., "nota": ...}]."""
    caminho = Path(caminho)
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"não foi possível ler {caminho}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{caminho}: JSON inválido ({exc})") from exc
    if not isinstance(dados, list) or not dados:
        raise ValueError(f"{caminho}: esperado uma lista não vazia de experimentos")
    experimentos = []
    for i, bruto in enumerate(dados, 1):
        if not isinstance(bruto, dict):
            raise ValueError(f"{caminho}: experimento {i} não é um objeto")
        nome = str(bruto.get("nome") or f"exp{i}").strip()
        de, ate = bruto.get("de"), bruto.get("ate")
        for rotulo, valor in (("de", de), ("ate", ate)):
            if valor is None:
                continue
            try:
                datetime.strptime(str(valor), "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError(
                    f"{caminho}: '{nome}.{rotulo}' deve ser AAAA-MM-DD (recebido {valor!r})"
                ) from exc
        if de and ate and str(de) > str(ate):
            raise ValueError(f"{caminho}: '{nome}' começa depois de terminar ({de} > {ate})")
        if not de and not ate and not bruto.get("tag"):
            raise ValueError(f"{caminho}: '{nome}' precisa de 'de'/'ate' ou 'tag'")
        experimentos.append({
            "nome": nome,
            "de": str(de) if de else None,
            "ate": str(ate) if ate else None,
            "tag": str(bruto.get("tag")).strip() if bruto.get("tag") else "",
            "nota": str(bruto.get("nota") or "").strip(),
        })
    return experimentos


def _selecionar_periodo(mensagens, sessoes, exp) -> list[dict]:
    de = dia(exp["de"]) if exp.get("de") else None
    ate = dia(exp["ate"], fim=True) if exp.get("ate") else None
    sel = filtrar(mensagens, None, de, ate)
    if exp.get("tag"):
        agulha = str(exp["tag"]).lower()
        sel = [
            m for m in sel
            if agulha in sessoes.get(m["sessao"], {}).get("titulo", "").lower()
            or agulha in m["sessao"].lower()
        ]
    return sel


def comparar(mensagens, sessoes, experimentos, precos=None) -> str:
    """Lado a lado de janelas (configurações) para achar o que de fato economiza tokens."""
    if not experimentos:
        return "  (nenhum experimento)"
    janelas = []
    for exp in experimentos:
        sel = _selecionar_periodo(mensagens, sessoes, exp)
        janelas.append((exp, economia(sel, precos)))

    cab = (f"  {'EXPERIMENTO':<20}{'MSGS':>6}{'SESS':>6}{'PAGO/SESS':>12}"
           f"{'LOCAL':>8}{'EVITADO':>10}  {'NOTA':<12}")
    out = [cab, "  " + "-" * (len(cab) - 2)]
    for exp, e in janelas:
        nome = str(exp.get("nome") or "?")
        nota = str(exp.get("nota") or "")
        out.append(
            f"  {nome[:19]:<20}{e['msgs']:>6}{e['sessoes']:>6}"
            f"{num(int(e['contexto_pago_por_sessao'] or 0)):>12}"
            f"{pct(e['fracao_local']):>8}{valor_usd(e['custo_evitado']):>10}"
            f"  {nota[:12]:<12}"
        )
    if len(janelas) > 1:
        base_exp, base = janelas[0]
        nome_base = str(base_exp.get("nome") or "?")
        out.append("")
        out.append(f"  Δ contra '{nome_base}' (negativo em PAGO/SESS é melhoria)")
        for exp, e in janelas[1:]:
            nome = str(exp.get("nome") or "?")[:19]
            variacao_pago = _variacao(
                base["contexto_pago_por_sessao"], e["contexto_pago_por_sessao"]
            )
            delta_local = (
                None
                if base["fracao_local"] is None or e["fracao_local"] is None
                else (e["fracao_local"] - base["fracao_local"]) * 100
            )
            variacao_evitado = _variacao(base["custo_evitado"], e["custo_evitado"])
            out.append(
                f"  {nome:<20} pago/sess {variacao_pago:>8}"
                f"   local {ponto_pct(delta_local):>8}"
                f"   evitado {variacao_evitado:>8}"
            )
    if not precos:
        out.append("  (EVITADO em branco: use --precos para estimar em US$)")
    vazios = [str(exp.get("nome") or "?") for exp, e in janelas if not e["msgs"]]
    if vazios:
        out.append(f"  aviso: sem mensagens no filtro — {', '.join(vazios)}")
    return "\n".join(out)


def dia(texto: str, fim=False) -> int:
    """'2026-10-01' -> ms epoch. fim=True devolve o último ms do dia."""
    d = datetime.strptime(texto, "%Y-%m-%d")
    if fim:
        d = d.replace(hour=23, minute=59, second=59, microsecond=999000)
    return int(d.timestamp() * 1000)


def principal(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Consumo de tokens e economia do OpenCode por agente, dia e configuração."
    )
    p.add_argument("--storage", type=Path,
                   default=Path(os.environ.get("OPENCODE_STORAGE") or STORAGE_PADRAO),
                   help="diretório do histórico ou o opencode.db")
    p.add_argument("--projeto", default=None, help="prefixo do caminho (padrão: diretório atual)")
    p.add_argument("--todos", action="store_true", help="não filtra por projeto")
    p.add_argument("--projetos", action="store_true", help="resumo por projeto e sai")
    p.add_argument("--por-sessao", action="store_true", help="inclui o top de sessões")
    p.add_argument("--diario", action="store_true", help="série dia a dia, com economia por dia")
    p.add_argument("--grafico", action="store_true", help="gráfico de uso diário local vs pago")
    p.add_argument("--dias", type=int, default=7, help="janela do gráfico em dias, terminando hoje (padrão 7)")
    p.add_argument("--economia", action="store_true", help="mostra só economia e tendência")
    p.add_argument("--precos", type=Path, help="tabela de preços em US$ por 1M de tokens (JSON)")
    p.add_argument("--comparar", type=Path, help="janelas de experimento (JSON) para comparar")
    p.add_argument("--desde", help="AAAA-MM-DD (inclusive)")
    p.add_argument("--ate", help="AAAA-MM-DD (inclusive)")
    p.add_argument("--json", action="store_true", help="saída estruturada")
    args = p.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - console sem reconfiguração
        pass

    base = Path(args.storage)
    if not base.is_dir() and not base.is_file():
        print(f"histórico não encontrado: {base}", file=sys.stderr)
        return 2

    mensagens, sessoes = carregar(base)
    if not mensagens:
        print(f"nenhuma mensagem de assistente em {base}", file=sys.stderr)
        return 2

    precos = None
    if args.precos:
        try:
            precos = carregar_precos(args.precos)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2

    if args.projetos:
        print("POR PROJETO\n" + projetos(mensagens))
        return 0

    projeto = args.projeto or (None if args.todos else os.getcwd())

    if args.comparar:
        try:
            experimentos = carregar_experimentos(args.comparar)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        base_comparacao = filtrar(mensagens, projeto)
        if not base_comparacao:
            print(f"nenhuma mensagem para o projeto '{projeto}'.\n"
                  "Use --todos (todas as sessões) ou --projetos (lista).", file=sys.stderr)
            return 1
        print(f"\n  PROJETO: {projeto or '(todos)'}")
        print(f"  EXPERIMENTOS: {args.comparar}")
        print()
        print(comparar(base_comparacao, sessoes, experimentos, precos))
        print()
        return 0

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
            "economia": economia(sel, precos),
            "diario": [
                {
                    "data": item["data"],
                    "msgs": item["pago"].msgs + item["local"].msgs,
                    "sessoes": len(item["sessoes"]),
                    "pago": item["pago"].como_dict(),
                    "local": item["local"].como_dict(),
                }
                for item in por_dia(sel)
            ],
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"\n  PROJETO: {projeto or '(todos)'}")
    if args.desde or args.ate:
        print(f"  PERÍODO: {args.desde or 'início'} → {args.ate or 'hoje'}")
    print()
    if args.economia:
        print(secao_economia(sel, precos))
        print()
        print(tendencia(sel, precos))
        if args.diario:
            print()
            print("POR DIA")
            print(secao_diario(sel, precos))
        if args.grafico:
            print()
            print(secao_grafico(sel, precos, args.dias))
        print()
        return 0
    print(relatorio(sel, sessoes, args.por_sessao, precos))
    print()
    print("ECONOMIA")
    print(secao_economia(sel, precos))
    print()
    print(tendencia(sel, precos))
    if args.diario:
        print()
        print("POR DIA")
        print(secao_diario(sel, precos))
    if args.grafico:
        print()
        print(secao_grafico(sel, precos, args.dias))
    if not precos:
        print()
        print("  --precos precos.json estima os US$ evitados   |   --comparar experimentos.json faz o A/B")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(principal())
