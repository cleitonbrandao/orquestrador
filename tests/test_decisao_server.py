"""Testes do servidor MCP de decisão. Determinísticos: sem Ollama e sem rede.

Rodar: python3 -m unittest discover -s tests -v
"""
import json
import os
import sys
import unittest

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RAIZ, "mcp", "decisao"))

import server as dec  # noqa: E402


class PedidoTest(unittest.TestCase):
    def test_usa_choice_e_acrescenta_nenhuma(self):
        corpo = dec.corpo_do_pedido("texto", "pergunta?", {"a": "A", "b": "B"})
        pergunta = corpo["questions"]["escolha"]
        self.assertEqual(pergunta["type"], "choice")
        self.assertEqual(pergunta["instructions"], "pergunta?")
        self.assertIn("nenhuma", pergunta["criteria"])
        self.assertEqual(pergunta["criteria"]["a"], "A")

    def test_nao_sobrescreve_nenhuma_do_chamador(self):
        corpo = dec.corpo_do_pedido("t", "p", {"nenhuma": "nada se aplica"})
        self.assertEqual(corpo["questions"]["escolha"]["criteria"]["nenhuma"], "nada se aplica")

    def test_state_recebe_o_texto(self):
        corpo = dec.corpo_do_pedido("o pedido", "p", {"a": "A"})
        self.assertEqual(corpo["state"], "o pedido")


class ExtrairTest(unittest.TestCase):
    def test_formato_objeto(self):
        resp = {"answers": {"escolha": {"type": "choice", "choice": "backend", "confidence": 0.9}}}
        self.assertEqual(dec.extrair(resp), ("backend", 0.9))

    def test_formato_string_json(self):
        resp = {"answers": {"escolha": json.dumps({"choice": "docs", "confidence": 0.8})}}
        self.assertEqual(dec.extrair(resp), ("docs", 0.8))

    def test_sem_confianca_devolve_none(self):
        resp = {"answers": {"escolha": {"choice": "docs"}}}
        self.assertEqual(dec.extrair(resp), ("docs", None))

    def test_confianca_booleana_nao_conta(self):
        resp = {"answers": {"escolha": {"choice": "docs", "confidence": True}}}
        self.assertEqual(dec.extrair(resp), ("docs", None))

    def test_sem_choice_falha(self):
        with self.assertRaises(dec.DecisaoError):
            dec.extrair({"answers": {"escolha": {"type": "choice"}}})

    def test_sem_answers_falha(self):
        with self.assertRaises(dec.DecisaoError):
            dec.extrair({})


class AvaliarTest(unittest.TestCase):
    def test_confianca_alta_decide(self):
        self.assertEqual(dec.avaliar("backend", 0.9), (False, "confiança 0.90 >= 0.70"))

    def test_confianca_baixa_escala(self):
        escalar, motivo = dec.avaliar("backend", 0.5)
        self.assertTrue(escalar)
        self.assertIn("0.50", motivo)

    def test_nenhuma_escala_mesmo_com_confianca_alta(self):
        escalar, motivo = dec.avaliar("nenhuma", 0.99)
        self.assertTrue(escalar)
        self.assertIn("nenhuma", motivo)

    def test_sem_confianca_escala(self):
        self.assertTrue(dec.avaliar("docs", None)[0])

    def test_limiar_customizado(self):
        self.assertFalse(dec.avaliar("docs", 0.55, 0.5)[0])
        self.assertTrue(dec.avaliar("docs", 0.55, 0.6)[0])


class DecidirTest(unittest.TestCase):
    def test_texto_vazio_bloqueia_sem_chamar_api(self):
        r = dec.decidir({"texto": "  ", "pergunta": "p", "opcoes": {"a": "A"}})
        self.assertEqual(r["resultado"], "bloqueado")
        self.assertIn("texto", r["motivo"])

    def test_sem_opcoes_bloqueia(self):
        r = dec.decidir({"texto": "t", "pergunta": "p", "opcoes": {}})
        self.assertEqual(r["resultado"], "bloqueado")

    def test_sem_pergunta_bloqueia(self):
        r = dec.decidir({"texto": "t", "pergunta": "", "opcoes": {"a": "A"}})
        self.assertEqual(r["resultado"], "bloqueado")


class TextoTest(unittest.TestCase):
    def test_decidido_mostra_escolha_e_confianca(self):
        txt = dec.texto_do_resultado({
            "resultado": "decidido", "escolha": "docs", "confianca": 0.9,
            "motivo": "ok", "modelo": "d3:2b", "ms": 2000,
        })
        self.assertIn("ESCOLHA: docs", txt)
        self.assertIn("CONFIANCA: 0.90", txt)
        self.assertNotIn("ACAO:", txt)

    def test_escalar_avisa_para_decidir_no_principal(self):
        txt = dec.texto_do_resultado({
            "resultado": "escalar", "escolha": "nenhuma", "confianca": 0.9,
            "motivo": "'nenhuma'", "modelo": "d3:2b", "ms": 2000,
        })
        self.assertIn("ACAO:", txt)

    def test_bloqueado_mostra_motivo(self):
        txt = dec.texto_do_resultado({"resultado": "bloqueado", "motivo": "sem modelo", "modelo": "d3:2b"})
        self.assertIn("MOTIVO: sem modelo", txt)


if __name__ == "__main__":
    unittest.main()
