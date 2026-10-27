# Medições de economia de tokens

Nada abaixo foi medido ainda. Preencha após o A/B.

## Método
1. Escolha 5 tarefas reais e repetíveis (ex.: achar onde X é feito; corrigir teste falhando; responder dúvida de runbook).
2. Rode cada tarefa **sem** as peças (sem `run_tests`, `kb`, `triagem`) e **com** elas, em sessões novas, mesmo modelo.
3. Claude Code: anote o `/cost` ao final (tokens de entrada, saída, cache). OpenCode: consulte `opencode.db` (tokens por sessão).
4. Registre também se a resposta final estava correta; economia com resposta errada não conta.

| Tarefa | Tokens sem | Tokens com | Correta? | Observação |
|---|---|---|---|---|
| | | | | |

## Medição 1 — Questor no executor de conferência (2026-10-23)

Tarefa: incluir o concorrente Questor (softnews-notion: executor Python, BIDEV, caso; conversor-softnews: catálogo e curadoria). Medido no transcript da própria sessão (136 turnos do segmento).
**Não é um A/B puro**: não houve execução sem as ferramentas. O "sem" abaixo é contrafactual, com as premissas explicadas.

| Item | Medido | Premissa/contrafactual |
|---|---|---|
| Segmento Questor | 136 turnos; cache lido 39,3 M, cache criado 334 k, saída 114 k | Pesos de custo assumidos: leitura de cache 0,1×, criação 1,25×, saída 5× o input → ~4,9 M tokens-equivalentes |
| Contexto que já vinha da sessão | 206 k tokens no 1º turno do segmento (368 k no último) | Re-lido a cada turno: ~57% do custo do segmento. **Rodar a tarefa em sessão nova é a maior economia** |
| `run_tests` condensado (`php artisan test`) | 43.889 bytes brutos (~11 k tokens) → ~0,7 KB (~175 tokens); ficou 30 turnos no contexto | ~0,9% do custo do segmento |
| Subagente `triagem` (mapa da fiação MAKRO/CALIMA em 3 repositórios) | devolveu ~2,5 k tokens; o subagente gastou ~50 k no próprio contexto | Se eu tivesse feito as ~25 buscas no contexto principal (15–30 k tokens, 116 turnos restantes): ~4–8% do custo do segmento |
| `search_kb` | 7 chamadas, ~8,5 k tokens devolvidos | Ganho incerto (0–1%): achou `tools/conferencia-conversao` de primeira, mas depois li os arquivos de qualquer forma |

Resultado: economia atribuível às ferramentas de ~5–10% neste segmento (estimativa, premissas acima); começar em sessão nova valeria bem mais.
Qualidade: executor com 219 testes verdes, conferência real do Questor × Domínio em ~7 s, 1 erro real de integridade (empresa sem CNPJ/CPF no Domínio) encontrado.
