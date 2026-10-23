#!/usr/bin/env bash
# Instala a config global do opencode (~/.config/opencode/opencode.json) via symlink
# para este repositório. Idempotente: pode rodar quantas vezes quiser.
set -euo pipefail

DOTFILES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$DOTFILES_DIR/opencode/opencode.json"
TARGET_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
TARGET="$TARGET_DIR/opencode.json"

if [ ! -f "$SOURCE" ]; then
    echo "ERRO: $SOURCE não encontrado." >&2
    exit 1
fi

mkdir -p "$TARGET_DIR"

# Preserva config existente (não-symlink) antes de sobrescrever.
if [ -e "$TARGET" ] && [ ! -L "$TARGET" ]; then
    BACKUP="$TARGET.bak.$(date +%Y%m%d%H%M%S)"
    cp "$TARGET" "$BACKUP"
    echo "Backup da config atual: $BACKUP"
fi

ln -sfn "$SOURCE" "$TARGET"
echo "Symlink criado: $TARGET -> $SOURCE"
echo

# Verifica pré-requisitos (não instala nada sozinho).
missing=0
check() {
    if command -v "$1" >/dev/null 2>&1; then
        echo "ok:       $1"
    else
        echo "FALTANDO: $1"
        missing=1
    fi
}

check opencode
check ollama
check node
check trail

echo
if [ "$missing" -eq 1 ]; then
    cat <<'EOF'
Instale o que estiver faltando:
  opencode : curl -fsSL https://opencode.ai/install | bash
  ollama   : https://ollama.com/download  (depois: ollama pull qwen2.5-coder:7b)
  node     : https://nodejs.org  (necessário para o trail CLI)
  trail    : npm i -g @trailhq/trail-code
EOF
    echo
fi

cat <<'EOF'
Próximos passos manuais:
  1. Faça o login dos providers dentro do opencode (tokens ficam em
     ~/.config/opencode/*.json e NUNCA vão para este repo).
  2. Se for usar os modelos locais: ollama pull qwen2.5-coder:7b
  3. (Opcional) Copie as variáveis de opencode/env.example para o ~/.zshrc
     para trocar os modelos locais sem editar JSON.
  4. Reinicie o opencode — config não tem hot-reload.
EOF
