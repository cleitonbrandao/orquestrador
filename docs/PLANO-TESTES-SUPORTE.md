# Plano de testes de modelos para suporte e análise de texto

Como estender a ferramenta de teste de modelos locais (`scripts/testar-modelo.sh`,
`scripts/modelos.sh`, `scripts/avaliar_respostas.py`, `scripts/relatorio.py`) para medir modelos naquilo
que **os fluxos de suporte e análise de texto** precisam — hoje sem cobertura nenhuma.

O que motiva: os prompts A–D medem **orquestração de código** (planejar, dividir em JSON, escrever
código, revisar diff). Nenhum deles mede o que `ia_relatorios` faz de verdade em produção:
**escolher uma entre N opções** (classificação de erro, prioridade de tarefa, classe/causa da análise
profunda) e **resumir/extrair texto de suporte sem inventar número**. Um modelo ótimo em A–D pode
ser péssimo nisso, e vice-versa.

---

## 1. Por que não basta acrescentar prompts E e F ao teste atual

O teste atual pressupõe um modelo que **gera texto**: mede tok/s de saída, salva `.txt` e avalia o
conteúdo com regex/JSON. Três coisas quebram nessa trilha:

| Problema | Consequência |
|---|---|
| Modelos de decisão (`d3`, `tev1`) **não geram texto** e usam `/v1/systemone`, não `/api/generate` | o script atual aborta em `gera_texto()` |
| A saída é probabilidade + rótulo, não prosa | não há o que avaliar com regex |
| `eval_count` de saída é **0** | a nota de velocidade (40 pontos) não faz sentido |

Logo: são **duas trilhas**, com métricas e pontuação próprias.

---

## 2. As duas trilhas

### Trilha E — Decisão (`/v1/systemone`)

Para modelos que escolhem entre opções: `d3:2b`, `d3:4b`, `tev1:0.8b`, `tev1:4b`,
`strands-decider:2b`, e qualquer decisor futuro.

**Não mede tok/s.** Mede acerto e custo de escalada, que é o que importa no `/v1/decide`.

| Métrica | Definição |
|---|---|
`acerto@1` | escolha == esperado, incluindo `nenhuma` quando o caso é fora de escopo |
`acerto_severidade` | entre os casos com severidade esperada, quantos acertaram |
`taxa_nenhuma` | % de respostas `nenhuma` (falso negativo operacional: sempre escala) |
`taxa_escalada` | % que escalaria com o limiar configurado (padrão 0,70) |
`ms_decisao` | p50 e p95 do tempo da chamada |
`ms_estimado` | `p50 + taxa_escalada × p50_do_4b` — tempo médio do `/v1/decide` completo |
`ram_gb` | `ollama ps` durante a rodada |
`opcoes_max` | maior número de opções que o modelo aceitou numa pergunta (teste de torneio) |

**Nota da trilha E (0–100):**

| Bloco | Pontos | Regra |
|---|---|---|
| Acerto do tipo | 60 | `60 × acerto@1` |
| Economia de escalada | 25 | 25 se ≤ 16% · 15 se ≤ 25% · 8 se ≤ 32% · 0 acima |
| Tempo estimado | 15 | 15 se ≤ baseline · 8 se ≤ 1,5× · 0 acima |

O baseline é medido na mesma máquina, na mesma rodada, com o `tev1:0.8b`. Nota só é comparável
dentro da mesma execução de dataset.

> **Severidade não entra na nota.** Em produção o `/v1/decide` usa a severidade **cadastrada no
> catálogo** (`severidade_padrao`), não a do modelo. Medir a severidade do modelo mediria algo que o
> fluxo não usa. Ela continua registrada na resposta bruta, para inspeção.
>
> **O bloco de tempo é o mais sensível à máquina.** No notebook (CPU, sem GPU) toda decisão custa
> segundos e todos os modelos tiram 0 nos 15 pontos. Nesse caso, compare **acerto e escalada**, e dê
> `--baseline-ms`/`--p50-escalada` coerentes com a máquina de produção.

### Trilha F — Análise de texto (geração)

Para modelos que escrevem: `qwen3.5:4b`, `gemma4:e2b/e4b`, `phi4-mini`, `granite4.2:3b`.

Três prompts, com critério **objetivo e determinístico** (nada de "parece bom"):

