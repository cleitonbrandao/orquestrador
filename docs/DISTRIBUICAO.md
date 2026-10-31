# Distribuição de tarefas: local vs. pago

O que roda no modelo pago, o que roda local, e a evidência que sustenta essa divisão.
Números vindos de `docs/resultados/` (medidos nesta máquina) — a nota e os critérios estão
em [`MODELOS-TESTADOS.md`](MODELOS-TESTADOS.md) e [`PROMPT-TESTE.md`](PROMPT-TESTE.md).

## Divisão atual

| Camada | Modelo | Tarefa |
|---|---|---|
| `orquestrador` | **pago** | triagem, arquitetura, integração entre arquivos, veredito final |
| `decompositor` | local `qwen3.5-2b-32k` | quebrar o pedido em tarefas |
| `local-helper` | local `gemma4-e2b-32k` | ler e explicar código |
| `local-mini` | local `qwen3.5-08b-32k` | ler um trecho curto |
| `revisor` | local `qwen3.5-2b-32k` | revisar o diff (advisory) |
| `exec-local` | local `gemma4-e2b-32k` | editar **um** arquivo, com teste determinístico |
| `exec-docs` | local `gemma4-e2b-32k` | editar Markdown |
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

`rota=local` exige **exatamente um arquivo**: o decompositor não pode gerar `rota=local` com
2+ arquivos e o orquestrador reclassifica para `edicao`. Era esse o caso que derrubou o
`exec-local` em 29/10 (tarefa com `cli.py` + `test_alterdata.py`): o modelo local gastou
4.337 tokens, narrou o plano e não editou nada.

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
e soma entrada, cache e saída por agente, por dia e por sessão, separando o que rodou em
modelo local (provider `ollama`) do que rodou em modelo pago:

```powershell
python scripts/custo_agentes.py                  # projeto atual: agentes + economia
python scripts/custo_agentes.py --economia       # só economia e tendência (7 dias vs 7 anteriores)
python scripts/custo_agentes.py --diario         # série dia a dia, com % local e US$ evitado
python scripts/custo_agentes.py --grafico            # 7 dias até hoje, no terminal
python scripts/custo_agentes.py --grafico --dias 60  # janela maior (só via --dias)
python scripts/custo_agentes.py --por-sessao
python scripts/custo_agentes.py --projetos
python scripts/custo_agentes.py --desde 2026-10-01 --json > custo.json
```

No terminal de modelos, `/custo` (atalhos `/uso`, `/u`) roda
`--todos --economia --grafico`: histórico **global** de uso local contra pago, com o gráfico
dos **últimos 7 dias até hoje** e a quebra por modelo local. Para ampliar a janela, passe o
parâmetro: `/custo --dias 60`; `--precos` vale aqui também (`/custo --precos precos.json`).

O que entra nessa conta é o uso **real** — as sessões do OpenCode, onde os subagentes locais
rodam. Os `/test`/`/bench` do terminal de modelos não são uso: eles medem tok/s e qualidade e
aparecem em `/rank`, `/nota` e `/report`.

### O que o relatório mede

- **contexto pago por sessão** — o número que decide a conta. Sessão longa reenvia o
  contexto acumulado a cada turno; é isso que domina o custo, não a edição.
- **% local** — quanto do contexto processado passou pelo Ollama. É o espaço de manobra.
- **custo evitado** — os tokens locais precificados como se tivessem rodado no modelo pago
  de referência. Só aparece com `--precos`; sem ele o relatório não inventa dólar. Com preços,
  a coluna `EVITADO` do quadro por agente mostra **qual subagente local** rendeu a economia.
- **gráfico por dia** (`--grafico`) — barras de contexto local e pago com **escala própria por
  série**: o local continua visível mesmo sendo 1% do volume. A janela termina **hoje** e tem
  **7 dias** por padrão; mais tempo só com `--dias N` (`/custo --dias 60`). Dias sem atividade
  aparecem zerados.

Como o `cost` gravado pelo OpenCode é 0 em boa parte dos provedores (assinatura/copilot),
o valor em US$ é uma **estimativa** que vem de uma tabela mantida por você (valores de
exemplo — confira os preços atuais no provedor):

```json
{
  "referencia": "gemini-2.5-flash",
  "modelos": {
    "gemini-2.5-flash": {
      "input": 0.30,
      "cache_read": 0.03,
      "cache_write": 0.30,
      "output": 2.50
    }
  }
}
```

