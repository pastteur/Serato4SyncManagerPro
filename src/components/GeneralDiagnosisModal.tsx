import React, { useState, useEffect } from 'react';
import { 
  X, FileText, CheckCircle2, AlertTriangle, ShieldCheck, 
  ExternalLink, Loader2, Music, Disc, Layers, HardDrive, 
  Activity, Sparkles
} from 'lucide-react';

interface GeneralDiagnosisModalProps {
  isOpen: boolean;
  onClose: () => void;
  mp3Path: string;
  seratoPath: string;
  onAddLog?: (message: string) => void;
}

interface LibraryHealthData {
  total_faixas: number;
  tamanho_gb: number;
  sem_bpm: number;
  sem_tom: number;
  baixa_qualidade: number;
  sem_cues: number;
  crates?: number;
  referencias_quebradas?: number;
}

export const GeneralDiagnosisModal: React.FC<GeneralDiagnosisModalProps> = ({
  isOpen,
  onClose,
  mp3Path,
  seratoPath,
  onAddLog
}) => {
  const [loading, setLoading] = useState<boolean>(true);
  const [healthData, setHealthData] = useState<LibraryHealthData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isOpeningBrowser, setIsOpeningBrowser] = useState<boolean>(false);

  const loadHealth = async () => {
    if (!mp3Path) {
      setError('Pasta MP3 Master não informada.');
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('library_health', {
        mp3Path,
        seratoPath: seratoPath || ''
      });
      const data = JSON.parse(resJson);
      if (data.sucesso) {
        setHealthData(data);
      } else {
        setError(data.erro || 'Falha ao consultar saúde da biblioteca.');
      }
    } catch (e: any) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      loadHealth();
    }
  }, [isOpen, mp3Path, seratoPath]);

  const handleOpenReportInBrowser = async () => {
    setIsOpeningBrowser(true);
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('export_html_report', {
        mp3Path,
        seratoPath: seratoPath || ''
      });
      const data = JSON.parse(resJson);
      if (data.sucesso && data.arquivo) {
        if (onAddLog) {
          onAddLog(`📊 Diagnóstico executivo gerado: ${data.arquivo}`);
        }
        // Abre diretamente no Navegador Padrão (Safari / Chrome), SEM abrir pastas no Finder
        await invoke('open_in_browser', { pathOrUrl: data.arquivo });
      } else {
        alert(data.erro || 'Não foi possível gerar relatório HTML.');
      }
    } catch (e: any) {
      alert(`Erro ao abrir relatório no navegador: ${e}`);
    } finally {
      setIsOpeningBrowser(false);
    }
  };

  if (!isOpen) return null;

  const total = healthData?.total_faixas || 0;
  const comBpm = Math.max(0, total - (healthData?.sem_bpm || 0));
  const comTom = Math.max(0, total - (healthData?.sem_tom || 0));
  const comCues = Math.max(0, total - (healthData?.sem_cues || 0));
  const altaQualidade = Math.max(0, total - (healthData?.baixa_qualidade || 0));

  const pctBpm = total > 0 ? Math.round((comBpm / total) * 100) : 0;
  const pctTom = total > 0 ? Math.round((comTom / total) * 100) : 0;
  const pctCues = total > 0 ? Math.round((comCues / total) * 100) : 0;
  const pctQualidade = total > 0 ? Math.round((altaQualidade / total) * 100) : 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-amber-400/10 text-amber-400 border border-amber-400/20">
              <FileText className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base leading-tight">
                Diagnóstico Geral da Biblioteca
              </h3>
              <p className="text-xs text-slate-400">
                Auditoria de metadados, qualidade sonora e integridade de Crates
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 overflow-y-auto space-y-5 flex-1">
          {loading ? (
            <div className="py-16 flex flex-col items-center justify-center text-slate-400 space-y-3">
              <Loader2 className="w-8 h-8 animate-spin text-amber-400" />
              <span className="text-xs font-mono">Realizando varredura de diagnóstico na biblioteca...</span>
            </div>
          ) : error ? (
            <div className="p-4 bg-rose-500/10 border border-rose-500/20 rounded-xl text-rose-300 text-xs flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          ) : healthData ? (
            <>
              {/* Cards Principais */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="p-3.5 bg-slate-950/60 border border-slate-800 rounded-xl space-y-1">
                  <div className="text-[10px] uppercase font-mono text-slate-400 font-bold flex items-center gap-1.5">
                    <Music className="w-3.5 h-3.5 text-serato-cyan" /> Total de Faixas
                  </div>
                  <div className="text-xl font-mono font-bold text-white">
                    {total.toLocaleString()}
                  </div>
                  <div className="text-[10px] text-slate-500 font-mono">músicas mapeadas</div>
                </div>

                <div className="p-3.5 bg-slate-950/60 border border-slate-800 rounded-xl space-y-1">
                  <div className="text-[10px] uppercase font-mono text-slate-400 font-bold flex items-center gap-1.5">
                    <HardDrive className="w-3.5 h-3.5 text-amber-400" /> Armazenamento
                  </div>
                  <div className="text-xl font-mono font-bold text-amber-400">
                    {healthData.tamanho_gb} <span className="text-xs">GB</span>
                  </div>
                  <div className="text-[10px] text-slate-500 font-mono">espaço ocupado</div>
                </div>

                <div className="p-3.5 bg-slate-950/60 border border-slate-800 rounded-xl space-y-1">
                  <div className="text-[10px] uppercase font-mono text-slate-400 font-bold flex items-center gap-1.5">
                    <Layers className="w-3.5 h-3.5 text-emerald-400" /> Crates
                  </div>
                  <div className="text-xl font-mono font-bold text-emerald-400">
                    {healthData.crates ?? '---'}
                  </div>
                  <div className="text-[10px] text-slate-500 font-mono">listas verificadas</div>
                </div>

                <div className="p-3.5 bg-slate-950/60 border border-slate-800 rounded-xl space-y-1">
                  <div className="text-[10px] uppercase font-mono text-slate-400 font-bold flex items-center gap-1.5">
                    <ShieldCheck className="w-3.5 h-3.5 text-purple-400" /> Ref. Quebradas
                  </div>
                  <div className={`text-xl font-mono font-bold ${healthData.referencias_quebradas ? 'text-rose-400' : 'text-emerald-400'}`}>
                    {healthData.referencias_quebradas ?? 0}
                  </div>
                  <div className="text-[10px] text-slate-500 font-mono">
                    {healthData.referencias_quebradas ? 'necessita relocate' : '100% íntegro'}
                  </div>
                </div>
              </div>

              {/* Barras de Cobertura */}
              <div className="p-4 bg-slate-950/60 border border-slate-800 rounded-xl space-y-3.5 text-xs">
                <span className="text-[10px] uppercase font-mono text-slate-400 font-bold tracking-wider">
                  Cobertura de Metadados e Qualidade de Áudio:
                </span>

                <div className="space-y-1.5">
                  <div className="flex justify-between text-slate-300 font-mono text-[11px]">
                    <span>BPM Analisado: {comBpm} de {total}</span>
                    <span className="font-bold text-serato-cyan">{pctBpm}%</span>
                  </div>
                  <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                    <div className="h-full bg-serato-cyan transition-all duration-500" style={{ width: `${pctBpm}%` }} />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <div className="flex justify-between text-slate-300 font-mono text-[11px]">
                    <span>Tom Musical (Camelot): {comTom} de {total}</span>
                    <span className="font-bold text-purple-400">{pctTom}%</span>
                  </div>
                  <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                    <div className="h-full bg-purple-500 transition-all duration-500" style={{ width: `${pctTom}%` }} />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <div className="flex justify-between text-slate-300 font-mono text-[11px]">
                    <span>Hot Cues / Cue Points: {comCues} de {total}</span>
                    <span className="font-bold text-amber-400">{pctCues}%</span>
                  </div>
                  <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                    <div className="h-full bg-amber-400 transition-all duration-500" style={{ width: `${pctCues}%` }} />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <div className="flex justify-between text-slate-300 font-mono text-[11px]">
                    <span>Qualidade Sonora (&ge; 192 kbps): {altaQualidade} de {total}</span>
                    <span className="font-bold text-emerald-400">{pctQualidade}%</span>
                  </div>
                  <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                    <div className="h-full bg-emerald-500 transition-all duration-500" style={{ width: `${pctQualidade}%` }} />
                  </div>
                </div>
              </div>

              {/* Diretórios Mapeados */}
              <div className="p-3 bg-slate-950/40 border border-slate-800/80 rounded-xl space-y-1.5 text-xs font-mono">
                <div className="flex items-center justify-between text-slate-400 text-[11px]">
                  <span>Pasta Master MP3:</span>
                  <span className="text-slate-200 truncate max-w-[340px]" title={mp3Path}>{mp3Path}</span>
                </div>
                <div className="flex items-center justify-between text-slate-400 text-[11px]">
                  <span>Pasta Serato Crates:</span>
                  <span className="text-slate-200 truncate max-w-[340px]" title={seratoPath}>{seratoPath || 'Padrão do Sistema'}</span>
                </div>
              </div>
            </>
          ) : null}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-slate-800 bg-slate-950/80 flex items-center justify-between">
          <button
            onClick={handleOpenReportInBrowser}
            disabled={isOpeningBrowser || loading}
            className="flex items-center gap-1.5 text-xs font-bold text-black bg-gradient-to-r from-amber-400 to-serato-gold hover:opacity-90 px-3.5 py-2 rounded-xl transition shadow disabled:opacity-50 cursor-pointer"
            title="Abre o dashboard executivo HTML em nova aba do navegador padrão"
          >
            {isOpeningBrowser ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ExternalLink className="w-3.5 h-3.5" />}
            <span>Abrir Relatório Completo no Navegador</span>
          </button>

          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 transition cursor-pointer"
          >
            Fechar
          </button>
        </div>
      </div>
    </div>
  );
};