| Prompt | Tarefa | Critério de aprovação |
|---|---|---|
| **F1 — resumo fiel** | resumir uma SSC sintética com contagens conhecidas (12 trâmites, 3 anexos, 2 prazos) | cita **todos** os números obrigatórios, **nenhum** número fora da entrada, ≤ 120 palavras, sem promessa de prazo |
| **F2 — extração JSON** | extrair `{cliente, modulo, topico, situacao, urgencia}` de um texto de SSC | JSON válido, schema exato, campos conferem com o gabarito, `null` quando ausente (não inventa) |
| **F3 — resposta ao cliente** | redigir resposta a partir de fatos dados | não inventa prazo nem nome, cita o próximo passo, sem jargão interno proibido (lista fixa), ≤ 90 palavras |

Pontuação: `15` por prompt (máx. 45) + velocidade (até 40, mesma régua de 20 tok/s) = **85**, com
os 15 restantes reservados a "não inventou nada" (checagem dura em F1/F2). Para manter comparabilidade
com o CSV atual, grava em **CSV separado** (§7).

---

## 3. Dataset (versionado, fora de `docs/resultados/`)

`docs/resultados/` é gitignored (depende da máquina). **Casos são entrada, não resultado** — vão para
`casos/`, versionado, porque o veredito de um modelo só vale contra um dataset fixo.

```
casos/
  suporte/
    decisao/
      casos.json        # catálogo (opcoes/niveis/instrucoes) + 64 casos, com "split": dev|teste
    texto/
      f1-resumos.json
      f2-extracao.json
      f3-resposta.json
```

Um arquivo só, de propósito: catálogo e casos não podem divergir. O `split` no caso (`dev` ou
`teste`) substitui dois arquivos separados e é validado pelo avaliador — o runner **só roda `teste`
por padrão**; `dev` é para ajustar limiar e prompt.

### Formato — decisão

O mesmo do `php artisan ai:export-classification-cases` do BiDev, para o dataset real entrar sem
conversão:

```json
{
  "versao": 1,
  "origem": "sintetico | export-bi-dev | anonimizado",
  "instrucoes": "Which listed error type best matches the problem described?",
  "opcoes": {
    "1": "Banco de dados | Violação de integridade | Erro de PK/FK, duplicidade ou constraint",
    "2": "Infraestrutura | Falha de conexão | Servidor, listener, VPN ou rede indisponível"
  },
  "niveis": {
    "baixa": "cosmetic or minor, no impact on results",
    "media": "wrong result but a workaround exists",
    "alta": "blocks a process or produces wrong payroll values",
    "critica": "blocks payroll or legal deadlines for one or more clients"
  },
  "casos": [
    {
      "id": "db-01",
      "bucket": "banco",
      "texto": "[#1] Ao gravar a rescisão aparece SQLSTATE[23503] foreign key violation...",
      "esperado": "1",
      "severidade": "alta",
      "fonte": "sintetico",
      "dificuldade": "facil"
    },
    {
      "id": "fora-01",
      "bucket": "fora_de_escopo",
      "texto": "Cliente pediu treinamento sobre lançamento de horas extras.",
      "esperado": "nenhuma",
      "severidade": null,
      "fonte": "sintetico",
      "dificuldade": "facil"
    }
  ]
}
```

### Cobertura (64 casos: 40 `dev` + 24 `teste`)

| Bucket | Casos | Esperado | Por quê |
|---|---|---|---|
| banco | 8 | tipo 1 | SQLSTATE/constraint — o caso mais comum |
| acesso | 8 | tipo 3 | permissão, empresa, perfil |
| calculo | 8 | tipo 4 | INSS/IRRF/férias — onde errar custa caro |
| esocial | 8 | tipo 6 | códigos S-xxxx e rejeições |
| conversao | 8 | tipo 5 | dado não migrado, contagem divergente |
| relatorios | 8 | tipo 7 | total divergente, formatação |
| interface | 8 | tipo 8 | botão, campo, lista |
| texto | 8 | `nenhuma` | 5 administrativos (dúvida, treinamento) + 3 fora de escopo (elogio, cobrança) — mede o falso positivo |

A **ambiguidade** não é um bucket: são casos com dois tipos plausíveis, marcados com `aceitos[]`
(`calc-08` = cálculo ou relatório, `cv-08` = conversão ou eSocial). Contar como acerto qualquer um da
lista evita punir o modelo por uma escolha defensável.

