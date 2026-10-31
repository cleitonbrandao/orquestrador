"""Testes da medição de adoção do MCP de contexto. Sem banco real."""
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import contextlib
from datetime import datetime
from pathlib import Path

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import contexto_adocao as ca  # noqa: E402


def quando(dia=30, hora=12):
    return int(datetime(2026, 10, dia, hora).timestamp() * 1000)


def mensagem(*ferramentas, tempo=None):
    partes = []
    for nome in ferramentas:
        entrada = {"path": "app/a.php"} if nome in ("read", "contexto_context_get_file") else {}
        partes.append({"type": "tool", "name": nome, "state": {"input": entrada}})
    return json.dumps({"time": {"created": tempo or quando()}, "agent": "orquestrador",
                       "content": partes})


class Banco:
    def __init__(self, caminho):
        self.con = sqlite3.connect(caminho)
        self.con.execute("CREATE TABLE session_v2 (id TEXT, title TEXT, directory TEXT)")
        self.con.execute("""CREATE TABLE session_message (id TEXT, session_id TEXT, type TEXT,
                            time_created INTEGER, data TEXT)""")

    def sessao(self, sid, titulo, dir_):
        self.con.execute("INSERT INTO session_v2 VALUES (?,?,?)", (sid, titulo, dir_))

    def msg(self, sid, dados):
        self.con.execute("INSERT INTO session_message VALUES (?,?,?,?,?)",
                         (sid + str(id(dados)), sid, "assistant", quando(), dados))

    def fechar(self):
        self.con.commit()
        self.con.close()


class CategoriaTest(unittest.TestCase):
    def test_contexto(self):
        self.assertEqual(ca.categoria("contexto_context_build"), "contexto")
        self.assertEqual(ca.categoria("contexto_context_get_file"), "contexto")

    def test_leitura(self):
        for nome in ("read", "grep", "glob", "kb_search_kb", "trail_trail_find_code"):
            self.assertEqual(ca.categoria(nome), "leitura", nome)

    def test_outros(self):
        for nome in ("shell", "edit", "run_tests_run_tests", "write"):
            self.assertEqual(ca.categoria(nome), "outros", nome)


class LeituraDoBancoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        b = Banco(self.base / "opencode.db")
        b.sessao("s1", "Usou contexto", "/repo/um")
        b.msg("s1", mensagem("contexto_context_build", "read", "shell"))
        b.sessao("s2", "So leu", "/repo/um")
        b.msg("s2", mensagem("read", "grep"))
        b.sessao("s3", "Outro projeto", "/repo/dois")
        b.msg("s3", mensagem("contexto_context_build"))
        b.fechar()

    def tearDown(self):
        self.tmp.cleanup()

    def test_conta_por_categoria(self):
        itens = ca.chamadas(self.base)
        self.assertEqual(len(itens), 6)
        self.assertEqual(sum(1 for i in itens if i["categoria"] == "contexto"), 2)
        self.assertEqual(sum(1 for i in itens if i["categoria"] == "leitura"), 3)

    def test_filtra_por_projeto(self):
        itens = ca.chamadas(self.base, projeto="/repo/um")
        self.assertEqual({i["sessao"] for i in itens}, {"s1", "s2"})

    def test_resumo_conta_adocao(self):
        r = ca.resumo(ca.chamadas(self.base, projeto="/repo/um"))
        self.assertEqual(r["sessoes"], 2)
        self.assertEqual(r["sessoes_com_contexto"], 1)
        self.assertEqual(r["adocao_pct"], 50.0)
        self.assertEqual(r["chamadas_leitura"], 3)
        self.assertEqual(r["leituras_por_sessao"], 1.5)

    def test_arquivos_distintos(self):
        r = ca.resumo(ca.chamadas(self.base))
        self.assertEqual(r["arquivos_lidos_distintos"], 1)

    def test_json_nao_quebra_com_set(self):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = ca.principal(["--storage", str(self.base), "--todos"])
        self.assertEqual(codigo, 0)
        texto = saida.getvalue()
        self.assertIn("sessões com ferramenta", texto)
        self.assertIn("66.7%", texto)

    def test_relatorio_vazio(self):
        self.assertIn("nenhuma chamada", ca.relatorio([]))

    def test_relatorio_mostra_taxa(self):
        texto = ca.relatorio(ca.chamadas(self.base, projeto="/repo/um"))
        self.assertIn("50.0%", texto)
        self.assertIn("Usou contexto", texto)


if __name__ == "__main__":
    unittest.main()
