use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::channel;
use std::time::Duration;
use notify::{Config, RecommendedWatcher, RecursiveMode, Watcher};
use tauri::{AppHandle, Emitter, Manager, Window};
use serde::{Deserialize, Serialize};

#[derive(Clone)]
pub struct AppSecurityState {
    pub is_operation_active: Arc<AtomicBool>,
    pub is_ui_busy: Arc<AtomicBool>,
}

#[derive(Debug)]
pub struct OperationGuard {
    active_flag: Arc<AtomicBool>,
}

impl Drop for OperationGuard {
    fn drop(&mut self) {
        self.active_flag.store(false, Ordering::SeqCst);
    }
}

impl AppSecurityState {
    pub fn new() -> Self {
        Self {
            is_operation_active: Arc::new(AtomicBool::new(false)),
            is_ui_busy: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Tenta adquirir o bloqueio exclusivo de operação mutável.
    /// Retorna OperationGuard se adquirido com sucesso, ou Erro se outra operação já estiver ativa.
    pub fn acquire_lock(&self) -> Result<OperationGuard, String> {
        if self
            .is_operation_active
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_ok()
        {
            Ok(OperationGuard {
                active_flag: Arc::clone(&self.is_operation_active),
            })
        } else {
            Err("Bloqueio de concorrência: outra operação de gravação ou sincronização já está em execução no momento.".to_string())
        }
    }
}

pub fn generate_operacao_id() -> String {
    static COUNTER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let count = COUNTER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let h1 = (nanos >> 64) as u64;
    let h2 = (nanos & 0xFFFF_FFFF_FFFF_FFFF) as u64;
    format!(
        "{:08x}-{:04x}-4{:03x}-a{:03x}-{:012x}",
        (h1 >> 32) as u32,
        (h1 & 0xFFFF) as u16,
        ((h1 >> 16) & 0x0FFF) as u16,
        ((h2 >> 48) & 0x0FFF) as u16,
        (h2 & 0x0000_FFFF_FFFF_FFFF) ^ count
    )
}

pub fn format_structured_error(
    codigo: &str,
    mensagem: &str,
    detalhes: serde_json::Value,
) -> String {
    let operacao_id = generate_operacao_id();
    serde_json::json!({
        "sucesso": false,
        "codigo": codigo,
        "mensagem": mensagem,
        "detalhes": detalhes,
        "operacao_id": operacao_id
    })
    .to_string()
}

#[derive(Serialize, Deserialize, Clone)]
pub struct DetectedPaths {
    pub mp3: String,
    pub serato: String,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct DetectedDjVolume {
    pub name: String,
    pub mount_point: String,
    pub mp3_path: Option<String>,
    pub serato_path: Option<String>,
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

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct FsChangeEvent {
    pub folder: String,
    pub count: usize,
    pub extensions: Vec<String>,
}

pub struct FsWatcherState {
    pub active_path: Arc<Mutex<Option<String>>>,
    pub watcher: Arc<Mutex<Option<RecommendedWatcher>>>,
}

impl FsWatcherState {
    pub fn new() -> Self {
        Self {
            active_path: Arc::new(Mutex::new(None)),
            watcher: Arc::new(Mutex::new(None)),
        }
    }
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

fn make_python_cmd_with_app(app: Option<&AppHandle>, script: &Path, bin: &Path) -> Command {
    let mut cmd = Command::new(bin);
    cmd.env("PYTHONDONTWRITEBYTECODE", "1");

    // Localização canônica dos módulos embutidos (vendor)
    let mut vendor_paths: Vec<PathBuf> = Vec::new();

    // 1. Recursos do bundle .app (.app/Contents/Resources/vendor)
    if let Ok(exe) = std::env::current_exe() {
        if let Some(macos_dir) = exe.parent() {
            if let Some(contents_dir) = macos_dir.parent() {
                let res_vendor = contents_dir.join("Resources").join("vendor");
                if res_vendor.is_dir() {
                    vendor_paths.push(res_vendor);
                }
            }
        }
    }

    // 2. Recursos via Tauri handle
    if let Some(handle) = app {
        if let Ok(res_dir) = handle.path().resource_dir() {
            let res_vendor = res_dir.join("vendor");
            if res_vendor.is_dir() {
                vendor_paths.push(res_vendor);
            }
        }
    }

    // 3. Fallback ao lado do próprio script ou workspace raiz
    if let Some(parent) = script.parent() {
        let script_vendor = parent.join("vendor");
        if script_vendor.is_dir() {
            vendor_paths.push(script_vendor);
        }
    }

    // Se encontramos diretórios vendor, injetamos explicitamente no PYTHONPATH
    if !vendor_paths.is_empty() {
        let mut py_path_parts: Vec<String> = vendor_paths
            .into_iter()
            .map(|p| p.to_string_lossy().to_string())
            .collect();

        if let Ok(existing) = std::env::var("PYTHONPATH") {
            if !existing.is_empty() {
                py_path_parts.push(existing);
            }
        }

        cmd.env("PYTHONPATH", py_path_parts.join(":"));
    }

    // Garante que /opt/homebrew/bin e /usr/local/bin estão no PATH para descoberta de ffmpeg
    if let Ok(current_path) = std::env::var("PATH") {
        let parts: Vec<&str> = current_path.split(':').collect();
        let mut new_parts = Vec::new();
        for p in &["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"] {
            if !parts.contains(p) {
                new_parts.push(*p);
            }
        }
        if !new_parts.is_empty() {
            let full_path = format!("{}:{}", new_parts.join(":"), current_path);
            cmd.env("PATH", full_path);
        }
    }

    cmd.arg(script);
    cmd
}

fn make_python_cmd(script: &Path, bin: &Path) -> Command {
    make_python_cmd_with_app(None, script, bin)
}

fn find_python_cmd(app: Option<&AppHandle>, script_name: &str) -> Result<Command, String> {
    let script = find_canonical_python_script(app, script_name)?;
    let bin = find_python_binary()?;
    Ok(make_python_cmd_with_app(app, &script, &bin))
}

#[allow(dead_code)]
fn find_python_script(app: Option<&AppHandle>, script_name: &str) -> Result<PathBuf, String> {
    find_canonical_python_script(app, script_name)
}


pub fn is_serato_running() -> bool {
    let procs = ["Serato DJ Pro", "Serato DJ Lite", "Serato DJ"];
    for proc_name in &procs {
        match Command::new("pgrep").arg("-x").arg(proc_name).output() {
            Ok(output) => {
                match output.status.code() {
                    Some(0) => return true, // Processo Serato detectado em execução ativa
                    Some(1) => {},          // Nenhum processo ativo detectado com esse nome
                    _ => return true,       // Fail-closed: código != 1 ou None (processo morto por sinal)
                }
            }
            Err(_) => {
                // Falha ao invocar pgrep no sistema operacional: fail-closed por segurança
                return true;
            }
        }
    }
    false
}

pub fn bloqueio_serato(acao: &str) -> Result<(), String> {
    if is_serato_running() {
        return Err(format!(
            "❌ BLOQUEIO DE SEGURANÇA: O Serato DJ Pro está em execução ativa (ou seu estado não pôde ser verificado pelo sistema). Feche o aplicativo Serato DJ Pro antes de {}.",
            acao
        ));
    }
    Ok(())
}

pub fn bloqueio_serato_e_concorrencia(
    app: Option<&AppHandle>,
    acao: &str,
) -> Result<Option<OperationGuard>, String> {
    bloqueio_serato(acao)?;
    if let Some(handle) = app {
        if let Some(state) = handle.try_state::<AppSecurityState>() {
            let guard = state.acquire_lock().map_err(|e| {
                format!("❌ {}: não é possível {}.", e, acao)
            })?;
            return Ok(Some(guard));
        }
    }
    Ok(None)
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
            let internal_serato_music = home.join("Music").join("_Serato_");
            let internal_serato_appsup = home.join("Library").join("Application Support").join("Serato");

            // Crates e preferências residem em Music/_Serato_!
            let opt_serato = if internal_serato_music.exists() && internal_serato_music.is_dir() {
                Some(internal_serato_music)
            } else if internal_serato_appsup.exists() && internal_serato_appsup.is_dir() {
                Some(internal_serato_appsup)
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
    pub async fn detect_dj_volumes() -> Result<Vec<DetectedDjVolume>, String> {
        let mut volumes = Vec::new();

        // 1. Armazenamento interno (Macintosh HD / Home)
        if let Some(home) = dirs_home() {
            let mp3_sub = home.join("Music").join("MP3");
            let mp3_main = home.join("Music");
            let serato_appsup = home.join("Library").join("Application Support").join("Serato");
            let serato_music = home.join("Music").join("_Serato_");

            let found_mp3 = if mp3_sub.exists() && mp3_sub.is_dir() {
                Some(mp3_sub.to_string_lossy().to_string())
            } else if mp3_main.exists() && mp3_main.is_dir() {
                Some(mp3_main.to_string_lossy().to_string())
            } else {
                None
            };

            let found_serato = if serato_music.exists() && serato_music.is_dir() {
                Some(serato_music.to_string_lossy().to_string())
            } else if serato_appsup.exists() && serato_appsup.is_dir() {
                Some(serato_appsup.to_string_lossy().to_string())
            } else {
                None
            };

            if found_mp3.is_some() || found_serato.is_some() {
                volumes.push(DetectedDjVolume {
                    name: "Macintosh HD (Interno)".into(),
                    mount_point: home.to_string_lossy().to_string(),
                    mp3_path: found_mp3,
                    serato_path: found_serato,
                });
            }
        }

        // 2. Volumes externos montados em /Volumes
        if let Ok(entries) = std::fs::read_dir("/Volumes") {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
                    if !name.starts_with('.') && !name.starts_with("Macintosh") {
                        let serato_moderno = path.join("Serato");
                        let serato_legado = path.join("_Serato_");
                        let mp3_sub = path.join("Music").join("MP3");
                        let mp3_main = path.join("Music");

                        let found_serato = if serato_moderno.exists() && serato_moderno.is_dir() {
                            Some(serato_moderno.to_string_lossy().to_string())
                        } else if serato_legado.exists() && serato_legado.is_dir() {
                            Some(serato_legado.to_string_lossy().to_string())
                        } else {
                            None
                        };

                        let found_mp3 = if mp3_sub.exists() && mp3_sub.is_dir() {
                            Some(mp3_sub.to_string_lossy().to_string())
                        } else if mp3_main.exists() && mp3_main.is_dir() {
                            Some(mp3_main.to_string_lossy().to_string())
                        } else {
                            None
                        };

                        if found_serato.is_some() || found_mp3.is_some() {
                            volumes.push(DetectedDjVolume {
                                name: format!("Volume: {}", name),
                                mount_point: path.to_string_lossy().to_string(),
                                mp3_path: found_mp3,
                                serato_path: found_serato,
                            });
                        }
                    }
                }
            }
        }

        Ok(volumes)
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
    pub async fn open_in_browser(path_or_url: String) -> Result<(), String> {
        let trimmed = path_or_url.trim();
        let target = if trimmed.starts_with("~/") {
            if let Some(home) = dirs_home() {
                home.join(&trimmed[2..]).to_string_lossy().to_string()
            } else {
                trimmed.to_string()
            }
        } else {
            trimmed.to_string()
        };

        Command::new("open")
            .arg(&target)
            .spawn()
            .map_err(|e| format!("Falha ao abrir no navegador: {}", e))?;

        Ok(())
    }

    #[tauri::command]
    pub async fn save_text_file(path: String, content: String) -> Result<String, String> {
        let expanded = if path.starts_with("~/") {
            if let Some(home) = dirs_home() {
                home.join(&path[2..])
            } else {
                PathBuf::from(&path)
            }
        } else {
            PathBuf::from(&path)
        };

        if let Some(parent) = expanded.parent() {
            let _ = std::fs::create_dir_all(parent);
        }

        std::fs::write(&expanded, content.as_bytes())
            .map_err(|e| format!("Erro ao salvar arquivo em {}: {}", expanded.display(), e))?;

        Ok(expanded.to_string_lossy().to_string())
    }

    #[tauri::command]
    pub async fn move_to_trash(path: String) -> Result<(), String> {
        bloqueio_serato("mover arquivo para a lixeira")?;
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
        _security_state: tauri::State<'_, AppSecurityState>,
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

        let guard = if !dry_run {
            Some(bloqueio_serato_e_concorrencia(Some(&app), "executar sincronização física da biblioteca")?)
        } else {
            None
        };

        let script_path = find_canonical_python_script(Some(&app), "serato_macos_app.py")?;
        let python_bin = find_python_binary()?;
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let _guard = guard;
            if !dry_run && is_serato_running() {
                let err_msg = "❌ BLOQUEIO DE SEGURANÇA: O Serato DJ Pro foi aberto durante a inicialização da sincronização. Operação cancelada.".to_string();
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
            let _ = window_clone.emit("sync-log", format!("🐍 Motor Python: {}", script_path.display()));

            let mut cmd = Command::new(&python_bin);
            cmd.env("PYTHONDONTWRITEBYTECODE", "1");
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
        let mut cmd = find_python_cmd(Some(&app), "tag_doctor.py")?;
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
        let mut cmd = find_python_cmd(Some(&app), "tag_doctor.py")?;
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
        let guard = bloqueio_serato_e_concorrencia(Some(&app), "aplicar tags nas músicas em lote")?;
        let script = find_canonical_python_script(Some(&app), "tag_doctor.py")?;
        let python_bin = find_python_binary()?;
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let _guard = guard;
            let mut cmd = make_python_cmd(&script, &python_bin);
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
        let guard = bloqueio_serato_e_concorrencia(Some(&app), "aplicar tags nas músicas selecionadas")?;
        let script = find_canonical_python_script(Some(&app), "tag_doctor.py")?;
        let python_bin = find_python_binary()?;
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
            let _guard = guard;
            let mut cmd = make_python_cmd_with_app(None, &script, &python_bin);
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
        let guard = bloqueio_serato_e_concorrencia(Some(&app), "enriquecer artistas ausentes nas tags")?;
        let script = find_canonical_python_script(Some(&app), "tag_doctor.py")?;
        let python_bin = find_python_binary()?;
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
            let _guard = guard;
            let mut cmd = make_python_cmd(&script, &python_bin);
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
        let mut cmd = find_python_cmd(Some(&app), "tag_doctor.py")?;
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
        let mut cmd = find_python_cmd(Some(&app), "tag_doctor.py")?;
        cmd.arg("--list-backups");

        let output = cmd.output().map_err(|e| format!("Falha ao listar backups: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn restore_serato_db(app: AppHandle, backup_path: String) -> Result<String, String> {
        let mut cmd = find_python_cmd(Some(&app), "tag_doctor.py")?;
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
        force: Option<bool>,
    ) -> Result<String, String> {
        let mut cmd = find_python_cmd(Some(&app), "sound_seal.py")?;
        cmd.arg("--scan");
        cmd.arg("--mp3");
        cmd.arg(&mp3_path);
        if let Some(b) = batch {
            cmd.arg("--batch");
            cmd.arg(b.to_string());
        }
        if let Some(true) = force {
            cmd.arg("--force");
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
        let mut cmd = find_python_cmd(Some(&app), "auto_cue.py")?;
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
        let mut cmd = find_python_cmd(Some(&app), "auto_cue.py")?;
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

    fn try_parse_json(stdout: &str) -> Option<serde_json::Value> {
        let stdout_trim = stdout.trim();
        if (stdout_trim.starts_with('{') && stdout_trim.ends_with('}'))
            || (stdout_trim.starts_with('[') && stdout_trim.ends_with(']'))
        {
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(stdout_trim) {
                return Some(v);
            }
        }

        for line in stdout.lines().rev() {
            let line_trim = line.trim();
            if (line_trim.starts_with('{') && line_trim.ends_with('}'))
                || (line_trim.starts_with('[') && line_trim.ends_with(']'))
            {
                if let Ok(v) = serde_json::from_str::<serde_json::Value>(line_trim) {
                    return Some(v);
                }
            }
        }

        if let Some(first_brace) = stdout.find('{') {
            if let Some(last_brace) = stdout.rfind('}') {
                if last_brace > first_brace {
                    let slice = &stdout[first_brace..=last_brace];
                    if let Ok(v) = serde_json::from_str::<serde_json::Value>(slice) {
                        return Some(v);
                    }
                }
            }
        }

        if let Some(first_bracket) = stdout.find('[') {
            if let Some(last_bracket) = stdout.rfind(']') {
                if last_bracket > first_bracket {
                    let slice = &stdout[first_bracket..=last_bracket];
                    if let Ok(v) = serde_json::from_str::<serde_json::Value>(slice) {
                        return Some(v);
                    }
                }
            }
        }

        None
    }

    /// Executa um script Python e devolve a resposta JSON de forma robusta e resiliente.
    fn run_py_json(app: &AppHandle, script: &str, args: &[String]) -> Result<String, String> {
        let path = match find_canonical_python_script(Some(app), script) {
            Ok(p) => p,
            Err(e) => {
                return Err(format_structured_error(
                    "SCRIPT_NOT_FOUND",
                    &format!("Script Python '{}' não encontrado nos recursos do aplicativo", script),
                    serde_json::json!({ "script": script, "erro": e }),
                ));
            }
        };

        let python_bin = match find_python_binary() {
            Ok(b) => b,
            Err(e) => {
                return Err(format_structured_error(
                    "PYTHON_INTERPRETER_NOT_FOUND",
                    "Nenhum interpretador Python 3 funcional foi localizado no sistema",
                    serde_json::json!({ "erro": e }),
                ));
            }
        };

        let mut cmd = Command::new(&python_bin);
        cmd.env("PYTHONDONTWRITEBYTECODE", "1");

        // Define diretório de trabalho onde o script reside e configura PYTHONPATH
        if let Some(parent) = path.parent() {
            cmd.current_dir(parent);
            let mut py_path_parts = vec![parent.to_string_lossy().to_string()];
            let vendor_dir = parent.join("vendor");
            if vendor_dir.is_dir() {
                py_path_parts.push(vendor_dir.to_string_lossy().to_string());
            }
            if let Ok(existing) = std::env::var("PYTHONPATH") {
                if !existing.is_empty() {
                    py_path_parts.push(existing);
                }
            }
            cmd.env("PYTHONPATH", py_path_parts.join(":"));
        }

        if let Ok(current_path) = std::env::var("PATH") {
            let parts: Vec<&str> = current_path.split(':').collect();
            let mut new_parts = Vec::new();
            for p in &["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"] {
                if !parts.contains(p) {
                    new_parts.push(*p);
                }
            }
            if !new_parts.is_empty() {
                let full_path = format!("{}:{}", new_parts.join(":"), current_path);
                cmd.env("PATH", full_path);
            }
        }

        cmd.arg(&path);
        for a in args {
            cmd.arg(a);
        }

        cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

        let mut child = cmd.spawn().map_err(|e| {
            format_structured_error(
                "PROCESS_SPAWN_FAILED",
                &format!("Falha ao iniciar processo Python para '{}': {}", script, e),
                serde_json::json!({ "script": script, "erro": e.to_string() }),
            )
        })?;

        let stdout_pipe = child.stdout.take();
        let stderr_pipe = child.stderr.take();

        let out_thread = std::thread::spawn(move || {
            let mut out = String::new();
            if let Some(p) = stdout_pipe {
                let r = BufReader::new(p);
                for line in r.lines().flatten() {
                    if !out.is_empty() { out.push('\n'); }
                    out.push_str(&line);
                }
            }
            out
        });

        let err_thread = std::thread::spawn(move || {
            let mut err = String::new();
            if let Some(p) = stderr_pipe {
                let r = BufReader::new(p);
                for line in r.lines().flatten() {
                    if !err.is_empty() { err.push('\n'); }
                    err.push_str(&line);
                }
            }
            err
        });

        let timeout = Duration::from_secs(120);
        let start_time = std::time::Instant::now();
        let exit_status = loop {
            match child.try_wait() {
                Ok(Some(status)) => {
                    break status;
                }
                Ok(None) => {
                    if start_time.elapsed() > timeout {
                        let _ = child.kill();
                        let _ = child.wait();
                        let _ = out_thread.join();
                        let _ = err_thread.join();
                        return Err(format_structured_error(
                            "PYTHON_TIMEOUT",
                            &format!("Tempo limite de 120s excedido ao executar {}", script),
                            serde_json::json!({ "script": script, "timeout_seconds": 120 }),
                        ));
                    }
                    std::thread::sleep(Duration::from_millis(50));
                }
                Err(e) => {
                    let _ = child.kill();
                    let _ = out_thread.join();
                    let _ = err_thread.join();
                    return Err(format_structured_error(
                        "PROCESS_WAIT_ERROR",
                        &format!("Erro ao monitorar subprocesso Python {}: {}", script, e),
                        serde_json::json!({ "script": script, "erro": e.to_string() }),
                    ));
                }
            }
        };

        let stdout = out_thread.join().unwrap_or_default();
        let stderr = err_thread.join().unwrap_or_default();
        let status = exit_status;

        if !status.success() {
            let code = status.code().unwrap_or(-1);
            if let Some(json_val) = try_parse_json(&stdout) {
                if json_val.is_object() {
                    return Ok(json_val.to_string());
                }
            }
            return Err(format_structured_error(
                "PYTHON_EXECUTION_FAILED",
                &format!("O módulo Python '{}' encerrou com falha (código {})", script, code),
                serde_json::json!({
                    "script": script,
                    "exit_code": code,
                    "stderr": stderr.trim(),
                    "stdout": stdout.trim()
                }),
            ));
        }

        if let Some(json_val) = try_parse_json(&stdout) {
            return Ok(json_val.to_string());
        }

        Err(format_structured_error(
            "INVALID_JSON_RESPONSE",
            &format!("O módulo Python '{}' concluiu mas não retornou um JSON válido", script),
            serde_json::json!({
                "script": script,
                "stdout": stdout.trim(),
                "stderr": stderr.trim()
            }),
        ))
    }

    /// Duplicados multi-pasta, com progresso emitido em "duplicates-progress".
    #[tauri::command]
    pub async fn scan_duplicates_multi(
        app: AppHandle,
        window: Window,
        roots: Vec<String>,
        include_serato_path: Option<String>,
    ) -> Result<String, String> {
        let script = find_canonical_python_script(Some(&app), "duplicates_tool.py")?;
        let python_bin = find_python_binary()?;
        let mut cmd = Command::new(&python_bin);
        cmd.env("PYTHONDONTWRITEBYTECODE", "1");
        cmd.arg(&script).arg("--roots");
        for r in &roots {
            cmd.arg(r);
        }
        if let Some(s) = include_serato_path {
            if !s.trim().is_empty() {
                cmd.arg("--include-serato").arg(s);
            }
        }
        cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

        let mut child = cmd.spawn().map_err(|e| format!("Falha ao iniciar análise de duplicados: {}", e))?;
        let stdout = child.stdout.take();
        let stderr = child.stderr.take();

        let window_clone = window.clone();
        let stdout_thread = std::thread::spawn(move || {
            let mut final_json = String::new();
            if let Some(out) = stdout {
                for line_res in BufReader::new(out).lines() {
                    if let Ok(line) = line_res {
                        let t = line.trim().to_string();
                        if t.starts_with('{') {
                            if t.contains("\"tipo\": \"progresso\"") {
                                let _ = window_clone.emit("duplicates-progress", &t);
                            } else {
                                final_json = t;
                            }
                        }
                    }
                }
            }
            final_json
        });

        let stderr_thread = std::thread::spawn(move || {
            let mut err_str = String::new();
            if let Some(err) = stderr {
                for line_res in BufReader::new(err).lines() {
                    if let Ok(line) = line_res {
                        if !err_str.is_empty() {
                            err_str.push('\n');
                        }
                        err_str.push_str(&line);
                    }
                }
            }
            err_str
        });

        let final_json = stdout_thread.join().unwrap_or_default();
        let err_output = stderr_thread.join().unwrap_or_default();
        let status = child.wait().map_err(|e| format!("Falha ao aguardar duplicados: {}", e))?;

        if !status.success() && final_json.is_empty() {
            let msg = if err_output.trim().is_empty() {
                "Erro na execução da análise de duplicados".to_string()
            } else {
                err_output
            };
            return Err(msg);
        }
        Ok(final_json)
    }

    #[tauri::command]
    pub async fn duplicates_move_paths(
        app: AppHandle,
        paths: Vec<String>,
        destination: String,
    ) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "mover arquivos da biblioteca")?;
        let mut args: Vec<String> = vec!["--move".into()];
        args.extend(paths);
        args.push("--destination".into());
        args.push(destination);
        run_py_json(&app, "duplicates_tool.py", &args)
    }

    #[tauri::command]
    pub async fn duplicates_trash_paths(
        app: AppHandle,
        paths: Vec<String>,
    ) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "mover arquivos para a lixeira")?;
        let mut args: Vec<String> = vec!["--trash".into()];
        args.extend(paths);
        run_py_json(&app, "duplicates_tool.py", &args)
    }

    #[tauri::command]
    pub async fn crate_add_paths(
        app: AppHandle,
        serato_path: String,
        crate_name: String,
        paths: Vec<String>,
    ) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "gravar em uma crate")?;
        let mut args: Vec<String> = vec![
            "--serato".into(), serato_path,
            "--crate".into(), crate_name,
            "--paths".into(),
        ];
        args.extend(paths);
        run_py_json(&app, "crate_ops.py", &args)
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
        let _guard = if write {
            Some(bloqueio_serato_e_concorrencia(Some(&app), "gravar BPM e tom nas tags")?)
        } else {
            None
        };
        let script = find_canonical_python_script(Some(&app), "music_analysis.py")?;
        let python_bin = find_python_binary()?;
        let mut cmd = Command::new(&python_bin);
        cmd.env("PYTHONDONTWRITEBYTECODE", "1");
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

        // Drenagem concorrente de STDERR para prevenir DEADLOCK de pipe buffer do SO
        let stderr_pipe = child.stderr.take();
        let err_drain_thread = std::thread::spawn(move || {
            let mut captured_err = String::new();
            if let Some(pipe) = stderr_pipe {
                let r = BufReader::new(pipe);
                for line in r.lines().flatten() {
                    if !captured_err.is_empty() {
                        captured_err.push('\n');
                    }
                    captured_err.push_str(&line);
                }
            }
            captured_err
        });

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

        let stderr_output = err_drain_thread.join().unwrap_or_default();
        let status = child.wait().map_err(|e| format!("Falha ao aguardar análise: {}", e))?;
        if !status.success() {
            let msg = if !stderr_output.trim().is_empty() {
                format!("Falha na execução da análise de BPM/tom: {}", stderr_output)
            } else {
                format!("Processo de análise encerrou com código anômalo {:?}", status.code())
            };
            return Err(msg);
        }
        if final_json.is_empty() {
            return Err("Nenhum resultado retornado pelo processo de análise de BPM/tom".into());
        }
        Ok(final_json)
    }

    #[tauri::command]
    pub async fn list_journal(app: AppHandle, limit: usize) -> Result<String, String> {
        run_py_json(&app, "journal.py", &["--list".into(), "--limit".into(), limit.to_string()])
    }

    #[tauri::command]
    pub async fn undo_journal(app: AppHandle, op_id: Option<i64>) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "desfazer alterações de tags")?;
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
    pub async fn export_html_report(app: AppHandle, mp3_path: String, serato_path: String) -> Result<String, String> {
        run_py_json(&app, "library_tools.py", &[
            "--export-html-report".into(), "--mp3".into(), mp3_path, "--serato".into(), serato_path,
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
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "criar uma crate")?;
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
        let _guard = if !dry_run {
            Some(bloqueio_serato_e_concorrencia(Some(&app), "criar uma crate inteligente")?)
        } else {
            None
        };
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
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "regenerar crates inteligentes")?;
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
        let mut cmd = find_python_cmd(Some(&app), "sound_seal.py")?;
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
        let mut cmd = find_python_cmd(Some(&app), "sound_seal.py")?;
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
        let mut cmd = find_python_cmd(Some(&app), "sound_seal.py")?;
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
        let mut cmd = find_python_cmd(Some(&app), "sound_seal.py")?;
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
        let mut cmd = find_python_cmd(Some(&app), "sound_seal.py")?;
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
        let mut cmd = find_python_cmd(Some(&app), "sound_seal.py")?;
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
        let mut cmd = find_python_cmd(Some(&app), "sound_seal.py")?;
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
        let guard = bloqueio_serato_e_concorrencia(Some(&app), "religar faixas ausentes em lote")?;
        let script = find_canonical_python_script(Some(&app), "sound_seal.py")?;
        let python_bin = find_python_binary()?;
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let _guard = guard;
            let mut cmd = make_python_cmd(&script, &python_bin);
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
        let mut cmd = find_python_cmd(Some(&app), "sound_seal.py")?;
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
        window: Window,
        input_type: String,
        input_data: String,
        mp3_path: String,
        serato_path: String,
        export_crate: Option<String>,
    ) -> Result<String, String> {
        let mut cmd = find_python_cmd(Some(&app), "track_matcher.py")?;
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

        cmd.stdout(Stdio::piped()).stderr(Stdio::piped());
        let mut child = cmd.spawn().map_err(|e| format!("Falha no Track Matcher: {}", e))?;

        let mut final_json = String::new();
        if let Some(stdout) = child.stdout.take() {
            for line_res in BufReader::new(stdout).lines() {
                if let Ok(line) = line_res {
                    let trimmed = line.trim().to_string();
                    if !trimmed.starts_with('{') {
                        continue;
                    }
                    // Progresso é repassado à interface; a última linha é o resultado
                    let _ = window.emit("match-progress", &trimmed);
                    final_json = trimmed;
                }
            }
        }
        let _ = child.wait();
        if final_json.is_empty() {
            return Err("Track Matcher não retornou resultado".into());
        }
        Ok(final_json)
    }

    #[tauri::command]
    pub async fn replace_upgrades_track_matcher(
        app: AppHandle,
        upgrades_json: String,
    ) -> Result<String, String> {
        let mut cmd = find_python_cmd(Some(&app), "track_matcher.py")?;
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
        let mut cmd = find_python_cmd(Some(&app), "track_matcher.py")?;
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
        let mut cmd = find_python_cmd(Some(&app), "audio_health.py")?;
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
    pub async fn get_audio_spectrogram(app: AppHandle, filepath: String) -> Result<String, String> {
        let mut cmd = find_python_cmd(Some(&app), "audio_health.py")?;
        cmd.arg("--spectrogram");
        cmd.arg(&filepath);

        let output = cmd.output().map_err(|e| format!("Falha ao gerar espectrograma: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        if !output.status.success() {
            return Err(stdout);
        }
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn resample_track_local(app: AppHandle, filepath: String) -> Result<String, String> {
        let mut cmd = find_python_cmd(Some(&app), "audio_health.py")?;
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
        let guard = bloqueio_serato_e_concorrencia(Some(&app), "normalizar frequência de áudio em lote")?;
        let script = find_canonical_python_script(Some(&app), "audio_health.py")?;
        let python_bin = find_python_binary()?;
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let _guard = guard;
            let mut cmd = make_python_cmd(&script, &python_bin);
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
    pub async fn repair_track_online(app: AppHandle, filepath: String, serato_dir: Option<String>) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "reparar faixa online")?;
        let mut cmd = find_python_cmd(Some(&app), "audio_health.py")?;
        let (tx, rx) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let _guard = _guard;
            cmd.arg("--repair-online");
            cmd.arg(&filepath);
            if let Some(ref s_dir) = serato_dir {
                if !s_dir.trim().is_empty() {
                    cmd.arg("--serato");
                    cmd.arg(s_dir);
                }
            }

            let res = match cmd.output() {
                Ok(output) => {
                    let stdout_str = String::from_utf8_lossy(&output.stdout).to_string();
                    let stderr_str = String::from_utf8_lossy(&output.stderr).to_string();
                    if !output.status.success() && stdout_str.trim().is_empty() {
                        Err(format!(
                            "Processo de reparação falhou (código {:?}): {}",
                            output.status.code(),
                            stderr_str
                        ))
                    } else {
                        Ok(stdout_str)
                    }
                }
                Err(e) => Err(format!("Falha ao executar motor de reparação: {}", e)),
            };
            let _ = tx.send(res);
        });

        rx.recv()
            .map_err(|e| format!("Falha na execução em background da tarefa de reparação: {}", e))?
    }

    #[tauri::command]
    pub async fn batch_repair_online(
        app: AppHandle,
        window: Window,
        filepaths_json: String,
        serato_dir: Option<String>,
    ) -> Result<(), String> {
        let guard = bloqueio_serato_e_concorrencia(Some(&app), "reparar faixas online em lote")?;
        let script = find_canonical_python_script(Some(&app), "audio_health.py")?;
        let python_bin = find_python_binary()?;
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let _guard = guard;
            let mut cmd = make_python_cmd(&script, &python_bin);
            cmd.arg("--batch-repair-online");
            cmd.arg(&filepaths_json);
            if let Some(ref s_dir) = serato_dir {
                if !s_dir.trim().is_empty() {
                    cmd.arg("--serato");
                    cmd.arg(s_dir);
                }
            }
            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            let mut child = match cmd.spawn() {
                Ok(c) => c,
                Err(e) => {
                    let _ = window_clone.emit("audio-health-batch-finished", serde_json::json!({
                        "tipo": "fim",
                        "sucesso": false,
                        "erro": e.to_string(),
                        "total": 0,
                        "atualizados": 0,
                        "erros": [e.to_string()]
                    }));
                    return;
                }
            };

            // Drenagem concorrente de STDERR para prevenir DEADLOCK de pipe cheio
            let stderr_pipe = child.stderr.take();
            let err_drain_thread = std::thread::spawn(move || {
                let mut captured_err = String::new();
                if let Some(pipe) = stderr_pipe {
                    let r = BufReader::new(pipe);
                    for line in r.lines().flatten() {
                        if !captured_err.is_empty() {
                            captured_err.push('\n');
                        }
                        captured_err.push_str(&line);
                    }
                }
                captured_err
            });

            let mut finished_emitted = false;
            if let Some(stdout) = child.stdout.take() {
                let reader = BufReader::new(stdout);
                for line_res in reader.lines().flatten() {
                    if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&line_res) {
                        let tipo = parsed.get("tipo").and_then(|t| t.as_str()).unwrap_or("");
                        if tipo == "progresso" {
                            let _ = window_clone.emit("audio-health-batch-progress", parsed);
                        } else if tipo == "fim" {
                            let _ = window_clone.emit("audio-health-batch-finished", parsed);
                            finished_emitted = true;
                        }
                    }
                }
            }

            let stderr_output = err_drain_thread.join().unwrap_or_default();
            let exit_status = child.wait();
            let success = exit_status.as_ref().map(|s| s.success()).unwrap_or(false);

            if !success && !finished_emitted {
                let err_msg = if !stderr_output.trim().is_empty() {
                    stderr_output
                } else {
                    format!("Processo Python encerrou com status {:?}", exit_status)
                };
                let _ = window_clone.emit("audio-health-batch-finished", serde_json::json!({
                    "tipo": "fim",
                    "sucesso": false,
                    "erro": err_msg,
                    "total": 0,
                    "atualizados": 0,
                    "erros": [err_msg]
                }));
            }
        });

        Ok(())
    }

