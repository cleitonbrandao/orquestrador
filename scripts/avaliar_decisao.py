#!/usr/bin/env python3
"""Avalia uma resposta de modelo de decisão (/v1/systemone) contra um caso rotulado.

Uso:
  avaliar_decisao.py --caso db-01 --esperado 1 --resposta r.json [--limiar 0.7]
  avaliar_decisao.py --validar casos.json
  avaliar_decisao.py --agregar avaliacao.tsv [--p50-escalada MS] [--baseline-ms MS]

Imprime uma linha ("OK", "OK/escala", "ESCALA" ou "FALHA: motivo") e sai com 0.
Só usa a biblioteca padrão. Nunca chama a rede.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys

LIMIAR_PADRAO = 0.70

# Vereditos possíveis. Acerto e escalada são dimensões independentes:
#   OK          acertou e o gateway responderia direto
#   OK/escala   acertou, mas a confiança levaria ao 4B (custo, não erro)
#   ESCALA      errou ou disse "nenhuma"; o gateway chamaria o 4B (a cascata decide)
#   FALHA       errou com confiança: é o caso perigoso, erra com convicção
VEREDITOS = ("OK", "OK/escala", "ESCALA", "FALHA")


def resposta_de(dados: dict, pergunta: str = "escolha") -> dict:
    """Aceita o corpo inteiro do /v1/systemone ou só a resposta de uma pergunta."""
    if not isinstance(dados, dict):
        return {}
    respostas = dados.get("answers")
    if isinstance(respostas, dict):
        alvo = respostas.get(pergunta)
        if isinstance(alvo, dict):
            return alvo
        if len(respostas) == 1:  # veio uma pergunta só, com outro nome
            unica = next(iter(respostas.values()))
            if isinstance(unica, dict):
                return unica
    if "choice" in dados or "probabilities" in dados:
        return dados
    return {}


def avaliar(dados: dict, esperado: str, limiar: float = LIMIAR_PADRAO, aceitos=()) -> tuple[str, str]:
    """Devolve (veredito, motivo)."""
    resposta = resposta_de(dados)
    escolha = resposta.get("choice")
    if not isinstance(escolha, str) or not escolha:
        return "FALHA", "resposta sem 'choice'"

    confianca = resposta.get("confidence")
    if not isinstance(confianca, (int, float)) or isinstance(confianca, bool):
        confianca = None

    # "nenhuma" sempre escala no gateway, independente da confiança.
    if escolha == "nenhuma" and esperado != "nenhuma":
        return "ESCALA", "'nenhuma' (sempre escala)"

    alvos = {esperado, *aceitos}
    acertou = escolha in alvos
    baixa = confianca is not None and confianca < limiar
    conf = f"{confianca:.2f}" if confianca is not None else "?"

    if acertou:
        if baixa:
            return "OK/escala", f"acertou {escolha} com confiança {conf} < {limiar:.2f}"
        return "OK", ""
    if baixa:
        return "ESCALA", f"escolheu {escolha} (esperado {esperado}) com confiança {conf} < {limiar:.2f}"
    return "FALHA", f"escolheu {escolha} (esperado {esperado})"


def validar(dados: dict) -> list[str]:
    """Confere o dataset. Devolve a lista de erros (vazia = ok)."""
    erros: list[str] = []
    opcoes = dados.get("opcoes")
    casos = dados.get("casos")
    if not isinstance(opcoes, dict) or not opcoes:
        erros.append("'opcoes' ausente ou vazio")
        opcoes = {}
    if not isinstance(casos, list) or not casos:
        erros.append("'casos' ausente ou vazio")
        casos = []
    niveis = dados.get("niveis") if isinstance(dados.get("niveis"), dict) else {}

    ids: set[str] = set()
    splits: dict[str, int] = {}
    for i, caso in enumerate(casos, 1):
        if not isinstance(caso, dict):
            erros.append(f"caso {i} não é um objeto")
            continue
        cid = str(caso.get("id") or "").strip()
        if not cid:
            erros.append(f"caso {i} sem 'id'")
        elif cid in ids:
            erros.append(f"id repetido: {cid}")
        else:
            ids.add(cid)
        if not str(caso.get("texto") or "").strip():
            erros.append(f"{cid or i}: texto vazio")
        esperado = caso.get("esperado")
        if esperado is None:
            erros.append(f"{cid or i}: sem 'esperado'")
        elif esperado != "nenhuma" and str(esperado) not in opcoes:
            erros.append(f"{cid or i}: esperado '{esperado}' não existe em opcoes")
        for aceito in caso.get("aceitos") or []:
            if aceito != "nenhuma" and str(aceito) not in opcoes:
                erros.append(f"{cid or i}: aceito '{aceito}' não existe em opcoes")
            if aceito == esperado:
                erros.append(f"{cid or i}: '{aceito}' está em aceitos e em esperado")
        severidade = caso.get("severidade")
        if severidade and niveis and severidade not in niveis:
            erros.append(f"{cid or i}: severidade '{severidade}' não existe em niveis")
        split = str(caso.get("split") or "")
        if split not in ("dev", "teste"):
            erros.append(f"{cid or i}: 'split' precisa ser 'dev' ou 'teste' (achei '{split}')")
        else:
            splits[split] = splits.get(split, 0) + 1

    if set(splits) != {"dev", "teste"} and casos:
        erros.append(f"o dataset precisa ter casos 'dev' e 'teste' (achei {splits or 'nenhum'})")
    return erros


def _p95(valores: list[float]) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    indice = max(0, math.ceil(0.95 * len(ordenados)) - 1)
    return float(ordenados[indice])


def agregar(linhas: list[dict], p50_escalada: float | None = None, baseline_ms: float | None = None) -> dict:
    """Métricas e nota (0-100) a partir das linhas do TSV do runner."""
    n = len(linhas)
    if n == 0:
        return {"casos": 0}

    acertos = sum(1 for l in linhas if l["veredito"] in ("OK", "OK/escala"))
    escaladas = sum(1 for l in linhas if l["veredito"] in ("OK/escala", "ESCALA"))
    falhas = sum(1 for l in linhas if l["veredito"] == "FALHA")
    tempos = [float(l["ms"]) for l in linhas if l.get("ms") not in (None, "")]
    p50 = float(statistics.median(tempos)) if tempos else 0.0
    p95 = _p95(tempos)

    acerto = acertos / n
    taxa_escalada = escaladas / n
    p50_esc = float(p50_escalada or 0.0)
    ms_estimado = p50 + taxa_escalada * p50_esc

    # 60 acerto + 25 economia de escalada + 15 tempo.
    if taxa_escalada <= 0.16:
        pontos_escalada = 25
    elif taxa_escalada <= 0.25:
        pontos_escalada = 15
    elif taxa_escalada <= 0.32:
        pontos_escalada = 8
    else:
        pontos_escalada = 0

    referencia = float(baseline_ms) if baseline_ms else 1500.0
    if ms_estimado <= referencia:
        pontos_tempo = 15
    elif ms_estimado <= referencia * 1.5:
        pontos_tempo = 8
    else:
        pontos_tempo = 0

    return {
        "casos": n,
        "acerto": acertos,
        "acerto_pct": round(acerto * 100, 1),
        "escaladas": escaladas,
        "taxa_escalada_pct": round(taxa_escalada * 100, 1),
        "falhas": falhas,
        "p50_ms": round(p50),
        "p95_ms": round(p95),
        "ms_estimado": round(ms_estimado),
        "pontos_acerto": round(60 * acerto),
        "pontos_escalada": pontos_escalada,
        "pontos_tempo": pontos_tempo,
        "nota": round(60 * acerto) + pontos_escalada + pontos_tempo,
        "p50_escalada": p50_esc,
    }


def ler_tsv(caminho: str) -> list[dict]:
    linhas = []
    with open(caminho, encoding="utf-8") as f:
        cabecalho = f.readline().rstrip("\n").split("\t")
        for linha in f:
            campos = linha.rstrip("\n").split("\t")
            if not any(campos):
                continue
            linhas.append(dict(zip(cabecalho, campos)))
    return linhas


def main() -> None:
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("--caso")
    p.add_argument("--esperado")
    p.add_argument("--resposta")
    p.add_argument("--limiar", type=float, default=LIMIAR_PADRAO)
    p.add_argument("--validar")
    p.add_argument("--agregar")
    p.add_argument("--p50-escalada", type=float, default=None)
    p.add_argument("--baseline-ms", type=float, default=None)
    p.add_argument("--tsv", action="store_true", help="saída em uma linha TSV, para o runner")
    a = p.parse_args()

    if a.validar:
        try:
            dados = json.load(open(a.validar, encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"FALHA: não foi possível ler o dataset ({e})")
            raise SystemExit(1)
        erros = validar(dados)
        if erros:
            for erro in erros:
                print(f"FALHA: {erro}")
            raise SystemExit(1)
        casos = dados.get("casos") or []
        dev = sum(1 for c in casos if c.get("split") == "dev")
        print(f"OK: {len(casos)} casos ({dev} dev, {len(casos) - dev} teste), "
              f"{len(dados.get('opcoes') or {})} opções, {len(dados.get('niveis') or {})} níveis")
        return

    if a.agregar:
        linhas = ler_tsv(a.agregar)
        m = agregar(linhas, a.p50_escalada, a.baseline_ms)
        if not m.get("casos"):
            print("FALHA: nenhuma linha no TSV")
            return
        if a.tsv:
            campos = ("casos", "acerto", "acerto_pct", "escaladas", "taxa_escalada_pct", "falhas",
                      "p50_ms", "p95_ms", "ms_estimado", "nota", "pontos_acerto",
                      "pontos_escalada", "pontos_tempo")
            print("\t".join(str(m[c]) for c in campos))
            return
        print(f"casos={m['casos']} acerto={m['acerto']} ({m['acerto_pct']}%) "
              f"escaladas={m['escaladas']} ({m['taxa_escalada_pct']}%) falhas={m['falhas']} "
              f"p50={m['p50_ms']}ms p95={m['p95_ms']}ms estimado={m['ms_estimado']}ms "
              f"nota={m['nota']} (acerto {m['pontos_acerto']} + escalada {m['pontos_escalada']} "
              f"+ tempo {m['pontos_tempo']})")
        return

    if not (a.caso and a.esperado and a.resposta):
        print("FALHA: uso: --caso ID --esperado X --resposta ARQ | --validar ARQ | --agregar TSV")
        return

    try:
        dados = json.load(open(a.resposta, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"FALHA: resposta ilegível ({e})")
        return

    veredito, motivo = avaliar(dados, str(a.esperado), a.limiar)
    print(veredito if not motivo else f"{veredito}: {motivo}")


if __name__ == "__main__":
    main()
