"""Testes do alternador da regra CONTEXTO (A/B da Fase 6). Sem tocar na config real."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import contexto_ab as ab  # noqa: E402

REGRA = "CONTEXTO (regra de custo): chame context_build. Use quando passar de ~2 mil tokens."
SISTEMA = "Prompt longo do orquestrador.\n\n" + REGRA + "\n\nTRIAGEM (regra, antes de tudo): classifique."


class TextoTest(unittest.TestCase):
    def test_extrai_o_paragrafo(self):
        self.assertEqual(ab.extrair(SISTEMA), REGRA)

    def test_extrai_vazio_quando_ausente(self):
        self.assertEqual(ab.extrair("só o prompt base\n\nTRIAGEM (regra, antes de tudo): x"), "")

    def test_desligar_remove_so_o_paragrafo(self):
        texto = ab.desligar(SISTEMA)
        self.assertNotIn("CONTEXTO (regra de custo)", texto)
        self.assertIn("Prompt longo do orquestrador.", texto)
        self.assertIn("TRIAGEM (regra, antes de tudo):", texto)

    def test_desligar_e_idempotente(self):
        uma_vez = ab.desligar(SISTEMA)
        self.assertEqual(ab.desligar(uma_vez), uma_vez)

    def test_ligar_devolve_o_texto_original(self):
        self.assertEqual(ab.ligar(ab.desligar(SISTEMA), REGRA), SISTEMA)

    def test_ligar_nao_duplica(self):
        self.assertEqual(ab.ligar(SISTEMA, REGRA), SISTEMA)

    def test_ligar_sem_ancora_falha(self):
        with self.assertRaises(ValueError):
            ab.ligar("prompt sem triagem", REGRA)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.config = self.base / "opencode.json"
        self.config.write_text(json.dumps({"agents": {"orquestrador": {"system": SISTEMA}}}),
                               encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def sistema(self):
        return json.loads(self.config.read_text(encoding="utf-8"))["agents"]["orquestrador"]["system"]

    def test_status_mostra_ligada(self):
        import io
        import contextlib
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = ab.principal(["--status", "--config", str(self.config)])
        self.assertEqual(codigo, 0)
        self.assertIn("LIGADA", saida.getvalue())

    def test_off_faz_backup_e_liga_de_volta(self):
        with mock.patch.object(ab, "regra_canonica", return_value=REGRA), \
                mock.patch("builtins.print"):
            self.assertEqual(ab.principal(["--off", "--config", str(self.config)]), 0)
            self.assertNotIn("CONTEXTO (regra de custo)", self.sistema())
            self.assertEqual(ab.principal(["--on", "--config", str(self.config)]), 0)
        self.assertEqual(self.sistema(), SISTEMA)
        backups = list(self.base.glob("opencode.json.bak.*"))
        self.assertEqual(len(backups), 2)

    def test_recusa_config_do_repositorio(self):
        import io
        import contextlib
        erro = io.StringIO()
        with contextlib.redirect_stderr(erro), \
                mock.patch.object(ab, "CONFIG_REPO", self.config.resolve()):
            codigo = ab.principal(["--off", "--config", str(self.config.resolve())])
        self.assertEqual(codigo, 2)
        self.assertIn("fonte canônica", erro.getvalue())


if __name__ == "__main__":
    unittest.main()
