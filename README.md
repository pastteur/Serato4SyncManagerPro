# Serato 4 Sync Manager Pro 🎧🔥

> **O ecossistema definitivo para organização, sincronização e proteção de bibliotecas para DJs profissionais no Serato DJ Pro 4.**

![macOS Tahoe / Apple Silicon & Intel](https://img.shields.io/badge/Platform-macOS%20(Silicon%20%26%20Intel)-00e5ff?style=for-the-badge&logo=apple)
![Tauri v2](https://img.shields.io/badge/Tauri-v2.0-ffd700?style=for-the-badge&logo=tauri)
![React 18](https://img.shields.io/badge/React-18-61dafb?style=for-the-badge&logo=react)
![Rust](https://img.shields.io/badge/Rust-High%20Performance-dea584?style=for-the-badge&logo=rust)
![Python 3](https://img.shields.io/badge/Python-3.9+-3776ab?style=for-the-badge&logo=python)

---

## 🚀 Principais Recursos

### 1. 📂 Sincronização Inteligente de Crates (Zero Corrupção Serato 4)
* **Arquitetura 100% Segura:** Utiliza exclusivamente o padrão binário oficial de `Subcrates/` com hierarquia `%%` e ordenação decrescente de novidades (`neworder.pref`).
* **Proteção de Dados:** **Nunca** toca nem corrompe o banco central `master.sqlite`.
* **Trava Anti-Falso-Positivo:** Cache rápido que evita regravações desnecessárias.

### 2. 🏷️ Tag Doctor (Higienizador de Tags ID3 & Nomes)
* **Preservação Sagrada de Versões:** Preserva 100% de detalhes de remixes, versões e feats (`(Bahia Mix)`, `(Rock Remix)`, `(feat Ciclano)`, etc.).
* **Limpeza de Ruídos:** Remove propagandas de download (`[DJ Pool]`, `_-_`, sites, sufixos residuais ` . ..` e caudas de BPM/Key ` . 80 . Fm`).
* **Detecção Automática de Crate Raiz:** Identifica a pasta mãe (`Axé`, `Funk`, `Sertanejo`, `EMusic`, etc.) e permite incorporar ao nome do arquivo e à tag `TCON` (Gênero).
* **3 Modelos de Nomenclatura:**
  1. 🌟 *Completo:* `{Artista} - {Título} - {Crate} - {Álbum}`
  2. 📂 *Com Crate:* `{Artista} - {Título} - {Crate}`
  3. 🎵 *DJ Clássico:* `{Artista} - {Título}`
* **Preservação Total do Serato:** Protege os blocos `GEOB:Serato Markers2`, `TBPM`, `TKEY` e `TXXX:SERATO_PLAYCOUNT`.

### 3. 🧬 Sound Seal (Assinatura Acústica SHA-256)
* **Impressão Digital do Áudio:** Gera um hash SHA-256 do fluxo sonoro puro (ignorando tags ID3 que mudam com o tempo).
* **Detecção de Cópias Renomeadas:** Encontra faixas duplicadas mesmo se o nome, a pasta e as tags forem totalmente diferentes.
* **Banco Local SQLite WAL:** Processamento incremental resiliente que continua sozinho mesmo após reiniciar o computador.

### 4. 🔍 Relocate Inteligente com Score de Confiança
* **Localizador de Faixas Perdidas:** Rastreia faixas que ficaram com ponto de interrogação alaranjado no Serato.
* **Busca na Lixeira (.Trashes):** Identifica se o arquivo foi movido para a Lixeira do HD externo e permite restaurar com 1 clique.
* **Scores de Confiança:** Indica 100%, 87% ou 77% de similaridade cruzando Sound Seal, duração em milissegundos, BPM e Tom.

### 5. 🎵 Track Matcher (Spotify / YouTube Music / Texto / M3U)
* **Importação Inteligente:** Cole uma playlist do Spotify ou lista de músicas em texto.
* **Cruzamento com 31.355+ Faixas:** Localiza instantaneamente as músicas que você já possui no HD e gera a Crate pronta no Serato.
* **Faixas Faltantes:** Painel de faltantes com opção de cópia e integração para download de áudios em alta fidelidade.

### 6. 🩺 Audio Health Doctor (Auditoria de Integridade)
* **Detecção de Downloads Interrompidos:** Alerta faixas cortadas no meio (ex: 1:30 min) com incompatibilidade de bytes vs duração.
* **Filtro de Duração:** Encontra vinhetas, toques e previews menores que 60s acidentalmente misturados no acervo.
* **Qualidade de Áudio & Fake 320 kbps:** Aponta arquivos com menos de 192 kbps e analisa o espectro de frequências sonoras (corte brusco em 16kHz/17.5kHz) para desmascarar áudios de baixa fidelidade re-encodados falsamente como 320 kbps.

### 7. 🎯 Auto-Cue Generator com Análise de Transientes
* **Alinhamento Acústico Real:** Análise espectral de energia e detecção de transientes (*onset/punch*) via FFmpeg para cravar o Cue 1 exatamente no primeiro impacto sonoro da música, alinhando os 16/32 compassos em fase.
* **Estrutura Métrica de DJ:** Calcula automaticamente os 5 pontos fundamentais de mixagem:
  * 🔴 **Cue 1:** Intro / Primeiro Kick (alinhado ao transiente real)
  * 🔵 **Cue 2:** Drop 1 (16/32 compassos em fase)
  * 🟡 **Cue 3:** Breakdown / Ponte
  * 🟢 **Cue 4:** Drop 2 (Clímax)
  * 🟠 **Cue 5:** Outro / Ponto de Mix-out
* **Proteção de Cues Manuais:** Nunca sobrescreve pontos de Cue personalizados já marcados pelo DJ.
* **Gravação Nativa:** Grava diretamente na tag `GEOB:Serato Markers2`, acendendo os pads coloridos no controlador.

### 8. 🔀 Varredura Lateral Multi-Pastas (Cross-Folders)
* **Cruzamento de Múltiplos Discos:** Compare lateralmente arquivos espalhados em pastas distintas, discos internos, SSDs externos e pen-drives.
* **Assinatura Acústica Sound Seal (SHA-256 Puro):** Isola os frames de áudio brutos (ignora tags ID3), identificando arquivos 100% idênticos mesmo com nomes e tags diferentes.
* **Keeper Inteligente:** Heurística automática que protege a faixa de maior bitrate, indexada no Serato e mais antiga.

### 9. 🔒 Trava de Segurança de Processo (Serato Lock)
* **Proteção Ativa:** Monitora a execução do `Serato DJ Pro`. Se o software estiver aberto, qualquer gravação física em crates ou tags é bloqueada preventivamente, impedindo que o cache da memória RAM do Serato sobrescreva ou reverta suas alterações.

### 10. 🛡️ Gerenciador de Backups & Journal de Desfazer
* **Desfazer Unificado (Undo Journal):** Histórico de operações de tags ID3 para restauração imediata do estado anterior.
* **Snapshots Automáticos:** Salva cópias versionadas e datadas da biblioteca do Serato.
* **Restauração em 1 Clique:** Retorne ao estado de qualquer data anterior sem complicações.

---

## 🛠️ Tecnologias Utilizadas

* **Desktop Framework:** [Tauri v2](https://v2.tauri.app/) (Rust + WebKit)
* **Frontend:** React 18, TypeScript, Tailwind CSS, Lucide Icons, Vite, Bun
* **Audio Engine:** Python 3, Mutagen, SQLite3 WAL
* **Compatibilidade:** macOS Sonoma & macOS Tahoe (Apple Silicon M1/M2/M3/M4 & Intel)

---

## 💻 Como Rodar e Desenvolver

### Pré-requisitos
* [Bun](https://bun.sh/) instalado
* [Rust](https://rustup.rs/) e Cargo instalados
* Python 3 instalado no macOS (a biblioteca `mutagen` já é distribuída e embutida no projeto em `vendor/mutagen`)

### Instalação e Execução
```bash
# Instalar dependências
bun install

# Rodar em modo de desenvolvimento com Hot Reload
bun run tauri dev

# Compilar release nativo (.app do macOS)
bun run tauri build --bundles app
```

---

## 📄 Licença
Distribuído sob a licença MIT. Desenvolvido para máxima fidelidade e segurança de DJs profissionais.
