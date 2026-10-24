# Arquitetura e decisões

Documento do **porquê** de cada escolha, com a evidência que sustentou a decisão.

## Visão geral

Nove agentes em um pipeline **triar → decompor → executar em slots → verificar → integrar**
(esboço original em [`esboco_possivel_estrutura.png`](esboco_possivel_estrutura.png)):

```
pedido ─► orquestrador ─► triagem por regra (Decisão 15)
              │              só Markdown → rota=docs sem decompositor · ≤ 2 arquivos → direto
              ├─► decompositor ─► PLANO (T1..Tn, area, rota, arquivos, teste)
              │
              │  no máximo SLOTS=2 Task por mensagem, só tarefas com dependências prontas
              ├─► rota=edicao ─► exec-backend | exec-dados | exec-frontend | executor
              │                      │ edita só os arquivos da tarefa
              │                      └─► qwen-testes (aninhado) ─► verificar.ps1|.sh ─► passou?
              │                             falhou ─► volta ao mesmo executor (≤ 2x) ─► bloqueado
              ├─► rota=docs ───► exec-docs (local) ─► qwen-testes ─► verificar_docs.py (Decisão 16)
              ├─► rota=leve ───► local-helper (só leitura)
              └─► integração: confere arquivos alterados + verificador no teste do conjunto
```

| Agente | Modo | Modelo | Ferramentas |
|---|---|---|---|
| `orquestrador` | `primary` | **nenhum** (segue `/models`) | tudo; `shell` e `edit` em `ask` |
| `decompositor` | `subagent` | nenhum (herda o da sessão) | `read`, `glob`, `grep` |
| `exec-backend` / `exec-dados` / `exec-frontend` / `executor` | `subagent` | nenhum (herda o da sessão) | `edit`, `read`, `glob`, `grep`; `subagent` só `qwen-testes` |
| `exec-docs` | `subagent` | `ollama/qwen3-12k:latest` | `edit` só em `*.md`, `read`, `glob` |
| `local-helper` | `subagent` | `ollama/qwen3-12k:latest` | `read`, `glob` |
| `qwen-testes` | `subagent` | `ollama/qwen3-12k:latest` | `shell` (ask; verificadores em allow), `read` |

O objetivo é econômico: leitura de código e execução de testes são as operações mais
frequentes e mais mecânicas. Mandá-las para um modelo local de 8B custa US$ 0,00 e
preserva o contexto do modelo principal para o que realmente exige raciocínio. Planejar
e editar ficam com o modelo de nuvem, porque um erro ali contamina todas as tarefas
seguintes.

No Claude Code o mesmo pipeline é a skill `/orquestrar` (`claude/skills/orquestrar`), com
os agentes em `claude/agents/` (`decompositor`, `exec-*` e `executor` em `sonnet`;
`exec-docs` e `testador` em `haiku`). O Claude Code não aceita modelo do Ollama como
subagente, então o modelo local entra por script: o agente principal roda o
`redigir_docs.py` e o `verificar.sh` pela ferramenta Bash. "Leve" é o próprio agente
principal ou o `Explore`.

A regra geral, das Decisões 14–16: **LLM só onde há texto a produzir** (planejar, editar,
redigir). Triar, verificar e decidir o veredito são regra, porque custam zero, não
alucinam e dão o mesmo resultado nos dois clientes.

## Decisão 1 — `orquestrador` sem modelo fixo

**O que foi feito:** nenhuma chave `model` no topo do config e nenhuma em
`agents.orquestrador`.

**Por quê:** com `model` fixo no JSON, o `/models` do OpenCode é ignorado em sessões novas
e você fica preso ao modelo que estava na moda no dia em que escreveu o arquivo.

**Evidência:** com o pin removido, uma sessão nova subiu em
`opencode/deepseek-v4.1-flash-free` (free) e respondeu `OK` em 5,3 s. Antes, com o pin
`ollama/deepseek-v4.1-flash:cloud`, toda sessão nova caía num modelo pago.

**Como trocar:** `/models` dentro do OpenCode. Nada a editar.

## Decisão 2 — V2 (`agents`) em vez de V1 (`agent`)

**O que foi feito:** o bloco se chama `agents` e cada agente tem `permissions` como
**array** de `{action, resource, effect}`.

**Por quê:** na V1 o formato era outro. Se você mistura os dois, o OpenCode **descarta as
permissões silenciosamente** — o agente aparece, funciona, e roda com o default permissivo.

