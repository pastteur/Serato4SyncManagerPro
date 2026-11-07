---
name: serato-sync-pro
description: >-
  Guia arquitetural, operacional e de engenharia reversa para o Serato 4 Sync Manager Pro.
  Use ao analisar, manter ou estender a sincronização de biblioteca do Serato DJ, manipulação
  binária de arquivos .crate, normalização de tags ID3v2.3, cálculo e auditoria de marcadores
  Serato Markers2 (Auto-Cue), matching com validação de hash/duração e IPC Tauri v2 + Python 3.12.
---

# Serato 4 Sync Manager Pro — Architectural & Operational Skill

Este documento é o guia definitivo de engenharia, arquitetura e processos do **Serato 4 Sync Manager Pro**, uma suíte profissional de gerenciamento, sincronização, normalização e automação de bibliotecas para DJs no ecossistema macOS e Serato DJ Pro.

---

## 1. Visão Geral da Arquitetura do Sistema

O sistema opera em uma arquitetura híbrida de alto desempenho:
1. **Front-end Desktop (GUI):** Tauri v2 + React 18 + TypeScript + Vite + TailwindCSS.
2. **IPC & Native Bridge:** Rust (`src-tauri/src/lib.rs`) gerenciando workers assíncronos em threads dedicadas, canais de streaming de eventos via Tauri Window Events e diálogo nativo com o macOS Finder.
3. **Core Engine de Áudio & Metadados:** Scripts especializados em Python 3.12 (`mutagen`, `hashlib`, `sqlite3`, `ffmpeg`, `struct`, `base64`).

```
┌────────────────────────────────────────────────────────┐
│               React 18 + Vite (Front-end)               │
│  [TrackMatcher] [AutoCue] [TagDoctor] [SoundSeal] ...   │
└───────────────────────────┬────────────────────────────┘
                            │ Tauri IPC (invoke / emit)
┌───────────────────────────▼────────────────────────────┐
│                  Rust Bridge (Tauri v2)                 │
│  • Localizador de Scripts (find_python_script)         │
│  • Spawner de Processos & Streaming de Stdout/Stderr   │
│  • Integração com Finder (open -R)                     │
└───────────────────────────┬────────────────────────────┘
                            │ Subprocessos Python 3.12
┌───────────────────────────▼────────────────────────────┐
│                 Python Execution Engine                │
│  • serato_macos_app.py   (Sincronização & .crate)      │
│  • auto_cue.py           (GEOB:Serato Markers2)        │
│  • track_matcher.py      (Upgrades, Hashes & Crate)    │
│  • tag_doctor.py         (Normalização ID3v2.3)        │
│  • sound_seal.py         (Integridade & Bitrot)        │
│  • audio_health.py       (Clipping, Sample Rate, etc.) │
└────────────────────────────────────────────────────────┘
```

---

## 2. Engenharia Reversa dos Formatos Proprietários do Serato

### 2.1. Estrutura Binária dos Arquivos `.crate`
Os arquivos de playlists virtuais do Serato residem em `_Serato_/Subcrates/` e utilizam uma codificação binária em blocos de 4 bytes baseada no formato de chunks estilo RIFF/AIFF em **Big-Endian**.

#### Cabeçalho Obrigatório:
```
vrsn\x00\x00\x00\x081.0/Serato ScratchLive Crate
```
- `vrsn`: Tag de versão (4 bytes ASCII).
- `\x00\x00\x00\x08`: Comprimento do texto de versão (8 bytes em uint32 Big-Endian).
- `1.0/Serato ScratchLive Crate`: Identificador oficial do protocolo.

#### Entradas de Faixa (`otrk` / `ptrk`):
Cada faixa dentro de uma Crate é representada por um bloco `otrk` (Outer Track Block) encapsulando um bloco `ptrk` (Path to Track):
```
[ 'otrk' (4 bytes) ] [ Tamanho do bloco otrk (uint32 BE) ]
  [ 'ptrk' (4 bytes) ] [ Comprimento da string UTF-16-BE (uint32 BE) ]
    [ Caminho Relativo ou Absoluto codificado em UTF-16-BE SEM BOM ]
```

> [!IMPORTANT]
> - O Serato exige **UTF-16-BE** (Big-Endian) sem Byte Order Mark (BOM).
> - Caracteres separadores de hierarquia em subcrates no nome do arquivo físico utilizam o token `%%` (ex: `Axé%%04.crate`).
> - O caminho codificado em `ptrk` deve ser relativo ao diretório base de áudios mapeado, normalizado sem caracteres invisíveis.

