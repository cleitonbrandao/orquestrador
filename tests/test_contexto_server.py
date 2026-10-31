"""Testes do servidor MCP do Context Manager. Sem rede e sem stdio real."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Importa por caminho: `test_decisao_server.py` já registra um módulo chamado
# `server` em sys.modules, e dois arquivos com o mesmo nome colidem.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "contexto_server", os.path.join(RAIZ, "mcp", "contexto", "server.py")
)
srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srv)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "projeto"
        self.root.mkdir()
        (self.root / "app").mkdir()
        (self.root / "app" / "a.py").write_text("um\ndois\ntres\n", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN=1\n", encoding="utf-8")
        self.estado = Path(self.tmp.name) / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def memoria(self, regras=None, decisoes=None):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.estado)}):
            pasta = srv.cm.pasta_memoria(self.root)
        pasta.mkdir(parents=True)
        if regras is not None:
            (pasta / "business_rules.json").write_text(
                json.dumps({"rules": regras}), encoding="utf-8")
        if decisoes is not None:
            (pasta / "decisions.json").write_text(
                json.dumps({"decisions": decisoes}), encoding="utf-8")
        return pasta


class ArquivoTest(Base):
    def test_le_com_numero_de_linha(self):
        r = srv.context_get_file({"path": "app/a.py", "root": str(self.root)})
        self.assertEqual(r["start"], 1)
        self.assertEqual(r["total_lines"], 3)
        self.assertIn("1| um", r["text"])
        self.assertIn("3| tres", r["text"])

    def test_recorta_intervalo(self):
        r = srv.context_get_file({"path": "app/a.py", "start": 2, "end": 2, "root": str(self.root)})
        self.assertEqual(r["text"], "    2| dois")

    def test_recusa_dotenv(self):
        with self.assertRaises(srv.ContextoServerError):
            srv.context_get_file({"path": ".env", "root": str(self.root)})

    def test_recusa_fora_da_raiz(self):
        with self.assertRaises(srv.ContextoServerError):
            srv.context_get_file({"path": "../fora.py", "root": str(self.root)})

    def test_arquivo_inexistente(self):
        with self.assertRaises(srv.ContextoServerError):
            srv.context_get_file({"path": "app/b.py", "root": str(self.root)})


class MemoriaTest(Base):
    def test_regras_e_filtro_por_prioridade(self):
        self.memoria(regras=[
            {"id": "a", "priority": "P0", "text": "team_id"},
            {"id": "b", "priority": "P1", "text": "inertia"},
        ])
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.estado)}):
            todas = srv.context_get_rules({"root": str(self.root)})
            p0 = srv.context_get_rules({"root": str(self.root), "priority": "p0"})
        self.assertEqual(todas["count"], 2)
        self.assertEqual(p0["count"], 1)
        self.assertEqual(p0["rules"][0]["id"], "a")

    def test_decisoes_filtradas_por_consulta(self):
        self.memoria(decisoes=[
            {"id": "D1", "description": "grafo do fluxo", "files": []},
            {"id": "D2", "description": "indices de vendas", "files": []},
        ])
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.estado)}):
            r = srv.context_get_decisions({"root": str(self.root), "query": "grafo"})
        self.assertEqual([d["id"] for d in r["decisions"]], ["D1"])

    def test_sem_memoria_nao_falha(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.estado)}):
            self.assertEqual(srv.context_get_rules({"root": str(self.root)})["count"], 0)


class ValidarTest(Base):
    def test_valida_pacote_por_objeto(self):
        pacote = {"relevant_files": [{"path": "app/a.py"}],
                  "source_references": [], "missing_information": []}
        r = srv.context_validate({"package": pacote, "root": str(self.root)})
        self.assertTrue(r["relevant_files"][0]["confirmed"])
        self.assertEqual(r["validation"]["pending"], 0)

    def test_valida_pacote_por_arquivo(self):
        caminho = self.root / "pacote.json"
        caminho.write_text(json.dumps({"relevant_files": [{"path": "app/nao.py"}]}),
                           encoding="utf-8")
        r = srv.context_validate({"path": str(caminho), "root": str(self.root)})
        self.assertEqual(r["validation"]["pending"], 1)

    def test_sem_pacote_falha(self):
        with self.assertRaises(srv.ContextoServerError):
            srv.context_validate({"root": str(self.root)})


class BuildTest(Base):
    def test_dry_run_monta_pacote_sem_rede(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.estado)}), \
                mock.patch.object(srv.cl, "resumir") as resumir:
            pacote = srv.context_build({
                "task": "o que tem no arquivo?", "files": ["app/a.py"],
                "root": str(self.root), "dry_run": True,
            })
        resumir.assert_not_called()
        self.assertEqual(pacote["task"], "o que tem no arquivo?")
        for chave in srv.cp.CHAVES:
            self.assertIn(chave, pacote)
        self.assertTrue(pacote["dry_run"])
        self.assertIn("app/a.py", pacote["prompt"])

    def test_build_com_memoria_seleciona_regras(self):
        self.memoria(regras=[
            {"id": "p0", "priority": "P0", "text": "seguranca sempre"},
            {"id": "p1", "priority": "P1", "text": "regra de css", "applies_to": ["*.css"]},
        ])
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.estado)}):
            pacote = srv.context_build({
                "task": "ler o arquivo", "files": ["app/a.py"],
                "root": str(self.root), "dry_run": True,
            })
        self.assertEqual(pacote["critical_rules"], ["P0 · seguranca sempre"])

    def test_build_sem_arquivos_falha(self):
        with self.assertRaises(srv.ContextoServerError):
            srv.context_build({"task": "x", "root": str(self.root)})

    def test_build_sem_task_falha(self):
        with self.assertRaises(srv.ContextoServerError):
            srv.context_build({"files": ["app/a.py"], "root": str(self.root)})

    def test_segundo_build_igual_usa_cache(self):
        falso = {"texto": "alfa", "entrada": 10, "saida": 5, "duracao": 1.0}
        args = {"task": "o que tem?", "files": ["app/a.py"], "root": str(self.root)}
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.estado)}), \
                mock.patch.object(srv.cl, "resumir", return_value=falso) as resumir:
            primeiro = srv.context_build(dict(args))
            segundo = srv.context_build(dict(args))
        self.assertEqual(resumir.call_count, 1, "o segundo build não devia chamar o modelo")
        self.assertFalse(primeiro.get("cached", False))
        self.assertTrue(segundo["cached"])

    def test_build_muda_de_arquivo_nao_usa_cache(self):
        falso = {"texto": "ok", "entrada": 10, "saida": 5, "duracao": 1.0}
        (self.root / "app" / "b.py").write_text("outro\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.estado)}), \
                mock.patch.object(srv.cl, "resumir", return_value=falso) as resumir:
            srv.context_build({"task": "t", "files": ["app/a.py"], "root": str(self.root)})
            srv.context_build({"task": "t", "files": ["app/b.py"], "root": str(self.root)})
        self.assertEqual(resumir.call_count, 2)

    def test_perfil_define_orcamento(self):
        grande = self.root / "app" / "grande.py"
        grande.write_text("\n".join(f"linha {i} " + "x" * 60 for i in range(400)), encoding="utf-8")
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.estado)}):
            rapida = srv.context_build({"task": "t", "files": ["app/grande.py"],
                                        "root": str(self.root), "dry_run": True,
                                        "profile": "rapida"})
            completa = srv.context_build({"task": "t", "files": ["app/grande.py"],
                                          "root": str(self.root), "dry_run": True,
                                          "profile": "completa"})
        self.assertLess(rapida["context_metrics"]["original_tokens"],
                        completa["context_metrics"]["original_tokens"])
        self.assertTrue(rapida["relevant_files"][0]["truncated"])

    def test_max_total_sobrepoe_o_perfil(self):
        grande = self.root / "app" / "grande.py"
        grande.write_text("\n".join(f"linha {i} " + "x" * 60 for i in range(400)), encoding="utf-8")
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.estado)}):
            pequeno = srv.context_build({"task": "t", "files": ["app/grande.py"],
                                         "root": str(self.root), "dry_run": True,
                                         "profile": "completa", "max_total": 2000})
        self.assertLess(pequeno["context_metrics"]["original_tokens"], 600)

    def test_perfil_invalido_falha(self):
        with self.assertRaises(srv.ContextoServerError):
            srv.context_build({"task": "t", "files": ["app/a.py"],
                               "root": str(self.root), "profile": "turbo"})

    def test_orcamento_de_regras_omite_p1_e_avisa(self):
        self.memoria(regras=[
            {"id": "p0", "priority": "P0", "text": "seguranca sempre"},
            {"id": "p1", "priority": "P1", "text": "leitura " + "regra longa " * 200},
        ])
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.estado)}):
            pacote = srv.context_build({"task": "leitura do arquivo", "files": ["app/a.py"],
                                        "root": str(self.root), "dry_run": True})
        self.assertEqual(pacote["critical_rules"], ["P0 · seguranca sempre"])
        self.assertIn("fora do pacote", pacote["memory_note"])


class BuscaTest(Base):
    def test_usa_o_kb_quando_responde(self):
        import types
        stub = types.SimpleNamespace(search=lambda app, q, k: [{"path": "x", "score": 1}])
        with mock.patch.dict(sys.modules, {"kb": stub}):
            r = srv.context_search({"query": "team_id", "root": str(self.root)})
        self.assertEqual(r["source"], "kb")
        self.assertEqual(r["count"], 1)

    def test_cai_no_fallback_quando_o_kb_falha(self):
        import types

        def explode(*_a, **_k):
            raise RuntimeError("sem índice")

        (self.root / "app" / "busca.py").write_text("team_id aqui\n", encoding="utf-8")
        with mock.patch.dict(sys.modules, {"kb": types.SimpleNamespace(search=explode)}):
            r = srv.context_search({"query": "team_id", "root": str(self.root)})
        self.assertEqual(r["source"], "fallback")
        self.assertIn("app/busca.py", [a["path"] for a in r["results"]])
        self.assertIn("kb indisponível", r["note"])

    def test_fallback_quando_o_kb_devolve_vazio(self):
        import types
        (self.root / "app" / "vazio.py").write_text("achado raro\n", encoding="utf-8")
        with mock.patch.dict(sys.modules, {"kb": types.SimpleNamespace(search=lambda *a: [])}):
            r = srv.context_search({"query": "achado", "root": str(self.root)})
        self.assertEqual(r["source"], "fallback")
        self.assertEqual(r["count"], 1)


class MetricasTest(Base):
    def test_sem_arquivo(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.estado)}):
            r = srv.context_metrics({})
        self.assertEqual(r["runs"], 0)

    def test_agrega_registros(self):
        pasta = self.estado / "orquestrador" / "contexto"
        pasta.mkdir(parents=True)
        with (pasta / "metrics.jsonl").open("w", encoding="utf-8") as f:
            f.write(json.dumps({"reduction_percentage": 80, "prompt_tokens": 100,
                                "compressed_tokens": 20, "pending": 0}) + "\n")
            f.write(json.dumps({"reduction_percentage": 60, "prompt_tokens": 50,
                                "compressed_tokens": 20, "pending": 1}) + "\n")
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.estado)}):
            r = srv.context_metrics({})
        self.assertEqual(r["runs"], 2)
        self.assertEqual(r["avg_reduction_percentage"], 70.0)
        self.assertEqual(r["total_prompt_tokens"], 150)
        self.assertEqual(r["pending"], 1)


class ProtocoloTest(Base):
    def capturar(self, msg):
        import io
        saida = io.StringIO()
        with mock.patch.object(srv.sys, "stdout", saida):
            srv.handle(msg)
        return json.loads(saida.getvalue())

    def test_initialize(self):
        r = self.capturar({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(r["result"]["serverInfo"]["name"], "orq-contexto")

    def test_tools_list_tem_as_sete(self):
        r = self.capturar({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        nomes = {t["name"] for t in r["result"]["tools"]}
        self.assertEqual(nomes, {
            "context_build", "context_get_file", "context_get_rules",
            "context_get_decisions", "context_validate", "context_metrics",
            "context_search",
        })

    def test_tool_desconhecida(self):
        r = self.capturar({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                           "params": {"name": "nao_existe"}})
        self.assertEqual(r["error"]["code"], -32602)

    def test_erro_de_uso_vira_iserror(self):
        r = self.capturar({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                           "params": {"name": "context_get_file", "arguments": {"path": ".env"}}})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("recusado", r["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