**Evidência:** com `agent` (V1) + `permissions` array, `opencode debug agents` mostrava o
agente sem as regras. Migrando para `agents`, as regras aparecem na lista.

**Sintoma de alerta:** agente listado, mas `edit`/`shell` funcionando sem pedir permissão.

## Decisão 3 — Modelo derivado para o contexto

> **Atualizada pela Decisão 11:** o derivado agora é `qwen3-12k` (`num_ctx 12288`), para
> caber 2 slots paralelos na GPU. O `qwen3-16k` abaixo é o histórico da decisão.

**O que foi feito:** `qwen3-16k` = `FROM qwen3:8b` + `PARAMETER num_ctx 16384`.

**Por quê:** o OpenCode **não envia** `num_ctx` por requisição, e configuração de
`options`/`body` no provider Ollama não é aplicada nesse caminho. Resultado: o modelo
sempre carregava a 4096, e tarefas com 3 arquivos de contexto estouravam.

**Evidência:** `ollama ps` mostrava `CONTEXT 4096` mesmo com o provider configurado;
depois do modelo derivado, `CONTEXT 16384` e `PARAMETER num_ctx 16384` no Modelfile.

**Custo:** 6,74 GB de VRAM em vez de 5,2 GB. Cabe em 8 GB.

## Decisão 4 — Modelo com suporte real a `tool_calls`

**O que foi feito:** `qwen3:8b` (e o derivado) em vez de `qwen2.5-coder:7b`.

**Por quê:** o `qwen2.5-coder:7b` no Ollama devolve a chamada de ferramenta como **texto
JSON** em vez de `tool_calls`, e o OpenCode não executa nada. O agente parece "educado e
inútil": descreve o comando, mas nunca roda.

**Evidência:** na API do Ollama, `tool_calls` vinha `null` para o `qwen2.5-coder:7b`;
com `qwen3:8b` veio preenchido e o `shell` executou de verdade.

## Decisão 5 — Segurança por `deny`, não por `ask`

**O que foi feito:** subagentes com lista de `deny` explícita; `shell` do `qwen-testes`
como `ask`.

**Por quê:** em subagente, uma regra `ask` **não abre prompt** — o log não mostra pedido
de permissão e o comando executa. Só `deny` realmente barra.

**Evidência:** `shell: ask` em subagente → comando executado sem nenhuma interação;
`composer install` com `shell: composer * deny` → `permission.rejected`, sem execução.

**Regra de ouro:** para o modelo local, tudo que não é essencial é `deny`.

## Decisão 6 — Ordem das permissões

Regras são avaliadas **em ordem e o último match vence**. Por isso as negações
específicas ficam **depois** do allow genérico:

```json
{ "action": "shell", "resource": "*",         "effect": "ask"  },
{ "action": "shell", "resource": "composer *", "effect": "deny" }
```

Inverter a ordem faz o `composer *` ser sobrescrito pelo `*`.

## Decisão 7 — Poucas ferramentas por agente

`local-helper` não tem `grep`, `shell`, `edit` nem `execute`. `qwen-testes` não tem
`edit`, `glob`, `grep` nem `execute`.

**Por quê:** cada ferramenta extra é uma chance de o modelo de 8B escolher errado. Um
agente que só sabe `read` lê; um que sabe `shell` tenta "resolver" com comando. Menos
ferramentas = comportamento previsível.

`grep` foi negado de propósito nos dois: modelos pequenos costumam montar regex inválida e
entrar em loop. A busca fica com o orquestrador, que passa os arquivos já localizados.

## Decisão 8 — `execute` (Code Mode) negado nos subagentes

Code Mode dá ao modelo um runtime JavaScript com acesso a ferramentas. Em um modelo local
de 8B o resultado é imprevisível e foge da auditoria linha a linha. O `qwen-testes` usa
`shell` direto: um comando, uma saída, uma evidência.

## Decisão 9 — Pipeline com contrato de plano

**O que foi feito:** o `decompositor` devolve um plano em formato fixo, uma linha por
tarefa:

```
T1 | objetivo: … | arquivos: a, b | depende_de: - | rota: leve|edicao | area: backend|dados|frontend|geral | criterio_aceite: … | comando_teste: …|nenhum
INTEGRACAO: <comando|nenhum>
RISCOS: …
```

**Por quê (ajustes ao esboço):**
- "quebrar o máximo possível" gera overhead e conflito. A regra é **unidade
  independente**: duas tarefas sem dependência nunca compartilham arquivo, de 2 a 6
  tarefas, e só entra em slot a tarefa cujas dependências já passaram (DAG);