---

### 2.2. Marcadores de Hot Cue (`GEOB:Serato Markers2`)
O Serato DJ Pro armazena dados de Beatgrid, Loops e Hot Cues em tags ID3 de objeto encapsulado: `GEOB` com descrição `Serato Markers2`.

#### Decodificação e Estrutura:
1. O conteúdo da tag começa com um prefixo de 2 bytes (`\x01\x00`).
2. Segue-se uma string Base64 proprietária terminada por `\x00`.
   - **Anomalia de Padding:** O Serato frequentemente substitui `=` por `A` ou suprime os paddings finais. O parser em `auto_cue.py` normaliza o comprimento para módulo de 4 antes de invocar `base64.b64decode`.
3. O payload decodificado contém blocos sequenciais:
   - `[Nome da Tag em ASCII (ex: 'CUE')]\x00`
   - `[Tamanho dos Dados (4 bytes uint32 BE)]`
   - Dados do Cue (mínimo 12 bytes):
     - `\x00` (1 byte)
     - `Index` (uint8: 0 a 7, correspondente ao Pad 1 a 8)
     - `Posição em milissegundos` (uint32 BE)
     - `\x00` (1 byte)
     - `Cor RGB` (3 bytes binários, ex: `\xcc\x00\x00` para vermelho)
     - `\x00\x00` (2 bytes)
     - `Label / Rótulo` (string UTF-8 terminada em nulo, ex: `INTRO`, `DROP 1`)

> [!WARNING]
> O Serato DJ Pro requer **estritamente ID3v2.3**. Se uma tag for gravada como ID3v2.4 (`v2_version=4`), o Serato ignorará os marcadores nos pads físicos! Toda operação deve salvar com `audio.save(v2_version=3)`.

---

## 3. Módulos do Sistema e Regras de Negócio

### 3.1. Track Matcher & Upgrade Engine (`track_matcher.py`)
Módulo responsável por cruzar pastas de novidades (downloads/packs) ou playlists externas (Spotify/M3U) contra a biblioteca física do DJ.

#### Trava de Segurança: Remix vs Original
- O extrator `extract_version_descriptors(text)` cataloga tokens de versões:
  `remix`, `mix`, `extended`, `radio edit`, `club mix`, `dub`, `instrumental`, `acapella`, `ao vivo`, `live`, `acoustic`, `mashup`, `bootleg`, `vip mix`, e nomes de remixers (`remixer:alok`).
- Se a faixa nova for identificada como Remix e a da biblioteca for Original (ou se forem remixes de produtores distintos), a operação é categorizada como **`VERSAO_DIVERGENTE`** e a substituição no local é **estritamente bloqueada**.
- O sistema oferece a ação **"Integrar Remix na Crate"**, gravando o remix como faixa adicional ao lado da original.

#### Trava Física por Duração ($\Delta > 5$s)
- Discrepâncias de duração física do áudio superiores a 5.0 segundos são marcadas como **`DURACAO_INCOMPATIVEL`**, prevenindo substituições de faixas de rádio por versões estendidas.

#### Assinatura Criptográfica de Áudio Puro (`compute_audio_seal`)
- Calcula a hash **SHA-256** ignorando o header ID3v2 e o footer ID3v1/TAG.
- Permite verificar se duas faixas com tags ou metadados distintos contêm exatamente o mesmo fluxo de áudio PCM/MPEG.

#### Substituição Atômica com Quarentena (`replace_track_with_upgrade`)
1. Clona as tags `GEOB:Serato Markers2`, `GEOB:Serato BeatGrid`, `TBPM` e `TKEY` da faixa antiga para a nova.
2. Faz backup da faixa antiga para o diretório de quarentena: `~/.serato_quarentena_audio/`.
3. Sobrescreve a faixa no caminho original do disco, preservando a organização de pastas e os subcrates do Serato.

---

### 3.2. Auto-Cue & Anti-Sobreposição (`auto_cue.py`)
Módulo de cálculo inteligente de Hot Cues baseado em métrica musical de DJs.

