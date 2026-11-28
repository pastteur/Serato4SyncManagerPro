#!/bin/bash
cd "$(dirname "$0")"
export PATH="$HOME/.bun/bin:$HOME/.cargo/bin:/opt/homebrew/bin:$PATH"
echo "🔄 Iniciando atualização automática do Serato5SyncPro..."
bun run build
bun run tauri build --bundles app
echo "🚚 Substituindo aplicativo na pasta oficial de Aplicativos do Mac..."
rm -rf /Applications/Serato5SyncPro.app
cp -R src-tauri/target/release/bundle/macos/Serato5SyncPro.app /Applications/
echo "🎯 Pronto! Seu aplicativo desktop foi atualizado com sucesso e já está na sua gaveta de Apps."
read -p "Aperte Enter para fechar..."