- o "analisar se pode ser local" do esboço virou o campo `rota`;
- sem `criterio_aceite` e `comando_teste` o testador não tem o que provar.

O orquestrador rejeita o plano se houver arquivo compartilhado sem dependência ou se
faltar critério.

## Decisão 10 — Testador aninhado no executor, com teto de retorno

**O que foi feito:** cada executor tem `subagent: * deny` seguido de
`subagent: qwen-testes allow`. Ele mesmo testa e corrige até 2 vezes; o orquestrador
ainda pode devolver a tarefa ao **mesmo** executor com a evidência, também no máximo 2
vezes, e depois a marca como `bloqueado`.

**Por quê:** uma chamada `Task` do orquestrador espera todas as outras da mesma
mensagem. Com o teste dentro do executor, cada slot vira um pipeline completo
(executor → testador → correção), sem precisar de uma "onda de testes" separada. O teto
evita o loop infinito do esboço (testador ↔ executora).

**Evidência (2026-10-23):** `opencode run --auto --agent executor` pedindo para delegar
`git --version` → o executor chamou o `qwen-testes` via Task, o comando rodou de verdade
(`git version 2.39.1.windows.1`) e o veredito voltou `bloqueado` (correto: não é saída
de PHPUnit). Os subagentes nativos `general`/`explore` vêm com `subagent * deny`,
outra confirmação de que o aninhamento é uma permissão, não uma limitação.

## Decisão 11 — 2 slots: `OLLAMA_NUM_PARALLEL=2`, KV `q8_0` e contexto 12k

**O que foi feito:** variáveis de usuário `OLLAMA_NUM_PARALLEL=2`,
`OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`
e modelo derivado `qwen3-12k`. No orquestrador, `SLOTS=2` no prompt.

**Por quê:** o limite "duro" de carga é o Ollama: ele atende N requisições do mesmo
modelo e **enfileira** o resto, decida o LLM o que decidir. O KV cache é por slot, então
2 slots dobram o KV. Com `q8_0` ele cai pela metade, mas 2 × 16k ainda não cabe.

**Evidência (RX 7600 8 GB, 2 requisições simultâneas, 300 tokens cada):**

| ctx por slot | VRAM | processador | tok/s por slot |
|---|---|---|---|
| 16384 | 8,1 GB | 10% CPU / 90% GPU | 20,5 |
| **12288** | **6,9 GB** | **100% GPU** | **30,4** |
| 8192 | 6,3 GB | 100% GPU | — |

12k é ~48% mais rápido que 16k e não vaza para a CPU. `SLOTS` acima de 2 não ajuda na
parte local (o Ollama enfileira), só na de nuvem.

**Como trocar:** `.\install.ps1 -OllamaParallel 3` + `SLOTS=3` no prompt do orquestrador
e na skill. Com 3 slots, reduza o contexto (`-Context 8192` → `qwen3-8k`).

## Decisão 12 — Especialistas por prompt, não por modelo

**O que foi feito:** `exec-backend`, `exec-dados` e `exec-frontend` têm as mesmas
permissões do `executor` e regras próprias no `system` (isolamento por `team_id` e
policies; migrations reversíveis e N+1; Livewire com `#[Locked]`). O `decompositor` marca
a `area`.

**Por quê:** 8 GB comportam **um** modelo de 8B. Um modelo local por assunto obriga a
trocar de modelo na GPU a cada tarefa (5–10 s por troca) e acaba com o paralelismo. Os
modelos "coder" pequenos também falham em `tool_calls` (Decisão 4). Especializar o prompt
não custa VRAM.

## Decisão 13 — Testador pequeno na CPU: testado e descartado

**Hipótese:** um `qwen3:4b` na CPU (`num_gpu 0`) como testador, deixando a GPU inteira
para o modelo de 8B.

**Evidência:**
- `qwen3:4b` (tag padrão = variante *thinking* 2507) ignora `think=false` e despeja o
  raciocínio no `content`: 362 tokens para uma tool call contra 26 do 8B;
- `qwen3:4b-instruct` corrige isso: tool call certa em 3,9 s com prompt curto, e a GPU
  segue em 32,9 tok/s ao mesmo tempo;
- **mas dentro do OpenCode** o prompt tem ~3.900 tokens (system + ferramentas), e na CPU a
  leitura do prompt sai a ~35 tok/s, ou seja ~110 s **por turno** antes de gerar qualquer
  coisa. O smoke `qwen-testes → git --version` levou **388 s**. Com o 8B na GPU, leva
  segundos.