    #[tauri::command]
    pub async fn preaudit_track_online(app: AppHandle, filepath: String) -> Result<String, String> {
        let mut cmd = find_python_cmd(Some(&app), "audio_health.py")?;
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
        let script = find_canonical_python_script(Some(&app), "audio_health.py")?;
        let python_bin = find_python_binary()?;
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let mut cmd = make_python_cmd(&script, &python_bin);
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
        let mut cmd = find_python_cmd(Some(&app), "audio_health.py")?;
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
        let mut cmd = find_python_cmd(Some(&app), "auto_cue.py")?;
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
        let mut cmd = find_python_cmd(Some(&app), "auto_cue.py")?;
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
        let mut cmd = find_python_cmd(Some(&app), "auto_cue.py")?;
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
        let guard = bloqueio_serato_e_concorrencia(Some(&app), "aplicar Hot Cues na crate")?;
        let script = find_canonical_python_script(Some(&app), "auto_cue.py")?;
        let python_bin = find_python_binary()?;
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let _guard = guard;
            let mut cmd = make_python_cmd(&script, &python_bin);
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
        let guard = bloqueio_serato_e_concorrencia(Some(&app), "reparar Hot Cues na crate")?;
        let script = find_canonical_python_script(Some(&app), "auto_cue.py")?;
        let python_bin = find_python_binary()?;
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let _guard = guard;
            let mut cmd = make_python_cmd(&script, &python_bin);
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
        let mut cmd = find_python_cmd(Some(&app), "auto_cue.py")?;
        cmd.arg("--apply-batch");
        cmd.arg(&filepaths_json);

        let output = cmd.output().map_err(|e| format!("Falha ao aplicar lote de Hot Cues: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        if !output.status.success() {
            return Err(stdout);
        }
        Ok(stdout)
    }

    #[tauri::command]
    pub async fn watch_music_folder(
        app: AppHandle,
        folder_path: String,
        state: tauri::State<'_, FsWatcherState>,
    ) -> Result<bool, String> {
        let path = PathBuf::from(&folder_path);
        if !path.exists() || !path.is_dir() {
            return Err("Diretório especificado para monitoramento não existe ou é inválido.".into());
        }

        // Se já está monitorando exatamente esta pasta, não precisa recriar
        {
            let current = state.active_path.lock().map_err(|e| e.to_string())?;
            if let Some(ref p) = *current {
                if p == &folder_path {
                    return Ok(true);
                }
            }
        }

        let app_handle = app.clone();
        let folder_for_event = folder_path.clone();

        // Canal de eventos do notify
        let (tx, rx) = channel();

        let mut watcher = RecommendedWatcher::new(
            move |res| {
                let _ = tx.send(res);
            },
            Config::default().with_poll_interval(Duration::from_secs(2)),
        ).map_err(|e| format!("Falha ao instanciar watcher FSEvents: {}", e))?;

        watcher
            .watch(&path, RecursiveMode::Recursive)
            .map_err(|e| format!("Falha ao iniciar escuta na pasta: {}", e))?;

        // Atualiza estado do watcher
        {
            let mut w_lock = state.watcher.lock().map_err(|e| e.to_string())?;
            *w_lock = Some(watcher);

            let mut p_lock = state.active_path.lock().map_err(|e| e.to_string())?;
            *p_lock = Some(folder_path);
        }

        // Thread desacoplada com debounce para processar alterações em segundo plano
        std::thread::spawn(move || {
            let valid_exts = ["mp3", "wav", "aiff", "aif", "flac", "m4a", "aac"];
            let mut pending_files: Vec<String> = Vec::new();
            let mut last_event_time = std::time::Instant::now();

            loop {
                match rx.recv_timeout(Duration::from_millis(500)) {
                    Ok(Ok(event)) => {
                        for path in event.paths {
                            if let Some(ext) = path.extension().and_then(|e| e.to_str()) {
                                let ext_lower = ext.to_lowercase();
                                if valid_exts.contains(&ext_lower.as_str()) {
                                    pending_files.push(path.to_string_lossy().to_string());
                                }
                            }
                        }
                        last_event_time = std::time::Instant::now();
                    }
                    Ok(Err(_)) => {}
                    Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                        // Se acumulou arquivos e passou pelo menos 1.5s de silêncio, emite o debounce para o front
                        if !pending_files.is_empty() && last_event_time.elapsed() >= Duration::from_millis(1500) {
                            let mut unique_exts: Vec<String> = Vec::new();
                            for f in &pending_files {
                                if let Some(ext) = Path::new(f).extension().and_then(|e| e.to_str()) {
                                    let ext_upper = ext.to_uppercase();
                                    if !unique_exts.contains(&ext_upper) {
                                        unique_exts.push(ext_upper);
                                    }
                                }
                            }

                            let payload = FsChangeEvent {
                                folder: folder_for_event.clone(),
                                count: pending_files.len(),
                                extensions: unique_exts,
                            };

                            let _ = app_handle.emit("fs-changes-detected", payload);
                            pending_files.clear();
                        }
                    }
                    Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                        break;
                    }
                }
            }
        });

