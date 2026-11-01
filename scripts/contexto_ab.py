#!/usr/bin/env python3
"""Liga/desliga a regra CONTEXTO do orquestrador para o A/B da Fase 6.

O A/B precisa dos dois braços com o **mesmo** prompt, mudando só a regra. Este
script edita a config global (`~/.config/opencode/opencode.json`), com backup, e
nunca toca no arquivo do repositório — que é a fonte canônica do texto.

  python3 scripts/contexto_ab.py --status
  python3 scripts/contexto_ab.py --off     # braço A (baseline)
  python3 scripts/contexto_ab.py --on      # braço B (com a regra)
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[1]
CONFIG_REPO = RAIZ_REPO / "opencode" / "opencode.json"
CONFIG_GLOBAL = Path(os.environ.get("OPENCODE_CONFIG") or
                     Path.home() / ".config" / "opencode" / "opencode.json")

INICIO = "CONTEXTO (regra de custo):"
FIM = "\n\nTRIAGEM (regra, antes de tudo):"


def extrair(texto: str) -> str:
    """Parágrafo da regra CONTEXTO (sem os separadores), ou '' se ausente."""
    pos = texto.find(INICIO)
    if pos < 0:
        return ""
    fim = texto.find(FIM, pos)
    if fim < 0:
        return texto[pos:].strip()
    return texto[pos:fim].strip()


def desligar(texto: str) -> str:
    regra = extrair(texto)
    if not regra:
        return texto
    for sufixo in ("\n\n", "\n", " "):
        trecho = regra + sufixo
        if trecho in texto:
            return texto.replace(trecho, "", 1)
    return texto.replace(regra, "", 1)


def ligar(texto: str, regra: str) -> str:
    if not regra:
        raise ValueError("regra canônica vazia")
    if extrair(texto):
        return texto
    alvo = FIM.lstrip("\n")
    if alvo not in texto:
        raise ValueError("âncora 'TRIAGEM (regra, antes de tudo):' não encontrada")
    return texto.replace(alvo, regra + "\n\n" + alvo)


def regra_canonica() -> str:
    dados = json.loads(CONFIG_REPO.read_text(encoding="utf-8"))
    return extrair(dados["agents"]["orquestrador"]["system"])


def servidor_canonico() -> dict:
    """Config MCP canônica do servidor `contexto` (do repositório)."""
    dados = json.loads(CONFIG_REPO.read_text(encoding="utf-8"))
    try:
        return dict(dados["mcp"]["servers"]["contexto"])
    except KeyError as exc:
        raise ValueError("servidor 'contexto' ausente no opencode.json do repositório") from exc


def _ler(config: Path) -> dict:
    return json.loads(config.read_text(encoding="utf-8"))


def _gravar(config: Path, dados: dict) -> None:
    backup = config.with_name(config.name + ".bak." + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    shutil.copy2(config, backup)
    config.write_text(json.dumps(dados, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  backup: {backup}")


def principal(argv=None) -> int:
    p = argparse.ArgumentParser(description="Alterna a regra CONTEXTO do orquestrador.")
    grupo = p.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--on", action="store_true", help="liga a regra (braço B)")
    grupo.add_argument("--off", action="store_true", help="desliga a regra (braço A)")
    grupo.add_argument("--status", action="store_true", help="só mostra o estado")
    p.add_argument("--config", type=Path, default=CONFIG_GLOBAL, help="config alvo")
    args = p.parse_args(argv)

    config = args.config.expanduser()
    if not config.is_file():
        print(f"config não encontrada: {config}", file=sys.stderr)
        return 2
    if config.resolve() == CONFIG_REPO.resolve():
        print("recusado: a config do repositório é a fonte canônica; edite a global", file=sys.stderr)
        return 2

    dados = _ler(config)
    sistema = dados["agents"]["orquestrador"]["system"]
    ligada = bool(extrair(sistema))
    servidores = (dados.get("mcp") or {}).get("servers") or {}
    tem_servidor = "contexto" in servidores

    if args.status:
        print(f"  config:  {config}")
        print(f"  regra:   {'LIGADA (braço B)' if ligada else 'DESLIGADA (braço A)'}")
        print(f"  MCP:     {'presente' if tem_servidor else 'ausente (braço A limpo)'}")
        return 0

    if args.on and ligada and tem_servidor:
        print("  já está ligado (regra + MCP)")
        return 0
    if args.off and not ligada and not tem_servidor:
        print("  já está desligado (regra + MCP)")
        return 0

    if args.off:
        dados["agents"]["orquestrador"]["system"] = desligar(sistema)
        servidores.pop("contexto", None)
        _gravar(config, dados)
        print("  regra CONTEXTO desligada e MCP 'contexto' removido (braço A)")
    else:
        dados["agents"]["orquestrador"]["system"] = ligar(sistema, regra_canonica())
        if not tem_servidor:
            dados.setdefault("mcp", {}).setdefault("servers", {})["contexto"] = servidor_canonico()
        _gravar(config, dados)
        print("  regra CONTEXTO ligada e MCP 'contexto' garantido (braço B)")
    print("  reinicie o OpenCode para a config valer")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
