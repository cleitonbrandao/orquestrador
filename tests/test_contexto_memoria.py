"""Testes da memória do projeto (roadmap §7). Sem rede."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import contexto_memoria as cm  # noqa: E402


def escrever(pasta, nome, dados):
    caminho = Path(pasta) / nome
    caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return caminho


class PastaTest(unittest.TestCase):
    def test_usa_xdg_state_home(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp}):
            pasta = cm.pasta_memoria("/home/x/projetos/softnews-notion")
            self.assertEqual(pasta, Path(tmp) / "orquestrador" / "memoria" / "softnews-notion")

    def test_slug_limpa_caracteres(self):
        self.assertEqual(cm.slug("Softnews Notion!!"), "softnews-notion")
        self.assertEqual(cm.slug(""), "projeto")
        self.assertEqual(cm.slug("."), "projeto")

    def test_raiz_ponto_usa_o_nome_do_diretorio_atual(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp}):
            pasta = cm.pasta_memoria(".")
            self.assertEqual(pasta.name, cm.slug(Path.cwd().name))
            self.assertNotEqual(pasta.name, ".")


class CriarTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.tmp.name) / "app"

    def tearDown(self):
        self.tmp.cleanup()

    def test_cria_os_dois_arquivos(self):
        criados = cm.criar(self.pasta)
        self.assertEqual(sorted(p.name for p in criados),
                         ["business_rules.json", "decisions.json"])
        self.assertTrue((self.pasta / cm.NOME_REGRAS).is_file())
        self.assertTrue((self.pasta / cm.NOME_DECISOES).is_file())

    def test_nao_sobrescreve(self):
        self.pasta.mkdir(parents=True)
        escrever(self.pasta, cm.NOME_REGRAS, {"rules": ["minha regra"]})
        criados = cm.criar(self.pasta)
        self.assertEqual([p.name for p in criados], ["decisions.json"])
        self.assertEqual(
            cm.carregar_regras(self.pasta / cm.NOME_REGRAS)[0]["text"], "minha regra"
        )


class RegrasTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_aceita_lista_de_strings(self):
        caminho = escrever(self.pasta, "r.json", ["Toda consulta respeita team_id"])
        regras = cm.carregar_regras(caminho)
        self.assertEqual(regras, [{"id": "R1", "priority": "P0",
                                   "text": "Toda consulta respeita team_id",
                                   "applies_to": []}])

    def test_aceita_objeto_com_rules_e_prioridade(self):
        caminho = escrever(self.pasta, "r.json", {"rules": [
            {"id": "team", "priority": "p1", "text": "Usar scopeAuth()"},
        ]})
        regras = cm.carregar_regras(caminho)
        self.assertEqual(regras[0]["priority"], "P1")
        self.assertEqual(regras[0]["id"], "team")

    def test_regra_sem_texto_falha(self):
        caminho = escrever(self.pasta, "r.json", {"rules": [{"id": "x"}]})
        with self.assertRaises(cm.MemoriaError):
            cm.carregar_regras(caminho)

    def test_json_invalido_falha(self):
        caminho = self.pasta / "r.json"
        caminho.write_text("{nao", encoding="utf-8")
        with self.assertRaises(cm.MemoriaError):
            cm.carregar_regras(caminho)

    def test_arquivo_ausente_falha(self):
        with self.assertRaises(cm.MemoriaError):
            cm.carregar_regras(self.pasta / "nao-existe.json")


class SelecaoRegrasTest(unittest.TestCase):
    REGRAS = [
        {"id": "p0", "priority": "P0", "text": "team_id em toda consulta", "applies_to": []},
        {"id": "jsx", "priority": "P1", "text": "usar Inertia", "applies_to": ["*.jsx"]},
        {"id": "sla", "priority": "P1", "text": "documentar SLA", "applies_to": []},
    ]

    def test_p0_entra_sempre(self):
        achadas = cm.selecionar_regras(self.REGRAS, "assunto aleatorio sem relacao")
        self.assertEqual([r["id"] for r in achadas], ["p0"])

    def test_p1_entra_quando_mencionada(self):
        achadas = cm.selecionar_regras(self.REGRAS, "preciso documentar o SLA disso")
        self.assertEqual([r["id"] for r in achadas], ["p0", "sla"])

    def test_p1_entra_pelo_applies_to(self):
        achadas = cm.selecionar_regras(
            self.REGRAS, "ajustar tela", ["app/resources/js/Pages/X.jsx"]
        )
        self.assertEqual([r["id"] for r in achadas], ["p0", "jsx"])

    def test_p0_fica_mesmo_com_applies_to_furado(self):
        regras = [{"id": "p0", "priority": "P0", "text": "seguranca", "applies_to": ["*.jsx"]}]
        self.assertEqual(len(cm.selecionar_regras(regras, "nada")), 1)

    def test_sem_regras_devolve_vazio(self):
        self.assertEqual(cm.selecionar_regras([], "qualquer"), [])


class DecisoesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_normaliza_campos_ausentes(self):
        caminho = escrever(self.pasta, "d.json", {"decisions": [
            {"id": "D1", "description": "Trocar PhaseTrail por grafo"},
        ]})
        decisao = cm.carregar_decisoes(caminho)[0]
        self.assertEqual(decisao["files"], [])
        self.assertEqual(decisao["rationale"], "")
        self.assertEqual(decisao["status"], "")

    def test_sem_descricao_falha(self):
        caminho = escrever(self.pasta, "d.json", {"decisions": [{"id": "D1"}]})
        with self.assertRaises(cm.MemoriaError):
            cm.carregar_decisoes(caminho)

    def test_files_precisa_ser_lista(self):
        caminho = escrever(self.pasta, "d.json", {"decisions": [
            {"description": "x", "files": "app/a.php"},
        ]})
        with self.assertRaises(cm.MemoriaError):
            cm.carregar_decisoes(caminho)

    def test_relevantes_casa_pelo_conteudo(self):
        decisoes = [
            {"id": "D1", "description": "Grafo do fluxo eSocial", "rationale": "",
             "files": ["app/Flow.jsx"], "date": "2026-01-01"},
            {"id": "D2", "description": "Índices de vendas", "rationale": "",
             "files": ["app/Sale.php"], "date": "2026-02-01"},
        ]
        achadas = cm.relevantes(decisoes, "mexer no Flow.jsx do eSocial")
        self.assertEqual([d["id"] for d in achadas], ["D1"])

    def test_sem_casamento_devolve_mais_recentes(self):
        decisoes = [
            {"id": "D1", "description": "a", "rationale": "", "files": [], "date": "2026-01-01"},
            {"id": "D2", "description": "b", "rationale": "", "files": [], "date": "2026-03-01"},
            {"id": "D3", "description": "c", "rationale": "", "files": [], "date": "2026-02-01"},
        ]
        self.assertEqual([d["id"] for d in cm.relevantes(decisoes, "zebra")], ["D2", "D3", "D1"])

    def test_respeita_o_limite(self):
        decisoes = [{"id": f"D{i}", "description": "x", "rationale": "", "files": [], "date": ""}
                    for i in range(10)]
        self.assertEqual(len(cm.relevantes(decisoes, "x", limite=3)), 3)

    def test_palavra_comum_nao_seleciona(self):
        decisoes = [
            {"id": "D1", "description": "grafo do fluxo", "rationale": "",
             "files": ["app/Flow.jsx"], "date": "2026-01-01"},
            {"id": "D2", "description": "indices de vendas", "rationale": "",
             "files": ["app/Sale.php"], "date": "2026-02-01"},
        ]
        # "como" não deve casar com a descrição de D2 por acaso
        achadas = cm.relevantes(decisoes, "como separar custo", limite=5)
        self.assertEqual([d["id"] for d in achadas], ["D2", "D1"])  # sem casamento: recentes


if __name__ == "__main__":
    unittest.main()