**Decisão:** `qwen-testes` fica no `qwen3-12k` (GPU) e `OLLAMA_MAX_LOADED_MODELS=1`.
Reavaliar com uma CPU mais rápida ou uma GPU com folga para um segundo modelo.

## Decisão 14 — Veredito de teste por script, não por modelo

**O que foi feito:** `scripts/verificar.sh` e `scripts/verificar.ps1` (instalados em
`~/.orquestrador/scripts/`) rodam um comando uma vez e decidem `passou`/`falhou`/`bloqueado`
por regra (contrato abaixo). No Claude Code, o agente principal roda o `verificar.sh` pela
ferramenta Bash e o agente `testador` virou fallback. No OpenCode, quem monta o comando do
verificador é o **executor** (modelo de nuvem); o `qwen-testes` só roda o que recebeu e
copia a saída. Os comandos dos verificadores estão em `allow` na permissão de `shell` do
`qwen-testes`.

**Por quê:** o testador fazia trabalho de regex com um modelo. No Claude Code isso era
uma chamada de agente (cold start, haiku) por tarefa e por retorno, até 3 por tarefa, e
ocupava slot. O script custa zero, sai na hora e não inventa contagem de teste.

**Evidência (2026-10-24, OpenCode v2.1.3, `qwen3-12k`):**

| Teste | Resultado |
|---|---|
| prompt do `qwen-testes` mandando "rode o pedido dentro do verificador" + `rode: git --version` | o 8B **ignorou** e rodou `git --version` direto |
| executor manda `rode exatamente: powershell ... verificar.ps1 'git --version'` | script rodou (`$HOME` expandido pelo shell do OpenCode); `RESULTADO: bloqueado` do script |
| mesmo pedido em `opencode run` sem `--auto`, antes do `allow` | `permission requested: shell; auto-rejecting` (`ask` vira rejeição no modo não interativo) |
| idem, com o `allow` dos verificadores | executou, 102,6 s (carga do modelo + 1 turno) |
| `python -m unittest discover -s tests` | 23 testes, OK (inclui os casos acima no bash e no PowerShell) |

Conclusão: o modelo pequeno segue "rode exatamente X" (Decisão 10), mas não segue "monte
X a partir de Y". A montagem fica com o modelo que planeja.

## Decisão 15 — Triagem por regra antes do decompositor

**O que foi feito:** a skill e o `system` do orquestrador começam com uma regra
objetiva. Se o pedido só altera Markdown, viram tarefas `rota: docs` sem decompositor. Se
toca até 2 arquivos ou uma só área, o orquestrador trabalha direto. Senão, vai para o
decompositor.

**Por quê:** antes era "menos de 3 partes independentes", e quem julgava era o próprio
LLM, depois de já ter lido o pedido inteiro. Uma regra que dá para conferir evita a
chamada do decompositor (sonnet, que relê o repositório) nos pedidos pequenos, que são a
maioria. É o mesmo princípio da triagem do gateway do ia_relatorios: decidir a rota por
regra custa zero e não decide pior que um modelo.

## Decisão 16 — Documentação no modelo local, conferida por regra

**O que foi feito:** nova `rota: docs` / `area: docs` no decompositor.
- Claude Code: o agente principal roda `scripts/redigir_docs.py`, que manda ao Ollama local
  só a seção pedida (`--secao`) e os arquivos de contexto, confere a resposta com o
  `scripts/verificar_docs.py` e reenvia com os motivos (≤ 2x). A proposta vai para um
  arquivo à parte; o agente principal revisa o diff e aplica. Falhou ou sem Ollama → agente
  `exec-docs` (haiku).
- OpenCode: agente `exec-docs` no `qwen3-12k`, com `edit` só em `*.md`; o orquestrador
  confere com o `verificar_docs.py` pelo `qwen-testes`.

O `verificar_docs.py` acusa link relativo e caminho entre crases que não existem, script
citado em bloco de código que não existe, `npm run`/`composer` sem o script no
`package.json`/`composer.json`, seção vazia e marcadores (`TODO`, `TBD`, `FIXME`). Ele só
conta o que **a mudança introduziu**: problema que já estava no original não reprova.

**Por quê:** docs são texto de um passo sobre fatos dados, o perfil em que um modelo
local de 4–8B vai bem (no ia_relatorios, o `qwen3.5:4b` passou o relatório de conversão com
0 problemas em 4 execuções). E saída é o token mais caro de um modelo de nuvem. Editar
código continua na nuvem: é um loop com ferramentas, onde o modelo pequeno erra (Decisão 4).

