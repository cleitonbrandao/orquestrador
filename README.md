# orquestrador — opencode

Configuração **global** do [opencode](https://opencode.ai) que liga a orquestração em
**qualquer repositório**, sem precisar de `opencode.json` por projeto. Aplicada via symlink
em `~/.config/opencode/opencode.json`.

## O que fica global (vale em qualquer repo)

| Item | Efeito |
|---|---|
| `default_agent: orquestrador` | Toda sessão inicia no orquestrador, que delega o trabalho simples ao `local-helper` |
| agentes `orquestrador`, `local-helper`, `qwen-testes` | Disponíveis por padrão; `Tab` troca de agente |
| provider `ollama` (localhost:11434) | Modelos locais prontos para os agentes |
| plugin `opencode-antigravity-auth` + modelos Gemini/Claude | Providers de nuvem disponíveis |
| MCP `trail` **desabilitado** | Só liga em repositórios indexados pelo trail (ver abaixo) |

## Estrutura

```
orquestrador/
├── install.sh               # symlink + backup automático + checagem de pré-requisitos
├── .gitignore               # bloqueia credenciais (*accounts*.json etc.)
└── opencode/
    ├── opencode.json        # config global (sem segredos)
    └── env.example          # vars opcionais p/ trocar modelos locais sem editar JSON
```

## Setup em uma máquina nova

```bash
# 1. Pré-requisitos
curl -fsSL https://opencode.ai/install | bash   # opencode
# Ollama: https://ollama.com/download
ollama pull qwen2.5-coder:7b                    # modelo do local-helper
npm i -g @trailhq/trail-code                    # opcional, p/ projetos indexados pelo trail

# 2. Este repo
git clone https://github.com/cleitonbrandao/orquestrador.git ~/Documentos/projetos/orquestrador
cd ~/Documentos/projetos/orquestrador && ./install.sh

# 3. Login dos providers (por máquina, dentro do opencode) — tokens NUNCA são commitados
opencode
```

Depois disso, **qualquer** projeto já abre com a orquestração. Após qualquer mudança em
`opencode.json`, **reinicie o opencode** — config não tem hot-reload.

## Usar em qualquer repositório

Nada a fazer: a config global é carregada em todo projeto. O projeto só precisa de um
`opencode.json` próprio quando quiser algo específico, e esse arquivo **sobrescreve** o
global (deep merge), por exemplo:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "trail": { "type": "local", "command": ["trail", "mcp"], "enabled": true }
  }
}
```

Esse é o caso do MCP `trail`: ele é por repositório (o índice `.trail/` é local), por isso
fica desabilitado no global e é ligado só nos repos que rodaram `trail init`/`trail build`.

Para usar outro agente como padrão em um projeto específico:
`{ "default_agent": "build" }` no `opencode.json` do projeto.

## Trocar os modelos locais

Os modelos dos agentes locais vêm de variáveis de ambiente, com default
`ollama/qwen2.5-coder:7b`:

```bash
# ~/.zshrc
export LOCAL_HELPER_MODEL=ollama/qwen3:8b        # após: ollama pull qwen3:8b
export QWEN_TESTES_MODEL=google/gemini-2.5-flash # máquina sem GPU? aponte p/ nuvem
```

Modelo Ollama novo precisa ser declarado uma vez no mapa `provider.ollama.models` deste
`opencode.json` (chaves de mapa não aceitam env) e baixado com `ollama pull`. Modelos de
nuvem já declarados (provider `google`) funcionam direto.

## Regras de ouro

- `~/.config/opencode/antigravity-accounts.json` e qualquer `*accounts*.json` contêm
  tokens e **jamais** entram neste repo (o `.gitignore` já bloqueia).
- Edições na config global devem ser feitas **neste repo** (o alvo é um symlink) e
  sincronizadas com `git pull` nas demais máquinas.
