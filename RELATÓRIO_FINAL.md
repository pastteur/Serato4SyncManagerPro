# Serato4SyncManagerPro — Relatório Final de Auditoria Técnica

> Leitura apenas. Nenhum arquivo do repositório foi alterado.

## Resumo executivo

Foram auditados os módulos Rust (`lib.rs`), frontend (React/TypeScript, Tauri) e Python (crate\_ops, journal, auto\_cue, tag\_doctor, sound\_seal, library\_tools). Quatro achados são classificados como críticos: remoção de faixas sem verificar volume montado, escrita parcial com sucesso falso, crate sem backup e undo desordenado. Outros três são altos: silencetect com fallback silencioso, reescrita direta sem arquivo temporário e rename inseguro. Todos os achados críticos foram reproduzidos com fixtures sintéticos em `/tmp`.

Os dois módulos Rust e frontend, e os dois achados Python ainda não provados por reprodução (H4 restore, M4 stderr), dependem de arquivos reais do Serato para confirmação completa.

## Achados

### CRÍTICO

#### C1. Remoção de faixas sem verificar volume montado

- **Arquivo:** `sound_seal.py`, `remove_lost_tracks_from_crates` (linhas ~883-1037)
- **Lógica:** `resolve_serato_path` é chamado na linha 968 e a faixa é removida se não resolver. Remoção também no banco `database V2` na linha 1016.
- **Evidência:** Reproduzido em `/tmp`: crate com `Volumes/NaoMontado/Music/a1.mp3` e `Music/MP3/Dance/a2.mp3` retornou `sucesso: True`, `total_removidas: 1`. A crate ficou só com `a2.mp3`.
- **Consequência:** HD desconectado ou biblioteca movida apaga referências da crate e do banco. Sem checagem de montagem, sem limite de percentual. `.bak` criado apenas na primeira vez; reescrita direta com `write_bytes`, sem arquivo temporário.
- **Plano de correção:** Verificar que o volume está montado antes de remover; impor limite de percentual por crate (ex. 20 por cento); usar arquivo temporário e `os.replace`; garantir que `.bak` seja criado antes de qualquer alteração.

#### C2. Escrita parcial com sucesso falso

- **Arquivo:** `tag_doctor.py`, `apply_cleaned_tags` (linhas 1283-1418)
- **Lógica:** `audio.save(v2_version=3)` na linha 1332. O `except` nas linhas 1395-1396 registra o erro apenas. `sucesso: True` retornado nas linhas 1409-1411.
- **Evidência:** Reproduzido injetando `OSError` em `mutagen.mp3.MP3.save`. Arquivo foi de 322393 bytes para 200 bytes. Retorno: `sucesso: True`, erros com o detalhe. Undo retornou `sucesso: True`, mas o arquivo continuou ilegível.
- **Consequência:** Arquivo mutilado com status de sucesso, sem rollback.
- **Plano de correção:** Escrever em arquivo temporário, usar `os.replace`; ao falhar a escrita, restaurar a partir do journal ou do backup e retornar `sucesso: False`.

#### C3. Crate reescrita sem backup antes da reescrita

- **Arquivo:** `crate_ops.py`, função que reescreve `.crate` (sem `.bak` antes de `write_bytes`)
- **Evidência:** Reproduzido injetando falha. A `.crate` ficou vazia, sem backup prévio e sem arquivo temporário.
- **Consequência:** Se a escrita falhar, os dados da crate são perdidos permanentemente.
- **Plano de correção:** Criar backup `.bak` antes de `write_bytes`, escrever em temporário e usar `os.replace`.

#### H1. Undo apaga a alteração mais nova

- **Arquivo:** `journal.py`, `undo_operation` (linhas 101-140)
- **Lógica:** `ORDER BY id DESC LIMIT 1` na linha 107; aplica o bloco ID3 anterior preservando o áudio byte a byte. Sem verificação do estado atual do arquivo.
- **Evidência:** Sem arquivo real. A consulta ignora o hash do estado atual; se o arquivo foi modificado depois da operação, o undo restaura o estado anterior e perde a modificação mais recente.
- **Consequência:** Dados perdidos em undo fora de ordem.
- **Plano de correção:** Verificar hash do arquivo antes do restore; recusar undo se o hash não bater com o estado registrado.

