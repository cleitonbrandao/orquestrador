# Prompt de teste para modelos locais

Use este roteiro para testar qualquer modelo do Ollama nesta máquina e registrar o resultado em
[`MODELOS-TESTADOS.md`](MODELOS-TESTADOS.md).

Há duas partes:

1. **Velocidade**: um prompt fixo que mede tokens por segundo.
2. **Qualidade**: quatro prompts curtos, um por etapa do pipeline, cada um com um critério de aprovação objetivo.

Máquina de referência: notebook Linux, i7 13ª gen, 14 GB de RAM, só CPU. Os números só valem para
este equipamento; não compare com os de `AMBIENTE.md` (outra máquina).

## Atalho: o terminal interativo

Tudo abaixo está automatizado em `scripts/modelos.sh` (prompts, medição, correção, nota e CSV):

```bash
scripts/modelos.sh
modelos> /test qwen3.5:4b      # teste completo, nota 0-100
modelos> /bench qwen3.5:4b     # só velocidade
modelos> /rank                 # ranking por tok/s, nota ao lado
modelos> /nota                 # ranking por nota, tok/s ao lado
modelos> /list                 # testados e pendentes
modelos> /report               # relatório visual em docs/resultados/relatorio.html
modelos> /prune                # desinstala os modelos reprovados (pergunta antes)
modelos> /reset [modelo]         # apaga os resultados dos testes desta máquina (ou só de um modelo)
modelos> /help
```

O terminal não fecha ao fim de um teste. Antes do primeiro teste da sessão ele oferece a limpeza de RAM
(`/clean`): descarrega outros modelos do Ollama e pergunta antes de parar containers Docker, fechar
Teams/Chrome e limpar cache e swap. Containers parados são religados ao sair (ou com `/restore`).
Resultados medidos com RAM livre muito diferente não são comparáveis; a coluna `ram_disp_mb` do CSV e
o `/ver <modelo>` mostram a RAM livre de cada teste. `drop_caches` tem ganho pequeno (o cache já conta
como memória disponível); o ganho real vem de parar consumidores.

### Limpar modelos reprovados

`/prune` (ou `scripts/podar-modelos.sh`) remove do Ollama o que ficou inviável. Um modelo reprova
quando o **melhor** teste dele tem qualidade < 30/60 **ou** velocidade < 8 tok/s; mude com
`--min-qualidade N` e `--min-toks N`. `--dry-run` só lista.

- Pergunta `[s/N]` por modelo e depois confirma o total; sem terminal interativo não remove nada.
- Nunca remove: modelos usados no `opencode.json`, o modelo de embeddings do kb, modelos que não
  geram texto e modelos sem teste salvo. Os reprovados protegidos aparecem na lista com o motivo.
- Modelos derivados (`qwen-coder-8k` a partir de `qwen2.5-coder:1.5b`) compartilham os pesos:
  remover um não libera espaço enquanto o outro existir, e não quebra o que ficou.
- O histórico em `docs/resultados/resultados.csv` é mantido. Essa pasta não é versionada (está no `.gitignore`):
  os resultados dependem da máquina, então cada computador guarda os seus. `/reset` apaga os testes
  salvos (todos, ou só de um modelo) para recomeçar do zero em outra máquina; não desinstala modelos.

### No Windows (PowerShell)

Os mesmos comandos existem em PowerShell (`.ps1`), com o mesmo CSV, as mesmas notas e os mesmos
`/test`, `/bench`, `/rank`, `/nota`, `/list`, `/ver`, `/report`, `/clean`, `/restore`, `/ram`, `/prune`:

```powershell
scripts\modelos.cmd              # abre o terminal sem mexer na política de execução
# ou, em um PowerShell já aberto:
powershell -ExecutionPolicy Bypass -File scripts\modelos.ps1
.\scripts\testar-modelo.ps1 qwen3.5:4b -Think -Rapido     # teste direto (-Limpar, -Velocidade, -Listar)
.\scripts\podar-modelos.ps1 -DryRun -MinQualidade 30 -MinToks 8
```

