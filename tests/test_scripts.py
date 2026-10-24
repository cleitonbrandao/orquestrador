"""Testes dos scripts do /orquestrar. Sem GPU: o Ollama é um servidor HTTP falso.

Rodar: python -m unittest discover -s tests -v
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import redigir_docs  # noqa: E402
import verificar_docs  # noqa: E402


def bash_disponivel() -> bool:
    return shutil.which("bash") is not None


def rodar_sh(comando: str) -> tuple[int, str]:
    # caminho completo: no Windows, "bash" sozinho cai no bash do WSL (System32), que não abre C:\...
    r = subprocess.run([shutil.which("bash"), str(SCRIPTS / "verificar.sh"), comando], capture_output=True)
    return r.returncode, r.stdout.decode("utf-8", "replace")


def rodar_ps1(comando: str) -> tuple[int, str]:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPTS / "verificar.ps1"), comando],
        capture_output=True,
    )
    return r.returncode, r.stdout.decode("utf-8", "replace")


@unittest.skipUnless(bash_disponivel(), "bash ausente")
class VerificarSh(unittest.TestCase):
    def caso(self, comando: str, resultado: str, codigo: int) -> str:
        rc, out = rodar_sh(comando)
        self.assertIn(f"RESULTADO: {resultado}", out)
        self.assertEqual(rc, codigo, out)
        return out

    def test_comando_sem_testes_e_bloqueado(self):
        out = self.caso("git --version", "bloqueado", 2)
        self.assertIn("git version", out)
        self.assertIn("CODIGO: 0", out)

    def test_phpunit_ok_passa(self):
        self.caso("echo 'OK (3 tests, 5 assertions)'", "passou", 0)

    def test_pytest_e_pest(self):
        self.caso("echo '5 passed in 0.12s'", "passou", 0)
        self.caso("echo 'Tests:  1 failed, 4 passed'", "falhou", 1)

    def test_falha_vence_codigo_zero(self):
        self.caso("echo 'FAILURES!'", "falhou", 1)

    def test_comando_inexistente_e_bloqueado(self):
        self.caso("comando_que_nao_existe_xyz", "bloqueado", 2)

    def test_recusa_instalacao_e_remocao(self):
        for c in ("composer install", "npm ci", "rm -rf build", "ls && rm x", "php artisan migrate:fresh", "docker ps"):
            with self.subTest(c=c):
                out = self.caso(c, "bloqueado", 2)
                self.assertIn("recusado", out)

    def test_saida_cortada_nas_ultimas_linhas(self):
        out = self.caso("for i in $(seq 1 100); do echo linha$i; done", "bloqueado", 2)
        self.assertIn("linha100", out)
        self.assertNotIn("linha60\n", out)


@unittest.skipUnless(sys.platform == "win32" and shutil.which("powershell"), "só no Windows")
class VerificarPs1(unittest.TestCase):
    def test_contrato(self):
        casos = [
            ("git --version", "bloqueado", 2),
            ("Write-Output 'OK (3 tests, 5 assertions)'", "passou", 0),
            ("Write-Output 'FAILURES!'; exit 1", "falhou", 1),
            ("Remove-Item x", "bloqueado", 2),
            ("composer install", "bloqueado", 2),
        ]
        for comando, resultado, codigo in casos:
            with self.subTest(c=comando):
                rc, out = rodar_ps1(comando)
                self.assertIn(f"RESULTADO: {resultado}", out)
                self.assertEqual(rc, codigo, out)


class VerificarDocs(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "docs").mkdir()
        (self.tmp / "docs" / "OPERACAO.md").write_text("# Operação\n\ntexto\n", encoding="utf-8")
        (self.tmp / "scripts").mkdir()
        (self.tmp / "scripts" / "build.sh").write_text("echo\n", encoding="utf-8")
        (self.tmp / "package.json").write_text(json.dumps({"scripts": {"test": "x", "build": "y"}}), encoding="utf-8")
        self.alvo = self.tmp / "README.md"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def motivos(self, proposta: str, original: str = "") -> list[str]:
        return [m for _, m in verificar_docs.verificar(self.alvo, proposta, original, self.tmp)]

    def test_texto_correto_passa(self):
        texto = (
            "# Projeto\n\nVeja [operação](docs/OPERACAO.md#parar) e `scripts/build.sh`.\n\n"
            "```bash\n./scripts/build.sh\nnpm run build\n```\n\nTodo o código fica em `docs/`.\n"
            "[site](https://exemplo.com) e [topo](#projeto).\n"
        )
        self.assertEqual(self.motivos(texto), [])

    def test_link_e_caminho_inventados(self):
        m = self.motivos("# P\n\nVeja [x](docs/NAO.md) e `scripts/deploy.sh`.\n")
        self.assertIn("link para caminho inexistente: docs/NAO.md", m)
        self.assertIn("caminho citado não existe: scripts/deploy.sh", m)

    def test_script_e_npm_inventados_no_bloco(self):
        m = self.motivos("# P\n\n```bash\n./verificar.sh\npython tools/x.py\nnpm run deploy\n```\n")
        self.assertIn("script citado não existe: verificar.sh", m)
        self.assertIn("script citado não existe: tools/x.py", m)
        self.assertIn("script npm não existe no package.json: deploy", m)

    def test_link_dentro_de_bloco_de_codigo_e_ignorado(self):
        self.assertEqual(self.motivos("# P\n\n```md\n[x](nao/existe.md)\n```\n"), [])

    def test_secao_vazia_e_marcador(self):
        m = self.motivos("# P\n\n## Instalação\n\n## Uso\n\nTODO escrever\n")
        self.assertIn("seção vazia: ## Instalação", m)
        self.assertIn("marcador de pendência: TODO", m)
        self.assertEqual(self.motivos("# P\n\nO verificador recusa `TODO` e `FIXME`.\n"), [])

    def test_problema_antigo_nao_conta(self):
        original = "# P\n\nVeja [x](docs/ANTIGO.md).\n"
        self.assertEqual(self.motivos(original + "\nNovo parágrafo.\n", original), [])
        self.assertEqual(len(self.motivos(original + "\n[y](docs/ANTIGO.md)\n", original)), 1)

    def test_id_de_modelo_nao_e_caminho(self):
        self.assertEqual(self.motivos("# P\n\nUse `opencode/deepseek-v4.1-flash-free`.\n"), [])

    def test_cli_compara_com_head_do_git(self):
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True)
        self.alvo.write_text("# P\n\n[x](docs/ANTIGO.md)\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.tmp, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], cwd=self.tmp, check=True)
        self.alvo.write_text("# P\n\n[x](docs/ANTIGO.md)\n\n[y](docs/NOVO.md)\n", encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = verificar_docs.main([str(self.alvo)])
        self.assertEqual(rc, 1)
        self.assertIn("docs/NOVO.md", out.getvalue())
        self.assertNotIn("ANTIGO", out.getvalue())


class OllamaFalso(BaseHTTPRequestHandler):
    respostas: list[str] = []
    pedidos: list[dict] = []

    def log_message(self, *a):
        pass

    def responder(self, corpo: dict):
        dados = json.dumps(corpo).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        self.responder({"models": [{"name": "falso:latest"}]})

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        OllamaFalso.pedidos.append(json.loads(self.rfile.read(tamanho)))
        texto = OllamaFalso.respostas.pop(0) if OllamaFalso.respostas else ""
        self.responder({"message": {"role": "assistant", "content": texto}})


class RedigirDocs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = HTTPServer(("127.0.0.1", 0), OllamaFalso)
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "docs").mkdir()
        (self.tmp / "docs" / "A.md").write_text("# A\n", encoding="utf-8")
        self.readme = self.tmp / "README.md"
        self.readme.write_text("# P\n\n## Uso\n\nRode `docs/A.md`.\n\n---\n\n## Fim\n\nfim\n", encoding="utf-8")
        self.saida = self.tmp / "proposta.md"
        OllamaFalso.respostas, OllamaFalso.pedidos = [], []
        redigir_docs.URL = "http://127.0.0.1:%d" % self.servidor.server_address[1]
        redigir_docs.MODELO = "falso"
        self.cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rodar(self, *extra: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = redigir_docs.main(["--alvo", "README.md", "--tarefa", "t", "--saida", str(self.saida), *extra])
        return rc, out.getvalue()

    def test_secao_trocada_preserva_separador_e_resto(self):
        OllamaFalso.respostas = ["```markdown\n## Uso\n\nRode `docs/A.md` duas vezes.\n```"]
        rc, out = self.rodar("--secao", "## Uso")
        self.assertEqual(rc, 0, out)
        self.assertEqual(
            self.saida.read_text(encoding="utf-8"),
            "# P\n\n## Uso\n\nRode `docs/A.md` duas vezes.\n\n---\n\n## Fim\n\nfim\n",
        )
        self.assertNotIn("\r\n", self.saida.read_bytes().decode("utf-8"))
        self.assertIn("Rode `docs/A.md`.", OllamaFalso.pedidos[0]["messages"][1]["content"])
        self.assertNotIn("## Fim", OllamaFalso.pedidos[0]["messages"][1]["content"])
        self.assertFalse(OllamaFalso.pedidos[0]["think"])

    def test_reenvia_com_motivo_e_aceita_correcao(self):
        OllamaFalso.respostas = ["## Uso\n\nVeja [b](docs/B.md).\n", "## Uso\n\nVeja [a](docs/A.md).\n"]
        rc, out = self.rodar("--secao", "## Uso")
        self.assertEqual(rc, 0, out)
        self.assertIn("TENTATIVAS: 2", out)
        self.assertIn("docs/B.md", OllamaFalso.pedidos[1]["messages"][-1]["content"])

    def test_falha_depois_das_tentativas(self):
        OllamaFalso.respostas = ["## Uso\n\n[b](docs/B.md)\n"] * 3
        rc, out = self.rodar("--secao", "## Uso")
        self.assertEqual(rc, 1)
        self.assertIn("RESULTADO: falhou", out)
        self.assertIn("link para caminho inexistente: docs/B.md", out)
        self.assertTrue(self.readme.read_text(encoding="utf-8").startswith("# P\n\n## Uso\n\nRode"))

    def test_secao_nova_vai_para_o_fim(self):
        OllamaFalso.respostas = ["Texto novo.\n"]
        rc, out = self.rodar("--secao", "## Extra")
        self.assertEqual(rc, 0, out)
        self.assertTrue(self.saida.read_text(encoding="utf-8").endswith("fim\n\n## Extra\n\nTexto novo.\n"))

    def test_sem_ollama_e_indisponivel(self):
        redigir_docs.URL = "http://127.0.0.1:9"
        rc, out = self.rodar()
        self.assertEqual(rc, 3)
        self.assertIn("RESULTADO: indisponivel", out)

    def test_modelo_ausente_e_indisponivel(self):
        redigir_docs.MODELO = "outro"
        rc, out = self.rodar()
        self.assertEqual(rc, 3)
        self.assertIn("não está no Ollama", out)

    def test_arquivo_grande_sem_secao_e_indisponivel(self):
        self.readme.write_text("# P\n\n" + "linha de texto\n" * 3000, encoding="utf-8")
        rc, out = self.rodar()
        self.assertEqual(rc, 3)
        self.assertIn("--secao", out)
        self.assertEqual(OllamaFalso.pedidos, [])


if __name__ == "__main__":
    unittest.main()