**Evidência (2026-10-24, RX 7600, seção `## Verificação` do README deste repo):**

| Rodada | Modelo | Tentativas | Tempo | Resultado |
|---|---|---|---|---|
| prompt inicial | `qwen3-12k` | 3 | 88,5 s | `falhou`: trocou `./verify.sh` por um `verificar.sh` na raiz, que não existe; o verificador pegou nas 3 |
| + "copie sem mudar o que a tarefa não pede" | `qwen3-12k` | 1 | 22–39 s | `passou`, texto correto com crases |
| idem | `qwen3.5:4b` | 1 | 20–21 s | `passou`, mas sem crases nos caminhos |
| as duas acima | ambos | — | — | apagavam o `---` que fecha a seção → o recorte passou a deixar o separador fora do trecho enviado |

O caso da primeira rodada é o motivo do verificador existir: o texto estava fluente e
errado, e só a regra pegou. O padrão continua `qwen3-12k`, que já está instalado e saiu
melhor; dá para trocar com `ORQ_MODELO_DOCS`.

## Contrato de saída do verificador

```
COMANDO: <comando literal>
CODIGO: <código de saída do comando, ou - se recusado>
SAIDA:
<últimas 40 linhas da saída literal>
RESULTADO: <passou|falhou|bloqueado>
```

- `falhou` se a saída mostrar falha de teste (`FAILURES!`, `ERRORS!`, `N failed`,
  `FAILED `, `--- FAIL`, `test result: FAILED`), qualquer que seja o código de saída;
- `passou` **somente** com código 0 **e** testes executados (`OK (N tests`, `N passed`,
  `OK`, `ok  pacote`, `test result: ok.`, `PASS `);
- qualquer outro caso → `bloqueado`, inclusive `composer`, `npm`, `npx`, `pnpm`, `yarn`,
  `docker`, `rm`, `Remove-Item`, `artisan migrate` e `artisan db:`, que o script recusa sem
  rodar.

Código de saída do script: 0 passou, 1 falhou, 2 bloqueado. Isso impede o clássico "os
testes passaram" sem que nenhum teste tenha rodado. Um comando que não existe
(`./vendor/bin/phpunit` em diretório errado) termina com erro e sem saída de teste, e o
veredito correto é **`bloqueado`**, não `passou`.

Sem os scripts instalados, o `qwen-testes` e o `testador` aplicam a regra antiga
(`passou` só com `OK (`; `falhou` só com `FAILURES!`/`ERRORS!`).

## Evidências de validação (2026-10-23, OpenCode v2.1.3)

| Teste | Resultado observado |
|---|---|
| `qwen-testes` → `git --version` | executou, saída literal, exit 0 |
| `qwen-testes` → `./vendor/bin/phpunit` (inexistente) | `CommandNotFoundException`, exit 1, veredito `bloqueado` |
| `qwen-testes` → `composer install` | `permission.rejected`, **não executou** |
| `local-helper` → `read app/phpunit.xml.dist` | devolveu `sqlite` / `Unit, Feature` |
| `local-helper` → `read` de arquivo inexistente | `File not found`, sem invenção |
| `local-helper` → `read app/.env` | `permission.rejected` |
| `local-helper` → `read app/.env.example` | permitido, conteúdo correto |
| `opencode debug agents` | 3 agentes, permissões efetivas corretas |

## O que **não** funciona (testado e descartado)

| Tentativa | Resultado |
|---|---|
| `provider.ollama` com `npm: @ai-sdk/openai-compatible` + `/v1` | tool calls quebradas (`tool_calls: null`) |
| `options.num_ctx` / `body.num_ctx` no provider | ignorado; segue 4096 |
| `{env:VAR:-default}` no `model` do agente | agente **desaparece** da lista, sem erro |
| `shell: ask` em subagente esperando prompt | não há prompt; executa |
| 2 slots de 16k na RX 7600 | 8,1 GB, 10% em CPU, 20 tok/s (ver Decisão 11) |
| `qwen3:4b` na CPU como testador | 388 s por teste no OpenCode (ver Decisão 13) |
| `qwen-testes` (8B) montando sozinho o comando do verificador | rodou o comando cru (ver Decisão 14) |
| `shell: ask` em `opencode run` não interativo | rejeição automática; os verificadores precisam de `allow` |

Para reproduzir qualquer um desses sintomas, veja
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).
