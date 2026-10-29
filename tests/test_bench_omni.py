"""Testes do benchmark multimodal. Determinísticos: sem Ollama e sem rede.

Rodar: python3 -m unittest discover -s tests -v
"""
import io
import os
import struct
import sys
import unittest
import wave

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import bench_omni as bo  # noqa: E402


class WavTest(unittest.TestCase):
    def test_duracao_do_wav_gerado(self):
        dados = bo.wav_exemplo(segundos_audio=2.5)
        self.assertAlmostEqual(bo.wav_seconds(dados), 2.5, places=2)

    def test_formato_do_wav_gerado(self):
        with wave.open(io.BytesIO(bo.wav_exemplo(1.0))) as w:
            self.assertEqual(w.getframerate(), 16000)
            self.assertEqual(w.getnchannels(), 1)
            self.assertEqual(w.getsampwidth(), 2)

    def test_rejeita_nao_wav(self):
        with self.assertRaises(bo.BenchError):
            bo.wav_seconds(b"nao sou um wav" * 10)

    def test_header_de_streaming_com_tamanho_maximo(self):
        """O /v1/audio/speech grava 0xFFFFFFFF no tamanho do 'data'; vale o real."""
        dados = bytearray(bo.wav_exemplo(1.0))
        pos = dados.find(b"data")
        dados[pos + 4 : pos + 8] = struct.pack("<I", 0xFFFFFFFF)
        self.assertAlmostEqual(bo.wav_seconds(bytes(dados)), 1.0, places=2)


class MetricasTest(unittest.TestCase):
    def test_rtf_mais_rapido_que_o_audio(self):
        self.assertEqual(bo.rtf(1.5, 3.0), 0.5)

    def test_rtf_mais_lento_que_o_audio(self):
        self.assertEqual(bo.rtf(6.0, 3.0), 2.0)

    def test_rtf_metade_do_tempo(self):
        """Verifica que bo.rtf(1.0, 4.0) resulta em 0.25."""
        self.assertEqual(bo.rtf(1.0, 4.0), 0.25)

    def test_rtf_sem_duracao(self):
        self.assertIsNone(bo.rtf(1.0, 0))

    def test_taxa_sem_tokens_ou_sem_tempo(self):
        self.assertIsNone(bo.taxa(0, 1_000_000))
        self.assertIsNone(bo.taxa(10, 0))

    def test_taxa_normal(self):
        self.assertEqual(bo.taxa(100, 2_000_000_000), 50.0)


class PlataformaTest(unittest.TestCase):
    def test_reconhece_erro_de_mlx(self):
        self.assertTrue(bo.eh_mlx("this model requires MLX support, but the MLX runtime is not available"))

    def test_nao_confunde_outros_erros(self):
        self.assertFalse(bo.eh_mlx("model requires more system memory (8.2 GiB)"))
        self.assertFalse(bo.eh_mlx(""))


class FixturesTest(unittest.TestCase):
    def test_png_tem_assinatura_e_chunks(self):
        png = bo.png_exemplo(64, 48)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn(b"IHDR", png[:32])
        self.assertTrue(png.endswith(b"IEND\xaeB`\x82"))

    def test_png_declara_as_dimensoes(self):
        png = bo.png_exemplo(64, 48)
        largura, altura = struct.unpack(">II", png[16:24])
        self.assertEqual((largura, altura), (64, 48))


if __name__ == "__main__":
    unittest.main()
