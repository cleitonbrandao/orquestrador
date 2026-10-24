#!/usr/bin/env bash
# Verificador de testes do /orquestrar: roda UM comando, uma vez, e dá o veredito por
# regra (código de saída + padrões de saída), sem LLM. Substitui o agente testador.
#
# Uso:   verificar.sh "<comando>"
# Saída: COMANDO / CODIGO / SAIDA (últimas 40 linhas) / RESULTADO
# Sai com 0 = passou, 1 = falhou, 2 = bloqueado.
set -uo pipefail

if [ $# -lt 1 ] || [ -z "$1" ]; then
  echo "Uso: verificar.sh \"<comando>\"" >&2
  exit 2
fi
COMANDO="$*"
LINHAS="${ORQ_LINHAS_SAIDA:-40}"
TIMEOUT_S="${ORQ_TIMEOUT_TESTE:-600}"

relatar() {
  # $1 = código, $2 = saída, $3 = resultado
  echo "COMANDO: $COMANDO"
  echo "CODIGO: $1"
  echo "SAIDA:"
  printf '%s\n' "$2" | tail -n "$LINHAS"
  echo "RESULTADO: $3"
}

# a mesma lista do testador: instalação, banco, containers e remoção nunca rodam aqui
if printf '%s' "$COMANDO" | grep -Eiq '(^|[;&|(]|&&|\|\|)[[:space:]]*(sudo[[:space:]]+)?(composer|npm|npx|pnpm|yarn|docker|rm|rmdir|del|remove-item)([[:space:]]|$)' \
  || printf '%s' "$COMANDO" | grep -Eiq 'artisan[[:space:]]+(migrate|db:)'; then
  relatar "-" "comando recusado pelo verificador (instalação, banco, docker ou remoção)" "bloqueado"
  exit 2
fi

if command -v timeout >/dev/null 2>&1; then
  SAIDA="$(timeout "$TIMEOUT_S" bash -c "$COMANDO" 2>&1)"
else
  SAIDA="$(bash -c "$COMANDO" 2>&1)"
fi
CODIGO=$?
[ "$CODIGO" -eq 124 ] && SAIDA="$SAIDA
(tempo esgotado: ${TIMEOUT_S}s)"

# falha de teste vence o código de saída; "passou" exige código 0 e testes executados
FALHA='FAILURES!|ERRORS!|(^|[^0-9])[1-9][0-9]* (failed|failing|errors?)([^a-z]|$)|^FAILED |^--- FAIL|test result: FAILED'
SUCESSO='OK \([0-9]+ tests?|(^|[^0-9])[1-9][0-9]* passed|^OK( |$)|^ok[[:space:]]+[^[:space:]]|test result: ok\.|^PASS '

if printf '%s\n' "$SAIDA" | grep -Eq "$FALHA"; then
  relatar "$CODIGO" "$SAIDA" "falhou"
  exit 1
fi
if [ "$CODIGO" -eq 0 ] && printf '%s\n' "$SAIDA" | grep -Eq "$SUCESSO"; then
  relatar "$CODIGO" "$SAIDA" "passou"
  exit 0
fi
relatar "$CODIGO" "$SAIDA" "bloqueado"
exit 2
