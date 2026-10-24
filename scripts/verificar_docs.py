#!/usr/bin/env python3
"""Verificador de documentação do /orquestrar: confere um Markdown por regra, sem LLM.

Só acusa o que a mudança INTRODUZIU: problemas que já existiam no original não contam.

Regras:
- link relativo ([texto](caminho)) aponta para arquivo ou pasta que existe;
- caminho citado em `código` (com "/" e sem variável) existe no repositório;
- script chamado em bloco de código (./x, python x.py, bash x.sh, -File x.ps1) existe;
- `npm run X` e `composer X` citam um script que existe no package.json / composer.json;
- nenhuma seção vazia nem marcador (TODO, TBD, FIXME, lorem ipsum, <preencher>).

Uso:
    verificar_docs.py ALVO [--proposta P] [--original O] [--raiz R]

ALVO é o caminho do arquivo no repositório (pode ainda não existir). Sem --proposta, confere
o próprio ALVO contra a versão do HEAD do git. Com --proposta, confere P como se estivesse em
ALVO, contra o ALVO atual. Sai com 0 = passou, 1 = falhou, 2 = erro de uso.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# maiúsculas de propósito: "todo" em português é palavra comum
PLACEHOLDER = re.compile(r"\b(?:TODO|TBD|FIXME)\b|(?i:lorem ipsum|<preencher[^>]*>|\[inserir[^\]]*\])")
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|!\[[^\]]*\]\(([^)\s]+)\)")
CODIGO_INLINE = re.compile(r"`([^`\n]+)`")
TITULO = re.compile(r"^(#{1,6})\s+\S")
CERCA = re.compile(r"^\s*(```|~~~)")
SCRIPT_CMD = re.compile(
    r"(?:^|[\s;&|(])(?:"
    r"(?:\./|\.\\)(?P<rel>[\w./\\-]+)"
    r"|(?:python3?|py|bash|sh|node|php)\s+(?P<arg>[\w./\\-]+\.(?:py|sh|js|mjs|php))"
    r"|-File\s+(?P<ps>[\w./\\-]+\.ps1)"
    r")"
)
NPM_RUN = re.compile(r"\b(?:npm|pnpm|yarn)\s+run\s+([\w:.-]+)")
COMPOSER = re.compile(r"\bcomposer\s+(?:run(?:-script)?\s+)?([\w:.-]+)")
COMPOSER_NATIVOS = {
    "install", "update", "require", "remove", "dump-autoload", "dumpautoload", "create-project",
    "init", "validate", "show", "outdated", "self-update", "selfupdate", "global", "config",
    "diagnose", "audit", "why", "why-not", "depends", "prohibits", "clear-cache", "exec",
    "run", "run-script", "list", "help", "status", "search", "fund", "licenses", "bump", "check-platform-reqs",
}


def raiz_git(inicio: Path) -> Path:
    try:
        saida = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=inicio, capture_output=True, text=True, check=True
        ).stdout.strip()
        return Path(saida)
    except (OSError, subprocess.CalledProcessError):
        return inicio


def conteudo_head(raiz: Path, alvo: Path) -> str:
    try:
        rel = alvo.resolve().relative_to(raiz.resolve()).as_posix()
    except ValueError:
        return ""
    r = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=raiz, capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""


def ler(caminho: Path) -> str:
    return caminho.read_text(encoding="utf-8", errors="replace") if caminho.is_file() else ""


def scripts_json(raiz: Path, nome: str) -> set[str] | None:
    arquivo = raiz / nome
    if not arquivo.is_file():
        return None
    try:
        return set((json.loads(arquivo.read_text(encoding="utf-8")).get("scripts") or {}).keys())
    except (ValueError, AttributeError):
        return None


def existe(caminho: str, base_doc: Path, raiz: Path) -> bool:
    caminho = caminho.replace("\\", "/").rstrip("/")
    if not caminho:
        return True
    if caminho.startswith("/"):
        return (raiz / caminho.lstrip("/")).exists()
    return (base_doc / caminho).exists() or (raiz / caminho).exists()


def parece_caminho(texto: str) -> bool:
    if any(c in texto for c in " $%<>*{}~=:@?,\"'") or texto.startswith(("-", "/")):
        return False
    if "/" not in texto.replace("\\", "/"):
        return False
    if texto.endswith("/"):
        return True
    # extensão de arquivo de verdade (".md", ".php"); "v4.1-flash-free" é id de modelo
    return re.search(r"\.[A-Za-z][A-Za-z0-9]{0,5}$", texto.replace("\\", "/").split("/")[-1]) is not None


def problemas(texto: str, base_doc: Path, raiz: Path) -> list[tuple[int, str]]:
    """Lista (linha, motivo). O motivo não leva o número da linha, para comparar versões."""
    achados: list[tuple[int, str]] = []
    npm = scripts_json(raiz, "package.json")
    composer = scripts_json(raiz, "composer.json")
    em_bloco = False
    ultimo_titulo: tuple[int, int, str] | None = None  # (linha, nível, título) sem conteúdo depois

    for n, linha in enumerate(texto.splitlines(), start=1):
        if CERCA.match(linha):
            em_bloco = not em_bloco
            if ultimo_titulo:
                ultimo_titulo = None
            continue

        if em_bloco:
            for m in SCRIPT_CMD.finditer(linha):
                alvo = m.group("rel") or m.group("arg") or m.group("ps")
                if alvo and not existe(alvo, base_doc, raiz):
                    achados.append((n, f"script citado não existe: {alvo}"))
            for m in NPM_RUN.finditer(linha):
                if npm is not None and m.group(1) not in npm:
                    achados.append((n, f"script npm não existe no package.json: {m.group(1)}"))
            for m in COMPOSER.finditer(linha):
                nome = m.group(1)
                if composer is not None and nome not in COMPOSER_NATIVOS and nome not in composer:
                    achados.append((n, f"script composer não existe no composer.json: {nome}"))
            continue

        t = TITULO.match(linha)
        if t:
            nivel = len(t.group(1))
            if ultimo_titulo and nivel <= ultimo_titulo[1]:
                achados.append((ultimo_titulo[0], f"seção vazia: {ultimo_titulo[2]}"))
            ultimo_titulo = (n, nivel, linha.strip())
            continue
        if linha.strip() and ultimo_titulo:
            ultimo_titulo = None

        marcador = PLACEHOLDER.search(CODIGO_INLINE.sub("", linha))  # `TODO` citado como nome não conta
        if marcador:
            achados.append((n, f"marcador de pendência: {marcador.group(0)}"))

        for m in LINK.finditer(linha):
            destino = (m.group(1) or m.group(2) or "").split("#", 1)[0]
            if not destino or re.match(r"^[a-z][a-z0-9+.-]*:", destino, re.I):
                continue  # âncora local, http:, mailto: etc.
            if not existe(destino, base_doc, raiz):
                achados.append((n, f"link para caminho inexistente: {destino}"))

        sem_links = LINK.sub("", linha)
        for m in CODIGO_INLINE.finditer(sem_links):
            trecho = m.group(1).strip()
            if parece_caminho(trecho) and not existe(trecho, base_doc, raiz):
                achados.append((n, f"caminho citado não existe: {trecho}"))

    if ultimo_titulo:
        achados.append((ultimo_titulo[0], f"seção vazia: {ultimo_titulo[2]}"))
    return achados


def novos(proposta: list[tuple[int, str]], original: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Problemas da proposta que não existiam no original (contando repetições)."""
    restantes: dict[str, int] = {}
    for _, motivo in original:
        restantes[motivo] = restantes.get(motivo, 0) + 1
    saida = []
    for linha, motivo in proposta:
        if restantes.get(motivo, 0) > 0:
            restantes[motivo] -= 1
        else:
            saida.append((linha, motivo))
    return saida