Regras de rotulagem:

1. **Um rótulo por caso** (`esperado`), mais `aceitos[]` opcional.
2. **Nada de dado pessoal.** Nome de cliente → `Cliente A`; CPF/CNPJ/e-mail removidos. A regra do
   projeto (`AiRedactor`) vale para o dataset também.
3. **Texto real só anonimizado**, e o campo `fonte` diz de onde veio.
4. Caso novo entra como `dev`; **vira `teste` só depois de congelado**, e o conjunto de teste não é
   usado para ajustar prompt nem limiar. Sem isso a medição vira auto-engano.

---

## 4. Avaliador determinístico: `scripts/avaliar_decisao.py`

**Implementado.** Mesmo contrato do `avaliar_respostas.py`: **só biblioteca padrão**, imprime uma
linha e não chama rede nem modelo — recebe a resposta já gravada.

```bash
python3 -I scripts/avaliar_decisao.py --caso db-01 --esperado 1 --resposta resposta.json --limiar 0.7
# OK
# OK/escala: acertou 1 com confiança 0.55 < 0.70
# ESCALA: escolheu 2 (esperado 1) com confiança 0.41 < 0.70
# FALHA: escolheu 2 (esperado 1)
```

Contrato de entrada — aceita o corpo inteiro do `/v1/systemone` **ou** a resposta solta:

```json
{"answers": {"escolha": {"type": "choice", "choice": "1",
  "probabilities": {"1": 0.93, "2": 0.05}, "confidence": 0.93}}}
```

| Situação | Veredito |
|---|---|
| `choice` == `esperado` (ou em `aceitos`) | OK |
| acertou, mas `confidence` < limiar | `OK/escala` — o gateway chamaria o 4B (custo, não erro) |
| `choice` == `nenhuma` com `esperado` != `nenhuma` | ESCALA — o gateway escala em "nenhuma" **independente da confiança** |
| errou, `confidence` < limiar | ESCALA — a cascata decide |
| errou, `confidence` >= limiar | **FALHA** — "erra com convicção", o caso perigoso |
| sem `choice` / JSON inválido | FALHA |

Acerto e escalada são **dimensões independentes**: um decisor pode acertar tudo e ainda assim custar
caro. O runner conta as duas em separado, mais `falhas` (erro confiante), que não entra na nota mas é
o número que mais importa para confiar no decisor.

Comandos: `--validar ARQ` (integridade do dataset e do split) e `--agregar TSV [--tsv]`
(`casos, acerto, acerto_pct, escaladas, taxa_escalada_pct, falhas, p50_ms, p95_ms, ms_estimado, nota`).

---

## 5. Runner: `scripts/testar-decisor.sh`

**Implementado.** Irmão do `testar-modelo.sh`; o `/test` do terminal detecta modelo de decisão e
delega sozinho para ele.

```bash
scripts/testar-decisor.sh d3:2b                    # 24 casos de teste
scripts/testar-decisor.sh d3:2b --split dev        # 40 casos de ajuste
scripts/testar-decisor.sh d3:2b --amostra 5 --limiar 0.5
scripts/testar-decisor.sh d3:2b --torneio --visao docs/suporte/erro.png
scripts/testar-decisor.sh tev1:0.8b --p50-escalada 700 --baseline-ms 1500
```

Fluxo:

1. Checa Ollama (`/api/version`); avisa se for < 0.40.9 (o `d3` declara exigir, mas responde na 0.40.8).
2. Se o modelo não está instalado, pergunta antes de baixar.
3. Confere **capacidade de decisão** pelo `/api/show` (`capabilities` contém `decision`). Sem isso,
   aborta dizendo para usar o `testar-modelo.sh` (o caso do `qwen3.5:4b`).
4. Valida o dataset (`--validar`) e filtra pelo `split` (padrão `teste`).
5. Faz um pedido de aquecimento (não conta no resultado) e então, por caso: `POST /v1/systemone` com
   `state=texto`, `questions.escolha`, `keep_alive=10m`. Grava a resposta bruta em
   `docs/resultados/decisao/<modelo>/<data>/<id>.json` e o veredito em `avaliacao.tsv`.
