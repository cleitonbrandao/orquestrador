#!/usr/bin/env python3
"""Servidor MCP (stdio) que consulta um modelo de DECISÃO local do Ollama.

Serve para o orquestrador classificar pedidos (só docs? quantos arquivos? qual área?)
sem gastar tokens do modelo pago. Usa `/v1/systemone`, o mesmo caminho da trilha E
(`scripts/testar_decisor.py`), então o comportamento é o que foi medido:
`d3:2b` acerta 92% dos 24 casos e escala em 8%.

Regra de escalada (a mesma de `scripts/avaliar_decisao.py`):
  - escolha "nenhuma"  -> escala sempre (o caso não é o que o modelo sabe decidir)
  - confiança < limiar -> escala (o modelo respondeu, mas sem convicção)
  - sem escolha        -> bloqueado (nada foi decidido)

Sem dependências: só biblioteca padrão. Requer o Ollama em execução.

  ORQ_DECISOR_MODEL  modelo (padrão: d3:2b)
  OLLAMA_HOST_URL    base da API (padrão: http://localhost:11434)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

NAME, VERSION = "decisao", "1.0.0"
PROTOCOL = "2024-11-05"
MODELO = os.environ.get("ORQ_DECISOR_MODEL", "d3:2b")
API = os.environ.get("OLLAMA_HOST_URL", "http://localhost:11434").rstrip("/")
LIMIAR = 0.7
TIMEOUT = 60

TOOL = {
    "name": "orq_decidir",
    "description": (
        "Classifica um texto com um modelo de decisão LOCAL (d3:2b), sem gastar tokens pagos. "
        "Use para triagem: o pedido só mexe em Markdown? é uma área só? qual família? "
        "Devolve a escolha, a confiança e se deve escalar para o modelo maior. "
        "Escala quando a escolha é 'nenhuma' ou a confiança fica abaixo do limiar."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "texto": {"type": "string", "description": "O texto a classificar (pedido, ticket, descrição do diff)"},
            "pergunta": {"type": "string", "description": "A pergunta de escolha, ex.: 'Qual área do código este pedido afeta?'"},
            "opcoes": {
                "type": "object",
                "description": "Mapa id -> descrição das opções. Ex.: {'docs': 'só Markdown', 'backend': 'PHP/Laravel'}",
                "additionalProperties": {"type": "string"},
            },
            "limiar": {"type": "number", "description": "Confiança mínima para não escalar (padrão 0.7)"},
        },
        "required": ["texto", "pergunta", "opcoes"],
    },
}


class DecisaoError(Exception):
    """Falha ao consultar o decisor (Ollama fora do ar, modelo ausente, resposta inválida)."""


def http(caminho, corpo, timeout=TIMEOUT):
    dados = json.dumps(corpo).encode("utf-8")
    req = urllib.request.Request(
        API + caminho, data=dados, headers={"content-type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8", "replace")).get("error", "")
        except Exception:  # noqa: BLE001 - corpo de erro nem sempre é JSON
            msg = ""
        raise DecisaoError(f"HTTP {e.code}: {msg or e.reason}") from e
    except urllib.error.URLError as e:
        raise DecisaoError(f"Ollama não respondeu em {API}: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise DecisaoError(f"resposta inválida do Ollama: {e}") from e


def corpo_do_pedido(texto, pergunta, opcoes, modelo=MODELO):
    """Monta o /v1/systemone. 'nenhuma' entra sempre, como em testar_decisor.py."""
    criterios = dict(opcoes)
    criterios.setdefault("nenhuma", "Nenhuma das opções descreve o texto.")
    return {
        "model": modelo,
        "state": texto,
        "keep_alive": "10m",
        "questions": {
            "escolha": {
                "type": "choice",
                "instructions": pergunta,
                "criteria": criterios,
            }
        },
    }


def extrair(resposta):
    """Devolve (escolha, confianca) da resposta do /v1/systemone."""
    respostas = resposta.get("answers") or {}
    bruto = respostas.get("escolha")
    if bruto is None:
        raise DecisaoError("resposta sem o campo 'escolha'")
    if isinstance(bruto, str):
        try:
            bruto = json.loads(bruto)
        except json.JSONDecodeError as e:
            raise DecisaoError(f"'escolha' não é JSON: {bruto!r}") from e
    if not isinstance(bruto, dict):
        raise DecisaoError(f"'escolha' inesperado: {bruto!r}")

    escolha = bruto.get("choice")
    if not isinstance(escolha, str) or not escolha:
        raise DecisaoError(f"resposta sem 'choice' utilizável: {bruto!r}")

    confianca = bruto.get("confidence")
    if isinstance(confianca, bool) or not isinstance(confianca, (int, float)):
        confianca = None
    return escolha, confianca


def avaliar(escolha, confianca, limiar=LIMIAR):
    """Devolve (escalar, motivo). Espelha a regra de avaliar_decisao.py."""
    if escolha == "nenhuma":
        return True, "'nenhuma' (sempre escala)"
    if confianca is None:
        return True, "sem confiança declarada"
    if confianca < limiar:
        return True, f"confiança {confianca:.2f} < {limiar:.2f}"
    return False, f"confiança {confianca:.2f} >= {limiar:.2f}"


def decidir(argumentos):
    texto = (argumentos.get("texto") or "").strip()
    pergunta = (argumentos.get("pergunta") or "").strip()
    opcoes = argumentos.get("opcoes") or {}
    limiar = argumentos.get("limiar", LIMIAR)

    if not texto:
        return {"resultado": "bloqueado", "motivo": "texto vazio", "modelo": MODELO}
    if not pergunta:
        return {"resultado": "bloqueado", "motivo": "pergunta vazia", "modelo": MODELO}
    if not isinstance(opcoes, dict) or not opcoes:
        return {"resultado": "bloqueado", "motivo": "opcoes vazio", "modelo": MODELO}
    try:
        limiar = float(limiar)
    except (TypeError, ValueError):
        limiar = LIMIAR

    inicio = time.perf_counter()
    try:
        resposta = http("/v1/systemone", corpo_do_pedido(texto, pergunta, opcoes))
    except DecisaoError as e:
        return {"resultado": "bloqueado", "motivo": str(e), "modelo": MODELO}
    ms = int((time.perf_counter() - inicio) * 1000)

    try:
        escolha, confianca = extrair(resposta)
    except DecisaoError as e:
        return {"resultado": "bloqueado", "motivo": str(e), "modelo": MODELO, "ms": ms}

    escalar, motivo = avaliar(escolha, confianca, limiar)
    return {
        "resultado": "escalar" if escalar else "decidido",
        "escolha": escolha,
        "confianca": confianca,
        "motivo": motivo,
        "limiar": limiar,
        "modelo": MODELO,
        "ms": ms,
    }


def texto_do_resultado(r):
    if r["resultado"] == "bloqueado":
        return f"RESULTADO: bloqueado\nMOTIVO: {r['motivo']}\nMODELO: {r['modelo']}"
    conf = "?" if r["confianca"] is None else f"{r['confianca']:.2f}"
    corpo = (
        f"RESULTADO: {r['resultado']}\n"
        f"ESCOLHA: {r['escolha']}\n"
        f"CONFIANCA: {conf}\n"
        f"MOTIVO: {r['motivo']}\n"
        f"MODELO: {r['modelo']} ({r['ms']} ms)"
    )
    if r["resultado"] == "escalar":
        corpo += "\nACAO: decida no modelo principal; a escolha local não é confiável."
    return corpo


def reply(msg_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": msg_id}
    msg.update({"error": error} if error else {"result": result})
    try:
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    except UnicodeEncodeError:
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
        if params.get("name") != "orq_decidir":
            return reply(msg_id, error={"code": -32602, "message": "tool desconhecida"})
        try:
            r = decidir(params.get("arguments") or {})
        except Exception as e:  # nunca derrubar o servidor
            r = {"resultado": "bloqueado", "motivo": f"erro interno: {e!r}", "modelo": MODELO}
        reply(msg_id, {
            "content": [{"type": "text", "text": texto_do_resultado(r)}],
            "structuredContent": r,
            "isError": r["resultado"] == "bloqueado",
        })
    elif method == "ping":
        reply(msg_id, {})
    else:
        reply(msg_id, error={"code": -32601, "message": f"método desconhecido: {method}"})


def use_utf8_stdio():
    """O protocolo MCP é UTF-8; no Windows o console usa o code page local."""
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main():
    use_utf8_stdio()
    for line in sys.stdin:
        line = line.strip()
        if line:
            try:
                handle(json.loads(line))
            except json.JSONDecodeError:
                reply(None, error={"code": -32700, "message": "JSON inválido"})


if __name__ == "__main__":
    main()
