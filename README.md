# orquestrador — OpenCode + modelos locais

Configuração **global** do [OpenCode](https://opencode.ai) que monta uma orquestração de
orquestrador (modelo que você escolher) que delega leitura de código a um modelo local e
executa testes por uma ferramenta determinística via [Ollama](https://ollama.com), com custo zero
nessas duas tarefas.

Funciona em **Windows** e **Linux/macOS**, em qualquer repositório, sem precisar de
`opencode.json` por projeto.

- Config: [`opencode/opencode.json`](opencode/opencode.json)
- Uso com o Claude Code: [`docs/CLAUDE-CODE.md`](docs/CLAUDE-CODE.md)
- Servidor de testes: [`mcp/run_tests/server.py`](mcp/run_tests/server.py)
- Instalador Windows: [`install.ps1`](install.ps1)
- Instalador Linux/macOS: [`install.sh`](install.sh)
- Verificação: [`verify.ps1`](verify.ps1) / [`verify.sh`](verify.sh)
- Ambiente onde foi validado: [`docs/AMBIENTE.md`](docs/AMBIENTE.md)
- Decisões e evidências: [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md)
- Problemas conhecidos: [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)
- Testes de modelos para suporte e análise de texto (trilhas E e F): [`docs/PLANO-TESTES-SUPORTE.md`](docs/PLANO-TESTES-SUPORTE.md)
- Benchmark multimodal (texto, imagem, áudio, fala): [`docs/BENCH-OMNI.md`](docs/BENCH-OMNI.md)
- Distribuição local vs. pago: [`docs/DISTRIBUICAO.md`](docs/DISTRIBUICAO.md)
- Consumo e economia de tokens por agente/dia — gráfico no terminal: `/custo` em [`scripts/modelos.sh`](scripts/modelos.sh) ou [`scripts/custo_agentes.py`](scripts/custo_agentes.py)
- Contexto resumido no local antes da sessão paga: [`scripts/contexto_local.py`](scripts/contexto_local.py) (`/ctx` no terminal de modelos)
- Adesão ao MCP de contexto (quantas sessões usaram em vez de ler): [`scripts/contexto_adocao.py`](scripts/contexto_adocao.py)

---

## Como funciona

```
   ┌──────────────────────────────────────┐
   │ orquestrador (mode: primary)         │
   │ modelo = o escolhido no /models      │
   │ shell: ask · edit: ask               │
   └───────┬──────────────────────┬───────┘
           │ Task / subagente     │ MCP (stdio)
           ▼                      ▼
 ┌───────────────────────┐  ┌──────────────────────────┐
 │ local-helper 4B       │  │ run_tests (mcp/run_tests)│
 │ kb + trail + read     │  │ sem LLM: allowlist,      │
 │ (qwen3.5-4b-16k)      │  │ exit code real, veredito │
 └───────────────────────┘  └──────────────────────────┘
```

| Componente | Modelo / tipo | Papel |
|---|---|---|
| `orquestrador` | primary, **sem pin** (segue `/models`) | arquitetura, mudanças complexas, integração; não lê PHP/SQL — delega |
| `decompositor` | `ollama/qwen3.5-2b-32k:latest` | quebrar pedido em tarefas (read-only) |
| `local-helper` | `ollama/gemma4-e2b-32k:latest` | ler/explicar código; usa `kb` e `trail` |
| `local-mini` | `ollama/qwen3.5-08b-32k:latest` | leitura pontual de um trecho/arquivo curto |
| `revisor` | `ollama/qwen3.5-2b-32k:latest` | revisão advisory do diff, sem ferramentas |
| `exec-local` | `ollama/gemma4-e2b-32k:latest` | edição pequena em **um** arquivo, com teste determinístico |
| `exec-docs` | `ollama/gemma4-e2b-32k:latest` | editar Markdown; verificação fica no orquestrador |
| `executor` | modelo principal | edição geral (o que não é arquivo único) |
| `exec-backend` | modelo principal | PHP/Laravel: rotas, models, policies, jobs |
| `exec-dados` | modelo principal | migrations, Eloquent, SQL, índices |
| `exec-frontend` | modelo principal | Livewire, Blade, JS, CSS |
| `run_tests` | MCP determinístico (Python stdlib) | rodar testes e devolver saída literal |
| `kb` / `trail` | MCP | busca por trechos e grafo de símbolos |
| `decisao` | MCP + `d3:2b` | triagem local (`orq_decidir`): só docs? qual área? escala ou não |
| `contexto` | MCP + `qwen3.5-2b-32k` | pacote de contexto (§6) com regras/decisões do projeto |

Os cinco agentes em **modelo principal** são o orquestrador e os quatro executores de
código (`executor`, `exec-backend`, `exec-dados`, `exec-frontend`). O resto roda local:
a decisão de manter código neles está em [`docs/DISTRIBUICAO.md`](docs/DISTRIBUICAO.md).

**Modelos de decisão** (`d3`, `tev1`) não geram texto e usam `/v1/systemone`. O `/test` detecta a
capacidade `decision` e cai na trilha E (`scripts/testar-decisor.sh`), que mede **acerto em casos
rotulados, taxa de escalada e latência** — não tok/s. Dataset em `casos/suporte/decisao/`.

**Por que `run_tests` e não um agente LLM:** rodar um comando e devolver stdout + exit code
não exige modelo; um modelo pequeno só acrescenta o risco de "inventar" o resultado.
Veredito: `passou` = exit 0 · `falhou` = exit ≠ 0 · `bloqueado` = recusado, inexistente ou
timeout (tratar como *não verificado*). Allowlist: phpunit/pest, `php artisan test`,
`composer test`, `npm|pnpm|yarn test`, vitest/jest, pytest, `go|cargo|dotnet test`,
`mvn|gradle test`. Estenda com `ORQ_TESTS_ALLOW="regex;;regex"`. Pipes, `;`, `&`, `>` e
`$()` são recusados; `install`, `migrate`, `db:`, `rm`, `docker`, `curl` também.
Instalados como `orq-run-tests`, `orq-kb`, `orq-decisor` e `orq-contexto` em `~/.local/bin` (Windows: `.cmd` em `%USERPROFILE%\.local\bin`).
No Windows, o instalador também coloca essa pasta no `PATH` do usuário.

O `orquestrador` **não tem modelo fixo de propósito**: o modelo ativo é o que você escolhe
com `/models`. Trocar o modelo no `/models` troca o modelo do orquestrador.

---

## Requisitos

| Item | Versão testada | Observação |
|---|---|---|
| OpenCode | v2.1.3 | `opencode --version` |
| Ollama | 0.40.9 | `ollama --version`, escutando em `127.0.0.1:11434` |
| Node.js | v22.13.1 | necessário quando o OpenCode é instalado via npm |
| GPU | AMD RX 7600 8 GB | 8 GB de VRAM comportam `qwen3.5-4b-16k` a 16384 de contexto |
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
.\install.ps1 -BaseModel qwen3.5:4b -Context 16384 # padrão
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
./install.sh --model qwen3.5:4b --ctx 16384 # padrão do 4B
./install.sh --no-model                     # não mexe no Ollama
./install.sh --link                         # symlink em vez de cópia (recomendado p/ editar no repo)
```

### O que o instalador faz

1. Faz **backup** do `opencode.json` atual (`.bak.<timestamp>`).
2. Copia `opencode/opencode.json` para o config global:
   - Windows: `%USERPROFILE%\.config\opencode\opencode.json`
   - Linux/macOS: `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json`
3. Copia o plugin `opencode/plugins/ollama-nothink.ts` para
   `.../opencode/plugins/ollama-nothink.ts`. Ele injeta
   `reasoning_effort: "none"` nas requisições do provider `ollama`; sem isso, o
   `qwen3.5:4b` pensa e trava a sessão.
4. Garante os modelos derivados no Ollama, pulando os que já existem:
   ```
   qwen3.5-2b-32k   FROM qwen3.5:2b    PARAMETER num_ctx 32768
   gemma4-e2b-32k   FROM gemma4:e2b    PARAMETER num_ctx 32768
   qwen3.5-08b-32k  FROM qwen3.5:0.8b  PARAMETER num_ctx 32768
   ```
5. Confere os pré-requisitos (`opencode`, `ollama`, `node`) e imprime os próximos passos.

O instalador **não** faz login em provider nenhum e **não** baixa modelo de 5 GB sem aviso:
se um modelo base não estiver presente, ele instrui o `ollama pull` correspondente.

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
- `mcp.servers` — `run_tests`, `kb` e `trail`, todos com `codemode: false` para
  expor as ferramentas MCP diretamente aos subagentes. O `trail` é útil em
  repositórios indexados com `trail build` (gera `graft/`, já ignorado pelo git);
  sem índice, o servidor conecta mas não responde consultas.
- plugin local `plugins/ollama-nothink.ts` — carregado automaticamente de
  `~/.config/opencode/plugins/`; desliga o thinking do Ollama.

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
3. `qwen3.5-2b-32k`, `gemma4-e2b-32k` e `qwen3.5-08b-32k` existem no Ollama e
   carregam com `num_ctx` 32768 (abaixo disso a auto-compactação degenera).
4. O plugin `plugins/ollama-nothink.ts` está presente.
5. `opencode debug agents` mostra os agentes e as permissões efetivas
   (`execute: deny` no `local-helper`); `run_tests` responde a comandos permitidos e
   bloqueados; `kb`, `trail` e `decisao` aparecem conectados em `opencode mcp list`.

Teste manual de ponta a ponta (custa tempo, não custa dinheiro):

```
Use run_tests para rodar: git --version
```

Resposta esperada, no formato do agente:

```
COMANDO: git --version
SAIDA: git version 2.x.y...
RESULTADO: passou
```

`passou` = exit code 0 real. Se o agente inventar contagem de testes, veja
[`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

---

## Escopo dos testes

Para não perder tempo rodando áreas não afetadas, a orquestração segue a regra de
**escopo mínimo**:

- Cada tarefa do plano traz um `comando_teste` restrito ao fluxo alterado (filter por
  arquivo/classe/método), nunca a suite inteira.
- O executor roda **apenas** esse comando via `run_tests`; se não houver teste
  específico para o escopo, o comando é `nenhum` e a tarefa é validada por inspeção.
- Na etapa `INTEGRAR`, o orquestrador roda somente os testes dos arquivos tocados pela
  mudança (ou o teste de integração dedicado ao fluxo, se existir) — nunca a suite
  completa nem áreas não afetadas.
- Se um fluxo novo for desenvolvido, testa-se apenas aquele escopo.

Essa regra está embutida nos prompts dos agentes (`orquestrador`, `decompositor` e
executores) em `opencode/opencode.json`.

---

## Segurança

O subagente roda com o **mínimo de ferramentas** e uma lista explícita de negações:

- `edit`, `execute` (Code Mode), `subagent`, `question`, `webfetch`, `websearch`,
  `external_directory` — negados no `local-helper`; as ferramentas MCP `kb`, `trail` e
  `run_tests` ficam disponíveis diretamente porque os servidores usam `codemode: false`;
- `read` de `*.env`, `*.env.*`, `*.pem`, `*.key`, `*id_rsa*` — negado
  (`*.env.example` liberado por ser template);
- `run_tests`: só comandos da allowlist; recusa `install`, `migrate`, `db:`, `rm`, `docker`,
  `curl` e qualquer encadeamento (`; & | > $()`).

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
│   ├── opencode.json            # config global (sem segredos)
│   └── plugins/
│       └── ollama-nothink.ts    # reasoning_effort: none para o Ollama
├── mcp/
│   ├── run_tests/server.py      # MCP: testes com saída condensada
│   ├── kb/kb.py                 # MCP + CLI: base de conhecimento por app (BM25 + embeddings opcionais)
│   ├── decisao/server.py        # MCP: triagem local (d3)
│   └── contexto/server.py       # MCP: pacote de contexto + regras/decisões (roadmap §10)
├── claude/                      # subagente `triagem` e trecho de CLAUDE.md (ver docs/CLAUDE-CODE.md)
├── docs/
│   ├── AMBIENTE.md              # setup exato onde foi validado
│   ├── ARQUITETURA.md           # decisões, permissões e evidências
│   ├── BENCH-OMNI.md            # benchmark multimodal (texto, imagem, áudio, fala)
│   ├── DISTRIBUICAO.md          # o que roda local, o que fica no modelo pago e por quê
│   └── TROUBLESHOOTING.md       # armadilhas conhecidas
└── .gitignore
```

---

## Limitações conhecidas (resumo)

| Sintoma | Causa | Solução |
|---|---|---|
| Agente local não chama ferramenta | modelo sem suporte a `tool_calls` | usar `qwen3.5-4b-16k` (ver TROUBLESHOOTING) |
| Modelo local pensa e trava | OpenCode 2.1.3 ignora `body` de provider/modelo | plugin `ollama-nothink.ts` (já instalado) |
| Contexto sempre 4096 | `num_ctx` via config de provider é ignorado | modelo derivado com `PARAMETER num_ctx` |
| `exec-docs` 4B edita mas não retorna | o 4B antigo entra em loop após a edição | `exec-docs` usa `gemma4-e4b-16k`; verificação fica no orquestrador |
| Sessão nova cai em modelo pago | `OPENCODE_CONFIG_CONTENT` antiga no serviço | limpar a variável e reiniciar |
| `opencode run --agent X` usa modelo errado | bug/limitação v2.1.3 | passar `--model` explícito |
| `lfm3-omni` / `lfm3-audio` não instalam | `nvfp4` exige runtime MLX; 0.40.12 só Apple Silicon | aguardar suporte a Linux/Windows (ver BENCH-OMNI) |

Detalhes e comandos de diagnóstico em [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).
