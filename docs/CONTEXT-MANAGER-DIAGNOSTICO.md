# Diagnóstico — Context Manager (Fase 1)

Entregável da Fase 1 de [`CONTEXT_MANAGER_ROADMAP.md`](CONTEXT_MANAGER_ROADMAP.md).
Tudo abaixo foi **medido**, não estimado. Fonte primária: `opencode.db` (storage V2),
lido por `scripts/custo_agentes.py`.

**Data da medição:** 2026-10-30 · **OpenCode:** 2.2.3 (o roadmap diz 1.18.31 — ver §6)
**Máquina:** Debian, i7 13ª geração, 14 GiB, sem GPU (Ollama 100% CPU)

---

## 1. Linha de base de consumo

Projeto `softnews-notion` (123 sessões, 7.276 mensagens de assistente):

| Medida | Valor | Observação |
|---|---:|---|
| Entrada paga | 37.606.088 | tokens novos |
| **Cache lido** | **796.842.146** | **95,2% de tudo que o pago processou** |
| Saída paga | 2.668.695 | resposta do modelo |
| Total processado no pago | 837.116.929 | |
| Razão entrada:saída | **312,7:1** | |
| Custo registrado | US$ 73,88 | `cost` gravado pelo provider |
| Tokens no local (Ollama) | 61.409 | **0,007%** do total |
| Mensagens locais | 26 de 20.248 | **0,13%** |

No repositório `orquestrador`: entrada 2.843.063 · cache 76.396.736 · saída 127.352 ·
US$ 0,54 — a mesma proporção, em escala menor.

### O que isso significa

1. **O custo é re-leitura, não geração.** 95% dos tokens pagos são cache de contexto
   reenviado a cada turno. Editar menos código economiza pouco; encurtar o contexto
   economiza quase tudo.
2. **A camada local hoje não existe na prática.** 0,13% das mensagens e 0,007% dos
   tokens. O objetivo do roadmap (§1) não está sendo realizado — não por falta de
   modelo, mas porque o trabalho continua começando no pago.
3. **A conta é de proporção, não de pacote.** Um resumo que corte 60% de um contexto de
   10 k tokens economiza 6 k tokens **por turno** — com 300 turnos de sessão, é a
   diferença entre 3 M e 7,5 M de tokens.

## 2. Como o contexto é construído hoje

O OpenCode V2 monta cada requisição com quatro camadas, nesta ordem:

| Camada | Tamanho medido | Muda entre turnos? |
|---|---|---|
| Prompt do agente (`agents.<nome>.system`) | 1.008–1.874 chars | não |
| Schemas de ferramentas permitidas | **dominante** (não separável no storage) | não |
| Histórico da sessão | cresce | sim |
| Pedido do usuário | 5.696 chars no decompositor | por tarefa |

Medição real do `decompositor` (sessão `ses_e72fbec54ffe…`):

```
prompt 10.410 tokens  →  plano 687 tokens     (15:1)
compactação automática: 12 min em CPU
```

O pico de qualquer sessão local observada foi **10.481 tokens** — ou seja, o prompt
base (agente + ferramentas + pedido) já consome quase todo o contexto de um modelo
16k antes de qualquer leitura.

### Compactação automática (descoberta da Fase 1)

`SessionRunner.runStep` chama a compactação **a cada passo**, e uma falha aborta o turno:

```text
limiar = contexto - max(15% do contexto, 16000 se contexto >= 32000)
keep   = 15000 (fixo)
```

Com 16k: limiar 13.927 **abaixo** do `keep` → toda compactação resume a conversa
inteira, a etapa seguinte não acha texto e a sessão morre com
`Nothing to compact yet`. Correção aplicada: locais em **32k**
(ver `TROUBLESHOOTING.md`).

## 3. Mapa do que já existe

O roadmap (§15) proíbe criar segunda infraestrutura. Boa parte do que as Fases 2–3
pedem já está no repositório:

