"""Memória do projeto para o Context Manager (roadmap §7).

Regras de negócio e decisões ficam **fora** do histórico de conversa e **fora** do
modelo: entram no pacote verbatim. O modelo local nunca reescreve uma regra —
no máximo sugere, e a sugestão fica em `missing_information`.

Formato aceito (tolerante, porque é escrito à mão):

`business_rules.json`
```json
{"project": "app", "rules": [
  {"id": "team-id", "priority": "P0", "text": "Toda consulta respeita team_id"}
]}
```
Também aceita uma lista simples de strings no lugar do objeto.

`decisions.json`
```json
{"decisions": [
  {"id": "D1", "date": "2026-10-30", "description": "...", "rationale": "...",
   "files": ["app/Models/Sale.php"], "status": "aceita", "references": []}
]}
```
"""
import json
import os
import re
import unicodedata
from pathlib import Path

NOME_REGRAS = "business_rules.json"
NOME_DECISOES = "decisions.json"
LIMITE_DECISOES = 5

# Termos curtos que casariam com tudo e destruiriam o filtro de relevância.
_PARADAS = {
    "como", "para", "qual", "quais", "onde", "quando", "porque", "sobre", "entre",
    "esse", "essa", "isso", "este", "esta", "aqui", "mais", "menos", "todo", "toda",
    "fazer", "deve", "pode", "tem", "com", "dos", "das", "por",
}


class MemoriaError(Exception):
    """Memória ausente, ilegível ou com formato inválido."""


def slug(texto: str, limite: int = 40) -> str:
    """Nome de pasta seguro a partir do caminho do projeto."""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    limpo = re.sub(r"[^a-zA-Z0-9._-]+", "-", sem_acento).strip("-").lower()
    return (limpo or "projeto")[:limite].strip("-") or "projeto"


def pasta_memoria(projeto) -> Path:
    """`$XDG_STATE_HOME/orquestrador/memoria/<slug do projeto>`."""
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    nome = Path(str(projeto)).name or str(projeto)
    return base / "orquestrador" / "memoria" / slug(nome)


def _ler(caminho) -> object:
    caminho = Path(caminho).expanduser()
    if not caminho.is_file():
        raise MemoriaError(f"memória não encontrada: {caminho}")
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MemoriaError(f"não li {caminho}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise MemoriaError(f"{caminho}: JSON inválido ({exc})") from exc


def carregar_regras(caminho) -> list[dict]:
    """Regras normalizadas: id, priority, text. Preserva a ordem do arquivo."""
    dados = _ler(caminho)
    itens = dados.get("rules") if isinstance(dados, dict) else dados
    if not isinstance(itens, list):
        raise MemoriaError(f"{caminho}: esperado uma lista em 'rules'")
    regras = []
    for posicao, item in enumerate(itens, 1):
        if isinstance(item, str) and item.strip():
            regras.append({"id": f"R{posicao}", "priority": "P0", "text": item.strip()})
        elif isinstance(item, dict) and str(item.get("text") or "").strip():
            regras.append({
                "id": str(item.get("id") or f"R{posicao}"),
                "priority": str(item.get("priority") or "P0").upper(),
                "text": str(item["text"]).strip(),
            })
        else:
            raise MemoriaError(f"{caminho}: regra {posicao} precisa de 'text'")
    return regras


def carregar_decisoes(caminho) -> list[dict]:
    """Decisões normalizadas; campos ausentes viram vazio, nunca invenção."""
    dados = _ler(caminho)
    itens = dados.get("decisions") if isinstance(dados, dict) else dados
    if not isinstance(itens, list):
        raise MemoriaError(f"{caminho}: esperado uma lista em 'decisions'")
    decisoes = []
    for posicao, item in enumerate(itens, 1):
        if not isinstance(item, dict):
            raise MemoriaError(f"{caminho}: decisão {posicao} precisa ser um objeto")
        descricao = str(item.get("description") or "").strip()
        if not descricao:
            raise MemoriaError(f"{caminho}: decisão {posicao} precisa de 'description'")
        arquivos = item.get("files") or []
        referencias = item.get("references") or []
        if not isinstance(arquivos, list) or not isinstance(referencias, list):
            raise MemoriaError(f"{caminho}: 'files'/'references' da decisão {posicao} devem ser listas")
        decisoes.append({
            "id": str(item.get("id") or f"D{posicao}"),
            "date": str(item.get("date") or ""),
            "description": descricao,
            "rationale": str(item.get("rationale") or "").strip(),
            "files": [str(a) for a in arquivos],
            "status": str(item.get("status") or ""),
            "references": [str(r) for r in referencias],
        })
    return decisoes


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.lower()


def relevantes(decisoes: list[dict], alvo: str, limite: int = LIMITE_DECISOES) -> list[dict]:
    """Filtra decisões por termos do alvo (pergunta + arquivos).

    Sem nenhuma decisão casando, devolve as mais recentes — memória vazia é pior
    que memória genérica, mas nunca maior que `limite`.
    """
    limite = max(1, int(limite))
    termos = {
        t for t in re.findall(r"[a-z0-9./_-]{4,}", _normalizar(alvo or ""))
        if t not in _PARADAS
    }
    casadas = []
    for decisao in decisoes:
        corpo = _normalizar(" ".join(
            [decisao["description"], decisao["rationale"], " ".join(decisao["files"])]
        ))
        if any(termo in corpo for termo in termos):
            casadas.append(decisao)
    if casadas:
        return casadas[:limite]
    return sorted(decisoes, key=lambda d: d.get("date") or "", reverse=True)[:limite]


def criar(pasta) -> list[Path]:
    """Cria os dois arquivos de memória (não sobrescreve o que existe)."""
    pasta = Path(pasta).expanduser()
    pasta.mkdir(parents=True, exist_ok=True)
    modelos = {
        NOME_REGRAS: {
            "project": pasta.parent.name,
            "rules": [
                {"id": "exemplo", "priority": "P0",
                 "text": "Substitua por uma regra real do projeto (o que nunca pode quebrar)."}
            ],
        },
        NOME_DECISOES: {
            "decisions": [
                {"id": "D1", "date": "", "description": "Substitua por uma decisão real.",
                 "rationale": "", "files": [], "status": "aceita", "references": []}
            ]
        },
    }
    criados = []
    for nome, conteudo in modelos.items():
        destino = pasta / nome
        if destino.exists():
            continue
        destino.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        criados.append(destino)
    return criados
