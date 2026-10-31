"""Invariantes da configuração do OpenCode. Determinístico: lê só o JSON do repo.

Cobre o que quebra silenciosamente: agente apontando para modelo que não existe no
provider (o OpenCode descarta o agente sem avisar), rota sem destino, MCP ausente e
a regra de leitura barata (que depende de negação explícita para valer).

Rodar: python3 -m unittest discover -s tests -v
"""
import json
import os
import unittest

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG = os.path.join(RAIZ, "opencode", "opencode.json")

SUBAGENTES = ("orquestrador", "decompositor", "executor", "exec-local", "exec-docs",
              "exec-backend", "exec-dados", "exec-frontend", "local-helper", "local-mini", "revisor")


class ConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CONFIG, encoding="utf-8") as f:
            cls.d = json.load(f)
        cls.agentes = cls.d["agents"]
        cls.modelos = cls.d["provider"]["ollama"]["models"]

    def test_agentes_esperados_existem(self):
        for nome in SUBAGENTES:
            self.assertIn(nome, self.agentes, f"agente {nome} ausente")

    def test_modelo_de_cada_agente_existe_no_provider(self):
        for nome, ag in self.agentes.items():
            modelo = ag.get("model")
            if not modelo or not modelo.startswith("ollama/"):
                continue
            chave = modelo.split("/", 1)[1]
            self.assertIn(chave, self.modelos, f"{nome} aponta para {chave}, que não está no provider")

    def test_orquestrador_sem_model_fixo(self):
        self.assertIsNone(self.agentes["orquestrador"].get("model"),
                          "o orquestrador deve seguir o /models")

    def test_orquestrador_pode_chamar_os_quatro_executores(self):
        permitidos = {p["resource"] for p in self.agentes["orquestrador"]["permissions"]
                      if p["action"] == "subagent"}
        for alvo in ("exec-local", "exec-docs", "executor", "exec-backend", "exec-dados",
                     "exec-frontend", "decompositor", "local-helper", "local-mini", "revisor"):
            self.assertIn(alvo, permitidos, f"orquestrador sem permissão para {alvo}")

    def test_exec_local_e_local_e_de_um_arquivo(self):
        ag = self.agentes["exec-local"]
        self.assertTrue(ag["model"].startswith("ollama/"))
        self.assertIn("UM único arquivo", ag["system"])
        self.assertIn("não remova, não substitua", ag["system"])

    def test_exec_docs_roda_local(self):
        self.assertTrue(self.agentes["exec-docs"]["model"].startswith("ollama/"))

    def test_decompositor_conhece_rota_local(self):
        sistema = self.agentes["decompositor"]["system"]
        self.assertIn("rota=local", sistema)
        self.assertIn("<leve|local|edicao|docs>", sistema)

    def test_orquestrador_roteia_rota_local(self):
        self.assertIn("rota=local vai para o exec-local",
                      self.agentes["orquestrador"]["system"])

    def test_leitura_de_codigo_e_negada_no_orquestrador(self):
        """Sem deny, a regra de custo é só prosa e o pago lê o arquivo inteiro."""
        denies = {p["resource"] for p in self.agentes["orquestrador"]["permissions"]
                  if p["action"] == "read" and p["effect"] == "deny"}
        self.assertIn("*.php", denies)
        self.assertIn("*.sql", denies)

    def test_regra_de_leitura_aponta_para_delegacao(self):
        sistema = self.agentes["orquestrador"]["system"]
        self.assertIn("LEITURA (regra de custo)", sistema)
        self.assertIn("local-helper", sistema)

    def test_orquestrador_usa_o_contexto_mcp_antes_de_ler(self):
        sistema = self.agentes["orquestrador"]["system"]
        self.assertIn("CONTEXTO (regra de custo)", sistema)
        self.assertIn("context_build", sistema)
        self.assertIn("context_get_rules", sistema)
        self.assertIn("confirmed: false", sistema)
        # critério de adoção explícito: sem ele a regra é só prosa
        self.assertIn("~2 mil tokens", sistema)
        self.assertIn("3+ arquivos", sistema)

    def test_integrar_confere_o_diff(self):
        self.assertIn("nenhum arquivo fora das listas", self.agentes["orquestrador"]["system"])

    def test_servidores_mcp(self):
        servidores = self.d["mcp"]["servers"]
        for nome in ("trail", "run_tests", "kb", "decisao", "contexto"):
            self.assertIn(nome, servidores)
        self.assertEqual(servidores["decisao"]["command"], ["orq-decisor"])

    def test_local_mini_nao_usa_o_coder_1_5b(self):
        self.assertNotIn("qwen2.5-coder:1.5b", self.agentes["local-mini"]["model"])
        self.assertTrue(self.agentes["local-mini"]["model"].startswith("ollama/"))

    def test_saida_dos_modelos_locais_comporta_edicao(self):
        for chave in ("qwen3.5-2b-32k:latest", "gemma4-e2b-32k:latest"):
            self.assertGreaterEqual(self.modelos[chave]["limit"]["output"], 4096,
                                    f"{chave} com output baixo trunca edição")

    def test_rota_local_exige_um_arquivo(self):
        orq = self.agentes["orquestrador"]["system"]
        self.assertIn("com 2+ arquivos trate como edicao", orq)
        self.assertIn("Rejeite também rota=local com mais de um arquivo", orq)
        self.assertIn("reclassifique para edicao", orq)
        dec = self.agentes["decompositor"]["system"]
        self.assertIn("exatamente UM arquivo", dec)
        self.assertIn("com 2+ arquivos use rota=edicao", dec)

    def test_locais_nao_narram_ferramenta(self):
        # Falha real de 29/10: o exec-local descreveu o plano e não chamou read/edit.
        for nome in ("local-helper", "exec-local"):
            self.assertTrue(self.agentes[nome]["system"].startswith("Não"),
                            f"{nome} deve proibir narração de ferramenta no início do prompt")
        self.assertIn("execute read/edit/run_tests diretamente",
                      self.agentes["exec-local"]["system"])


if __name__ == "__main__":
    unittest.main()
