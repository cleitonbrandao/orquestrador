#!/usr/bin/env python3
"""Avalia a resposta de um modelo a um dos prompts A-D de docs/PROMPT-TESTE.md.

Uso: python3 -I avaliar_respostas.py <A|B|C|D> <arquivo_com_a_resposta>
Imprime uma linha: "OK" ou "FALHA: <motivo>". Sempre sai com código 0.
Só usa a biblioteca padrão.
"""
import json
import os
import re
import subprocess
import sys
import tempfile


def limpar(texto):
    """Remove blocos <think>...</think> que alguns modelos deixam na resposta."""
    return re.sub(r"<think>.*?</think>", "", texto, flags=re.S).strip()


def avaliar_a(texto):
    passos = [l for l in texto.splitlines() if re.match(r"^\s*\d+[.)]\s+\S", l)]
    if len(passos) != 5:
        return f"FALHA: {len(passos)} passos numerados (esperado 5)"
    for l in passos:
        palavras = len(re.sub(r"^\s*\d+[.)]\s+", "", l).split())
        if palavras > 20:
            return f"FALHA: passo com {palavras} palavras (máx. 20)"
    if "100" not in texto:
        return "FALHA: não cita o limite 100"
    if not re.search(r"teste", texto, re.I):
        return "FALHA: sem passo de teste"
    return "OK"


def avaliar_b(texto):
    bruto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError as e:
        return f"FALHA: JSON inválido ({e.msg})"
    tarefas = dados.get("tarefas") if isinstance(dados, dict) else None
    if not isinstance(tarefas, list) or len(tarefas) != 5:
        return "FALHA: 'tarefas' deve ser uma lista com 5 itens"
    ids = [t.get("id") for t in tarefas if isinstance(t, dict)]
    if len(ids) != 5 or len(set(ids)) != 5:
        return "FALHA: ids ausentes ou repetidos"
    for t in tarefas:
        if not t.get("arquivos"):
            return f"FALHA: tarefa {t.get('id')} sem arquivos"
        deps = t.get("depende_de")
        if not isinstance(deps, list) or any(d not in ids for d in deps):
            return f"FALHA: tarefa {t.get('id')} com depende_de inválido"
    return "OK"


RUNNER = r"""
import sys, types
try:
    import pytest  # noqa: F401
except ImportError:
    sys.modules["pytest"] = types.ModuleType("pytest")
ns = {"__name__": "codigo_do_modelo"}
exec(compile(open("codigo.py", encoding="utf-8").read(), "codigo.py", "exec"), ns)
assert callable(ns.get("slugify")), "slugify não definida"
assert ns["slugify"]("  Olá, Mundo!! ") == "ola-mundo", "slugify('  Olá, Mundo!! ')"
assert ns["slugify"]("---") == "", "slugify('---')"
assert ns["slugify"]("ação") == "acao", "slugify('ação')"
testes = [f for n, f in ns.items() if n.startswith("test_") and callable(f)]
assert len(testes) >= 2, f"{len(testes)} testes escritos (esperado 2)"
for f in testes:
    f()
"""


def avaliar_c(texto):
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", texto, re.S)
    if not m:
        return "FALHA: sem bloco de código"
    with tempfile.TemporaryDirectory() as pasta:
        with open(os.path.join(pasta, "codigo.py"), "w", encoding="utf-8") as f:
            f.write(m.group(1))
        with open(os.path.join(pasta, "runner.py"), "w", encoding="utf-8") as f:
            f.write(RUNNER)
        try:
            r = subprocess.run(
                [sys.executable, "-I", "runner.py"],
                cwd=pasta, capture_output=True, text=True, timeout=20,
            )
        except subprocess.TimeoutExpired:
            return "FALHA: código travou (timeout 20 s)"
    if r.returncode != 0:
        ultima = (r.stderr.strip().splitlines() or ["erro desconhecido"])[-1]
        return f"FALHA: {ultima[:120]}"
    return "OK"


def avaliar_d(texto):
    baixo = texto.lower()
    achou = re.search(r"page\s*-\s*1|\(page|primeir[ao]s?|pula|pular|off-by-one|offset", baixo)
    if not achou:
        return "FALHA: não apontou o erro de início da página"
    linhas = [l for l in texto.splitlines() if re.match(r"^\s*linha\s+\d+", l, re.I)]
    if len(linhas) > 2:
        return f"FALHA: {len(linhas)} problemas listados (provável invenção)"
    return "OK"


AVALIADORES = {"A": avaliar_a, "B": avaliar_b, "C": avaliar_c, "D": avaliar_d}


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in AVALIADORES:
        print("FALHA: uso: avaliar_respostas.py <A|B|C|D> <arquivo>")
        return
    with open(sys.argv[2], encoding="utf-8", errors="replace") as f:
        texto = limpar(f.read())
    if not texto:
        print("FALHA: resposta vazia")
        return
    print(AVALIADORES[sys.argv[1]](texto))


if __name__ == "__main__":
    main()
