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

## O que este benchmark não mede

- **Tempo do modelo local**: `context_build` gasta 20–60 s de CPU por chamada. É
  custo de latência, não de dinheiro — anote, mas não misture com a conta.
- **Qualidade do resumo**: se o pacote omitir algo importante, a tarefa falha e
  aparece como "acerto pior" no braço B. Nesse caso o problema é o compressor,
  não a regra.
- **Adesão futura**: `contexto_adocao.py` mede o que aconteceu; não prevê o
  comportamento com outro modelo ou outra tarefa.