Preços em **US$ por 1M de tokens**. `referencia` escolhe qual modelo precifica o que rodou no
local; com mais de um modelo no arquivo, o campo é obrigatório. Schema inválido sai com a
mensagem do campo, não com traceback.

### A/B de configurações

O laço que responde "esta estrutura vale a pena" é comparar janelas: rode uma configuração por
alguns dias, outra na janela seguinte, e compare as mesmas métricas. Um arquivo de experimentos
nomeia as janelas — ou filtra pelo título da sessão, via `tag`:

```json
[
  { "nome": "sem local",    "de": "2026-10-01", "ate": "2026-10-15", "nota": "0% local" },
  { "nome": "local 2b",     "de": "2026-10-16", "ate": "2026-10-29", "nota": "8/10" },
  { "nome": "local + docs", "tag": "[A]",                            "nota": "9/10" }
]
```

```powershell
python scripts/custo_agentes.py --todos --comparar experimentos.json --precos precos.json
```

A tabela traz, por janela: mensagens, sessões, **contexto pago por sessão**, % local e US$
evitado. As linhas de `Δ` comparam cada janela com a primeira (a base). O critério de aprovação
não é só token: registre a nota de qualidade em `nota` — economia com resposta pior não conta.
Se o `exec-local` começar a bloquear mais, o ganho é falso.

A janela de 7 dias da tendência é ancorada no **último registro do histórico**, não no relógio:
histórico parado há meses não vira "tendência de queda".

A leitura por trás disso é a **razão entrada/saída** — o volume é contexto relido, não edição.
Medição em projeto real desta máquina (`emprestapro`, 6 sessões, 1.396 mensagens):

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

### Contexto antes do modelo pago

O maior custo não é a edição: é o contexto que entra na sessão paga. O
`scripts/contexto_local.py` faz esse corte **antes** da sessão abrir — lê os arquivos,
corta por linha/bytes com orçamento explícito, pede um resumo factual ao Ollama (com
`arquivo:linha`) e grava um Markdown:

```powershell
python scripts/contexto_local.py --pergunta "onde X é feito" src/a.py app/b.php
python scripts/contexto_local.py --pergunta "qual o erro?" --stdin < log.txt
python scripts/contexto_local.py --pergunta "..." --glob "app/**/*.php" --max-total 48000
```

No terminal de modelos: `/ctx src/a.py app/b.php` — ele pergunta a pergunta no terminal.
Depois, na sessão paga, peça para ler **só o Markdown** gerado (em
`~/.local/state/orquestrador/contexto/`), não os originais.

Com `--pacote contexto.json` ele grava também o pacote estruturado do Context
Manager (`docs/CONTEXT_MANAGER_ROADMAP.md` §6): arquivos lidos com linhas e
truncamento, referências `arquivo:linha`, métricas e as pendências. A validação é
**determinística** — não passa pelo modelo: arquivo inexistente, caminho fora da
raiz, `.env` e citação inventada viram `missing_information` com
`confirmed: false`, em vez de virar fato.

```powershell
python scripts/contexto_local.py --pergunta "..." --raiz . --pacote contexto.json src/a.py
```

Atenção à base de cada número: a linha `redução` do console compara o **prompt
enviado** com o resumo (inclui instruções); `context_metrics.reduction_percentage`
do pacote compara os **arquivos lidos** (bytes/4) com o resumo. São medidas
diferentes e ambas ficam registradas.

### Memória do projeto

O pacote não carrega histórico: carrega **regras e decisões**, que ficam fora da
conversa em `~/.local/state/orquestrador/memoria/<projeto>/`.

```powershell
python scripts/contexto_local.py --init-memoria --raiz .   # cria os dois modelos
# edite business_rules.json e decisions.json
python scripts/contexto_local.py --pergunta "..." --raiz . --pacote contexto.json src/a.py
```

- **Regras** entram **verbatim** em `critical_rules`, prefixadas com a prioridade
  (`P0 · …`). O modelo local nunca as reescreve; se ele sugerir regras, elas são
  descartadas quando há memória. **P0 entra sempre**; P1+ só entra quando a tarefa
  menciona a regra ou quando o caminho lido casa com o campo `applies_to`
  (`["*.jsx"]`, `["tools/conferencia-conversao/*"]`). Com 12 regras no
  `softnews-notion`, isso cortou ~40% do peso do pacote sem tocar em segurança.
- **Decisões** são filtradas por termos da pergunta e dos arquivos lidos (palavras
  comuns como "como"/"para" não contam) — sem casamento, entram as mais recentes,
  no máximo 5.
