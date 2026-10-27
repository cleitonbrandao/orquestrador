# Modelos locais testados

Registro manual de desempenho por modelo, medido **nesta máquina** (notebook Linux, i7 13ª gen,
14 GB de RAM, só CPU). Método e prompts em [`PROMPT-TESTE.md`](PROMPT-TESTE.md).

Os campos de resultado ficam em branco até alguém medir. Nenhum número aqui foi estimado.

## Como preencher

- **tok/s ger.**: `eval rate` da **2ª rodada** (modelo já carregado), em tokens por segundo.
- **tok/s leit.**: `prompt eval rate`.
- **Carga (s)**: `load duration` da 1ª rodada.
- **RAM (GB)**: tamanho mostrado em `ollama ps` durante a geração.
- **A / B / C / D**: ✅ passou no critério, ❌ falhou, `—` não testado (A planejamento, B JSON, C código, D revisão).
- **Thinking**: `off`, `on` ou `n/a`. Se testou os dois, use duas linhas.
- **Veredito**: `adotar`, `talvez` ou `descartar`.

## Resultados

| Data | Modelo | Link | Tam./quant. | Thinking | tok/s ger. | tok/s leit. | Carga (s) | RAM (GB) | Ctx | A | B | C | D | Veredito | Observação |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | `qwen2.5-coder:1.5b` (instalado) | [ollama](https://ollama.com/library/qwen2.5-coder) | | n/a | | | | | 4096 | | | | | | |
| | `qwen3.5:2b` (instalado) | [ollama](https://ollama.com/library/qwen3.5) | | | | | | | 4096 | | | | | | |
| | `phi3.5` (instalado) | [ollama](https://ollama.com/library/phi3.5) | | n/a | | | | | 4096 | | | | | | |
| | `qwen3.5:4b` | [ollama](https://ollama.com/library/qwen3.5) | | | | | | | 4096 | | | | | | |
| | `qwen2.5-coder:3b` | [ollama](https://ollama.com/library/qwen2.5-coder) | | n/a | | | | | 4096 | | | | | | |
| | `granite4.2:3b` | [ollama](https://ollama.com/library/granite4.2) | | | | | | | 4096 | | | | | | |
| | `granite4:1b` | [ollama](https://ollama.com/library/granite4) | | n/a | | | | | 4096 | | | | | | |
| | `tev1:0.8b` | [ollama](https://ollama.com/library/tev1) | | | | | | | 4096 | | | | | | |
| | `tev1:4b` | [ollama](https://ollama.com/library/tev1) | | | | | | | 4096 | | | | | | |
| | `strands-decider:2b` | [ollama](https://ollama.com/library/strands-decider) | | | | | | | 4096 | | | | | | |
| | `phi4-mini` | [ollama](https://ollama.com/library/phi4-mini) | | n/a | | | | | 4096 | | | | | | |
| | `phi4-mini-reasoning` | [ollama](https://ollama.com/library/phi4-mini-reasoning) | | | | | | | 4096 | | | | | | |
| | `gemma4:e2b` | [ollama](https://ollama.com/library/gemma4) | | | | | | | 4096 | | | | | | |
| | `gemma4:e4b` | [ollama](https://ollama.com/library/gemma4) | | | | | | | 4096 | | | | | | |
| | `bonsai-2:2b` | [ollama](https://ollama.com/library/bonsai-2) | | | | | | | 4096 | | | | | | |
| | `bonsai-2:4b` | [ollama](https://ollama.com/library/bonsai-2) | | | | | | | 4096 | | | | | | |
| | `nemotron-3.5-bolt:e4b` | [ollama](https://ollama.com/library/nemotron-3.5-bolt) | | | | | | | 4096 | | | | | | |

Para um modelo novo, copie uma linha, troque o nome e o link e preencha.

## Notas do ambiente

Preencha uma vez por sessão de testes, para saber em que condição os números foram medidos.

| Data | Ollama | RAM disponível antes | Swap em uso | Apps abertos | Observação |
|---|---|---|---|---|---|
| | `ollama --version` | `free -h` | | | |

## Leitura dos resultados

Preencha depois de testar vários modelos: o melhor modelo por etapa do pipeline (roteador, planejador,
divisor, executor, revisor) e por quê. A decisão final vai para `ARQUITETURA.md`.

| Etapa | Modelo escolhido | Motivo (números da tabela acima) |
|---|---|---|
| Roteador | | |
| Planejador | | |
| Divisor | | |
| Executor | | |
| Revisor | | |
