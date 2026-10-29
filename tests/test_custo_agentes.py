"""Testes do relatório de custo. Determinísticos: sem rede e sem histórico real.

Rodar: python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import custo_agentes as ca  # noqa: E402


def msg(agente="orquestrador", provider="google", entrada=1000, saida=100, cache=0,
        projeto="/tmp/p", quando=1000):
    return {
        "agente": agente,
        "modelo": "m1",
        "provider": provider,
        "sessao": "ses_1",
        "projeto": projeto,
        "quando": quando,
        "entrada": entrada,
        "saida": saida,
        "raciocinio": 0,
        "cache_lido": cache,
        "cache_escrito": 0,
        "custo": 0.0,
    }


class NormalizarTest(unittest.TestCase):
    def test_mensagem_de_assistente(self):
        cru = {
            "role": "assistant", "agent": "exec-local", "modelID": "gemma4",
            "providerID": "Ollama", "path": {"cwd": "C:\\repo"},
            "time": {"created": 123}, "cost": "0.5",
            "tokens": {"input": 10, "output": 5, "reasoning": 2,
                       "cache": {"read": 7, "write": 3}},
        }
        r = ca.normalizar(cru)
        self.assertEqual(r["agente"], "exec-local")
        self.assertEqual(r["provider"], "ollama")   # normalizado para minúsculas
        self.assertTrue(ca.eh_local(r))
        self.assertEqual((r["entrada"], r["saida"], r["cache_lido"], r["cache_escrito"]), (10, 5, 7, 3))
        self.assertEqual(r["custo"], 0.5)

    def test_ignora_usuario(self):
        self.assertIsNone(ca.normalizar({"role": "user"}))

    def test_sem_tokens_zera(self):
        r = ca.normalizar({"role": "assistant", "agent": "x"})
        self.assertEqual((r["entrada"], r["saida"], r["cache_lido"]), (0, 0, 0))

    def test_valores_estranhos_nao_quebram(self):
        cru = {"role": "assistant", "tokens": {"input": "abc", "output": None,
                                               "cache": {"read": True}}}
        r = ca.normalizar(cru)
        self.assertEqual((r["entrada"], r["saida"], r["cache_lido"]), (0, 0, 0))


class ProjetoTest(unittest.TestCase):
    def test_caminho_windows_com_caixa_diferente(self):
        self.assertTrue(ca.mesmo_projeto("C:\\Users\\X\\proj", "c:/users/x/proj"))

    def test_subpasta_conta(self):
        self.assertTrue(ca.mesmo_projeto("C:\\proj\\sub", "C:\\proj"))

    def test_prefixo_parcial_nao_conta(self):
        self.assertFalse(ca.mesmo_projeto("C:\\projeto-outro", "C:\\proj"))

    def test_vazio_nao_conta(self):
        self.assertFalse(ca.mesmo_projeto("", "C:\\proj"))


class FiltroTest(unittest.TestCase):
    def test_por_periodo(self):
        m = [msg(quando=100), msg(quando=200), msg(quando=300)]
        self.assertEqual(len(ca.filtrar(m, desde=200, ate=300)), 2)

    def test_sem_filtro_devolve_tudo(self):
        m = [msg(), msg()]
        self.assertEqual(len(ca.filtrar(m)), 2)


class AgregarTest(unittest.TestCase):
    def test_separa_pago_e_local(self):
        m = [msg(agente="exec-backend"), msg(agente="exec-local", provider="ollama"), msg()]
        linhas = ca.agregar(m, lambda x: (x["agente"], x["modelo"]))
        origens = {l.chave[0]: l.origem for l in linhas}
        self.assertEqual(origens["exec-backend"], "pago")
        self.assertEqual(origens["exec-local"], "local")

    def test_soma_por_chave(self):
        m = [msg(entrada=100, saida=10), msg(entrada=200, saida=20)]
        linhas = ca.agregar(m, lambda x: (x["agente"], x["modelo"]))
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0].msgs, 2)
        self.assertEqual(linhas[0].entrada, 300)
        self.assertEqual(linhas[0].saida, 30)

    def test_ordena_por_contexto(self):
        m = [msg(agente="a", entrada=10), msg(agente="b", entrada=500)]
        linhas = ca.agregar(m, lambda x: (x["agente"], x["modelo"]))
        self.assertEqual(linhas[0].chave[0], "b")


class TotaisTest(unittest.TestCase):
    def test_split_pago_local(self):
        m = [msg(entrada=1000, cache=500), msg(provider="ollama", entrada=10)]
        t = ca.totais(m)
        self.assertEqual(t["pago"].entrada, 1000)
        self.assertEqual(t["pago"].cache_lido, 500)
        self.assertEqual(t["local"].entrada, 10)
        self.assertEqual(t["msgs"], 2)

    def test_razao_entrada_por_saida(self):
        linha = ca.Linha()
        linha.entrada, linha.cache_lido, linha.saida = 900, 100, 100
        self.assertEqual(ca.razao(linha), 10.0)

    def test_razao_sem_saida(self):
        linha = ca.Linha()
        linha.entrada = 10
        self.assertIsNone(ca.razao(linha))


class FormatoTest(unittest.TestCase):
    def test_num_usa_ponto_de_milhar(self):
        self.assertEqual(ca.num(1234567), "1.234.567")

    def test_dia_fim_do_periodo(self):
        inicio = ca.dia("2026-10-01")
        fim = ca.dia("2026-10-01", fim=True)
        self.assertLess(inicio, fim)
        self.assertEqual(fim - inicio, 86_399_999)

    def test_relatorio_vazio(self):
        self.assertIn("Nenhuma mensagem", ca.relatorio([], {}))

    def test_relatorio_mostra_totais(self):
        texto = ca.relatorio([msg(), msg(provider="ollama")], {})
        self.assertIn("POR AGENTE", texto)
        self.assertIn("pago", texto)
        self.assertIn("contexto processado no local", texto)


if __name__ == "__main__":
    unittest.main()
