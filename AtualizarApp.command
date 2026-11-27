#!/bin/bash
cd "$(dirname "$0")"
export PATH="$HOME/.bun/bin:$HOME/.cargo/bin:/opt/homebrew/bin:$PATH"
echo "🔄 Iniciando atualização automática do Serato4SyncPro..."
bun run build
bun run tauri build --bundles app
echo "🚚 Substituindo aplicativo na pasta oficial de Aplicativos do Mac..."
rm -rf /Applications/Serato4SyncPro.app
cp -R src-tauri/target/release/bundle/macos/Serato4SyncPro.app /Applications/
echo "🎯 Pronto! Seu aplicativo desktop foi atualizado com sucesso e já está na sua gaveta de Apps."
read -p "Aperte Enter para fechar..."