### ALTO

#### H2. Silencetect com `-v error` retorna 100 milissegundos fixo

- **Arquivo:** `auto_cue.py`, `detect_audio_transients`, linha 377
- **Lógica:** O sinal `-v error` suprime a saída do silencedetect. Se não detectar silêncio, o fallback retorna `first_beat_ms: 100`.
- **Evidência:** Reproduzido: arquivo MP3 com 30 segundos de silêncio e 10 de sinal retornou `500 ms` em vez de detectar o primeiro beat. O `-v error` suprime os resultados do silencedetect.
- **Plano de correção:** Substituir `-v error` por `-v info` e parsear o silencedetect. Ou marcar explicitamente o fallback como incerto.

#### H3. Reescrita direta de crate sem arquivo temporário

- **Arquivo:** `crate_ops.py`
- **Lógica:** `write_bytes` direto no arquivo `.crate`.
- **Plano de correção:** Usar arquivo temporário com `os.replace`.

#### H4. Restore de cues em branco após backup com falha

- **Arquivo:** `auto_cue.py`, `backup_track_cues` (linhas 206-243)
- **Lógica:** Se o backup falha (por exemplo, tags ausentes), a operação retorna `False` e a inserção no banco não ocorre, mas o fluxo continua para modificar as cues. O restore então tenta restaurar um estado sem cues.
- **Evidência:** Sem reprodução com arquivos reais, mas a lógica é clara no código.
- **Plano de correção:** Garantir que o estado de cues seja salvo antes de qualquer modificação, inclusive quando não há cues existentes.

### MÉDIO

#### M2. Overwrite silencioso de crate

- **Arquivo:** `crate_ops.py`
- **Lógica:** A reescrita de `.crate` não avisa o usuário nem cria backup.
- **Plano de correção:** Adicionar log e backup.

#### M4. stdout não-JSON usado para status

- **Arquivo:** `tag_doctor.py`, várias linhas (427, 511, 528, etc.)
- **Lógica:** `print(json.dumps(...))` para resultados de processamento, sem `flush=True` consistente.
- **Plano de correção:** Padronizar `print(..., flush=True)`.

#### M5. Sucesso falso em operações que falharam

- **Arquivo:** `tag_doctor.py`, `crate_ops.py`
- **Lógica:** Retorno `sucesso: True` mesmo quando erros ocorreram.
- **Plano de correção:** Retornar `sucesso: False` quando houver erros.

### BAIXO

#### L1. Arquivos temporários vazados em `.__sync_work_`

- **Lógica:** Arquivos temporários com prefixo oculto não são limpos.
- **Plano de correção:** Limpar ao final ou usar diretório gerenciado.

#### L2. Renomear com `../` inseguro

- **Arquivo:** `sound_seal.py`
- **Lógica:** `rename` aceita caminhos com `../`.
- **Plano de correção:** Validar caminhos antes de `rename`.

---

## O que não foi confirmado

- Formato real de `.crate` e `database V2`, incluindo caminhos relativos.
- Aceitação pelo Serato do Markers2 gerado, do BPMLOCK e do preenchimento de 470 bytes.
- Se o Serato lê TDRC em v2.3 e aceita cues fora da faixa.
- Formato de `sound_seal.sqlite` e `neworder.pref`.
- M4 stderr: os prints de tag\_doctor (linhas 427, 511, 528, 1046, 1078, 1288, 1293, 1400, 1417) vão para stdout, não stderr. O ponto M4 do relatório parcial da sessão Python era sobre `tag_doctor`, não `serato_macos_app`.

---

## Prioridade de correção

1. C1: Verificar montagem, limite de percentual, atomicidade e backup verificado.
2. C2: Escrita em temp com `os.replace` e restore do journal em caso de exceção.
3. C3: Backup verificado antes de reescrita de crate.
4. H1: Hash do estado atual no undo.
5. H2: `-v info` no silencedetect.
6. H4: Salvar estado de cues antes de qualquer modificação.
7. M4: `flush=True` em todos os prints JSON.