#!/usr/bin/env bash
# Testa um modelo do Ollama: mede tok/s, roda os prompts A-D de docs/PROMPT-TESTE.md,
# salva o resultado e mostra a pontuação.
#
# Uso: scripts/testar-modelo.sh [modelo] [--think] [--rapido]
#   modelo    nome no Ollama (ex.: qwen3.5:4b). Se omitido, o script pergunta.
#   --think   liga o thinking nos modelos que o suportam (padrão: desligado)
#   --rapido  gera 300 tokens na medição de velocidade em vez de 700
#   --velocidade  mede só tok/s (rápido), sem os prompts de qualidade e sem salvar nada
#   --limpar  antes do teste, libera RAM (descarrega outros modelos; pergunta antes de
#             parar containers, fechar apps e limpar cache/swap) e restaura no fim
#   --listar  mostra os testes salvos com a nota e os modelos que faltam testar
#
# Ao terminar um teste completo, abre o terminal interativo (scripts/modelos.sh),
# com /rank, /nota, /list, /report e os demais comandos.
#
# Requisitos: ollama em execução, curl, jq, python3.
set -u -o pipefail

API="${OLLAMA_HOST_URL:-http://localhost:11434}"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AVALIADOR="$RAIZ/scripts/avaliar_respostas.py"
RELATORIO="$RAIZ/scripts/relatorio.py"
SAIDA="${ORQ_RESULTADOS:-$RAIZ/docs/resultados}"   # ORQ_RESULTADOS isola testes do CSV real
CSV="$SAIDA/resultados.csv"
CSV_DECISAO="$SAIDA/decisao.csv"
# shellcheck source=limpar-ram.sh
source "$RAIZ/scripts/limpar-ram.sh"

# shellcheck source=visual.sh
source "$RAIZ/scripts/visual.sh"

# passo <n> <texto>: linha de progresso (n de 5)
passo() { printf '  %s%s%s %s[%s/5]%s %s\n' "$(fg "$P_AMAR")" "$I_TESTE" "$N" "$DIM" "$1" "$N" "$2"; }

# situacao <modelo>: última nota e tok/s do modelo (texto), ou da trilha de decisão.
situacao() {
  local r=""
  if [ -f "$CSV" ]; then
    r="$(awk -F, -v n="${1%:latest}" 'NR>1 { m=$2; sub(/:latest$/,"",m); if (m==n) r="nota " $15 "/100, " $4 " tok/s" } END { print r }' "$CSV")"
  fi
  if [ -z "$r" ] && [ -f "$CSV_DECISAO" ]; then
    r="$(awk -F, -v n="${1%:latest}" 'NR>1 { m=$2; sub(/:latest$/,"",m); if (m==n) r="decisão " $6 "/" $3 " (" $7 "%), nota " $14 "/100" } END { print r }' "$CSV_DECISAO")"
  fi
  [ -n "$r" ] && echo "$r"
}

listar() {
  local inst
  inst="$(nomes_testaveis | paste -sd, -)"
  python3 -I "$RELATORIO" lista --csv "$CSV" --instalados "${inst:-}"
}

MODELO=""
THINK=0
NP_VEL=700
SO_VELOCIDADE=0
LIMPAR=0
for arg in "$@"; do
  case "$arg" in
    --think) THINK=1 ;;
    --rapido) NP_VEL=300 ;;
    --listar|-l) listar; exit 0 ;;
    --velocidade) SO_VELOCIDADE=1 ;;
    --limpar) LIMPAR=1 ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    -*) echo "opção desconhecida: $arg" >&2; exit 2 ;;
    *) MODELO="$arg" ;;
  esac
done

# Fora do terminal interativo, não fecha ao terminar: abre o scripts/modelos.sh.
continuar_no_terminal() {
  if [ -t 0 ] && [ -t 1 ] && [ -z "${ORQ_CLI:-}" ]; then
    echo
    read -r -p "Enter para abrir o terminal de modelos (/help lista os comandos), q para sair: " r || return 0
    [[ "$r" =~ ^[qQ]$ ]] && return 0
    LIMPOU_AQUI=0   # a sessão interativa assume a restauração dos containers
    if [ -s "$ESTADO" ]; then
      echo "(containers parados continuam na lista de restauração do terminal)"
    fi
    rm -rf "${TMP:-}"
    exec "$RAIZ/scripts/modelos.sh"
  fi
}

