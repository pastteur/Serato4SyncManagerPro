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

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct SystemTelemetry {
    pub cpu_percent: f32,
    pub ram_used_gb: f32,
    pub ram_total_gb: f32,
    pub ram_percent: f32,
    pub disk_name: String,
    pub disk_free_gb: f32,
    pub disk_total_gb: f32,
    pub disk_percent: f32,
    pub serato_running: bool,
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

fn find_python_binary() -> Result<PathBuf, String> {
    // 1. Variável de ambiente explícita
    if let Ok(py_env) = std::env::var("SERATO_PYTHON").or_else(|_| std::env::var("PYTHON_PATH")) {
        let p = PathBuf::from(&py_env);
        if p.exists() && p.is_file() {
            return Ok(p);
        }
    }

    // 2. Ambiente virtual ativo (VIRTUAL_ENV)
    if let Ok(venv) = std::env::var("VIRTUAL_ENV") {
        let venv_py = PathBuf::from(venv).join("bin").join("python3");
        if venv_py.exists() && venv_py.is_file() {
            return Ok(venv_py);
        }
    }

    // 3. Python empacotado no bundle .app se existir
    if let Ok(exe) = std::env::current_exe() {
        if let Some(macos_dir) = exe.parent() {
            if let Some(contents_dir) = macos_dir.parent() {
                let bundled_py = contents_dir.join("Resources").join("python").join("bin").join("python3");
                if bundled_py.exists() && bundled_py.is_file() {
                    return Ok(bundled_py);
                }
            }
        }
    }

    // 4. Locais padrão no macOS
    let candidates = [
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
    ];

    for candidate in &candidates {
        let p = PathBuf::from(candidate);
        if p.exists() && p.is_file() {
            return Ok(p);
        }
    }

    // 5. Fallback via PATH
    if let Ok(output) = Command::new("which").arg("python3").output() {
        if output.status.success() {
            let path_str = String::from_utf8_lossy(&output.stdout).trim().to_string();
            if !path_str.is_empty() {
                let p = PathBuf::from(path_str);
                if p.exists() && p.is_file() {
                    return Ok(p);
                }
            }
        }
    }

    Err("Nenhum interpretador Python 3 funcional foi localizado no sistema (verificado Homebrew, /usr/local/bin, /usr/bin).".into())
}

fn find_canonical_python_script(app: Option<&AppHandle>, script_name: &str) -> Result<PathBuf, String> {
    let mut possible = Vec::new();

    // 1. Recursos oficiais empacotados dentro do bundle macOS (.app/Contents/Resources/...)
    if let Ok(exe) = std::env::current_exe() {
        if let Some(macos_dir) = exe.parent() {
            if let Some(contents_dir) = macos_dir.parent() {
                let res = contents_dir.join("Resources");
                if res.is_dir() {
                    possible.push(res.join(script_name));
                    possible.push(res.join("_up_").join(script_name));
                }
            }
        }
    }

    // 2. Diretório canônico de recursos da API Tauri
    if let Some(handle) = app {
        if let Ok(res_dir) = handle.path().resource_dir() {
            possible.push(res_dir.join(script_name));
            possible.push(res_dir.join("_up_").join(script_name));
        }
    }

    // Em modo de desenvolvimento local exclusivo (cargo run / tauri dev), permite resolução da raiz do workspace
    #[cfg(debug_assertions)]
    {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        if let Some(parent) = manifest_dir.parent() {
            possible.push(parent.join(script_name));
        }
        possible.push(PathBuf::from(script_name));
    }

    // NOTA DE SEGURANÇA DA AUDITORIA:
    // Foram removidas buscas em ~/SeratoSync, ~/pasync e diretório de trabalho arbitrário.
    // O aplicativo em produção executa estritamente os scripts distribuídos em seu pacote.

    for p in possible {
        if p.exists() && p.is_file() {
            return Ok(p);
        }
    }

    Err(format!(
        "Script Python canônico '{}' não foi encontrado nos recursos empacotados do aplicativo.",
        script_name
    ))
}

fn find_python_script(app: Option<&AppHandle>, script_name: &str) -> PathBuf {
    find_canonical_python_script(app, script_name).unwrap_or_else(|_| PathBuf::from(script_name))
}

pub fn is_serato_running() -> bool {
    Command::new("pgrep")
        .arg("-x")
        .arg("Serato DJ Pro")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

extern "C" {
    fn mach_port_deallocate(task: libc::mach_port_t, name: libc::mach_port_t) -> libc::c_int;
}

mod commands {
    use super::*;

    #[tauri::command]
    #[allow(deprecated)]
    pub fn get_system_telemetry() -> SystemTelemetry {
        // 1. CPU Usage
        let mut cpu_pct: f32 = 0.0;
        unsafe {
            #[repr(C)]
            struct host_cpu_load_info {
                cpu_ticks: [u32; 4],
            }
            let mut count = (std::mem::size_of::<host_cpu_load_info>() / std::mem::size_of::<libc::integer_t>()) as libc::mach_msg_type_number_t;
            let mut load_info: host_cpu_load_info = std::mem::zeroed();
            let host_port = libc::mach_host_self();
            let kr = libc::host_statistics(
                host_port,
                libc::HOST_CPU_LOAD_INFO,
                &mut load_info as *mut _ as *mut libc::integer_t,
                &mut count,
            );
            mach_port_deallocate(libc::mach_task_self(), host_port);

            if kr == 0 {
                let user = load_info.cpu_ticks[0] as u64;
                let system = load_info.cpu_ticks[1] as u64;
                let idle = load_info.cpu_ticks[2] as u64;
                let nice = load_info.cpu_ticks[3] as u64;

                let total_ticks = user + system + idle + nice;
                let active_ticks = user + system + nice;

                static PREV_CPU: std::sync::Mutex<(u64, u64)> = std::sync::Mutex::new((0, 0));
                if let Ok(mut prev) = PREV_CPU.lock() {
                    if prev.0 > 0 && total_ticks > prev.0 {
                        let d_total = total_ticks - prev.0;
                        let d_active = active_ticks.saturating_sub(prev.1);
                        cpu_pct = ((d_active as f64 / d_total as f64) * 100.0) as f32;
                    }
                    *prev = (total_ticks, active_ticks);
                }
            }
        }

        // 2. RAM Usage
        let mut total_ram_bytes: u64 = 8 * 1024 * 1024 * 1024;
        let mut size = std::mem::size_of::<u64>();
        unsafe {
            let name = std::ffi::CString::new("hw.memsize").unwrap();
            let _ = libc::sysctlbyname(
                name.as_ptr(),
                &mut total_ram_bytes as *mut _ as *mut libc::c_void,
                &mut size,
                std::ptr::null_mut(),
                0,
            );
        }
        let ram_total_gb = (total_ram_bytes as f64 / 1_073_741_824.0) as f32;

        let mut used_ram_gb = 0.0;
        unsafe {
            #[repr(C)]
            struct vm_statistics64 {
                free_count: u32,
                active_count: u32,
                inactive_count: u32,
                wire_count: u32,
                zero_fill_count: u64,
                reactivations: u64,
                pageins: u64,
                pageouts: u64,
                faults: u64,
                cow_faults: u64,
                lookups: u64,
                hits: u64,
                purges: u64,
                purgeable_count: u32,
                speculative_count: u32,
                decompressions: u64,
                compressions: u64,
                swapins: u64,
                swapouts: u64,
                compressor_page_count: u32,
                throttled_count: u32,
                external_page_count: u32,
                internal_page_count: u32,
                total_uncompressed_pages_in_compressor: u64,
            }
            let mut count = (std::mem::size_of::<vm_statistics64>() / std::mem::size_of::<libc::integer_t>()) as libc::mach_msg_type_number_t;
            let mut vm_stat: vm_statistics64 = std::mem::zeroed();
            let host_port = libc::mach_host_self();
            let kr = libc::host_statistics64(
                host_port,
                libc::HOST_VM_INFO64,
                &mut vm_stat as *mut _ as *mut libc::integer_t,
                &mut count,
            );
            mach_port_deallocate(libc::mach_task_self(), host_port);

            if kr == 0 {
                let page_size = libc::sysconf(libc::_SC_PAGESIZE) as u64;
                let active = (vm_stat.active_count + vm_stat.wire_count + vm_stat.compressor_page_count) as u64;
                let used_bytes = active * page_size;
                used_ram_gb = (used_bytes as f64 / 1_073_741_824.0) as f32;
            }
        }
        let ram_percent = if ram_total_gb > 0.0 {
            ((used_ram_gb / ram_total_gb) * 100.0).min(100.0)
        } else {
            0.0
        };

        // 3. Disk Usage
        let (disk_name, target_path) = if std::path::Path::new("/Volumes/Pastteyr").exists() {
            ("Pastteyr".to_string(), "/Volumes/Pastteyr")
        } else {
            ("Macintosh HD".to_string(), "/")
        };

        let mut disk_free_gb = 0.0;
        let mut disk_total_gb = 0.0;
        let mut disk_percent = 0.0;

        if let Ok(c_path) = std::ffi::CString::new(target_path) {
            let mut stat: std::mem::MaybeUninit<libc::statvfs> = std::mem::MaybeUninit::uninit();
            if unsafe { libc::statvfs(c_path.as_ptr(), stat.as_mut_ptr()) } == 0 {
                let stat = unsafe { stat.assume_init() };
                let block_size = stat.f_frsize as u64;
                let total_bytes = stat.f_blocks as u64 * block_size;
                let free_bytes = stat.f_bavail as u64 * block_size;
                let used_bytes = total_bytes.saturating_sub(free_bytes);

                disk_total_gb = (total_bytes as f64 / 1_073_741_824.0) as f32;
                disk_free_gb = (free_bytes as f64 / 1_073_741_824.0) as f32;
                if total_bytes > 0 {
                    disk_percent = ((used_bytes as f64 / total_bytes as f64) * 100.0) as f32;
                }
            }
        }

        // 4. Serato DJ Pro Running
        let serato_running = is_serato_running();

        SystemTelemetry {
            cpu_percent: (cpu_pct * 10.0).round() / 10.0,
            ram_used_gb: (used_ram_gb * 10.0).round() / 10.0,
            ram_total_gb: (ram_total_gb * 10.0).round() / 10.0,
            ram_percent: ram_percent.round(),
            disk_name,
            disk_free_gb: (disk_free_gb * 10.0).round() / 10.0,
            disk_total_gb: (disk_total_gb * 10.0).round() / 10.0,
            disk_percent: disk_percent.round(),
            serato_running,
        }
    }

    #[tauri::command]
    pub fn get_detected_paths() -> DetectedPaths {
        // Prioridade 1: Volume externo que possua TANTO pasta de músicas quanto pasta Serato na mesma unidade
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

                        let opt_serato = if serato_path.exists() && serato_path.is_dir() {
                            Some(serato_path)
                        } else if serato_legada.exists() && serato_legada.is_dir() {
                            Some(serato_legada)
                        } else {
                            None
                        };

                        let opt_mp3 = if mp3_path.exists() && mp3_path.is_dir() {
                            Some(mp3_path)
                        } else if music_path.exists() && music_path.is_dir() {
                            Some(music_path)
                        } else {
                            None
                        };

                        if let (Some(s), Some(m)) = (opt_serato, opt_mp3) {
                            return DetectedPaths {
                                mp3: m.to_string_lossy().to_string(),
                                serato: s.to_string_lossy().to_string(),
                            };
                        }
                    }
                }
            }
        }

        // Prioridade 2: Armazenamento interno (Macintosh HD / Notebook) na mesma unidade
        if let Some(home) = dirs_home() {
            let internal_mp3_sub = home.join("Music").join("MP3");
            let internal_mp3 = home.join("Music");
            let internal_serato_appsup = home.join("Library").join("Application Support").join("Serato");
            let internal_serato_music = home.join("Music").join("_Serato_");

            let opt_serato = if internal_serato_appsup.exists() && internal_serato_appsup.is_dir() {
                Some(internal_serato_appsup)
            } else if internal_serato_music.exists() && internal_serato_music.is_dir() {
                Some(internal_serato_music)
            } else {
                None
            };

            let opt_mp3 = if internal_mp3_sub.exists() && internal_mp3_sub.is_dir() {
                Some(internal_mp3_sub)
            } else if internal_mp3.exists() && internal_mp3.is_dir() {
                Some(internal_mp3)
            } else {
                None
            };

            if let (Some(s), Some(m)) = (&opt_serato, &opt_mp3) {
                return DetectedPaths {
                    mp3: m.to_string_lossy().to_string(),
                    serato: s.to_string_lossy().to_string(),
                };
            }
        }

        // Se nenhum volume tiver ambos, procura individualmente mas NUNCA inventa caminhos inexistentes
        let mut final_mp3 = String::new();
        let mut final_serato = String::new();

        if let Ok(entries) = std::fs::read_dir("/Volumes") {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
                    if !name.starts_with('.') && !name.starts_with("Macintosh") {
                        if final_mp3.is_empty() {
                            let mp3_path = path.join("Music").join("MP3");
                            let music_path = path.join("Music");
                            if mp3_path.exists() && mp3_path.is_dir() {
                                final_mp3 = mp3_path.to_string_lossy().to_string();
                            } else if music_path.exists() && music_path.is_dir() {
                                final_mp3 = music_path.to_string_lossy().to_string();
                            }
                        }
                        if final_serato.is_empty() {
                            let serato_path = path.join("Serato");
                            let serato_legada = path.join("_Serato_");
                            if serato_path.exists() && serato_path.is_dir() {
                                final_serato = serato_path.to_string_lossy().to_string();
                            } else if serato_legada.exists() && serato_legada.is_dir() {
                                final_serato = serato_legada.to_string_lossy().to_string();
                            }
                        }
                    }
                }
            }
        }

        DetectedPaths {
            mp3: final_mp3,
            serato: final_serato,
        }
    }

    #[tauri::command]
    pub fn validate_path(path: String) -> bool {
        let trimmed = path.trim();
        if trimmed.is_empty() {
            return false;
        }
        let p = PathBuf::from(trimmed);
        p.exists() && p.is_dir()
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

        // Se ainda não encontrar, tenta busca tolerante a Unicode NFD/NFC no diretório pai
        if !file_path.exists() {
            if let Some(parent) = file_path.parent() {
                if parent.exists() {
                    if let Some(target_name) = file_path.file_name() {
                        let target_str = target_name.to_string_lossy().to_lowercase();
                        if let Ok(entries) = std::fs::read_dir(parent) {
                            for entry in entries.flatten() {
                                if entry.file_name().to_string_lossy().to_lowercase() == target_str {
                                    file_path = entry.path();
                                    break;
                                }
                            }
                        }
                    }
                }
            }
        }

        // Se o arquivo for um link simbólico quebrado (o link existe mas o alvo foi excluído):
        if file_path.is_symlink() && !file_path.exists() {
            let _ = std::fs::remove_file(&file_path);
            return Ok(());
        }

        // Se o arquivo realmente não existe mais no disco, ele já foi removido anteriormente
        if !file_path.exists() && !file_path.is_symlink() {
            // Retorna Ok para permitir que a interface e o banco limpem a referência sem travar
            return Ok(());
        }

        let file_name = match file_path.file_name() {
            Some(n) => n,
            None => return Ok(()),
        };

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
                if file_path.exists() {
                    let _ = std::fs::copy(&file_path, &dest);
                    let _ = std::fs::remove_file(&file_path);
                }
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
        let mp3_clean = mp3_path.trim().to_string();
        let serato_clean = serato_path.trim().to_string();

        if mp3_clean.is_empty() || !PathBuf::from(&mp3_clean).is_dir() {
            return Err("Diretório de músicas MP3 inválido ou não encontrado no disco.".into());
        }
        if serato_clean.is_empty() || !PathBuf::from(&serato_clean).is_dir() {
            return Err("Diretório da biblioteca Serato inválido ou não encontrado no disco.".into());
        }

        if !dry_run && is_serato_running() {
            let err_msg = "❌ BLOQUEIO DE SEGURANÇA: O Serato DJ Pro está em execução ativa. Feche o aplicativo Serato DJ Pro antes de gravar ou ajustar a biblioteca. Enquanto o Serato estiver aberto, seu cache na memória RAM reverterá e sobrescreverá qualquer alteração física ao ser encerrado. O Modo Análise (Sem Alterar) permanece disponível.".to_string();
            let _ = window.emit("sync-log", &err_msg);
            return Err(err_msg);
        }

        let script_path = find_canonical_python_script(Some(&app), "serato_macos_app.py")?;
        let python_bin = find_python_binary()?;
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let _ = window_clone.emit("sync-log", format!("🐍 Motor Python: {}", script_path.display()));

            let mut cmd = Command::new(&python_bin);
            cmd.arg(&script_path);
            cmd.arg(&mp3_clean);
            cmd.arg(&serato_clean);
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
                    let err_msg = format!("❌ Erro ao disparar processo Python: {}", e);
                    let _ = window_clone.emit("sync-log", &err_msg);
                    let _ = window_clone.emit(
                        "sync-finished",
                        SyncFinishedPayload {
                            success: false,
                            exit_code: Some(1),
                            message: err_msg,
                        },
                    );
                    return;
                }
            };

            // Leitura concorrente de stdout e stderr para eliminação total de deadlocks
            let stdout = child.stdout.take();
            let stderr = child.stderr.take();

            let win_stdout = window_clone.clone();
            let stdout_thread = std::thread::spawn(move || {
                let mut captured_summary = None;
                if let Some(out) = stdout {
                    let reader = BufReader::new(out);
                    for line_res in reader.lines() {
                        if let Ok(line) = line_res {
                            if line.starts_with("__PAYLOAD_JSON_SUMMARY__") {
                                captured_summary = Some(line.clone());
                            }
                            let _ = win_stdout.emit("sync-log", line);
                        }
                    }
                }
                captured_summary
            });

            let win_stderr = window_clone.clone();
            let stderr_thread = std::thread::spawn(move || {
                let mut err_lines = Vec::new();
                if let Some(err) = stderr {
                    let reader = BufReader::new(err);
                    for line_res in reader.lines() {
                        if let Ok(line) = line_res {
                            let _ = win_stderr.emit("sync-log", format!("⚠️ [STDERR] {}", line));
                            err_lines.push(line);
                        }
                    }
                }
                err_lines.join("\n")
            });

            let _ = stdout_thread.join();
            let stderr_output = stderr_thread.join().unwrap_or_default();

            let exit_status = child.wait();
            let (success, code, message) = match exit_status {
                Ok(status) => {
                    let code = status.code().unwrap_or(-1);
                    if status.success() {
                        (true, code, "Sincronização concluída com sucesso.".into())
                    } else {
                        let err_detail = if !stderr_output.trim().is_empty() {
                            format!("Erro no motor Python (código {}): {}", code, stderr_output.trim())
                        } else {
                            format!("O processo Python encerrou com código de erro {}", code)
                        };
                        (false, code, err_detail)
                    }
                }
                Err(e) => (false, -1, format!("Falha de comunicação/espera do processo: {}", e)),
            };

            let _ = window_clone.emit(
                "sync-finished",
                SyncFinishedPayload {
                    success,
                    exit_code: Some(code),
                    message,
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
        window: Window,
        mp3_path: String,
        limit: Option<usize>,
        offset: Option<usize>,
        search: Option<String>,
        crate_raiz: Option<String>,
        subcrate: Option<String>,
        include_subcrates: Option<bool>,
        naming_mode: Option<String>,
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
        if let Some(nm) = naming_mode {
            if !nm.is_empty() {
                cmd.arg("--naming-mode");
                cmd.arg(nm);
            }
        }

        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());

        let mut child = cmd.spawn().map_err(|e| format!("Falha ao executar scanner: {}", e))?;

        let mut final_json = String::new();
        if let Some(stdout) = child.stdout.take() {
            let reader = BufReader::new(stdout);
            for line_res in reader.lines() {
                if let Ok(line) = line_res {
                    let trimmed = line.trim();
                    if trimmed.starts_with('{') {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(trimmed) {
                            let tipo = parsed.get("tipo").and_then(|t| t.as_str()).unwrap_or("");
                            if tipo == "progresso" {
                                let _ = window.emit("tag-doctor-scan-progress", parsed);
                                continue;
                            } else if tipo == "resultado" {
                                if let Some(dados) = parsed.get("dados") {
                                    final_json = dados.to_string();
                                    continue;
                                }
                            }
                        }
                    }
                    if final_json.is_empty() && trimmed.starts_with('{') {
                        final_json = trimmed.to_string();
                    }
                }
            }
        }

        let status = child.wait().map_err(|e| format!("Falha ao aguardar scanner: {}", e))?;
        if !status.success() && final_json.is_empty() {
            return Err("Erro na execução do scanner".to_string());
        }

        Ok(final_json)
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
        if is_serato_running() {
            return Err("Bloqueio de segurança: O Serato DJ Pro está aberto. Feche o Serato antes de aplicar tags nos arquivos para evitar perda de dados por conflito de gravação.".into());
        }
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

            if let Some(stderr) = child.stderr.take() {
                std::thread::spawn(move || {
                    let reader = BufReader::new(stderr);
                    for _ in reader.lines() {}
                });
            }

            if let Some(stdout) = child.stdout.take() {
                let reader = BufReader::new(stdout);
                for line_res in reader.lines() {
                    if let Ok(line) = line_res {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&line) {
                            let tipo = parsed.get("tipo").and_then(|t| t.as_str()).unwrap_or("");
                            if tipo == "inicio" {
                                let total = parsed.get("total").and_then(|t| t.as_u64()).unwrap_or(0);
                                let _ = window_clone.emit("tag-doctor-batch-progress", serde_json::json!({
                                    "processados": 0,
                                    "total": total,
                                    "percentual": 0,
                                    "atualizados": 0,
                                    "faixa_atual": "Iniciando gravação..."
                                }));
                            } else if tipo == "progresso" {
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
        window: Window,
        items_json: String,
        rename_files: Option<bool>,
    ) -> Result<(), String> {
        if is_serato_running() {
            return Err("Bloqueio de segurança: O Serato DJ Pro está aberto. Feche o Serato antes de aplicar tags nos arquivos para evitar perda de dados por conflito de gravação.".into());
        }
        let script = find_python_script(Some(&app), "tag_doctor.py");
        let window_clone = window.clone();

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

        std::thread::spawn(move || {
            let mut cmd = Command::new("/usr/bin/python3");
            cmd.arg(&script);
            cmd.arg("--apply-tags");
            cmd.arg(&temp_file);
            if let Some(true) = rename_files {
                cmd.arg("--rename-files");
            }

            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            let mut child = match cmd.spawn() {
                Ok(c) => c,
                Err(e) => {
                    let _ = std::fs::remove_file(&temp_file);
                    let _ = window_clone.emit("tag-doctor-apply-finished", serde_json::json!({
                        "sucesso": false,
                        "erro": e.to_string()
                    }));
                    return;
                }
            };

            if let Some(stderr) = child.stderr.take() {
                std::thread::spawn(move || {
                    let reader = BufReader::new(stderr);
                    for _ in reader.lines() {}
                });
            }

            if let Some(stdout) = child.stdout.take() {
                let reader = BufReader::new(stdout);
                for line_res in reader.lines() {
                    if let Ok(line) = line_res {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&line) {
                            let tipo = parsed.get("tipo").and_then(|t| t.as_str()).unwrap_or("");
                            if tipo == "inicio" {
                                let total = parsed.get("total").and_then(|t| t.as_u64()).unwrap_or(0);
                                let _ = window_clone.emit("tag-doctor-apply-progress", serde_json::json!({
                                    "processados": 0,
                                    "total": total,
                                    "percentual": 0,
                                    "atualizados": 0,
                                    "faixa_atual": "Iniciando gravação..."
                                }));
                            } else if tipo == "progresso" {
                                let _ = window_clone.emit("tag-doctor-apply-progress", parsed);
                            } else if tipo == "fim" {
                                let _ = window_clone.emit("tag-doctor-apply-finished", parsed);
                            }
                        }
                    }
                }
            }

            let _ = child.wait();
            let _ = std::fs::remove_file(&temp_file);
        });

        Ok(())
    }

    #[tauri::command]
    pub async fn enrich_missing_artists(
        app: AppHandle,
        window: Window,
        items_json: String,
    ) -> Result<(), String> {
        let script = find_python_script(Some(&app), "tag_doctor.py");
        let window_clone = window.clone();

        let temp_dir = std::env::temp_dir();
        let temp_file = temp_dir.join(format!(
            "tag_enrich_{}.json",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis()
        ));
        std::fs::write(&temp_file, &items_json)
            .map_err(|e| format!("Falha ao criar arquivo temporário: {}", e))?;

        std::thread::spawn(move || {
            let mut cmd = Command::new("/usr/bin/python3");
            cmd.arg(&script);
            cmd.arg("--enrich-artists");
            cmd.arg(&temp_file);

            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            let mut child = match cmd.spawn() {
                Ok(c) => c,
                Err(e) => {
                    let _ = std::fs::remove_file(&temp_file);
                    let _ = window_clone.emit("tag-doctor-enrich-finished", serde_json::json!({
                        "sucesso": false,
                        "erro": e.to_string()
                    }));
                    return;
                }
            };

            if let Some(stderr) = child.stderr.take() {
                std::thread::spawn(move || {
                    let reader = BufReader::new(stderr);
                    for _ in reader.lines() {}
                });
            }

            if let Some(stdout) = child.stdout.take() {
                let reader = BufReader::new(stdout);
                for line_res in reader.lines() {
                    if let Ok(line) = line_res {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&line) {
                            let tipo = parsed.get("tipo").and_then(|t| t.as_str()).unwrap_or("");
                            if tipo == "inicio" {
                                let total = parsed.get("total").and_then(|t| t.as_u64()).unwrap_or(0);
                                let _ = window_clone.emit("tag-doctor-enrich-progress", serde_json::json!({
                                    "processados": 0,
                                    "total": total,
                                    "percentual": 0,
                                    "enriquecidos": 0,
                                    "faixa_atual": "Iniciando identificação..."
                                }));
                            } else if tipo == "progresso" {
                                let _ = window_clone.emit("tag-doctor-enrich-progress", parsed);
                            } else if tipo == "fim" {
                                let _ = window_clone.emit("tag-doctor-enrich-finished", parsed);
                            }
                        }
                    }
                }
            }

            let _ = child.wait();
            let _ = std::fs::remove_file(&temp_file);
        });

        Ok(())
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
        window: Window,
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

        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());

        let mut child = cmd.spawn().map_err(|e| format!("Falha ao iniciar Sound Seal: {}", e))?;

        let mut final_json = String::new();
        if let Some(stdout) = child.stdout.take() {
            let reader = BufReader::new(stdout);
            for line_res in reader.lines() {
                if let Ok(line) = line_res {
                    let trimmed = line.trim();
                    if trimmed.starts_with('{') {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(trimmed) {
                            let tipo = parsed.get("tipo").and_then(|t| t.as_str()).unwrap_or("");
                            if tipo == "progresso" {
                                let _ = window.emit("sound-seal-scan-progress", parsed);
                                continue;
                            } else if tipo == "fim" {
                                final_json = trimmed.to_string();
                                continue;
                            }
                        }
                    }
                    if final_json.is_empty() && trimmed.starts_with('{') {
                        final_json = trimmed.to_string();
                    }
                }
            }
        }

        let status = child.wait().map_err(|e| format!("Falha ao aguardar Sound Seal: {}", e))?;
        if !status.success() && final_json.is_empty() {
            return Err("Erro na execução do Sound Seal".to_string());
        }

        if final_json.is_empty() {
            final_json = "{}".to_string();
        }
        Ok(final_json)
    }

    #[tauri::command]
    pub async fn list_cue_backups(app: AppHandle, search: Option<String>) -> Result<String, String> {
        let script = find_python_script(Some(&app), "auto_cue.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--list-backups");
        if let Some(s) = search {
            if !s.trim().is_empty() {
                cmd.arg("--list-backups-search");
                cmd.arg(s);
            }
        }

        let output = cmd.output().map_err(|e| format!("Falha ao listar backups de cues: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        let result = stdout.lines().filter(|l| !l.trim().is_empty()).last().unwrap_or("{}").to_string();
        if !output.status.success() || result.is_empty() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let msg = if stderr.trim().is_empty() { "Execução falhou" } else { stderr.as_ref() };
            return Err(format!("Erro ao listar backups de cues: {}", msg));
        }
        Ok(result)
    }

    #[tauri::command]
    pub async fn restore_auto_cues(app: AppHandle, filepath: String) -> Result<String, String> {
        if is_serato_running() {
            return Err("Bloqueio de segurança: O Serato DJ Pro está em execução. Feche o Serato antes de restaurar Hot Cues.".into());
        }
        let script = find_python_script(Some(&app), "auto_cue.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--restore");
        cmd.arg(&filepath);

        let output = cmd.output().map_err(|e| format!("Falha ao restaurar Hot Cues: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        if !output.status.success() {
            return Err(stdout);
        }
        Ok(stdout)
    }

    // ------------------------------------------------------------------
    // Ferramentas de biblioteca: BPM/tom, journal de desfazer, crates
    // ------------------------------------------------------------------

    /// Executa um script Python e devolve a última linha JSON da saída.
    fn run_py_json(app: &AppHandle, script: &str, args: &[String]) -> Result<String, String> {
        let path = find_python_script(Some(app), script);
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&path);
        for a in args {
            cmd.arg(a);
        }
        let output = cmd
            .output()
            .map_err(|e| format!("Falha ao executar {}: {}", script, e))?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        let result = stdout
            .lines()
            .filter(|l| !l.trim().is_empty())
            .last()
            .unwrap_or("")
            .to_string();
        if result.starts_with('{') {
            return Ok(result);
        }
        let stderr = String::from_utf8_lossy(&output.stderr);
        let msg = if stderr.trim().is_empty() { "Execução falhou" } else { stderr.as_ref() };
        Err(format!("Erro em {}: {}", script, msg))
    }

    fn bloqueio_serato(acao: &str) -> Result<(), String> {
        if is_serato_running() {
            return Err(format!(
                "Bloqueio de segurança: o Serato DJ Pro está em execução. Feche o Serato antes de {}.",
                acao
            ));
        }
        Ok(())
    }

    #[tauri::command]
    pub async fn analyze_track_file(app: AppHandle, filepath: String) -> Result<String, String> {
        run_py_json(&app, "music_analysis.py", &["--analyze".into(), filepath])
    }

    /// Lote de BPM/tom com progresso transmitido por evento "analysis-progress".
    #[tauri::command]
    pub async fn analyze_tracks_batch(
        app: AppHandle,
        window: Window,
        mp3_path: String,
        limit: usize,
        write: bool,
        include_filled: bool,
    ) -> Result<String, String> {
        if write {
            bloqueio_serato("gravar BPM e tom nas tags")?;
        }
        let script = find_python_script(Some(&app), "music_analysis.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script).arg("--analyze-batch").arg(&mp3_path);
        cmd.arg("--limit").arg(limit.to_string());
        if write {
            cmd.arg("--write");
        }
        if include_filled {
            cmd.arg("--include-filled");
        }
        cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

        let mut child = cmd.spawn().map_err(|e| format!("Falha ao iniciar análise: {}", e))?;
        let mut final_json = String::new();
        if let Some(stdout) = child.stdout.take() {
            for line_res in BufReader::new(stdout).lines() {
                if let Ok(line) = line_res {
                    let trimmed = line.trim().to_string();
                    if trimmed.starts_with('{') {
                        let _ = window.emit("analysis-progress", trimmed.clone());
                        final_json = trimmed;
                    }
                }
            }
        }
        let status = child.wait().map_err(|e| format!("Falha ao aguardar análise: {}", e))?;
        if !status.success() && final_json.is_empty() {
            return Err("Erro na execução da análise de BPM/tom".into());
        }
        Ok(final_json)
    }

    #[tauri::command]
    pub async fn list_journal(app: AppHandle, limit: usize) -> Result<String, String> {
        run_py_json(&app, "journal.py", &["--list".into(), "--limit".into(), limit.to_string()])
    }

    #[tauri::command]
    pub async fn undo_journal(app: AppHandle, op_id: Option<i64>) -> Result<String, String> {
        bloqueio_serato("desfazer alterações de tags")?;
        let mut args: Vec<String> = vec!["--undo".into()];
        if let Some(id) = op_id {
            args.push(id.to_string());
        }
        run_py_json(&app, "journal.py", &args)
    }

    #[tauri::command]
    pub async fn check_crate_references(app: AppHandle, serato_path: String) -> Result<String, String> {
        run_py_json(&app, "library_tools.py", &["--check-refs".into(), "--serato".into(), serato_path])
    }

    #[tauri::command]
    pub async fn library_health(app: AppHandle, mp3_path: String, serato_path: String) -> Result<String, String> {
        run_py_json(&app, "library_tools.py", &[
            "--health".into(), "--mp3".into(), mp3_path, "--serato".into(), serato_path,
        ])
    }

    #[tauri::command]
    pub async fn export_crate_m3u(app: AppHandle, serato_path: String, crate_file: String) -> Result<String, String> {
        run_py_json(&app, "library_tools.py", &[
            "--export-m3u".into(), crate_file, "--serato".into(), serato_path,
        ])
    }

    #[tauri::command]
    pub async fn import_m3u_crate(
        app: AppHandle,
        serato_path: String,
        m3u_path: String,
        crate_name: String,
    ) -> Result<String, String> {
        bloqueio_serato("criar uma crate")?;
        run_py_json(&app, "library_tools.py", &[
            "--import-m3u".into(), m3u_path, "--crate-name".into(), crate_name, "--serato".into(), serato_path,
        ])
    }

    #[tauri::command]
    pub async fn smart_crate_create(
        app: AppHandle,
        mp3_path: String,
        serato_path: String,
        config_json: String,
        dry_run: bool,
    ) -> Result<String, String> {
        if !dry_run {
            bloqueio_serato("criar uma crate inteligente")?;
        }
        let mut args: Vec<String> = vec![
            "--smart-create".into(), config_json, "--mp3".into(), mp3_path, "--serato".into(), serato_path,
        ];
        if dry_run {
            args.push("--smart-dry-run".into());
        }
        run_py_json(&app, "library_tools.py", &args)
    }

    #[tauri::command]
    pub async fn smart_crate_refresh(app: AppHandle, mp3_path: String, serato_path: String) -> Result<String, String> {
        bloqueio_serato("regenerar crates inteligentes")?;
        run_py_json(&app, "library_tools.py", &[
            "--smart-refresh".into(), "--mp3".into(), mp3_path, "--serato".into(), serato_path,
        ])
    }

    #[tauri::command]
    pub async fn smart_crate_list(app: AppHandle) -> Result<String, String> {
        run_py_json(&app, "library_tools.py", &["--smart-list".into()])
    }

    #[tauri::command]
    pub async fn smart_crate_delete(app: AppHandle, nome: String) -> Result<String, String> {
        run_py_json(&app, "library_tools.py", &["--smart-delete".into(), nome])
    }

    #[tauri::command]
    pub async fn scan_new_tracks(app: AppHandle, mp3_path: String) -> Result<String, String> {
        run_py_json(&app, "library_tools.py", &["--scan-new".into(), "--mp3".into(), mp3_path])
    }

    #[tauri::command]
    pub async fn get_sound_seal_status(app: AppHandle) -> Result<String, String> {
        let script = find_python_script(Some(&app), "sound_seal.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--status");

        let output = cmd.output().map_err(|e| format!("Falha ao consultar status do Sound Seal: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        let result = stdout.lines().filter(|l| !l.trim().is_empty()).last().unwrap_or("{}").to_string();
        if !output.status.success() || result.is_empty() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let msg = if stderr.trim().is_empty() { "Execução falhou" } else { stderr.as_ref() };
            return Err(format!("Erro ao consultar status do Sound Seal: {}", msg));
        }
        Ok(result)
    }

    #[tauri::command]
    pub async fn get_sound_seal_duplicates(app: AppHandle, strategy: Option<String>) -> Result<String, String> {
        let script = find_python_script(Some(&app), "sound_seal.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--duplicates");
        if let Some(s) = strategy {
            cmd.arg("--strategy");
            cmd.arg(s);
        }

        let output = cmd.output().map_err(|e| format!("Falha ao consultar duplicatas do Sound Seal: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        let result = stdout.lines().filter(|l| !l.trim().is_empty()).last().unwrap_or("{}").to_string();
        if !output.status.success() || result.is_empty() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let msg = if stderr.trim().is_empty() { "Execução falhou" } else { stderr.as_ref() };
            return Err(format!("Erro ao consultar duplicatas do Sound Seal: {}", msg));
        }
        Ok(result)
    }

    #[tauri::command]
    pub async fn set_sound_seal_master(app: AppHandle, audio_seal: String, filepath: String) -> Result<String, String> {
        let script = find_python_script(Some(&app), "sound_seal.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--set-master");
        cmd.arg(&audio_seal);
        cmd.arg(&filepath);

        let output = cmd.output().map_err(|e| format!("Falha ao definir master do Sound Seal: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        let result = stdout.lines().filter(|l| !l.trim().is_empty()).last().unwrap_or("{}").to_string();
        if !output.status.success() || result.is_empty() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let msg = if stderr.trim().is_empty() { "Execução falhou" } else { stderr.as_ref() };
            return Err(format!("Erro ao definir master do Sound Seal: {}", msg));
        }
        Ok(result)
    }

    #[tauri::command]
    pub async fn batch_set_sound_seal_masters(app: AppHandle, masters_json: String) -> Result<String, String> {
        let script = find_python_script(Some(&app), "sound_seal.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--batch-set-masters");
        cmd.arg(&masters_json);

        let output = cmd.output().map_err(|e| format!("Falha ao salvar masters em lote: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        let result = stdout.lines().filter(|l| !l.trim().is_empty()).last().unwrap_or("{}").to_string();
        if !output.status.success() || result.is_empty() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let msg = if stderr.trim().is_empty() { "Execução falhou" } else { stderr.as_ref() };
            return Err(format!("Erro ao salvar masters em lote: {}", msg));
        }
        Ok(result)
    }

    #[tauri::command]
    pub async fn clear_sound_seal_masters(app: AppHandle) -> Result<String, String> {
        let script = find_python_script(Some(&app), "sound_seal.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--clear-masters");

        let output = cmd.output().map_err(|e| format!("Falha ao limpar preferências de master: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        let result = stdout.lines().filter(|l| !l.trim().is_empty()).last().unwrap_or("{}").to_string();
        if !output.status.success() || result.is_empty() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let msg = if stderr.trim().is_empty() { "Execução falhou" } else { stderr.as_ref() };
            return Err(format!("Erro ao limpar masters: {}", msg));
        }
        Ok(result)
    }

    #[tauri::command]
    pub async fn scan_missing_relocate(
        app: AppHandle,
        window: Window,
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

        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());

        let mut child = cmd.spawn().map_err(|e| format!("Falha ao iniciar scanner de faixas perdidas: {}", e))?;

        let mut final_json = String::new();
        if let Some(stdout) = child.stdout.take() {
            let reader = BufReader::new(stdout);
            for line_res in reader.lines() {
                if let Ok(line) = line_res {
                    let trimmed = line.trim();
                    if trimmed.starts_with('{') {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(trimmed) {
                            let tipo = parsed.get("tipo").and_then(|t| t.as_str()).unwrap_or("");
                            if tipo == "progresso" {
                                let _ = window.emit("relocate-scan-progress", parsed);
                                continue;
                            } else if tipo == "fim" {
                                final_json = trimmed.to_string();
                                continue;
                            }
                        }
                    }
                    if final_json.is_empty() && trimmed.starts_with('{') {
                        final_json = trimmed.to_string();
                    }
                }
            }
        }

        let status = child.wait().map_err(|e| format!("Falha ao aguardar scanner de faixas perdidas: {}", e))?;
        if !status.success() && final_json.is_empty() {
            return Err("Erro na execução do Relocate".to_string());
        }

        if final_json.is_empty() {
            final_json = "{}".to_string();
        }
        Ok(final_json)
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
    pub async fn remove_lost_tracks(
        app: AppHandle,
        mp3_path: String,
        serato_path: String,
        target_path: Option<String>,
        target_paths: Option<String>,
    ) -> Result<String, String> {
        let script = find_python_script(Some(&app), "sound_seal.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--remove-lost");
        cmd.arg("--mp3");
        cmd.arg(&mp3_path);
        cmd.arg("--serato");
        cmd.arg(&serato_path);
        if let Some(tp) = target_path {
            if !tp.trim().is_empty() {
                cmd.arg("--target-path");
                cmd.arg(tp);
            }
        }
        if let Some(tps) = target_paths {
            if !tps.trim().is_empty() {
                cmd.arg("--target-paths");
                cmd.arg(tps);
            }
        }
        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());

        let output = cmd
            .output()
            .map_err(|e| format!("Erro ao executar sound_seal.py --remove-lost: {e}"))?;

        let stdout = String::from_utf8_lossy(&output.stdout);
        let result: String = stdout.lines().filter(|l| !l.trim().is_empty()).last().unwrap_or("{}").to_string();
        if !output.status.success() || result.is_empty() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let msg = if stderr.trim().is_empty() { result.as_str() } else { stderr.as_ref() };
            return Err(format!("Falha ao remover faixas: {}", msg));
        }
        Ok(result)
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
        } else if input_type == "folder" {
            cmd.arg("--match-folder");
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
    pub async fn replace_upgrades_track_matcher(
        app: AppHandle,
        upgrades_json: String,
    ) -> Result<String, String> {
        let script = find_python_script(Some(&app), "track_matcher.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--replace-upgrades");
        cmd.arg(&upgrades_json);

        let output = cmd.output().map_err(|e| format!("Falha ao substituir upgrades: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn integrate_tracks_to_crate(
        app: AppHandle,
        tracks_json: String,
        target_folder: String,
    ) -> Result<String, String> {
        let script = find_python_script(Some(&app), "track_matcher.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--integrate-tracks");
        cmd.arg(&tracks_json);
        cmd.arg("--target-folder");
        cmd.arg(&target_folder);

        let output = cmd.output().map_err(|e| format!("Falha ao integrar faixas na Crate: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn scan_audio_health(
        app: AppHandle,
        window: Window,
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

        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());

        let mut child = cmd.spawn().map_err(|e| format!("Falha na auditoria de áudio: {}", e))?;

        let mut final_json = String::new();
        if let Some(stdout) = child.stdout.take() {
            let reader = BufReader::new(stdout);
            for line_res in reader.lines() {
                if let Ok(line) = line_res {
                    let trimmed = line.trim();
                    if trimmed.starts_with('{') {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(trimmed) {
                            let tipo = parsed.get("tipo").and_then(|t| t.as_str()).unwrap_or("");
                            if tipo == "progresso" {
                                let _ = window.emit("audio-health-scan-progress", parsed);
                                continue;
                            } else if tipo == "resultado" {
                                if let Some(dados) = parsed.get("dados") {
                                    final_json = dados.to_string();
                                    continue;
                                }
                            }
                        }
                    }
                    if final_json.is_empty() && trimmed.starts_with('{') {
                        final_json = trimmed.to_string();
                    }
                }
            }
        }

        let status = child.wait().map_err(|e| format!("Falha ao aguardar auditoria de áudio: {}", e))?;
        if !status.success() && final_json.is_empty() {
            return Err("Erro na execução da auditoria de áudio".to_string());
        }

        if final_json.is_empty() {
            final_json = "{}".to_string();
        }
        Ok(final_json)
    }

    #[tauri::command]
    pub async fn resample_track_local(app: AppHandle, filepath: String) -> Result<String, String> {
        let script = find_python_script(Some(&app), "audio_health.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--resample-local");
        cmd.arg(&filepath);

        let output = cmd.output().map_err(|e| format!("Falha ao normalizar frequência: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn batch_resample_local(
        app: AppHandle,
        window: Window,
        filepaths_json: String,
    ) -> Result<(), String> {
        let script = find_python_script(Some(&app), "audio_health.py");
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let mut cmd = Command::new("/usr/bin/python3");
            cmd.arg(&script);
            cmd.arg("--batch-resample-local");
            cmd.arg(&filepaths_json);
            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            let mut child = match cmd.spawn() {
                Ok(c) => c,
                Err(e) => {
                    let _ = window_clone.emit("audio-health-resample-finished", serde_json::json!({
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
                                let _ = window_clone.emit("audio-health-resample-progress", parsed);
                            } else if tipo == "fim" {
                                let _ = window_clone.emit("audio-health-resample-finished", parsed);
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
    pub async fn preaudit_track_online(app: AppHandle, filepath: String) -> Result<String, String> {
        let script = find_python_script(Some(&app), "audio_health.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--preaudit-online");
        cmd.arg(&filepath);

        let output = cmd.output().map_err(|e| format!("Falha ao pré-auditar faixa online: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn batch_preaudit_online(
        app: AppHandle,
        window: Window,
        filepaths_json: String,
    ) -> Result<(), String> {
        let script = find_python_script(Some(&app), "audio_health.py");
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let mut cmd = Command::new("/usr/bin/python3");
            cmd.arg(&script);
            cmd.arg("--batch-preaudit-online");
            cmd.arg(&filepaths_json);
            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            let mut child = match cmd.spawn() {
                Ok(c) => c,
                Err(e) => {
                    let _ = window_clone.emit("audio-health-preaudit-finished", serde_json::json!({
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
                                let _ = window_clone.emit("audio-health-preaudit-progress", parsed);
                            } else if tipo == "fim" {
                                let _ = window_clone.emit("audio-health-preaudit-finished", parsed);
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
    pub async fn rename_audio_track(
        app: AppHandle,
        filepath: String,
        new_name: String,
    ) -> Result<String, String> {
        let script = find_python_script(Some(&app), "audio_health.py");
        let mut cmd = Command::new("/usr/bin/python3");
        cmd.arg(&script);
        cmd.arg("--rename-track");
        cmd.arg(&filepath);
        cmd.arg("--new-name");
        cmd.arg(&new_name);

        let output = cmd.output().map_err(|e| format!("Falha ao renomear arquivo: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
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
        if is_serato_running() {
            return Err("Bloqueio de segurança: O Serato DJ Pro está em execução. Feche o Serato antes de gravar Hot Cues nos arquivos.".into());
        }
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
    pub async fn audit_crate_cues(
        app: AppHandle,
        mp3_path: String,
        crate_raiz: Option<String>,
        subcrate: Option<String>,
        include_subcrates: Option<bool>,
    ) -> Result<String, String> {
        let script = find_canonical_python_script(Some(&app), "auto_cue.py")?;
        let python_bin = find_python_binary()?;
        let mut cmd = Command::new(&python_bin);
        cmd.arg(&script);
        cmd.arg("--audit-crate");
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

        let output = cmd.output().map_err(|e| format!("Falha ao auditar cues na crate: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();

        if !output.status.success() {
            let err_msg = if !stderr.trim().is_empty() {
                format!("Erro na auditoria de cues: {}", stderr.trim())
            } else {
                format!("Erro na auditoria (código {}): {}", output.status.code().unwrap_or(-1), stdout.trim())
            };
            return Err(err_msg);
        }
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
        overwrite_existing: Option<bool>,
    ) -> Result<(), String> {
        if is_serato_running() {
            return Err("Bloqueio de segurança: O Serato DJ Pro está em execução. Feche o Serato antes de aplicar Hot Cues na crate.".into());
        }
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
            if let Some(true) = overwrite_existing {
                cmd.arg("--overwrite-existing");
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
    pub async fn repair_crate_cues(
        app: AppHandle,
        window: Window,
        mp3_path: String,
        crate_raiz: Option<String>,
        subcrate: Option<String>,
        include_subcrates: Option<bool>,
    ) -> Result<(), String> {
        let script = find_python_script(Some(&app), "auto_cue.py");
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let mut cmd = Command::new("/usr/bin/python3");
            cmd.arg(&script);
            cmd.arg("--repair-batch");
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

            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            let mut child = match cmd.spawn() {
                Ok(c) => c,
                Err(e) => {
                    let _ = window_clone.emit("auto-cue-repair-finished", serde_json::json!({
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
                                let _ = window_clone.emit("auto-cue-repair-progress", parsed);
                            } else if tipo == "fim" {
                                let _ = window_clone.emit("auto-cue-repair-finished", parsed);
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
        if is_serato_running() {
            return Err("Bloqueio de segurança: O Serato DJ Pro está em execução. Feche o Serato antes de aplicar lote de Hot Cues nos arquivos.".into());
        }
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
            commands::get_system_telemetry,
            commands::get_detected_paths,
            commands::validate_path,
            commands::start_sync,
            commands::open_in_finder,
            commands::open_file_in_finder,
            commands::move_to_trash,
            commands::list_crates_tag_doctor,
            commands::scan_tags_doctor,
            commands::apply_tags_doctor,
            commands::batch_apply_tags_doctor,
            commands::enrich_missing_artists,
            commands::backup_serato_db,
            commands::list_serato_backups,
            commands::restore_serato_db,
            commands::scan_sound_seals,
            commands::get_sound_seal_status,
            commands::get_sound_seal_duplicates,
            commands::set_sound_seal_master,
            commands::batch_set_sound_seal_masters,
            commands::clear_sound_seal_masters,
            commands::scan_missing_relocate,
            commands::relink_track,
            commands::batch_relink_tracks,
            commands::remove_lost_tracks,
            commands::match_tracks,
            commands::replace_upgrades_track_matcher,
            commands::integrate_tracks_to_crate,
            commands::scan_audio_health,
            commands::repair_track_online,
            commands::batch_repair_online,
            commands::preaudit_track_online,
            commands::batch_preaudit_online,
            commands::rename_audio_track,
            commands::resample_track_local,
            commands::batch_resample_local,
            commands::preview_auto_cues,
            commands::apply_auto_cues,
            commands::scan_crate_cues,
            commands::audit_crate_cues,
            commands::batch_apply_crate_cues,
            commands::repair_crate_cues,
            commands::apply_batch_auto_cues,
            commands::list_cue_backups,
            commands::restore_auto_cues,
            commands::analyze_track_file,
            commands::analyze_tracks_batch,
            commands::list_journal,
            commands::undo_journal,
            commands::check_crate_references,
            commands::library_health,
            commands::export_crate_m3u,
            commands::import_m3u_crate,
            commands::smart_crate_create,
            commands::smart_crate_refresh,
            commands::smart_crate_list,
            commands::smart_crate_delete,
            commands::scan_new_tracks
        ])
        .run(tauri::generate_context!())
        .expect("erro ao inicializar aplicação tauri");
}
