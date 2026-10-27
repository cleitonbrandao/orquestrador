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

## Decisão do fluxo (2026-10-27)

Medido nesta máquina, sem estimativa. O `qwen3.5:4b` foi o único que passou nos quatro
critérios (A planejamento, B JSON, C código, D revisão); o `qwen3.5:2b` passou em D e foi
adotado no `revisor`; `gemma4:e4b`, `bonsai-2:4b` e `qwen3.5:2b` no papel de executor
quebraram/inventaram no relatório real e foram descartados para essa etapa.

| Etapa / agente | Modelo | Evidência |
|---|---|---|
| `local-helper` (leitura, kb/trail) | `qwen3.5-4b-16k` | respondeu usando `kb`; ferramentas MCP visíveis com `codemode: false` |
| `decompositor` (planejamento) | `qwen3.5-4b-16k` | passou em A/B no benchmark |
| `revisor` (advisory) | `qwen3.5-2b-16k` | passou em D; apontou risco real (`$guarded = []`) |
| `local-mini` (leitura pontual) | `qwen-coder-8k` | coder 1.5B; sem benchmark de agente completo |
| `exec-docs` (edição de Markdown) | **modelo principal** | o 4B editou corretamente em uma execução, mas travou antes/depois em outras (sem retorno em 120–240 s); o coder 1.5B não chama `edit` e inventa comando |
| Testes | `run_tests` (MCP) | determinístico; suíte real do `ia_relatorios`: 46 passed |

O `qwen3.5:4b` **não** foi adotado no `exec-docs` por instabilidade do loop de ferramentas,
não por qualidade de texto. O plugin `ollama-nothink.ts` resolve o thinking
(`reasoning_effort: "none"`), mas não o travamento após a edição. Para docs, o `exec-docs`
usa o modelo principal e o verificador de docs roda no orquestrador.
