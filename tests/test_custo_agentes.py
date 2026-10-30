"""Testes do relatório de custo. Determinísticos: sem rede e sem histórico real.

Rodar: python3 -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import custo_agentes as ca  # noqa: E402


def msg(agente="orquestrador", provider="google", entrada=1000, saida=100, cache=0,
        projeto="/tmp/p", quando=1000, sessao="ses_1", modelo="m1", custo=0.0,
        cache_escrito=0):
    return {
        "agente": agente,
        "modelo": modelo,
        "provider": provider,
        "sessao": sessao,
        "projeto": projeto,
        "quando": quando,
        "entrada": entrada,
        "saida": saida,
        "raciocinio": 0,
        "cache_lido": cache,
        "cache_escrito": cache_escrito,
        "custo": custo,
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


class EconomiaTest(unittest.TestCase):
    def test_contexto_soma_cache_escrito(self):
        linha = ca.Linha()
        linha.entrada, linha.cache_lido, linha.cache_escrito = 10, 20, 5
        self.assertEqual(ca.contexto(linha), 35)

    def test_sem_precos_nao_inventa_dolar(self):
        e = ca.economia([msg(), msg(provider="ollama")])
        self.assertIsNone(e["custo_evitado"])
        self.assertIsNone(e["referencia"])
        self.assertEqual(e["contexto_local"], 1000)

    def test_custo_evitado_usa_preco_por_milhao(self):
        precos = {"referencia": "pago", "preco": {
            "input": 2.0, "cache_read": 0.5, "cache_write": 3.0, "output": 10.0}}
        local = msg(provider="ollama", entrada=1_000_000, cache=2_000_000,
                    cache_escrito=1_000_000, saida=100_000)
        e = ca.economia([local], precos)
        # 2.0 + 0.5*2 + 3.0*1 + 10.0*0.1 = 7.0
        self.assertAlmostEqual(e["custo_evitado"], 7.0)
        self.assertAlmostEqual(e["custo_evitado_por_sessao"], 7.0)

    def test_fracao_local(self):
        m = [msg(entrada=300), msg(provider="ollama", entrada=100)]
        e = ca.economia(m)
        self.assertAlmostEqual(e["fracao_local"], 0.25)

    def test_contexto_pago_por_sessao(self):
        m = [msg(entrada=100, sessao="a"), msg(entrada=100, sessao="b")]
        self.assertEqual(ca.economia(m)["contexto_pago_por_sessao"], 100)

    def test_secao_avisa_quando_nada_rodou_no_local(self):
        texto = ca.secao_economia([msg()])
        self.assertIn("nenhum token rodou no local", texto)
        self.assertIn("--precos", texto)


class PrecosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def escrever(self, dados, nome="precos.json"):
        caminho = self.dir / nome
        caminho.write_text(json.dumps(dados), encoding="utf-8")
        return caminho

    def test_le_referencia(self):
        caminho = self.escrever({"referencia": "x", "modelos": {
            "x": {"input": 1, "cache_read": 0.1, "cache_write": 1.25, "output": 5}}})
        precos = ca.carregar_precos(caminho)
        self.assertEqual(precos["referencia"], "x")
        self.assertEqual(precos["preco"]["output"], 5.0)

    def test_referencia_unica_implicita(self):
        caminho = self.escrever({"modelos": {"x": {"input": 1}}})
        self.assertEqual(ca.carregar_precos(caminho)["referencia"], "x")

    def test_referencia_ausente_em_varios_modelos(self):
        caminho = self.escrever({"modelos": {"x": {"input": 1}, "y": {"input": 2}}})
        with self.assertRaises(ValueError):
            ca.carregar_precos(caminho)

    def test_referencia_inexistente(self):
        caminho = self.escrever({"referencia": "z", "modelos": {"x": {"input": 1}}})
        with self.assertRaises(ValueError):
            ca.carregar_precos(caminho)

    def test_preco_negativo(self):
        caminho = self.escrever({"modelos": {"x": {"input": -1}}})
        with self.assertRaises(ValueError):
            ca.carregar_precos(caminho)

    def test_preco_booleano(self):
        caminho = self.escrever({"modelos": {"x": {"input": True}}})
        with self.assertRaises(ValueError):
            ca.carregar_precos(caminho)

    def test_json_invalido(self):
        caminho = self.dir / "ruim.json"
        caminho.write_text("{", encoding="utf-8")
        with self.assertRaises(ValueError):
            ca.carregar_precos(caminho)

    def test_arquivo_inexistente(self):
        with self.assertRaises(ValueError):
            ca.carregar_precos(self.dir / "nao-existe.json")


class DiarioTest(unittest.TestCase):
    def quando(self, ano, mes, dia, hora=12):
        return int(datetime(ano, mes, dia, hora).timestamp() * 1000)

    def test_agrupa_e_ordena_por_dia(self):
        m = [
            msg(quando=self.quando(2026, 10, 2), entrada=10),
            msg(quando=self.quando(2026, 10, 1), entrada=20),
            msg(provider="ollama", quando=self.quando(2026, 10, 1), entrada=5),
        ]
        dias = ca.por_dia(m)
        self.assertEqual([d["data"] for d in dias], ["2026-10-01", "2026-10-02"])
        self.assertEqual(dias[0]["pago"].entrada, 20)
        self.assertEqual(dias[0]["local"].entrada, 5)
        self.assertEqual(dias[1]["pago"].msgs, 1)

    def test_tabela_mostra_travessao_sem_precos(self):
        texto = ca.secao_diario([msg(quando=self.quando(2026, 10, 1))])
        self.assertIn("DATA", texto)
        self.assertIn("2026-10-01", texto)
        self.assertIn("—", texto)

    def test_tabela_mostra_evitado_com_precos(self):
        precos = {"referencia": "pago", "preco": {
            "input": 10.0, "cache_read": 0.0, "cache_write": 0.0, "output": 0.0}}
        texto = ca.secao_diario(
            [msg(provider="ollama", entrada=100_000, quando=self.quando(2026, 10, 1))],
            precos,
        )
        self.assertIn("1.00", texto)

    def test_tendencia_ancora_no_ultimo_registro(self):
        m = [
            msg(quando=self.quando(2026, 10, 1), entrada=1_000),
            msg(quando=self.quando(2026, 10, 20), entrada=100),
        ]
        texto = ca.tendencia(m)
        self.assertIn("7 dias até 2026-10-20", texto)
        self.assertIn("→", texto)

    def test_tendencia_sem_data(self):
        self.assertIn("(nada)", ca.tendencia([msg(quando=0)]))


class GraficoTest(unittest.TestCase):
    PRECOS = {"referencia": "pago", "preco": {
        "input": 10.0, "cache_read": 0.0, "cache_write": 0.0, "output": 0.0}}

    def quando(self, dias_atras, hora=12):
        d = datetime.now().date() - timedelta(days=dias_atras)
        return int(datetime(d.year, d.month, d.day, hora).timestamp() * 1000)

    def linhas(self, texto):
        return [l for l in texto.splitlines()
                if l.strip()[:4].isdigit() and l.strip()[4:5] == "-"]

    def test_sem_mensagens(self):
        self.assertIn("sem uso", ca.secao_grafico([]))

    def test_janela_padrao_termina_hoje_com_7_linhas(self):
        texto = ca.secao_grafico([msg(quando=self.quando(0))])
        hoje = datetime.now().date()
        self.assertEqual(len(self.linhas(texto)), 7)
        self.assertIn(hoje.isoformat(), texto)
        self.assertIn((hoje - timedelta(days=6)).isoformat(), texto)
        self.assertNotIn((hoje - timedelta(days=7)).isoformat(), texto)

    def test_parametro_dias_define_a_janela(self):
        m = [msg(quando=self.quando(0))]
        self.assertEqual(len(self.linhas(ca.secao_grafico(m, dias=3))), 3)
        self.assertEqual(len(self.linhas(ca.secao_grafico(m, dias=14))), 14)

    def test_fora_da_janela_nao_aparece(self):
        m = [msg(quando=self.quando(10))]
        self.assertIn("sem uso nos últimos 7", ca.secao_grafico(m))
        alvo = (datetime.now().date() - timedelta(days=10)).isoformat()
        self.assertIn(alvo, ca.secao_grafico(m, dias=14))

    def test_serie_local_usa_escala_propria(self):
        m = [msg(quando=self.quando(1), provider="ollama", entrada=50_000),
             msg(quando=self.quando(1), entrada=5_000_000)]
        texto = ca.secao_grafico(m)
        self.assertIn("█" * 20, texto)  # o local enche a barra apesar do pago ser 100x maior

    def test_lista_modelos_locais_com_evitado(self):
        m = [
            msg(quando=self.quando(1), provider="ollama", entrada=50_000, modelo="gemma"),
            msg(quando=self.quando(1), provider="ollama", entrada=10_000, modelo="qwen"),
        ]
        texto = ca.secao_grafico(m, self.PRECOS)
        self.assertIn("POR MODELO LOCAL", texto)
        self.assertIn("gemma", texto)
        self.assertIn("qwen", texto)
        self.assertIn("0.50", texto)
        self.assertIn("0.10", texto)

    def test_tabela_por_modelo_respeita_a_janela(self):
        m = [
            msg(quando=self.quando(1), provider="ollama", modelo="recente"),
            msg(quando=self.quando(10), provider="ollama", modelo="antigo"),
        ]
        texto = ca.secao_grafico(m)
        self.assertIn("recente", texto)
        self.assertNotIn("antigo", texto)

    def test_sem_local_avisa(self):
        texto = ca.secao_grafico([msg(quando=self.quando(1))])
        self.assertIn("nenhum modelo local usado", texto)

    def test_dias_invalido_nao_quebra(self):
        texto = ca.secao_grafico([msg(quando=self.quando(0))], dias=0)
        self.assertEqual(len(self.linhas(texto)), 1)


class ExperimentosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def escrever(self, dados):
        caminho = self.dir / "exp.json"
        caminho.write_text(json.dumps(dados), encoding="utf-8")
        return caminho

    def test_aceita_tag_sem_datas(self):
        caminho = self.escrever([{"nome": "A", "tag": "[A]"}])
        exp = ca.carregar_experimentos(caminho)
        self.assertEqual(exp[0]["tag"], "[A]")
        self.assertIsNone(exp[0]["de"])

    def test_exige_janela_ou_tag(self):
        caminho = self.escrever([{"nome": "A"}])
        with self.assertRaises(ValueError):
            ca.carregar_experimentos(caminho)

    def test_data_invalida(self):
        caminho = self.escrever([{"nome": "A", "de": "01/10/2026"}])
        with self.assertRaises(ValueError):
            ca.carregar_experimentos(caminho)

    def test_intervalo_invertido(self):
        caminho = self.escrever([{"nome": "A", "de": "2026-10-10", "ate": "2026-10-01"}])
        with self.assertRaises(ValueError):
            ca.carregar_experimentos(caminho)

    def test_compara_janelas_e_calcula_delta(self):
        def quando(ano, mes, dia, hora=12):
            return int(datetime(ano, mes, dia, hora).timestamp() * 1000)

        m = [
            msg(entrada=1_000, sessao="s1", quando=quando(2026, 10, 1)),
            msg(entrada=100, sessao="s2", quando=quando(2026, 10, 10)),
        ]
        experimentos = [
            {"nome": "antes", "de": "2026-10-01", "ate": "2026-10-02", "nota": "sem local"},
            {"nome": "depois", "de": "2026-10-09", "ate": "2026-10-11", "nota": "com local"},
        ]
        texto = ca.comparar(m, {}, experimentos)
        self.assertIn("antes", texto)
        self.assertIn("depois", texto)
        self.assertIn("Δ contra 'antes'", texto)
        self.assertIn("-90.0%", texto)

    def test_compara_por_tag_de_sessao(self):
        m = [msg(sessao="s1"), msg(sessao="s2")]
        sessoes = {"s1": {"titulo": "[A] tarefa"}, "s2": {"titulo": "[B] tarefa"}}
        texto = ca.comparar(m, sessoes, [{"nome": "A", "tag": "[a]"}])
        self.assertIn("A", texto)
        self.assertIn("1", texto)

    def test_janela_vazia_avisa(self):
        texto = ca.comparar(
            [msg(quando=int(datetime(2026, 10, 1).timestamp() * 1000))],
            {}, [{"nome": "fora", "de": "2026-11-01", "ate": "2026-11-02"}],
        )
        self.assertIn("aviso: sem mensagens", texto)

    def test_variacao_com_base_zero_nao_mostra_infinito(self):
        self.assertEqual(ca._variacao(0, 5), "novo")
        self.assertEqual(ca._variacao(0, 0), "—")


class BancoTest(unittest.TestCase):
    """O banco do OpenCode é a fonte atual; o storage JSON é só fallback."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "opencode.db"
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE message (id TEXT, session_id TEXT, data TEXT)")
        con.execute("CREATE TABLE session (id TEXT, title TEXT, directory TEXT)")
        con.execute("CREATE TABLE session_v2 (id TEXT, title TEXT, directory TEXT)")
        con.execute("INSERT INTO session VALUES ('ses_x', 'Titulo legado', '/repo')")
        con.execute("INSERT INTO session_v2 VALUES ('ses_x', NULL, '/repo')")
        con.execute(
            "INSERT INTO message VALUES ('m1', 'ses_x', ?)",
            (json.dumps({
                "role": "assistant", "agent": "exec-local",
                "modelID": "gemma4", "providerID": "ollama",
                "path": {"cwd": "/repo"}, "time": {"created": 1000},
                "tokens": {"input": 10, "output": 5, "cache": {"read": 0, "write": 0}},
                "cost": 0,
            }),),
        )
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_le_do_banco(self):
        mensagens, sessoes = ca.carregar(self.dir)
        self.assertEqual(len(mensagens), 1)
        self.assertEqual(mensagens[0]["agente"], "exec-local")
        self.assertTrue(ca.eh_local(mensagens[0]))
        self.assertEqual(sessoes["ses_x"]["titulo"], "Titulo legado")  # session completa session_v2
        self.assertEqual(sessoes["ses_x"]["dir"], "/repo")

    def test_aceita_caminho_do_banco(self):
        mensagens, _ = ca.carregar(self.db)
        self.assertEqual(len(mensagens), 1)

    def test_banco_corrompido_cai_no_storage(self):
        self.db.write_bytes(b"isto nao e um banco")
        erro = io.StringIO()
        with contextlib.redirect_stderr(erro):
            mensagens, sessoes = ca.carregar(self.dir)
        self.assertEqual((mensagens, sessoes), ([], {}))
        self.assertIn("tentando storage", erro.getvalue())

    def test_sem_banco_usa_storage(self):
        self.db.unlink()
        pasta = self.dir / "message" / "ses_y"
        pasta.mkdir(parents=True)
        (pasta / "m.json").write_text(json.dumps({
            "role": "assistant", "agent": "local-helper",
            "modelID": "gemma4", "providerID": "ollama", "sessionID": "ses_y",
        }), encoding="utf-8")
        mensagens, _ = ca.carregar(self.dir)
        self.assertEqual(len(mensagens), 1)
        self.assertEqual(mensagens[0]["sessao"], "ses_y")


