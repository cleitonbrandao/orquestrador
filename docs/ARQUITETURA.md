# Arquitetura e decisões

Documento do **porquê** de cada escolha, com a evidência que sustentou a decisão.

## Visão geral

Três agentes, papéis bem separados:

| Agente | Modo | Modelo | Ferramentas |
|---|---|---|---|
| `orquestrador` | `primary` | **nenhum** (segue `/models`) | tudo; `shell` e `edit` em `ask` |
| `local-helper` | `subagent` | `ollama/qwen3-16k:latest` | `read`, `glob` |
| `run_tests` | servidor MCP (sem LLM) | — | só comandos de teste da allowlist |

O objetivo é econômico: leitura de código e execução de testes são as operações mais
frequentes e mais mecânicas. Mandá-las para um modelo local de 8B custa US$ 0,00 e
preserva o contexto do modelo principal para o que realmente exige raciocínio.

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

**O que foi feito:** subagentes com lista de `deny` explícita; `shell` do antigo `qwen-testes`
como `ask` (hoje substituído pelo `run_tests`).

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

`local-helper` não tem `grep`, `shell`, `edit` nem `execute`. o antigo `qwen-testes` não tinha
`edit`, `glob`, `grep` nem `execute`.

**Por quê:** cada ferramenta extra é uma chance de o modelo de 8B escolher errado. Um
agente que só sabe `read` lê; um que sabe `shell` tenta "resolver" com comando. Menos
ferramentas = comportamento previsível.

`grep` foi negado de propósito nos dois: modelos pequenos costumam montar regex inválida e
entrar em loop. A busca fica com o orquestrador, que passa os arquivos já localizados.

## Decisão 8 — `execute` (Code Mode) negado nos subagentes

Code Mode dá ao modelo um runtime JavaScript com acesso a ferramentas. Em um modelo local
de 8B o resultado é imprevisível e foge da auditoria linha a linha. O antigo `qwen-testes` usava
`shell` direto: um comando, uma saída, uma evidência.

## Decisão 9 — `qwen-testes` (LLM) substituído por `run_tests` (MCP)

**O que foi feito:** o agente LLM que executava testes virou um servidor MCP determinístico
(`mcp/run_tests/server.py`, só biblioteca padrão).

**Por quê:** rodar um comando e devolver stdout + exit code não exige modelo. O agente LLM
só acrescentava o risco de inventar saída e dependia de ler `OK (` (formato PHPUnit), o que
não vale para pest/jest/pytest.

**Contrato:** `passou` = exit 0 · `falhou` = exit ≠ 0 · `bloqueado` = comando recusado,
inexistente, cwd inválido ou timeout. `bloqueado` significa *não verificado*.

**Segurança:** allowlist de comandos de teste + lista de negação (`install`, `migrate`,
`db:`, `rm`, `docker`, `curl`...), execução sem shell (`shlex`), metacaracteres
(`; & | > < $()`) recusados, timeout (padrão 300 s, máx. 1800 s), saída truncada em 16 KB.
Isso substitui o `deny` por padrão de shell do antigo agente, que só barrava por prefixo.

**Evidência (2026-10-23, Linux):** `git --version` → `passou`; `composer install` e
`git --version; rm -rf x` → `bloqueado`; `pytest` inexistente → `bloqueado`; cwd inexistente
→ `bloqueado`. Reproduzível com `./verify.sh`. **Não validado ainda** dentro do OpenCode V2
(ver pendência abaixo) nem no Windows.

## Decisão 10 — Busca semântica local (`kb` + `nomic-embed-text`)

O MCP `kb` (`mcp/kb/kb.py`) combina BM25 com embeddings do `nomic-embed-text` (Ollama `/api/embed`),
e está registrado nos dois lados: Claude Code (escopo user) e OpenCode (`mcp.kb` em
`opencode/opencode.json`, ferramenta `kb_search_kb`). O modelo não gera texto, então fica fora do
`scripts/testar-modelo.sh`. Um app só tem busca semântica se foi indexado com o modelo presente;
`./verify.sh` avisa os apps com 0 embeddings. Detalhes e custo de indexação em `CLAUDE-CODE.md`.

## Evidências de validação (2026-10-23, OpenCode v2.1.3)

| Teste | Resultado observado |
|---|---|
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

Para reproduzir qualquer um desses sintomas, veja
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).
