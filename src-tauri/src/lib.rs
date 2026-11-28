use std::io::{BufRead, BufReader, Read};
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

impl Default for AppSecurityState {
    fn default() -> Self {
        Self::new()
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

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
pub struct DetectedPaths {
    pub mp3: String,
    pub serato: String,
    pub same_volume: bool,
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

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
pub struct SyncFinishedPayload {
    pub success: bool,
    pub exit_code: Option<i32>,
    pub message: String,
    pub summary: Option<serde_json::Value>,
}

fn parse_sync_summary_line(line: &str) -> Option<serde_json::Value> {
    let json_str = line.strip_prefix("__PAYLOAD_JSON_SUMMARY__")?.trim();
    if json_str.is_empty() {
        return None;
    }
    serde_json::from_str::<serde_json::Value>(json_str).ok()
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

impl Default for FsWatcherState {
    fn default() -> Self {
        Self::new()
    }
}

fn dirs_home() -> Option<PathBuf> {
    std::env::var_os("HOME").map(PathBuf::from)
}

pub struct ApprovedSyncPlanState {
    pub current: Arc<Mutex<Option<(String, serde_json::Value)>>>,
}

impl ApprovedSyncPlanState {
    pub fn new() -> Self {
        Self {
            current: Arc::new(Mutex::new(None)),
        }
    }
}

impl Default for ApprovedSyncPlanState {
    fn default() -> Self {
        Self::new()
    }
}

/// Garante remoção automática de arquivo temporário ao sair de escopo por sucesso ou erro.
pub(crate) struct TempFileCleanup(Option<PathBuf>);

impl TempFileCleanup {
    pub(crate) fn new(path: PathBuf) -> Self {
        Self(Some(path))
    }

    pub(crate) fn disarm(&mut self) -> Option<PathBuf> {
        self.0.take()
    }
}

impl Drop for TempFileCleanup {
    fn drop(&mut self) {
        if let Some(p) = self.0.take() {
            let _ = std::fs::remove_file(p);
        }
    }
}

/// Calcula SHA-256 em streaming sem dependências externas (FIPS 180-4).
pub(crate) fn calculate_sha256(path: &Path) -> Result<[u8; 32], String> {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
    ];

    fn compress(state: &mut [u32; 8], block: &[u8; 64]) {
        let mut w = [0u32; 64];
        for (i, word) in w.iter_mut().enumerate().take(16) {
            let j = i * 4;
            *word = u32::from_be_bytes([block[j], block[j + 1], block[j + 2], block[j + 3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16].wrapping_add(s0).wrapping_add(w[i - 7]).wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = *state;
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let temp1 = h.wrapping_add(s1).wrapping_add(ch).wrapping_add(K[i]).wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = s0.wrapping_add(maj);

            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }
        state[0] = state[0].wrapping_add(a);
        state[1] = state[1].wrapping_add(b);
        state[2] = state[2].wrapping_add(c);
        state[3] = state[3].wrapping_add(d);
        state[4] = state[4].wrapping_add(e);
        state[5] = state[5].wrapping_add(f);
        state[6] = state[6].wrapping_add(g);
        state[7] = state[7].wrapping_add(h);
    }

    let file = std::fs::File::open(path)
        .map_err(|e| format!("Erro ao abrir '{}' para SHA-256: {}", path.display(), e))?;
    let mut reader = BufReader::with_capacity(64 * 1024, file);
    let mut state: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    ];
    let mut block = [0u8; 64];
    let mut block_len = 0usize;
    let mut total_len = 0u64;
    let mut buf = [0u8; 64 * 1024];

    loop {
        let n = reader
            .read(&mut buf)
            .map_err(|e| format!("Erro de leitura em '{}' para SHA-256: {}", path.display(), e))?;
        if n == 0 {
            break;
        }
        total_len = total_len.saturating_add(n as u64);
        let mut offset = 0usize;
        while offset < n {
            let take = (64 - block_len).min(n - offset);
            block[block_len..block_len + take].copy_from_slice(&buf[offset..offset + take]);
            block_len += take;
            offset += take;
            if block_len == 64 {
                compress(&mut state, &block);
                block_len = 0;
            }
        }
    }

    block[block_len] = 0x80;
    block_len += 1;
    if block_len > 56 {
        block[block_len..64].fill(0);
        compress(&mut state, &block);
        block_len = 0;
    }
    block[block_len..56].fill(0);
    let bit_len = total_len.wrapping_mul(8);
    block[56..64].copy_from_slice(&bit_len.to_be_bytes());
    compress(&mut state, &block);

    let mut out = [0u8; 32];
    for (idx, word) in state.iter().enumerate() {
        out[idx * 4..idx * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    Ok(out)
}

pub(crate) fn verify_file_copy(original: &Path, destination: &Path) -> Result<(), String> {
    let original_meta = std::fs::metadata(original)
        .map_err(|e| format!("Erro ao consultar original: {}", e))?;
    let copied_meta = std::fs::metadata(destination)
        .map_err(|e| format!("Erro ao consultar cópia: {}", e))?;

    if original_meta.len() != copied_meta.len() {
        return Err(format!(
            "Tamanho da cópia divergente (original={}, cópia={})",
            original_meta.len(),
            copied_meta.len()
        ));
    }

    let original_hash = calculate_sha256(original)?;
    let copied_hash = calculate_sha256(destination)?;
    if original_hash != copied_hash {
        return Err("SHA-256 da cópia divergente".to_string());
    }

    Ok(())
}

pub(crate) fn move_file_with_verified_fallback(
    file_path: &Path,
    dest: &Path,
    force_copy_fallback: bool,
) -> Result<(), String> {
    if !force_copy_fallback && std::fs::rename(file_path, dest).is_ok() {
        return Ok(());
    }

    if !file_path.exists() {
        return Err(format!("Arquivo original desapareceu antes da cópia: {}", file_path.display()));
    }

    if let Err(e) = std::fs::copy(file_path, dest) {
        let _ = std::fs::remove_file(dest);
        return Err(format!("Falha ao copiar arquivo para a lixeira '{}': {}", dest.display(), e));
    }

    if let Ok(f) = std::fs::File::open(dest) {
        if let Err(e) = f.sync_all() {
            let _ = std::fs::remove_file(dest);
            return Err(format!("Falha ao sincronizar cópia em disco '{}': {}", dest.display(), e));
        }
    }

    if let Err(err) = verify_file_copy(file_path, dest) {
        let _ = std::fs::remove_file(dest);
        return Err(format!("Verificação de integridade da cópia falhou (original preservado): {}", err));
    }

    std::fs::remove_file(file_path).map_err(|e| {
        format!(
            "Cópia íntegra criada em '{}', mas falhou ao remover original '{}': {}",
            dest.display(),
            file_path.display(),
            e
        )
    })
}

pub(crate) fn should_store_approved_plan(
    dry_run: bool,
    exit_success: bool,
    summary_val: Option<&serde_json::Value>,
) -> Option<String> {
    if !dry_run || !exit_success {
        return None;
    }
    let val = summary_val?;
    if val.get("sucesso").and_then(|v| v.as_bool()) != Some(true) {
        return None;
    }
    if val.get("dry_run").and_then(|v| v.as_bool()) != Some(true) {
        return None;
    }
    if val.get("status_analise").and_then(|v| v.as_str()) == Some("parcial_com_erros") {
        return None;
    }
    let pid = val.get("plan_id").and_then(|v| v.as_str())?.trim();
    if pid.is_empty() {
        return None;
    }
    let has_plan = val.get("plan").map(|p| p.is_object()).unwrap_or(false);
    if !has_plan {
        return None;
    }
    Some(pid.to_string())
}

#[derive(serde::Serialize)]
pub struct DependencyStatus {
    pub python_ok: bool,
    pub python_detail: String,
    pub ffmpeg_ok: bool,
    pub ffmpeg_path: Option<String>,
    pub ffprobe_ok: bool,
    pub ffprobe_path: Option<String>,
    pub yt_dlp_ok: bool,
    pub yt_dlp_path: Option<String>,
    pub warnings: Vec<String>,
}

fn collect_vendor_paths(app: Option<&AppHandle>, script: Option<&Path>) -> Vec<PathBuf> {
    let mut vendor_paths: Vec<PathBuf> = Vec::new();

    if let Ok(exe) = std::env::current_exe() {
        if let Some(macos_dir) = exe.parent() {
            if let Some(contents_dir) = macos_dir.parent() {
                let res_vendor = contents_dir.join("Resources").join("vendor");
                if res_vendor.is_dir() && !vendor_paths.contains(&res_vendor) {
                    vendor_paths.push(res_vendor);
                }
            }
        }
    }

    if let Some(handle) = app {
        if let Ok(res_dir) = handle.path().resource_dir() {
            let res_vendor = res_dir.join("vendor");
            if res_vendor.is_dir() && !vendor_paths.contains(&res_vendor) {
                vendor_paths.push(res_vendor);
            }
        }
    }

    if let Some(s) = script {
        if let Some(parent) = s.parent() {
            let script_vendor = parent.join("vendor");
            if script_vendor.is_dir() && !vendor_paths.contains(&script_vendor) {
                vendor_paths.push(script_vendor);
            }
        }
    }

    #[cfg(debug_assertions)]
    {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        if let Some(parent) = manifest_dir.parent() {
            let dev_vendor = parent.join("vendor");
            if dev_vendor.is_dir() && !vendor_paths.contains(&dev_vendor) {
                vendor_paths.push(dev_vendor);
            }
        }
    }

    vendor_paths
}

fn build_pythonpath_env(vendor_paths: &[PathBuf]) -> Option<String> {
    if vendor_paths.is_empty() {
        return None;
    }
    let mut py_path_parts: Vec<String> = vendor_paths
        .iter()
        .map(|p| p.to_string_lossy().to_string())
        .collect();

    if let Ok(existing) = std::env::var("PYTHONPATH") {
        if !existing.is_empty() {
            py_path_parts.push(existing);
        }
    }
    Some(py_path_parts.join(":"))
}

fn authorize_asset_directory(app: &AppHandle, dir_path: &str) {
    let clean = dir_path.trim();
    if clean.is_empty() {
        return;
    }
    let path = PathBuf::from(clean);
    if path.is_dir() {
        let _ = app.asset_protocol_scope().allow_directory(&path, true);
    }
}

fn find_external_binary(app: Option<&AppHandle>, name: &str) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Ok(exe) = std::env::current_exe() {
        if let Some(macos_dir) = exe.parent() {
            if let Some(contents_dir) = macos_dir.parent() {
                candidates.push(contents_dir.join("Resources").join("bin").join(name));
            }
        }
    }
    if let Some(handle) = app {
        if let Ok(res_dir) = handle.path().resource_dir() {
            candidates.push(res_dir.join("bin").join(name));
        }
    }
    #[cfg(debug_assertions)]
    {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        if let Some(parent) = manifest_dir.parent() {
            candidates.push(parent.join("bin").join(name));
        }
    }

    candidates.push(PathBuf::from("/opt/homebrew/bin").join(name));
    candidates.push(PathBuf::from("/usr/local/bin").join(name));

    if let Ok(path_env) = std::env::var("PATH") {
        for dir in path_env.split(':') {
            if !dir.trim().is_empty() {
                candidates.push(PathBuf::from(dir.trim()).join(name));
            }
        }
    }

    candidates.into_iter().find(|p| p.exists() && p.is_file())
}

fn validate_python_candidate_with_vendor(
    candidate: &std::path::Path,
    vendor_paths: &[PathBuf],
) -> Result<(), String> {
    if !candidate.exists() || !candidate.is_file() {
        return Err(format!("arquivo inexistente: {}", candidate.display()));
    }

    let check_script = "import sys; assert sys.version_info >= (3, 9), f'Python {sys.version_info[0]}.{sys.version_info[1]} < 3.9'; import mutagen";
    let mut cmd = Command::new(candidate);
    cmd.env("PYTHONDONTWRITEBYTECODE", "1");
    if let Some(py_path) = build_pythonpath_env(vendor_paths) {
        cmd.env("PYTHONPATH", py_path);
    }
    let output = cmd
        .args(["-c", check_script])
        .output()
        .map_err(|e| format!("falha ao executar {}: {}", candidate.display(), e))?;

    if output.status.success() {
        return Ok(());
    }

    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    let detail = if stderr.is_empty() {
        format!("código de saída {:?}", output.status.code())
    } else {
        stderr
    };
    Err(format!("{} inválido ({})", candidate.display(), detail))
}

#[allow(dead_code)]
fn validate_python_candidate(candidate: &std::path::Path) -> Result<(), String> {
    let vendor_paths = collect_vendor_paths(None, None);
    validate_python_candidate_with_vendor(candidate, &vendor_paths)
}

fn find_python_binary_with_app(app: Option<&AppHandle>) -> Result<PathBuf, String> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    let vendor_paths = collect_vendor_paths(app, None);

    // 1. Python empacotado no bundle .app (prioridade máxima em produção)
    if let Ok(exe) = std::env::current_exe() {
        if let Some(macos_dir) = exe.parent() {
            if let Some(contents_dir) = macos_dir.parent() {
                candidates.push(
                    contents_dir
                        .join("Resources")
                        .join("python")
                        .join("bin")
                        .join("python3"),
                );
            }
        }
    }

    // 2. Variáveis de ambiente e virtualenv apenas em modo de desenvolvimento/teste
    #[cfg(debug_assertions)]
    {
        if let Ok(py_env) = std::env::var("SERATO_PYTHON").or_else(|_| std::env::var("PYTHON_PATH")) {
            let trimmed = py_env.trim();
            if !trimmed.is_empty() {
                candidates.push(PathBuf::from(trimmed));
            }
        }
        if let Ok(venv) = std::env::var("VIRTUAL_ENV") {
            let trimmed = venv.trim();
            if !trimmed.is_empty() {
                candidates.push(PathBuf::from(trimmed).join("bin").join("python3"));
            }
        }
    }

    // 3. Locais canônicos padrão no macOS (sem fallback arbitrário via PATH)
    for canonical in [
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
    ] {
        candidates.push(PathBuf::from(canonical));
    }

    let mut diagnostics: Vec<String> = Vec::new();
    for candidate in candidates {
        match validate_python_candidate_with_vendor(&candidate, &vendor_paths) {
            Ok(()) => return Ok(candidate),
            Err(reason) => diagnostics.push(reason),
        }
    }

    Err(format!(
        "Nenhum interpretador Python 3.9+ com o módulo 'mutagen' (global ou vendor) foi localizado. Verificações: {}",
        diagnostics.join("; ")
    ))
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

#[allow(dead_code)]
fn make_python_cmd(script: &Path, bin: &Path) -> Command {
    make_python_cmd_with_app(None, script, bin)
}

fn find_python_cmd(app: Option<&AppHandle>, script_name: &str) -> Result<Command, String> {
    let script = find_canonical_python_script(app, script_name)?;
    let bin = find_python_binary_with_app(app)?;
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

        // 3. Disk Usage: seleciona o primeiro volume externo de DJ montado (ou Macintosh HD)
        let mut disk_name = "Macintosh HD".to_string();
        let mut target_path_buf = PathBuf::from("/");
        if let Ok(entries) = std::fs::read_dir("/Volumes") {
            let mut candidates: Vec<(String, PathBuf)> = entries
                .flatten()
                .filter_map(|entry| {
                    let p = entry.path();
                    if !p.is_dir() {
                        return None;
                    }
                    let name = p.file_name()?.to_str()?.to_string();
                    if name.starts_with('.') || name.starts_with("Macintosh") {
                        return None;
                    }
                    let has_dj_layout = p.join("Serato").is_dir()
                        || p.join("_Serato_").is_dir()
                        || p.join("Music").is_dir();
                    if has_dj_layout {
                        Some((name, p))
                    } else {
                        None
                    }
                })
                .collect();
            candidates.sort_by(|a, b| a.0.cmp(&b.0));
            if let Some((vol_name, vol_path)) = candidates.into_iter().next() {
                disk_name = vol_name;
                target_path_buf = vol_path;
            }
        }
        let target_path = target_path_buf.to_string_lossy().to_string();

        let mut disk_free_gb = 0.0;
        let mut disk_total_gb = 0.0;
        let mut disk_percent = 0.0;

        if let Ok(c_path) = std::ffi::CString::new(target_path.as_str()) {
            let mut stat: std::mem::MaybeUninit<libc::statvfs> = std::mem::MaybeUninit::uninit();
            if unsafe { libc::statvfs(c_path.as_ptr(), stat.as_mut_ptr()) } == 0 {
                let stat = unsafe { stat.assume_init() };
                let block_size = stat.f_frsize;
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

    pub fn detect_paths_in_roots(
        volumes_dir: &std::path::Path,
        home_dir: Option<&std::path::Path>,
    ) -> DetectedPaths {
        // Prioridade 1: Volume externo que possua TANTO pasta de músicas quanto pasta Serato na mesma unidade
        if let Ok(entries) = std::fs::read_dir(volumes_dir) {
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
                                same_volume: true,
                            };
                        }
                    }
                }
            }
        }

        // Prioridade 2: Armazenamento interno (Macintosh HD / Notebook) na mesma unidade
        if let Some(home) = home_dir {
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
                    same_volume: true,
                };
            }
        }

        // Fallback: retorna caminhos encontrados individualmente com same_volume=false
        // para que o frontend NÃO os combine automaticamente entre unidades distintas.
        let mut final_mp3 = String::new();
        let mut final_serato = String::new();

        if let Ok(entries) = std::fs::read_dir(volumes_dir) {
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

        if let Some(home) = home_dir {
            if final_mp3.is_empty() {
                let internal_mp3_sub = home.join("Music").join("MP3");
                let internal_mp3 = home.join("Music");
                if internal_mp3_sub.exists() && internal_mp3_sub.is_dir() {
                    final_mp3 = internal_mp3_sub.to_string_lossy().to_string();
                } else if internal_mp3.exists() && internal_mp3.is_dir() {
                    final_mp3 = internal_mp3.to_string_lossy().to_string();
                }
            }
            if final_serato.is_empty() {
                let internal_serato_music = home.join("Music").join("_Serato_");
                let internal_serato_appsup = home.join("Library").join("Application Support").join("Serato");
                if internal_serato_music.exists() && internal_serato_music.is_dir() {
                    final_serato = internal_serato_music.to_string_lossy().to_string();
                } else if internal_serato_appsup.exists() && internal_serato_appsup.is_dir() {
                    final_serato = internal_serato_appsup.to_string_lossy().to_string();
                }
            }
        }

        DetectedPaths {
            mp3: final_mp3,
            serato: final_serato,
            same_volume: false,
        }
    }

    #[tauri::command]
    pub fn get_detected_paths() -> DetectedPaths {
        detect_paths_in_roots(std::path::Path::new("/Volumes"), dirs_home().as_deref())
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
        let expanded = if let Some(rest) = path.strip_prefix("~/") {
            if let Some(home) = dirs_home() {
                home.join(rest)
            } else {
                PathBuf::from(&path)
            }
        } else {
            PathBuf::from(&path)
        };

        if !expanded.exists() {
            return Err(format!("Caminho não encontrado no sistema: {}", expanded.display()));
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
        if trimmed.is_empty() {
            return Err("Destino vazio para abertura no navegador.".into());
        }
        let target = if let Some(rest) = trimmed.strip_prefix("~/") {
            if let Some(home) = dirs_home() {
                home.join(rest).to_string_lossy().to_string()
            } else {
                trimmed.to_string()
            }
        } else {
            trimmed.to_string()
        };

        let is_http_url = target.starts_with("https://") || target.starts_with("http://");
        let target_path = Path::new(&target);
        let is_local_html = target_path.is_file()
            && matches!(
                target_path.extension().and_then(|e| e.to_str()).map(|s| s.to_lowercase()).as_deref(),
                Some("html") | Some("htm")
            );
        if !is_http_url && !is_local_html {
            return Err("Destino inválido: apenas URLs http(s) ou relatórios HTML locais podem ser abertos.".into());
        }

        Command::new("open")
            .arg("--")
            .arg(&target)
            .spawn()
            .map_err(|e| format!("Falha ao abrir no navegador: {}", e))?;

        Ok(())
    }

    #[tauri::command]
    pub async fn save_text_file(path: String, content: String) -> Result<String, String> {
        let expanded = if let Some(rest) = path.strip_prefix("~/") {
            if let Some(home) = dirs_home() {
                home.join(rest)
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
    pub async fn move_to_trash(app: AppHandle, path: String) -> Result<(), String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "mover arquivo para a lixeira")?;
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
                let uid = unsafe { libc::geteuid() };
                let volume_trash = PathBuf::from(&volume_root).join(".Trashes").join(uid.to_string());
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
            std::fs::create_dir_all(&trash_dir)
                .map_err(|e| format!("Falha ao preparar Lixeira '{}': {}", trash_dir.display(), e))?;
        }

        let mut dest = trash_dir.join(file_name);
        if dest.exists() {
            let ts = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs();
            dest = trash_dir.join(format!("{}_{}", ts, file_name.to_string_lossy()));
        }

        // 3. Tenta rename(); se falhar (ex: cross-device EXDEV), copia, verifica tamanho + SHA-256 e só então remove a origem
        crate::move_file_with_verified_fallback(&file_path, &dest, false)
    }

    #[tauri::command]
    #[allow(clippy::too_many_arguments)]
    pub async fn start_sync(
        app: AppHandle,
        window: Window,
        _security_state: tauri::State<'_, AppSecurityState>,
        approved_plan_state: tauri::State<'_, ApprovedSyncPlanState>,
        mp3_path: String,
        serato_path: String,
        export_csv: bool,
        dry_run: bool,
        plan_id: Option<String>,
    ) -> Result<(), String> {
        let mp3_clean = mp3_path.trim().to_string();
        let serato_clean = serato_path.trim().to_string();

        if mp3_clean.is_empty() || !PathBuf::from(&mp3_clean).is_dir() {
            return Err("Diretório de músicas MP3 inválido ou não encontrado no disco.".into());
        }
        if serato_clean.is_empty() || !PathBuf::from(&serato_clean).is_dir() {
            return Err("Diretório da biblioteca Serato inválido ou não encontrado no disco.".into());
        }

        authorize_asset_directory(&app, &mp3_clean);
        authorize_asset_directory(&app, &serato_clean);

        if !dry_run && is_serato_running() {
            let err_msg = "❌ BLOQUEIO DE SEGURANÇA: O Serato DJ Pro está em execução ativa. Feche o aplicativo Serato DJ Pro antes de gravar ou ajustar a biblioteca. Enquanto o Serato estiver aberto, seu cache na memória RAM reverterá e sobrescreverá qualquer alteração física ao ser encerrado. O Modo Análise (Sem Alterar) permanece disponível.".to_string();
            let _ = window.emit("sync-log", &err_msg);
            return Err(err_msg);
        }

        let mut temp_plan_guard: Option<crate::TempFileCleanup> = None;
        let mut expected_plan_id: Option<String> = None;
        let mut validated_plan_payload: Option<serde_json::Value> = None;

        if !dry_run {
            let requested_pid = plan_id
                .as_deref()
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .ok_or_else(|| {
                    "Plano imutável ausente. Execute o Modo Análise (Sem Alterar) antes de Ajustar.".to_string()
                })?;

            // QA-09: inspecionar e validar sem consumir antecipadamente
            let (stored_pid, stored_plan) = {
                let lock = approved_plan_state
                    .current
                    .lock()
                    .map_err(|_| "Falha ao acessar estado do plano aprovado.".to_string())?;
                let (pid, plan) = lock.as_ref().ok_or_else(|| {
                    "Nenhum plano aprovado disponível. Execute o Modo Análise (Sem Alterar) antes de Ajustar.".to_string()
                })?;
                (pid.clone(), plan.clone())
            };

            if stored_pid != requested_pid {
                return Err("Identificador do plano não corresponde à última análise aprovada. Execute uma nova Análise.".into());
            }

            let canon_mp3 = std::fs::canonicalize(&mp3_clean)
                .unwrap_or_else(|_| PathBuf::from(&mp3_clean))
                .to_string_lossy()
                .to_string();
            let canon_serato = std::fs::canonicalize(&serato_clean)
                .unwrap_or_else(|_| PathBuf::from(&serato_clean))
                .to_string_lossy()
                .to_string();
            let plan_mp3 = stored_plan.get("mp3_dir").and_then(|v| v.as_str()).unwrap_or("");
            let plan_serato = stored_plan.get("serato_dir").and_then(|v| v.as_str()).unwrap_or("");
            if plan_mp3 != canon_mp3 || plan_serato != canon_serato {
                return Err("Biblioteca alterada após a análise. Execute uma nova Análise para os caminhos atuais.".into());
            }

            expected_plan_id = Some(stored_pid);
            validated_plan_payload = Some(stored_plan);
        }

        let guard = if !dry_run {
            Some(bloqueio_serato_e_concorrencia(Some(&app), "executar sincronização física da biblioteca")?)
        } else {
            None
        };

        let script_path = find_canonical_python_script(Some(&app), "serato_macos_app.py")?;
        let python_bin = find_python_binary_with_app(Some(&app))?;
        let vendor_paths = collect_vendor_paths(Some(&app), Some(&script_path));
        let py_path_env = build_pythonpath_env(&vendor_paths);

        if let (Some(ref pid), Some(ref plan_val)) = (&expected_plan_id, &validated_plan_payload) {
            let plan_path = std::env::temp_dir().join(format!("serato_approved_plan_{}.json", pid));
            let plan_json = serde_json::to_string(plan_val)
                .map_err(|e| format!("Falha ao serializar plano aprovado: {}", e))?;
            std::fs::write(&plan_path, plan_json)
                .map_err(|e| format!("Falha ao gravar arquivo temporário do plano: {}", e))?;
            let mut guard_tmp = crate::TempFileCleanup::new(plan_path);

            // QA-09: Reservar (consumir) o plano apenas após todas as validações de inicialização
            let mut lock = approved_plan_state
                .current
                .lock()
                .map_err(|_| "Falha ao reservar plano aprovado para execução.".to_string())?;
            let matches_expected = lock
                .as_ref()
                .map(|(curr_id, _)| curr_id == pid)
                .unwrap_or(false);
            if !matches_expected {
                return Err("Plano aprovado foi alterado ou já está em execução concorrente. Execute nova Análise.".into());
            }
            let _ = lock.take();
            let disarm_path = guard_tmp.disarm();
            if let Some(p) = disarm_path {
                temp_plan_guard = Some(crate::TempFileCleanup::new(p));
            }
        }

        let plan_state_arc = approved_plan_state.current.clone();
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let _guard = guard;
            let _temp_plan_cleanup = temp_plan_guard;
            let temp_plan_file = _temp_plan_cleanup
                .as_ref()
                .and_then(|c| c.0.as_ref())
                .cloned();
            if !dry_run && is_serato_running() {
                if let (Some(pid), Some(plan_val)) = (expected_plan_id.clone(), validated_plan_payload.clone()) {
                    if let Ok(mut lock) = plan_state_arc.lock() {
                        if lock.is_none() {
                            *lock = Some((pid, plan_val));
                        }
                    }
                }
                let err_msg = "❌ BLOQUEIO DE SEGURANÇA: O Serato DJ Pro foi aberto durante a inicialização da sincronização. Operação cancelada.".to_string();
                let _ = window_clone.emit("sync-log", &err_msg);
                let _ = window_clone.emit(
                    "sync-finished",
                    SyncFinishedPayload {
                        success: false,
                        exit_code: Some(1),
                        message: err_msg,
                        summary: None,
                    },
                );
                return;
            }
            let _ = window_clone.emit("sync-log", format!("🐍 Motor Python: {}", script_path.display()));

            let mut cmd = Command::new(&python_bin);
            cmd.env("PYTHONDONTWRITEBYTECODE", "1");
            if let Some(ref py_path) = py_path_env {
                cmd.env("PYTHONPATH", py_path);
            }
            cmd.arg(&script_path);
            cmd.arg(&mp3_clean);
            cmd.arg(&serato_clean);
            cmd.arg("--json-summary");

            if !export_csv {
                cmd.arg("--no-csv");
            }

            if let Some(ref pf) = temp_plan_file {
                cmd.arg("--execute-plan");
                cmd.arg(pf);
            }

            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            if dry_run {
                cmd.arg("--dry-run");
            }

            let mut child = match cmd.spawn() {
                Ok(child) => child,
                Err(e) => {
                    if let (Some(pid), Some(plan_val)) = (expected_plan_id, validated_plan_payload) {
                        if let Ok(mut lock) = plan_state_arc.lock() {
                            if lock.is_none() {
                                *lock = Some((pid, plan_val));
                            }
                        }
                    }
                    let err_msg = format!("❌ Erro ao disparar processo Python: {}", e);
                    let _ = window_clone.emit("sync-log", &err_msg);
                    let _ = window_clone.emit(
                        "sync-finished",
                        SyncFinishedPayload {
                            success: false,
                            exit_code: Some(1),
                            message: err_msg,
                            summary: None,
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
                    for line in reader.lines().map_while(Result::ok) {
                        if line.starts_with("__PAYLOAD_JSON_SUMMARY__") {
                            captured_summary = Some(line.clone());
                            if let Some(mut parsed) = parse_sync_summary_line(&line) {
                                if let Some(obj) = parsed.as_object_mut() {
                                    obj.remove("plan");
                                }
                                let _ = win_stdout.emit(
                                    "sync-log",
                                    format!("__PAYLOAD_JSON_SUMMARY__{}", parsed),
                                );
                                continue;
                            }
                        }
                        let _ = win_stdout.emit("sync-log", line);
                    }
                }
                captured_summary
            });

            let win_stderr = window_clone.clone();
            let stderr_thread = std::thread::spawn(move || {
                let mut err_lines = Vec::new();
                if let Some(err) = stderr {
                    let reader = BufReader::new(err);
                    for line in reader.lines().map_while(Result::ok) {
                        let _ = win_stderr.emit("sync-log", format!("⚠️ [STDERR] {}", line));
                        err_lines.push(line);
                    }
                }
                err_lines.join("\n")
            });

            let mut parsed_summary = stdout_thread
                .join()
                .ok()
                .flatten()
                .and_then(|line| parse_sync_summary_line(&line));
            let stderr_output = stderr_thread.join().unwrap_or_default();

            let exit_status = child.wait();
            let exit_ok = exit_status.as_ref().map(|s| s.success()).unwrap_or(false);

            // QA-03: Armazenar plano aprovado SOMENTE após código de saída == 0 e validação estrita do resumo
            if let Some(pid) = crate::should_store_approved_plan(dry_run, exit_ok, parsed_summary.as_ref()) {
                if let Some(plan_val) = parsed_summary
                    .as_mut()
                    .and_then(|s| s.as_object_mut())
                    .and_then(|obj| obj.remove("plan"))
                {
                    if let Ok(mut lock) = plan_state_arc.lock() {
                        *lock = Some((pid, plan_val));
                    }
                }
            } else if let Some(ref mut summary_val) = parsed_summary {
                if let Some(obj) = summary_val.as_object_mut() {
                    obj.remove("plan");
                }
            }

            let (success, code, message) = match exit_status {
                Ok(status) => {
                    let code = status.code().unwrap_or(-1);
                    if status.success() {
                        let ok_msg = if dry_run {
                            "Pré-avaliação (Modo Análise) concluída com sucesso. Nenhuma alteração gravada no HD."
                        } else {
                            "Sincronização concluída com sucesso."
                        };
                        (true, code, ok_msg.into())
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
                    summary: parsed_summary,
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
    #[allow(clippy::too_many_arguments)]
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
        let stderr_pipe = child.stderr.take();
        let err_thread = std::thread::spawn(move || {
            let mut err_buf = String::new();
            if let Some(err) = stderr_pipe {
                for line in BufReader::new(err).lines().map_while(Result::ok) {
                    if !err_buf.is_empty() {
                        err_buf.push('\n');
                    }
                    err_buf.push_str(&line);
                }
            }
            err_buf
        });

        let mut final_json = String::new();
        if let Some(stdout) = child.stdout.take() {
            let reader = BufReader::new(stdout);
            for line in reader.lines().map_while(Result::ok) {
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

        let stderr_output = err_thread.join().unwrap_or_default();
        let status = child.wait().map_err(|e| format!("Falha ao aguardar scanner: {}", e))?;
        if !status.success() {
            let detail = if stderr_output.trim().is_empty() {
                format!("Erro na execução do scanner (código {:?})", status.code())
            } else {
                format!("Erro na execução do scanner: {}", stderr_output.trim())
            };
            return Err(detail);
        }

        if final_json.is_empty() {
            return Err("O scanner de tags não retornou JSON válido.".into());
        }

        Ok(final_json)
    }

    #[tauri::command]
    #[allow(clippy::too_many_arguments)]
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
        let python_bin = find_python_binary_with_app(Some(&app))?;
        let window_clone = window.clone();

        std::thread::spawn(move || {
            let _guard = guard;
            let mut cmd = make_python_cmd_with_app(Some(&app), &script, &python_bin);
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

            drop(window_clone);
            run_streaming_py_event_job(
                cmd,
                window,
                "tag-doctor-batch-progress",
                "tag-doctor-batch-finished",
                None,
                Some("Iniciando gravação..."),
                None,
            );
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
        let mut cmd = find_python_cmd(Some(&app), "tag_doctor.py")?;

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

        cmd.arg("--apply-tags");
        cmd.arg(&temp_file);
        if let Some(true) = rename_files {
            cmd.arg("--rename-files");
        }

        run_streaming_py_event_job(
            cmd,
            window,
            "tag-doctor-apply-progress",
            "tag-doctor-apply-finished",
            guard,
            Some("Iniciando gravação..."),
            Some(temp_file),
        );

        Ok(())
    }

    #[tauri::command]
    pub async fn enrich_missing_artists(
        app: AppHandle,
        window: Window,
        items_json: String,
    ) -> Result<(), String> {
        let guard = bloqueio_serato_e_concorrencia(Some(&app), "enriquecer artistas ausentes nas tags")?;
        let mut cmd = find_python_cmd(Some(&app), "tag_doctor.py")?;

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

        cmd.arg("--enrich-artists");
        cmd.arg(&temp_file);

        run_streaming_py_event_job(
            cmd,
            window,
            "tag-doctor-enrich-progress",
            "tag-doctor-enrich-finished",
            guard,
            Some("Iniciando identificação..."),
            Some(temp_file),
        );

        Ok(())
    }

    #[tauri::command]
    pub async fn backup_serato_db(app: AppHandle) -> Result<String, String> {
        let mut cmd = find_python_cmd(Some(&app), "tag_doctor.py")?;
        cmd.arg("--backup-db");
        run_python_output_checked(cmd, "Falha ao executar backup", "Erro ao gerar backup")
    }

    #[tauri::command]
    pub async fn list_serato_backups(app: AppHandle) -> Result<String, String> {
        let mut cmd = find_python_cmd(Some(&app), "tag_doctor.py")?;
        cmd.arg("--list-backups");
        run_python_output_checked(cmd, "Falha ao listar backups", "Erro ao listar backups")
    }

    #[tauri::command]
    pub async fn restore_serato_db(app: AppHandle, backup_path: String) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "restaurar backup do banco do Serato")?;
        let mut cmd = find_python_cmd(Some(&app), "tag_doctor.py")?;
        cmd.arg("--restore-db");
        cmd.arg(&backup_path);
        run_python_json_allow_domain_error(cmd, "Falha ao restaurar banco", "Erro ao restaurar banco")
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
        let stderr_pipe = child.stderr.take();
        let err_thread = std::thread::spawn(move || {
            let mut err_buf = String::new();
            if let Some(err) = stderr_pipe {
                for line in BufReader::new(err).lines().map_while(Result::ok) {
                    if !err_buf.is_empty() {
                        err_buf.push('\n');
                    }
                    err_buf.push_str(&line);
                }
            }
            err_buf
        });

        let mut final_json = String::new();
        if let Some(stdout) = child.stdout.take() {
            let reader = BufReader::new(stdout);
            for line in reader.lines().map_while(Result::ok) {
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

        let stderr_output = err_thread.join().unwrap_or_default();
        let status = child.wait().map_err(|e| format!("Falha ao aguardar Sound Seal: {}", e))?;
        if !status.success() {
            let detail = if stderr_output.trim().is_empty() {
                format!("Erro na execução do Sound Seal (código {:?})", status.code())
            } else {
                format!("Erro na execução do Sound Seal: {}", stderr_output.trim())
            };
            return Err(detail);
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
        let result = stdout.lines().rfind(|l| !l.trim().is_empty()).unwrap_or("{}").to_string();
        if !output.status.success() || result.is_empty() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            let msg = if stderr.trim().is_empty() { "Execução falhou" } else { stderr.as_ref() };
            return Err(format!("Erro ao listar backups de cues: {}", msg));
        }
        Ok(result)
    }

    #[tauri::command]
    pub async fn restore_auto_cues(app: AppHandle, filepath: String) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "restaurar Hot Cues nos arquivos")?;
        let mut cmd = find_python_cmd(Some(&app), "auto_cue.py")?;
        cmd.arg("--restore");
        cmd.arg(&filepath);
        run_python_json_allow_domain_error(cmd, "Falha ao restaurar Hot Cues", "Erro ao restaurar Hot Cues")
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

    /// Helper unificado para streaming de eventos em lote com drenagem concorrente de stderr e validação de ExitStatus.
    pub(crate) fn run_streaming_py_event_job(
        mut cmd: Command,
        window: Window,
        progress_event: &str,
        finished_event: &str,
        guard: Option<OperationGuard>,
        init_progress_label: Option<&str>,
        temp_cleanup_path: Option<PathBuf>,
    ) {
        let progress_ev = progress_event.to_string();
        let finished_ev = finished_event.to_string();
        let init_label = init_progress_label.map(String::from);

        std::thread::spawn(move || {
            let _guard = guard;
            let _tmp_cleanup = temp_cleanup_path.map(crate::TempFileCleanup::new);

            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            let mut child = match cmd.spawn() {
                Ok(c) => c,
                Err(e) => {
                    let _ = window.emit(
                        &finished_ev,
                        serde_json::json!({
                            "tipo": "fim",
                            "sucesso": false,
                            "erro": e.to_string(),
                        }),
                    );
                    return;
                }
            };

            let stderr_pipe = child.stderr.take();
            let err_drain = std::thread::spawn(move || {
                let mut err_buf = String::new();
                if let Some(pipe) = stderr_pipe {
                    for line in BufReader::new(pipe).lines().map_while(Result::ok) {
                        if !err_buf.is_empty() {
                            err_buf.push('\n');
                        }
                        err_buf.push_str(&line);
                    }
                }
                err_buf
            });

            let mut finished_emitted = false;
            let mut finished_ok = false;
            if let Some(stdout) = child.stdout.take() {
                for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                    if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&line) {
                        let tipo = parsed.get("tipo").and_then(|t| t.as_str()).unwrap_or("");
                        if tipo == "inicio" {
                            if let Some(ref lbl) = init_label {
                                let total = parsed.get("total").and_then(|t| t.as_u64()).unwrap_or(0);
                                let _ = window.emit(
                                    &progress_ev,
                                    serde_json::json!({
                                        "processados": 0,
                                        "total": total,
                                        "percentual": 0,
                                        "atualizados": 0,
                                        "enriquecidos": 0,
                                        "faixa_atual": lbl
                                    }),
                                );
                            }
                        } else if tipo == "progresso" {
                            let _ = window.emit(&progress_ev, parsed);
                        } else if tipo == "fim" {
                            finished_emitted = true;
                            finished_ok = parsed.get("sucesso").and_then(|v| v.as_bool()).unwrap_or(false);
                            let _ = window.emit(&finished_ev, parsed);
                        }
                    }
                }
            }

            let stderr_output = err_drain.join().unwrap_or_default();
            let exit_status = child.wait();
            let exit_ok = exit_status.as_ref().map(|s| s.success()).unwrap_or(false);

            if (!exit_ok && (!finished_emitted || finished_ok)) || (exit_ok && !finished_emitted) {
                let err_msg = if !stderr_output.trim().is_empty() {
                    stderr_output.trim().to_string()
                } else {
                    format!("Processo Python encerrou com status {:?}", exit_status.map(|s| s.code()))
                };
                let _ = window.emit(
                    &finished_ev,
                    serde_json::json!({
                        "tipo": "fim",
                        "sucesso": false,
                        "erro": err_msg,
                        "total": 0,
                        "atualizados": 0,
                        "erros": [err_msg],
                    }),
                );
            }
        });
    }

    pub(crate) fn run_python_output_checked(
        mut cmd: Command,
        spawn_err_prefix: &str,
        exec_err_prefix: &str,
    ) -> Result<String, String> {
        let output = cmd.output().map_err(|e| format!("{}: {}", spawn_err_prefix, e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr).to_string();
            let detail = if !stderr.trim().is_empty() {
                stderr.trim().to_string()
            } else if !stdout.trim().is_empty() {
                stdout.trim().to_string()
            } else {
                format!("código de saída {:?}", output.status.code())
            };
            return Err(format!("{}: {}", exec_err_prefix, detail));
        }
        Ok(stdout)
    }

    /// Executa um comando Python que pode sair com código != 0 emitindo JSON estruturado
    /// (`{"sucesso": false, "erro": ...}`) para o frontend, mas rejeita falhas sem JSON válido.
    pub(crate) fn run_python_json_allow_domain_error(
        mut cmd: Command,
        spawn_err_prefix: &str,
        exec_err_prefix: &str,
    ) -> Result<String, String> {
        let output = cmd.output().map_err(|e| format!("{}: {}", spawn_err_prefix, e))?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        if output.status.success() {
            return Ok(stdout);
        }
        if let Some(json_val) = try_parse_json(&stdout) {
            return Ok(json_val.to_string());
        }
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        let detail = if !stderr.trim().is_empty() {
            stderr.trim().to_string()
        } else if !stdout.trim().is_empty() {
            stdout.trim().to_string()
        } else {
            format!("código de saída {:?}", output.status.code())
        };
        Err(format!("{}: {}", exec_err_prefix, detail))
    }

    /// Executa um script Python e devolve a resposta JSON com timeout configurável.
    fn run_py_json_with_timeout(
        app: &AppHandle,
        script: &str,
        args: &[String],
        timeout_secs: u64,
    ) -> Result<String, String> {
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

        let python_bin = match find_python_binary_with_app(Some(app)) {
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

        // Define diretório de trabalho onde o script reside e configura PYTHONPATH com vendor completo
        if let Some(parent) = path.parent() {
            cmd.current_dir(parent);
            let mut vendor_paths = vec![parent.to_path_buf()];
            vendor_paths.extend(collect_vendor_paths(Some(app), Some(&path)));
            if let Some(py_path) = build_pythonpath_env(&vendor_paths) {
                cmd.env("PYTHONPATH", py_path);
            }
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
                for line in r.lines().map_while(Result::ok) {
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
                for line in r.lines().map_while(Result::ok) {
                    if !err.is_empty() { err.push('\n'); }
                    err.push_str(&line);
                }
            }
            err
        });

        let timeout = Duration::from_secs(timeout_secs);
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
                            &format!("Tempo limite de {}s excedido ao executar {}", timeout_secs, script),
                            serde_json::json!({ "script": script, "timeout_seconds": timeout_secs }),
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
        evaluate_python_json_output(script, exit_status.code(), exit_status.success(), &stdout, &stderr)
    }

    /// Executa um script Python e devolve a resposta JSON de forma robusta e resiliente (timeout padrão 120s).
    fn run_py_json(app: &AppHandle, script: &str, args: &[String]) -> Result<String, String> {
        run_py_json_with_timeout(app, script, args, 120)
    }

    pub(crate) fn evaluate_python_json_output(
        script: &str,
        exit_code: Option<i32>,
        success: bool,
        stdout: &str,
        stderr: &str,
    ) -> Result<String, String> {
        if !success {
            let code = exit_code.unwrap_or(-1);
            let diagnostic = if !stderr.trim().is_empty() {
                stderr.trim().to_string()
            } else if !stdout.trim().is_empty() {
                stdout.trim().to_string()
            } else {
                "Processo Python terminou com erro sem diagnóstico.".to_string()
            };
            return Err(format_structured_error(
                "PYTHON_EXECUTION_FAILED",
                &format!(
                    "O módulo Python '{}' encerrou com falha (código {}): {}",
                    script, code, diagnostic
                ),
                serde_json::json!({
                    "script": script,
                    "exit_code": code,
                    "stderr": stderr.trim(),
                    "stdout": stdout.trim()
                }),
            ));
        }

        if stdout.trim().is_empty() {
            return Err(format_structured_error(
                "PYTHON_EMPTY_RESPONSE",
                &format!("O módulo Python '{}' concluiu sem retornar dados (resposta vazia)", script),
                serde_json::json!({
                    "script": script,
                    "stdout": "",
                    "stderr": stderr.trim()
                }),
            ));
        }

        if let Some(json_val) = try_parse_json(stdout) {
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
        let mut cmd = find_python_cmd(Some(&app), "duplicates_tool.py")?;
        cmd.arg("--roots");
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
                for line in BufReader::new(out).lines().map_while(Result::ok) {
                    let t = line.trim().to_string();
                    if t.starts_with('{') {
                        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&t) {
                            if parsed.get("tipo").and_then(|v| v.as_str()) == Some("progresso") {
                                let _ = window_clone.emit("duplicates-progress", &t);
                                continue;
                            }
                        }
                        final_json = t;
                    }
                }
            }
            final_json
        });

        let stderr_thread = std::thread::spawn(move || {
            let mut err_str = String::new();
            if let Some(err) = stderr {
                for line in BufReader::new(err).lines().map_while(Result::ok) {
                    if !err_str.is_empty() {
                        err_str.push('\n');
                    }
                    err_str.push_str(&line);
                }
            }
            err_str
        });

        let final_json = stdout_thread.join().unwrap_or_default();
        let err_output = stderr_thread.join().unwrap_or_default();
        let status = child.wait().map_err(|e| format!("Falha ao aguardar duplicados: {}", e))?;

        if !status.success() {
            let msg = if err_output.trim().is_empty() {
                "Erro na execução da análise de duplicados".to_string()
            } else {
                err_output
            };
            return Err(msg);
        }
        if final_json.is_empty() {
            return Err("A análise de duplicados não retornou JSON válido.".into());
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
        let mut cmd = find_python_cmd(Some(&app), "music_analysis.py")?;
        cmd.arg("--analyze-batch").arg(&mp3_path);
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
                for line in r.lines().map_while(Result::ok) {
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
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                let trimmed = line.trim().to_string();
                if trimmed.starts_with('{') {
                    let _ = window.emit("analysis-progress", trimmed.clone());
                    final_json = trimmed;
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
        tauri::async_runtime::spawn_blocking(move || {
            run_py_json_with_timeout(
                &app,
                "library_tools.py",
                &["--check-refs".into(), "--serato".into(), serato_path],
                300,
            )
        })
        .await
        .map_err(|e| format!("Falha na thread de verificação de referências: {}", e))?
    }

    #[tauri::command]
    pub async fn library_health(app: AppHandle, mp3_path: String, serato_path: String) -> Result<String, String> {
        tauri::async_runtime::spawn_blocking(move || {
            run_py_json_with_timeout(
                &app,
                "library_tools.py",
                &[
                    "--health".into(), "--mp3".into(), mp3_path, "--serato".into(), serato_path,
                ],
                600,
            )
        })
        .await
        .map_err(|e| format!("Falha na thread de saúde da biblioteca: {}", e))?
    }

    #[tauri::command]
    pub async fn export_html_report(app: AppHandle, mp3_path: String, serato_path: String) -> Result<String, String> {
        tauri::async_runtime::spawn_blocking(move || {
            run_py_json_with_timeout(
                &app,
                "library_tools.py",
                &[
                    "--export-html-report".into(), "--mp3".into(), mp3_path, "--serato".into(), serato_path,
                ],
                600,
            )
        })
        .await
        .map_err(|e| format!("Falha na thread de relatório HTML: {}", e))?
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
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "remover smart crate")?;
        run_py_json(&app, "library_tools.py", &["--smart-delete".into(), nome])
    }

    #[tauri::command]
    pub async fn scan_new_tracks(app: AppHandle, mp3_path: String) -> Result<String, String> {
        tauri::async_runtime::spawn_blocking(move || {
            run_py_json_with_timeout(
                &app,
                "library_tools.py",
                &["--scan-new".into(), "--mp3".into(), mp3_path],
                300,
            )
        })
        .await
        .map_err(|e| format!("Falha na thread de busca por novas faixas: {}", e))?
    }

    #[tauri::command]
    pub async fn get_sound_seal_status(app: AppHandle) -> Result<String, String> {
        let mut cmd = find_python_cmd(Some(&app), "sound_seal.py")?;
        cmd.arg("--status");

        let output = cmd.output().map_err(|e| format!("Falha ao consultar status do Sound Seal: {}", e))?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        let result = stdout.lines().rfind(|l| !l.trim().is_empty()).unwrap_or("{}").to_string();
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
        let result = stdout.lines().rfind(|l| !l.trim().is_empty()).unwrap_or("{}").to_string();
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
        let result = stdout.lines().rfind(|l| !l.trim().is_empty()).unwrap_or("{}").to_string();
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
        let result = stdout.lines().rfind(|l| !l.trim().is_empty()).unwrap_or("{}").to_string();
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
        let result = stdout.lines().rfind(|l| !l.trim().is_empty()).unwrap_or("{}").to_string();
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
        let stderr_pipe = child.stderr.take();
        let err_thread = std::thread::spawn(move || {
            let mut err_buf = String::new();
            if let Some(err) = stderr_pipe {
                for line in BufReader::new(err).lines().map_while(Result::ok) {
                    if !err_buf.is_empty() {
                        err_buf.push('\n');
                    }
                    err_buf.push_str(&line);
                }
            }
            err_buf
        });

        let mut final_json = String::new();
        if let Some(stdout) = child.stdout.take() {
            let reader = BufReader::new(stdout);
            for line in reader.lines().map_while(Result::ok) {
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

        let stderr_output = err_thread.join().unwrap_or_default();
        let status = child.wait().map_err(|e| format!("Falha ao aguardar scanner de faixas perdidas: {}", e))?;
        if !status.success() {
            let detail = if stderr_output.trim().is_empty() {
                format!("Erro na execução do Relocate (código {:?})", status.code())
            } else {
                format!("Erro na execução do Relocate: {}", stderr_output.trim())
            };
            return Err(detail);
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
        serato_path: Option<String>,
        rel_path: String,
        source_path: String,
    ) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "religar faixa ausente")?;
        let mut cmd = find_python_cmd(Some(&app), "sound_seal.py")?;
        cmd.arg("--relink");
        cmd.arg("--mp3");
        cmd.arg(&mp3_path);
        if let Some(sp) = serato_path {
            if !sp.trim().is_empty() {
                cmd.arg("--serato");
                cmd.arg(sp.trim());
            }
        }
        cmd.arg("--rel-path");
        cmd.arg(&rel_path);
        cmd.arg("--source-path");
        cmd.arg(&source_path);
        run_python_json_allow_domain_error(cmd, "Falha ao religar faixa", "Erro ao religar faixa")
    }

    #[tauri::command]
    pub async fn batch_relink_tracks(
        app: AppHandle,
        window: Window,
        mp3_path: String,
        serato_path: Option<String>,
        items_json: String,
    ) -> Result<(), String> {
        let guard = bloqueio_serato_e_concorrencia(Some(&app), "religar faixas ausentes em lote")?;
        let mut cmd = find_python_cmd(Some(&app), "sound_seal.py")?;
        cmd.arg("--batch-relink");
        cmd.arg(&items_json);
        cmd.arg("--mp3");
        cmd.arg(&mp3_path);
        if let Some(sp) = serato_path {
            if !sp.trim().is_empty() {
                cmd.arg("--serato");
                cmd.arg(sp.trim());
            }
        }

        run_streaming_py_event_job(
            cmd,
            window,
            "sound-seal-relink-progress",
            "sound-seal-relink-finished",
            guard,
            None,
            None,
        );

        Ok(())
    }

    #[tauri::command]
    pub async fn remove_lost_tracks(
        app: AppHandle,
        mp3_path: String,
        serato_path: String,
        target_path: Option<String>,
        target_paths: Option<String>,
        allow_global_cleanup: Option<bool>,
    ) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "remover faixas perdidas das crates")?;
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
            cmd.arg("--target-paths");
            cmd.arg(tps);
        }
        if allow_global_cleanup == Some(true) {
            cmd.arg("--allow-global-cleanup");
        }
        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());

        let output = cmd
            .output()
            .map_err(|e| format!("Erro ao executar sound_seal.py --remove-lost: {e}"))?;

        let stdout = String::from_utf8_lossy(&output.stdout);
        let result: String = stdout.lines().rfind(|l| !l.trim().is_empty()).unwrap_or("{}").to_string();
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
        let stderr_pipe = child.stderr.take();
        let err_thread = std::thread::spawn(move || {
            let mut err_buf = String::new();
            if let Some(err) = stderr_pipe {
                for line in BufReader::new(err).lines().map_while(Result::ok) {
                    if !err_buf.is_empty() {
                        err_buf.push('\n');
                    }
                    err_buf.push_str(&line);
                }
            }
            err_buf
        });

        let mut final_json = String::new();
        if let Some(stdout) = child.stdout.take() {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                let trimmed = line.trim().to_string();
                if !trimmed.starts_with('{') {
                    continue;
                }
                // Progresso é repassado à interface; a última linha é o resultado
                let _ = window.emit("match-progress", &trimmed);
                final_json = trimmed;
            }
        }
        let stderr_output = err_thread.join().unwrap_or_default();
        let status = child.wait().map_err(|e| format!("Falha ao aguardar Track Matcher: {}", e))?;
        if !status.success() {
            let msg = if stderr_output.trim().is_empty() {
                format!("Track Matcher encerrou com erro (código {:?})", status.code())
            } else {
                format!("Track Matcher falhou: {}", stderr_output.trim())
            };
            return Err(msg);
        }
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
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "substituir faixas por upgrades")?;
        let mut cmd = find_python_cmd(Some(&app), "track_matcher.py")?;
        cmd.arg("--replace-upgrades");
        cmd.arg(&upgrades_json);
        run_python_output_checked(cmd, "Falha ao substituir upgrades", "Erro ao substituir upgrades")
    }