class BancoV2Test(unittest.TestCase):
    """V2 grava em `session_message` com `model` como objeto e cwd na sessão."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        con = sqlite3.connect(self.dir / "opencode.db")
        con.execute("CREATE TABLE session_v2 (id TEXT, title TEXT, directory TEXT)")
        con.execute("CREATE TABLE session_message (id TEXT, session_id TEXT, type TEXT,"
                    " time_created INTEGER, data TEXT)")
        con.execute("CREATE TABLE message (id TEXT, session_id TEXT, data TEXT)")
        con.execute("INSERT INTO session_v2 VALUES ('ses_v2', 'Titulo V2', '/repo2')")
        con.execute("INSERT INTO session_message VALUES ('m1', 'ses_v2', 'user', 900, '{}')")
        con.execute("INSERT INTO session_message VALUES ('m2', 'ses_v2', 'assistant', 1000, ?)", (
            json.dumps({
                "time": {"created": 1000},
                "agent": "exec-backend",
                "model": {"id": "gpt-x", "providerID": "openai"},
                "tokens": {"input": 10, "output": 5, "reasoning": 1,
                           "cache": {"read": 100, "write": 2}},
                "cost": 0.5,
            }),
        ))
        # legado V1 não pode ser somado junto
        con.execute("INSERT INTO message VALUES ('m3', 'ses_v1', ?)", (
            json.dumps({"role": "assistant", "agent": "build", "modelID": "velho",
                        "providerID": "openai", "tokens": {"input": 999}}),
        ))
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_le_session_message_e_ignora_v1(self):
        mensagens, sessoes = ca.carregar(self.dir)
        self.assertEqual(len(mensagens), 1)
        r = mensagens[0]
        self.assertEqual(r["agente"], "exec-backend")
        self.assertEqual(r["modelo"], "gpt-x")
        self.assertEqual(r["provider"], "openai")
        self.assertEqual(r["projeto"], "/repo2")
        self.assertEqual((r["entrada"], r["saida"], r["cache_lido"], r["cache_escrito"]),
                         (10, 5, 100, 2))
        self.assertEqual(r["custo"], 0.5)
        self.assertEqual(sessoes["ses_v2"]["titulo"], "Titulo V2")

    def test_local_no_v2(self):
        con = sqlite3.connect(self.dir / "opencode.db")
        con.execute("INSERT INTO session_message VALUES ('m4', 'ses_v2', 'assistant', 1100, ?)", (
            json.dumps({"time": {"created": 1100}, "agent": "exec-local",
                        "model": {"id": "gemma4", "providerID": "Ollama"},
                        "tokens": {"input": 7, "output": 3, "cache": {}}}),
        ))
        con.commit()
        con.close()
        mensagens, _ = ca.carregar(self.dir)
        local = [m for m in mensagens if ca.eh_local(m)]
        self.assertEqual(len(local), 1)
        self.assertEqual(local[0]["modelo"], "gemma4")

    def test_compaction_conta_quando_a_resposta_fica_vazia(self):
        """Sessão interrompida: o assistente fica sem tokens e o uso só existe na compaction."""
        con = sqlite3.connect(self.dir / "opencode.db")
        con.execute("INSERT INTO session_v2 VALUES ('ses_v3', 'Interrompida', '/repo3')")
        con.execute("INSERT INTO session_message VALUES ('c0', 'ses_v3', 'assistant', 1200, ?)", (
            json.dumps({"time": {"created": 1200}, "agent": "local-helper",
                        "model": {"id": "gemma4", "providerID": "ollama"},
                        "content": []}),
        ))
        con.execute("INSERT INTO session_message VALUES ('c1', 'ses_v3', 'compaction', 1300, ?)", (
            json.dumps({"time": {"created": 1300}, "reason": "auto", "status": "completed",
                        "model": {"id": "gemma4", "providerID": "ollama"},
                        "tokens": {"input": 786, "output": 221, "reasoning": 0,
                                   "cache": {"read": 8007, "write": 0}},
                        "cost": 0}),
        ))
        con.commit()
        con.close()
        mensagens, _ = ca.carregar(self.dir)
        da_sessao = [m for m in mensagens if m["sessao"] == "ses_v3"]
        compactacao = [m for m in da_sessao if m["agente"] == "(compaction)"]
        self.assertEqual(len(compactacao), 1)
        self.assertTrue(ca.eh_local(compactacao[0]))
        self.assertEqual(compactacao[0]["projeto"], "/repo3")
        self.assertEqual((compactacao[0]["entrada"], compactacao[0]["saida"],
                          compactacao[0]["cache_lido"]), (786, 221, 8007))
        self.assertEqual(ca.somar(da_sessao).entrada, 786)
        self.assertEqual(ca.somar([m for m in mensagens if m["sessao"] == "ses_v2"]).entrada, 10)

    def test_sessao_vazia_sem_compaction_nao_inventa_uso(self):
        con = sqlite3.connect(self.dir / "opencode.db")
        con.execute("INSERT INTO session_v2 VALUES ('ses_v4', 'Abortada', '/repo4')")
        con.execute("INSERT INTO session_message VALUES ('d0', 'ses_v4', 'assistant', 1400, ?)", (
            json.dumps({"time": {"created": 1400}, "agent": "local-helper",
                        "model": {"id": "gemma4", "providerID": "ollama"},
                        "content": []}),
        ))
        con.commit()
        con.close()
        mensagens, _ = ca.carregar(self.dir)
        da_sessao = [m for m in mensagens if m["sessao"] == "ses_v4"]
        self.assertEqual(len(da_sessao), 1)
        self.assertEqual(ca.contexto(ca.somar(da_sessao)), 0)


class TabelaPrecosTest(unittest.TestCase):
    PRECOS = {"referencia": "pago", "preco": {
        "input": 10.0, "cache_read": 0.0, "cache_write": 0.0, "output": 0.0}}

    def test_coluna_evitado_so_aparece_com_precos(self):
        linhas = ca.agregar(
            [msg(provider="ollama", entrada=100_000)], lambda m: (m["agente"], m["modelo"])
        )
        self.assertNotIn("EVITADO", ca.tabela(linhas))
        texto = ca.tabela(linhas, precos=self.PRECOS)
        self.assertIn("EVITADO", texto)
        self.assertIn("1.00", texto)

    def test_linha_paga_nao_atribui_economia(self):
        linhas = ca.agregar(
            [msg(provider="google", entrada=100_000)], lambda m: (m["agente"], m["modelo"])
        )
        self.assertIn("—", ca.tabela(linhas, precos=self.PRECOS))

    def test_relatorio_repassa_precos(self):
        texto = ca.relatorio([msg(provider="ollama", entrada=100_000)], {}, precos=self.PRECOS)
        self.assertIn("EVITADO", texto)


class PrincipalTest(unittest.TestCase):
    """Integração: histórico sintético no disco -> relatório completo."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        sessao = self.base / "message" / "ses_x"
        sessao.mkdir(parents=True)
        quando = int(datetime(2026, 10, 1, 12).timestamp() * 1000)
        for i, (provider, entrada) in enumerate((("google", 500_000), ("ollama", 25_000))):
            (sessao / f"msg_{i}.json").write_text(json.dumps({
                "role": "assistant", "agent": "exec-local" if provider == "ollama" else "plan",
                "modelID": "m", "providerID": provider, "sessionID": "ses_x",
                "path": {"cwd": "/tmp/p"}, "time": {"created": quando},
                "tokens": {"input": entrada, "output": 1000,
                           "cache": {"read": 0, "write": 0}},
                "cost": 0,
            }), encoding="utf-8")
        self.precos = self.base / "precos.json"
        self.precos.write_text(json.dumps({
            "referencia": "pago",
            "modelos": {"pago": {"input": 10, "output": 20}},
        }), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def rodar(self, *args):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = ca.principal(["--storage", str(self.base), "--todos", *args])
        return codigo, saida.getvalue()

    def test_relatorio_padrao_traz_economia(self):
        codigo, texto = self.rodar()
        self.assertEqual(codigo, 0)
        self.assertIn("POR AGENTE", texto)
        self.assertIn("ECONOMIA", texto)
        self.assertIn("(4.8% do total)", texto)

    def test_economia_com_precos_usa_referencia(self):
        codigo, texto = self.rodar("--economia", "--precos", str(self.precos))
        self.assertEqual(codigo, 0)
        self.assertIn("referência: pago", texto)
        self.assertIn("US$ 0.27", texto)  # 25.000 * 10/1M + 1.000 * 20/1M

    def test_diario_no_json(self):
        codigo, texto = self.rodar("--json")
        self.assertEqual(codigo, 0)
        dados = json.loads(texto)
        self.assertEqual(len(dados["diario"]), 1)
        self.assertEqual(dados["diario"][0]["data"], "2026-10-01")
        self.assertIn("economia", dados)

    def test_grafico_no_modo_economia(self):
        codigo, texto = self.rodar("--economia", "--grafico", "--dias", "60")
        self.assertEqual(codigo, 0)
        self.assertIn("USO POR DIA", texto)
        self.assertIn("POR MODELO LOCAL", texto)

    def test_projeto_explicito_vence_todos(self):
        codigo, _ = self.rodar("--todos", "--projeto", "/tmp/p", "--economia")
        self.assertEqual(codigo, 0)
        codigo, _ = self.rodar("--todos", "--projeto", "/tmp/outro", "--economia")
        self.assertEqual(codigo, 1)

    def test_precos_invalido_sai_com_erro(self):
        ruim = self.base / "ruim.json"
        ruim.write_text("[]", encoding="utf-8")
        codigo, texto = self.rodar("--precos", str(ruim))
        self.assertEqual(codigo, 2)
        self.assertEqual(texto, "")


if __name__ == "__main__":
    unittest.main()
