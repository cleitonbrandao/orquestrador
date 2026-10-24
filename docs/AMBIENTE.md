# Ambiente de referência

Este é o setup **real** onde a configuração deste repositório foi montada e validada.
Nada aqui é estimativa: cada número foi medido na máquina descrita.

Data da medição: **2026-10-23**.

## Máquina

| Item | Valor | Como conferir |
|---|---|---|
| Sistema | Windows 11 Pro, 10.0.26300, 64 bits | `Get-CimInstance Win32_OperatingSystem` |
| CPU/GPU | AMD Radeon RX 7600, **8 GB VRAM** | `ollama ps` (mostra o uso real) |
| RAM | **19,9 GB** | Gerenciador de Tarefas / `Get-CimInstance Win32_ComputerSystem` |
| Shell | PowerShell 5.1 (padrão do Windows) | `$PSVersionTable` |

> A GPU tem 8 GB. O `qwen3-16k` carregado a 16384 de contexto ocupa **6,74 GB de VRAM**,
> ou seja: cabe, mas com pouca folga. Fechar navegador com muitas abas ajuda.

## Software

| Item | Versão | Origem |
|---|---|---|
| OpenCode | **v2.1.3** | instalado global via npm (`npm i -g @opencode/cli`) |
| Node.js | v22.13.1 | necessário para o OpenCode via npm |
| npm | 11.1.0 | |
| Ollama | **0.40.10** | app de bandeja (`ollama app.exe`), API em `127.0.0.1:11434` |
| git | 2.39.1.windows.1 | |
| gh | 2.39.1 | autenticado como `cleitonbrandao` |

## Modelos no Ollama

Saída de `ollama list` na máquina de referência:

```
NAME                   ID              SIZE      MODIFIED
qwen3-12k:latest       51e448e602f6    5.2 GB    (derivado, em uso)
qwen3-16k:latest       a7e33c9e82f6    5.2 GB    (derivado anterior)
qwen3-4b-cpu:latest    2628f6ef27c5    2.5 GB    (teste da Decisão 13, não usado)
qwen3:4b-instruct      0edcdef34593    2.5 GB
qwen3:4b               359d7dd4bcda    2.5 GB
qwen3:8b               500a1f067a9f    5.2 GB
deepseek-r1:8b      6995872bfe4c    5.2 GB
llama3.2:3b         a80c4f17acd5    2.0 GB
qwen2.5-coder:7b    dae161e27b0e    4.7 GB
qwen3.8:27b         aaee06c39dcf    17 GB
```

O modelo usado pelos dois subagentes locais é **`qwen3-12k`**, um modelo derivado de
`qwen3:8b` (antes era `qwen3-16k`; 12k é o que cabe com 2 slots, ver ARQUITETURA,
Decisão 11):

```
FROM qwen3:8b
PARAMETER num_ctx 12288
```

Por que derivar em vez de configurar no OpenCode: ver
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md#contexto-sempre-4096-num_ctx-ignorado).

Confirmação de que o parâmetro pegou:

```powershell
ollama show qwen3-12k --modelfile | Select-String num_ctx
# PARAMETER num_ctx 12288
```

e, com o modelo carregado:

```powershell
ollama ps
# qwen3-12k:latest ... 6.9 GB  100% GPU  12288     (2 slots carregados)
```

## Variáveis do Ollama (variáveis de usuário no Windows)

| Variável | Valor | Por quê |
|---|---|---|
| `OLLAMA_NUM_PARALLEL` | `2` | 2 requisições simultâneas por modelo; o resto enfileira |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | um modelo na VRAM; nada de troca silenciosa |
| `OLLAMA_FLASH_ATTENTION` | `1` | exigido para quantizar o KV cache |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | KV pela metade; 2 × 12k cabe em 6,9 GB |

Conferir se o servidor pegou: `server.log` em `%LOCALAPPDATA%\Ollama` deve mostrar
`OLLAMA_NUM_PARALLEL:2` e, na carga, `n_slots = 2`.

## Desempenho medido

| Cenário | Tempo | Observação |
|---|---|---|
| `qwen3-16k` a 16384, um turno completo com *thinking* | **~100 s** | 1695 tokens de saída; GPU RX 7600 |
| `qwen3-12k`, 2 slots simultâneos, 300 tokens cada | **30,4 tok/s por slot** | 6,9 GB, 100% GPU |
| `qwen3-16k`, 2 slots simultâneos, 300 tokens cada | 20,5 tok/s por slot | 8,1 GB, 10% CPU |
| `qwen3:4b-instruct` na CPU, smoke `qwen-testes` no OpenCode | 388 s | prompt de ~3,9k tokens a ~35 tok/s; descartado |
| `qwen3:8b` a 4096, chamada nativa única | **~22 s** | sem orquestração |
| modelo free de nuvem (`flint-40b-free`) | **~5 s** | usado como orquestrador em teste |
| `verificar.ps1` / `verificar.sh` (veredito por regra) | < 1 s + o próprio teste | sem modelo; substitui o `testador` (2026-10-24) |
| `qwen-testes` rodando o verificador (`verify.ps1 -Smoke`) | **102,6 s** | inclui carregar o `qwen3-12k` e o prompt do OpenCode |
| `redigir_docs.py`, 1 seção do README, `qwen3-12k` | **22–39 s** | 1 tentativa, passou no `verificar_docs.py` |
| `redigir_docs.py`, mesma seção, `qwen3.5:4b` | 20–21 s | 1 tentativa; texto sem crases nos caminhos |

Custo dos subagentes: **US$ 0,00** (Ollama local). O custo da sessão é o do modelo que você
escolher para o `orquestrador` no `/models`.

## Providers

| Provider | Estado na máquina de referência |
|---|---|
| Ollama (local) | funcionando, `127.0.0.1:11434` |
| OpenCode free models | funcionando (`flint-40b-free`, `deepseek-v4.1-flash-free`) |
| Google (API key) | **inválida** (`API key not valid`) |
| Google (Antigravity OAuth) | **não conectado** (`Connect Google with Antigravity OAuth...`) |

Ou seja: o bloco `provider.google` do `opencode.json` é opcional e está inerte até você
rodar `/auth` e conectar o Antigravity. Se não usa, pode apagar o bloco e o plugin
`opencode-antigravity-auth`.

## Caminhos importantes

| O quê | Windows | Linux/macOS |
|---|---|---|
| Config global | `%USERPROFILE%\.config\opencode\opencode.json` | `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json` |
| Dados/logs | `%USERPROFILE%\.local\share\opencode\` | `~/.local/share/opencode/` |
| Banco de evidências | `...\share\opencode\opencode.db` | idem |
| Log | `...\share\opencode\log\opencode.log` | idem |

O Windows usa o mesmo layout `~/.config/opencode` — por isso a config é idêntica nos dois
sistemas e o instalador só muda a forma de copiar/verificar.
