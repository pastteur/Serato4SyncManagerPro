use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use tauri::{AppHandle, Emitter, Manager, Window};
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Clone)]
pub struct DetectedPaths {
    pub mp3: String,
    pub serato: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct SyncFinishedPayload {
    pub success: bool,
    pub exit_code: Option<i32>,
    pub message: String,
}

fn dirs_home() -> Option<PathBuf> {
    std::env::var_os("HOME").map(PathBuf::from)
}

fn find_python_script(app: Option<&AppHandle>, script_name: &str) -> PathBuf {
    let mut possible = Vec::new();

    // 1. Bundle Resources inside .app (Contents/Resources/...)
    if let Ok(exe) = std::env::current_exe() {
        if let Some(macos_dir) = exe.parent() {
            if let Some(contents_dir) = macos_dir.parent() {
                possible.push(contents_dir.join("Resources").join(script_name));
                possible.push(contents_dir.join("Resources").join("_up_").join(script_name));
            }
        }
    }

    // 2. Tauri App resource directory
    if let Some(handle) = app {
        if let Ok(res_dir) = handle.path().resource_dir() {
            possible.push(res_dir.join(script_name));
            possible.push(res_dir.join("_up_").join(script_name));
        }
    }

    // 3. User Directories
    if let Some(home) = dirs_home() {
        possible.push(home.join("SeratoSync").join(script_name));
        possible.push(home.join("pasync").join(script_name));
    }

    // 4. Current working directory
    possible.push(PathBuf::from(script_name));

    possible
        .into_iter()
        .find(|p| p.exists())
        .unwrap_or_else(|| PathBuf::from(script_name))
}

mod commands {
    use super::*;

    #[tauri::command]
    pub fn get_detected_paths() -> DetectedPaths {
        // 1. Check external volumes (/Volumes/*)
        if let Ok(entries) = std::fs::read_dir("/Volumes") {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
                    if !name.starts_with('.') && !name.starts_with("Macintosh") {
                        let serato_path = path.join("Serato");
                        let serato_legada = path.join("_Serato_");
                        let mp3_path = path.join("Music").join("MP3");
                        let music_path = path.join("Music");

                        let final_serato = if serato_path.exists() {
                            serato_path
                        } else if serato_legada.exists() {
                            serato_legada
                        } else {
                            serato_path
                        };

                        let final_mp3 = if mp3_path.exists() {
                            mp3_path
                        } else {
                            music_path
                        };

                        return DetectedPaths {
                            mp3: final_mp3.to_string_lossy().to_string(),
                            serato: final_serato.to_string_lossy().to_string(),
                        };
                    }
                }
            }
        }

        // 2. Fallback to internal storage (Notebook)
        if let Some(home) = dirs_home() {
            let internal_mp3 = home.join("Music").join("MP3");
            let internal_serato = home.join("Library").join("Application Support").join("Serato");
            return DetectedPaths {
                mp3: internal_mp3.to_string_lossy().to_string(),
                serato: internal_serato.to_string_lossy().to_string(),
            };
        }