| Componente do roadmap | Já existe | Onde | Lacuna |
|---|---|---|---|
| Context Retriever — busca textual | sim | `mcp/kb/kb.py` (BM25) | índice por app, não por tarefa |
| Context Retriever — busca semântica | opcional | `kb.py` + `nomic-embed-text` | não avaliado (§13 Fase 3) |
| Context Retriever — símbolos/dependências | sim | MCP `trail` (nó, chamadas, arquivo:linha) | não usado pelo `contexto_local` |
| Context Filter — orçamento determinístico | sim | `contexto_local.py` (`--max-linhas`, `--max-por-arquivo`, `--max-total`) | falta dedup entre fontes |
| Context Compressor — síntese local | sim | `contexto_local.py` + Ollama | prompt não pede JSON estruturado |
| Context Validator (§4.4) | **novo** | `scripts/contexto_pacote.py` | — |
| Pacote §6 | **novo** | `contexto_local.py --pacote` | `reason` por arquivo ainda vazio |
| Memória persistente (§7) | **não existe** | — | próxima fase |
| Servidor MCP (§10) | padrão pronto | 4 servidores em uso | falta o do Context Manager |
| Métricas (§12) | sim | `custo_agentes.py`, `context_metrics` do pacote | falta cruzar economia × qualidade |

## 4. O que foi entregue nesta fase

- `scripts/contexto_pacote.py` — pacote §6 + validador determinístico §4.4
  (arquivo inexistente, caminho fora da raiz, `.env` e citação inventada viram
  `missing_information`, nunca fato).
- `scripts/contexto_local.py --pacote` — grava o pacote já validado ao lado do Markdown.
- 17 testes do pacote + 2 de integração na CLI (188 testes no repositório).
- Modelos locais em 32k e agentes reapontados (correção do §2 acima).

## 5. Lacunas e riscos

1. **§3.2 é o gargalo real.** Uma ferramenta MCP não remove o histórico já enviado. O
   ganho só aparece se o orquestrador **chamar** o Context Manager em vez de ler os
   arquivos — depende do prompt de roteamento, como já ocorre na regra `LEITURA`.
2. **Cache é barato, entrada não.** Reduzir contexto corta as duas coisas, mas a
   economia em US$ é menor que a economia em tokens sugere (cache custa ~0,1× da
   entrada). As metas do §12 devem ser lidas como tokens, não como dinheiro.
3. **Local é lento em CPU.** 17 tok/s de leitura: um prompt de 10 k tokens custa ~10 min
   de pré-processamento. O Context Manager precisa caber em contextos de 2–4 k.
4. **Qualidade do 2B é irregular.** No teste de decomposição acertou 8/8 caminhos, mas
   inventou comando de teste e ignorou a pergunta sobre bloqueio entre tarefas. Sem o
   validador, o pacote passaria erro adiante.
5. **Memória (§7) não existe** — sem ela, cada tarefa redescobre o projeto.

## 6. Correções necessárias no roadmap

| Item | Diz | Realidade |
|---|---|---|
| §2.2 / §10 | OpenCode 1.18.31, evitar V2 | **2.2.3**, storage V2 em uso; o aviso está obsoleto |
| §2.3 | `phi3.5` instalado | **não instalado**; nota 10/100 quando testado |
| §2.3 | `qwen2.5-coder:1.5b` para código | 0/60 nos prompts A–D, **sem `tool_calls` nativos** |
| §5 | `local-helper` = Qwen2.5 Coder 1.5B | usar `gemma4-e2b-32k` |
| — | (sem regra de contexto) | **locais exigem ≥32k**, senão a compactação degenera |
| §12 | redução de 50–70% | plausível em tokens; em US$ o teto é menor por causa do cache |

## 7. Próximo passo recomendado

**Fase 4 (memória) antes da Fase 5 (MCP).** O pacote já existe; o que falta para ele
valer algo é o que ele não consegue responder: regras de negócio e decisões
anteriores. Um MCP sem memória devolve o mesmo resumo que o `contexto_local` já
devolve, com uma chamada de rede a mais.

Ordem sugerida: `business_rules.json` + `decisions.json` preenchidos à mão a partir de
`docs/` → `contexto_local.py` consome os dois (`--regras`, `--decisoes`) → só então o
servidor MCP.
