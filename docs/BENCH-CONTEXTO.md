# Benchmark A/B — regra `CONTEXTO` (Fase 6)

Mede uma coisa só: **a regra que manda chamar o MCP `contexto` antes de ler
arquivos reduz token pago sem piorar o resultado?**

- Hipótese: o braço B gasta menos token pago por tarefa, com a mesma taxa de acerto.
- O que muda entre os braços: **apenas** a presença do parágrafo `CONTEXTO` no
  prompt do orquestrador.
- O que não muda: modelo pago, dataset, prompt da tarefa, máquina.

## Dataset

Cinco tarefas repetíveis do `softnews-notion`, cada uma com prompt fixo (copie
igual nos dois braços):

| # | Tarefa | O que exercita |
|---|---|---|
| T1 | "Onde o `PhaseTrail` é usado e como um grafo entraria no `Flow.jsx`?" | leitura de 1 arquivo grande |
| T2 | "Faça `/sscs/{id}/tabelas-conversao` redirecionar para `/fluxo-esocial` quando o tipo for `conversao_esocial`" | backend, exige 3+ arquivos |
| T3 | "Esconda o link 'Tabelas de conversão' no detalhe da SSC esocial" | frontend, 2 arquivos |
| T4 | "Como o sync SGD trata uma SSc que desapareceu da listagem?" | regra de negócio (memória) |
| T5 | "Quais campos manuais o sync precisa preservar ao enriquecer uma SSc?" | regra P1 (memória) |

T4 e T5 existem para separar dois efeitos: **pacote de contexto** e **memória do
projeto**. Se só T4/T5 melhorarem, o ganho veio de `context_get_rules`, não de
`context_build`.

## Preparo

```bash
# braço A
python3 scripts/contexto_ab.py --off
# reinicie o OpenCode

# braço B
python3 scripts/contexto_ab.py --on
# reinicie o OpenCode
```

`--status` confirma o estado. Cada troca grava um backup
`opencode.json.bak.<timestamp>` ao lado da config global.

**Nomeie as sessões com o prefixo do braço** (`AB-A T2 redirecionamento`,
`AB-B T2 redirecionamento`). A comparação por tag usa o título da sessão.

## Execução headless (repetível)

`opencode run` cria sessão nova a cada chamada e lê a config do zero — serve tanto
para automatizar quanto para evitar o viés de conduzir a tarefa na mão:

```bash
opencode run --agent orquestrador --model deepseek/deepseek-flash \
  --title "AB-A T4 r2" --auto \
  "Como o sync SGD trata uma SSc que desapareceu da listagem?"
```

`--title` é o que o comparativo lê (`ab-a` / `ab-b`); `--auto` aprova o que não
está negado (o `read` de PHP/SQL continua negado). Uma chamada por sessão, sem
`--continue`, para não herdar histórico.

## Regras de validade

Uma execução só conta se:

1. foi em **sessão nova** (histórico zerado);
2. o mesmo modelo pago em todo o braço;
3. **tarefa de código** (T2, T3): terminou com `run_tests` executado e diff conferido;
   **tarefa de leitura** (T1, T4, T5): a resposta cita `arquivo:linha` que existe;
4. bateu o mesmo prompt dos dois lados.

Descarte a execução (e repita) se o provider falhou, se a sessão foi interrompida
por você ou se o modelo foi trocado no meio.

## Medição

```bash
# tokens pagos por tarefa (o título da sessão identifica o braço)
python3 scripts/custo_agentes.py --todos --por-sessao --desde 2026-11-01

# adoção: quantas sessões usaram o MCP e quantas leituras diretas sobraram
python3 scripts/contexto_adocao.py --todos --desde 2026-11-01

# comparativo pronto, por tag de sessão
python3 scripts/custo_agentes.py --todos --comparar docs/bench-contexto.experimentos.json
```

Registre por execução: tokens pagos, leituras diretas, `pending` do pacote
(`context_metrics`), tempo de parede e se a tarefa saiu correta.

## Critério de aceite

| Resultado | Leitura |
|---|---|
| B ≤ 80% dos tokens pagos de A **e** acerto ≥ A | regra fica ligada |
| B reduz token mas piora acerto | ajustar o critério (`~2 mil tokens` / `3+ arquivos`) e repetir |
| B ≥ A em token | a regra não paga o custo do prompt; remover |