for cmd in curl jq python3; do
  command -v "$cmd" >/dev/null || { echo "faltando: $cmd" >&2; exit 1; }
done
curl -s --max-time 5 "$API/api/version" >/dev/null || {
  echo "Ollama não responde em $API. Inicie com 'ollama serve'." >&2; exit 1; }

if [ -z "$MODELO" ]; then
  echo "Modelos instalados:"
  while read -r nome; do
    s="$(situacao "$nome")"
    if [ -n "$s" ]; then printf '  [testado]      %s  (%s)\n' "$nome" "$s"
    else printf '  [falta testar] %s\n' "$nome"; fi
  done < <(nomes_testaveis)
  echo "  (scripts/testar-modelo.sh --listar mostra o ranking por tok/s)"
  read -r -p "Nome do modelo no Ollama: " MODELO
fi
[ -n "$MODELO" ] || { echo "nenhum modelo informado" >&2; exit 2; }

if ! curl -s "$API/api/tags" | jq -e --arg m "$MODELO" \
    '.models[] | select(.name==$m or .name==($m+":latest"))' >/dev/null; then
  read -r -p "'$MODELO' não está instalado. Baixar agora? [s/N] " r
  [[ "$r" =~ ^[sSyY]$ ]] || exit 1
  ollama pull "$MODELO" || exit 1
fi

if ! gera_texto "$MODELO"; then
  # Modelo de decisão (d3, tev1): não gera texto, vai para a trilha E.
  if tem_decisao "$MODELO"; then
    if [ "$SO_VELOCIDADE" = 1 ]; then
      echo "${AMAR}$MODELO é modelo de decisão: não tem tok/s.${N} Use /decisao $MODELO (acerto e escalada)." >&2
      exit 2
    fi
    args=("$MODELO")
    [ "$LIMPAR" = 1 ] && args+=(--limpar)
    exec "$RAIZ/scripts/testar-decisor.sh" "${args[@]}"
  fi
  echo "${VERM}${I_FALHA} $MODELO não gera texto (modelo de embeddings).${N} Ele não responde aos prompts de teste;" >&2
  echo "  escolha um modelo de linguagem. Use /list para ver os testáveis." >&2
  exit 1
fi

# Capacidades: o parâmetro "think" só pode ser enviado a modelos que o suportam.
TEM_THINKING=0
curl -s "$API/api/show" -d "$(jq -n --arg m "$MODELO" '{model:$m}')" \
  | jq -e '.capabilities // [] | index("thinking")' >/dev/null && TEM_THINKING=1
if [ "$TEM_THINKING" = 1 ]; then
  if [ "$THINK" = 1 ]; then EXTRA='{"think":true}'; THINK_ROTULO=on
  else EXTRA='{"think":false}'; THINK_ROTULO=off; fi
else
  EXTRA='{}'; THINK_ROTULO='n/a'
  [ "$THINK" = 1 ] && echo "aviso: $MODELO não tem thinking; --think ignorado."
fi

AGORA="$(date +%Y-%m-%d_%H-%M-%S)"
DIR="$SAIDA/${MODELO//[:\/]/_}/$AGORA"
mkdir -p "$DIR"
TMP="$(mktemp -d)"
LIMPOU_AQUI=0
trap 'rm -rf "$TMP"; [ "$LIMPOU_AQUI" = 1 ] && restaurar' EXIT
INICIO=$SECONDS
if [ "$LIMPAR" = 1 ]; then
  echo
  LIMPOU_AQUI=1
  limpar "$MODELO"
fi