6. Agrega (`avaliar_decisao.py --agregar`), mostra acerto / escalada / falhas / p50 / p95 / nota.
7. `--torneio`: pergunta sintética com 30 e com 40 opções, registra quantas voltaram.
   `--visao`: manda a imagem em base64 puro e registra se o endpoint aceita `images`.

O runner **não** testa a cascata com escalada: mede o decisor isolado. A escalada é **estimada**
(`taxa × p50 do 4B`, com `--p50-escalada`, padrão 700 ms). Medir a cascata de verdade é papel do
`avaliacao/classificacao.py` do `ia_relatorios`, que já existe.

**Pendente nesta trilha** (planejado, não implementado): `--idioma pt|en|bilingue` (paridade de
idioma), `--seed` e os prompts F1–F3 da trilha F.

---

## 6. Onde encaixa na ferramenta atual

| Arquivo | Mudança | Tam. | Status |
|---|---|---|---|
| `scripts/avaliar_decisao.py` | avaliador + agregador + `--validar` (stdlib) | M | **feito** |
| `scripts/testar-decisor.sh` | runner da trilha E | G | **feito** |
| `casos/suporte/decisao/casos.json` | 64 casos PT-BR, catálogo e split | M | **feito** |
| `scripts/testar-modelo.sh` | detecta modelo de decisão e delega; `situacao` lê o CSV E | P | **feito** |
| `scripts/limpar-ram.sh` | `tem_decisao()`; `nomes_testaveis` inclui decisores | P | **feito** |
| `scripts/modelos.sh` | comando `/decisao` e ajuda | P | **feito** |
| `tests/test_avaliar_decisao.py` | 22 testes determinísticos (unittest) | M | **feito** |
| `scripts/avaliar_respostas.py` | `avaliar_f1/f2/f3` | M | pendente |
| `scripts/relatorio.py` | `decisao` / `rank-decisao`; `lista` por trilha | M | pendente |
| `scripts/podar-modelos.sh` | decidir o que fazer com decisor reprovado | P | pendente |
| `docs/MODELOS-TESTADOS.md` | seção "decisor escolhido" | P | pendente |
| `docs/PROMPT-TESTE.md` | §5 (trilha E) e §6 (trilha F) | M | pendente |

### Comandos no terminal

```text
/test d3:2b                  # detecta decisão e cai na trilha E
/decisao d3:2b [--split dev] [--amostra N] [--limiar 0.7] [--torneio] [--visao print.png]
```

---

## 7. CSV da trilha E

Arquivo separado (`docs/resultados/decisao.csv`), porque as colunas são outras e misturar estraga os
rankings atuais. Colunas reais:

```csv
data,modelo,casos,split,dataset_hash,acerto,acerto_pct,escaladas,taxa_escalada_pct,falhas,p50_ms,p95_ms,ms_estimado,nota,tempo_s,ram_disp_mb,maquina,opcoes_max,visao
2026-10-28_12:00,d3:2b,24,teste,55012b4301bf,16,66.7,14,58.3,0,7858,8114,8266,40,285,6117,cletion-Inspiron-15-3530,40,sim
2026-10-28_12:03,tev1:0.8b,24,teste,55012b4301bf,10,41.7,15,62.5,0,4265,4444,4702,25,99,4855,cletion-Inspiron-15-3530,,
```

`dataset_hash` (sha256 curto do `casos.json`) substitui a "versão" manual: nota de datasets
diferentes não se compara. `split` diz se a linha é ajuste ou veredito — **só `teste` vale como
veredito**.

---

## 7b. Primeira medição (2026-10-28, notebook sem GPU)

`d3:2b` e `tev1:0.8b` no **mesmo** dataset, 24 casos de teste, limiar 0,70:

| | `d3:2b` | `tev1:0.8b` |
|---|---|---|
| Acerto | **16/24 (66,7%)** | 10/24 (41,7%) |
| Escalaria | **14/24 (58,3%)** | 15/24 (62,5%) |
| Erra com convicção | 0 | 0 |
| p50 | 7,9 s | 4,3 s |
| 30 / 40 opções | aceita | não testado |
| Imagem | aceita (0,81 de confiança) | não tem |

Leitura:

- **O d3 é bem melhor que o tev1 no nosso texto de suporte** (+25 pontos de acerto) e escala um pouco
  menos. A confiança é confiável: **nenhum dos dois errou com convicção** no limiar 0,70 — todo erro
  caiu em "escalar".
