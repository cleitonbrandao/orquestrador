"""Cache de pacote de contexto por conteúdo (Fase 7).

Uma chamada de `context_build` custa 20–60 s de CPU. Se a mesma tarefa pede os
mesmos arquivos, no mesmo estado, o pacote anterior serve.

A chave é o conteúdo do que entrou: tarefa, modelo, orçamento, **caminho + tamanho
+ mtime** de cada arquivo e o estado dos arquivos de memória. Arquivo alterado ou
regra editada invalidam sozinhos — não há TTL para correção, só para limpeza.
"""
import hashlib
import json
import os
import time
from pathlib import Path

MAX_IDADE_DIAS = 7
MAX_ENTRADAS = 200


def pasta() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "orquestrador" / "contexto" / "cache"


def _assinatura(caminho: Path) -> dict:
    try:
        st = caminho.stat()
        return {"path": str(caminho), "size": st.st_size, "mtime": st.st_mtime_ns}
    except OSError:
        return {"path": str(caminho), "size": -1, "mtime": -1}


def chave(tarefa: str, modelo: str, arquivos, orcamento=None, memoria=()) -> str:
    """Hash estável do conteúdo que entra no pacote."""
    material = {
        "task": (tarefa or "").strip(),
        "model": modelo or "",
        "budget": orcamento or {},
        "files": [_assinatura(Path(str(a))) for a in arquivos],
        "memory": [_assinatura(Path(str(m))) for m in memoria],
    }
    bruto = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:32]


def _caminho(nome: str) -> Path:
    return pasta() / f"{nome}.json"


def obter(nome: str, max_idade_dias: int = MAX_IDADE_DIAS) -> dict | None:
    caminho = _caminho(nome)
    try:
        if (time.time() - caminho.stat().st_mtime) > max_idade_dias * 86400:
            return None
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dados if isinstance(dados, dict) else None


def guardar(nome: str, pacote: dict) -> None:
    caminho = _caminho(nome)
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(pacote, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        return  # cache não pode derrubar a ferramenta
    _podar()


def _podar(maximo: int = MAX_ENTRADAS) -> None:
    """Remove o que passou da idade e o excedente mais antigo."""
    raiz = pasta()
    try:
        itens = sorted(raiz.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    limite = time.time() - MAX_IDADE_DIAS * 86400
    for i, caminho in enumerate(itens):
        try:
            if i >= maximo or caminho.stat().st_mtime < limite:
                caminho.unlink()
        except OSError:
            continue


def limpar() -> int:
    """Apaga todo o cache; devolve quantos arquivos saíram."""
    total = 0
    try:
        for caminho in pasta().glob("*.json"):
            try:
                caminho.unlink()
                total += 1
            except OSError:
                continue
    except OSError:
        return 0
    return total


def estatisticas() -> dict:
    raiz = pasta()
    arquivos = list(raiz.glob("*.json")) if raiz.is_dir() else []
    bytes_ = sum(p.stat().st_size for p in arquivos if p.exists())
    return {"pasta": str(raiz), "entradas": len(arquivos), "bytes": bytes_}
