# Modelos locais testados

Registro manual de desempenho por modelo, medido **nesta máquina** (notebook Linux, i7 13ª gen,
14 GB de RAM, só CPU). Método e prompts em [`PROMPT-TESTE.md`](PROMPT-TESTE.md).

Os campos de resultado ficam em branco até alguém medir. Nenhum número aqui foi estimado.

> **Decisores e análise de texto ainda não são medidos aqui.** A tabela A–D cobre orquestração de
> código; para `tev1`, `d3` e afins (que não geram texto) e para os prompts de suporte, o método está
> em [`PLANO-TESTES-SUPORTE.md`](PLANO-TESTES-SUPORTE.md) (trilhas E e F, com CSV próprio).

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

## Decisores (trilha E)

Modelos que **não geram texto** e escolhem entre opções (`/v1/systemone`) não entram na tabela A–D.
Eles são medidos por `scripts/testar-decisor.sh` em casos rotulados de suporte (método e critérios em
[`PLANO-TESTES-SUPORTE.md`](PLANO-TESTES-SUPORTE.md)): o que importa é **acerto**, **taxa de escalada**
(quanto cai no modelo maior) e **latência** — não tok/s.

Primeira medição (2026-10-28, 24 casos de teste, notebook sem GPU). Duas rodadas: a segunda com os
`criteria` das opções enriquecidos (deadlock, senha, layout, lista que não atualiza, relatório que
diverge do cálculo):

| Rodada | Modelo | Acerto | Escalaria | Erra com convicção | p50 |
|---|---|---|---|---|---|
| 1 | `d3:2b` | 16/24 (66,7%) | 58,3% | 0 | 7,9 s |
| 1 | `tev1:0.8b` | 10/24 (41,7%) | 62,5% | 0 | 4,3 s |
| **2** | **`d3:2b`** | **22/24 (91,7%)** | 29,2% (a 0,7) · **12,5% a 0,6** | 1 | 11,4 s |
| 2 | `tev1:0.8b` | 16/24 (66,7%) | 50,0% | 0 | 5,8 s |

Capacidades estruturais do `d3:2b`, confirmadas na mesma rodada: **30 e 40 opções** numa pergunta
(mata o torneio de 3 chamadas) e **imagem** aceita no `/v1/systemone` (base64 puro).

Notas: a latência é de CPU e **não** representa a máquina de produção (GPU); a nota do CSV zera o
bloco de tempo nessa condição. O `d3` domina o `tev1` nos dois eixos, mas o conjunto de teste foi
visto durante o ajuste — o número é otimista até o export real. Histórico em
`docs/resultados/decisao.csv` (local, não versionado).

## Requisitos da máquina onde foi testado e implementado

Esta estrutura foi medida e ajustada para um **notebook de 16 GB de RAM, só CPU**:

| Item | Valor |
|---|---|
| CPU | Intel Core i7-1355U (12 threads) |
| RAM | 14 Gi (≈9,4 Gi disponível em uso normal) |
| Swap | 8 Gi (aumentado de 2 Gi; swappiness 10) |
| GPU | Intel Iris Xe (integrada, sem VRAM dedicada) |
| SO | Linux (kernel 6.x) |
| Ollama | 0.40.8 |
| OpenCode | 2.1.4 (`opencode2`) |
| Node.js | v24.x |

**Implicações para a escolha de modelos:**
- Modelos ≥4,6 GB (gemma4:e2b/e4b) cabem, mas ficam lentos em CPU e competem com o SO;
  usar apenas sob demanda, um por vez, com RAM livre.
- Subagentes locais preferem modelos 1,5b–2b (≤2,7 GB) para rodar junto com o SO.
- Orquestrador principal e `exec-docs` ficam na **nuvem** (zero RAM local).
- Não empilhar subagentes locais ≥2b simultaneamente.

## Decisão do fluxo (configuração modesta para 16 GB / CPU)

Medido nesta máquina, sem estimativa. O `qwen3.5:4b` foi o único que passou nos quatro
critérios (A planejamento, B JSON, C código, D revisão) com nota 100/100, mas por ser
pesado e inconsistente em CPU (6,9–52 tok/s) **não é o padrão** dos subagentes locais.
A configuração efetiva (em `opencode/opencode.json`) usa modelos modestos:

| Etapa / agente | Modelo | Evidência / Nota |
|---|---|---|
| `local-helper` (leitura, kb/trail) | `qwen3.5-2b-16k` | Nota 52/100 (11,2 tok/s, A/D OK) · leve, roda junto com o SO |
| `decompositor` (planejamento) | `qwen3.5-2b-16k` | Nota 52/100 (A/D OK) · planeja e divide tarefas |
| `revisor` (advisory) | `deepseek-r1:1.5b` | Nota 55/100 (20,8 tok/s, D OK) · rápido e leve (1,3 GB) |
| `local-mini` (leitura pontual) | `qwen-coder-8k` | Nota 40/100 (20,2 tok/s) · leitura rápida pontual (1,0 GB) |
| `exec-docs` (edição de Markdown) | **modelo principal** (nuvem) | 4B travou em sessões longas; modelo principal edita docs com segurança |
| `orquestrador` / `exec-*` | **modelo principal** (nuvem) | arquitetura, integração e execução de código |
| Testes | `run_tests` (MCP) | determinístico; suíte real: 46 passed |
| Busca semântica | `nomic-embed-text` | 274 MB, leve |

**Sob demanda (com RAM livre, um por vez):** `qwen3.5-4b-16k` (nota 100/100, A/B/C/D OK)
para divisão em JSON de alta qualidade; `gemma4:e2b` (nota 65/100, B/C/D OK) para revisão
mais acurada.

O `qwen3.5:4b` **não** foi adotado no `exec-docs` por instabilidade do loop de ferramentas,
não por qualidade de texto. O plugin `ollama-nothink.ts` resolve o thinking
(`reasoning_effort: "none"`), mas não o travamento após a edição. Para docs, o `exec-docs`
usa o modelo principal e o verificador de docs roda no orquestrador.

### Escopo dos testes
A orquestração segue a regra de **escopo mínimo**: cada tarefa traz um `comando_teste`
restrito ao fluxo alterado (filter por arquivo/classe/método), nunca a suite inteira; o
executor roda apenas esse comando via `run_tests`; na etapa `INTEGRAR`, rodam-se apenas os
testes dos arquivos tocados (ou o teste de integração dedicado ao fluxo). Fluxo novo →
testa-se apenas aquele escopo.
