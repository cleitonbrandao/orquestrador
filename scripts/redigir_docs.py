#!/usr/bin/env python3
"""Redator de documentação do /orquestrar: o modelo local (Ollama) escreve, a regra confere.

Fluxo: monta o pedido com a tarefa, o texto atual e o contexto -> Ollama -> verificar_docs.py
-> recusado? reenvia com os motivos (até 2 retornos) -> grava a PROPOSTA num arquivo à parte.
Nunca altera o arquivo alvo: quem aplica é o agente principal, depois de revisar o diff.

Uso:
    redigir_docs.py --alvo README.md --tarefa "documentar a opção --link" \\
        [--secao "## Instalação"] [--contexto install.sh install.ps1] [--diff] [--saida P]

Saída: ALVO / PROPOSTA / MODELO / TENTATIVAS / TEMPO / RESULTADO [/ MOTIVOS]
Sai com 0 = passou, 1 = falhou (use o fallback), 3 = indisponível (sem Ollama, sem modelo
ou pedido grande demais para o modelo local).

Variáveis: ORQ_OLLAMA_URL (http://127.0.0.1:11434), ORQ_MODELO_DOCS (qwen3-12k:latest),
ORQ_CTX_DOCS (12288), ORQ_TIMEOUT_DOCS (600 s).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verificar_docs  # noqa: E402

URL = os.environ.get("ORQ_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
MODELO = os.environ.get("ORQ_MODELO_DOCS", "qwen3-12k:latest")
CTX = int(os.environ.get("ORQ_CTX_DOCS", "12288"))
TIMEOUT = int(os.environ.get("ORQ_TIMEOUT_DOCS", "600"))
CHARS_POR_TOKEN = 3.0  # conservador para português e código; errar para menos só corta antes
SAIDA_MAX_TOKENS = 4096
SAIDA_MIN_TOKENS = 1024

SISTEMA = (
    "Você é redator de documentação técnica em Markdown. Regras:\n"
    "- use somente fatos do texto atual, do CONTEXTO e do DIFF; não invente caminho, comando, opção, "
    "número ou versão;\n"
    "- copie sem mudar tudo o que a tarefa não pede para alterar (comandos, nomes de arquivo, links, "
    "separadores ---); só acrescente ou troque o que foi pedido;\n"
    "- mantenha o idioma, o tom e a formatação do documento (títulos, tabelas, blocos de código);\n"
    "- não deixe seção vazia nem marcador como TODO;\n"
    "- responda SOMENTE com o Markdown pedido, sem explicação antes ou depois e sem cercar a resposta "
    "com ```."
)


class Indisponivel(Exception):
    pass


def http(metodo: str, caminho: str, corpo: dict | None = None, timeout: int = 10) -> dict:
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(URL + caminho, data=dados, method=metodo,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def conferir_modelo() -> None:
    try:
        tags = http("GET", "/api/tags")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise Indisponivel(f"Ollama fora do ar em {URL} ({e})")
    nomes = {m.get("name", "") for m in tags.get("models", [])}
    nomes |= {n[: -len(":latest")] for n in nomes if n.endswith(":latest")}
    if MODELO not in nomes:
        raise Indisponivel(f"modelo {MODELO} não está no Ollama (ollama list)")


def conversar(mensagens: list[dict], num_predict: int) -> str:
    corpo = {
        "model": MODELO,
        "messages": mensagens,
        "stream": False,
        "think": False,  # thinking nesta classe de GPU leva minutos por turno
        "options": {"temperature": 0.2, "num_ctx": CTX, "num_predict": num_predict},
    }
    try:
        resposta = http("POST", "/api/chat", corpo, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode("utf-8", "replace")
        if e.code == 400 and "think" in detalhe:
            corpo.pop("think")  # modelo sem suporte a thinking
            resposta = http("POST", "/api/chat", corpo, timeout=TIMEOUT)
        else:
            raise Indisponivel(f"Ollama devolveu {e.code}: {detalhe[:200]}")
    except (urllib.error.URLError, OSError) as e:
        raise Indisponivel(f"falha na chamada ao Ollama ({e})")
    return (resposta.get("message") or {}).get("content", "")


def limpar(texto: str) -> str:
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.S).strip()
    cercado = re.match(r"^```[\w-]*\n(.*)\n```$", texto, flags=re.S)
    if cercado:
        texto = cercado.group(1).strip()
    return texto + "\n"


def localizar_secao(texto: str, titulo: str) -> tuple[int, int] | None:
    """(início, fim) em caracteres da seção que começa no título, até o próximo título de nível igual ou maior.

    Linhas em branco e o separador (---) no fim da seção ficam de fora: o modelo tende a
    apagá-los, e eles pertencem à estrutura do arquivo, não ao conteúdo pedido.
    """
    linhas = texto.splitlines(keepends=True)
    alvo = titulo.strip()
    nivel = len(alvo) - len(alvo.lstrip("#"))
    pos, inicio, fim, em_bloco = 0, None, None, False
    for linha in linhas:
        if verificar_docs.CERCA.match(linha):
            em_bloco = not em_bloco
        elif not em_bloco:
            t = verificar_docs.TITULO.match(linha)
            if inicio is None and linha.strip() == alvo:
                inicio = pos
            elif inicio is not None and t and len(t.group(1)) <= nivel:
                fim = pos
                break
        pos += len(linha)
    if inicio is None:
        return None
    if fim is None:
        fim = len(texto)
    corpo = texto[inicio:fim]
    aparado = re.sub(r"(?:\n[ \t]*(?:-{3,}|\*{3,}|_{3,})?[ \t]*)+\s*$", "", corpo)
    return inicio, inicio + len(aparado)


def git(raiz: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=raiz, capture_output=True)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""


def montar_pedido(args, raiz: Path, atual: str, escopo: str, modo: str, orcamento: int) -> str:
    partes = [f"TAREFA: {args.tarefa}", f"ARQUIVO: {args.alvo}"]
    if modo == "secao":
        partes.append(f"Reescreva SOMENTE a seção abaixo e devolva-a começando pelo título \"{args.secao.strip()}\".")
    elif modo == "secao-nova":
        partes.append(f"A seção \"{args.secao.strip()}\" ainda não existe: escreva-a, começando por esse título.")
    elif modo == "novo":
        partes.append("O arquivo ainda não existe: escreva o conteúdo completo.")
    else:
        partes.append("Devolva o arquivo inteiro, já atualizado.")
    if escopo:
        partes.append("TEXTO ATUAL:\n<<<\n" + escopo.rstrip() + "\n>>>")

    restante = orcamento - sum(len(p) for p in partes)
    extras = []
    if args.diff:
        diff = git(raiz, "diff", "HEAD")
        if diff:
            extras.append(("DIFF (git diff HEAD)", diff))
    for caminho in args.contexto or []:
        p = (raiz / caminho) if not Path(caminho).is_absolute() else Path(caminho)
        if p.is_file():
            extras.append((f"CONTEXTO: {caminho}", verificar_docs.ler(p)))
        else:
            extras.append((f"CONTEXTO: {caminho}", "(arquivo não encontrado)"))
    if extras:
        fatia = max(restante // len(extras), 0)
        for rotulo, conteudo in extras:
            if len(conteudo) > fatia:
                conteudo = conteudo[:fatia] + "\n[... cortado ...]"
            partes.append(f"--- {rotulo} ---\n{conteudo}")
    return "\n\n".join(partes)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Redige documentação com o modelo local e confere por regra.")
    ap.add_argument("--alvo", required=True, help="arquivo Markdown no repositório (pode não existir)")
    ap.add_argument("--tarefa", required=True, help="o que o texto precisa dizer")
    ap.add_argument("--secao", help='título exato da seção a reescrever, ex.: "## Instalação"')
    ap.add_argument("--contexto", nargs="*", help="arquivos com os fatos (código, config, outros docs)")
    ap.add_argument("--diff", action="store_true", help="inclui o git diff HEAD como fato")
    ap.add_argument("--saida", help="onde gravar a proposta (padrão: pasta temporária)")
    ap.add_argument("--tentativas", type=int, default=3, help="1 + retornos com o motivo (padrão 3)")
    args = ap.parse_args(argv)

    inicio_relogio = time.monotonic()
    raiz = verificar_docs.raiz_git(Path.cwd())
    alvo = (raiz / args.alvo) if not Path(args.alvo).is_absolute() else Path(args.alvo)
    atual = verificar_docs.ler(alvo)
    saida = Path(args.saida) if args.saida else Path(tempfile.gettempdir()) / "orquestrador-docs" / alvo.name
    saida.parent.mkdir(parents=True, exist_ok=True)

    def relatar(resultado: str, tentativas: int, motivos: list[str]) -> None:
        print(f"ALVO: {args.alvo}")
        print(f"PROPOSTA: {saida if resultado != 'indisponivel' else '-'}")
        print(f"MODELO: {MODELO}")
        print(f"TENTATIVAS: {tentativas}")
        print(f"TEMPO: {time.monotonic() - inicio_relogio:.1f}s")
        print(f"RESULTADO: {resultado}")
        if motivos:
            print("MOTIVOS:")
            for m in motivos:
                print(f"- {m}")

    trecho = None
    if args.secao:
        trecho = localizar_secao(atual, args.secao)
        modo = "secao" if trecho else "secao-nova"
        escopo = atual[trecho[0]:trecho[1]] if trecho else ""
    else:
        modo = "arquivo" if atual else "novo"
        escopo = atual

    tokens_escopo = int(len(escopo) / CHARS_POR_TOKEN)
    num_predict = min(SAIDA_MAX_TOKENS, max(SAIDA_MIN_TOKENS, tokens_escopo * 2 + 512))
    orcamento = int((CTX - num_predict - 600) * CHARS_POR_TOKEN)  # 600 = sistema e folga
    if len(escopo) > orcamento * 0.6:
        relatar("indisponivel", 0, [f"texto atual grande demais para o modelo local ({len(escopo)} caracteres); "
                                    "use --secao com um título do arquivo"])
        return 3

    try:
        conferir_modelo()
        mensagens = [
            {"role": "system", "content": SISTEMA},
            {"role": "user", "content": montar_pedido(args, raiz, atual, escopo, modo, orcamento)},
        ]
        motivos: list[str] = []
        for tentativa in range(1, max(args.tentativas, 1) + 1):
            texto = limpar(conversar(mensagens, num_predict))
            if args.secao and not texto.lstrip().startswith("#"):
                texto = args.secao.strip() + "\n\n" + texto
            if modo == "secao":
                proposta = atual[:trecho[0]] + texto.rstrip() + atual[trecho[1]:]
            elif modo == "secao-nova":
                proposta = atual.rstrip() + "\n\n" + texto if atual.strip() else texto
            else:
                proposta = texto
            with open(saida, "w", encoding="utf-8", newline="") as f:  # mantém LF no Windows
                f.write(proposta)

            achados = verificar_docs.verificar(alvo.resolve(), proposta, atual, raiz)
            if not texto.strip():
                achados.append((0, "resposta vazia"))
            motivos = [m for _, m in achados]
            if not motivos:
                relatar("passou", tentativa, [])
                return 0
            mensagens += [
                {"role": "assistant", "content": texto},
                {"role": "user", "content": "Sua resposta foi rejeitada pelo verificador:\n"
                 + "\n".join(f"- {m}" for m in motivos)
                 + "\nVolte ao TEXTO ATUAL, copie sem mudar o que a tarefa não pede, corrija só isso e "
                 "devolva o texto completo de novo, no mesmo formato."},
            ]
        relatar("falhou", tentativa, motivos)
        return 1
    except Indisponivel as e:
        relatar("indisponivel", 0, [str(e)])
        return 3


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