        Ok(true)
    }

    #[tauri::command]
    pub async fn stop_watching_folder(state: tauri::State<'_, FsWatcherState>) -> Result<bool, String> {
        let mut w_lock = state.watcher.lock().map_err(|e| e.to_string())?;
        *w_lock = None;

        let mut p_lock = state.active_path.lock().map_err(|e| e.to_string())?;
        *p_lock = None;

        Ok(true)
    }

    #[tauri::command]
    pub fn set_operation_active(state: tauri::State<'_, AppSecurityState>, active: bool) {
        state.is_ui_busy.store(active, Ordering::SeqCst);
    }

    #[tauri::command]
    pub fn is_operation_active(state: tauri::State<'_, AppSecurityState>) -> bool {
        state.is_operation_active.load(Ordering::SeqCst) || state.is_ui_busy.load(Ordering::SeqCst)
    }

    #[tauri::command]
    pub async fn audit_serato_v4(app: AppHandle, library_path: Option<String>) -> Result<String, String> {
        let mut args = vec!["--audit".into(), "--json".into()];
        if let Some(p) = library_path {
            if !p.trim().is_empty() {
                args.push("--dir".into());
                args.push(p);
            }
        }
        run_py_json(&app, "serato_v4_engine.py", &args)
    }

    #[tauri::command]
    pub async fn extract_apple_music_library(app: AppHandle) -> Result<String, String> {
        run_py_json(&app, "music_library_helper.py", &["--json".into()])
    }

    #[tauri::command]
    pub async fn search_fts_library(app: AppHandle, query: String, limit: Option<i32>) -> Result<String, String> {
        let lim = limit.unwrap_or(40).to_string();
        run_py_json(&app, "fts_library_cache.py", &[
            "--search".into(), query,
            "--limit".into(), lim
        ])
    }

    #[tauri::command]
    pub async fn sync_fts_library(app: AppHandle, mp3_path: String) -> Result<String, String> {
        run_py_json(&app, "fts_library_cache.py", &[
            "--sync".into(), mp3_path
        ])
    }

    #[tauri::command]
    pub async fn load_saved_summary(logs_dir: Option<String>) -> Result<Option<String>, String> {
        let mut candidates = Vec::new();
        if let Some(ref l) = logs_dir {
            let p = PathBuf::from(l);
            candidates.push(p.join(".serato_sync_summary.json"));
            candidates.push(p.join("logs").join(".serato_sync_summary.json"));
        }
        if let Some(home) = dirs_home() {
            candidates.push(home.join("SeratoSync").join("logs").join(".serato_sync_summary.json"));
            candidates.push(home.join(".serato_sync_summary.json"));
        }
        candidates.push(PathBuf::from("/Users/pastteur/SeratoSync/logs/.serato_sync_summary.json"));

        for candidate in candidates {
            if candidate.exists() && candidate.is_file() {
                if let Ok(content) = std::fs::read_to_string(&candidate) {
                    if !content.trim().is_empty() {
                        return Ok(Some(content));
                    }
                }
            }
        }
        Ok(None)
    }

    #[tauri::command]
    pub async fn load_crates_from_disk(app: AppHandle, serato_path: String) -> Result<String, String> {
        let clean = serato_path.trim().to_string();
        if clean.is_empty() {
            return Err("Caminho do Serato inválido".into());
        }
        run_py_json(&app, "crate_ops.py", &[
            "--list-tree".into(),
            "--serato".into(), clean,
        ])
    }

    #[tauri::command]
    pub async fn export_pioneer_usb(
        app: AppHandle,
        usb_path: String,
        crate_name: String,
        tracks_json: String,
        copy_audio: bool,
        dry_run: bool
    ) -> Result<String, String> {
        let _guard = if !dry_run {
            Some(bloqueio_serato_e_concorrencia(Some(&app), "exportar biblioteca para pendrive Pioneer")?)
        } else {
            None
        };
        // Grava tracks_json em arquivo temporário para evitar estouro de buffer de linha de comando
        let temp_dir = std::env::temp_dir();
        let temp_file = temp_dir.join(format!("pioneer_tracks_{}.json", std::process::id()));
        std::fs::write(&temp_file, tracks_json).map_err(|e| format!("Falha ao gravar arquivo temporário: {}", e))?;

        let mut args = vec![
            "--usb".into(), usb_path,
            "--crate".into(), crate_name,
            "--tracks".into(), temp_file.to_string_lossy().to_string()
        ];
        if !copy_audio {
            args.push("--no-copy".into());
        }
        if dry_run {
            args.push("--dry-run".into());
        }

        let res = run_py_json(&app, "pioneer_usb_exporter.py", &args);
        let _ = std::fs::remove_file(temp_file);
        res
    }

    #[tauri::command]
    pub async fn scan_unused_files(app: AppHandle, mp3_path: String, serato_path: String) -> Result<String, String> {
        run_py_json(&app, "scan_unused_files.py", &[
            "--mp3".into(), mp3_path,
            "--serato".into(), serato_path,
            "--json".into()
        ])
    }

    #[tauri::command]
    pub async fn quarantine_orphan_files(
        app: AppHandle,
        mp3_path: String,
        serato_path: String,
        files: Vec<String>,
        dest: Option<String>,
    ) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "mover arquivos órfãos para quarentena")?;
        let mut args: Vec<String> = vec![
            "--mp3".into(), mp3_path,
            "--serato".into(), serato_path,
            "--quarantine".into(),
        ];
        if let Some(d) = dest {
            if !d.trim().is_empty() {
                args.push("--dest".into());
                args.push(d);
            }
        }
        if !files.is_empty() {
            args.push("--files".into());
            args.extend(files);
        }
        run_py_json(&app, "scan_unused_files.py", &args)
    }

    #[tauri::command]
    pub async fn scan_beatshift(app: AppHandle, filepath: String) -> Result<String, String> {
        run_py_json(&app, "beatshift_scanner.py", &[
            "--file".into(), filepath,
            "--json".into()
        ])
    }

    #[tauri::command]
    pub async fn convert_key(app: AppHandle, key_str: String, target_format: String) -> Result<String, String> {
        run_py_json(&app, "key_converter.py", &[
            "--key".into(), key_str,
            "--to".into(), target_format
        ])
    }

    #[tauri::command]
    pub async fn clean_taxonomy_file(app: AppHandle, filepath: String, dry_run: bool) -> Result<String, String> {
        let _guard = if !dry_run {
            Some(bloqueio_serato_e_concorrencia(Some(&app), "limpar taxonomia do arquivo")?)
        } else {
            None
        };
        let mut args = vec!["--file".into(), filepath];
        if dry_run {
            args.push("--dry-run".into());
        }
        run_py_json(&app, "taxonomy_cleaner.py", &args)
    }

    #[tauri::command]
    pub async fn apply_recipe(
        app: AppHandle,
        recipe_name: String,
        files: Vec<String>,
        param: Option<String>
    ) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "aplicar receita de organização de tags")?;
        let mut args = vec!["--recipe".into(), recipe_name, "--files".into()];
        for f in files {
            args.push(f);
        }
        if let Some(p) = param {
            if !p.trim().is_empty() {
                args.push("--param".into());
                args.push(p);
            }
        }
        run_py_json(&app, "recipe_engine.py", &args)
    }

    #[tauri::command]
    pub async fn undo_recipe(app: AppHandle) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "desfazer receita de organização de tags")?;
        run_py_json(&app, "recipe_engine.py", &["--undo".into()])
    }

    #[tauri::command]
    pub async fn crate_playlist_tools(
        app: AppHandle,
        serato_path: String,
        action: String,
        crate_name: String,
        prefix: Option<String>,
        sort_mode: Option<String>,
        sources: Option<Vec<String>>,
        paths: Option<Vec<String>>,
        target: Option<String>,
    ) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "modificar ou reordenar crates")?;
        let mut args: Vec<String> = vec![
            "--action".into(), action,
            "--serato".into(), serato_path,
            "--crate".into(), crate_name,
        ];
        if let Some(pfx) = prefix {
            if !pfx.trim().is_empty() {
                args.push("--prefix".into());
                args.push(pfx);
            }
        }
        if let Some(sm) = sort_mode {
            args.push("--sort-mode".into());
            args.push(sm);
        }
        if let Some(tgt) = target {
            args.push("--target".into());
            args.push(tgt);
        }
        if let Some(srcs) = sources {
            if !srcs.is_empty() {
                args.push("--sources".into());
                args.extend(srcs);
            }
        }
        if let Some(pts) = paths {
            if !pts.is_empty() {
                args.push("--paths".into());
                args.extend(pts);
            }
        }
        run_py_json(&app, "crate_ops.py", &args)
    }

    #[tauri::command]
    pub async fn analyze_energy_batch(
        app: AppHandle,
        window: Window,
        mp3_path: String,
        limit: usize,
        write: bool,
        target_tag: String,
        serato_path: Option<String>,
        crate_name: Option<String>,
    ) -> Result<String, String> {
        let _guard = if write {
            Some(bloqueio_serato_e_concorrencia(Some(&app), "gravar Energy nas tags")?)
        } else {
            None
        };
        let script = find_canonical_python_script(Some(&app), "music_analysis.py")?;
        let python_bin = find_python_binary()?;
        let mut cmd = Command::new(&python_bin);
        cmd.env("PYTHONDONTWRITEBYTECODE", "1");
        cmd.arg(&script).arg("--energy-batch").arg(&mp3_path);
        cmd.arg("--limit").arg(limit.to_string());
        cmd.arg("--target-tag").arg(target_tag);
        if let (Some(sp), Some(cn)) = (serato_path, crate_name) {
            if !sp.trim().is_empty() && !cn.trim().is_empty() {
                cmd.arg("--serato").arg(sp.trim());
                cmd.arg("--crate").arg(cn.trim());
            }
        }
        if write {
            cmd.arg("--write");
        }
        cmd.stdout(Stdio::piped()).stderr(Stdio::piped());

        let mut child = cmd.spawn().map_err(|e| format!("Falha ao iniciar análise de energia: {}", e))?;
        let stderr_pipe = child.stderr.take();
        let err_drain = std::thread::spawn(move || {
            let mut s = String::new();
            if let Some(pipe) = stderr_pipe {
                for line in BufReader::new(pipe).lines().flatten() {
                    if !s.is_empty() { s.push('\n'); }
                    s.push_str(&line);
                }
            }
            s
        });

        let mut final_json = String::new();
        if let Some(stdout) = child.stdout.take() {
            for line_res in BufReader::new(stdout).lines() {
                if let Ok(line) = line_res {
                    let trimmed = line.trim();
                    if trimmed.starts_with('{') {
                        if trimmed.contains("\"tipo\": \"progresso\"") || trimmed.contains("\"tipo\":\"progresso\"") {
                            let _ = window.emit("energy-progress", trimmed);
                        } else if trimmed.contains("\"tipo\": \"fim\"") || trimmed.contains("\"tipo\":\"fim\"") {
                            final_json = trimmed.to_string();
                        }
                    }
                }
            }
        }
        let _ = child.wait();
        let _ = err_drain.join();
        if final_json.is_empty() {
            Ok("{\"sucesso\": true}".into())
        } else {
            Ok(final_json)
        }
    }

    #[tauri::command]
    pub async fn generate_curated_set(
        app: AppHandle,
        serato_path: String,
        crate_name: String,
        profile: String,
        max_tracks: usize,
        start_track: Option<String>,
        commit: Option<bool>,
        exclude_incomplete: Option<bool>,
    ) -> Result<String, String> {
        let is_commit = commit.unwrap_or(false);
        let _guard = if is_commit {
            Some(bloqueio_serato_e_concorrencia(Some(&app), "gerar Crate curada no Serato")?)
        } else {
            None
        };
        let mut args: Vec<String> = vec![
            "--curate-set".into(),
            "--serato".into(), serato_path,
            "--crate".into(), crate_name,
            "--profile".into(), profile,
            "--max-tracks".into(), max_tracks.to_string(),
        ];
        if is_commit {
            args.push("--commit".into());
        }
        if exclude_incomplete.unwrap_or(false) {
            args.push("--exclude-incomplete".into());
        }
        if let Some(st) = start_track {
            if !st.trim().is_empty() {
                args.push("--start-track".into());
                args.push(st);
            }
        }
        run_py_json(&app, "music_analysis.py", &args)
    }

    #[tauri::command]
    pub async fn get_deckwatch(app: AppHandle, serato_path: Option<String>) -> Result<String, String> {
        let mut args = vec!["--json".into()];
        if let Some(p) = serato_path {
            if !p.trim().is_empty() {
                args.push("--serato".into());
                args.push(p);
            }
        }
        run_py_json(&app, "deckwatch_monitor.py", &args)
    }

    #[tauri::command]
    pub async fn update_mytags(
        app: AppHandle,
        filepath: String,
        add_tags: Vec<String>,
        remove_tags: Vec<String>
    ) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "atualizar MyTags nas faixas")?;
        let mut args = vec!["--file".into(), filepath];
        if !add_tags.is_empty() {
            args.push("--add".into());
            for t in add_tags {
                args.push(t);
            }
        }
        if !remove_tags.is_empty() {
            args.push("--remove".into());
            for t in remove_tags {
                args.push(t);
            }
        }
        run_py_json(&app, "smart_tags.py", &args)
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let security_state = AppSecurityState::new();
    let is_op_active_clone = security_state.is_operation_active.clone();
    let is_ui_busy_clone = security_state.is_ui_busy.clone();

    tauri::Builder::default()
        .manage(FsWatcherState::new())
        .manage(security_state)
        .plugin(tauri_plugin_dialog::init())
        .on_window_event(move |window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if is_op_active_clone.load(Ordering::SeqCst) || is_ui_busy_clone.load(Ordering::SeqCst) {
                    api.prevent_close();
                    let _ = window.emit("operation-in-progress-warning", "⚠️ Uma atividade de sincronização ou gravação na biblioteca está em andamento. Aguarde a finalização antes de fechar o aplicativo para evitar corrupção de dados.");
                }
            }
        })
        .setup(|app| {
            let app_handle = app.handle().clone();

            // Watcher nativo em segundo plano para monitorar hot-plug de volumes (/Volumes)
            std::thread::spawn(move || {
                let volumes_path = PathBuf::from("/Volumes");
                if volumes_path.exists() {
                    let (tx, rx) = channel();
                    if let Ok(mut watcher) = RecommendedWatcher::new(
                        move |res| {
                            let _ = tx.send(res);
                        },
                        Config::default().with_poll_interval(Duration::from_secs(2)),
                    ) {
                        if watcher.watch(&volumes_path, RecursiveMode::NonRecursive).is_ok() {
                            let mut last_trigger = std::time::Instant::now();
                            while let Ok(_) = rx.recv() {
                                // Debounce de 1 segundo para estabilizar a montagem do volume
                                if last_trigger.elapsed() >= Duration::from_secs(1) {
                                    last_trigger = std::time::Instant::now();
                                    std::thread::sleep(Duration::from_millis(800));
                                    let _ = app_handle.emit("volumes-changed", ());
                                }
                            }
                        }
                    }
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_system_telemetry,
            commands::get_detected_paths,
            commands::validate_path,
            commands::start_sync,
            commands::open_in_finder,
            commands::open_file_in_finder,
            commands::open_in_browser,
            commands::save_text_file,
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
            commands::get_audio_spectrogram,
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
            commands::export_html_report,
            commands::export_crate_m3u,
            commands::import_m3u_crate,
            commands::smart_crate_create,
            commands::smart_crate_refresh,
            commands::smart_crate_list,
            commands::smart_crate_delete,
            commands::scan_new_tracks,
            commands::scan_duplicates_multi,
            commands::duplicates_move_paths,
            commands::duplicates_trash_paths,
            commands::crate_add_paths,
            commands::watch_music_folder,
            commands::stop_watching_folder,
            commands::detect_dj_volumes,
            commands::set_operation_active,
            commands::is_operation_active,
            commands::audit_serato_v4,
            commands::extract_apple_music_library,
            commands::search_fts_library,
            commands::sync_fts_library,
            commands::load_saved_summary,
            commands::load_crates_from_disk,
            commands::export_pioneer_usb,
            commands::scan_unused_files,
            commands::quarantine_orphan_files,
            commands::scan_beatshift,
            commands::convert_key,
            commands::clean_taxonomy_file,
            commands::apply_recipe,
            commands::undo_recipe,
            commands::crate_playlist_tools,
            commands::analyze_energy_batch,
            commands::generate_curated_set,
            commands::get_deckwatch,
            commands::update_mytags
        ])
        .run(tauri::generate_context!())
        .expect("erro ao inicializar aplicação tauri");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_operation_guard_concurrency_and_raii() {
        let state = AppSecurityState::new();
        assert!(!state.is_operation_active.load(Ordering::SeqCst));

        // 1. Primeira aquisição deve ser bem sucedida
        let guard1 = state.acquire_lock();
        assert!(guard1.is_ok());
        assert!(state.is_operation_active.load(Ordering::SeqCst));

        // 2. Aquisição concorrente deve ser bloqueada
        let guard2 = state.acquire_lock();
        assert!(guard2.is_err());
        assert!(guard2.unwrap_err().contains("Bloqueio de concorrência"));

        // 3. Liberação via drop do RAII Guard
        drop(guard1);
        assert!(!state.is_operation_active.load(Ordering::SeqCst));

        // 4. Nova aquisição após drop deve ser liberada imediatamente
        let guard3 = state.acquire_lock();
        assert!(guard3.is_ok());
        assert!(state.is_operation_active.load(Ordering::SeqCst));
    }

    #[test]
    fn test_structured_error_format() {
        let err_json = format_structured_error(
            "PYTHON_EXECUTION_FAILED",
            "Erro de execução do teste",
            serde_json::json!({ "script": "test.py", "exit_code": 1 }),
        );

        let parsed: serde_json::Value = serde_json::from_str(&err_json).expect("JSON inválido");
        assert_eq!(parsed["sucesso"], false);
        assert_eq!(parsed["codigo"], "PYTHON_EXECUTION_FAILED");
        assert_eq!(parsed["mensagem"], "Erro de execução do teste");
        assert_eq!(parsed["detalhes"]["script"], "test.py");
        assert_eq!(parsed["detalhes"]["exit_code"], 1);

        let op_id = parsed["operacao_id"].as_str().expect("operacao_id ausente");
        assert!(op_id.len() >= 16);
    }

    #[test]
    fn test_generate_unique_operacao_ids() {
        let id1 = generate_operacao_id();
        let id2 = generate_operacao_id();
        assert_ne!(id1, id2);
        assert!(id1.contains("-"));
        assert!(id2.contains("-"));
    }
}
