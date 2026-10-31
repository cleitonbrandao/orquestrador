"""Testes do cache de pacote (Fase 7). Sem rede."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import contexto_cache as cc  # noqa: E402


class ChaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name)
        self.arq = self.raiz / "a.py"
        self.arq.write_text("um\ndois\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_estavel_para_mesma_entrada(self):
        k1 = cc.chave("t", "m", [self.arq], {"max_total": 100})
        k2 = cc.chave("t", "m", [self.arq], {"max_total": 100})
        self.assertEqual(k1, k2)

    def test_muda_com_a_tarefa(self):
        self.assertNotEqual(cc.chave("t1", "m", [self.arq]), cc.chave("t2", "m", [self.arq]))

    def test_muda_com_o_modelo(self):
        self.assertNotEqual(cc.chave("t", "m1", [self.arq]), cc.chave("t", "m2", [self.arq]))

    def test_muda_com_o_orcamento(self):
        a = cc.chave("t", "m", [self.arq], {"max_total": 100})
        b = cc.chave("t", "m", [self.arq], {"max_total": 200})
        self.assertNotEqual(a, b)

    def test_muda_quando_o_arquivo_e_editado(self):
        antes = cc.chave("t", "m", [self.arq])
        self.arq.write_text("um\ndois\ntres\n", encoding="utf-8")
        self.assertNotEqual(antes, cc.chave("t", "m", [self.arq]))

    def test_muda_quando_a_memoria_e_editada(self):
        regras = self.raiz / "r.json"
        regras.write_text("{}", encoding="utf-8")
        antes = cc.chave("t", "m", [self.arq], memoria=[regras])
        os.utime(regras, (time.time() + 10, time.time() + 10))
        self.assertNotEqual(antes, cc.chave("t", "m", [self.arq], memoria=[regras]))


class GuardarObterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.estado = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.estado)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_roundtrip(self):
        cc.guardar("abc", {"task": "x", "validation": {"pending": 0}})
        self.assertEqual(cc.obter("abc")["task"], "x")

    def test_ausente_devolve_none(self):
        self.assertIsNone(cc.obter("nao-existe"))

    def test_json_corrompido_devolve_none(self):
        pasta = cc.pasta()
        pasta.mkdir(parents=True)
        (pasta / "ruim.json").write_text("{nao", encoding="utf-8")
        self.assertIsNone(cc.obter("ruim"))

    def test_expirado_devolve_none(self):
        cc.guardar("velho", {"task": "x"})
        caminho = cc.pasta() / "velho.json"
        antigo = time.time() - 30 * 86400
        os.utime(caminho, (antigo, antigo))
        self.assertIsNone(cc.obter("velho"))

    def test_poda_limita_entradas(self):
        pasta = cc.pasta()
        pasta.mkdir(parents=True)
        for i in range(5):
            (pasta / f"c{i}.json").write_text(json.dumps({"task": i}), encoding="utf-8")
            os.utime(pasta / f"c{i}.json", (time.time() + i, time.time() + i))
        cc._podar(maximo=2)
        self.assertEqual(len(list(pasta.glob("*.json"))), 2)

    def test_limpar(self):
        cc.guardar("a", {"task": "x"})
        cc.guardar("b", {"task": "y"})
        self.assertEqual(cc.limpar(), 2)
        self.assertEqual(cc.estatisticas()["entradas"], 0)

    def test_estatisticas(self):
        cc.guardar("a", {"task": "x"})
        r = cc.estatisticas()
        self.assertEqual(r["entradas"], 1)
        self.assertGreater(r["bytes"], 0)


if __name__ == "__main__":
    unittest.main()