# gerar <arquivo_prompt> <num_predict> <arquivo_saida_json>
gerar() {
  jq -n --arg m "$MODELO" --rawfile p "$1" --argjson np "$2" --argjson extra "$EXTRA" \
    '{model:$m, prompt:$p, stream:false,
      options:{temperature:0, seed:42, num_ctx:4096, num_predict:$np}} + $extra' \
  | curl -s --max-time 900 "$API/api/generate" -d @- > "$3"
}

# --- Prompts (mesmos de docs/PROMPT-TESTE.md) ---
cat > "$TMP/vel.txt" <<'EOF'
Explique, em português, como funciona um índice B-tree em banco de dados relacional.
Cubra: estrutura de nós, busca, inserção com divisão de página e custo de leitura.
Escreva exatamente 6 parágrafos de 4 a 5 frases cada. Não use listas nem tabelas.
EOF
cat > "$TMP/A.txt" <<'EOF'
Você é um planejador de software. Pedido: "adicionar paginação à listagem de clientes de uma API Laravel,
com os parâmetros page e per_page (máximo 100)".
Responda SOMENTE com um plano de exatamente 5 passos numerados. Cada passo tem no máximo 20 palavras e
cita o arquivo ou a camada afetada (rota, controller, request, resource, teste). Sem introdução e sem conclusão.
EOF
cat > "$TMP/B.txt" <<'EOF'
Converta o plano abaixo em tarefas para agentes. Responda SOMENTE com JSON válido, sem texto antes ou depois,
sem markdown, neste formato:
{"tarefas":[{"id":1,"titulo":"...","arquivos":["..."],"depende_de":[],"criterio":"..."}]}

Plano:
1. Criar PaginacaoRequest validando page (inteiro >= 1) e per_page (inteiro 1..100).
2. Usar o request no ClienteController@index com paginate().
3. Devolver os dados via ClienteResource::collection.
4. Atualizar a rota GET /clientes se necessário.
5. Escrever teste de feature cobrindo per_page=101 (422) e per_page=10 (200).
EOF
cat > "$TMP/C.txt" <<'EOF'
Escreva em Python 3 uma função slugify(texto: str) -> str que:
- converte para minúsculas;
- remove acentos (ex.: "ação" vira "acao");
- troca qualquer sequência de caracteres não alfanuméricos por um único hífen;
- remove hífens no início e no fim.
Depois escreva 2 testes pytest: slugify("  Olá, Mundo!! ") == "ola-mundo" e slugify("---") == "".
Responda só com o código em um único bloco python, sem explicações.
EOF
cat > "$TMP/D.txt" <<'EOF'
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
EOF

echo
pl_linha "$P_ROXO" "$P_TEXTO" "$I_FRASCO  Testando" "$P_ESCURO" "$P_CIANO" "$MODELO" "$P_ESCURO" "$P_CINZA" "thinking: $THINK_ROTULO"

# --- 1. Velocidade: rodada a frio e rodada a quente ---
echo
passo 1 "Velocidade (a frio, depois a quente; $NP_VEL tokens)"
curl -s "$API/api/generate" -d "$(jq -n --arg m "$MODELO" '{model:$m, keep_alive:0}')" >/dev/null
sleep 2
RAM_DISP=$(mem_disp_mb)
echo "      ${DIM}RAM disponível no início: ${RAM_DISP} MB${N}"
gerar "$TMP/vel.txt" "$NP_VEL" "$TMP/frio.json"
gerar "$TMP/vel.txt" "$NP_VEL" "$TMP/quente.json"
for f in frio quente; do
  if jq -e '.error' "$TMP/$f.json" >/dev/null 2>&1 || ! jq -e '.eval_duration' "$TMP/$f.json" >/dev/null 2>&1; then
    echo "erro do Ollama: $(jq -r '.error // "sem resposta"' "$TMP/$f.json" 2>/dev/null)" >&2
    exit 1
  fi
done
cp "$TMP/frio.json" "$DIR/velocidade_frio.json"
cp "$TMP/quente.json" "$DIR/velocidade_quente.json"

