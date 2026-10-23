# orquestrador — OpenCode + modelos locais

Configuração **global** do [OpenCode](https://opencode.ai) que monta uma orquestração de
três agentes: um orquestrador (modelo que você escolher) delegando leitura de código e
execução de testes para modelos locais via [Ollama](https://ollama.com), com custo zero
nessas duas tarefas.

Funciona em **Windows** e **Linux/macOS**, em qualquer repositório, sem precisar de
`opencode.json` por projeto.

- Config: [`opencode/opencode.json`](opencode/opencode.json)
- Instalador Windows: [`install.ps1`](install.ps1)
- Instalador Linux/macOS: [`install.sh`](install.sh)
- Verificação: [`verify.ps1`](verify.ps1) / [`verify.sh`](verify.sh)
- Ambiente onde foi validado: [`docs/AMBIENTE.md`](docs/AMBIENTE.md)
- Decisões e evidências: [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md)
- Problemas conhecidos: [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)

---

## Como funciona

```
                       ┌──────────────────────────────────────┐
                       │ orquestrador (mode: primary)         │
                       │ modelo = o escolhido no /models      │
                       │ shell: ask · edit: ask               │
                       └───────────────┬──────────────────────┘
                                       │ Task / subagente
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
      ┌───────────────────────────┐        ┌────────────────────────────┐
      │ local-helper              │        │ qwen-testes                │
      │ ollama/qwen3-16k:latest   │        │ ollama/qwen3-16k:latest    │
      │ read + glob               │        │ shell (ask) + read         │
      │ sem edit/shell/execute    │        │ sem edit/execute/subagent  │
      └───────────────────────────┘        └────────────────────────────┘
                    │                                     │
                    └──────────► Ollama 127.0.0.1:11434 ◄┘
                                 (modelo derivado, ctx 16384)
```

| Agente | Modelo | Papel | Ferramentas permitidas |
|---|---|---|---|
| `orquestrador` | **nenhum pin** → segue o `/models` | arquitetura, mudanças complexas, revisão | tudo, com `shell`/`edit` em modo *ask* |
| `local-helper` | `ollama/qwen3-16k:latest` | ler e explicar código, sugerir testes | `read`, `glob` |
| `qwen-testes` | `ollama/qwen3-16k:latest` | executar comandos e reportar saída literal | `shell` (ask), `read` |

O `orquestrador` **não tem modelo fixo de propósito**: o modelo ativo é o que você escolhe
com `/models`. Trocar o modelo no `/models` troca o modelo do orquestrador.

---

## Requisitos

| Item | Versão testada | Observação |
|---|---|---|
| OpenCode | v2.1.3 | `opencode --version` |
| Ollama | 0.40.9 | `ollama --version`, escutando em `127.0.0.1:11434` |
| Node.js | v22.13.1 | necessário quando o OpenCode é instalado via npm |
| GPU | AMD RX 7600 8 GB | 8 GB de VRAM comportam `qwen3-16k` a 16384 de contexto |
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
.\install.ps1 -BaseModel qwen3:8b -Context 16384   # padrão
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
./install.sh --model qwen3:8b --ctx 16384   # padrão
./install.sh --no-model                     # não mexe no Ollama
./install.sh --link                         # symlink em vez de cópia (recomendado p/ editar no repo)
```

### O que o instalador faz

1. Faz **backup** do `opencode.json` atual (`.bak.<timestamp>`).
2. Copia `opencode/opencode.json` para o config global:
   - Windows: `%USERPROFILE%\.config\opencode\opencode.json`
   - Linux/macOS: `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json`
3. Garante o modelo derivado `qwen3-16k` no Ollama:
   ```
   FROM qwen3:8b
   PARAMETER num_ctx 16384
   ```
   (`ollama create qwen3-16k -f <Modelfile>`), pulando se já existir.
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
3. `qwen3-16k` existe no Ollama e carrega com `context_length: 16384`.
4. `opencode debug agents` mostra os três agentes e as permissões efetivas
   (`execute: deny` nos subagentes, `shell: ask` no `qwen-testes`).

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
  `external_directory` — negados nos dois subagentes;
- `read` de `*.env`, `*.env.*`, `*.pem`, `*.key`, `*id_rsa*` — negado
  (`*.env.example` liberado por ser template);
- `qwen-testes`: `composer *`, `npm *`, `php artisan migrate*`, `php artisan db:*`,
  `docker *`, `Remove-Item *`, `rm *` — negados.

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
├── docs/
│   ├── AMBIENTE.md              # setup exato onde foi validado
│   ├── ARQUITETURA.md           # decisões, permissões e evidências
│   └── TROUBLESHOOTING.md       # armadilhas conhecidas
└── .gitignore
```

---

## Limitações conhecidas (resumo)

| Sintoma | Causa | Solução |
|---|---|---|
| Agente local não chama ferramenta | modelo sem suporte a `tool_calls` | usar `qwen3-16k` (ver TROUBLESHOOTING) |
| Contexto sempre 4096 | `num_ctx` via config de provider é ignorado | modelo derivado com `PARAMETER num_ctx` |
| Sessão nova cai em modelo pago | `OPENCODE_CONFIG_CONTENT` antiga no serviço | limpar a variável e reiniciar |
| `opencode run --agent X` usa modelo errado | bug/limitação v2.1.3 | passar `--model` explícito |

Detalhes e comandos de diagnóstico em [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).
