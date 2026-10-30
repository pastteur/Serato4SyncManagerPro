#!/bin/bash
cd "$(dirname "$0")"
export PATH="$HOME/.bun/bin:$HOME/.cargo/bin:/opt/homebrew/bin:$PATH"
echo "🔄 Iniciando atualização automática do Serato4SyncPro..."
bun run build
bun run tauri build --bundles app
echo "🚚 Substituindo aplicativo na pasta oficial de Aplicativos do Mac..."
cp -R src-tauri/target/release/bundle/macos/Serato4SyncPro.app /Applications/
cp serato_macos_app.py /Applications/Serato4SyncPro.app/Contents/Resources/
echo "🎯 Pronto! Seu aplicativo desktop foi atualizado com sucesso e já está na sua gaveta de Apps."
read -p "Aperte Enter para fechar..."
