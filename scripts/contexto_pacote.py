"""Pacote de contexto (roadmap §6) e validação determinística (§4.4).

Nada aqui chama modelo: o pacote é montado a partir das fontes realmente lidas e
o validador só confere o que dá para conferir — arquivo existe, caminho está
dentro do repositório, citação do resumo aponta para algo real.

O modelo local contribui com o texto do resumo e, se devolver, um bloco
```json``` com regras/dependências. O que ele afirmar sem confirmação fica em
`missing_information`, nunca vira fato.

Segurança (§11): caminho fora da raiz e arquivo `.env` são reprovados.
"""
import json
import re
from pathlib import Path

# Chaves que o consumidor (orquestrador) espera encontrar no pacote (§6).
CHAVES = (
    "task",
    "project",
    "critical_rules",
    "relevant_files",
    "dependencies",
    "known_constraints",
    "decisions",
    "missing_information",
    "assumptions",
    "source_references",
    "context_metrics",
)

CHAVES_DO_MODELO = (
    "critical_rules",
    "dependencies",
    "known_constraints",
    "decisions",
    "assumptions",
    "missing_information",
)

_SENSIVEL = re.compile(r"(^|/)\.env($|\.)")
_CITACAO = re.compile(r"([\w./\-]+\.(?:php|jsx|js|ts|py|md|sql|sh|json))(?::(\d+))?")
_BLOCO_JSON = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


def estimar_tokens(texto: str) -> int:
    """Mesma aproximação do contexto_local: len/4."""
    return max(1, len(texto) // 4)


def _resolver(nome: str, raiz: Path) -> Path:
    caminho = Path(nome)
    return caminho if caminho.is_absolute() else raiz / caminho


def caminho_permitido(caminho: Path, raiz: Path) -> bool:
    """Dentro da raiz e sem arquivo sensível? (symlink é resolvido antes)."""
    try:
        rel = caminho.resolve().relative_to(Path(raiz).resolve())
    except (ValueError, OSError):
        return False
    return not _SENSIVEL.search(rel.as_posix())


def citacoes(texto: str) -> list[dict]:
    """Referências `arquivo:linha` citadas no resumo, na ordem e sem repetir."""
    vistas: dict[str, dict] = {}
    for casou in _CITACAO.finditer(texto or ""):
        nome, linha = casou.group(1), casou.group(2)
        ref = f"{nome}:{linha}" if linha else nome
        if ref not in vistas:
            vistas[ref] = {"ref": ref, "path": nome, "line": int(linha) if linha else None}
    return list(vistas.values())


def extras(texto: str) -> dict:
    """Bloco JSON opcional do modelo. Inválido ou ausente devolve {}."""
    casou = _BLOCO_JSON.search(texto or "")
    if not casou:
        return {}
    try:
        dados = json.loads(casou.group(1))
    except json.JSONDecodeError:
        return {}
    return dados if isinstance(dados, dict) else {}


def montar(pergunta, trechos, resumo=None, modelo="", projeto=None, raiz=".") -> dict:
    """Pacote §6 a partir das fontes lidas. Sem inventar campo."""
    raiz = Path(raiz or ".")
    texto = (resumo or {}).get("texto") or ""
    incluidos = [t for t in trechos if t.get("incluido")]

    arquivos = []
    for t in incluidos:
        nome = str(t["nome"])
        arquivos.append({
            "path": nome,
            "lines": f"{t['de']}-{t['ate']}" if t.get("de") else "",
            "truncated": bool(t.get("truncado")),
            "tokens": estimar_tokens(t["texto"]),
            "reason": "",
        })

    originais = sum(t["bytes"] for t in incluidos)
    original_tokens = int(originais / 4) if originais else 0
    compactados = int((resumo or {}).get("saida") or 0)
    reducao = 0.0
    if original_tokens and compactados:
        reducao = round((1 - compactados / original_tokens) * 100, 1)

    # Toda fonte lida é referência; citação do modelo entra por cima, sem repetir.
    referencias = []
    for t in incluidos:
        nome = str(t["nome"])
        linhas = f"{t['de']}-{t['ate']}" if t.get("de") else ""
        referencias.append({
            "ref": f"{nome}:{linhas}" if linhas else nome,
            "path": nome,
            "line": t.get("de") or None,
        })
    vistos = {r["ref"] for r in referencias}
    for citacao in citacoes(texto):
        if citacao["ref"] not in vistos:
            vistos.add(citacao["ref"])
            referencias.append(citacao)

    pacote = {
        "task": pergunta,
        "project": projeto or {},
        "critical_rules": [],
        "relevant_files": arquivos,
        "dependencies": [],
        "known_constraints": [],
        "decisions": [],
        "missing_information": [],
        "assumptions": [],
        "source_references": referencias,
        "context_metrics": {
            "original_tokens": original_tokens,
            "prompt_tokens": int((resumo or {}).get("entrada") or 0),
            "compressed_tokens": compactados,
            "reduction_percentage": reducao,
            "model": modelo,
            "seconds": round(float((resumo or {}).get("duracao") or 0), 2),
        },
    }

    dados = extras(texto)
    for chave in CHAVES_DO_MODELO:
        valor = dados.get(chave)
        if isinstance(valor, list):
            pacote[chave] = [str(v) for v in valor]
    return pacote


def validar(pacote: dict, raiz=".", texto_fonte: str = "") -> dict:
    """Confere referências sem IA e devolve o pacote com `validation`."""
    raiz = Path(raiz or ".")
    pendencias = list(pacote.get("missing_information") or [])
    confirmados = pendentes = 0
    estado: dict[str, bool] = {}

    for arq in pacote.get("relevant_files") or []:
        nome = arq.get("path") or ""
        if nome == "stdin":
            arq["confirmed"] = True
            confirmados += 1
            estado[nome] = True
            continue
        alvo = _resolver(nome, raiz)
        ok = caminho_permitido(alvo, raiz) and alvo.is_file()
        arq["confirmed"] = ok
        estado[nome] = ok
        if ok:
            confirmados += 1
        else:
            pendentes += 1
            pendencias.append(f"arquivo não confirmado: {nome}")

    for ref in pacote.get("source_references") or []:
        nome = ref.get("path") or ref.get("ref", "").split(":")[0]
        if nome in estado:
            # Mesmo arquivo já conferido: herda o veredito sem contar de novo.
            ref["confirmed"] = estado[nome]
            continue
        if nome == "stdin":
            ref["confirmed"] = True
            estado[nome] = True
            confirmados += 1
            continue
        alvo = _resolver(nome, raiz)
        ok = caminho_permitido(alvo, raiz) and alvo.exists()
        ref["confirmed"] = ok
        estado[nome] = ok
        if ok:
            confirmados += 1
        else:
            pendentes += 1
            pendencias.append(f"referência não confirmada: {ref.get('ref', nome)}")

    for dep in pacote.get("dependencies") or []:
        if texto_fonte and dep not in texto_fonte:
            pendentes += 1
            pendencias.append(f"dependência não encontrada nas fontes: {dep}")
        else:
            confirmados += 1

    pacote["missing_information"] = pendencias
    pacote["validation"] = {
        "checked": confirmados + pendentes,
        "confirmed": confirmados,
        "pending": pendentes,
    }
    return pacote