- **66,7% ainda está longe dos 90%** do critério de adoção. Com a cascata, o 4B resolve o resto, mas
  **58% de escalada** custa mais que os 32% atuais (medidos em outro conjunto, de 22 casos).
- **O acerto não muda com o limiar** (66,7% de 0,3 a 0,9). O que muda é o que a cascata recebe:

| Limiar | Escalaria | Erra com convicção |
|---|---|---|
| 0,3–0,4 | 12,5% | 5 |
| 0,5 | 25,0% | 3 |
| 0,6 | 41,7% | 1 |
| 0,7 | 58,3% | 0 |

  Ou seja: baixar o limiar economiza escalada e deixa passar erro confiante. Para um fluxo que só
  sugere e tem revisão humana, 0,5–0,6 pode ser razoável; para classificação que dispara ação, 0,7.
- **A latência desta máquina não vale para produção** (CPU, sem GPU): 7,9 s por decisão. Na máquina
  do gateway, com a RX 7600, o mesmo modelo deve ficar na casa das centenas de ms — medir lá.

Conclusão da primeira rodada: **o d3 é o melhor decisor que já medimos** (66,7% × 41,7%), mas ainda
longe do corte. A rodada seguinte mostrou que boa parte do erro era do catálogo, não do modelo.

---

## 7c. Ajuste no `dev` e validação no `teste`

O que mudou entre as rodadas: os `criteria` das 8 opções ganharam os casos que faltavam (deadlock,
senha/bloqueio, lista que não atualiza, layout sobreposto, relatório que diverge do cálculo) e a
instrução passou a dizer que dúvida, pedido, treinamento, elogio e cobrança são `nenhuma`.
**Nenhum caso do teste foi alterado** — só a definição das opções.

| Rodada | `d3:2b` | `tev1:0.8b` |
|---|---|---|
| Catálogo v1 (24 casos) | 66,7% · escalada 58,3% | 41,7% · escalada 62,5% |
| Catálogo v2 (24 casos) | **91,7%** · escalada 29,2% (a 0,7) | 66,7% · escalada 50,0% |

Curva de limiar com o catálogo v2 (o acerto não muda; muda o custo e o risco):

| Limiar | `d3` escalada | `d3` erros confiantes | `tev1` escalada | `tev1` erros confiantes |
|---|---|---|---|---|
| 0,4 | 4,2% | 1 | 20,8% | 3 |
| 0,5 | 8,3% | 1 | 20,8% | 3 |
| **0,6** | **12,5%** | **1** | 41,7% | 1 |
| 0,7 | 29,2% | 1 | 50,0% | 0 |
| 0,8 | 45,8% | 0 | 50,0% | 0 |

**Custo escondido:** o catálogo maior encareceu o prompt — p50 de 7,9 s para 11,4 s em CPU (+44%).
Em GPU a proporção deve ser menor, mas prompt maior não é de graça.

**Ressalva metodológica:** o console mostra caso a caso, então o conjunto de teste foi **visto** antes
do ajuste. O ajuste foi guiado pelos erros do `dev` (relatório × cálculo, botão desabilitado), mas o
número de 91,7% é **otimista** e precisa de confirmação no export real do BiDev.

**Conclusão:** com catálogo claro e limiar 0,6, o d3 atende ao critério numérico e domina o `tev1`.
Não é adoção ainda: falta o conjunto real e a medição de VRAM/latência na máquina de produção.

---

## 8. Testes da própria ferramenta

A ferramenta decide qual modelo entra em produção; se ela mentir, a decisão é errada. Por isso os
avaliadores têm teste determinístico, **sem GPU e sem Ollama**.

**Implementado:** `tests/test_avaliar_decisao.py`, 22 testes em `unittest` (stdlib — a máquina não tem
pytest instalado), cobrindo:

