"""Testes do avaliador da trilha E (decisão). Determinísticos: sem Ollama e sem rede.

Rodar: python3 -m unittest discover -s tests -v
"""
import json
import os
import sys
import unittest

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import avaliar_decisao as av  # noqa: E402

CASOS = os.path.join(RAIZ, "casos", "suporte", "decisao", "casos.json")


def resposta(choice, conf=None, pergunta="escolha"):
    corpo = {"answers": {pergunta: {"type": "choice", "choice": choice}}}
    if conf is not None:
        corpo["answers"][pergunta]["confidence"] = conf
    return corpo


class AvaliarTest(unittest.TestCase):
    def test_acerto_exato(self):
        self.assertEqual(av.avaliar(resposta("1", 0.95), "1")[0], "OK")

    def test_erro_com_conviccao(self):
        veredito, motivo = av.avaliar(resposta("2", 0.95), "1")
        self.assertEqual(veredito, "FALHA")
        self.assertIn("2", motivo)
        self.assertIn("1", motivo)

    def test_nenhuma_quando_esperado_tem_opcao_sempre_escala(self):
        # o gateway escala em "nenhuma" independente da confiança
        self.assertEqual(av.avaliar(resposta("nenhuma", 0.99), "1")[0], "ESCALA")

    def test_nenhuma_quando_esperado_e_nenhuma(self):
        self.assertEqual(av.avaliar(resposta("nenhuma", 0.60), "nenhuma")[0], "OK/escala")

    def test_acerto_com_confianca_baixa_conta_como_escala(self):
        self.assertEqual(av.avaliar(resposta("1", 0.40), "1")[0], "OK/escala")

    def test_erro_com_confianca_baixa_deixa_a_cascata_decidir(self):
        self.assertEqual(av.avaliar(resposta("3", 0.30), "1")[0], "ESCALA")

    def test_sem_choice_e_falha(self):
        self.assertEqual(av.avaliar({"answers": {"escolha": {"type": "choice"}}}, "1")[0], "FALHA")
        self.assertEqual(av.avaliar({}, "1")[0], "FALHA")
        self.assertEqual(av.avaliar({"answers": {"escolha": {"choice": None}}}, "1")[0], "FALHA")

    def test_sem_confianca_nao_quebra(self):
        self.assertEqual(av.avaliar(resposta("1"), "1")[0], "OK")

    def test_aceitos_conta_como_acerto(self):
        self.assertEqual(av.avaliar(resposta("7", 0.9), "4", aceitos=("7",))[0], "OK")

    def test_aceita_corpo_inteiro_e_resposta_solta(self):
        inteiro = {"model": "d3:2b", "answers": {"escolha": {"choice": "1", "confidence": 0.9}}}
        solta = {"choice": "1", "confidence": 0.9, "probabilities": {"1": 0.9}}
        self.assertEqual(av.avaliar(inteiro, "1")[0], "OK")
        self.assertEqual(av.avaliar(solta, "1")[0], "OK")

    def test_limiar_customizado(self):
        self.assertEqual(av.avaliar(resposta("1", 0.60), "1", limiar=0.5)[0], "OK")
        self.assertEqual(av.avaliar(resposta("1", 0.60), "1", limiar=0.8)[0], "OK/escala")


class AgregarTest(unittest.TestCase):
    def linhas(self, *pares):
        return [{"veredito": v, "ms": ms} for v, ms in pares]

    def test_metricas_e_nota(self):
        m = av.agregar(self.linhas(("OK", 100), ("OK", 200), ("OK/escala", 300), ("FALHA", 400)),
                       p50_escalada=700, baseline_ms=1500)
        self.assertEqual(m["casos"], 4)
        self.assertEqual(m["acerto"], 3)
        self.assertEqual(m["acerto_pct"], 75.0)
        self.assertEqual(m["escaladas"], 1)
        self.assertEqual(m["taxa_escalada_pct"], 25.0)
        self.assertEqual(m["falhas"], 1)
        self.assertEqual(m["p50_ms"], 250)
        self.assertEqual(m["p95_ms"], 400)
        self.assertEqual(m["ms_estimado"], 425)
        self.assertEqual(m["nota"], 45 + 15 + 15)

    def test_escalada_alta_zera_o_peso(self):
        m = av.agregar(self.linhas(("ESCALA", 100), ("ESCALA", 100), ("OK", 100)),
                       p50_escalada=700, baseline_ms=5000)
        self.assertEqual(m["pontos_escalada"], 0)

    def test_tempo_lento_zera_o_peso(self):
        m = av.agregar(self.linhas(("OK", 4000)), p50_escalada=700, baseline_ms=1000)
        self.assertEqual(m["pontos_tempo"], 0)

    def test_vazio(self):
        self.assertEqual(av.agregar([]), {"casos": 0})


class DatasetTest(unittest.TestCase):
    def base(self, **extra):
        dados = {
            "opcoes": {"1": "um", "2": "dois"},
            "casos": [
                {"id": "a", "texto": "texto", "esperado": "1", "split": "dev"},
                {"id": "b", "texto": "texto", "esperado": "nenhuma", "split": "teste"},
            ],
        }
        dados.update(extra)
        return dados

    def test_dataset_minimo_valido(self):
        self.assertEqual(av.validar(self.base()), [])

    def test_id_repetido(self):
        dados = self.base()
        dados["casos"][1]["id"] = "a"
        self.assertTrue(any("repetido" in e for e in av.validar(dados)))

    def test_esperado_inexistente(self):
        dados = self.base()
        dados["casos"][0]["esperado"] = "9"
        self.assertTrue(any("não existe" in e for e in av.validar(dados)))

    def test_split_invalido(self):
        dados = self.base()
        dados["casos"][0]["split"] = "treino"
        self.assertTrue(any("split" in e for e in av.validar(dados)))

    def test_texto_vazio(self):
        dados = self.base()
        dados["casos"][0]["texto"] = "  "
        self.assertTrue(any("texto vazio" in e for e in av.validar(dados)))

    def test_aceitos_sem_opcao(self):
        dados = self.base()
        dados["casos"][0]["aceitos"] = ["9"]
        self.assertTrue(any("aceito" in e for e in av.validar(dados)))

    def test_dataset_do_repositorio_e_valido(self):
        with open(CASOS, encoding="utf-8") as f:
            dados = json.load(f)
        self.assertEqual(av.validar(dados), [])
        self.assertGreaterEqual(len(dados["casos"]), 64)
        dev = sum(1 for c in dados["casos"] if c["split"] == "dev")
        teste = sum(1 for c in dados["casos"] if c["split"] == "teste")
        self.assertGreaterEqual(min(dev, teste), 20)


if __name__ == "__main__":
    unittest.main()
