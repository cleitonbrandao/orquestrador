# Distribuição de tarefas: local vs. pago

O que roda no modelo pago, o que roda local, e a evidência que sustenta essa divisão.
Números vindos de `docs/resultados/` (medidos nesta máquina) — a nota e os critérios estão
em [`MODELOS-TESTADOS.md`](MODELOS-TESTADOS.md) e [`PROMPT-TESTE.md`](PROMPT-TESTE.md).

## Divisão atual

| Camada | Modelo | Tarefa |
|---|---|---|
| `orquestrador` | **pago** | triagem, arquitetura, integração entre arquivos, veredito final |
| `decompositor` | local `qwen3.5-4b-16k` | quebrar o pedido em tarefas |
| `local-helper` | local `qwen3.5-4b-16k` | ler e explicar código |
| `local-mini` | local `qwen3.5-08b-8k` | ler um trecho curto |
| `revisor` | local `qwen3.5-2b-16k` | revisar o diff (advisory) |
| `exec-local` | local `gemma4-e4b-16k` | editar **um** arquivo, com teste determinístico |
| `exec-docs` | local `gemma4-e4b-16k` | editar Markdown |
| `executor` / `exec-backend` / `exec-dados` / `exec-frontend` | **pago** | implementar código |
| `orq_decidir` | local `d3:2b` | classificar antes de decidir (`/v1/systemone`) |

Cinco agentes pagos: o orquestrador e os quatro executores de código.

## Por que código continua no pago

O teste C (escrever uma função Python com dois testes pytest) aprovou **só dois modelos com
velocidade usável**:

| Modelo | C | tok/s | Carga |
|---|---|---|---|
| `gemma4:e4b` | OK | 52,9 | 15,6 s |
| `qwen3.5:4b` | OK | 52,4 | 20,8 s |

Todos os outros 4B–9B falharam em C. `bonsai-2:4b` (73,8 tok/s) passa em A, B e D, mas falha
em C. `qwen2.5-coder:7b` passa em B e D, falha em C — e é justamente o modelo documentado em
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) como **não emissor de `tool_calls`**.