- Requisitos: Windows PowerShell 5.1 ou superior, Ollama em execução e Python 3 (`python` ou `py`) no PATH.
- Use o **Windows Terminal** para as cores e os ícones. Os ícones Nerd Font são detectados pelas fontes
  instaladas; sem eles o visual usa símbolos Unicode (`$env:ORQ_ICONS = "nerd|unicode|ascii"` força um).
- Diferenças do Linux: a limpeza de RAM não limpa cache nem swap (o Windows libera o cache sozinho);
  sai do terminal com `/quit` ou Ctrl+Z e Enter, e Ctrl+C encerra o terminal (os containers parados
  são religados mesmo assim). A linha de memória do teste mostra CPU e GPU (`% CPU / % GPU`).
- O CSV ganhou a coluna `maquina` (nome do computador), porque notas de máquinas diferentes não são
  comparáveis: a velocidade vale 40 dos 100 pontos. Ao comparar, filtre por máquina.

O resto deste documento descreve o método manual.

## 1. Preparar a medição

Antes de cada modelo, para a medição ser comparável:

```bash
ollama stop <modelo>        # descarrega, para medir a carga a frio
free -h                     # anote a RAM "disponível" antes
ollama pull <modelo>        # só na primeira vez
```

Feche navegador e IDE pesados. Rode um modelo por vez.

## 2. Prompt de velocidade (tokens por segundo)

Salve como `/tmp/prompt-velocidade.txt` (ou cole direto no `ollama run`):

```text
Explique, em português, como funciona um índice B-tree em banco de dados relacional.
Cubra: estrutura de nós, busca, inserção com divisão de página e custo de leitura.
Escreva exatamente 6 parágrafos de 4 a 5 frases cada. Não use listas nem tabelas.
```

O pedido força uma resposta longa (cerca de 500 a 700 tokens), o que dá uma taxa estável.

### Opção A: `ollama run --verbose`

```bash
ollama run <modelo> --verbose < /tmp/prompt-velocidade.txt
```

No fim aparecem estas linhas. Anote as quatro marcadas:

```text
total duration:       ...
load duration:        ...   <- anote (s): tempo de carga do modelo
prompt eval count:    ...
prompt eval duration: ...
prompt eval rate:     ...   <- anote: tok/s de leitura do prompt
eval count:           ...
eval duration:        ...
eval rate:            ...   <- anote: tok/s de GERAÇÃO (a métrica principal)
```

Para modelos com *thinking*, o `ollama run` mostra o raciocínio antes da resposta e o `eval count`
inclui esses tokens. Mede-se duas vezes: com `/set nothink` e depois com `/set think`.

### Opção B: API (resultado já calculado)

Precisa de `jq`. Troque `MODELO` e, se o modelo tiver thinking, `"think"` entre `true` e `false`:

```bash
MODELO="qwen3.5:4b"
curl -s http://localhost:11434/api/generate -d "$(jq -n --arg m "$MODELO" --rawfile p /tmp/prompt-velocidade.txt \
  '{model:$m, prompt:$p, stream:false, think:false, options:{temperature:0, num_predict:700, num_ctx:4096}}')" \
| jq '{
    modelo: .model,
    tok_s_geracao: ((.eval_count / (.eval_duration/1e9)) * 10 | round / 10),
    tok_s_leitura: ((.prompt_eval_count / (.prompt_eval_duration/1e9)) * 10 | round / 10),
    carga_s: ((.load_duration/1e9) * 10 | round / 10),
    tokens_gerados: .eval_count,
    total_s: ((.total_duration/1e9) * 10 | round / 10)
  }'
```

Se o modelo não aceitar `think`, remova esse campo (a API devolve erro `does not support thinking`).

### Regras para o número valer

- Fixe `temperature: 0` e `num_ctx: 4096` em todos os modelos; contextos diferentes mudam RAM e velocidade.
- **Faça duas rodadas**: a 1ª (a frio, com `carga_s` alto) e a 2ª (a quente). Registre o `tok_s_geracao` da **2ª**; a carga da 1ª.
- Se `tokens_gerados` for menor que 300, o modelo cortou a resposta: a taxa fica pouco confiável. Anote na observação.
- Em outro terminal, rode `ollama ps` durante a geração. Registre o tamanho em memória e a coluna `PROCESSOR`.
  `100% CPU` é o esperado; qualquer outro valor vale registrar.
