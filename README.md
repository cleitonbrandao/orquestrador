# orquestrador — OpenCode + modelos locais

Configuração **global** do [OpenCode](https://opencode.ai) e do
[Claude Code](https://claude.com/claude-code) que monta um pipeline de agentes:
**decompor → executar em paralelo (2 slots) → testar cada parte → integrar**.
Planejamento e edição ficam com o modelo que você escolher; leitura de código e execução
de testes vão para modelos locais via [Ollama](https://ollama.com), a custo zero.

Funciona em **Windows** e **Linux/macOS**, em qualquer repositório, sem precisar de
`opencode.json` por projeto.

- Config OpenCode: [`opencode/opencode.json`](opencode/opencode.json)
- Agentes e skill do Claude Code: [`claude/`](claude/)
- Instalador Windows: [`install.ps1`](install.ps1)
- Instalador Linux/macOS: [`install.sh`](install.sh)
- Verificação: [`verify.ps1`](verify.ps1) / [`verify.sh`](verify.sh)
- Ambiente onde foi validado: [`docs/AMBIENTE.md`](docs/AMBIENTE.md)
- Decisões e evidências: [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md)
- Problemas conhecidos: [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)

---

## Como funciona

```
pedido ─► orquestrador (modelo do /models)
              │ 1. decompositor ─► PLANO: T1..Tn com arquivos exclusivos, area, rota, teste
              │ 2. no máximo SLOTS=2 subagentes por vez, respeitando dependências
              ├─► rota=edicao ─► exec-backend | exec-dados | exec-frontend | executor
              │                     └─► qwen-testes (local) ─► falhou? corrige (≤ 2x)
              ├─► rota=leve ───► local-helper (local, só leitura)
              └─► 3. integra: confere arquivos alterados + teste do conjunto ─► relatório

     local-helper e qwen-testes ─► Ollama 127.0.0.1:11434
                                   qwen3-12k (ctx 12288) · 2 slots · 100% GPU
```

| Agente | Modelo | Papel | Ferramentas permitidas |
|---|---|---|---|
| `orquestrador` | **nenhum pin** → segue o `/models` | coordena o pipeline, integra, revisa | tudo, com `shell`/`edit` em modo *ask* |
| `decompositor` | herda o da sessão | quebra o pedido em tarefas (plano) | `read`, `glob`, `grep` |
| `exec-backend` | herda o da sessão | PHP/Laravel: controllers, services, policies, jobs | `edit`, `read`, `glob`, `grep`, subagente `qwen-testes` |
| `exec-dados` | herda o da sessão | migrations, Eloquent, SQL, índices | idem |
| `exec-frontend` | herda o da sessão | Livewire, Blade, Alpine/JS, CSS | idem |
| `executor` | herda o da sessão | tarefas `geral` (config, docs, outros) | idem |
| `local-helper` | `ollama/qwen3-12k:latest` | ler e explicar código (rota `leve`) | `read`, `glob` |
| `qwen-testes` | `ollama/qwen3-12k:latest` | executar comandos e reportar saída literal | `shell` (ask), `read` |

O `orquestrador` **não tem modelo fixo de propósito**: o modelo ativo é o que você escolhe
com `/models`. Trocar o modelo no `/models` troca o modelo do orquestrador (e dos agentes
que herdam o da sessão).

Para pedidos com menos de 3 partes independentes, o orquestrador trabalha direto, sem
pipeline. Por que cada escolha (slots, 12k, especialistas por prompt, testador na GPU):
[`docs/ARQUITETURA.md`](docs/ARQUITETURA.md), Decisões 9–13.

### No Claude Code

```
/orquestrar <pedido>
```

Mesmo pipeline, com os agentes de `claude/agents/` instalados em `~/.claude/agents/`:
`decompositor`, `exec-backend`, `exec-dados`, `exec-frontend` e `executor` em `sonnet`, e
`testador` em `haiku`. O agente principal mantém no máximo 2 subagentes rodando e, quando
um executor termina, manda o `testador` rodar o teste daquela tarefa. `SLOTS` fica no
topo de `claude/skills/orquestrar/SKILL.md`.

---

## Requisitos

| Item | Versão testada | Observação |
|---|---|---|
| OpenCode | v2.1.3 | `opencode --version` |
| Ollama | 0.40.9 | `ollama --version`, escutando em `127.0.0.1:11434` |
| Node.js | v22.13.1 | necessário quando o OpenCode é instalado via npm |
| GPU | AMD RX 7600 8 GB | 2 slots de `qwen3-12k` (12288 de contexto) = 6,9 GB, 100% GPU |
| RAM | 19.9 GB | fallback em CPU quando a VRAM não cabe |

Sem GPU dedicada dá para usar mesmo assim, com dois ajustes: reduzir o contexto do modelo
derivado (ver [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)) ou apontar os agentes
locais para um modelo de nuvem trocando `agents.<id>.model` no JSON.

---

## Instalação

### Windows (PowerShell 5.1+)

```powershell
git clone https://github.com/cleitonbrandao/orquestrador.git "$HOME\Documents\projetos\orquestrador"
cd "$HOME\Documents\projetos\orquestrador"
.\install.ps1
```

Opções:

```powershell
.\install.ps1 -BaseModel qwen3:8b -Context 12288   # padrão (cria qwen3-12k)
.\install.ps1 -OllamaParallel 3                     # slots no Ollama (padrão 2)
.\install.ps1 -SkipOllamaEnv                        # não grava as variáveis OLLAMA_*
.\install.ps1 -SkipClaude                           # não instala em ~/.claude
.\install.ps1 -SkipModel                            # não mexe no Ollama
.\install.ps1 -Link                                 # tenta symlink (precisa de modo desenvolvedor/admin)
```

### Linux / macOS

```bash
git clone https://github.com/cleitonbrandao/orquestrador.git ~/Documentos/projetos/orquestrador
cd ~/Documentos/projetos/orquestrador
./install.sh
```

Opções:

```bash
./install.sh --model qwen3:8b --ctx 12288   # padrão (cria qwen3-12k)
./install.sh --parallel 3                   # mostra as variáveis OLLAMA_* para 3 slots
./install.sh --no-claude                    # não instala em ~/.claude
./install.sh --no-model                     # não mexe no Ollama
./install.sh --link                         # symlink em vez de cópia (recomendado p/ editar no repo)
```

### O que o instalador faz

1. Faz **backup** do `opencode.json` atual (`.bak.<timestamp>`).
2. Copia `opencode/opencode.json` para o config global:
   - Windows: `%USERPROFILE%\.config\opencode\opencode.json`
   - Linux/macOS: `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json`
3. Garante o modelo derivado `qwen3-12k` no Ollama (o nome segue o contexto):
   ```
   FROM qwen3:8b
   PARAMETER num_ctx 12288
   ```
   (`ollama create qwen3-12k -f <Modelfile>`), pulando se já existir.
5. Variáveis do Ollama para 2 slots: `OLLAMA_NUM_PARALLEL=2`, `OLLAMA_MAX_LOADED_MODELS=1`,
   `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`. No Windows grava como variável
   de usuário (feche e reabra o Ollama na bandeja); no Linux/macOS mostra o
   `systemctl edit ollama` / `launchctl setenv` para você aplicar.
6. Copia (ou linka, com `-Link`/`--link`) `claude/agents/*.md` para `~/.claude/agents/` e
   a skill para `~/.claude/skills/orquestrar/`, com backup do que for diferente.
4. Confere os pré-requisitos (`opencode`, `ollama`, `node`) e imprime os próximos passos.

O instalador **não** faz login em provider nenhum e **não** baixa modelo de 5 GB sem aviso:
se `qwen3:8b` não estiver presente, ele instrui o `ollama pull qwen3:8b`.

Depois de instalar, **reinicie o OpenCode** — configuração não tem hot-reload completo.

---

## Escolher o modelo do orquestrador

Dentro do OpenCode, use `/models` e escolha o modelo. O `orquestrador` passa a usar esse
modelo na sessão; nenhum arquivo precisa ser editado.

Para fixar um modelo padrão (opcional), adicione a chave `model` no topo do
`opencode.json` ou em `agents.orquestrador.model` — mas saiba que isso **anula** o
comportamento de seguir o `/models`.

---

## Providers e plugins (opcional)

A config também carrega, de forma opcional:

- `plugin: ["opencode-antigravity-auth@latest"]` — habilita os modelos `antigravity-*`;
- `provider.google.models` — Gemini 3 Pro/Flash e Claude Sonnet/Opus via Antigravity;
- `mcp.trail` **desabilitado** — só faz sentido em repositórios indexados pelo `trail`.

Nada disso é necessário para a orquestração local. Se você não usa Google, apague o bloco
`provider` e o `plugin`. Os modelos `antigravity-*` exigem `/auth` com OAuth do Antigravity
— API key do Google **não** serve para eles.

---

## Verificação

```powershell
# Windows
.\verify.ps1
```

```bash
# Linux/macOS
./verify.sh
```

O script confere:

1. `opencode` e `ollama` disponíveis e suas versões.
2. `opencode.json` é JSON válido e está no caminho global correto.
3. `qwen3-12k` existe no Ollama com `num_ctx 12288`.
4. `opencode debug agents` mostra os oito agentes e as permissões efetivas
   (`execute: deny` nos subagentes, `shell: ask` no `qwen-testes`, `shell: deny` e
   `subagent` só `qwen-testes` nos executores, `edit: deny` no `decompositor`).
5. Variáveis `OLLAMA_*` dos slots e se o `ollama ps` mostra uso de CPU.
6. Agentes e skill do Claude Code em `~/.claude`.

Teste manual de ponta a ponta (custa tempo, não custa dinheiro):

```
Delegue ao qwen-testes rodar: git --version
```

Resposta esperada, no formato do agente:

```
COMANDO: git --version
SAIDA: git version 2.x.y...
RESULTADO: bloqueado
```

`bloqueado` é correto: o comando não produziu saída de teste (`OK (`, `FAILURES!`,
`ERRORS!`). Se o agente inventar contagem de testes, veja
[`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

---

## Segurança

Os subagentes rodam com o **mínimo de ferramentas** e uma lista explícita de negações:

- `edit`, `execute` (Code Mode), `subagent`, `question`, `webfetch`, `websearch`,
  `external_directory` — negados nos dois subagentes locais;
- `read` de `*.env`, `*.env.*`, `*.pem`, `*.key`, `*id_rsa*` — negado em todos os
  subagentes (`*.env.example` liberado por ser template);
- `qwen-testes`: `composer *`, `npm *`, `php artisan migrate*`, `php artisan db:*`,
  `docker *`, `Remove-Item *`, `rm *` — negados;
- `decompositor`: só lê (`edit`, `shell`, `subagent` negados);
- executores (`exec-*`, `executor`): **editam sem pedir confirmação** (subagente não tem
  prompt de permissão, ver Decisão 5), mas não rodam `shell`, não editam `.env`/chaves e
  só podem acionar o `qwen-testes`. Revise o `git diff` que o orquestrador apresenta no
  relatório final.

Regras de permissão são avaliadas em ordem e **o último match vence**; por isso as
negações específicas vêm depois do `*: allow` padrão.

Arquivos de credencial (`*accounts*.json`, `secrets*`) são ignorados pelo `.gitignore`.
Tokens de provider ficam em `~/.config/opencode/` e nunca neste repositório.

---

## Estrutura

```
orquestrador/
├── install.sh / install.ps1     # instaladores (Linux/macOS · Windows)
├── verify.sh  / verify.ps1      # verificação do ambiente
├── opencode/
│   └── opencode.json            # config global (sem segredos)
├── claude/
│   ├── agents/                  # decompositor, exec-*, executor, testador
│   └── skills/orquestrar/       # skill /orquestrar (SLOTS no topo)
├── docs/
│   ├── AMBIENTE.md              # setup exato onde foi validado
│   ├── ARQUITETURA.md           # decisões, permissões e evidências
│   ├── TROUBLESHOOTING.md       # armadilhas conhecidas
│   └── esboco_possivel_estrutura.png  # esboço original do pipeline
└── .gitignore
```

---

## Limitações conhecidas (resumo)

| Sintoma | Causa | Solução |
|---|---|---|
| Agente local não chama ferramenta | modelo sem suporte a `tool_calls` | usar `qwen3-12k` (ver TROUBLESHOOTING) |
| `ollama ps` mostra CPU com 2 slots | contexto grande demais ou variáveis OLLAMA_* não aplicadas | ver TROUBLESHOOTING |
| `opencode` no PowerShell é a v1.x | Chocolatey antes do npm no PATH | ver TROUBLESHOOTING |
| Contexto sempre 4096 | `num_ctx` via config de provider é ignorado | modelo derivado com `PARAMETER num_ctx` |
| Sessão nova cai em modelo pago | `OPENCODE_CONFIG_CONTENT` antiga no serviço | limpar a variável e reiniciar |
| `opencode run --agent X` usa modelo errado | bug/limitação v2.1.3 | passar `--model` explícito |

Detalhes e comandos de diagnóstico em [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).