Além disso, existe um limite do que o benchmark mede: são respostas de **um turno**. Ele não
testa chamar ferramenta, editar o arquivo certo e encerrar a sessão. O próprio
[`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) registra o caso oposto: o 4B "edita mas não
encerra a sessão" — motivo pelo qual `exec-docs` ficou tanto tempo no modelo pago.

Regra de bolso: um erro de `team_id` ou de policy custa mais caro do que o token economizado.
Por isso autorização, isolamento e migration nunca vão para o `exec-local` — o system prompt
dele manda bloquear nesses casos.

## Por que docs e arquivo único foram para o local

São os dois casos em que a falha é **detectável por script**, não por julgamento:

- docs: `~/.orquestrador/scripts/verificar_docs.py` reprova caminho inexistente, link
  quebrado e seção vazia. Se o local errar, o orquestrador barra;
- `exec-local`: a tarefa chega com critério objetivo e `comando_teste`, e o veredito vem do
  `run_tests` (exit code real). Modelo local que inventa não passa.

`gemma4-e4b-16k` foi validado nesses dois papéis antes de entrar: emite `tool_calls` nativos
(`read` e `edit`) pelo endpoint compatível com OpenAI, com `reasoning_effort: none`, e roda
com `num_ctx` 16384 embutido (`ollama ps` mostra `CONTEXT 16384`).

## O que mudou e por quê

| Antes | Depois | Motivo |
|---|---|---|
| `exec-docs` no modelo principal | `exec-docs` em `gemma4-e4b-16k` | docs têm verificador determinístico |
| não existia | `exec-local` (rota=local) | arquivo único + teste é o menor risco de edição |
| `local-mini` em `qwen-coder-8k` (1.5B) | `qwen3.5-08b-8k` | o 1.5B tirou nota 40 e falhou em A, B, C e D; o 0.8B passa em D |
| `output: 1024` no 4B | `output: 4096` | 1024 truncava qualquer arquivo real — falha garantida como executor |
| sem decisor no fluxo | MCP `decisao` (`orq_decidir`) | `d3:2b`: 92% de acerto, 8% de escalada, 2,2 s a quente |
| leitura de código só por instrução | `read` negado em `*.php`/`*.sql` + regra explícita | instrução sem negação não muda hábito |
| `local-helper` em `qwen3.5-4b` | `local-helper` em `gemma4-e4b-16k` | 3/5 de acerto contra 1/3 em cópia literal (ver teste abaixo) |

O `d3:2b` é o melhor decisor medido (24 casos sintéticos, split `teste`); `nimble-v3` acerta
83% mas leva 7,8 s por decisão, e `d1` escala em 50% dos casos. Como o dataset é sintético e
pequeno, o `orq_decidir` **escala** quando a confiança fica abaixo de 0,7 ou quando a escolha
é `nenhuma` — quem decide nesses casos é o modelo principal.

## Leitura de código: por que precisa de negação

A instrução "delegue leitura ao local-helper" existia desde a primeira versão do prompt e,
mesmo assim, o consumo local medido foi **0%** — instrução sem consequência não muda hábito.
O que muda é o par:

1. `read` de `*.php` e `*.sql` **negado** para o orquestrador (config global);
2. regra explícita no prompt: localizar com `kb`/`trail`, entender por delegação, e usar `read`
   só em Markdown, JSON/YAML de config e diff.

Medido numa pergunta real sobre `scripts/bench_omni.py` (24.406 bytes):

```
arquivo inteiro              ~6.102 tokens
resumo do local-helper         ~290 tokens
compressão                     ~21×
```

A resposta veio correta (linha de base sem áudio, tentativa por formato, critério de aceite
por diferença de resposta ou de tokens, e `BenchError` quando nenhum formato entra) — ou seja,
o resumo substitui o arquivo sem perda para a decisão que o orquestrador precisa tomar.

Limite dessa regra: o orquestrador **não** lê PHP/SQL direto. Para conferir o que um executor
mudou, usa `git diff` e `run_tests`; para um símbolo específico, `grep` (saída pequena). Se
precisar do arquivo inteiro no contexto pago, é sinal de que a tarefa deveria ser delegada.

## Teste da regra de leitura (29/10/2026)

A/B com processo novo (`opencode run --standalone`), orquestrador em modelo local para não gastar:

| Arquivo pedido | Resultado |
|---|---|
| `alvo.php` | `Permission denied: read` — o agente respondeu "NEGADO" |
| `alvo.md` | leu e devolveu o conteúdo |
| `grep MARCADOR` em `.php` | funcionou, com a linha encontrada (fallback determinístico) |

A negação também vale para a sessão já aberta: `read` em `.php` foi recusado sem reiniciar.

**O caminho de delegação é instável.** Na mesma pergunta ("use read em X e devolva o literal"),
o `local-helper` produziu, em 5 tentativas: 3 respostas corretas, 1 resposta vazia e 1 erro de
permissão inventado ("diretório externo negado", com o arquivo dentro do projeto). Com
`qwen3.5-4b` foram 3 tentativas: 1 correta, 1 vazia, 1 erro inventado. Por isso o
`local-helper` passou a usar `gemma4-e4b-16k` e o prompt do orquestrador ganhou três regras:

1. delegar de forma literal — dizer qual arquivo abrir, não "veja os arquivos";
2. pedir o retorno literal, e repetir uma vez se vier vazio ou truncado;
3. **fato** (nome, valor, linha) se confirma com `grep`, `run_tests` ou `git diff` — nunca só
   com o resumo do local.

Conclusão prática: o resumo do 4B serve para **entender**; para **afirmar**, use o caminho
determinístico.

## O primeiro teste real do `exec-local`

Tarefa: acrescentar um teste em `tests/test_bench_omni.py`, com `comando_teste`
`python -m unittest tests.test_bench_omni`. O agente respondeu:

```
RESULTADO: passou
EVIDENCIA: Ran 13 tests ... OK
```

O `git diff` mostrou outra coisa: ele **substituiu** o teste `test_rtf_sem_duracao` pelo novo.
A contagem continuou 13, o exit code continuou 0, e o veredito continuou verde — a remoção
era invisível para o `run_tests`.

Duas correções saíram desse caso:

1. o system prompt do `exec-local` proíbe remover, substituir ou reescrever o que já existe; se
   remover for necessário, ele tem de bloquear;
2. a etapa `INTEGRAR` do orquestrador passou a conferir **o diff**, não só "nenhum arquivo fora
   da lista" — remoção não autorizada é o modo de falha silencioso do modelo local.

Lição para medir: `passou` no `run_tests` não prova preservação. Um teste removido junto com um
teste novo dá o mesmo resultado verde. Quem pega isso é o diff.

## Como saber se está economizando

`scripts/custo_agentes.py` lê o histórico do OpenCode (`~/.local/share/opencode/storage`)
e soma entrada, cache e saída por agente e por sessão, separando o que rodou em modelo local
(provider `ollama`) do que rodou em modelo pago:

```powershell
python scripts/custo_agentes.py --por-sessao
python scripts/custo_agentes.py --projetos
python scripts/custo_agentes.py --desde 2026-10-01 --json > custo.json
```

O número que importa é a **razão entrada/saída**. Medição em projeto real desta máquina
(`emprestapro`, 6 sessões, 1.396 mensagens):

```
pago   entrada 8.075.215  cache 199.764.224  saída 496.522  razão 418,6:1
local  entrada         0  cache           0  saída       0
contexto processado no local: 0,0%
```

Três leituras:

1. **o volume é contexto, não edição** — 418 tokens processados por token escrito;
2. **o tier local não estava sendo usado** — 0% do contexto passou por ele;
3. **a sessão maior concentra o custo** — uma única sessão teve 865 mensagens e 138 milhões
   de tokens de cache relidos.

Por isso, fragmentar mais a tarefa **dentro da mesma sessão** aumenta o custo: cada turno
reenvia o contexto acumulado. O ganho vem de (a) usar o local e (b) sessão curta por tarefa.

Além do token, conte por tarefa:

1. quantos turnos rodaram no modelo pago (cada delegação a `exec-*` pago é um turno);
2. quantos voltaram `bloqueado` — devolução custa dois turnos pagos e é o pior cenário;
3. se o `exec-local` fechou com `RESULTADO: passou` na primeira tentativa.

Sinal de alarme: `exec-local` bloqueando com frequência indica que a tarefa não era de arquivo
único — o problema é o decompositor, não o modelo.

## Como reverter

Cada mudança é independente. Para voltar atrás, no `opencode/opencode.json`:

- `exec-docs`: `model` do agente → `null` (volta a herdar o principal);
- `exec-local`: remover o agente e a permissão `subagent/exec-local` do orquestrador;
- `local-mini`: `model` → o que preferir;
- `decisao`: remover o servidor de `mcp.servers` no `opencode/opencode.json`.

Depois de qualquer edição, reinicie o OpenCode — não há hot-reload completo.