        DetectedPaths {
            mp3: String::new(),
            serato: String::new(),
        }
    }

    #[tauri::command]
    pub async fn open_in_finder(path: String) -> Result<(), String> {
        let expanded = if path.starts_with("~/") {
            if let Some(home) = dirs_home() {
                home.join(&path[2..])
            } else {
                PathBuf::from(&path)
            }
        } else {
            PathBuf::from(&path)
        };

        if !expanded.exists() {
            let _ = std::fs::create_dir_all(&expanded);
        }

        Command::new("open")
            .arg(&expanded)
            .spawn()
            .map_err(|e| e.to_string())?;

        Ok(())
    }

    #[tauri::command]
    pub async fn open_file_in_finder(path: String) -> Result<(), String> {
        let mut file_path = PathBuf::from(&path);

        // Se o caminho for relativo ou não existir diretamente, tenta resolver contra /Volumes/* ou Home
        if !file_path.exists() {
            if let Ok(entries) = std::fs::read_dir("/Volumes") {
                for entry in entries.flatten() {
                    let candidate = entry.path().join(&path);
                    if candidate.exists() {
                        file_path = candidate;
                        break;
                    }
                }
            }
        }

        if !file_path.exists() {
            if let Some(home) = dirs_home() {
                let candidate = home.join(&path);
                if candidate.exists() {
                    file_path = candidate;
                }
            }
        }

        if !file_path.exists() {
            return Err("Arquivo não encontrado no disco".into());
        }

        Command::new("open")
            .arg("-R")
            .arg(&file_path)
            .spawn()
            .map_err(|e| e.to_string())?;

        Ok(())
    }

    #[tauri::command]
    pub async fn move_to_trash(path: String) -> Result<(), String> {
        let mut file_path = PathBuf::from(&path);

        // Se o caminho for relativo ou não existir diretamente, tenta resolver contra /Volumes/* ou Home
        if !file_path.exists() {
            if let Ok(entries) = std::fs::read_dir("/Volumes") {
                for entry in entries.flatten() {
                    let candidate = entry.path().join(&path);
                    if candidate.exists() {
                        file_path = candidate;
                        break;
                    }
                }
            }
        }
        if !file_path.exists() {
            if let Some(home) = dirs_home() {
                let candidate = home.join(&path);
                if candidate.exists() {
                    file_path = candidate;
                }
            }
        }

        if !file_path.exists() {
            return Err("Arquivo não encontrado no disco".into());
        }

        let file_name = file_path.file_name().ok_or("Nome de arquivo inválido")?;

        // 1. Se estiver em um volume externo (/Volumes/<VolumeName>/...), tenta mover para a Lixeira do próprio volume
        let path_str = file_path.to_string_lossy();
        if path_str.starts_with("/Volumes/") {
            let parts: Vec<&str> = path_str.split('/').collect();
            if parts.len() >= 3 {
                let volume_root = format!("/Volumes/{}", parts[2]);
                let volume_trash = PathBuf::from(&volume_root).join(".Trashes").join("501");
                if volume_trash.exists() || std::fs::create_dir_all(&volume_trash).is_ok() {
                    let mut dest = volume_trash.join(file_name);
                    if dest.exists() {
                        let ts = std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH)
                            .unwrap_or_default()
                            .as_secs();
                        dest = volume_trash.join(format!("{}_{}", ts, file_name.to_string_lossy()));
                    }
                    if std::fs::rename(&file_path, &dest).is_ok() {
                        return Ok(());
                    }
                }
            }
        }

        // 2. Destino Lixeira do usuário (~/.Trash)
        let trash_dir = dirs_home().ok_or("Home directory não localizado")?.join(".Trash");
        if !trash_dir.exists() {
            let _ = std::fs::create_dir_all(&trash_dir);
        }

        let mut dest = trash_dir.join(file_name);
        if dest.exists() {
            let ts = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs();
            dest = trash_dir.join(format!("{}_{}", ts, file_name.to_string_lossy()));
        }

        // 3. Tenta rename; se falhar por Cross-device link (os error 18), copia e remove a origem!
        match std::fs::rename(&file_path, &dest) {
            Ok(_) => Ok(()),
            Err(_) => {
                // Cross-device copy fallback
                std::fs::copy(&file_path, &dest)
                    .map_err(|copy_err| format!("Falha ao copiar para a Lixeira: {}", copy_err))?;
                std::fs::remove_file(&file_path)
                    .map_err(|rm_err| format!("Falha ao remover arquivo de origem: {}", rm_err))?;
                Ok(())
            }
        }
    }

    #[tauri::command]
    pub async fn start_sync(
        app: AppHandle,
        window: Window,
        mp3_path: String,
        serato_path: String,
        export_csv: bool,
        dry_run: bool,
    ) -> Result<(), String> {
        let window_clone = window.clone();
        let script_path = find_python_script(Some(&app), "serato_macos_app.py");

        std::thread::spawn(move || {
            let _ = window_clone.emit("sync-log", format!("🐍 Motor Python: {}", script_path.display()));

            let mut cmd = Command::new("/usr/bin/python3");
            cmd.arg(&script_path);
            cmd.arg(&mp3_path);
            cmd.arg(&serato_path);
            cmd.arg("--json-summary");

            if !export_csv {
                cmd.arg("--no-csv");
            }

            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            if dry_run {
                cmd.arg("--dry-run");
            }

            let mut child = match cmd.spawn() {
                Ok(child) => child,
                Err(e) => {
                    let _ = window_clone.emit("sync-log", format!("❌ Erro ao disparar Python: {}", e));
                    let _ = window_clone.emit(
                        "sync-finished",
                        SyncFinishedPayload {
                            success: false,
                            exit_code: Some(1),
                            message: e.to_string(),
                        },
                    );
                    return;
                }
            };

            // Stream stdout in real time
            if let Some(stdout) = child.stdout.take() {
                let reader = BufReader::new(stdout);
                for line_res in reader.lines() {
                    if let Ok(line) = line_res {
                        let _ = window_clone.emit("sync-log", line);
                    }
                }
            }

            // Stream stderr in real time
            if let Some(stderr) = child.stderr.take() {
                let reader = BufReader::new(stderr);
                for line_res in reader.lines() {
                    if let Ok(line) = line_res {
                        let _ = window_clone.emit("sync-log", format!("⚠️ [STDERR] {}", line));
                    }
                }
            }

            let exit_status = child.wait().ok();
            let code = exit_status.and_then(|s| s.code()).unwrap_or(-1);
            let success = code == 0;

            let _ = window_clone.emit(
                "sync-finished",
                SyncFinishedPayload {
                    success,
                    exit_code: Some(code),
                    message: if success {
                        "Sincronização concluída com sucesso.".into()
                    } else {
                        format!("Processo finalizou com código {}", code)
                    },
                },
            );
        });

        Ok(())
    }

    #[tauri::command]
    pub async fn list_crates_tag_doctor(
        app: AppHandle,
        mp3_path: String,
    ) -> Result<String, String> {
        let script = find_python_script(Some(&app), "tag_doctor.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--list-crates");
        cmd.arg("--mp3");
        cmd.arg(&mp3_path);

        let output = cmd.output().map_err(|e| format!("Falha ao listar crates: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr).to_string();
            return Err(format!("Erro ao listar crates: {} {}", stdout, stderr));
        }
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn scan_tags_doctor(
        app: AppHandle,
        mp3_path: String,
        limit: Option<usize>,
        offset: Option<usize>,
        search: Option<String>,
        crate_raiz: Option<String>,
        subcrate: Option<String>,
        include_subcrates: Option<bool>,
    ) -> Result<String, String> {
        let script = find_python_script(Some(&app), "tag_doctor.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--scan-tags");
        cmd.arg("--mp3");
        cmd.arg(&mp3_path);
        if let Some(lim) = limit {
            cmd.arg("--limit");
            cmd.arg(lim.to_string());
        }
        if let Some(off) = offset {
            cmd.arg("--offset");
            cmd.arg(off.to_string());
        }
        if let Some(s) = search {
            if !s.is_empty() {
                cmd.arg("--search");
                cmd.arg(s);
            }
        }
        if let Some(cr) = crate_raiz {
            if !cr.is_empty() {
                cmd.arg("--crate-raiz");
                cmd.arg(cr);
            }
        }
        if let Some(sub) = subcrate {
            if !sub.is_empty() {
                cmd.arg("--subcrate");
                cmd.arg(sub);
            }
        }
        if let Some(false) = include_subcrates {
            cmd.arg("--no-subcrates");
        }

        let output = cmd.output().map_err(|e| format!("Falha ao executar scanner: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr).to_string();
            return Err(format!("Erro no scanner: {} {}", stdout, stderr));
        }
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn batch_apply_tags_doctor(
        app: AppHandle,
        window: Window,
        mp3_path: String,
        crate_raiz: Option<String>,
        subcrate: Option<String>,
        include_subcrates: Option<bool>,
        naming_mode: Option<String>,
        rename_files: Option<bool>,
        search: Option<String>,
    ) -> Result<(), String> {
        let script = find_python_script(Some(&app), "tag_doctor.py");
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let mut cmd = Command::new("/usr/bin/python3");
            cmd.arg(&script);
            cmd.arg("--batch-apply");
            cmd.arg("--mp3");
            cmd.arg(&mp3_path);

            if let Some(cr) = crate_raiz {
                if !cr.is_empty() {
                    cmd.arg("--crate-raiz");
                    cmd.arg(cr);
                }
            }
            if let Some(sub) = subcrate {
                if !sub.is_empty() {
                    cmd.arg("--subcrate");
                    cmd.arg(sub);
                }
            }
            if let Some(false) = include_subcrates {
                cmd.arg("--no-subcrates");
            }
            if let Some(mode) = naming_mode {
                cmd.arg("--naming-mode");
                cmd.arg(mode);
            }
            if let Some(true) = rename_files {
                cmd.arg("--rename-files");
            }
            if let Some(s) = search {
                if !s.is_empty() {
                    cmd.arg("--search");
                    cmd.arg(s);
                }
            }

            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            let mut child = match cmd.spawn() {
                Ok(c) => c,
                Err(e) => {
                    let _ = window_clone.emit("tag-doctor-batch-finished", serde_json::json!({
                        "sucesso": false,
                        "erro": e.to_string()
                    }));
                    return;
                }
            };

            if let Some(stdout) = child.stdout.take() {
                let reader = BufReader::new(stdout);
                for line_res in reader.lines() {
                    if let Ok(line) = line_res {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&line) {
                            let tipo = parsed.get("tipo").and_then(|t| t.as_str()).unwrap_or("");
                            if tipo == "progresso" {
                                let _ = window_clone.emit("tag-doctor-batch-progress", parsed);
                            } else if tipo == "fim" {
                                let _ = window_clone.emit("tag-doctor-batch-finished", parsed);
                            }
                        }
                    }
                }
            }

            let _ = child.wait();
        });

        Ok(())
    }

    #[tauri::command]
    pub async fn apply_tags_doctor(
        app: AppHandle,
        items_json: String,
        rename_files: Option<bool>,
    ) -> Result<String, String> {
        let script = find_python_script(Some(&app), "tag_doctor.py");

        let temp_dir = std::env::temp_dir();
        let temp_file = temp_dir.join(format!(
            "tag_doctor_{}.json",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis()
        ));
        std::fs::write(&temp_file, &items_json)
            .map_err(|e| format!("Falha ao criar arquivo temporário: {}", e))?;

        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--apply-tags");
        cmd.arg(&temp_file);
        if let Some(true) = rename_files {
            cmd.arg("--rename-files");
        }

        let output = cmd.output();
        let _ = std::fs::remove_file(&temp_file);

        let output = output.map_err(|e| format!("Falha ao executar aplicação de tags: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr).to_string();
            return Err(format!("Erro ao aplicar tags: {} {}", stdout, stderr));
        }
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn backup_serato_db(app: AppHandle) -> Result<String, String> {
        let script = find_python_script(Some(&app), "tag_doctor.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--backup-db");

        let output = cmd.output().map_err(|e| format!("Falha ao executar backup: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr).to_string();
            return Err(format!("Erro ao gerar backup: {} {}", stdout, stderr));
        }
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn list_serato_backups(app: AppHandle) -> Result<String, String> {
        let script = find_python_script(Some(&app), "tag_doctor.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--list-backups");

        let output = cmd.output().map_err(|e| format!("Falha ao listar backups: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn restore_serato_db(app: AppHandle, backup_path: String) -> Result<String, String> {
        let script = find_python_script(Some(&app), "tag_doctor.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--restore-db");
        cmd.arg(&backup_path);

        let output = cmd.output().map_err(|e| format!("Falha ao restaurar banco: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr).to_string();
            return Err(format!("Erro ao restaurar banco: {} {}", stdout, stderr));
        }
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn scan_sound_seals(
        app: AppHandle,
        mp3_path: String,
        batch: Option<usize>,
    ) -> Result<String, String> {
        let script = find_python_script(Some(&app), "sound_seal.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--scan");
        cmd.arg("--mp3");
        cmd.arg(&mp3_path);
        if let Some(b) = batch {
            cmd.arg("--batch");
            cmd.arg(b.to_string());
        }

        let output = cmd.output().map_err(|e| format!("Falha ao iniciar Sound Seal: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn get_sound_seal_status(app: AppHandle) -> Result<String, String> {
        let script = find_python_script(Some(&app), "sound_seal.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--status");

        let output = cmd.output().map_err(|e| format!("Falha ao consultar status do Sound Seal: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn get_sound_seal_duplicates(app: AppHandle) -> Result<String, String> {
        let script = find_python_script(Some(&app), "sound_seal.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--duplicates");

        let output = cmd.output().map_err(|e| format!("Falha ao consultar duplicatas do Sound Seal: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn scan_missing_relocate(
        app: AppHandle,
        mp3_path: String,
        serato_path: String,
    ) -> Result<String, String> {
        let script = find_python_script(Some(&app), "sound_seal.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--relocate");
        cmd.arg("--mp3");
        cmd.arg(&mp3_path);
        cmd.arg("--serato");
        cmd.arg(&serato_path);

        let output = cmd.output().map_err(|e| format!("Falha no scanner de faixas perdidas: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn relink_track(
        app: AppHandle,
        mp3_path: String,
        rel_path: String,
        source_path: String,
    ) -> Result<String, String> {
        let script = find_python_script(Some(&app), "sound_seal.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--relink");
        cmd.arg("--mp3");
        cmd.arg(&mp3_path);
        cmd.arg("--rel-path");
        cmd.arg(&rel_path);
        cmd.arg("--source-path");
        cmd.arg(&source_path);

        let output = cmd.output().map_err(|e| format!("Falha ao religar faixa: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        if !output.status.success() {
            return Err(stdout);
        }
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn batch_relink_tracks(
        app: AppHandle,
        window: Window,
        mp3_path: String,
        items_json: String,
    ) -> Result<(), String> {
        let script = find_python_script(Some(&app), "sound_seal.py");
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let mut cmd = Command::new("/usr/bin/python3");
            cmd.arg(&script);
            cmd.arg("--batch-relink");
            cmd.arg(&items_json);
            cmd.arg("--mp3");
            cmd.arg(&mp3_path);
            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            let mut child = match cmd.spawn() {
                Ok(c) => c,
                Err(e) => {
                    let _ = window_clone.emit("sound-seal-relink-finished", serde_json::json!({
                        "sucesso": false,
                        "erro": e.to_string()
                    }));
                    return;
                }
            };

            if let Some(stdout) = child.stdout.take() {
                let reader = BufReader::new(stdout);
                for line_res in reader.lines() {
                    if let Ok(line) = line_res {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&line) {
                            let tipo = parsed.get("tipo").and_then(|t| t.as_str()).unwrap_or("");
                            if tipo == "progresso" {
                                let _ = window_clone.emit("sound-seal-relink-progress", parsed);
                            } else if tipo == "fim" {
                                let _ = window_clone.emit("sound-seal-relink-finished", parsed);
                            }
                        }
                    }
                }
            }

            let _ = child.wait();
        });

        Ok(())
    }

    #[tauri::command]
    pub async fn match_tracks(
        app: AppHandle,
        input_type: String,
        input_data: String,
        mp3_path: String,
        serato_path: String,
        export_crate: Option<String>,
    ) -> Result<String, String> {
        let script = find_python_script(Some(&app), "track_matcher.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--mp3");
        cmd.arg(&mp3_path);
        cmd.arg("--serato");
        cmd.arg(&serato_path);

        if input_type == "spotify" {
            cmd.arg("--match-spotify");
            cmd.arg(&input_data);
        } else if input_type == "file" {
            cmd.arg("--match-file");
            cmd.arg(&input_data);
        } else {
            cmd.arg("--match-text");
            cmd.arg(&input_data);
        }

        if let Some(crate_name) = export_crate {
            if !crate_name.is_empty() {
                cmd.arg("--export-crate");
                cmd.arg(&crate_name);
            }
        }

        let output = cmd.output().map_err(|e| format!("Falha no Track Matcher: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn scan_audio_health(
        app: AppHandle,
        mp3_path: String,
        crate_raiz: Option<String>,
        subcrate: Option<String>,
        include_subcrates: Option<bool>,
        max_duration: Option<f64>,
        categoria: Option<String>,
        limit: Option<usize>,
        offset: Option<usize>,
    ) -> Result<String, String> {
        let script = find_python_script(Some(&app), "audio_health.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--scan");
        cmd.arg("--mp3");
        cmd.arg(&mp3_path);
        if let Some(cr) = crate_raiz {
            if !cr.is_empty() {
                cmd.arg("--crate-raiz");
                cmd.arg(cr);
            }
        }
        if let Some(sub) = subcrate {
            if !sub.is_empty() {
                cmd.arg("--subcrate");
                cmd.arg(sub);
            }
        }
        if let Some(false) = include_subcrates {
            cmd.arg("--no-subcrates");
        }
        if let Some(dur) = max_duration {
            cmd.arg("--max-duration");
            cmd.arg(dur.to_string());
        }
        if let Some(cat) = categoria {
            if !cat.is_empty() {
                cmd.arg("--categoria");
                cmd.arg(cat);
            }
        }
        if let Some(l) = limit {
            cmd.arg("--limit");
            cmd.arg(l.to_string());
        }
        if let Some(o) = offset {
            cmd.arg("--offset");
            cmd.arg(o.to_string());
        }

        let output = cmd.output().map_err(|e| format!("Falha na auditoria de áudio: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn repair_track_online(app: AppHandle, filepath: String) -> Result<String, String> {
        let script = find_python_script(Some(&app), "audio_health.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--repair-online");
        cmd.arg(&filepath);

        let output = cmd.output().map_err(|e| format!("Falha ao reparar áudio online: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn batch_repair_online(
        app: AppHandle,
        window: Window,
        filepaths_json: String,
    ) -> Result<(), String> {
        let script = find_python_script(Some(&app), "audio_health.py");
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let mut cmd = Command::new("/usr/bin/python3");
            cmd.arg(&script);
            cmd.arg("--batch-repair-online");
            cmd.arg(&filepaths_json);
            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            let mut child = match cmd.spawn() {
                Ok(c) => c,
                Err(e) => {
                    let _ = window_clone.emit("audio-health-batch-finished", serde_json::json!({
                        "sucesso": false,
                        "erro": e.to_string()
                    }));
                    return;
                }
            };

            if let Some(stdout) = child.stdout.take() {
                let reader = BufReader::new(stdout);
                for line_res in reader.lines() {
                    if let Ok(line) = line_res {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&line) {
                            let tipo = parsed.get("tipo").and_then(|t| t.as_str()).unwrap_or("");
                            if tipo == "progresso" {
                                let _ = window_clone.emit("audio-health-batch-progress", parsed);
                            } else if tipo == "fim" {
                                let _ = window_clone.emit("audio-health-batch-finished", parsed);
                            }
                        }
                    }
                }
            }

            let _ = child.wait();
        });

        Ok(())
    }

    #[tauri::command]
    pub async fn preview_auto_cues(app: AppHandle, filepath: String) -> Result<String, String> {
        let script = find_python_script(Some(&app), "auto_cue.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--preview");
        cmd.arg(&filepath);

        let output = cmd.output().map_err(|e| format!("Falha ao calcular Hot Cues: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn apply_auto_cues(app: AppHandle, filepath: String) -> Result<String, String> {
        let script = find_python_script(Some(&app), "auto_cue.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--apply");
        cmd.arg(&filepath);

        let output = cmd.output().map_err(|e| format!("Falha ao aplicar Hot Cues: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        if !output.status.success() {
            return Err(stdout);
        }
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn scan_crate_cues(
        app: AppHandle,
        mp3_path: String,
        crate_raiz: Option<String>,
        subcrate: Option<String>,
        include_subcrates: Option<bool>,
        limit: Option<usize>,
        offset: Option<usize>,
    ) -> Result<String, String> {
        let script = find_python_script(Some(&app), "auto_cue.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--scan-crate");
        cmd.arg("--mp3");
        cmd.arg(&mp3_path);
        if let Some(cr) = crate_raiz {
            if !cr.is_empty() {
                cmd.arg("--crate-raiz");
                cmd.arg(cr);
            }
        }
        if let Some(sub) = subcrate {
            if !sub.is_empty() {
                cmd.arg("--subcrate");
                cmd.arg(sub);
            }
        }
        if let Some(false) = include_subcrates {
            cmd.arg("--no-subcrates");
        }
        if let Some(l) = limit {
            cmd.arg("--limit");
            cmd.arg(l.to_string());
        }
        if let Some(o) = offset {
            cmd.arg("--offset");
            cmd.arg(o.to_string());
        }

        let output = cmd.output().map_err(|e| format!("Falha ao escanear cues na crate: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn batch_apply_crate_cues(
        app: AppHandle,
        window: Window,
        mp3_path: String,
        crate_raiz: Option<String>,
        subcrate: Option<String>,
        include_subcrates: Option<bool>,
        only_pending: Option<bool>,
    ) -> Result<(), String> {
        let script = find_python_script(Some(&app), "auto_cue.py");
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let mut cmd = Command::new("/usr/bin/python3");
            cmd.arg(&script);
            cmd.arg("--batch-crate");
            cmd.arg("--mp3");
            cmd.arg(&mp3_path);
            if let Some(cr) = crate_raiz {
                if !cr.is_empty() {
                    cmd.arg("--crate-raiz");
                    cmd.arg(cr);
                }
            }
            if let Some(sub) = subcrate {
                if !sub.is_empty() {
                    cmd.arg("--subcrate");
                    cmd.arg(sub);
                }
            }
            if let Some(false) = include_subcrates {
                cmd.arg("--no-subcrates");
            }
            if let Some(true) = only_pending {
                cmd.arg("--only-pending");
            }

            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            let mut child = match cmd.spawn() {
                Ok(c) => c,
                Err(e) => {
                    let _ = window_clone.emit("auto-cue-batch-finished", serde_json::json!({
                        "sucesso": false,
                        "erro": e.to_string()
                    }));
                    return;
                }
            };

            if let Some(stdout) = child.stdout.take() {
                let reader = BufReader::new(stdout);
                for line_res in reader.lines() {
                    if let Ok(line) = line_res {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&line) {
                            let tipo = parsed.get("tipo").and_then(|t| t.as_str()).unwrap_or("");
                            if tipo == "progresso" {
                                let _ = window_clone.emit("auto-cue-batch-progress", parsed);
                            } else if tipo == "fim" {
                                let _ = window_clone.emit("auto-cue-batch-finished", parsed);
                            }
                        }
                    }
                }
            }

            let _ = child.wait();
        });

        Ok(())
    }

    #[tauri::command]
    pub async fn apply_batch_auto_cues(app: AppHandle, filepaths_json: String) -> Result<String, String> {
        let script = find_python_script(Some(&app), "auto_cue.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--apply-batch");
        cmd.arg(&filepaths_json);

        let output = cmd.output().map_err(|e| format!("Falha ao aplicar lote de Hot Cues: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        if !output.status.success() {
            return Err(stdout);
        }
        Ok(stdout)
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            commands::get_detected_paths,
            commands::start_sync,
            commands::open_in_finder,
            commands::open_file_in_finder,
            commands::move_to_trash,
            commands::list_crates_tag_doctor,
            commands::scan_tags_doctor,
            commands::apply_tags_doctor,
            commands::batch_apply_tags_doctor,
            commands::backup_serato_db,
            commands::list_serato_backups,
            commands::restore_serato_db,
            commands::scan_sound_seals,
            commands::get_sound_seal_status,
            commands::get_sound_seal_duplicates,
            commands::scan_missing_relocate,
            commands::relink_track,
            commands::batch_relink_tracks,
            commands::match_tracks,
            commands::scan_audio_health,
            commands::repair_track_online,
            commands::batch_repair_online,
            commands::preview_auto_cues,
            commands::apply_auto_cues,
            commands::scan_crate_cues,
            commands::batch_apply_crate_cues,
            commands::apply_batch_auto_cues
        ])
        .run(tauri::generate_context!())
        .expect("erro ao inicializar aplicação tauri");
}
