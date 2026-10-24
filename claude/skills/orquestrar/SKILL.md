---
name: orquestrar
description: Pipeline triagem → decompor → executar em paralelo (no máximo 2 agentes por vez) → verificar cada parte por script → integrar. Docs vão para o modelo local. Use quando o usuário pedir /orquestrar ou um pedido de desenvolvimento com 3 ou mais partes independentes.
argument-hint: <pedido de desenvolvimento>
---

# /orquestrar

**SLOTS = 2**: número máximo de subagentes (executores) rodando ao mesmo tempo. Os
verificadores são scripts e não ocupam slot. Para mudar, edite este número; não passe de 4.

**SCRIPTS = `~/.orquestrador/scripts`** (instalados pelo `install.ps1`/`install.sh`).
Use `python3` (no Windows, `python`).

Pedido: $ARGUMENTS

## 0. Triagem (regra, sem subagente)
Decida pela primeira regra que se aplica:
1. O pedido só altera Markdown (README, `docs/`, CHANGELOG, guias) → não chame o
   decompositor: monte você as tarefas `rota: docs` (um arquivo alvo cada) e vá ao passo 3.
2. O pedido toca até 2 arquivos, ou uma só área sem partes independentes → resolva direto,
   sem pipeline. Para testar, use o verificador do passo 3 mesmo assim.
3. Senão → passo 1.

## 1. Decompor
Chame o agente `decompositor` com o pedido completo e o contexto que você já tem (inclua os
caminhos que já localizou, para ele não buscar de novo). Ele devolve `PLANO` com T1..Tn.

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
código: executor ──pronto──► verificar.sh ──passou──► concluída
            ▲                     │
            └──falhou (≤2x)───────┘   3ª falha ► bloqueada

docs:   redigir_docs.py (local) ──passou──► você revisa e aplica ──► concluída
            │ falhou / indisponivel
            └──► exec-docs ──► verificar_docs.py ──falhou (≤2x)──► exec-docs
```

**Código** (`rota: edicao`)
- Executor da `area`: `backend` → `exec-backend`, `dados` → `exec-dados`,
  `frontend` → `exec-frontend`, `geral` → `executor`. Mande: id, objetivo, arquivos,
  critério de aceite e, se for retorno, a `EVIDENCIA` da falha anterior (retorno vai para
  o mesmo executor).
- Executor respondeu `pronto` e `comando_teste` ≠ `nenhum` → rode você, pela ferramenta Bash
  (no Windows é o Git Bash):
  ```
  bash ~/.orquestrador/scripts/verificar.sh '<comando_teste exato>'
  ```
  O veredito é a linha `RESULTADO` do script (código de saída 0 passou, 1 falhou,
  2 bloqueado). Não reinterprete. `falhou` → volta ao executor com a `SAIDA` como
  `EVIDENCIA`. `bloqueado` → veja a `SAIDA` (comando errado ou recusado) e corrija o
  comando ou marque a tarefa.
- Se `~/.orquestrador/scripts/verificar.sh` não existir, use o agente `testador`
  (fallback; ocupa slot).

**Docs** (`rota: docs`)
- Rode o redator local (pode ir em segundo plano enquanto os slots trabalham):
  ```
  python3 ~/.orquestrador/scripts/redigir_docs.py --alvo <arquivo> \
      --tarefa '<objetivo + critério de aceite>' [--secao '<título exato>'] \
      [--contexto <arquivos (contexto)>] [--diff]
  ```
  Use `--diff` quando o texto documenta mudanças desta sessão. O script nunca altera o
  alvo; ele grava a `PROPOSTA` à parte e já passou pelo `verificar_docs.py`.
- `RESULTADO: passou` → revise com `git diff --no-index -- <alvo> <PROPOSTA>`. Se estiver
  certo, `cp <PROPOSTA> <alvo>`. Se não, trate como `falhou` com o seu motivo.
- `falhou` ou `indisponivel` → agente `exec-docs` com a tarefa e os `MOTIVOS` como
  `EVIDENCIA` (ocupa slot). Quando ele responder `pronto`:
  ```
  python3 ~/.orquestrador/scripts/verificar_docs.py <alvo>
  ```
  `falhou` → volta ao `exec-docs` com os `MOTIVOS` (≤ 2x).

**Leitura** (`rota: leve`) → resolva você mesmo ou use o agente `Explore`; não ocupa slot.

**Regras da fila**
- Sempre que um subagente terminar, rode o verificador da tarefa dele antes de abrir um
  executor novo.
- Nunca dispare dois executores para tarefas que tocam o mesmo arquivo.
- `bloqueado` do executor (precisa de arquivo fora da lista) → reavalie o plano; não
  amplie a lista em silêncio.

## 4. Integrar
Quando a fila esvaziar:
1. `git status --short` / `git diff --stat`: confirme que só os arquivos dos planos
   mudaram.
2. Se `INTEGRACAO` ≠ `nenhum`, rode `bash ~/.orquestrador/scripts/verificar.sh '<comando>'`.

## 5. Relatar
| Tarefa | Resultado | Arquivos | Evidência |
|---|---|---|---|

Depois da tabela: resultado do teste de integração (saída real do verificador) e as
tarefas bloqueadas com o motivo. Diga quais docs saíram do modelo local e quais foram
para o `exec-docs`. Nunca diga que passou sem a saída do verificador.
