---
name: orquestrar
description: Pipeline decompor → executar em paralelo (no máximo 2 agentes por vez) → testar cada parte → integrar. Use quando o usuário pedir /orquestrar ou um pedido de desenvolvimento com 3 ou mais partes independentes.
argument-hint: <pedido de desenvolvimento>
---

# /orquestrar

**SLOTS = 2** — número máximo de subagentes (executor + testador) rodando ao mesmo tempo.
Para mudar, edite este número; não passe de 4 (os testes rodam nesta máquina).

Pedido: $ARGUMENTS

Se o pedido tem menos de 3 partes independentes, não use o pipeline: resolva direto.

## 1. Decompor
Chame o agente `decompositor` com o pedido completo e o contexto que você já tem. Ele
devolve `PLANO` com T1..Tn.

## 2. Conferir o plano (você, sem subagente)
Rejeite e peça um novo plano ao `decompositor` se:
- duas tarefas sem dependência entre si compartilham arquivo;
- alguma tarefa não tem `criterio_aceite` ou `area`;
- há ciclo em `depende_de`.

Mostre o plano ao usuário em uma tabela curta antes de executar.

## 3. Executar em slots (pipeline)
Mantenha uma fila com as tarefas prontas (dependências concluídas) e no máximo **SLOTS**
subagentes ativos. Cada tarefa percorre:

```
executor ──pronto──► testador ──passou──► concluída
    ▲                    │
    └──falhou (≤2x)──────┘   3ª falha ► bloqueada
```

- `rota: edicao` → executor da `area`: `backend` → `exec-backend`, `dados` → `exec-dados`,
  `frontend` → `exec-frontend`, `geral` → `executor`. Mande: id, objetivo, arquivos,
  critério de aceite e, se for retorno, a `EVIDENCIA` da falha anterior (retorno vai para
  o mesmo executor).
- `rota: leve` → resolva você mesmo (leitura/análise) ou use o agente `Explore`; não ocupa slot.
- Executor respondeu `pronto` e `comando_teste` ≠ `nenhum` → agente `testador` com o
  comando exato. Testador ocupa slot como qualquer outro.
- Sempre que um subagente terminar, preencha o slot livre com o próximo item da fila
  (um testador pendente tem prioridade sobre um executor novo).
- Nunca dispare dois executores para tarefas que tocam o mesmo arquivo.
- `bloqueado` do executor (precisa de arquivo fora da lista) → reavalie o plano; não
  amplie a lista em silêncio.

## 4. Integrar
Quando a fila esvaziar:
1. `git status --short` / `git diff --stat`: confirme que só os arquivos dos planos
   mudaram.
2. Se `INTEGRACAO` ≠ `nenhum`, chame o `testador` com esse comando.

## 5. Relatar
| Tarefa | Resultado | Arquivos | Evidência |
|---|---|---|---|

Depois da tabela: resultado do teste de integração (saída real) e as tarefas bloqueadas
com o motivo. Nunca diga que passou sem a saída do testador.
