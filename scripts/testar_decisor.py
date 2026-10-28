#!/usr/bin/env python3
"""Testa um modelo de DECISÃO do Ollama (/v1/systemone) em casos rotulados.

Não mede tok/s: modelos de decisão não geram texto. Mede acerto, taxa de escalada,
erros confiantes, latência e grava a linha em docs/resultados/decisao.csv.

Uso:
  testar_decisor.py <modelo> [--casos ARQ] [--split dev|teste|todos] [--amostra N]
                             [--limiar 0.7] [--instrucoes "pergunta"] [--torneio]
                             [--visao IMG] [--p50-escalada MS] [--baseline-ms MS]
                             [--saida DIR]

Chamado por scripts/testar-decisor.sh e scripts/testar-decisor.ps1 (que cuidam do --limpar).
Só usa a biblioteca padrão.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)
import avaliar_decisao as av  # noqa: E402

API = os.environ.get("OLLAMA_HOST_URL", "http://localhost:11434").rstrip("/")
CASOS_PADRAO = os.path.join(RAIZ, "casos", "suporte", "decisao", "casos.json")
TEMPO_LIMITE = 300

# cores só quando o destino é terminal (e NO_COLOR não está setado)
COR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
VERM = "\033[31m" if COR else ""
VERDE = "\033[32m" if COR else ""
AMAR = "\033[33m" if COR else ""
CINZA = "\033[2m" if COR else ""
N = "\033[0m" if COR else ""


def http(caminho: str, corpo: dict | None = None, metodo: str = "POST") -> dict:
    dados = None if corpo is None else json.dumps(corpo).encode()
    req = urllib.request.Request(API + caminho, data=dados, method=metodo,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=TEMPO_LIMITE) as r:
        texto = r.read().decode("utf-8", "replace")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return {"error": texto[:200]}


def modelo_info(modelo: str) -> dict:
    try:
        return http("/api/show", {"model": modelo})
    except (urllib.error.URLError, OSError) as e:
        return {"error": str(e)}


def capacidades(modelo: str) -> list[str]:
    return list(modelo_info(modelo).get("capabilities") or [])


def ram_disp_mb() -> str:
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for linha in f:
                if linha.startswith("MemAvailable:"):
                    return str(int(linha.split()[1]) // 1024)
    except OSError:
        pass
    return ""


def barra(pct: float, largura: int = 24) -> str:
    cheio = max(0, min(largura, round(largura * pct / 100)))
    return "█" * cheio + "░" * (largura - cheio)


def exibir(caminho: str) -> str:
    """Relativo à raiz quando está dentro do repositório; absoluto quando não."""
    try:
        if os.path.commonpath([os.path.abspath(caminho), RAIZ]) == RAIZ:
            return os.path.relpath(caminho, RAIZ)
    except ValueError:
        pass
    return caminho


def ler_casos(caminho: str, split: str, amostra: int) -> tuple[dict, list[dict]]:
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)
    casos = [c for c in dados.get("casos") or [] if split == "todos" or c.get("split") == split]
    if amostra > 0:
        casos = casos[:amostra]
    return dados, casos


def pedido(modelo: str, texto: str, pergunta: str, opcoes: dict, imagem: str | None = None) -> dict:
    corpo = {
        "model": modelo,
        "state": texto,
        "keep_alive": "10m",
        "questions": {
            "escolha": {
                "type": "choice",
                "instructions": pergunta,
                "criteria": dict(opcoes, nenhuma="Nenhuma das opções descreve o problema."),
            }
        },
    }
    if imagem:
        corpo["images"] = [imagem]
    return corpo


def testar_torneio(modelo: str) -> int | None:
    """Quantas opções o modelo aceita numa única pergunta (30, 40...). None = nenhuma."""
    maior = None
    for n in (30, 40):
        criterios = {f"c{i}": f"causa possível {i}" for i in range(n)}
        corpo = {"model": modelo, "state": "erro ao gravar a rescisão", "keep_alive": "10m",
                 "questions": {"q": {"type": "choice", "instructions": "Qual causa?", "criteria": criterios}}}
        try:
            resp = http("/v1/systemone", corpo)
        except (urllib.error.URLError, OSError) as e:
            print(f"    {n} opções: {VERM}erro{N} ({e})")
            break
        qtd = len(((resp.get("answers") or {}).get("q") or {}).get("probabilities") or {})
        if qtd >= n:
            print(f"    {n} opções: {VERDE}aceitou{N} ({qtd} probabilidades)")
            maior = n
        else:
            print(f"    {n} opções: {AMAR}não devolveu todas{N} ({qtd})")
    return maior


def testar_visao(modelo: str, caminho: str) -> str:
    try:
        with open(caminho, "rb") as f:
            imagem = base64.b64encode(f.read()).decode()
    except OSError as e:
        print(f"    {VERM}não abriu{N}: {e}")
        return ""
    corpo = {
        "model": modelo, "state": "O que esta imagem mostra?", "images": [imagem], "keep_alive": "10m",
        "questions": {"tela": {"type": "choice", "instructions": "Que tipo de tela é esta?",
                               "criteria": {"lista": "lista de registros", "formulario": "formulário",
                                            "erro": "mensagem de erro", "relatorio": "relatório"}}},
    }
    try:
        resp = http("/v1/systemone", corpo)
    except (urllib.error.URLError, OSError) as e:
        print(f"    {VERM}não aceitou{N}: {e}")
        return "nao"
    tela = (resp.get("answers") or {}).get("tela") or {}
    if tela.get("choice"):
        conf = tela.get("confidence")
        print(f"    {VERDE}aceita imagem{N}: {tela['choice']}"
              + (f" (confiança {float(conf):.2f})" if isinstance(conf, (int, float)) else ""))
        return "sim"
    print(f"    {VERM}não aceitou{N}: {str(resp.get('error') or 'sem resposta')[:120]}")
    return "nao"


def main() -> int:
    p = argparse.ArgumentParser(description="Testa modelo de decisão em casos rotulados.")
    p.add_argument("modelo", nargs="?", default=None)
    p.add_argument("--casos", default=CASOS_PADRAO)
    p.add_argument("--split", default="teste", choices=("dev", "teste", "todos"))
    p.add_argument("--amostra", type=int, default=0)
    p.add_argument("--limiar", type=float, default=0.70)
    p.add_argument("--instrucoes", default=None, help="sobrepõe a pergunta do dataset")
    p.add_argument("--torneio", action="store_true")
    p.add_argument("--visao", default=None)
    p.add_argument("--p50-escalada", type=float, default=700.0)
    p.add_argument("--baseline-ms", type=float, default=1500.0)
    p.add_argument("--saida", default=None)
    a = p.parse_args()

    modelo = a.modelo
    if not modelo:
        modelo = input("Modelo de decisão (ex.: d3:2b, tev1:0.8b): ").strip()
    if not modelo:
        print("nenhum modelo informado", file=sys.stderr)
        return 2
    saida = a.saida or os.environ.get("ORQ_RESULTADOS") or os.path.join(RAIZ, "docs", "resultados")

    try:
        versao = http("/api/version", metodo="GET").get("version", "?")
    except (urllib.error.URLError, OSError) as e:
        print(f"Ollama não responde em {API}: {e}", file=sys.stderr)
        return 1

    caps = capacidades(modelo)
    if not caps:
        print(f"'{modelo}' não está instalado. Rode: ollama pull {modelo}", file=sys.stderr)
        return 1
    if "decision" not in caps:
        print(f"'{modelo}' não é um modelo de decisão (capacidades: {', '.join(caps)}). "
              "Use scripts/testar-modelo.sh para modelos de texto.", file=sys.stderr)
        return 1

    if versao != "?" and tuple(int(x) for x in versao.split(".")[:3]) < (0, 40, 9):
        print(f"{CINZA}aviso: Ollama {versao}; o d3 declara exigir >= 0.40.9 (funciona, mas é não suportado){N}")

    dados, casos = ler_casos(a.casos, a.split, a.amostra)
    erros = av.validar(dados)
    if erros:
        for e in erros:
            print(f"FALHA: {e}", file=sys.stderr)
        return 1
    if not casos:
        print(f"nenhum caso no split '{a.split}'", file=sys.stderr)
        return 1

    pergunta = a.instrucoes or dados.get("instrucoes") or "Qual tipo melhor descreve o problema?"
    opcoes = dados["opcoes"]
    agora = time.strftime("%Y-%m-%d_%H-%M-%S")
    pasta = os.path.join(saida, "decisao", modelo.replace(":", "_").replace("/", "_"), agora)
    os.makedirs(pasta, exist_ok=True)
    tsv = os.path.join(pasta, "avaliacao.tsv")

    print()
    print(f"  Modelo de decisão {VERDE}{modelo}{N} | {len(casos)} casos ({a.split}) | limiar {a.limiar}")

    try:  # aquecimento: paga o carregamento, não conta no resultado
        http("/v1/systemone", pedido(modelo, "aquecimento", "escolha", {"a": "a", "b": "b"}))
    except (urllib.error.URLError, OSError):
        pass

    inicio = time.time()
    linhas = []
    with open(tsv, "w", encoding="utf-8") as f:
        f.write("id\tesperado\tchoice\tconfianca\tveredito\tms\n")
        for caso in casos:
            cid, esperado = caso["id"], str(caso["esperado"])
            arq = os.path.join(pasta, f"{cid}.json")
            t0 = time.monotonic()
            try:
                resp = http("/v1/systemone", pedido(modelo, caso["texto"], pergunta, opcoes))
            except (urllib.error.URLError, OSError) as e:
                resp = {"error": str(e)}
            ms = int((time.monotonic() - t0) * 1000)
            with open(arq, "w", encoding="utf-8") as fh:
                json.dump(resp, fh, ensure_ascii=False)

            if "answers" not in resp:
                print(f"  {VERM}✗{N} {cid:<9} {CINZA}ERRO: {str(resp.get('error'))[:70]}{N}")
                f.write(f"{cid}\t{esperado}\t\t\tFALHA\t{ms}\n")
                linhas.append({"veredito": "FALHA", "ms": ms})
                continue

            veredito, motivo = av.avaliar(resp, esperado, a.limiar, caso.get("aceitos") or ())
            escolha = ((resp.get("answers") or {}).get("escolha") or {}).get("choice") or ""
            conf = ((resp.get("answers") or {}).get("escolha") or {}).get("confidence")
            f.write(f"{cid}\t{esperado}\t{escolha}\t{conf if conf is not None else ''}\t{veredito}\t{ms}\n")
            linhas.append({"veredito": veredito, "ms": ms})

            marca, cor = {"OK": ("✓", VERDE), "OK/escala": ("•", AMAR),
                          "ESCALA": ("~", CINZA)}.get(veredito, ("✗", VERM))
            extra = "" if veredito == "OK" else f"  ({motivo or 'escalaria'})"
            print(f"  {cor}{marca}{N} {cid:<9} {CINZA}{escolha or '—':<3}{N} esperado {esperado:<7}"
                  f"  {CINZA}{ms:5d} ms{N}{CINZA}{extra}{N}")

    opcoes_max = None
    if a.torneio:
        print()
        print(f"{CINZA}  Torneio (uma pergunta, N opções){N}")
        opcoes_max = testar_torneio(modelo)

    visao = ""
    if a.visao:
        print()
        print(f"{CINZA}  Visão: {exibir(a.visao)}{N}")
        visao = testar_visao(modelo, a.visao)

    m = av.agregar(linhas, a.p50_escalada, a.baseline_ms)
    if not m.get("casos"):
        print("FALHA: sem resultados", file=sys.stderr)
        return 1
    tempo_total = int(time.time() - inicio)
    cor_nota = VERDE if m["nota"] >= 70 else AMAR if m["nota"] >= 40 else VERM

    print()
    print(f"  {CINZA}Decisão{N} {VERDE}{modelo}{N}  {cor_nota}{m['nota']}/100{N}")
    print(f"  acerto             {VERDE}{m['acerto']:3d}/{m['casos']} ({m['acerto_pct']}%){N}  {barra(m['acerto_pct'])}")
    print(f"  escalaria          {AMAR}{m['escaladas']:3d}/{m['casos']} ({m['taxa_escalada_pct']}%){N}  {barra(m['taxa_escalada_pct'])}")
    print(f"  erra com convicção  {VERM if m['falhas'] else VERDE}{m['falhas']}{N}")
    print(f"  tempo              p50 {m['p50_ms']}ms · p95 {m['p95_ms']}ms · estimado com escalada {m['ms_estimado']}ms")
    print(f"  nota               {cor_nota}{m['nota']}{N}/100  "
          f"{CINZA}(acerto {m['pontos_acerto']} + escalada {m['pontos_escalada']} + tempo {m['pontos_tempo']}){N}")
    print(f"{CINZA}  estimativa com 4B a {a.p50_escalada:.0f}ms por escalada; ajuste com --p50-escalada{N}")
    print(f"{CINZA}  respostas em: {exibir(pasta)}{N}")

    csv = os.path.join(saida, "decisao.csv")
    cabecalho = ("data,modelo,casos,split,dataset_hash,acerto,acerto_pct,escaladas,taxa_escalada_pct,"
                 "falhas,p50_ms,p95_ms,ms_estimado,nota,tempo_s,ram_disp_mb,maquina,opcoes_max,visao")
    novo = not os.path.exists(csv)
    with open(csv, "a", encoding="utf-8") as f:
        if novo:
            f.write(cabecalho + "\n")
        with open(a.casos, "rb") as fh:
            assinatura = hashlib.sha256(fh.read()).hexdigest()[:12]
        f.write(",".join(str(x) for x in (
            time.strftime("%Y-%m-%d_%H:%M"), modelo, m["casos"], a.split, assinatura,
            m["acerto"], m["acerto_pct"], m["escaladas"], m["taxa_escalada_pct"], m["falhas"],
            m["p50_ms"], m["p95_ms"], m["ms_estimado"], m["nota"], tempo_total,
            ram_disp_mb(), socket.gethostname(), opcoes_max or "", visao)) + "\n")
    print(f"{CINZA}  salvo em {exibir(csv)}{N}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