def verificar(alvo: Path, proposta: str, original: str, raiz: Path) -> list[tuple[int, str]]:
    base = alvo.parent
    return novos(problemas(proposta, base, raiz), problemas(original, base, raiz))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Confere um Markdown por regra (links, caminhos, scripts, seções).")
    ap.add_argument("alvo", help="caminho do arquivo no repositório")
    ap.add_argument("--proposta", help="arquivo com o texto proposto (padrão: o próprio alvo)")
    ap.add_argument("--original", help="arquivo com a versão anterior (padrão: HEAD do git ou o alvo atual)")
    ap.add_argument("--raiz", help="raiz do repositório (padrão: git rev-parse --show-toplevel)")
    args = ap.parse_args(argv)

    alvo = Path(args.alvo).resolve()
    raiz = Path(args.raiz).resolve() if args.raiz else raiz_git(alvo.parent if alvo.parent.exists() else Path.cwd())

    if args.proposta:
        proposta_path = Path(args.proposta)
        if not proposta_path.is_file():
            print(f"proposta não encontrada: {proposta_path}", file=sys.stderr)
            return 2
        proposta = ler(proposta_path)
        original = ler(Path(args.original)) if args.original else ler(alvo)
    else:
        if not alvo.is_file():
            print(f"arquivo não encontrado: {alvo}", file=sys.stderr)
            return 2
        proposta = ler(alvo)
        original = ler(Path(args.original)) if args.original else conteudo_head(raiz, alvo)

    achados = verificar(alvo, proposta, original, raiz)
    try:
        exibido = alvo.relative_to(raiz).as_posix()
    except ValueError:
        exibido = str(alvo)
    print(f"ARQUIVO: {exibido}")
    print(f"RESULTADO: {'falhou' if achados else 'passou'}")
    if achados:
        print("MOTIVOS:")
        for linha, motivo in achados:
            print(f"- linha {linha}: {motivo}")
    return 1 if achados else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