TOK_GER=$(jq -r '(.eval_count/(.eval_duration/1e9))*10|round/10' "$TMP/quente.json")
# Leitura do prompt vem da rodada a frio: na quente o prompt já está em cache e a taxa sai inflada.
TOK_LEIT=$(jq -r '(.prompt_eval_count/(.prompt_eval_duration/1e9))*10|round/10' "$TMP/frio.json")
CARGA=$(jq -r '(.load_duration/1e9)*10|round/10' "$TMP/frio.json")
TOKENS=$(jq -r '.eval_count' "$TMP/quente.json")
MINIMO=$(( NP_VEL / 2 ))

read -r RAM_GB CPU_PCT < <(curl -s "$API/api/ps" | jq -r --arg m "$MODELO" \
  '[.models[] | select(.name==$m or .name==($m+":latest"))][0]
   | if . == null then "0 0"
     else "\((.size/1e9)*10|round/10) \(if .size>0 then ((.size-.size_vram)/.size*100|round) else 0 end)" end')

if [ "$SO_VELOCIDADE" = 1 ]; then
  echo
  pl_linha "$P_AMAR" "$P_BASE" "$I_BOLT  Velocidade" "$P_ESCURO" "$P_CIANO" "$MODELO"
  echo
  printf "  geração   %s%s%7s tok/s%s  %s\n" "$(fg "$P_CIANO")" "$(neg)" "$TOK_GER" "$N" "$(barra_v "$TOK_GER" 40 20 "$P_CIANO")"
  printf "  leitura   %7s tok/s\n  carga     %7s s\n" "$TOK_LEIT" "$CARGA"
  printf "  memória   %7s GB em uso | %s%% na CPU | RAM livre no início: %s MB\n" "$RAM_GB" "$CPU_PCT" "$RAM_DISP"
  [ "$TOKENS" -lt "$MINIMO" ] && echo "  ${AMAR}${I_FALHA} aviso:${N} só $TOKENS tokens gerados; a taxa é pouco confiável."
  echo "${DIM}  (só velocidade: nada foi salvo; use /test para a avaliação completa)${N}"
  rm -rf "$DIR"; rmdir "$(dirname "$DIR")" "$SAIDA" 2>/dev/null
  continuar_no_terminal
  exit 0
fi

# --- 2. Qualidade: prompts A-D ---
declare -A RES
declare -A NP=( [A]=600 [B]=1200 [C]=1200 [D]=600 )
declare -A NOME=( [A]="Planejamento" [B]="Divisão JSON" [C]="Código" [D]="Revisão" )
i=2
for t in A B C D; do
  passo "$i" "$t. ${NOME[$t]}"
  gerar "$TMP/$t.txt" "${NP[$t]}" "$TMP/$t.json"
  jq -r '.response // ""' "$TMP/$t.json" > "$DIR/resposta_$t.txt"
  RES[$t]=$(python3 -I "$AVALIADOR" "$t" "$DIR/resposta_$t.txt")
  i=$((i+1))
done

# --- 3. Pontuação ---
# Qualidade: 15 pontos por prompt (máx. 60). Velocidade: até 40 pontos, 40 em >= 20 tok/s.
PONTOS_Q=0
for t in A B C D; do [ "${RES[$t]}" = "OK" ] && PONTOS_Q=$((PONTOS_Q+15)); done
PONTOS_V=$(awk -v v="$TOK_GER" 'BEGIN{p=v/20*40; if(p>40)p=40; printf "%d", p+0.5}')
NOTA=$((PONTOS_Q + PONTOS_V))
TEMPO=$(( SECONDS - INICIO ))

ok() { [ "${RES[$1]}" = "OK" ] && echo "✅" || echo "❌"; }
serve=""
awk -v v="$TOK_GER" 'BEGIN{exit !(v>=15)}' && [ "${RES[B]}" = "OK" ] && serve="$serve roteador/divisor"
awk -v v="$TOK_GER" 'BEGIN{exit !(v>=8)}' && [ "${RES[A]}" = "OK" ] && [ "${RES[D]}" = "OK" ] && serve="$serve planejador/revisor"
awk -v v="$TOK_GER" 'BEGIN{exit !(v>=8)}' && [ "${RES[C]}" = "OK" ] && serve="$serve executor"
[ -n "$serve" ] || serve=" nenhuma etapa (abaixo do mínimo de velocidade ou qualidade)"

COR_NOTA="$(cor_nota "$NOTA")"

echo
pl_linha "$P_VERDE" "$P_BASE" "$I_PRONTO  Resultado" "$P_ESCURO" "$P_CIANO" "$MODELO" "$COR_NOTA" "$P_BASE" "$I_NOTA $NOTA/100"
echo
printf "  %s%s Velocidade%s\n" "$(fg "$P_CIANO")" "$I_BOLT" "$N"
printf "    geração   %s%s%7s tok/s%s  %s\n" "$(fg "$P_CIANO")" "$(neg)" "$TOK_GER" "$N" "$(barra_v "$TOK_GER" 40 20 "$P_CIANO")"
printf "    leitura   %7s tok/s\n    carga     %7s s\n" "$TOK_LEIT" "$CARGA"
printf "    memória   %7s GB em uso | %s%% na CPU | RAM livre no início: %s MB\n" "$RAM_GB" "$CPU_PCT" "$RAM_DISP"
[ "$TOKENS" -lt "$MINIMO" ] && echo "    ${AMAR}${I_FALHA} aviso:${N} só $TOKENS tokens gerados; a taxa de velocidade é pouco confiável."
echo
printf "  %s%s Qualidade%s\n" "$(fg "$P_ROSA")" "$I_CODIGO" "$N"
for t in A B C D; do
  if [ "${RES[$t]}" = "OK" ]; then
    printf "    %s%s%s  %s  %sok%s\n" "$VERDE" "$I_OK" "$N" "$t. ${NOME[$t]}" "$VERDE" "$N"
  else
    printf "    %s%s%s  %s  %s%s%s\n" "$VERM" "$I_FALHA" "$N" "$t. ${NOME[$t]}" "$DIM" "${RES[$t]}" "$N"
  fi
done
echo
printf "  %s%s Nota%s    %s%s%s/100%s  %s  %s(qualidade %d/60 + velocidade %d/40)%s\n" \
  "$(fg "$P_AMAR")" "$I_NOTA" "$N" "$(fg "$COR_NOTA")" "$(neg)" "$NOTA" "$N" "$(barra_v "$NOTA" 100 20 "$COR_NOTA")" "$DIM" "$PONTOS_Q" "$PONTOS_V" "$N"
echo "  ${NEG}Serve para${N}  ${serve# }"
echo "${DIM}  Tempo do teste: ${TEMPO}s | respostas em: ${DIR#$RAIZ/}${N}"

# --- 4. CSV ---
CABECALHO="data,modelo,thinking,tok_s_geracao,tok_s_leitura,carga_s,ram_gb,cpu_pct,A,B,C,D,pontos_qualidade,pontos_velocidade,nota,tempo_s,ram_disp_mb,maquina"
[ -f "$CSV" ] || echo "$CABECALHO" > "$CSV"
# CSV criado antes da coluna ram_disp_mb: completa o cabeçalho (linhas antigas ficam com o campo vazio)
head -1 "$CSV" | grep -q ram_disp_mb || sed -i '1s/$/,ram_disp_mb/' "$CSV"
head -1 "$CSV" | grep -q maquina || sed -i '1s/$/,maquina/' "$CSV"
echo "$(date +%Y-%m-%d_%H:%M),$MODELO,$THINK_ROTULO,$TOK_GER,$TOK_LEIT,$CARGA,$RAM_GB,$CPU_PCT,${RES[A]%%:*},${RES[B]%%:*},${RES[C]%%:*},${RES[D]%%:*},$PONTOS_Q,$PONTOS_V,$NOTA,$TEMPO,$RAM_DISP,$(hostname)" >> "$CSV"
echo "${DIM}  ${I_PRONTO} salvo em ${CSV#$RAIZ/}. Use /rank, /nota ou /report para comparar.${N}"
continuar_no_terminal
