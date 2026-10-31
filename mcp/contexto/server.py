#!/usr/bin/env python3
"""MCP local do Context Manager (roadmap §10). Somente leitura.

Sete ferramentas:
  context_build        monta o pacote (§6) para uma tarefa, com resumo local
  context_get_file     trecho de arquivo validado (arquivo:linha)
  context_get_rules    regras de negócio do projeto
  context_get_decisions decisões técnicas, filtradas por relevância
  context_validate     revalida um pacote já montado
  context_metrics      agregados das execuções (redução, tokens, modelo)
  context_search       busca textual na base do `kb` (se o app estiver indexado)

Regras de segurança (§11): nada é escrito no projeto, `.env` é recusado,
caminho fora da raiz é recusado e conteúdo de arquivo é dado, nunca instrução.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ_REPO / "scripts"))
sys.path.insert(0, str(RAIZ_REPO / "mcp" / "kb"))

import contexto_cache as cc  # noqa: E402
import contexto_local as cl  # noqa: E402
import contexto_memoria as cm  # noqa: E402
import contexto_pacote as cp  # noqa: E402

PROTOCOL = "2024-11-05"
NAME = "orq-contexto"
VERSION = "0.1.0"
MODELO = os.environ.get("ORQ_CONTEXT_MODEL", "qwen3.5-2b-32k")
HOST = os.environ.get("OLLAMA_HOST_URL", "http://localhost:11434")
MAX_LINHAS_ARQUIVO = 400

# Orçamento por tipo de tarefa (bytes de fonte). O perfil determina o que é
# enviado ao modelo local; a latência, nesta máquina, varia com o estado da CPU
# e o carregamento do modelo (medido: 2,7 mil tokens entre 77 e 87 s com a máquina
# ocupada, 8,1 mil tokens em 32 s com o modelo quente). Não prometa tempo.
PERFIS = {
    "rapida": {"max_total": 6000, "num_predict": 300},
    "leitura": {"max_total": 16000, "num_predict": 500},
    "completa": {"max_total": 48000, "num_predict": 700},
}


class ContextoServerError(Exception):
    """Erro de uso; vira isError na resposta, não derruba o servidor."""


def _raiz(valor) -> Path:
    raiz = Path(str(valor or ".")).expanduser().resolve()
    if not raiz.is_dir():
        raise ContextoServerError(f"raiz inexistente: {raiz}")
    return raiz


def _estado() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "orquestrador" / "contexto"


def _metricas_registrar(registro: dict) -> None:
    destino = _estado() / "metrics.jsonl"
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except OSError:
        pass  # métrica não pode derrubar a ferramenta


def _ler_arquivo(raiz: Path, relativo: str, inicio=None, fim=None) -> dict:
    alvo = cp._resolver(relativo, raiz)
    if not cp.caminho_permitido(alvo, raiz):
        raise ContextoServerError(f"caminho recusado: {relativo}")
    if not alvo.is_file():
        raise ContextoServerError(f"arquivo não existe: {relativo}")
    try:
        linhas = alvo.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise ContextoServerError(f"não li {relativo}: {exc}") from exc
    de = max(1, int(inicio or 1))
    ate = min(len(linhas), int(fim or de + MAX_LINHAS_ARQUIVO - 1))
    if ate < de:
        raise ContextoServerError(f"intervalo invertido: {de}-{ate}")
    trecho = linhas[de - 1:ate]
    return {
        "path": relativo,
        "start": de,
        "end": ate,
        "total_lines": len(linhas),
        "truncated": ate < len(linhas) or de > 1,
        "text": "\n".join(f"{n:>5}| {linha}" for n, linha in enumerate(trecho, de)),
    }


def _memoria(raiz: Path):
    pasta = cm.pasta_memoria(raiz)
    regras, decisoes = [], []
    if (pasta / cm.NOME_REGRAS).is_file():
        regras = cm.carregar_regras(pasta / cm.NOME_REGRAS)
    if (pasta / cm.NOME_DECISOES).is_file():
        decisoes = cm.carregar_decisoes(pasta / cm.NOME_DECISOES)
    return pasta, regras, decisoes


def context_build(argumentos: dict) -> dict:
    tarefa = str(argumentos.get("task") or "").strip()
    if not tarefa:
        raise ContextoServerError("'task' é obrigatório")
    raiz = _raiz(argumentos.get("root"))
    arquivos = [str(a) for a in (argumentos.get("files") or [])]
    globs = [str(g) for g in (argumentos.get("globs") or [])]
    if not arquivos and not globs and not argumentos.get("stdin"):
        raise ContextoServerError("informe 'files', 'globs' ou 'stdin'")

    # Caminhos são relativos à raiz do projeto, não ao cwd do servidor.
    absolutos = [a if Path(a).is_absolute() else str(raiz / a) for a in arquivos]
    padroes = [g if Path(g).is_absolute() else str(raiz / g) for g in globs]
    caminhos = cl.expandir(absolutos, padroes)

    modelo = str(argumentos.get("model") or MODELO)
    perfil = str(argumentos.get("profile") or "leitura").lower()
    if perfil not in PERFIS:
        raise ContextoServerError(
            f"profile inválido: {perfil} (use {', '.join(PERFIS)})")
    padrao = PERFIS[perfil]
    orcamento = {
        "profile": perfil,
        "max_lines": int(argumentos.get("max_lines") or cl.MAX_LINHAS),
        "max_per_file": int(argumentos.get("max_per_file") or cl.MAX_POR_ARQUIVO),
        "max_total": int(argumentos.get("max_total") or padrao["max_total"]),
        "num_ctx": int(argumentos.get("num_ctx") or 32768),
        "num_predict": int(argumentos.get("num_predict") or padrao["num_predict"]),
        "no_numbers": bool(argumentos.get("no_numbers")),
    }
    pasta_mem = cm.pasta_memoria(raiz)
    arquivos_memoria = [p for p in (pasta_mem / cm.NOME_REGRAS, pasta_mem / cm.NOME_DECISOES)
                        if p.is_file()]
    chave = cc.chave(tarefa, modelo, caminhos, orcamento, arquivos_memoria)
    seco = not argumentos.get("dry_run")

    if seco:
        cacheado = cc.obter(chave)
        if cacheado is not None:
            cacheado["cached"] = True
            _metricas_registrar({
                "quando": datetime.now().isoformat(timespec="seconds"),
                "root": str(raiz), "task": tarefa,
                "model": cacheado.get("context_metrics", {}).get("model", modelo),
                "original_tokens": 0, "prompt_tokens": 0, "compressed_tokens": 0,
                "reduction_percentage": 0, "pending": cacheado.get("validation", {}).get("pending", 0),
                "cached": True, "seconds": 0,
            })
            return cacheado

    try:
        trechos = cl.montar_trechos(
            caminhos,
            argumentos.get("stdin"),
            orcamento["max_lines"],
            orcamento["max_per_file"],
            orcamento["max_total"],
        )
    except cl.ContextoError as exc:
        raise ContextoServerError(str(exc)) from exc

    for trecho in trechos:  # relativo à raiz fica legível no pacote
        nome = str(trecho["nome"])
        if nome != "stdin":
            try:
                trecho["nome"] = str(Path(nome).resolve().relative_to(raiz))
            except (ValueError, OSError):
                pass
    prompt = cl.montar_prompt(tarefa, trechos, numerar=not orcamento["no_numbers"])

    resumo = None
    if seco:
        try:
            resumo = cl.resumir(
                HOST, modelo, prompt,
                int(argumentos.get("timeout") or 900),
                orcamento["num_ctx"], orcamento["num_predict"],
            )
        except cl.ContextoError as exc:
            raise ContextoServerError(str(exc)) from exc

    alvo = " ".join([tarefa] + [str(t["nome"]) for t in trechos if t.get("incluido")])
    _, regras_todas, decisoes_todas = _memoria(raiz)
    selecionadas, omitidas = cm.limitar_regras(
        cm.selecionar_regras(regras_todas, alvo, [str(t["nome"]) for t in trechos]),
        int(argumentos.get("rule_budget") or cm.LIMITE_REGRAS_TOKENS),
    )
    decisoes = cm.relevantes(decisoes_todas, alvo, int(argumentos.get("limit_decisions") or 5))
    nota = ""
    if omitidas:
        nota = (f"{len(omitidas)} regra(s) fora do pacote por orçamento; "
                "use context_get_rules para vê-las por inteiro.")

    texto_fonte = "\n".join(t["texto"] for t in trechos if t.get("incluido"))
    pacote = cp.validar(
        cp.montar(tarefa, trechos, resumo, modelo, raiz=raiz,
                  regras=selecionadas, decisoes=decisoes, memory_note=nota),
        raiz=raiz,
        texto_fonte=texto_fonte,
    )
    if seco:
        cc.guardar(chave, pacote)
        _metricas_registrar({
            "quando": datetime.now().isoformat(timespec="seconds"),
            "root": str(raiz),
            "task": tarefa,
            "model": pacote["context_metrics"]["model"],
            "original_tokens": pacote["context_metrics"]["original_tokens"],
            "prompt_tokens": pacote["context_metrics"]["prompt_tokens"],
            "compressed_tokens": pacote["context_metrics"]["compressed_tokens"],
            "reduction_percentage": pacote["context_metrics"]["reduction_percentage"],
            "pending": pacote["validation"]["pending"],
            "cached": False,
            "seconds": pacote["context_metrics"]["seconds"],
        })
    else:
        pacote["dry_run"] = True
        pacote["prompt"] = prompt
    return pacote


def context_get_file(argumentos: dict) -> dict:
    raiz = _raiz(argumentos.get("root"))
    caminho = str(argumentos.get("path") or "").strip()
    if not caminho:
        raise ContextoServerError("'path' é obrigatório")
    return _ler_arquivo(raiz, caminho, argumentos.get("start"), argumentos.get("end"))


def context_get_rules(argumentos: dict) -> dict:
    raiz = _raiz(argumentos.get("root"))
    pasta, regras, _ = _memoria(raiz)
    prioridade = str(argumentos.get("priority") or "").upper()
    if prioridade:
        regras = [r for r in regras if r["priority"] == prioridade]
    return {"memory": str(pasta), "count": len(regras), "rules": regras}


def context_get_decisions(argumentos: dict) -> dict:
    raiz = _raiz(argumentos.get("root"))
    pasta, _, decisoes = _memoria(raiz)
    consulta = str(argumentos.get("query") or "").strip()
    limite = int(argumentos.get("limit") or cm.LIMITE_DECISOES)
    selecionadas = cm.relevantes(decisoes, consulta, limite) if consulta else decisoes[:limite]
    return {"memory": str(pasta), "count": len(selecionadas), "decisions": selecionadas}


def context_validate(argumentos: dict) -> dict:
    raiz = _raiz(argumentos.get("root"))
    pacote = argumentos.get("package")
    if isinstance(argumentos.get("path"), str):
        caminho = Path(argumentos["path"]).expanduser()
        if not caminho.is_file():
            raise ContextoServerError(f"pacote não encontrado: {caminho}")
        try:
            pacote = json.loads(caminho.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ContextoServerError(f"pacote inválido: {exc}") from exc
    if not isinstance(pacote, dict):
        raise ContextoServerError("envie 'package' (objeto) ou 'path'")
    return cp.validar(pacote, raiz=raiz, texto_fonte=str(argumentos.get("source_text") or ""))


def context_metrics(argumentos: dict) -> dict:
    caminho = _estado() / "metrics.jsonl"
    limite = max(1, int(argumentos.get("limit") or 50))
    if not caminho.is_file():
        return {"runs": 0, "file": str(caminho), "recent": [],
                "note": "nenhuma execução registrada ainda"}
    registros = []
    for linha in caminho.read_text(encoding="utf-8").splitlines()[-limite:]:
        try:
            registros.append(json.loads(linha))
        except json.JSONDecodeError:
            continue
    reducoes = [r["reduction_percentage"] for r in registros if r.get("reduction_percentage")]
    return {
        "file": str(caminho),
        "runs": len(registros),
        "avg_reduction_percentage": round(sum(reducoes) / len(reducoes), 1) if reducoes else 0.0,
        "total_prompt_tokens": sum(r.get("prompt_tokens") or 0 for r in registros),
        "total_compressed_tokens": sum(r.get("compressed_tokens") or 0 for r in registros),
        "pending": sum(r.get("pending") or 0 for r in registros),
        "cache_hits": sum(1 for r in registros if r.get("cached")),
        "seconds_total": round(sum(r.get("seconds") or 0 for r in registros), 1),
        "cache": cc.estatisticas(),
        "recent": registros[-5:],
    }


def context_search(argumentos: dict) -> dict:
    consulta = str(argumentos.get("query") or "").strip()
    if not consulta:
        raise ContextoServerError("'query' é obrigatório")
    try:
        import kb  # noqa: PLC0415 - opcional: só existe com o mcp/kb no caminho
    except ImportError as exc:
        raise ContextoServerError(f"mcp/kb indisponível: {exc}") from exc
    app = str(argumentos.get("app") or Path.cwd().name)
    try:
        achados = kb.search(app, consulta, int(argumentos.get("k") or 5))
    except Exception as exc:  # noqa: BLE001 - índice ausente não é erro fatal
        raise ContextoServerError(
            f"busca falhou para o app '{app}' ({exc}); rode `orq-kb index {app}`"
        ) from exc
    return {"app": app, "count": len(achados), "results": achados}


FERRAMENTAS = [
    {
        "name": "context_build",
        "description": "Monta o pacote de contexto (§6) para uma tarefa: lê arquivos com "
                       "orçamento, resume no modelo local, valida referências e anexa as "
                       "regras/decisões do projeto. dry_run=true não chama o modelo.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "o que precisa ser respondido"},
                "files": {"type": "array", "items": {"type": "string"}},
                "globs": {"type": "array", "items": {"type": "string"}},
                "root": {"type": "string", "description": "raiz do repositório (padrão: cwd)"},
                "model": {"type": "string"},
                "profile": {"type": "string", "enum": ["rapida", "leitura", "completa"],
                            "description": "orçamento de contexto: rapida=6 KB, leitura=16 KB "
                                           "(padrão), completa=48 KB"},
                "max_total": {"type": "integer"},
                "num_predict": {"type": "integer"},
                "dry_run": {"type": "boolean"},
            },
            "required": ["task"],
        },
    },
    {
        "name": "context_get_file",
        "description": "Trecho de arquivo com números de linha. Recusa .env e caminho fora da raiz.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start": {"type": "integer"},
                "end": {"type": "integer"},
                "root": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "context_get_rules",
        "description": "Regras de negócio do projeto (memória), opcionalmente por prioridade.",
        "inputSchema": {
            "type": "object",
            "properties": {"root": {"type": "string"}, "priority": {"type": "string"}},
        },
    },
    {
        "name": "context_get_decisions",
        "description": "Decisões técnicas do projeto, filtradas por relevância.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "root": {"type": "string"},
            },
        },
    },
    {
        "name": "context_validate",
        "description": "Revalida um pacote: confere arquivos, referências e decisões.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "package": {"type": "object"},
                "path": {"type": "string"},
                "source_text": {"type": "string"},
                "root": {"type": "string"},
            },
        },
    },
    {
        "name": "context_metrics",
        "description": "Agregados das execuções: redução média, tokens e pendências.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
    {
        "name": "context_search",
        "description": "Busca textual na base local do kb (precisa do app indexado).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "app": {"type": "string"},
                "k": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
]

DESPACHO = {
    "context_build": context_build,
    "context_get_file": context_get_file,
    "context_get_rules": context_get_rules,
    "context_get_decisions": context_get_decisions,
    "context_validate": context_validate,
    "context_metrics": context_metrics,
    "context_search": context_search,
}


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
        reply(msg_id, {"tools": FERRAMENTAS})
    elif method == "tools/call":
        params = msg.get("params") or {}
        nome = params.get("name")
        funcao = DESPACHO.get(nome)
        if funcao is None:
            return reply(msg_id, error={"code": -32602, "message": f"tool desconhecida: {nome}"})
        try:
            r = funcao(params.get("arguments") or {})
        except ContextoServerError as exc:
            return reply(msg_id, {"content": [{"type": "text", "text": f"erro: {exc}"}],
                                  "isError": True})
        except Exception as exc:  # noqa: BLE001 - nunca derrubar o servidor
            return reply(msg_id, {"content": [{"type": "text", "text": f"erro interno: {exc!r}"}],
                                  "isError": True})
        reply(msg_id, {"content": [{"type": "text", "text": json.dumps(r, ensure_ascii=False)}],
                       "structuredContent": r})
    elif method == "ping":
        reply(msg_id, {})
    else:
        reply(msg_id, error={"code": -32601, "message": f"método desconhecido: {method}"})


def use_utf8_stdio():
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def main():
    use_utf8_stdio()
    for linha in sys.stdin:
        linha = linha.strip()
        if not linha:
            continue
        try:
            handle(json.loads(linha))
        except json.JSONDecodeError:
            reply(None, error={"code": -32700, "message": "JSON inválido"})


if __name__ == "__main__":
    main()