- Se `free -h` mostrar o swap crescendo, o modelo não cabe: anote "swap" na observação e descarte.

## 3. Prompts de qualidade (um por etapa)

Rode cada um com `ollama run <modelo>` (sem `--verbose`), `temperature` baixa, e marque ✅ ou ❌ conforme o critério.

### A. Planejamento

```text
Você é um planejador de software. Pedido: "adicionar paginação à listagem de clientes de uma API Laravel,
com os parâmetros page e per_page (máximo 100)".
Responda SOMENTE com um plano de exatamente 5 passos numerados. Cada passo tem no máximo 20 palavras e
cita o arquivo ou a camada afetada (rota, controller, request, resource, teste). Sem introdução e sem conclusão.
```

**Aprovado se:** há exatamente 5 passos, nenhum passa de 20 palavras, a validação do limite 100 aparece em algum passo e existe um passo de teste.

### B. Divisão em tarefas (JSON)

```text
Converta o plano abaixo em tarefas para agentes. Responda SOMENTE com JSON válido, sem texto antes ou depois,
sem markdown, neste formato:
{"tarefas":[{"id":1,"titulo":"...","arquivos":["..."],"depende_de":[],"criterio":"..."}]}

Plano:
1. Criar PaginacaoRequest validando page (inteiro >= 1) e per_page (inteiro 1..100).
2. Usar o request no ClienteController@index com paginate().
3. Devolver os dados via ClienteResource::collection.
4. Atualizar a rota GET /clientes se necessário.
5. Escrever teste de feature cobrindo per_page=101 (422) e per_page=10 (200).
```

**Aprovado se:** o texto inteiro é parseável (salve a resposta em `r.json` e rode `jq . r.json`), tem 5 tarefas, os ids são únicos, `depende_de` só aponta para ids existentes e nenhuma tarefa tem `arquivos` vazio.

### C. Execução (código com testes)

```text
Escreva em Python 3 uma função slugify(texto: str) -> str que:
- converte para minúsculas;
- remove acentos (ex.: "ação" vira "acao");
- troca qualquer sequência de caracteres não alfanuméricos por um único hífen;
- remove hífens no início e no fim.
Depois escreva 2 testes pytest: slugify("  Olá, Mundo!! ") == "ola-mundo" e slugify("---") == "".
Responda só com o código em um único bloco python, sem explicações.
```

**Aprovado se:** salvando o bloco como `t.py` e rodando `python3 -m pytest t.py -q`, os 2 testes passam sem editar o código.

### D. Revisão (bug plantado)

```text
Revise o diff abaixo. Liste somente problemas reais (bugs ou riscos), um por linha, no formato
"linha N: problema". Se não houver nenhum, responda "nenhum problema".

--- a/paginacao.py
+++ b/paginacao.py
@@ -1,9 +1,9 @@
 def paginar(itens, page, per_page):
     if per_page > 100:
         per_page = 100
-    inicio = (page - 1) * per_page
+    inicio = page * per_page
     fim = inicio + per_page
     return itens[inicio:fim]
```

**Aprovado se:** aponta que a página 1 pula os primeiros `per_page` itens (o início deveria ser `(page - 1) * per_page`) e não inventa mais de 1 problema falso. Falta de validação de `page < 1` é aceita como bônus, mas não substitui o bug principal.

## 4. Registrar o resultado

Preencha uma linha em [`MODELOS-TESTADOS.md`](MODELOS-TESTADOS.md) com: modelo, link, tamanho e quantização
(`ollama show <modelo>`), `tok_s_geracao` (2ª rodada), `tok_s_leitura`, `carga_s`, RAM usada, ✅/❌ de A a D e o veredito.

Referência para decidir o veredito (a ajustar com os seus números):

| Etapa | Velocidade mínima útil | Qualidade mínima |
|---|---|---|
| Roteador / divisor | 15 tok/s | B ✅ |
| Planejador / revisor | 8 tok/s | A ✅ e D ✅ |
| Executor | 8 tok/s | C ✅ |