- Os arquivos citados por cada decisão são conferidos no disco: decisão que aponta
  arquivo inexistente vira `missing_information` com `confirmed: false`.

`--regras` e `--decisoes` aceitam caminhos alternativos; `--memoria` troca a pasta.

### Servidor MCP

`orq-contexto` (roadmap §10) expõe o que os scripts já fazem, sem reescrever lógica:

| Ferramenta | O que devolve |
|---|---|
| `context_build` | pacote §6 pronto (resumo local + regras + decisões + validação); `dry_run` não chama o modelo |
| `context_get_file` | trecho com número de linha, recusando `.env` e caminho fora da raiz |
| `context_get_rules` / `context_get_decisions` | memória do projeto, filtrada por prioridade/relevância |
| `context_validate` | revalida um pacote por objeto ou arquivo |
| `context_metrics` | redução média, tokens e pendências das execuções |
| `context_search` | busca textual no `kb` (precisa do app indexado) |

Tudo somente leitura: nada é escrito no projeto e o conteúdo lido é tratado como dado.
Cada `context_build` registra uma linha em `~/.local/state/orquestrador/contexto/metrics.jsonl`.

O prompt do **orquestrador** tem a regra `CONTEXTO (regra de custo)`: antes de ler
arquivos para entender uma área, chamar `context_build`; usar a memória por
`context_get_rules`/`context_get_decisions`; e tratar `confirmed: false` como
pendência, nunca como fato. A regra vale quando o contexto passa de ~2 mil tokens ou envolve 3+ arquivos; um
arquivo só com trecho pontual continua `local-helper`/`local-mini`.

**Cache (Fase 7).** Cada build custa 20–60 s de CPU. O pacote é cacheado por
conteúdo: tarefa + modelo + orçamento + caminho/tamanho/mtime de cada arquivo +
estado dos arquivos de memória. Repetir a mesma pergunta sobre os mesmos arquivos
devolve na hora (`cached: true`); editar arquivo ou regra invalida sozinho.
Medido aqui: 32,4 s no primeiro build, 0 s no segundo. Cache em
`~/.local/state/orquestrador/contexto/cache/`, podado em 7 dias / 200 entradas.

Para saber se a regra pega, `scripts/contexto_adocao.py` lê o histórico e mostra a taxa:
sessões que usaram o MCP ÷ sessões com trabalho de ferramenta, além das leituras diretas
(`read`/`grep`/`glob`/`kb`/`trail`). É medida de **escolha**, não de resultado.

O manifesto mostra o custo real medido pelo Ollama:

```
  CONTEXTO LOCAL
  pergunta     onde X é feito
  modelo       gemma4-e4b-16k:latest (31.2s)
  entrada      12.340 tokens em 4 arquivo(s)
  resumo         380 tokens
  redução      96.9% do contexto
  arquivo      /home/.../2026-10-29-...md
```

- `--dry-run` monta o prompt e não chama o modelo; `--json` devolve o manifesto para log.
- As linhas vão **numeradas** no prompt (`  12| ...`), então o resumo consegue citar
  `arquivo:linha`; `--sem-numeros` reduz o prompt e perde a citação exata.
- `--num-ctx` (padrão 16384) e `--max-total` (padrão 48 KB) são o orçamento; se o texto
  estimado passar do contexto, ele **falha antes** de chamar, em vez de truncar calado.
- `thinking` vai desligado (`think: false`): modelos de raciocínio gastam o orçamento sem
  responder.
- Modelo grande em CPU é lento: 1.068 tokens no `gemma4-e4b-16k` levaram ~3 min. Para
  iterar rápido use `--modelo` com um menor (escolha pelo `/rank`).
- O resumo é **dado derivado**, não instrução — o Markdown já abre com esse aviso.

Para medir o ganho: mesma tarefa em sessão nova, uma vez com os arquivos originais e outra
só com o resumo, e compare `contexto pago/sessão` no `/custo` (ou `--comparar` com janelas
rotuladas). Economia com resposta pior não conta.

## Como reverter

Cada mudança é independente. Para voltar atrás, no `opencode/opencode.json`:

- `exec-docs`: `model` do agente → `null` (volta a herdar o principal);
- `exec-local`: remover o agente e a permissão `subagent/exec-local` do orquestrador;
- `local-mini`: `model` → o que preferir;
- `decisao`: remover o servidor de `mcp.servers` no `opencode/opencode.json`.

Depois de qualquer edição, reinicie o OpenCode — não há hot-reload completo.
