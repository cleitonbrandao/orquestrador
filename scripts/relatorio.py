#!/usr/bin/env python3
"""Rankings e relatório dos testes de modelos (lê docs/resultados/resultados.csv).

Uso: python3 -I relatorio.py <comando> [argumentos] [--csv ARQ] [--instalados a,b,c]
  rank              ranking por tokens/s, com a nota ao lado
  nota              ranking por nota (0-100), com a velocidade ao lado
  lista             todos os modelos testados (último teste) com a nota, mais os pendentes
  ver <modelo>      histórico completo de um modelo
  html [--abrir]    gera docs/resultados/relatorio.html (e abre no navegador com --abrir)
Só usa a biblioteca padrão.
"""
import csv
import html
import os
import shutil
import subprocess
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CSV_PADRAO = os.path.join(os.environ.get("ORQ_RESULTADOS") or os.path.join(RAIZ, "docs", "resultados"), "resultados.csv")

COR = sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _nerd():
    modo = os.environ.get("ORQ_ICONS", "")
    if modo:
        return modo == "nerd"
    try:
        saida = subprocess.run(["fc-list"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "nerd" in saida.lower()


NERD = COR and _nerd()
CAP_E, SEP, CAP_D = ("\ue0b6", "\ue0b0", "\ue0b0") if NERD else ("▐", "▌", "▌")
I_TROFEU, I_BOLT, I_FRASCO, I_CODIGO = ("\uf091", "\uf0e7", "\uf0c3", "\uf121") if NERD else ("★", "▲", "◆", "‹›")
I_OK, I_FALHA = ("\uf00c", "\uf00d") if NERD else ("✔", "✘")

# paleta de pixel art (r, g, b)
BASE, TEXTO, CINZA, ESCURO = (30, 30, 46), (205, 214, 244), (88, 91, 112), (49, 50, 68)
ROXO, CIANO, VERDE, AMAR = (137, 88, 245), (34, 211, 238), (74, 222, 128), (250, 204, 21)
ROSA, VERM, LARANJA, AZUL = (244, 114, 182), (248, 113, 113), (251, 146, 60), (96, 165, 250)
OURO, PRATA, BRONZE = (250, 204, 21), (203, 213, 225), (205, 127, 50)


def fg(rgb): return "\033[38;2;%d;%d;%dm" % rgb
def bg(rgb): return "\033[48;2;%d;%d;%dm" % rgb


def cor(rgb, texto):
    return f"{fg(rgb)}{texto}\033[0m" if COR else str(texto)


def c(codigo, texto):
    return f"\033[{codigo}m{texto}\033[0m" if COR else str(texto)


def negrito(t): return c("1", t)
def apagado(t): return c("2", t)
def ciano(t): return cor(CIANO, t)


def rgb_nota(n):
    return VERDE if n >= 70 else AMAR if n >= 40 else VERM


def cor_nota(n, texto=None):
    texto = f"{n:>3}" if texto is None else texto
    return cor(rgb_nota(n), texto) if not COR else f"\033[1m{fg(rgb_nota(n))}{texto}\033[0m"


def barra(valor, maximo, largura=14, rgb=None):
    cheio = 0 if maximo <= 0 else max(0, min(largura, round(valor / maximo * largura)))
    if not COR:
        return "█" * cheio + "░" * (largura - cheio)
    return fg(rgb or CIANO) + "█" * cheio + "\033[0m" + "\033[2m" + "░" * (largura - cheio) + "\033[0m"


def pilulas(*segmentos):
    """Linha powerline: segmentos = (bg, fg, texto)."""
    if not COR:
        return " ".join(f"[{t}]" for _, _, t in segmentos)
    saida, anterior = "", None
    for fundo, frente, texto in segmentos:
        saida += (fg(fundo) + CAP_E) if anterior is None else (fg(anterior) + bg(fundo) + SEP)
        saida += f"{bg(fundo)}{fg(frente)}\033[1m {texto} \033[0m"
        anterior = fundo
    return saida + fg(anterior) + CAP_D + "\033[0m"


def medalha(i):
    if not COR or i > 3:
        return apagado(i)
    return f"\033[1m{fg((OURO, PRATA, BRONZE)[i - 1])}{i}\033[0m"


def num(s, padrao=0.0):
    try:
        return float(s)
    except (TypeError, ValueError):
        return padrao


def ler(caminho):
    """Linhas do CSV; o último teste de cada (modelo, thinking) vem em `ultimos`."""
    if not os.path.isfile(caminho):
        return [], []
    with open(caminho, encoding="utf-8", newline="") as f:
        linhas = list(csv.DictReader(f))
    ultimos = {}
    for r in linhas:
        ultimos[(r["modelo"], r["thinking"])] = r
    return linhas, list(ultimos.values())


def serve_para(r):
    tok = num(r["tok_s_geracao"])
    ok = lambda k: r.get(k) == "OK"
    papeis = []
    if tok >= 15 and ok("B"):
        papeis.append("roteador/divisor")
    if tok >= 8 and ok("A") and ok("D"):
        papeis.append("planejador/revisor")
    if tok >= 8 and ok("C"):
        papeis.append("executor")
    return papeis


def marcas(r):
    if not COR:
        return " ".join(k if r.get(k) == "OK" else "·" for k in "ABCD")
    return " ".join(cor(VERDE if r.get(k) == "OK" else VERM, "■") for k in "ABCD")


def cabecalho(titulo, subtitulo="", icone=None, cor_fundo=None):
    print()
    print(pilulas((cor_fundo or ROXO, TEXTO, f"{icone or I_CODIGO}  {titulo}")))
    if subtitulo:
        print(apagado(subtitulo))
    print()


def tabela(cols, linhas):
    """cols: [(titulo, largura, alinhamento)]; linhas: listas de (texto_puro, texto_colorido)."""
    cab = "  ".join(negrito(t.ljust(w) if a == "<" else t.rjust(w)) for t, w, a in cols)
    print("  " + cab)
    print("  " + apagado("─" * (sum(w for _, w, _ in cols) + 2 * (len(cols) - 1))))
    for linha in linhas:
        partes = []
        for (t, w, a), (puro, colorido) in zip(cols, linha):
            puro = str(puro)
            if len(puro) > w:
                puro, colorido = puro[: w - 1] + "…", puro[: w - 1] + "…"
            pad = " " * (w - len(puro))
            partes.append(colorido + pad if a == "<" else pad + colorido)
        print("  " + "  ".join(partes))


def sem_dados(caminho):
    print(apagado(f"Nenhum teste salvo ainda ({os.path.relpath(caminho, RAIZ)}). Rode /test."))


def cmd_rank(ultimos, caminho, **_):
    if not ultimos:
        return sem_dados(caminho)
    ordem = sorted(ultimos, key=lambda r: num(r["tok_s_geracao"]), reverse=True)
    maximo = num(ordem[0]["tok_s_geracao"])
    cabecalho("Ranking por velocidade", "tokens por segundo na geração (rodada a quente), do mais rápido ao mais lento", I_BOLT, AMAR)
    linhas = []
    for i, r in enumerate(ordem, 1):
        tok = num(r["tok_s_geracao"])
        n = int(num(r["nota"]))
        linhas.append([
            (i, medalha(i)), (r["modelo"], negrito(r["modelo"])), (r["thinking"], apagado(r["thinking"])),
            (f"{tok:.1f}", ciano(f"{tok:.1f}")), ("█" * 14, barra(tok, maximo, 14, CIANO)),
            (r["tok_s_leitura"], r["tok_s_leitura"]), (f"{r['ram_gb']}G", f"{r['ram_gb']}G"),
            (f"{n}", cor_nota(n, f"{n}")),
        ])
    tabela([("#", 2, ">"), ("MODELO", 28, "<"), ("THINK", 5, "<"), ("TOK/S", 6, ">"), ("", 14, "<"),
            ("LEITURA", 7, ">"), ("RAM", 5, ">"), ("NOTA", 4, ">")], linhas)


def cmd_nota(ultimos, caminho, **_):
    if not ultimos:
        return sem_dados(caminho)
    ordem = sorted(ultimos, key=lambda r: (num(r["nota"]), num(r["tok_s_geracao"])), reverse=True)
    cabecalho("Ranking por nota", "0-100 = qualidade (até 60, prompts A-D) + velocidade (até 40, máximo em 20 tok/s)", I_TROFEU, ROSA)
    linhas = []
    for i, r in enumerate(ordem, 1):
        n = int(num(r["nota"]))
        papeis = ", ".join(serve_para(r)) or "—"
        linhas.append([
            (i, medalha(i)), (r["modelo"], negrito(r["modelo"])), (r["thinking"], apagado(r["thinking"])),
            (n, cor_nota(n)), ("█" * 14, barra(n, 100, 14, rgb_nota(n))),
            ("A B C D", marcas(r)), (r["tok_s_geracao"], ciano(r["tok_s_geracao"])), (papeis, apagado(papeis)),
        ])
    tabela([("#", 2, ">"), ("MODELO", 28, "<"), ("THINK", 5, "<"), ("NOTA", 4, ">"), ("", 14, "<"),
            ("A B C D", 7, "<"), ("TOK/S", 6, ">"), ("SERVE PARA", 36, "<")], linhas)
    print()
    print(apagado("  ■ A planejamento  ■ B divisão em JSON  ■ C código  ■ D revisão   verde = passou, vermelho = falhou"))


def cmd_lista(ultimos, caminho, instalados=(), **_):
    cabecalho("Modelos testados e pendentes", icone=I_FRASCO, cor_fundo=AZUL)
    testados = {r["modelo"].removesuffix(":latest") for r in ultimos}
    if ultimos:
        linhas = []
        for r in sorted(ultimos, key=lambda r: (r["modelo"], r["thinking"])):
            n = int(num(r["nota"]))
            linhas.append([
                (I_OK, cor(VERDE, I_OK)), (r["modelo"], negrito(r["modelo"])), (r["thinking"], apagado(r["thinking"])),
                (n, cor_nota(n)), ("A B C D", marcas(r)), (f"{num(r['tok_s_geracao']):.1f}", ciano(f"{num(r['tok_s_geracao']):.1f}")),
                (r["data"][:10], apagado(r["data"][:10])),
            ])
        tabela([("", 1, "<"), ("MODELO", 28, "<"), ("THINK", 5, "<"), ("NOTA", 4, ">"),
                ("A B C D", 7, "<"), ("TOK/S", 6, ">"), ("DATA", 10, "<")], linhas)
    else:
        sem_dados(caminho)
    pendentes = [m for m in instalados if m.removesuffix(":latest") not in testados]
    if pendentes:
        print()
        print("  " + negrito("Instalados, ainda sem teste"))
        for m in pendentes:
            print("  " + cor(AMAR, "○") + " " + m)
    elif instalados:
        print()
        print("  " + c("32", "Todos os modelos instalados já foram testados."))


def cmd_ver(linhas, caminho, args=(), **_):
    if not args:
        print("uso: /ver <modelo>")
        return
    alvo = args[0].removesuffix(":latest")
    sel = [r for r in linhas if r["modelo"].removesuffix(":latest") == alvo]
    if not sel:
        print(apagado(f"Nenhum teste de '{args[0]}'. Rode /test {args[0]}."))
        return
    cabecalho(f"Histórico: {sel[0]['modelo']}", f"{len(sel)} teste(s) salvo(s)")
    linhas_t = []
    for r in sel:
        n = int(num(r["nota"]))
        linhas_t.append([
            (r["data"], apagado(r["data"])), (r["thinking"], r["thinking"]), (r["tok_s_geracao"], ciano(r["tok_s_geracao"])),
            (r["tok_s_leitura"], r["tok_s_leitura"]), (r["carga_s"], r["carga_s"]), (f"{r['ram_gb']}G", f"{r['ram_gb']}G"),
            (r.get("ram_disp_mb") or "—", apagado(r.get("ram_disp_mb") or "—")),
            ("A B C D", marcas(r)), (n, cor_nota(n)),
        ])
    tabela([("DATA", 16, "<"), ("THINK", 5, "<"), ("TOK/S", 6, ">"), ("LEIT.", 7, ">"), ("CARGA", 5, ">"),
            ("RAM", 5, ">"), ("LIVRE MB", 8, ">"), ("A B C D", 7, "<"), ("NOTA", 4, ">")], linhas_t)
    papeis = ", ".join(serve_para(sel[-1])) or "nenhuma etapa"
    print()
    print("  Último teste serve para: " + negrito(papeis))
    pasta = os.path.join("docs", "resultados", sel[-1]["modelo"].replace(":", "_").replace("/", "_"))
    print(apagado(f"  Respostas brutas em {pasta}/"))


CSS = """
:root{color-scheme:light dark;--bg:#f4f1ff;--fg:#1e1e2e;--mut:#6c6f85;--card:#fff;--bd:#cfc8ee;--ok:#1a7f37;--md:#9a6700;--ruim:#cf222e;--bar:#7c3aed;--acc:#7c3aed;--sh:#cfc8ee}
@media(prefers-color-scheme:dark){:root{--bg:#1e1e2e;--fg:#cdd6f4;--mut:#8b8fa8;--card:#262637;--bd:#45475a;--ok:#4ade80;--md:#facc15;--ruim:#f87171;--bar:#22d3ee;--acc:#f472b6;--sh:#11111b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 'JetBrains Mono',ui-monospace,Menlo,Consolas,monospace}
main{max-width:1100px;margin:0 auto;padding:28px 16px 64px}
h1,h2,th,.card b{font-family:'Silkscreen','Press Start 2P',ui-monospace,monospace;letter-spacing:.04em}
h1{font-size:1.9rem;margin:0 0 6px;color:var(--acc);text-transform:uppercase;text-shadow:3px 3px 0 var(--sh)}
p.sub{color:var(--mut);margin:0 0 24px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px;margin-bottom:28px}
.card{background:var(--card);border:2px solid var(--bd);box-shadow:4px 4px 0 var(--sh);padding:14px}
.card b{display:block;font-size:1.05rem;color:var(--acc);overflow-wrap:anywhere}.card span{color:var(--mut);font-size:.8rem}
.wrap{overflow-x:auto;background:var(--card);border:2px solid var(--bd);box-shadow:4px 4px 0 var(--sh)}table{border-collapse:collapse;width:100%;min-width:780px}
th,td{padding:9px 12px;text-align:left;border-bottom:2px solid var(--bd);white-space:nowrap}
th{cursor:pointer;color:var(--acc);font-size:.72rem;text-transform:uppercase;user-select:none}th:hover{text-decoration:underline}
tr:last-child td{border-bottom:0}tr:hover td{background:color-mix(in srgb,var(--acc) 8%,transparent)}td.n{text-align:right;font-variant-numeric:tabular-nums}
.bar{display:inline-block;width:96px;height:10px;margin-left:8px;vertical-align:middle;background:repeating-linear-gradient(90deg,var(--bd) 0 6px,transparent 6px 8px);overflow:hidden}
.bar i{display:block;height:100%;background:repeating-linear-gradient(90deg,var(--bar) 0 6px,transparent 6px 8px)}
.nota{font-weight:700}.ok{color:var(--ok)}.md{color:var(--md)}.ruim{color:var(--ruim)}.f{color:var(--mut)}
.k{display:inline-block;width:1.5em;text-align:center;font-weight:700;margin-right:2px;border:2px solid currentColor}.k.f{border-color:var(--bd)}
h2{font-size:1rem;margin:34px 0 10px;color:var(--acc)}code{background:var(--card);border:2px solid var(--bd);padding:1px 6px}
"""

JS = """
document.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{
 const tb=th.closest('table').tBodies[0],rows=[...tb.rows],asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
 rows.sort((a,b)=>{const x=a.cells[i].dataset.v??a.cells[i].textContent,y=b.cells[i].dataset.v??b.cells[i].textContent;
  const nx=parseFloat(x),ny=parseFloat(y);const r=(!isNaN(nx)&&!isNaN(ny))?nx-ny:x.localeCompare(y);return asc?r:-r});
 rows.forEach(r=>tb.appendChild(r))}));
"""


def cmd_html(ultimos, caminho, instalados=(), args=(), **_):
    destino = os.path.join(os.path.dirname(caminho), "relatorio.html")
    if not ultimos:
        return sem_dados(caminho)
    e = html.escape
    ordem = sorted(ultimos, key=lambda r: num(r["tok_s_geracao"]), reverse=True)
    maximo = max(num(r["tok_s_geracao"]) for r in ordem) or 1
    rapido = ordem[0]
    melhor = max(ultimos, key=lambda r: num(r["nota"]))
    testados = {r["modelo"].removesuffix(":latest") for r in ultimos}
    pendentes = [m for m in instalados if m.removesuffix(":latest") not in testados]
    linhas = []
    for r in ordem:
        tok, n = num(r["tok_s_geracao"]), int(num(r["nota"]))
        cls = "ok" if n >= 70 else "md" if n >= 40 else "ruim"
        ks = "".join(f'<span class="k {"ok" if r[k] == "OK" else "f"}">{k if r[k] == "OK" else "·"}</span>' for k in "ABCD")
        papeis = ", ".join(serve_para(r)) or "—"
        linhas.append(
            f'<tr><td>{e(r["modelo"])}</td><td>{e(r["thinking"])}</td>'
            f'<td class="n" data-v="{tok}">{tok:.1f}<span class="bar"><i style="width:{tok / maximo * 100:.0f}%"></i></span></td>'
            f'<td class="n">{e(r["tok_s_leitura"])}</td><td class="n">{e(r["carga_s"])}</td><td class="n">{e(r["ram_gb"])}</td>'
            f'<td data-v="{sum(r[k] == "OK" for k in "ABCD")}">{ks}</td>'
            f'<td class="n nota {cls}" data-v="{n}">{n}</td><td>{e(papeis)}</td><td class="f">{e(r["data"][:10])}</td></tr>'
        )
    pend = ""
    if pendentes:
        pend = "<h2>Instalados, ainda sem teste</h2><p>" + ", ".join(f"<code>{e(m)}</code>" for m in pendentes) + "</p>"
    doc = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Testes de modelos locais</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Silkscreen:wght@400;700&display=swap">
<style>{CSS}</style></head><body><main>
<h1>Testes de modelos locais</h1>
<p class="sub">Ollama, só CPU. Nota = qualidade (até 60) + velocidade (até 40). Clique no cabeçalho para ordenar.</p>
<div class="cards">
<div class="card"><b>{len(ultimos)}</b><span>testes (último de cada modelo/thinking)</span></div>
<div class="card"><b>{e(rapido["modelo"])}</b><span>mais rápido: {num(rapido["tok_s_geracao"]):.1f} tok/s</span></div>
<div class="card"><b>{e(melhor["modelo"])}</b><span>maior nota: {int(num(melhor["nota"]))}/100</span></div>
<div class="card"><b>{len(pendentes)}</b><span>instalados sem teste</span></div>
</div>
<div class="wrap"><table><thead><tr><th>Modelo</th><th>Think</th><th>Tok/s</th><th>Leitura</th><th>Carga s</th><th>RAM GB</th>
<th>A B C D</th><th>Nota</th><th>Serve para</th><th>Data</th></tr></thead><tbody>
{"".join(linhas)}
</tbody></table></div>
<p class="sub" style="margin-top:12px">A planejamento · B divisão em JSON · C código · D revisão.</p>
{pend}
</main><script>{JS}</script></body></html>
"""
    with open(destino, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"Relatório gerado: {os.path.relpath(destino, RAIZ)}")
    if "--abrir" in args:
        opener = shutil.which("xdg-open")
        if opener:
            subprocess.Popen([opener, destino], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            print(apagado("xdg-open não encontrado; abra o arquivo no navegador."))


COMANDOS = {"rank": cmd_rank, "nota": cmd_nota, "lista": cmd_lista, "ver": cmd_ver, "html": cmd_html}


def main():
    args = sys.argv[1:]
    caminho, instalados = CSV_PADRAO, []
    for flag in ("--csv", "--instalados"):
        if flag in args:
            i = args.index(flag)
            valor = args[i + 1] if i + 1 < len(args) else ""
            del args[i:i + 2]
            if flag == "--csv":
                caminho = valor
            else:
                instalados = [m for m in valor.split(",") if m]
    if not args or args[0] not in COMANDOS:
        print(__doc__)
        return
    linhas, ultimos = ler(caminho)
    COMANDOS[args[0]](linhas=linhas, ultimos=ultimos, caminho=caminho, instalados=instalados, args=args[1:])
    print()


if __name__ == "__main__":
    main()
