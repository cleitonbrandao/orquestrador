"""Testes da busca determinística (fallback do kb). Sem rede."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import contexto_busca as cb  # noqa: E402


class TermosTest(unittest.TestCase):
    def test_ignora_curtos_e_repete(self):
        self.assertEqual(cb.termos("o Sync do sync de SSc"), ["sync", "ssc"])

    def test_vazio(self):
        self.assertEqual(cb.termos("a b c"), [])


class BuscaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name)
        (self.raiz / "app").mkdir()
        (self.raiz / "app" / "a.php").write_text(
            "class SaleController\n{\n    // team_id obrigatorio\n}\n", encoding="utf-8")
        (self.raiz / "app" / "b.php").write_text("nada aqui\n", encoding="utf-8")
        (self.raiz / "node_modules" / "x").mkdir(parents=True)
        (self.raiz / "node_modules" / "x" / "c.js").write_text("team_id lixo\n", encoding="utf-8")
        (self.raiz / ".env").write_text("TEAM_ID=1\n", encoding="utf-8")
        (self.raiz / "bin.png").write_bytes(b"\x89PNG\x00team_id")

    def tearDown(self):
        self.tmp.cleanup()

    def test_encontra_com_caminho_e_linha(self):
        achados = cb.buscar(self.raiz, "team_id")
        self.assertEqual(achados[0]["path"], "app/a.php")
        self.assertEqual(achados[0]["line"], 3)
        self.assertIn("team_id", achados[0]["text"])

    def test_ignora_node_modules(self):
        caminhos = {a["path"] for a in cb.buscar(self.raiz, "team_id")}
        self.assertNotIn("node_modules/x/c.js", caminhos)

    def test_ignora_dotenv(self):
        caminhos = {a["path"] for a in cb.buscar(self.raiz, "team_id")}
        self.assertNotIn(".env", caminhos)

    def test_ignora_binario(self):
        self.assertEqual(cb.buscar(self.raiz, "png"), [])

    def test_respeita_k(self):
        (self.raiz / "app" / "d.php").write_text("team_id\n", encoding="utf-8")
        (self.raiz / "app" / "e.php").write_text("team_id\n", encoding="utf-8")
        self.assertEqual(len(cb.buscar(self.raiz, "team_id", k=1)), 1)

    def test_ordena_por_termos_distintos(self):
        (self.raiz / "app" / "f.php").write_text("team_id e ssc\n", encoding="utf-8")
        achados = cb.buscar(self.raiz, "team_id ssc")
        self.assertEqual(achados[0]["path"], "app/f.php")
        self.assertEqual(achados[0]["score"], 2)

    def test_consulta_sem_termos_falha(self):
        with self.assertRaises(cb.BuscaError):
            cb.buscar(self.raiz, "a b")

    def test_raiz_inexistente_falha(self):
        with self.assertRaises(cb.BuscaError):
            cb.buscar(self.raiz / "nao-existe", "team_id")


if __name__ == "__main__":
    unittest.main()