```python
# 1. acerto exato → OK
# 2. opção errada com confiança → FALHA com as duas opções na mensagem
# 3. "nenhuma" com esperado != "nenhuma" → ESCALA (o gateway escala sempre)
# 4. "nenhuma" com esperado "nenhuma" → OK/escala
# 5. acerto com confiança baixa → OK/escala (não vira erro)
# 6. erro com confiança baixa → ESCALA (a cascata decide)
# 7. sem "choice" / JSON vazio → FALHA, sem exceção
# 8. sem "confidence" → não quebra
# 9. aceitos[] conta como acerto
# 10. aceita corpo inteiro do /v1/systemone e resposta solta
# 11. limiar customizado
# 12. agregador: 3 acertos em 4, 1 escalada, tempos → nota 75 exata
# 13. escalada alta zera o peso; tempo lento zera o peso; lista vazia
# 14. dataset: id repetido, esperado inexistente, split inválido, texto vazio, aceito inexistente
# 15. o casos.json do repositório passa na validação e tem >= 64 casos com dev e teste
```

Rodar: `python3 -m unittest discover -s tests -v` (aceito pelo `run_tests`).

Checagem de **integridade do dataset**, que evita erro silencioso:

```bash
python3 -I scripts/avaliar_decisao.py --validar casos/suporte/decisao/casos.json
# OK: 64 casos (40 dev, 24 teste), 8 opções, 4 níveis
# FALHA: calc-09: esperado "9" não existe em opcoes
```

---

## 9. Orçamento de execução e contenção de GPU

| Cenário | Chamadas | Tempo estimado (CPU, 14 GB) |
|---|---|---|
| Trilha E, 24 casos | 24 (+2 torneio) | 1–4 min por modelo |
| Trilha E, 64 casos | 64 | 3–10 min por modelo |
| Trilha F, 3 prompts | 3 | 2–6 min por modelo |
| Bateria completa (4 modelos × E + 2 × F) | ~270 | 30–60 min |

Regras para o número valer:

1. **Um modelo por vez.** `--limpar` antes de cada medição (o script já faz).
2. **Mesma RAM livre** (±1 GB) — a coluna `ram_disp_mb` existe para isso.
3. **Sem rodar junto com o gateway** (`ia_relatorios`) nem com o OpenCode. Se o gateway estiver no ar,
   ele segura o 4B na VRAM (`keep_alive=10m`) e contamina a medição.
4. **Duas rodadas, vale a segunda** (a primeira paga o carregamento). Para decisão, isso importa
   menos (a chamada é curta), então registrar `carga_s` e rodar 3 casos de aquecimento antes de contar.
5. **Não comparar máquinas.** O notebook (Iris Xe, CPU) mede acerto e custo relativo; a latência de
   produção só vale medida no PC com a RX 7600.

---

## 10. Critério de adoção por fluxo

| Fluxo | Métrica que decide | Corte |
|---|---|---|
| `MODELO_DECISOR` do gateway (`/v1/decide`) | acerto@1 + taxa de escalada | ≥ 90% e ≤ 16% |
| `softnews-notion` classificação de erro | acerto@1 no export real | ≥ 90% (hoje a cascata faz 100% em 22 casos sintéticos) |
| `softnews` prioridade de tarefa | acerto@1 em 4 classes | ≥ 85% (é decisão de baixo risco) |
| qualquer decisor | p95 | ≤ 1,5 s na máquina de produção |
| modelo de texto (F) | nota F | ≥ 55/85, e F1 sem número inventado |

**Regra de ouro:** acerto abaixo do baseline atual **nunca** se compensa com velocidade. O contrário
(mais acerto, mais lento) pode se compensar se a taxa de escalada cair — é o caso do d3.

---

## 11. O que não fazer

- **Não reusar a nota A–D** para decisor. `eval_count = 0` faz a nota virar só qualidade de regex,
  e o ranking atual misturaria coisas incomparáveis.
- **Não medir só acerto.** Um decisor que acerta 95% e diz "nenhuma" em 40% dos casos é pior na
  operação do que um que acerta 88% e escala 10% — o primeiro sempre cai no 4B.
- **Não testar com o dataset de ajuste.** Se o limiar foi escolhido nos 64 casos, a nota nos 64 está
  inflada. Separar dev/teste desde o primeiro dia.
- **Não rodar com a máquina em bateria/economia** nem com Docker/Chrome abertos: a nota de velocidade
  varia 2–3× (já observado: `qwen3.5:4b` deu 52 tok/s e 6,9 tok/s em dois testes).
- **Não colocar o dataset em `docs/resultados/`** — é gitignored, e o dataset precisa ser versionado
  para o veredito ser reproduzível.
