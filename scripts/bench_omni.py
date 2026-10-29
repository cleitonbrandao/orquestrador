#!/usr/bin/env python3
"""Benchmark de modelos multimodais do Ollama: texto, imagem, áudio e fala.

Mede o que `tok/s` de texto não mede:

  texto   carga, TTFT, tok/s de leitura e de geração (frio e quente)
  imagem  custo da imagem em tokens de prompt e latência extra
  áudio   tempo de codificação e RTF de entrada (tempo de máquina / duração do áudio)
  fala    RTF de saída (tempo de geração / duração do áudio gerado)

As etapas rodam apenas para as capacidades que o modelo declara em /api/show
(completion, vision, audio, speech). Modelos que dependem do runtime MLX
(lfm3-omni, lfm3-audio no Ollama 0.40.12) falham na primeira chamada e o script
sai com código 3 explicando o motivo, em vez de gravar número inventado.

Uso:
    python scripts/bench_omni.py --model lfm3-omni
    python scripts/bench_omni.py --model llava:7b --only text,image
    python scripts/bench_omni.py --model x --audio fala.wav --image foto.png

Somente biblioteca padrão. Requer Ollama em execução.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import struct
import sys
import textwrap
import time
import urllib.error
import urllib.request
import wave
import zlib
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA_PADRAO = RAIZ / "docs" / "resultados" / "omni"

TEXTO_VELOCIDADE = (
    "Explique, em português, como funciona um índice B-tree em banco de dados relacional. "
    "Cubra: estrutura de nós, busca, inserção com divisão de página e custo de leitura. "
    "Escreva exatamente 4 parágrafos de 4 a 5 frases cada. Não use listas nem tabelas."
)
PERGUNTA_IMAGEM = "Descreva em uma frase o que aparece nesta imagem."
FALA_TEXTO = "Teste de performance do orquestrador. Esta frase mede a latência de síntese de voz."
AUDIO_ENTRADA_TEXTO = "Transcreva o áudio."


class BenchError(Exception):
    """Erro de benchmark com mensagem pronta para o usuário."""


# --------------------------------------------------------------------------- HTTP


def _req(host: str, caminho: str, corpo, timeout: int) -> urllib.request.Request:
    dados = None
    cabecalhos = {"Accept": "application/json"}
    if corpo is not None:
        dados = json.dumps(corpo).encode("utf-8")
        cabecalhos["Content-Type"] = "application/json; charset=utf-8"
    return urllib.request.Request(host + caminho, data=dados, headers=cabecalhos)


def _erro_http(exc: urllib.error.HTTPError) -> str:
    try:
        bruto = exc.read().decode("utf-8", "replace")
        return json.loads(bruto).get("error", bruto) or f"HTTP {exc.code}"
    except Exception:  # noqa: BLE001 - qualquer falha de parse vira mensagem genérica
        return f"HTTP {exc.code}"


def http_json(host: str, caminho: str, corpo=None, timeout: int = 900) -> dict:
    try:
        with urllib.request.urlopen(_req(host, caminho, corpo, timeout), timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise BenchError(_erro_http(e)) from e
    except urllib.error.URLError as e:
        raise BenchError(f"Ollama não respondeu em {host}: {e.reason}") from e


def http_bytes(host: str, caminho: str, corpo, timeout: int = 900) -> bytes:
    try:
        with urllib.request.urlopen(_req(host, caminho, corpo, timeout), timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise BenchError(_erro_http(e)) from e
    except urllib.error.URLError as e:
        raise BenchError(f"Ollama não respondeu em {host}: {e.reason}") from e


def conversar(host: str, corpo: dict, timeout: int = 900) -> dict:
    """POST /api/chat com stream, devolvendo texto, tempos do Ollama e TTFT."""
    corpo = dict(corpo)
    corpo["stream"] = True
    t0 = time.perf_counter()
    ttft = None
    pedacos: list[str] = []
    final: dict = {}
    try:
        with urllib.request.urlopen(_req(host, "/api/chat", corpo, timeout), timeout=timeout) as r:
            for linha in r:
                linha = linha.strip()
                if not linha:
                    continue
                evento = json.loads(linha.decode("utf-8"))
                if evento.get("error"):
                    raise BenchError(evento["error"])
                pedaco = (evento.get("message") or {}).get("content") or ""
                if pedaco:
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                    pedacos.append(pedaco)
                if evento.get("done"):
                    final = evento
    except urllib.error.HTTPError as e:
        raise BenchError(_erro_http(e)) from e
    except urllib.error.URLError as e:
        raise BenchError(f"Ollama não respondeu em {host}: {e.reason}") from e

    final["texto"] = "".join(pedacos)
    final["ttft_s"] = ttft
    final["parede_s"] = time.perf_counter() - t0
    return final


# --------------------------------------------------------------------- métricas


def segundos(ns) -> float:
    return (ns or 0) / 1e9


def taxa(tokens, ns) -> float | None:
    dur = segundos(ns)
    return round(tokens / dur, 1) if tokens and dur > 0 else None


def rtf(tempo_maquina: float, duracao_audio: float) -> float | None:
    """Fator de tempo real: <1 é mais rápido que o áudio tocar; >1 é mais lento."""
    if not duracao_audio or duracao_audio <= 0:
        return None
    return round(tempo_maquina / duracao_audio, 2)


def wav_seconds(dados: bytes) -> float:
    """Duração de um WAV contando apenas os bytes realmente recebidos.

    O /v1/audio/speech escreve o tamanho máximo no header enquanto gera, então o
    campo de tamanho do chunk 'data' não é confiável: usamos byte_rate × bytes reais.
    """
    if len(dados) < 44 or dados[:4] != b"RIFF" or dados[8:12] != b"WAVE":
        raise BenchError("resposta não é um WAV válido")
    pos, byte_rate, inicio_dados = 12, 0, None
    while pos + 8 <= len(dados):
        chunk = dados[pos : pos + 4]
        tam = struct.unpack("<I", dados[pos + 4 : pos + 8])[0]
        if chunk == b"fmt " and pos + 20 <= len(dados):
            byte_rate = struct.unpack("<I", dados[pos + 16 : pos + 20])[0]
        elif chunk == b"data":
            inicio_dados = pos + 8
            break
        pos += 8 + tam + (tam & 1)
    if inicio_dados is None or not byte_rate:
        raise BenchError("WAV sem chunk 'fmt ' com byte_rate ou sem chunk 'data'")
    return (len(dados) - inicio_dados) / byte_rate


def eh_mlx(erro: str) -> bool:
    """Modelos nvfp4 da família LFM3 só rodam no runtime MLX (Apple) no 0.40.12."""
    return "mlx" in (erro or "").lower()


# ------------------------------------------------------------------ fixtures


def png_exemplo(largura: int = 512, altura: int = 512) -> bytes:
    """PNG RGB com gradiente e blocos, gerado sem Pillow (só zlib/struct)."""
    linhas = bytearray()
    for y in range(altura):
        linhas.append(0)  # filtro None
        for x in range(largura):
            bloco = 40 if ((x // 64) + (y // 64)) % 2 == 0 else 0
            linhas += bytes(
                (
                    min(255, x * 255 // largura),
                    min(255, y * 255 // altura),
                    min(255, bloco + 60),
                )
            )

    def chunk(tipo: bytes, dados: bytes) -> bytes:
        return (
            struct.pack(">I", len(dados))
            + tipo
            + dados
            + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(linhas), 6))
        + chunk(b"IEND", b"")
    )


def wav_exemplo(segundos_audio: float = 3.0, taxa_hz: int = 16000) -> bytes:
    """Tom de 16 kHz mono 16 bits, no formato que o encoder de áudio espera.

    Serve para medir latência e RTF. Para avaliar transcrição, passe um áudio
    de fala real com --audio.
    """
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa_hz)
        quadros = bytearray()
        for i in range(int(segundos_audio * taxa_hz)):
            amostra = 0.3 * math.sin(2 * math.pi * 440 * i / taxa_hz)
            quadros += struct.pack("<h", int(amostra * 32767))
        w.writeframes(bytes(quadros))
    return buf.getvalue()


# ------------------------------------------------------------------- benchmark


def capacidades_do_modelo(host: str, modelo: str) -> tuple[list[str], dict]:
    show = http_json(host, "/api/show", {"model": modelo}, timeout=30)
    caps = [str(c) for c in (show.get("capabilities") or [])]
    if not caps:
        caps = ["completion"]  # Ollama antigo não expõe capabilities
    info = show.get("details") or {}
    return caps, {
        "parametros": info.get("parameter_size"),
        "quantizacao": info.get("quantization_level"),
        "familia": info.get("family"),
    }


def etapa_texto(host: str, modelo: str, num_predict: int, num_ctx: int) -> dict:
    """Rodada a frio (modelo descarregado) e a quente, com TTFT em ambas."""
    http_json(host, "/api/generate", {"model": modelo, "keep_alive": 0}, timeout=60)
    time.sleep(1)
    base = {
        "model": modelo,
        "options": {"temperature": 0, "seed": 42, "num_ctx": num_ctx, "num_predict": num_predict},
    }

    frio = conversar(host, {**base, "messages": [{"role": "user", "content": TEXTO_VELOCIDADE}]})
    quente = conversar(host, {**base, "messages": [{"role": "user", "content": TEXTO_VELOCIDADE}]})

    return {
        "carga_s": round(segundos(frio.get("load_duration")), 2),
        "ttft_frio_s": round(frio["ttft_s"], 2) if frio.get("ttft_s") else None,
        "ttft_quente_s": round(quente["ttft_s"], 2) if quente.get("ttft_s") else None,
        # leitura vem do frio: na rodada quente o prompt já está em cache
        "tok_s_leitura": taxa(frio.get("prompt_eval_count"), frio.get("prompt_eval_duration")),
        "tok_s_geracao": taxa(quente.get("eval_count"), quente.get("eval_duration")),
        "tokens_prompt": frio.get("prompt_eval_count"),
        "tokens_gerados": quente.get("eval_count"),
        "parede_s": round(quente["parede_s"], 2),
        "resposta": (quente.get("texto") or "")[:400],
    }


def etapa_imagem(host: str, modelo: str, imagem: bytes, num_predict: int, num_ctx: int) -> dict:
    """Custo da imagem em tokens de prompt, comparando com o mesmo texto sem imagem."""
    opcoes = {"temperature": 0, "seed": 42, "num_ctx": num_ctx, "num_predict": num_predict}
    b64 = base64.b64encode(imagem).decode("ascii")

    sem = conversar(
        host,
        {"model": modelo, "messages": [{"role": "user", "content": PERGUNTA_IMAGEM}], "options": opcoes},
    )
    com = conversar(
        host,
        {
            "model": modelo,
            "messages": [{"role": "user", "content": PERGUNTA_IMAGEM, "images": [b64]}],
            "options": opcoes,
        },
    )

    tokens_sem = sem.get("prompt_eval_count") or 0
    tokens_com = com.get("prompt_eval_count") or 0
    prefill_com = segundos(com.get("prompt_eval_duration"))
    delta_latencia = com["parede_s"] - sem["parede_s"]

    return {
        "tokens_prompt_sem": tokens_sem,
        "tokens_prompt_com": tokens_com,
        "tokens_da_imagem": max(0, tokens_com - tokens_sem),
        "prefill_s": round(prefill_com, 2),
        "tok_s_leitura": taxa(com.get("prompt_eval_count"), com.get("prompt_eval_duration")),
        "tok_s_geracao": taxa(com.get("eval_count"), com.get("eval_duration")),
        "ttft_s": round(com["ttft_s"], 2) if com.get("ttft_s") else None,
        "latencia_extra_s": round(delta_latencia, 2),
        "parede_s": round(com["parede_s"], 2),
        "resposta": (com.get("texto") or "")[:400],
    }


# Formatos que o /api/chat já aceitou para áudio em alguma versão do Ollama. O
# primeiro que responder 200 vence; o resto é tentativa e erro registrado.
FORMATOS_AUDIO = (
    ("message.audio", lambda b64: {"messages": [{"role": "user", "content": AUDIO_ENTRADA_TEXTO, "audio": [b64]}]}),
    (
        "content[type=audio]",
        lambda b64: {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": AUDIO_ENTRADA_TEXTO},
                        {"type": "audio", "audio": b64},
                    ],
                }
            ]
        },
    ),
    ("generate.audio", lambda b64: None),  # tratado à parte, em /api/generate
)


def etapa_audio(host: str, modelo: str, audio: bytes, num_predict: int, num_ctx: int) -> dict:
    """Descobre qual formato de entrada de áudio a versão instalada aceita e mede.

    HTTP 200 não basta: o Ollama aceita o campo `audio` e o descarta em silêncio,
    devolvendo a mesma resposta que daria sem áudio. A aceitação exige diferença
    na resposta ou no número de tokens de prompt em relação à mesma pergunta sem áudio.
    """
    duracao = wav_seconds(audio)
    b64 = base64.b64encode(audio).decode("ascii")
    opcoes = {"temperature": 0, "seed": 42, "num_ctx": num_ctx, "num_predict": num_predict}

    sem = conversar(
        host,
        {"model": modelo, "messages": [{"role": "user", "content": AUDIO_ENTRADA_TEXTO}], "options": opcoes},
    )
    texto_sem = (sem.get("texto") or "").strip()
    tokens_sem = sem.get("prompt_eval_count")
    tentativas: dict[str, str] = {}

    for nome, montar in FORMATOS_AUDIO:
        try:
            if nome == "generate.audio":
                corpo = {
                    "model": modelo,
                    "prompt": AUDIO_ENTRADA_TEXTO,
                    "audio": [b64],
                    "stream": False,
                    "options": opcoes,
                }
                r = http_json(host, "/api/generate", corpo)
                texto = (r.get("response") or "").strip()
            else:
                r = conversar(host, {"model": modelo, **montar(b64), "options": opcoes})
                texto = (r.get("texto") or "").strip()
        except BenchError as e:
            tentativas[nome] = str(e)[:160]
            continue

        # Evidência de que o áudio entrou: a resposta mudou ou o prompt cresceu.
        mudou_resposta = texto != texto_sem
        mudou_prompt = (r.get("prompt_eval_count") or 0) > (tokens_sem or 0)
        if not (mudou_resposta or mudou_prompt):
            tentativas[nome] = (
                "HTTP 200, mas ignorado: mesma resposta e mesmos tokens de prompt "
                f"({tokens_sem}) do pedido sem áudio"
            )
            continue

        prefill = segundos(r.get("prompt_eval_duration"))
        tentativas[nome] = "aceito"
        return {
            "via": nome,
            "duracao_audio_s": round(duracao, 2),
            "prefill_s": round(prefill, 2),
            "rtf_entrada": rtf(prefill, duracao),
            "tokens_prompt": r.get("prompt_eval_count"),
            "tok_s_leitura": taxa(r.get("prompt_eval_count"), r.get("prompt_eval_duration")),
            "ttft_s": round(r["ttft_s"], 2) if r.get("ttft_s") else None,
            "parede_s": round(r.get("parede_s") or segundos(r.get("total_duration")), 2),
            "resposta": texto[:400],
            "resposta_sem_audio": texto_sem[:200],
            "tentativas": tentativas,
        }

    raise BenchError(
        "áudio não entrou por nenhum formato nesta versão do Ollama: "
        + "; ".join(f"{k}: {v}" for k, v in tentativas.items())
    )


def etapa_fala(host: str, modelo: str) -> dict:
    """Síntese de fala pelo endpoint OpenAI-compatível, medindo RTF de saída."""
    t0 = time.perf_counter()
    wav = http_bytes(
        host,
        "/v1/audio/speech",
        {"model": modelo, "input": FALA_TEXTO, "voice": "default", "response_format": "wav"},
    )
    parede = time.perf_counter() - t0
    duracao = wav_seconds(wav)
    return {
        "duracao_audio_s": round(duracao, 2),
        "geracao_s": round(parede, 2),
        "rtf_saida": rtf(parede, duracao),
        "bytes": len(wav),
        "velocidade_bytes_s": int(len(wav) / parede) if parede > 0 else None,
    }


# -------------------------------------------------------------------- relatório


def fmt(valor, sufixo: str = "") -> str:
    return "—" if valor is None else f"{valor}{sufixo}"


def imprimir(modelo: str, detalhes: dict, caps: list[str], etapas: dict[str, dict]) -> None:
    print("")
    print(f"Modelo      {modelo}")
    if detalhes.get("parametros") or detalhes.get("quantizacao"):
        print(f"            {fmt(detalhes.get('parametros'))} · {fmt(detalhes.get('quantizacao'))}")
    ativas = ", ".join(caps) if caps else "—"
    print(f"Capacidades {ativas}")

    if "texto" in etapas and "erro" not in etapas["texto"]:
        t = etapas["texto"]
        print("\nTexto")
        print(f"  carga                {fmt(t['carga_s'], ' s')}")
        print(f"  TTFT frio/quente     {fmt(t['ttft_frio_s'], ' s')} / {fmt(t['ttft_quente_s'], ' s')}")
        print(f"  leitura              {fmt(t['tok_s_leitura'], ' tok/s')}")
        print(f"  geração              {fmt(t['tok_s_geracao'], ' tok/s')}")
        print(f"  prompt / gerados     {fmt(t['tokens_prompt'])} / {fmt(t['tokens_gerados'])} tokens")

    if "imagem" in etapas and "erro" not in etapas["imagem"]:
        i = etapas["imagem"]
        print("\nImagem")
        print(f"  tokens da imagem     {fmt(i['tokens_da_imagem'])}  ({fmt(i['tokens_prompt_sem'])} → {fmt(i['tokens_prompt_com'])})")
        print(f"  prefill              {fmt(i['prefill_s'], ' s')}")
        print(f"  latência extra       {fmt(i['latencia_extra_s'], ' s')}")
        print(f"  geração              {fmt(i['tok_s_geracao'], ' tok/s')}")

    if "audio" in etapas and "erro" not in etapas["audio"]:
        a = etapas["audio"]
        print("\nÁudio (entrada)")
        print(f"  via                  {a['via']}")
        print(f"  áudio                {fmt(a['duracao_audio_s'], ' s')}")
        print(f"  prefill              {fmt(a['prefill_s'], ' s')}")
        print(f"  RTF entrada          {fmt(a['rtf_entrada'])}  (<1 = processa mais rápido que o áudio)")
        print(f"  tokens de prompt     {fmt(a['tokens_prompt'])}")

    if "fala" in etapas and "erro" not in etapas["fala"]:
        f = etapas["fala"]
        print("\nFala (saída)")
        print(f"  áudio gerado         {fmt(f['duracao_audio_s'], ' s')}")
        print(f"  tempo                {fmt(f['geracao_s'], ' s')}")
        print(f"  RTF saída            {fmt(f['rtf_saida'])}")

    for nome, e in etapas.items():
        if e.get("erro"):
            print(f"\n{nome.capitalize()}: falhou")
            for linha in textwrap.wrap(e["erro"], 96):
                print(f"  {linha}")


def salvar(modelo: str, dados: dict, destino: Path) -> Path:
    destino.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    arquivo = destino / f"{modelo.replace(':', '_').replace('/', '_')}_{carimbo}.json"
    arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

    csv = destino.parent / "omni.csv"
    novo = not csv.exists()
    def campo(v):
        return "" if v is None else str(v)

    linha = ",".join(
        campo(v)
        for v in (
            carimbo,
            modelo,
            dados["etapas"].get("texto", {}).get("tok_s_geracao"),
            dados["etapas"].get("texto", {}).get("ttft_quente_s"),
            dados["etapas"].get("imagem", {}).get("tokens_da_imagem"),
            dados["etapas"].get("audio", {}).get("rtf_entrada"),
            dados["etapas"].get("fala", {}).get("rtf_saida"),
        )
    )
    with csv.open("a", encoding="utf-8", newline="") as f:
        if novo:
            f.write("data,modelo,tok_s_geracao,ttft_quente_s,tokens_imagem,rtf_entrada,rtf_saida\n")
        f.write(linha + "\n")
    return arquivo


# ------------------------------------------------------------------------ main


def principal(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Benchmark multimodal de modelos do Ollama.")
    p.add_argument("--model", "-m", required=True, help="nome do modelo no Ollama")
    p.add_argument("--host", default=os.environ.get("OLLAMA_HOST_URL", "http://localhost:11434"))
    p.add_argument("--only", default="", help="etapas separadas por vírgula: text,image,audio,speech")
    p.add_argument("--num-predict", type=int, default=256)
    p.add_argument("--num-ctx", type=int, default=4096)
    p.add_argument("--image", help="PNG de teste (padrão: gerado)")
    p.add_argument("--audio", help="WAV 16 kHz de teste (padrão: tom de 3 s)")
    p.add_argument("--out", help="diretório de saída")
    p.add_argument("--sem-salvar", action="store_true")
    args = p.parse_args(argv)

    host = args.host.rstrip("/")
    pedidas = {s.strip() for s in args.only.split(",") if s.strip()}
    alias = {"text": "texto", "image": "imagem", "audio": "audio", "speech": "fala"}

    try:
        versao = http_json(host, "/api/version", timeout=10).get("version", "?")
        caps, detalhes = capacidades_do_modelo(host, args.model)
    except BenchError as e:
        print(f"erro: {e}", file=sys.stderr)
        if "not found" in str(e).lower():
            print(
                "dica: se o modelo for da família LFM3 (lfm3, lfm3-vl, lfm3-audio, lfm3-omni), "
                "o pull falha no Ollama 0.40.12 fora do Apple Silicon com "
                "'this model requires MLX support'.",
                file=sys.stderr,
            )
        return 4

    print(f"Ollama {versao} em {host}")

    plano = [("texto", "completion" in caps), ("imagem", "vision" in caps),
             ("audio", "audio" in caps), ("fala", "speech" in caps)]
    if pedidas:
        plano = [(n, ok and (n in pedidas or {v: k for k, v in alias.items()}[n] in pedidas))
                 for n, ok in plano]

    etapas: dict[str, dict] = {}
    imagem = Path(args.image).read_bytes() if args.image else png_exemplo()
    audio = Path(args.audio).read_bytes() if args.audio else wav_exemplo()
    mlx = False

    for nome, ativa in plano:
        if not ativa:
            continue
        print(f"… {nome}", file=sys.stderr)
        try:
            if nome == "texto":
                etapas["texto"] = etapa_texto(host, args.model, args.num_predict, args.num_ctx)
            elif nome == "imagem":
                etapas["imagem"] = etapa_imagem(host, args.model, imagem, args.num_predict, args.num_ctx)
            elif nome == "audio":
                etapas["audio"] = etapa_audio(host, args.model, audio, args.num_predict, args.num_ctx)
            else:
                etapas["fala"] = etapa_fala(host, args.model)
        except BenchError as e:
            if eh_mlx(str(e)):
                print(
                    f"\n{args.model} exige o runtime MLX (Apple Silicon). "
                    f"O Ollama {versao} não executa este modelo nesta plataforma.\n"
                    "Veja docs/MODELOS-TESTADOS.md: a família LFM3 é Apple-only nesta versão.",
                    file=sys.stderr,
                )
                return 3
            etapas[nome] = {"erro": str(e)}

    if not etapas:
        print("nenhuma etapa aplicável: o modelo não declara completion, vision, audio nem speech.")
        return 5

    imprimir(args.model, detalhes, caps, etapas)
    dados = {
        "modelo": args.model,
        "ollama": versao,
        "host": host,
        "plataforma": sys.platform,
        "capacidades": caps,
        "detalhes": detalhes,
        "etapas": etapas,
        "quando": datetime.now().isoformat(timespec="seconds"),
    }
    if not args.sem_salvar:
        arquivo = salvar(args.model, dados, Path(args.out) if args.out else SAIDA_PADRAO)
        print(f"\nSalvo em {arquivo}")

    falhou = any("erro" in e for e in etapas.values())
    return 5 if falhou else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - console sem suporte a reconfiguração
        pass
    sys.exit(principal())