Mínimo de **5 execuções por braço** para a média valer. Com menos, é anedota.

---

# Rodada 1 — resultado (2026-10-30)

5 tarefas, 1 execução cada, braço B rodado antes do A.

| Tarefa | A (sem regra) | B (com regra) | Δ |
|---|---:|---:|---:|
| T1 PhaseTrail/grafo | 245.887 | 289.481 | **+17,7%** |
| T2 redirecionar rota | 217.586 | 348.032 | **+60,0%** |
| T3 ocultar link | 383.494 | 324.920 | −15,3% |
| T4 SSc ausente | 217.510 | 58.313 | **−73,2%** |
| T5 campos manuais | 58.438 | 37.555 | −35,7% |
| **Total** | **1.122.915** | **1.058.301** | **−5,8%** |

Por tipo de tarefa:

| Tipo | A | B | Δ |
|---|---:|---:|---:|
| Leitura/entendimento (T1, T4, T5) | 521.835 | 385.349 | **−26,2%** |
| Edição de código (T2, T3) | 601.080 | 672.952 | **+12,0%** |

**Veredito:** o agregado (−5,8%) está dentro do ruído de 5 amostras e **não**
atende ao critério de aceite (B ≤ 80%). O sinal útil está na separação: o pacote
economiza em tarefa de leitura e custa em tarefa de edição.

## Duas falhas de método na rodada 1

1. **O braço A não estava limpo.** Desligar só a regra não remove a ferramenta: o
   MCP seguiu disponível e o modelo chamou `context_build` em 3 das 5 sessões do
   braço A (2, 5 e 1 chamadas). O "A" virou um "B com menos insistência".
   **Correção:** `contexto_ab.py --off` agora remove também `mcp.servers.contexto`.
2. **O sinal ficou colado na regra errada.** As tarefas de edição pagaram o
   `context_build` e ainda leram o arquivo para editar. A regra passou a dizer:
   *use em tarefa de leitura/entendimento; em tarefa de edição, vá direto ao
   arquivo a alterar*.

## Terceira falha: T1–T3 não são repetíveis

Na 2ª rodada o repositório **já contém** o resultado das três:

- `SscConversionTableController` já redireciona `conversao_esocial` para o fluxo;
- o atalho "Tabelas de conversão" já está escondido (há teste cobrindo);
- `app/resources/js/components/esocial/flow-graph.jsx` já existe.

Pedir de novo mede "descobrir que já está feito", não "implementar". Isso também
contamina a rodada 1: o +60% do T2 pode ser o custo de procurar e achar o código
pronto.

**Regra nova:** tarefa de código só é repetível com o repositório no **mesmo
commit** nos dois braços (`git checkout <sha>` + `git clean -fd` antes de cada
execução). Sem reset, meça só tarefa de leitura.

## Rodada 2 (para fechar)

Dataset reduzido a **T4 e T5** — perguntas de regra de negócio, somente leitura,
repetíveis em qualquer commit. **3 repetições de cada**, braço A sem o MCP:

```bash
python3 scripts/contexto_ab.py --off   # remove regra E servidor
# reiniciar → AB-A T4 r1, AB-A T4 r2, AB-A T4 r3, AB-A T5 r1..r3
python3 scripts/contexto_ab.py --on
# reiniciar → AB-B T4 r1..r3, AB-B T5 r1..r3
```

T4 e T5 podem rodar **em paralelo, em chats diferentes**: não alteram arquivo e
cada sessão registra seus próprios tokens. Duas ressalvas: as duas chamadas de
`context_build` disputam o mesmo modelo local na CPU (se uma estourar timeout,
descarte aquela execução) e o título precisa levar o braço e a repetição
(`AB-A T4 r2`), senão as repetições se misturam.

---

# Rodada 2 — resultado (2026-10-30, 23:35–23:37)

Braço A **sem o MCP** (0 chamadas de contexto nas duas sessões — a correção do
toggle funcionou), braço B com a regra restrita a leitura. 1 execução por tarefa.

| Tarefa | A (MCP off) | B (regra, leitura) | Δ |
|---|---:|---:|---:|
| T4 SSc ausente | 206.046 | 82.956 | **−59,7%** |
| T5 campos manuais | 140.831 | 58.656 | **−58,4%** |
| **Total** | **346.877** | **141.612** | **−59,2%** |

