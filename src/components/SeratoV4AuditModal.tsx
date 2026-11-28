import React, { useState, useEffect } from 'react';
import { X, ShieldCheck, AlertTriangle, CheckCircle2, Database, RefreshCw, FolderTree, Activity } from 'lucide-react';

interface SeratoV4Report {
  library_dir: string;
  v4_detected: boolean;
  v5_features_detected?: boolean;
  serato_generation?: string;
  healthy: boolean;
  master_exists: boolean;
  root_exists: boolean;
  location_exists: boolean;
  locations_count?: number;
  streaming_dbs?: Record<string, boolean>;
  db_uuid: string | null;
  user_version: number | null;
  autosync_disabled: number | null;
  v3_migration_status: string;
  containers_count: number;
  assets_count?: number;
  smart_crate_rules_count?: number;
  triggers_count: number;
  warnings: string[];
  errors: string[];
}

interface SeratoV4AuditModalProps {
  isOpen: boolean;
  onClose: () => void;
  seratoPath?: string;
}

export const SeratoV4AuditModal: React.FC<SeratoV4AuditModalProps> = ({
  isOpen,
  onClose,
  seratoPath
}) => {
  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
  
  const [report, setReport] = useState<SeratoV4Report | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const runAudit = async () => {
    if (!isTauri) return;
    setIsLoading(true);
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('audit_serato_v4', { libraryPath: seratoPath || null });
      setReport(JSON.parse(resJson));
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      runAudit();
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="bg-serato-card border border-serato-cardBorder rounded-2xl w-full max-w-xl shadow-2xl overflow-hidden flex flex-col">
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-serato-cardBorder bg-slate-900/50">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-xl border ${
              report?.healthy 
                ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                : 'bg-amber-500/20 text-amber-400 border-amber-500/30'
            }`}>
              <Database className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                Auditoria de Integridade Serato DJ Pro 5
                <span className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded border ${
                  report?.v4_detected
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                    : 'bg-slate-800 text-slate-400 border-slate-700'
                }`}>
                  {report?.v5_features_detected ? 'v5 SQLite + Streaming' : report?.v4_detected ? 'v4/v5 SQLite Ativo' : 'v3 Legado'}
                </span>
              </h3>
              <p className="text-xs text-slate-400">
                Inspeciona triggers, schema SQLite, ponte dbv2 e bancos de streaming do Serato 5.
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-white/5 transition">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Corpo */}
        <div className="p-6 space-y-4">
          {isLoading ? (
            <div className="py-12 flex flex-col items-center justify-center gap-2 text-slate-400">
              <RefreshCw className="w-6 h-6 animate-spin text-serato-cyan" />
              <span className="text-xs font-mono">Inspecionando master.sqlite e triggers...</span>
            </div>
          ) : report ? (
            <div className="space-y-4">
              
              {/* Card Status Principal */}
              <div className={`p-4 rounded-xl border flex items-center justify-between ${
                report.healthy
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                  : 'bg-amber-500/10 border-amber-500/30 text-amber-300'
              }`}>
                <div className="flex items-center gap-3">
                  {report.healthy ? (
                    <CheckCircle2 className="w-6 h-6 text-emerald-400 shrink-0" />
                  ) : (
                    <AlertTriangle className="w-6 h-6 text-amber-400 shrink-0" />
                  )}
                  <div>
                    <div className="text-sm font-bold text-white">
                      {report.healthy ? 'Banco Serato 5 Íntegro e Saudável' : 'Avisos de Inconsistência na Base'}
                    </div>
                    <div className="text-xs text-slate-400">
                      {report.v3_migration_status}
                    </div>
                  </div>
                </div>

                <button
                  onClick={runAudit}
                  className="p-1.5 rounded-lg bg-black/40 hover:bg-black/60 text-slate-300 transition"
                  title="Re-auditar"
                >
                  <RefreshCw className="w-4 h-4" />
                </button>
              </div>

              {/* Grid de Metadados */}
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-3 bg-slate-900/60 border border-slate-800 rounded-xl space-y-1">
                  <span className="text-[10px] uppercase font-mono text-slate-400">UUID da Base:</span>
                  <div className="font-mono text-white truncate text-[11px]">{report.db_uuid || 'N/A'}</div>
                </div>
                <div className="p-3 bg-slate-900/60 border border-slate-800 rounded-xl space-y-1">
                  <span className="text-[10px] uppercase font-mono text-slate-400">Versão do Schema:</span>
                  <div className="font-mono text-white text-[11px] font-bold">PRAGMA user_version = {report.user_version ?? 0}</div>
                </div>
                <div className="p-3 bg-slate-900/60 border border-slate-800 rounded-xl space-y-1">
                  <span className="text-[10px] uppercase font-mono text-slate-400">Containers (Crates):</span>
                  <div className="font-mono text-serato-cyan text-sm font-bold">{report.containers_count} registrados</div>
                </div>
                <div className="p-3 bg-slate-900/60 border border-slate-800 rounded-xl space-y-1">
                  <span className="text-[10px] uppercase font-mono text-slate-400">Triggers de Proteção:</span>
                  <div className="font-mono text-emerald-400 text-sm font-bold">{report.triggers_count} ativos</div>
                </div>
              </div>

              {/* Arquivos de Banco */}
              <div className="p-3 bg-slate-900/40 border border-slate-800 rounded-xl space-y-1.5 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase font-mono text-slate-400 font-bold">Diretório do Banco Serato 5:</span>
                  <span className="text-[10px] font-mono text-serato-cyan truncate max-w-[280px]" title={report.library_dir}>
                    {report.library_dir}
                  </span>
                </div>
                <div className="flex items-center justify-between text-slate-300 font-mono text-[11px] pt-1 border-t border-white/5">
                  <span>master.sqlite:</span>
                  <span className={report.master_exists ? 'text-emerald-400 font-bold' : 'text-slate-500'}>
                    {report.master_exists ? 'PRESENTE' : 'AUSENTE'}
                  </span>
                </div>
                <div className="flex items-center justify-between text-slate-300 font-mono text-[11px]">
                  <span>root.sqlite:</span>
                  <span className={report.root_exists ? 'text-emerald-400 font-bold' : 'text-slate-500'}>
                    {report.root_exists ? 'PRESENTE' : 'AUSENTE'}
                  </span>
                </div>
                <div className="flex items-center justify-between text-slate-300 font-mono text-[11px]">
                  <span>Entidade de Localizações:</span>
                  <span className={report.location_exists ? 'text-emerald-400 font-bold' : 'text-slate-500'}>
                    {report.location_exists ? `PRESENTE (${report.locations_count ? `${report.locations_count} locais` : 'OK'})` : 'AUSENTE'}
                  </span>
                </div>
                {(report.assets_count !== undefined || report.smart_crate_rules_count !== undefined) && (
                  <div className="flex items-center justify-between text-slate-300 font-mono text-[11px]">
                    <span>Faixas (assets) / Smart Rules:</span>
                    <span className="text-serato-cyan font-bold">
                      {report.assets_count ?? 0} assets • {report.smart_crate_rules_count ?? 0} regras
                    </span>
                  </div>
                )}
                {report.streaming_dbs && (
                  <div className="pt-1.5 border-t border-white/5 flex flex-wrap gap-1.5">
                    {Object.entries(report.streaming_dbs).map(([name, present]) => (
                      <span
                        key={name}
                        className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                          present
                            ? 'bg-serato-cyan/10 text-serato-cyan border-serato-cyan/30'
                            : 'bg-slate-900 text-slate-500 border-slate-800'
                        }`}
                      >
                        {name}: {present ? 'ON' : 'OFF'}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Erros / Avisos */}
              {report.warnings.length > 0 && (
                <div className="space-y-1 text-xs text-amber-300 bg-amber-500/10 p-3 rounded-xl border border-amber-500/20">
                  <div className="font-bold flex items-center gap-1">
                    <AlertTriangle className="w-3.5 h-3.5" /> Avisos da Auditoria:
                  </div>
                  {report.warnings.map((w, i) => (
                    <div key={i} className="text-[11px]">• {w}</div>
                  ))}
                </div>
              )}

            </div>
          ) : null}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-serato-cardBorder bg-slate-900/40 flex items-center justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-xs font-bold text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 transition"
          >
            Fechar
          </button>
        </div>

      </div>
    </div>
  );
};