    #[tauri::command]
    pub async fn integrate_tracks_to_crate(
        app: AppHandle,
        tracks_json: String,
        target_folder: String,
    ) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "integrar faixas na crate")?;
        let mut cmd = find_python_cmd(Some(&app), "track_matcher.py")?;
        cmd.arg("--integrate-tracks");
        cmd.arg(&tracks_json);
        cmd.arg("--target-folder");
        cmd.arg(&target_folder);
        run_python_output_checked(cmd, "Falha ao integrar faixas na Crate", "Erro ao integrar faixas na Crate")
    }

    #[tauri::command]
    #[allow(clippy::too_many_arguments)]
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
        let stderr_pipe = child.stderr.take();
        let err_thread = std::thread::spawn(move || {
            let mut err_buf = String::new();
            if let Some(err) = stderr_pipe {
                for line in BufReader::new(err).lines().map_while(Result::ok) {
                    if !err_buf.is_empty() {
                        err_buf.push('\n');
                    }
                    err_buf.push_str(&line);
                }
            }
            err_buf
        });

        let mut final_json = String::new();
        if let Some(stdout) = child.stdout.take() {
            let reader = BufReader::new(stdout);
            for line in reader.lines().map_while(Result::ok) {
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

        let stderr_output = err_thread.join().unwrap_or_default();
        let status = child.wait().map_err(|e| format!("Falha ao aguardar auditoria de áudio: {}", e))?;
        if !status.success() {
            let detail = if stderr_output.trim().is_empty() {
                format!("Erro na execução da auditoria de áudio (código {:?})", status.code())
            } else {
                format!("Erro na execução da auditoria de áudio: {}", stderr_output.trim())
            };
            return Err(detail);
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
        run_python_json_allow_domain_error(cmd, "Falha ao gerar espectrograma", "Erro ao gerar espectrograma")
    }

    #[tauri::command]
    pub async fn resample_track_local(app: AppHandle, filepath: String) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "normalizar frequência de áudio")?;
        let mut cmd = find_python_cmd(Some(&app), "audio_health.py")?;
        cmd.arg("--resample-local");
        cmd.arg(&filepath);
        run_python_output_checked(cmd, "Falha ao normalizar frequência", "Erro ao normalizar frequência")
    }

    #[tauri::command]
    pub async fn batch_resample_local(
        app: AppHandle,
        window: Window,
        filepaths_json: String,
    ) -> Result<(), String> {
        let guard = bloqueio_serato_e_concorrencia(Some(&app), "normalizar frequência de áudio em lote")?;
        let mut cmd = find_python_cmd(Some(&app), "audio_health.py")?;
        cmd.arg("--batch-resample-local");
        cmd.arg(&filepaths_json);
        run_streaming_py_event_job(
            cmd,
            window,
            "audio-health-resample-progress",
            "audio-health-resample-finished",
            guard,
            None,
            None,
        );
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

            let res = run_python_json_allow_domain_error(
                cmd,
                "Falha ao executar motor de reparação",
                "Processo de reparação falhou",
            );
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
        let mut cmd = find_python_cmd(Some(&app), "audio_health.py")?;
        cmd.arg("--batch-repair-online");
        cmd.arg(&filepaths_json);
        if let Some(ref s_dir) = serato_dir {
            if !s_dir.trim().is_empty() {
                cmd.arg("--serato");
                cmd.arg(s_dir);
            }
        }
        run_streaming_py_event_job(
            cmd,
            window,
            "audio-health-batch-progress",
            "audio-health-batch-finished",
            guard,
            None,
            None,
        );
        Ok(())
    }

    #[tauri::command]
    pub async fn preaudit_track_online(app: AppHandle, filepath: String) -> Result<String, String> {
        let mut cmd = find_python_cmd(Some(&app), "audio_health.py")?;
        cmd.arg("--preaudit-online");
        cmd.arg(&filepath);
        run_python_output_checked(cmd, "Falha ao pré-auditar faixa online", "Erro ao pré-auditar faixa online")
    }

    #[tauri::command]
    pub async fn batch_preaudit_online(
        app: AppHandle,
        window: Window,
        filepaths_json: String,
    ) -> Result<(), String> {
        let mut cmd = find_python_cmd(Some(&app), "audio_health.py")?;
        cmd.arg("--batch-preaudit-online");
        cmd.arg(&filepaths_json);
        run_streaming_py_event_job(
            cmd,
            window,
            "audio-health-preaudit-progress",
            "audio-health-preaudit-finished",
            None,
            None,
            None,
        );
        Ok(())
    }

    #[tauri::command]
    pub async fn rename_audio_track(
        app: AppHandle,
        filepath: String,
        new_name: String,
    ) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "renomear arquivo de áudio")?;
        let mut cmd = find_python_cmd(Some(&app), "audio_health.py")?;
        cmd.arg("--rename-track");
        cmd.arg(&filepath);
        cmd.arg("--new-name");
        cmd.arg(&new_name);
        run_python_output_checked(cmd, "Falha ao renomear arquivo", "Falha ao renomear faixa")
    }

    #[tauri::command]
    pub async fn preview_auto_cues(app: AppHandle, filepath: String) -> Result<String, String> {
        let mut cmd = find_python_cmd(Some(&app), "auto_cue.py")?;
        cmd.arg("--preview");
        cmd.arg(&filepath);
        run_python_json_allow_domain_error(cmd, "Falha ao calcular Hot Cues", "Erro ao calcular Hot Cues")
    }

    #[tauri::command]
    pub async fn apply_auto_cues(app: AppHandle, filepath: String) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "gravar Hot Cues nos arquivos")?;
        let mut cmd = find_python_cmd(Some(&app), "auto_cue.py")?;
        cmd.arg("--apply");
        cmd.arg(&filepath);
        run_python_json_allow_domain_error(cmd, "Falha ao aplicar Hot Cues", "Erro ao aplicar Hot Cues")
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

        run_python_output_checked(cmd, "Falha ao escanear cues na crate", "Erro ao escanear cues na crate")
    }

    #[tauri::command]
    pub async fn audit_crate_cues(
        app: AppHandle,
        mp3_path: String,
        crate_raiz: Option<String>,
        subcrate: Option<String>,
        include_subcrates: Option<bool>,
    ) -> Result<String, String> {
        let mut cmd = find_python_cmd(Some(&app), "auto_cue.py")?;
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
    #[allow(clippy::too_many_arguments)]
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
        let mut cmd = find_python_cmd(Some(&app), "auto_cue.py")?;
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

        run_streaming_py_event_job(
            cmd,
            window,
            "auto-cue-batch-progress",
            "auto-cue-batch-finished",
            guard,
            None,
            None,
        );

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
        let mut cmd = find_python_cmd(Some(&app), "auto_cue.py")?;
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

        run_streaming_py_event_job(
            cmd,
            window,
            "auto-cue-repair-progress",
            "auto-cue-repair-finished",
            guard,
            None,
            None,
        );

        Ok(())
    }

    #[tauri::command]
    pub async fn apply_batch_auto_cues(app: AppHandle, filepaths_json: String) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "aplicar lote de Hot Cues nos arquivos")?;
        let mut cmd = find_python_cmd(Some(&app), "auto_cue.py")?;
        cmd.arg("--apply-batch");
        cmd.arg(&filepaths_json);
        run_python_json_allow_domain_error(cmd, "Falha ao aplicar lote de Hot Cues", "Erro ao aplicar lote de Hot Cues")
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
    pub async fn load_saved_summary(
        logs_dir: Option<String>,
        serato_path: Option<String>,
        mp3_path: Option<String>,
    ) -> Result<Option<String>, String> {
        let Some(ref sp_raw) = serato_path else {
            return Ok(None);
        };
        let sp_clean = sp_raw.trim();
        if sp_clean.is_empty() {
            return Ok(None);
        }

        let target_serato = std::fs::canonicalize(sp_clean)
            .unwrap_or_else(|_| PathBuf::from(sp_clean));
        let target_mp3 = mp3_path
            .as_deref()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(|p| std::fs::canonicalize(p).unwrap_or_else(|_| PathBuf::from(p)));

        let mut base_dirs: Vec<PathBuf> = Vec::new();
        if let Some(ref l) = logs_dir {
            let p = PathBuf::from(l);
            base_dirs.push(p.clone());
            base_dirs.push(p.join("logs"));
        }
        if let Some(home) = dirs_home() {
            base_dirs.push(home.join("SeratoSync").join("logs"));
            base_dirs.push(home);
        }

        let mut candidates: Vec<PathBuf> = Vec::new();
        for dir in &base_dirs {
            let summaries_dir = dir.join("summaries");
            if summaries_dir.is_dir() {
                if let Ok(entries) = std::fs::read_dir(&summaries_dir) {
                    for entry in entries.flatten() {
                        let p = entry.path();
                        if p.extension().and_then(|e| e.to_str()) == Some("json") {
                            candidates.push(p);
                        }
                    }
                }
            }
            candidates.push(dir.join(".serato_sync_summary.json"));
        }

        for candidate in candidates {
            if !candidate.exists() || !candidate.is_file() {
                continue;
            }
            let Ok(content) = std::fs::read_to_string(&candidate) else {
                continue;
            };
            if content.trim().is_empty() {
                continue;
            }
            let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&content) else {
                continue;
            };
            let Some(saved_serato_raw) = parsed.get("serato_path").and_then(|v| v.as_str()) else {
                continue;
            };
            let saved_serato = std::fs::canonicalize(saved_serato_raw)
                .unwrap_or_else(|_| PathBuf::from(saved_serato_raw));
            if saved_serato != target_serato {
                continue;
            }
            if let Some(ref t_mp3) = target_mp3 {
                if let Some(saved_mp3_raw) = parsed.get("mp3_path").and_then(|v| v.as_str()) {
                    let saved_mp3 = std::fs::canonicalize(saved_mp3_raw)
                        .unwrap_or_else(|_| PathBuf::from(saved_mp3_raw));
                    if &saved_mp3 != t_mp3 {
                        continue;
                    }
                }
            }
            return Ok(Some(content));
        }
        Ok(None)
    }

    #[tauri::command]
    pub async fn load_crates_from_disk(app: AppHandle, serato_path: String) -> Result<String, String> {
        let clean = serato_path.trim().to_string();
        if clean.is_empty() {
            return Err("Caminho do Serato inválido".into());
        }
        authorize_asset_directory(&app, &clean);
        run_py_json(&app, "crate_ops.py", &[
            "--list-tree".into(),
            "--serato".into(), clean,
        ])
    }

    #[tauri::command]
    pub async fn check_external_dependencies(app: AppHandle) -> DependencyStatus {
        let (python_ok, python_detail) = match find_python_binary_with_app(Some(&app)) {
            Ok(p) => (true, p.to_string_lossy().to_string()),
            Err(e) => (false, e),
        };
        let ffmpeg = find_external_binary(Some(&app), "ffmpeg");
        let ffprobe = find_external_binary(Some(&app), "ffprobe");
        let yt_dlp = find_external_binary(Some(&app), "yt-dlp");

        let mut warnings = Vec::new();
        if !python_ok {
            warnings.push(format!("Python 3.9+ com mutagen indisponível: {}", python_detail));
        }
        if ffmpeg.is_none() || ffprobe.is_none() {
            warnings.push(
                "FFmpeg/FFprobe não encontrados. Auto-Cue por transientes, análise espectral (Fake 320 kbps) e beatshift ficarão limitados. Instale via: brew install ffmpeg".into(),
            );
        }
        if yt_dlp.is_none() {
            warnings.push(
                "yt-dlp não encontrado. Reparação online de faixas no Audio Health / Track Matcher ficará indisponível. Instale via: brew install yt-dlp".into(),
            );
        }

        DependencyStatus {
            python_ok,
            python_detail,
            ffmpeg_ok: ffmpeg.is_some(),
            ffmpeg_path: ffmpeg.map(|p| p.to_string_lossy().to_string()),
            ffprobe_ok: ffprobe.is_some(),
            ffprobe_path: ffprobe.map(|p| p.to_string_lossy().to_string()),
            yt_dlp_ok: yt_dlp.is_some(),
            yt_dlp_path: yt_dlp.map(|p| p.to_string_lossy().to_string()),
            warnings,
        }
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
        // Grava tracks_json em arquivo temporário único para evitar estouro de buffer e colisão concorrente
        let temp_dir = std::env::temp_dir();
        let temp_file = temp_dir.join(format!("pioneer_tracks_{}.json", generate_operacao_id()));
        std::fs::write(&temp_file, tracks_json).map_err(|e| format!("Falha ao gravar arquivo temporário: {}", e))?;
        let _temp_cleanup = crate::TempFileCleanup::new(temp_file.clone());

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

        run_py_json(&app, "pioneer_usb_exporter.py", &args)
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
        let mut args = vec!["--recipe".into(), recipe_name];
        if let Some(p) = param {
            if !p.trim().is_empty() {
                args.push("--param".into());
                args.push(p);
            }
        }
        if files.len() > 30 {
            let tmp_path = std::env::temp_dir().join(format!("recipe_files_{}.json", generate_operacao_id()));
            let json_str = serde_json::to_string(&files).map_err(|e| e.to_string())?;
            std::fs::write(&tmp_path, json_str).map_err(|e| format!("Falha ao gravar arquivo temporário: {}", e))?;
            args.push("--files-file".into());
            args.push(tmp_path.to_string_lossy().to_string());
            let res = run_py_json(&app, "recipe_engine.py", &args);
            let _ = std::fs::remove_file(&tmp_path);
            res
        } else {
            args.push("--files".into());
            for f in files {
                args.push(f);
            }
            run_py_json(&app, "recipe_engine.py", &args)
        }
    }

    #[tauri::command]
    pub async fn undo_recipe(app: AppHandle) -> Result<String, String> {
        let _guard = bloqueio_serato_e_concorrencia(Some(&app), "desfazer receita de organização de tags")?;
        run_py_json(&app, "recipe_engine.py", &["--undo".into()])
    }

    #[tauri::command]
    #[allow(clippy::too_many_arguments)]
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
                if pts.len() > 30 {
                    let tmp_path = std::env::temp_dir().join(format!("crate_paths_{}.json", generate_operacao_id()));
                    if let Ok(json_str) = serde_json::to_string(&pts) {
                        if std::fs::write(&tmp_path, json_str).is_ok() {
                            args.push("--paths-file".into());
                            args.push(tmp_path.to_string_lossy().to_string());
                            let res = run_py_json(&app, "crate_ops.py", &args);
                            let _ = std::fs::remove_file(&tmp_path);
                            return res;
                        }
                    }
                }
                args.push("--paths".into());
                args.extend(pts);
            }
        }
        run_py_json(&app, "crate_ops.py", &args)
    }

    pub(crate) fn evaluate_energy_batch_output(
        exit_code: Option<i32>,
        exit_success: bool,
        final_json: &str,
        stderr: &str,
    ) -> Result<String, String> {
        if !exit_success {
            let code = exit_code.unwrap_or(-1);
            let detail = if stderr.trim().is_empty() {
                format!("Análise de energia falhou (código {})", code)
            } else {
                format!("Análise de energia falhou: {}", stderr.trim())
            };
            return Err(format_structured_error(
                "ENERGY_BATCH_FAILED",
                &detail,
                serde_json::json!({
                    "exit_code": code,
                    "stderr": stderr.trim()
                }),
            ));
        }

        let trimmed = final_json.trim();
        if trimmed.is_empty() {
            return Err(format_structured_error(
                "ENERGY_MISSING_FINAL_RESULT",
                "Análise de energia concluiu sem emitir o resultado JSON final estruturado (execução não confirmada).",
                serde_json::json!({
                    "exit_code": exit_code,
                    "stderr": stderr.trim()
                }),
            ));
        }

        let val: serde_json::Value = serde_json::from_str(trimmed).map_err(|e| {
            format_structured_error(
                "ENERGY_INVALID_FINAL_RESULT",
                &format!("Resultado final da análise de energia inválido: {}", e),
                serde_json::json!({ "raw": trimmed }),
            )
        })?;

        let tipo_ok = val.get("tipo").and_then(|v| v.as_str()) == Some("fim");
        let sucesso_opt = val.get("sucesso").and_then(|v| v.as_bool());
        if !tipo_ok || sucesso_opt.is_none() {
            return Err(format_structured_error(
                "ENERGY_MALFORMED_FINAL_RESULT",
                "Payload final da análise de energia não segue o contrato esperado ('tipo': 'fim', 'sucesso': bool).",
                serde_json::json!({ "payload": val }),
            ));
        }

        if sucesso_opt == Some(false) {
            let msg = val
                .get("erro")
                .and_then(|v| v.as_str())
                .unwrap_or("Análise de energia retornou falha sem detalhe adicional.");
            return Err(format_structured_error(
                "ENERGY_DOMAIN_ERROR",
                msg,
                serde_json::json!({ "payload": val }),
            ));
        }

        let has_metrics = val.get("total").and_then(|v| v.as_u64()).is_some()
            && val.get("analisadas").and_then(|v| v.as_u64()).is_some()
            && val.get("gravadas").and_then(|v| v.as_u64()).is_some()
            && val.get("erros").and_then(|v| v.as_u64()).is_some();
        if !has_metrics {
            return Err(format_structured_error(
                "ENERGY_INCOMPLETE_FINAL_RESULT",
                "Payload final da análise de energia não contém os contadores estruturados obrigatórios.",
                serde_json::json!({ "payload": val }),
            ));
        }

        Ok(val.to_string())
    }

    #[tauri::command]
    #[allow(clippy::too_many_arguments)]
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
        let mut cmd = find_python_cmd(Some(&app), "music_analysis.py")?;
        cmd.arg("--energy-batch").arg(&mp3_path);
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
                for line in BufReader::new(pipe).lines().map_while(Result::ok) {
                    if !s.is_empty() { s.push('\n'); }
                    s.push_str(&line);
                }
            }
            s
        });

        let mut final_json = String::new();
        if let Some(stdout) = child.stdout.take() {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                let trimmed = line.trim();
                if trimmed.starts_with('{') {
                    if let Ok(val) = serde_json::from_str::<serde_json::Value>(trimmed) {
                        match val.get("tipo").and_then(|v| v.as_str()) {
                            Some("progresso") => {
                                let _ = window.emit("energy-progress", trimmed);
                            }
                            Some("fim") => {
                                final_json = trimmed.to_string();
                            }
                            _ => {}
                        }
                    }
                }
            }
        }
        let stderr_output = err_drain.join().unwrap_or_default();
        let status = child.wait().map_err(|e| format!("Falha ao aguardar análise de energia: {}", e))?;
        evaluate_energy_batch_output(status.code(), status.success(), &final_json, &stderr_output)
    }

    #[tauri::command]
    #[allow(clippy::too_many_arguments)]
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
        .manage(ApprovedSyncPlanState::new())
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
                            while rx.recv().is_ok() {
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
            commands::check_external_dependencies,
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

    #[test]
    fn test_concurrent_threads_only_one_acquires_lock_and_releases_on_error_or_panic() {
        let state = AppSecurityState::new();
        let state_a = state.clone();
        let state_b = state.clone();

        let barrier = Arc::new(std::sync::Barrier::new(2));
        let b_a = Arc::clone(&barrier);
        let b_b = Arc::clone(&barrier);

        let h1 = std::thread::spawn(move || {
            b_a.wait();
            let g = state_a.acquire_lock();
            if g.is_ok() {
                std::thread::sleep(Duration::from_millis(40));
                true
            } else {
                false
            }
        });

        let h2 = std::thread::spawn(move || {
            b_b.wait();
            let g = state_b.acquire_lock();
            if g.is_ok() {
                std::thread::sleep(Duration::from_millis(40));
                true
            } else {
                false
            }
        });

        let r1 = h1.join().unwrap();
        let r2 = h2.join().unwrap();
        assert_ne!(r1, r2, "Apenas uma operação simultânea pode adquirir o lock");
        assert!(!state.is_operation_active.load(Ordering::SeqCst));

        // Simula falha/panic durante operação com guard ativo
        let state_panic = state.clone();
        let res = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _guard = state_panic.acquire_lock().expect("Lock deve estar livre");
            assert!(state_panic.is_operation_active.load(Ordering::SeqCst));
            panic!("Falha simulada durante operação");
        }));
        assert!(res.is_err());
        assert!(
            !state.is_operation_active.load(Ordering::SeqCst),
            "Lock deve ser liberado automaticamente após falha/panic via Drop"
        );

        // Nova operação após falha deve ser aceita normalmente
        let guard_after = state.acquire_lock();
        assert!(guard_after.is_ok());
    }

    #[test]
    fn test_detect_paths_blocks_cross_volume_auto_pairing() {
        let base = std::env::temp_dir().join(format!("serato_detect_cross_{}", generate_operacao_id()));
        let volumes = base.join("Volumes");
        let vol_a = volumes.join("DriveA");
        let vol_b = volumes.join("DriveB");
        std::fs::create_dir_all(vol_a.join("Music").join("MP3")).unwrap();
        std::fs::create_dir_all(vol_b.join("_Serato_")).unwrap();

        let detected = commands::detect_paths_in_roots(&volumes, None);
        assert!(!detected.same_volume);
        assert!(detected.mp3.ends_with("DriveA/Music/MP3"));
        assert!(detected.serato.ends_with("DriveB/_Serato_"));

        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn test_detect_paths_prefers_same_volume_over_split_volumes() {
        let base = std::env::temp_dir().join(format!("serato_detect_same_{}", generate_operacao_id()));
        let volumes = base.join("Volumes");
        let vol_a = volumes.join("DriveA");
        let vol_b = volumes.join("DriveB");
        std::fs::create_dir_all(vol_a.join("Music").join("MP3")).unwrap();
        std::fs::create_dir_all(vol_b.join("Music").join("MP3")).unwrap();
        std::fs::create_dir_all(vol_b.join("_Serato_")).unwrap();

        let detected = commands::detect_paths_in_roots(&volumes, None);
        assert!(detected.same_volume);
        assert!(detected.mp3.ends_with("DriveB/Music/MP3"));
        assert!(detected.serato.ends_with("DriveB/_Serato_"));

        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn test_validate_python_candidate_checks_version_and_mutagen() {
        use std::os::unix::fs::PermissionsExt;

        let base = std::env::temp_dir().join(format!("serato_py_check_{}", generate_operacao_id()));
        std::fs::create_dir_all(&base).unwrap();

        let missing = base.join("missing_python");
        assert!(validate_python_candidate(&missing).is_err());

        let fake_fail = base.join("fake_fail.sh");
        std::fs::write(&fake_fail, "#!/bin/sh\necho \"No module named 'mutagen'\" >&2\nexit 1\n").unwrap();
        let mut perms = std::fs::metadata(&fake_fail).unwrap().permissions();
        perms.set_mode(0o755);
        std::fs::set_permissions(&fake_fail, perms).unwrap();
        let err = validate_python_candidate(&fake_fail).unwrap_err();
        assert!(err.contains("mutagen"));

        let fake_ok = base.join("fake_ok.sh");
        std::fs::write(&fake_ok, "#!/bin/sh\nexit 0\n").unwrap();
        let mut perms_ok = std::fs::metadata(&fake_ok).unwrap().permissions();
        perms_ok.set_mode(0o755);
        std::fs::set_permissions(&fake_ok, perms_ok).unwrap();
        assert!(validate_python_candidate(&fake_ok).is_ok());

        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn test_find_python_binary_resolves_valid_runtime() {
        let bin = find_python_binary_with_app(None);
        assert!(bin.is_ok(), "Esperava encontrar Python 3.9+ com mutagen: {:?}", bin);
    }

    #[test]
    fn test_parse_sync_summary_line_and_payload_contract() {
        let line = "__PAYLOAD_JSON_SUMMARY__{\"sucesso\":true,\"total_faixas\":42,\"crates_gravadas\":3}";
        let parsed = parse_sync_summary_line(line).expect("Resumo JSON deveria ser parseado");
        assert_eq!(parsed["sucesso"], true);
        assert_eq!(parsed["total_faixas"], 42);
        assert_eq!(parsed["crates_gravadas"], 3);

        assert!(parse_sync_summary_line("linha comum de log").is_none());
        assert!(parse_sync_summary_line("__PAYLOAD_JSON_SUMMARY__").is_none());
        assert!(parse_sync_summary_line("__PAYLOAD_JSON_SUMMARY__{invalido").is_none());

        let payload = SyncFinishedPayload {
            success: true,
            exit_code: Some(0),
            message: "Sincronização concluída com sucesso.".into(),
            summary: Some(parsed),
        };
        let json = serde_json::to_value(&payload).unwrap();
        assert_eq!(json["success"], true);
        assert_eq!(json["summary"]["total_faixas"], 42);
    }

    #[test]
    fn test_validate_python_candidate_with_vendor_mutagen() {
        use std::os::unix::fs::PermissionsExt;

        let base = std::env::temp_dir().join(format!("serato_py_vendor_{}", generate_operacao_id()));
        let vendor = base.join("vendor");
        std::fs::create_dir_all(&vendor).unwrap();

        let fake_py = base.join("fake_py.sh");
        // Simulates a Python binary that fails unless PYTHONPATH includes vendor
        std::fs::write(
            &fake_py,
            format!(
                "#!/bin/sh\ncase \"$PYTHONPATH\" in\n  *{}*) exit 0 ;;\n  *) echo \"No module named 'mutagen'\" >&2; exit 1 ;;\nesac\n",
                vendor.display()
            ),
        )
        .unwrap();
        let mut perms = std::fs::metadata(&fake_py).unwrap().permissions();
        perms.set_mode(0o755);
        std::fs::set_permissions(&fake_py, perms).unwrap();

        assert!(validate_python_candidate_with_vendor(&fake_py, &[]).is_err());
        assert!(validate_python_candidate_with_vendor(&fake_py, std::slice::from_ref(&vendor)).is_ok());

        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn test_load_saved_summary_validates_library_identity() {
        let base = std::env::temp_dir().join(format!("serato_summary_id_{}", generate_operacao_id()));
        let logs = base.join("logs");
        let serato_a = base.join("LibA").join("_Serato_");
        let serato_b = base.join("LibB").join("_Serato_");
        std::fs::create_dir_all(&logs).unwrap();
        std::fs::create_dir_all(&serato_a).unwrap();
        std::fs::create_dir_all(&serato_b).unwrap();

        let summary_a = serde_json::json!({
            "sucesso": true,
            "serato_path": std::fs::canonicalize(&serato_a).unwrap().to_string_lossy().to_string(),
            "crates_arvore": {"House": {"total_faixas": 1}}
        });
        std::fs::write(logs.join(".serato_sync_summary.json"), summary_a.to_string()).unwrap();

        let loaded_a = tauri::async_runtime::block_on(commands::load_saved_summary(
            Some(logs.to_string_lossy().to_string()),
            Some(serato_a.to_string_lossy().to_string()),
            None,
        )).unwrap();
        assert!(loaded_a.is_some());

        // Switching to Library B must NOT load Library A's summary!
        let loaded_b = tauri::async_runtime::block_on(commands::load_saved_summary(
            Some(logs.to_string_lossy().to_string()),
            Some(serato_b.to_string_lossy().to_string()),
            None,
        )).unwrap();
        assert!(loaded_b.is_none());

        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn test_evaluate_python_json_output_rejects_nonzero_even_with_json() {
        // QA-02: Non-zero exit code MUST fail even if stdout contains a valid JSON object
        let err = commands::evaluate_python_json_output(
            "dummy.py",
            Some(1),
            false,
            r#"{"sucesso":true,"nota":"parcial"}"#,
            "fatal error on stderr",
        )
        .unwrap_err();
        assert!(err.contains("PYTHON_EXECUTION_FAILED"));
        assert!(err.contains("fatal error on stderr"));

        // Empty stdout with exit code 0 MUST fail
        let empty_err = commands::evaluate_python_json_output("dummy.py", Some(0), true, "   ", "").unwrap_err();
        assert!(empty_err.contains("PYTHON_EMPTY_RESPONSE"));

        // Invalid JSON with exit code 0 MUST fail
        let bad_json = commands::evaluate_python_json_output("dummy.py", Some(0), true, "not json", "").unwrap_err();
        assert!(bad_json.contains("INVALID_JSON_RESPONSE"));

        // Zero exit code with valid JSON MUST succeed
        let ok = commands::evaluate_python_json_output("dummy.py", Some(0), true, r#"{"ok":true}"#, "").unwrap();
        assert_eq!(ok, r#"{"ok":true}"#);
    }

    #[test]
    fn test_qa01_move_file_verified_fallback_and_sha256_integrity() {
        let base = std::env::temp_dir().join(format!("serato_qa01_{}", generate_operacao_id()));
        let src_dir = base.join("src");
        let dst_dir = base.join("trash");
        std::fs::create_dir_all(&src_dir).unwrap();
        std::fs::create_dir_all(&dst_dir).unwrap();

        // 0. SHA-256 NIST vector "abc"
        let abc = src_dir.join("abc.txt");
        std::fs::write(&abc, b"abc").unwrap();
        let digest = calculate_sha256(&abc).unwrap();
        let hex: String = digest.iter().map(|b| format!("{:02x}", b)).collect();
        assert_eq!(hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");

        // 1. Normal rename succeeds and removes original
        let f1 = src_dir.join("track1.mp3");
        std::fs::write(&f1, b"ID3\x03\x00AUDIO_ONE").unwrap();
        let d1 = dst_dir.join("track1.mp3");
        move_file_with_verified_fallback(&f1, &d1, false).unwrap();
        assert!(!f1.exists());
        assert_eq!(std::fs::read(&d1).unwrap(), b"ID3\x03\x00AUDIO_ONE");

        // 2. Forced cross-device copy fallback > 100KB succeeds with SHA-256 verification
        let f2 = src_dir.join("track2.mp3");
        let big_payload: Vec<u8> = (0..131072).map(|i| (i % 251) as u8).collect();
        std::fs::write(&f2, &big_payload).unwrap();
        let d2 = dst_dir.join("track2.mp3");
        move_file_with_verified_fallback(&f2, &d2, true).unwrap();
        assert!(!f2.exists());
        assert_eq!(std::fs::read(&d2).unwrap(), big_payload);

        // 3. Copy failure (nonexistent destination parent) MUST preserve original and return Err
        let f3 = src_dir.join("track3.mp3");
        std::fs::write(&f3, b"KEEP_ME_SAFE").unwrap();
        let bad_dest = base.join("missing_parent").join("track3.mp3");
        assert!(move_file_with_verified_fallback(&f3, &bad_dest, true).is_err());
        assert!(f3.exists());
        assert_eq!(std::fs::read(&f3).unwrap(), b"KEEP_ME_SAFE");

        // 4. Size mismatch & SHA-256 mismatch detection in verify_file_copy
        let orig = src_dir.join("orig.bin");
        let diff_size = dst_dir.join("diff_size.bin");
        let diff_hash = dst_dir.join("diff_hash.bin");
        std::fs::write(&orig, b"ABCD1234").unwrap();
        std::fs::write(&diff_size, b"ABCD").unwrap();
        std::fs::write(&diff_hash, b"WXYZ1234").unwrap();
        assert!(verify_file_copy(&orig, &diff_size).is_err());
        assert!(verify_file_copy(&orig, &diff_hash).is_err());
        assert!(verify_file_copy(&orig, &orig).is_ok());

        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn test_qa03_should_store_approved_plan_gates() {
        let valid_summary = serde_json::json!({
            "sucesso": true,
            "dry_run": true,
            "plan_id": "plan-1234",
            "plan": {"files": []}
        });
        assert_eq!(
            should_store_approved_plan(true, true, Some(&valid_summary)),
            Some("plan-1234".to_string())
        );

        // Non-zero exit MUST reject plan even when JSON claims sucesso: true
        assert_eq!(should_store_approved_plan(true, false, Some(&valid_summary)), None);
        // Non-dry-run MUST NOT store
        assert_eq!(should_store_approved_plan(false, true, Some(&valid_summary)), None);
        // Partial errors MUST block approval
        let partial = serde_json::json!({
            "sucesso": true,
            "dry_run": true,
            "status_analise": "parcial_com_erros",
            "plan_id": "plan-1234",
            "plan": {"files": []}
        });
        assert_eq!(should_store_approved_plan(true, true, Some(&partial)), None);
        // Empty plan_id MUST block
        let empty_pid = serde_json::json!({
            "sucesso": true,
            "dry_run": true,
            "plan_id": "   ",
            "plan": {"files": []}
        });
        assert_eq!(should_store_approved_plan(true, true, Some(&empty_pid)), None);
        // Missing plan object MUST block
        let no_plan = serde_json::json!({
            "sucesso": true,
            "dry_run": true,
            "plan_id": "plan-1234"
        });
        assert_eq!(should_store_approved_plan(true, true, Some(&no_plan)), None);
    }

    #[test]
    fn test_qa08_and_qa09_checked_output_and_temp_cleanup() {
        let base = std::env::temp_dir().join(format!("serato_qa08_09_{}", generate_operacao_id()));
        std::fs::create_dir_all(&base).unwrap();

        // QA-09 TempFileCleanup cleans file on scope exit
        let tmp_plan = base.join("temp_plan.json");
        std::fs::write(&tmp_plan, b"{}").unwrap();
        assert!(tmp_plan.exists());
        {
            let _guard = TempFileCleanup::new(tmp_plan.clone());
        }
        assert!(!tmp_plan.exists(), "TempFileCleanup drop must remove temp plan file");

        // QA-08 run_python_output_checked fails on non-zero exit with stderr
        let mut fail_cmd = Command::new("/bin/sh");
        fail_cmd.arg("-c").arg("echo '{\"sucesso\":true}'; echo 'boom error' >&2; exit 1");
        let err = commands::run_python_output_checked(fail_cmd, "spawn", "exec").unwrap_err();
        assert!(err.contains("boom error"));

        let mut ok_cmd = Command::new("/bin/sh");
        ok_cmd.arg("-c").arg("echo '{\"sucesso\":true}'");
        let out = commands::run_python_output_checked(ok_cmd, "spawn", "exec").unwrap();
        assert!(out.contains("sucesso"));

        // run_python_json_allow_domain_error preserves structured JSON error on non-zero exit
        let mut domain_err_cmd = Command::new("/bin/sh");
        domain_err_cmd.arg("-c").arg("echo '{\"sucesso\":false,\"erro\":\"bloqueado\"}'; exit 1");
        let domain_out = commands::run_python_json_allow_domain_error(domain_err_cmd, "spawn", "exec").unwrap();
        assert!(domain_out.contains("bloqueado"));

        // run_python_json_allow_domain_error rejects non-JSON crash on non-zero exit
        let mut crash_cmd = Command::new("/bin/sh");
        crash_cmd.arg("-c").arg("echo 'Traceback fatal' >&2; exit 1");
        let crash_err = commands::run_python_json_allow_domain_error(crash_cmd, "spawn", "exec").unwrap_err();
        assert!(crash_err.contains("Traceback fatal"));

        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn test_qa006_evaluate_energy_batch_output_contract() {
        // Exit 0 sem payload final estruturado deve falhar explicitamente
        let missing_err = commands::evaluate_energy_batch_output(Some(0), true, "", "").unwrap_err();
        assert!(missing_err.contains("ENERGY_MISSING_FINAL_RESULT"));

        // JSON sem tipo=fim ou sem métricas obrigatórias deve falhar
        let malformed = commands::evaluate_energy_batch_output(
            Some(0),
            true,
            r#"{"sucesso":true}"#,
            "",
        )
        .unwrap_err();
        assert!(malformed.contains("ENERGY_MALFORMED_FINAL_RESULT"));

        let incomplete = commands::evaluate_energy_batch_output(
            Some(0),
            true,
            r#"{"tipo":"fim","sucesso":true}"#,
            "",
        )
        .unwrap_err();
        assert!(incomplete.contains("ENERGY_INCOMPLETE_FINAL_RESULT"));

        // Domain error com sucesso=false deve falhar
        let domain_err = commands::evaluate_energy_batch_output(
            Some(0),
            true,
            r#"{"tipo":"fim","sucesso":false,"erro":"Crate não encontrada"}"#,
            "",
        )
        .unwrap_err();
        assert!(domain_err.contains("ENERGY_DOMAIN_ERROR"));
        assert!(domain_err.contains("Crate não encontrada"));

        // Payload completo e válido deve ser aceito
        let valid = commands::evaluate_energy_batch_output(
            Some(0),
            true,
            r#"{"tipo":"fim","sucesso":true,"total":3,"analisadas":3,"gravadas":2,"erros":0,"resultados":[]}"#,
            "",
        )
        .unwrap();
        assert!(valid.contains("\"gravadas\":2"));
    }
}