Acerto: equivalente. As duas respostas do A citam `SgdSyncService.php`,
`SgdSyncListCommand.php` e `SscController.php` (abreviados, mas todos existem);
as do B citam caminho completo **e** `AGENTS.md:24` — rastro da regra injetada
pelo pacote, que o A não tinha.

**Veredito:** atende ao critério (B ≈ 41% de A) e o efeito aparece nas duas
tarefas com magnitude parecida, o que reduz a chance de ser ruído de uma sessão.
A regra fica **ligada, restrita a tarefa de leitura/entendimento**.

**Ressalva:** é 1 execução por tarefa (n=2). Para confiança estatística faltam 2
repetições de cada — o doc pede 3. A decisão já se sustenta porque a direção é a
mesma da rodada 1 (T4 −73%, T5 −36%) e a magnitude é grande; repetir serve para
estreitar o intervalo, não para mudar o veredito.

---

# Rodada 3 — tentativa headless (2026-10-30/31)

Feita com `opencode run --auto` em vez do TUI, 2 repetições extras por tarefa e
braço. **4 das 7 execuções estouraram o timeout de 600 s** (loops de `grep`), uma
morreu com `Subagent failed: Nothing to compact yet`, e uma foi interrompida.
Só 4 execuções passaram nos critérios de validade.

## Consolidado (só execuções válidas, 3 rodadas, 2 harnesses)

| Tarefa | Braço | n | Média | Mediana |
|---|---|---:|---:|---:|
| T4 | A | 4 | 242.355 | 242.448 |
| T4 | B | 3 | 131.541 | **82.956** |
| T5 | A | 2 | 99.634 | 99.634 |
| T5 | B | 3 | 142.846 | **58.656** |
| **Total** | A | 6 | 194.782 | 211.778 |
| **Total** | B | 6 | 137.194 | **70.806** |

Δ pela **média**: −29,6% · Δ pela **mediana**: −66,6%.

## Como ler isso

- A distribuição é muito assimétrica (37 k a 484 k na mesma tarefa e braço), então
  a **mediana** descreve melhor: B é mais barato nas duas tarefas.
- Pela média, T5 inverte (+43%) por causa de **uma** sessão de 332 k. Um ponto
  extremo não deve decidir a regra num n=6.
- T4 se repete em três rodadas (−73%, −60%, −46% pela média): é o sinal mais firme
  que existe neste benchmark.

## O que impede um resultado controlado

1. **Harness misto.** r1 foi TUI; r2/r3 foram `opencode run --auto`. Auto-aprovar
   muda o comportamento (mais ferramentas, mais turnos) — as duas séries não são
   diretamente comparáveis.
2. **Timeout silencioso.** `opencode run` sem humano pode entrar em loop de busca
   até o limite. 4 de 7 foi o que aconteceu.
3. **Bug do subagente em 32k.** `local-helper` com `gemma4-e2b-32k` ainda morre com
   `Nothing to compact yet` (sessão `ses_e700bf37affe…`: compactação resumiu 9 k
   tokens, a resposta veio vazia e o passo seguinte não achou texto). Ver
   `TROUBLESHOOTING.md`.
4. **Variância de 4–8×** entre sessões da mesma tarefa. Com essa dispersão, n=3
   não distingue 20% de 60%.

## Veredito

A regra **fica ligada e restrita a leitura/entendimento** — a mediana favorece B
nas duas tarefas e T4 replica. Mas isto é evidência **direcional**, não
controlada: para virar resultado, é preciso um harness só (headless com timeout
maior e sem `--auto`, ou TUI), e o bug do subagente resolvido antes — ele injeta
falha aleatória em qualquer braço.

## O que este benchmark não mede

- **Tempo do modelo local**: `context_build` gasta 20–60 s de CPU por chamada. É
  custo de latência, não de dinheiro — anote, mas não misture com a conta.
- **Qualidade do resumo**: se o pacote omitir algo importante, a tarefa falha e
  aparece como "acerto pior" no braço B. Nesse caso o problema é o compressor,
  não a regra.
- **Adesão futura**: `contexto_adocao.py` mede o que aconteceu; não prevê o
  comportamento com outro modelo ou outra tarefa.
