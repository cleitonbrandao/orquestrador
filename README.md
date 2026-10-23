# dotfiles — opencode

Configuração global do [opencode](https://opencode.ai) replicável em qualquer máquina.
Cobre a **camada global** (`~/.config/opencode/opencode.json`): plugin de auth e definições
dos modelos Gemini/Claude. A **camada de projeto** (agentes orquestrador/local-helper,
provider Ollama, MCP trail) viaja no `opencode.json` da raiz de cada projeto (ex.: softnews-notion)
e não precisa deste repo.

## Estrutura

```
dotfiles/
├── install.sh               # cria o symlink da config global (idempotente, com backup)
├── .gitignore               # bloqueia credenciais (*accounts*.json etc.)
└── opencode/
    ├── opencode.json        # config global sanitizada (sem segredos)
    └── env.example          # vars opcionais p/ trocar modelos locais sem editar JSON
```

## Setup em uma máquina nova

```bash
# 1. Pré-requisitos
curl -fsSL https://opencode.ai/install | bash   # opencode
# Ollama: https://ollama.com/download
ollama pull qwen2.5-coder:7b                    # modelo do local-helper
npm i -g @trailhq/trail-code                    # MCP trail (usado por projetos indexados)

# 2. Este repo
git clone git@github.com:cleitonbrandao/dotfiles.git ~/Documentos/projetos/dotfiles
cd ~/Documentos/projetos/dotfiles
./install.sh

# 3. Login dos providers (por máquina, dentro do opencode) — tokens NUNCA são commitados
opencode

# 4. Clonar o projeto e abrir — a config de projeto carrega sozinha
git clone git@github.com:cleitonbrandao/softnews-notion.git
cd softnews-notion && opencode
```

Depois de qualquer mudança em `opencode.json` (global ou de projeto), **reinicie o opencode** —
config não tem hot-reload.

## Trocar os modelos locais

Os modelos dos agentes locais (`local-helper`, `qwen-testes`) vêm de variáveis de ambiente
com default para `ollama/qwen2.5-coder:7b`. Para trocar sem editar JSON:

```bash
# ~/.zshrc
export LOCAL_HELPER_MODEL=ollama/qwen3:8b        # após: ollama pull qwen3:8b
export QWEN_TESTES_MODEL=google/gemini-2.5-flash # máquina sem GPU? aponte p/ nuvem
```

Atenção: modelos Ollama novos precisam ser declarados uma vez no mapa
`provider.ollama.models` do `opencode.json` **do projeto** (chaves de mapa não aceitam env).

## Regras de ouro

- `~/.config/opencode/antigravity-accounts.json` e qualquer `*accounts*.json` contêm
  tokens e **jamais** entram neste repo (o `.gitignore` já bloqueia).
- Edições na config global devem ser feitas **neste repo** (o alvo é um symlink) e
  sincronizadas com `git pull` nas demais máquinas.
