#!/bin/bash
cd "$(dirname "$0")"
export PATH="$HOME/.bun/bin:$HOME/.cargo/bin:/opt/homebrew/bin:$PATH"
echo "🌐 Inicializando o ecossistema híbrido (Site Dev + Aplicativo Local)..."
echo "💡 O seu site de desenvolvimento estará online em: http://localhost:5173"
echo "🚀 Abrindo a janela nativa do Tauri conectada ao motor Python..."
bun run tauri dev