#### Algoritmo dos 5 Hot Cues Padrão:
Calcula os pontos com base na duração total e no BPM identificado:
- **Cue 1 (#0 - Verde):** `INÍCIO` — Primeiro transiente audível (0.15s).
- **Cue 2 (#1 - Ciano):** `INTRO` — Início da primeira frase musical (8 compassos após início).
- **Cue 3 (#2 - Vermelho):** `DROP 1` — Ponto de clímax e entrada do beat principal (~25% da música).
- **Cue 4 (#3 - Amarelo):** `BREAK` — Queda melódica central (~60% da música).
- **Cue 5 (#4 - Laranja):** `OUTRO` — Ponto ideal para transição e mixagem final (últimos 32 tempos).

#### Auditoria Sem Truncamento (`audit_crate_cues_detailed`):
- Escaneia 100% dos arquivos da Crate sem limite arbitrário de paginação.
- Diferencia faixas com **Cues Manuais de DJ** (marcadores personalizados com labels próprios) de faixas com **Auto-Cues Padrão** e faixas **Pendentes Sem Cues**.
- Permite aplicar em lote via flag `--only-pending` e `--overwrite-existing=false`, garantindo proteção absoluta dos cues manuais do DJ.

---

### 3.3. Sound Seal & Integridade Forense (`sound_seal.py`)
- Mantém um banco SQLite local em `~/.serato_sound_seals.sqlite`.
- Armazena metadados físicos (`st_size`, `st_mtime`), hash de áudio puro SHA-256 e data da última auditoria.
- Erradica relatórios fantasmas (falsos positivos) evitando reescritas desnecessárias em disco se `mtime` e `size` permanecerem inalterados.

---

## 4. Comunicação IPC e Bridge Tauri (`src-tauri/src/lib.rs`)

### Resolução de Scripts Python no macOS Bundle
A função `find_python_script(app, script_name)` localiza os motores em Python na seguinte ordem de prioridade:
1. `Contents/Resources/<script>` (dentro de `Serato4SyncPro.app`).
2. `Contents/Resources/_up_/<script>` (estrutura de symlink do Tauri).
3. Diretório de recursos da API Tauri `handle.path().resource_dir()`.
4. Diretórios do usuário (`~/SeratoSync`, `~/pasync`).
5. Diretório de trabalho atual (`CWD`).

### Comandos Registrados no Tauri:
- `match_tracks` / `replace_upgrades_track_matcher` / `integrate_tracks_to_crate`
- `audit_crate_cues` / `scan_crate_cues` / `batch_apply_crate_cues` / `repair_crate_cues`
- `open_file_in_finder` (executa `open -R <caminho>` para revelar no Finder nativo).
- `scan_audio_health` / `preaudit_track_online` / `repair_track_online`.

---

## 5. Procedimentos de Build, Empacotamento e Teste

### 5.1. Compilação do Front-end
```bash
cd /Users/pastteur/SeratoSync
bun run build
```

### 5.2. Compilação e Empacotamento da Aplicação macOS
```bash
cd /Users/pastteur/SeratoSync
bun run tauri build --bundles app
```
*Saída gerada:* `src-tauri/target/release/bundle/macos/Serato4SyncPro.app`

### 5.3. Instalação e Deploy no Sistema
```bash
rm -rf /Applications/Serato4SyncPro.app
cp -R src-tauri/target/release/bundle/macos/Serato4SyncPro.app /Applications/
```

### 5.4. Teste Direto de Scripts de Backend
```bash
# Auditoria de cues em uma crate
/usr/bin/python3 auto_cue.py --audit-crate --mp3 "/Volumes/Pastteyr/Music/MP3" --crate-raiz "04"

# Match de pasta de novidades
/usr/bin/python3 track_matcher.py --match-folder "/Users/pastteur/Downloads/PackNovo" --mp3 "/Volumes/Pastteyr/Music/MP3"
```

---

## 6. Diretrizes Estritas para o Agente de IA

1. **Proteção Contra Perda de Dados:**
   - NUNCA execute sobrescrita destrutiva direta de faixas de áudio sem enviar a cópia original para `~/.serato_quarentena_audio/`.
   - NUNCA substitua faixas originais por remixes ou versões estendidas. Se houver divergência de versão ou $\Delta\text{duração} > 5.0$s, trate como nova faixa a ser integrada.
2. **Compatibilidade Binária do Serato:**
   - Todas as tags ID3 devem ser gravadas na versão **ID3v2.3**.
   - Os arquivos `.crate` devem manter `UTF-16-BE` sem BOM e cabeçalho `1.0/Serato ScratchLive Crate`.
3. **Comunicação com o Usuário:**
   - Todas as respostas, labels de interface, logs e alertas devem ser redigidos em **Português do Brasil**.
   - Forneça explicações transparentes das causas técnicas e ofereça opções seguras antes de operações irreversíveis.
