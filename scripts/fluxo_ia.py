import csv
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

CSV_PATH = os.path.join("docs", "resultados", "resultados.csv")

def main():
    if not os.path.exists(CSV_PATH):
        print("Arquivo resultados.csv não encontrado.")
        return

    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        linhas = list(csv.DictReader(f))

    ultimos = {}
    for r in linhas:
        ultimos[r["modelo"]] = r

    print("=" * 80)
    print(" RECOMENDAÇÕES DE COMBINAÇÃO PARA O FLUXO DE CÓDIGO (GERADOR + REVISOR)")
    print("=" * 80)
    print("Baseado nas medições reais de velocidade (tok/s) e nota de qualidade (A-D).\n")

    geradores = []
    revisores = []

    for modelo, r in ultimos.items():
        toks = float(r.get("tok_s_geracao", 0) or 0)
        nota = int(r.get("nota", 0) or 0)
        c = r.get("C", "")
        d = r.get("D", "")

        if toks >= 40 and nota >= 70:
            geradores.append((modelo, toks, nota, c, d))
        if nota >= 75 or d == "OK":
            revisores.append((modelo, toks, nota, c, d))

    print("🚀 MODELOS RECOMENDADOS COMO GERADORES (Alta velocidade para 'trabalho de formiguinha'):")
    for m, t, n, c, d in sorted(geradores, key=lambda x: x[1], reverse=True):
        print(f"  - {m:20s} | {t:5.1f} tok/s | Nota: {n:3d}/100 | Código (C): {c or '—'} | Revisão (D): {d or '—'}")

    print("\n🔍 MODELOS RECOMENDADOS COMO REVISORES / SEGUNDA OPINIÃO (Alta acurácia):")
    for m, t, n, c, d in sorted(revisores, key=lambda x: x[2], reverse=True):
        print(f"  - {m:20s} | {t:5.1f} tok/s | Nota: {n:3d}/100 | Código (C): {c or '—'} | Revisão (D): {d or '—'}")

    print("\n💡 SUGESTÕES DE DUPLAS (GERADOR + REVISOR) PARA 8 GB VRAM:")
    print("  1. Padrão Equilibrado:")
    print("     [Gerador: qwen3.5:4b (~52 tok/s)] + [Revisor: qwen3.5:9b ou gemma4:e4b]")
    print("  2. Ultra-Rápido (Formiguinha Pura):")
    print("     [Gerador: bonsai-2:4b (~73 tok/s)] + [Revisor: qwen3.5:4b (~52 tok/s)]")
    print("=" * 80)

if __name__ == "__main__":
    main()
