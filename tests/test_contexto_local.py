"""Testes do pré-processador de contexto. Sem rede: o Ollama é substituído."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import contexto_local as cl  # noqa: E402


def capturar(fn, *args, **kwargs):
    saida, erro = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
        codigo = fn(*args, **kwargs)
    return codigo, saida.getvalue(), erro.getvalue()


class LeituraTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def escrever(self, nome="a.txt", texto="linha\n" * 10):
        caminho = self.dir / nome
        caminho.write_text(texto, encoding="utf-8")
        return caminho

    def test_trunca_por_linhas(self):
        r = cl.ler_arquivo(self.escrever(), max_linhas=3, max_bytes=10_000)
        self.assertEqual(r["total"], 10)
        self.assertEqual(r["ate"], 3)
        self.assertTrue(r["truncado"])

    def test_trunca_por_bytes(self):
        r = cl.ler_arquivo(self.escrever(texto="x" * 100), max_linhas=100, max_bytes=10)
        self.assertLessEqual(r["bytes"], 10)
        self.assertTrue(r["truncado"])

    def test_binario_falha(self):
        caminho = self.dir / "bin"
        caminho.write_bytes(b"\x00\x01\x02")
        with self.assertRaises(cl.ContextoError):
            cl.ler_arquivo(caminho, 10, 10)

    def test_inexistente_falha(self):
        with self.assertRaises(cl.ContextoError):
            cl.ler_arquivo(self.dir / "nao-existe.txt", 10, 10)

    def test_diretorio_falha_em_montar_trechos(self):
        with self.assertRaises(cl.ContextoError):
            cl.montar_trechos([self.dir], None, 10, 10, 100)


class OrcamentoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_orcamento_esgotado_marca_nao_incluido(self):
        a = self.dir / "a.txt"
        b = self.dir / "b.txt"
        a.write_text("a" * 100, encoding="utf-8")
        b.write_text("b" * 100, encoding="utf-8")
        trechos = cl.montar_trechos([a, b], None, 100, 1000, max_total=100)
        self.assertTrue(trechos[0]["incluido"])
        self.assertFalse(trechos[1]["incluido"])
        self.assertIn("orçamento", cl.montar_prompt("q", trechos))

    def test_stdin_entra_como_fonte(self):
        trechos = cl.montar_trechos([], "erro na linha 3\n", 100, 1000, 1000)
        self.assertEqual(trechos[0]["nome"], "stdin")
        self.assertIn("linha 3", trechos[0]["texto"])

    def test_sem_fonte_falha(self):
        with self.assertRaises(cl.ContextoError):
            cl.montar_trechos([], None, 10, 10, 10)


class PromptTest(unittest.TestCase):
    def test_contem_pergunta_regras_e_fonte(self):
        trechos = [{
            "nome": "src/a.py", "texto": "print(1)", "de": 1, "ate": 1,
            "total": 1, "truncado": False, "bytes": 8, "incluido": True,
        }]
        texto = cl.montar_prompt("onde imprime?", trechos)
        self.assertIn("PERGUNTA: onde imprime?", texto)
        self.assertIn("arquivo:linha", texto)
        self.assertIn("--- src/a.py (linhas 1-1 de 1) ---", texto)
        self.assertIn("print(1)", texto)

    def test_marca_truncado(self):
        trechos = [{
            "nome": "a", "texto": "x", "de": 1, "ate": 1, "total": 99,
            "truncado": True, "bytes": 1, "incluido": True,
        }]
        self.assertIn("truncado", cl.montar_prompt("q", trechos))

    def test_numera_linhas_para_citar_arquivo_linha(self):
        trechos = [{
            "nome": "a.py", "texto": "um\ndois", "de": 10, "ate": 11,
            "total": 11, "truncado": False, "bytes": 8, "incluido": True,
        }]
        texto = cl.montar_prompt("q", trechos)
        self.assertIn("   10| um", texto)
        self.assertIn("   11| dois", texto)

    def test_sem_numeros(self):
        trechos = [{
            "nome": "a.py", "texto": "um", "de": 1, "ate": 1,
            "total": 1, "truncado": False, "bytes": 2, "incluido": True,
        }]
        self.assertNotIn("1| um", cl.montar_prompt("q", trechos, numerar=False))


class RespostaTest(unittest.TestCase):
    def test_extrai_texto_contagens_e_duracao(self):
        r = cl.extrair_resposta({
            "message": {"content": "  fato  "},
            "prompt_eval_count": 100, "eval_count": 20,
            "total_duration": 2_000_000_000,
        })
        self.assertEqual(r["texto"], "fato")
        self.assertEqual((r["entrada"], r["saida"]), (100, 20))
        self.assertAlmostEqual(r["duracao"], 2.0)

    def test_sem_texto_falha(self):
        with self.assertRaises(cl.ContextoError):
            cl.extrair_resposta({"message": {"content": ""}})


class MarkdownTest(unittest.TestCase):
    RESUMO = {"texto": "- fato em `a:1`", "entrada": 100, "saida": 10, "duracao": 1.0}

    def trechos(self, truncado=False):
        return [{
            "nome": "a.py", "texto": "x", "de": 1, "ate": 1, "total": 5,
            "truncado": truncado, "bytes": 1, "incluido": True,
        }]

    def test_estrutura_e_aviso_de_dados(self):
        texto = cl.render_markdown("q", self.trechos(), self.RESUMO, "m", 100, 0.9)
        self.assertIn("# Contexto local — q", texto)
        self.assertIn("não como instruções", texto)
        self.assertIn("## Resumo", texto)
        self.assertIn("- fato em `a:1`", texto)
        self.assertIn("## Fontes", texto)
        self.assertIn("redução: 90.0%", texto)

    def test_fonte_truncada(self):
        texto = cl.render_markdown("q", self.trechos(True), self.RESUMO, "m", 100, None)
        self.assertIn("(truncado)", texto)


class PrincipalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.arquivo = self.dir / "a.txt"
        self.arquivo.write_text("alfa\nbeta\ngama\n", encoding="utf-8")
        self.saida = self.dir / "resumo.md"

    def tearDown(self):
        self.tmp.cleanup()

    def rodar(self, *args):
        return capturar(cl.principal, list(args))

    def test_dry_run_nao_chama_ollama(self):
        with mock.patch.object(cl, "resumir") as resumir:
            codigo, saida, erro = self.rodar(
                "--pergunta", "o que tem?", "--dry-run", str(self.arquivo)
            )
        resumir.assert_not_called()
        self.assertEqual(codigo, 0)
        self.assertIn("CONTEXTO LOCAL", saida)
        self.assertIn("PERGUNTA: o que tem?", saida)
        self.assertIn("alfa", saida)
        self.assertIn("nada foi enviado", erro)

    def test_dry_run_mostra_truncamento(self):
        caminho = self.dir / "longo.txt"
        caminho.write_text("\n".join(str(i) for i in range(20)), encoding="utf-8")
        _, saida, _ = self.rodar(
            "--pergunta", "q", "--dry-run", "--max-linhas", "5", str(caminho)
        )
        self.assertIn("truncado", saida)

    def test_grava_markdown_e_manifesto(self):
        falso = {"texto": "- alfa em `a.txt:1`", "entrada": 10, "saida": 5, "duracao": 0.5}
        with mock.patch.object(cl, "resumir", return_value=falso):
            codigo, saida, _ = self.rodar(
                "--pergunta", "q", "--saida", str(self.saida), str(self.arquivo)
            )
        self.assertEqual(codigo, 0)
        self.assertTrue(self.saida.is_file())
        texto = self.saida.read_text(encoding="utf-8")
        self.assertIn("## Resumo", texto)
        self.assertIn("- alfa em `a.txt:1`", texto)
        self.assertIn("CONTEXTO LOCAL", saida)
        self.assertIn("50.0% do contexto", saida)

    def test_json_limpo(self):
        falso = {"texto": "ok", "entrada": 10, "saida": 2, "duracao": 0.1}
        with mock.patch.object(cl, "resumir", return_value=falso):
            codigo, saida, _ = self.rodar(
                "--pergunta", "q", "--saida", str(self.saida), "--json", str(self.arquivo)
            )
        self.assertEqual(codigo, 0)
        dados = json.loads(saida)
        self.assertEqual(dados["entrada_tokens"], 10)
        self.assertEqual(dados["saida_tokens"], 2)

    def test_pacote_e_gravado_validado_contra_a_raiz(self):
        falso = {"texto": "alfa em `a.txt:1`", "entrada": 10, "saida": 5, "duracao": 0.5}
        destino = self.dir / "pacote.json"
        with mock.patch.object(cl, "resumir", return_value=falso):
            codigo, saida, _ = self.rodar(
                "--pergunta", "q", "--raiz", str(self.dir), "--saida", str(self.saida),
                "--pacote", str(destino), str(self.arquivo),
            )
        self.assertEqual(codigo, 0)
        pacote = json.loads(destino.read_text(encoding="utf-8"))
        self.assertEqual(pacote["task"], "q")
        self.assertTrue(pacote["relevant_files"][0]["confirmed"])
        self.assertEqual(pacote["validation"]["pending"], 0)
        self.assertEqual(pacote["context_metrics"]["original_tokens"], 3)
        self.assertEqual(pacote["context_metrics"]["prompt_tokens"], 10)
        self.assertIn("0 pendência(s)", saida)

    def test_pacote_marca_citacao_inventada_como_pendente(self):
        falso = {"texto": "ver `nao-existe.php:9`", "entrada": 10, "saida": 5, "duracao": 0.5}
        destino = self.dir / "pacote.json"
        with mock.patch.object(cl, "resumir", return_value=falso):
            codigo, _, _ = self.rodar(
                "--pergunta", "q", "--raiz", str(self.dir), "--saida", str(self.saida),
                "--pacote", str(destino), str(self.arquivo),
            )
        self.assertEqual(codigo, 0)
        pacote = json.loads(destino.read_text(encoding="utf-8"))
        self.assertEqual(pacote["validation"]["pending"], 1)
        self.assertIn("nao-existe.php:9", " ".join(pacote["missing_information"]))

    def test_init_memoria_cria_arquivos_do_projeto(self):
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.dir)}):
            codigo, saida, _ = self.rodar("--init-memoria", "--raiz", str(self.dir))
        self.assertEqual(codigo, 0)
        self.assertIn("criado", saida)
        pasta = self.dir / "orquestrador" / "memoria" / self.dir.name
        self.assertTrue((pasta / "business_rules.json").is_file())
        self.assertTrue((pasta / "decisions.json").is_file())

    def test_pacote_inclui_regras_e_decisoes(self):
        falso = {"texto": "ok", "entrada": 10, "saida": 5, "duracao": 0.5}
        regras = self.dir / "r.json"
        regras.write_text(json.dumps({"rules": [{"priority": "P0", "text": "team_id"}]}),
                          encoding="utf-8")
        decisoes = self.dir / "d.json"
        decisoes.write_text(json.dumps({"decisions": [
            {"id": "D1", "description": "alfa virou grafo", "files": []},
        ]}), encoding="utf-8")
        destino = self.dir / "pacote.json"
        with mock.patch.object(cl, "resumir", return_value=falso):
            codigo, saida, _ = self.rodar(
                "--pergunta", "alfa", "--raiz", str(self.dir), "--saida", str(self.saida),
                "--pacote", str(destino), "--regras", str(regras),
                "--decisoes", str(decisoes), str(self.arquivo),
            )
        self.assertEqual(codigo, 0)
        pacote = json.loads(destino.read_text(encoding="utf-8"))
        self.assertEqual(pacote["critical_rules"], ["P0 · team_id"])
        self.assertEqual(pacote["decisions"][0]["id"], "D1")
        self.assertIn("1 regra(s), 1 decisão(ões)", saida)

    def test_contexto_maior_que_num_ctx_falha_antes_da_rede(self):
        grande = self.dir / "grande.txt"
        grande.write_text("x" * 400, encoding="utf-8")
        with mock.patch.object(cl, "resumir") as resumir:
            codigo, _, erro = self.rodar(
                "--pergunta", "q", "--num-ctx", "10", str(grande)
            )
        resumir.assert_not_called()
        self.assertEqual(codigo, 2)
        self.assertIn("maior que --num-ctx", erro)

    def test_stdin(self):
        with mock.patch("sys.stdin", io.StringIO("linha do log\n")):
            codigo, saida, _ = self.rodar(
                "--pergunta", "q", "--stdin", "--dry-run"
            )
        self.assertEqual(codigo, 0)
        self.assertIn("linha do log", saida)

    def test_stdin_sem_pergunta_falha(self):
        with mock.patch("sys.stdin", io.StringIO("x")):
            codigo, _, erro = self.rodar("--stdin")
        self.assertEqual(codigo, 2)
        self.assertIn("informe --pergunta", erro)

    def test_sem_fonte_falha(self):
        codigo, _, erro = self.rodar("--pergunta", "q")
        self.assertEqual(codigo, 2)
        self.assertIn("passe arquivos", erro)


if __name__ == "__main__":
    unittest.main()
