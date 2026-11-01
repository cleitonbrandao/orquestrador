"""Busca textual determinística no repositório (fallback do `kb`).

O `context_search` depende do índice do `kb`; quando o app não está indexado, não
há o que consultar. Este módulo faz a busca sem índice: varre a árvore com limites
explícitos e devolve `arquivo:linha` com a linha — nada de modelo, nada de rede.

Segurança (§11): fica dentro da raiz, pula `.env`, diretórios de build/vendor e
arquivos binários.
"""
import re
from pathlib import Path

DIRETORIOS_IGNORADOS = {
    ".git", ".hg", ".svn", "node_modules", "vendor", ".venv", "venv", "__pycache__",
    "dist", "build", ".next", ".nuxt", ".cache", ".trail", "graft", "coverage", "storage",
}
MAX_ARQUIVOS = 4000
MAX_BYTES_ARQUIVO = 1_500_000
_BINARIO = re.compile(rb"[\x00]")


class BuscaError(Exception):
    """Consulta vazia ou raiz inválida."""


def termos(consulta: str) -> list[str]:
    """Palavras de 3+ caracteres, sem repetição, em minúsculas."""
    vistos, saida = set(), []
    for bruto in re.findall(r"[0-9A-Za-z_.\-/]{3,}", consulta or ""):
        baixo = bruto.lower()
        if baixo not in vistos:
            vistos.add(baixo)
            saida.append(baixo)
    return saida


def _e_binario(caminho: Path) -> bool:
    try:
        with caminho.open("rb") as f:
            return bool(_BINARIO.search(f.read(8192)))
    except OSError:
        return True


def _arquivos(raiz: Path, limite: int):
    total = 0
    for caminho in raiz.rglob("*"):
        if total >= limite:
            return
        if not caminho.is_file():
            continue
        if any(parte in DIRETORIOS_IGNORADOS for parte in caminho.parts):
            continue
        if caminho.name.startswith(".env") or caminho.suffix in {".png", ".jpg", ".jpeg",
                                                               ".gif", ".pdf", ".zip", ".gz"}:
            continue
        try:
            if caminho.stat().st_size > MAX_BYTES_ARQUIVO:
                continue
        except OSError:
            continue
        total += 1
        yield caminho


def buscar(raiz, consulta: str, k: int = 5, max_arquivos: int = MAX_ARQUIVOS) -> list[dict]:
    """Linhas que casam com os termos, ordenadas por termos distintos e caminho."""
    raiz = Path(str(raiz or ".")).expanduser().resolve()
    if not raiz.is_dir():
        raise BuscaError(f"raiz inexistente: {raiz}")
    alvos = termos(consulta)
    if not alvos:
        raise BuscaError("consulta sem termos úteis (3+ caracteres)")

    achados = []
    for caminho in _arquivos(raiz, max_arquivos):
        if _e_binario(caminho):
            continue
        try:
            linhas = caminho.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for numero, linha in enumerate(linhas, 1):
            baixa = linha.lower()
            casados = sum(1 for t in alvos if t in baixa)
            if not casados:
                continue
            try:
                relativo = str(caminho.relative_to(raiz))
            except ValueError:
                relativo = str(caminho)
            achados.append({
                "path": relativo,
                "line": numero,
                "score": casados,
                "text": linha.strip()[:240],
            })
    achados.sort(key=lambda a: (-a["score"], a["path"], a["line"]))
    return achados[:max(int(k), 1)]
