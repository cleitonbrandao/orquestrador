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

## Rodada 2 (para fechar)

Repetir com o braço A **sem o MCP**, e ao menos **3 repetições** de T4/T5 — são
as tarefas que mostraram o efeito e as únicas em que a diferença não pode ser
explicada por tamanho de arquivo.

```bash
python3 scripts/contexto_ab.py --off   # agora remove regra E servidor
# reiniciar, rodar AB-A T1..T5
python3 scripts/contexto_ab.py --on    # devolve os dois
# reiniciar, rodar AB-B T1..T5
```

## O que este benchmark não mede

- **Tempo do modelo local**: `context_build` gasta 20–60 s de CPU por chamada. É
  custo de latência, não de dinheiro — anote, mas não misture com a conta.
- **Qualidade do resumo**: se o pacote omitir algo importante, a tarefa falha e
  aparece como "acerto pior" no braço B. Nesse caso o problema é o compressor,
  não a regra.
- **Adesão futura**: `contexto_adocao.py` mede o que aconteceu; não prevê o
  comportamento com outro modelo ou outra tarefa.
