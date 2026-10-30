"""Testes do pacote de contexto (roadmap §6) e do validador (§4.4). Sem rede."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import contexto_pacote as cp  # noqa: E402


def trecho(nome, texto, de=1, truncado=False, incluido=True):
    linhas = texto.splitlines()
    return {
        "nome": nome,
        "texto": texto,
        "de": de,
        "ate": de + len(linhas) - 1 if linhas else 0,
        "total": len(linhas),
        "truncado": truncado,
        "bytes": len(texto.encode("utf-8")),
        "incluido": incluido,
    }


class MontarTest(unittest.TestCase):
    def test_tem_todas_as_chaves_do_roadmap(self):
        pacote = cp.montar("pergunta", [trecho("a.py", "x = 1\n")])
        for chave in cp.CHAVES:
            self.assertIn(chave, pacote, f"faltou {chave}")

    def test_metricas_usam_bytes_lidos_e_tokens_de_saida(self):
        pacote = cp.montar(
            "t", [trecho("a.py", "x" * 4000)], {"texto": "ok", "saida": 100, "duracao": 2.0}
        )
        m = pacote["context_metrics"]
        self.assertEqual(m["original_tokens"], 1000)
        self.assertEqual(m["compressed_tokens"], 100)
        self.assertEqual(m["reduction_percentage"], 90.0)
        self.assertEqual(m["seconds"], 2.0)

    def test_sem_resumo_nao_inventa_tokens(self):
        m = cp.montar("t", [trecho("a.py", "abcd")])["context_metrics"]
        self.assertEqual(m["compressed_tokens"], 0)
        self.assertEqual(m["reduction_percentage"], 0.0)

    def test_arquivo_nao_incluido_fica_fora_do_pacote(self):
        pacote = cp.montar(
            "t", [trecho("a.py", "x"), trecho("b.py", "y", incluido=False)]
        )
        self.assertEqual([a["path"] for a in pacote["relevant_files"]], ["a.py"])

    def test_truncamento_e_linhas_aparecem_no_arquivo(self):
        pacote = cp.montar("t", [trecho("a.py", "1\n2\n3", de=4, truncado=True)])
        arq = pacote["relevant_files"][0]
        self.assertTrue(arq["truncated"])
        self.assertEqual(arq["lines"], "4-6")

    def test_citacoes_do_resumo_viram_source_references(self):
        pacote = cp.montar("t", [trecho("a.py", "x")], {"texto": "ver a.py:12 e b.py"})
        refs = [r["ref"] for r in pacote["source_references"]]
        self.assertEqual(refs, ["a.py:1-1", "a.py:12", "b.py"])

    def test_json_do_modelo_e_mesclado(self):
        texto = 'Resumo\n```json\n{"critical_rules": ["team_id"], "dependencies": ["Sale"]}\n```'
        pacote = cp.montar("t", [trecho("a.py", "x")], {"texto": texto})
        self.assertEqual(pacote["critical_rules"], ["team_id"])
        self.assertEqual(pacote["dependencies"], ["Sale"])

    def test_json_invalido_ou_ausente_nao_quebra(self):
        for texto in ("sem bloco", "```json\n{nao}\n```", "```json\n[1,2]\n```"):
            pacote = cp.montar("t", [trecho("a.py", "x")], {"texto": texto})
            self.assertEqual(pacote["critical_rules"], [], texto)

    def test_regras_entram_verbatim_e_vencem_o_modelo(self):
        texto = '```json\n{"critical_rules": ["inventada pelo modelo"]}\n```'
        pacote = cp.montar(
            "t", [trecho("a.py", "x")], {"texto": texto},
            regras=[{"id": "R1", "priority": "P0", "text": "toda consulta respeita team_id"}],
        )
        self.assertEqual(pacote["critical_rules"], ["P0 · toda consulta respeita team_id"])

    def test_decisoes_entram_no_pacote(self):
        decisoes = [{"id": "D1", "description": "grafo substitui PhaseTrail", "rationale": "",
                     "files": [], "date": "", "status": "aceita", "references": []}]
        pacote = cp.montar("t", [trecho("a.py", "x")], decisoes=decisoes)
        self.assertEqual(pacote["decisions"][0]["id"], "D1")


class ValidarTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name)
        (self.raiz / "app").mkdir()
        (self.raiz / "app" / "a.py").write_text("Sale\n", encoding="utf-8")
        (self.raiz / ".env").write_text("TOKEN=1\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def montar(self, trechos, texto="", decisoes=None):
        return cp.montar("t", trechos, {"texto": texto} if texto else None, decisoes=decisoes)

    def test_arquivo_existente_confirmado(self):
        pacote = cp.validar(self.montar([trecho("app/a.py", "Sale")]), self.raiz)
        self.assertTrue(pacote["relevant_files"][0]["confirmed"])
        self.assertEqual(pacote["validation"]["pending"], 0)
        self.assertEqual(pacote["missing_information"], [])

    def test_arquivo_inexistente_vira_pendencia(self):
        pacote = cp.validar(self.montar([trecho("app/fantasma.py", "x")]), self.raiz)
        self.assertFalse(pacote["relevant_files"][0]["confirmed"])
        self.assertEqual(pacote["validation"]["pending"], 1)
        self.assertIn("fantasma", " ".join(pacote["missing_information"]))

    def test_dotenv_reprovado_mesmo_existindo(self):
        pacote = cp.validar(self.montar([trecho(".env", "TOKEN=1")]), self.raiz)
        self.assertFalse(pacote["relevant_files"][0]["confirmed"])

    def test_caminho_fora_da_raiz_reprovado(self):
        pacote = cp.validar(self.montar([trecho("../fora.py", "x")]), self.raiz)
        self.assertFalse(pacote["relevant_files"][0]["confirmed"])

    def test_stdin_nao_e_arquivo_e_fica_confirmado(self):
        pacote = cp.validar(self.montar([trecho("stdin", "texto colado")]), self.raiz)
        self.assertTrue(pacote["relevant_files"][0]["confirmed"])

    def test_citacao_do_resumo_confere_no_disco(self):
        pacote = cp.validar(
            self.montar([trecho("app/a.py", "Sale")], "ver app/a.py:1 e app/b.py:9"),
            self.raiz,
        )
        vistos = {r["ref"]: r["confirmed"] for r in pacote["source_references"]}
        self.assertTrue(vistos["app/a.py:1"])
        self.assertFalse(vistos["app/b.py:9"])
        self.assertIn("app/b.py:9", " ".join(pacote["missing_information"]))

    def test_dependencia_ausente_nas_fontes_fica_pendente(self):
        texto = '```json\n{"dependencies": ["Sale", "Product"]}\n```'
        pacote = cp.validar(
            self.montar([trecho("app/a.py", "Sale")], texto), self.raiz, texto_fonte="Sale"
        )
        self.assertIn("Product", " ".join(pacote["missing_information"]))

    def test_sem_texto_fonte_dependencia_nao_e_reprovada(self):
        texto = '```json\n{"dependencies": ["Sale"]}\n```'
        pacote = cp.validar(self.montar([trecho("app/a.py", "Sale")], texto), self.raiz)
        self.assertEqual(pacote["validation"]["pending"], 0)

    def test_pendencia_do_modelo_e_preservada(self):
        texto = '```json\n{"missing_information": ["falta a policy"]}\n```'
        pacote = cp.validar(self.montar([trecho("app/a.py", "Sale")], texto), self.raiz)
        self.assertIn("falta a policy", pacote["missing_information"])

    def test_decisao_com_arquivo_existente_confirmada(self):
        decisoes = [{"id": "D1", "description": "x", "files": ["app/a.py"], "rationale": "",
                     "date": "", "status": "", "references": []}]
        pacote = cp.validar(self.montar([trecho("app/a.py", "Sale")], decisoes=decisoes), self.raiz)
        self.assertTrue(pacote["decisions"][0]["confirmed"])
        self.assertEqual(pacote["validation"]["pending"], 0)

    def test_decisao_com_arquivo_inexistente_fica_pendente(self):
        decisoes = [{"id": "D1", "description": "x", "files": ["app/fantasma.py"], "rationale": "",
                     "date": "", "status": "", "references": []}]
        pacote = cp.validar(self.montar([trecho("app/a.py", "Sale")], decisoes=decisoes), self.raiz)
        self.assertFalse(pacote["decisions"][0]["confirmed"])
        self.assertIn("D1", " ".join(pacote["missing_information"]))


if __name__ == "__main__":
    unittest.main()
