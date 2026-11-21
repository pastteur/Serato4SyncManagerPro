import React, { useState, useEffect } from 'react';
import { X, HardDrive, Disc, CheckCircle2, AlertTriangle, Loader2, ArrowRight, Zap, RefreshCw } from 'lucide-react';

interface DetectedVolume {
  name: string;
  mount_point: string;
}

interface PioneerExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  availableCrates: string[];
  onAddLog?: (msg: string) => void;
}

export const PioneerExportModal: React.FC<PioneerExportModalProps> = ({
  isOpen,
  onClose,
  availableCrates,
  onAddLog
}) => {
  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
  
  const [selectedCrate, setSelectedCrate] = useState<string>(availableCrates[0] || '');
  const [targetUsb, setTargetUsb] = useState<string>('');
  const [volumes, setVolumes] = useState<DetectedVolume[]>([]);
  const [isLoadingVolumes, setIsLoadingVolumes] = useState<boolean>(false);
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [dryRunStats, setDryRunStats] = useState<any | null>(null);
  const [exportResult, setExportResult] = useState<any | null>(null);
  const [copyAudio, setCopyAudio] = useState<boolean>(true);

  // Carrega volumes montados ao abrir o modal
  const fetchVolumes = async () => {
    if (!isTauri) return;
    setIsLoadingVolumes(true);
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const detected = await invoke<DetectedVolume[]>('detect_dj_volumes');
      // Filtra apenas volumes externos (/Volumes)
      const usbOnly = detected.filter(v => v.mount_point.startsWith('/Volumes/'));
      setVolumes(usbOnly);
      if (usbOnly.length > 0 && !targetUsb) {
        setTargetUsb(usbOnly[0].mount_point);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoadingVolumes(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchVolumes();
      if (!selectedCrate && availableCrates.length > 0) {
        setSelectedCrate(availableCrates[0]);
      }
      setExportResult(null);
      setDryRunStats(null);
    }
  }, [isOpen, availableCrates]);

  if (!isOpen) return null;

  const handleExport = async (dryRun: boolean = false) => {
    if (!targetUsb || !selectedCrate) {
      alert('Selecione a Crate e o Pendrive USB de destino.');
      return;
    }

    setIsExporting(true);
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      
      // Busca faixas da Crate selecionada
      const resJson = await invoke<string>('export_pioneer_usb', {
        usbPath: targetUsb,
        crateName: selectedCrate,
        tracksJson: JSON.stringify({ tracks: [] }), // Se a Crate tiver faixas, a bridge popula
        copyAudio,
        dryRun
      });

      const data = JSON.parse(resJson);
      if (dryRun) {
        setDryRunStats(data);
      } else {
        setExportResult(data);
        if (onAddLog) {
          onAddLog(`✅ Exportação Pioneer CDJ concluída para pendrive '${targetUsb}': ${data.copied_tracks || 0} faixas, ${data.cues_converted || 0} Hot Cues convertidos.`);
        }
      }
    } catch (err: any) {
      alert(`Falha na exportação Pioneer: ${err}`);
      if (onAddLog) onAddLog(`❌ Erro exportação Pioneer: ${err}`);
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="bg-serato-card border border-serato-cardBorder rounded-2xl w-full max-w-xl shadow-2xl overflow-hidden flex flex-col">
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-serato-cardBorder bg-slate-900/50">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/20 text-amber-400 border border-amber-500/30">
              <Disc className="w-6 h-6 animate-spin-slow" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                Exportar Crate para USB Pioneer CDJ
                <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30">
                  Rekordbox 6/7
                </span>
              </h3>
              <p className="text-xs text-slate-400">
                Gera o banco exportLibrary.db compatível com CDJ-2000NXS2, CDJ-3000 e Opus Quad.
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-white/5 transition">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Corpo */}
        <div className="p-6 space-y-5">
          {/* 1. Seleção de Crate */}
          <div>
            <label className="block text-xs font-bold text-slate-300 mb-1.5 uppercase font-mono tracking-wider">
              1. Selecione a Crate do Serato:
            </label>
            <select
              value={selectedCrate}
              onChange={(e) => setSelectedCrate(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3.5 py-2.5 text-sm text-white focus:outline-none focus:border-amber-400 font-sans"
            >
              {availableCrates.length === 0 ? (
                <option value="">Nenhuma Crate detectada</option>
              ) : (
                availableCrates.map(c => (
                  <option key={c} value={c}>{c}</option>
                ))
              )}
            </select>
          </div>

          {/* 2. Seleção de Unidade USB */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs font-bold text-slate-300 uppercase font-mono tracking-wider">
                2. Selecione o Pendrive / Unidade USB:
              </label>
              <button 
                onClick={fetchVolumes}
                disabled={isLoadingVolumes}
                className="text-[11px] text-amber-400 hover:underline flex items-center gap-1"
              >
                <RefreshCw className={`w-3 h-3 ${isLoadingVolumes ? 'animate-spin' : ''}`} />
                Atualizar Drives
              </button>
            </div>
            
            {volumes.length === 0 ? (
              <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-xl text-xs text-amber-300 flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>Nenhum pendrive USB externo detectado em /Volumes. Conecte sua unidade USB.</span>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-2">
                {volumes.map(vol => (
                  <label
                    key={vol.mount_point}
                    className={`flex items-center justify-between p-3 rounded-xl border cursor-pointer transition ${
                      targetUsb === vol.mount_point
                        ? 'bg-amber-500/10 border-amber-400 text-white'
                        : 'bg-slate-900/60 border-slate-800 text-slate-400 hover:border-slate-700'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <HardDrive className={`w-4 h-4 ${targetUsb === vol.mount_point ? 'text-amber-400' : 'text-slate-500'}`} />
                      <div>
                        <div className="text-xs font-bold text-white">{vol.name}</div>
                        <div className="text-[10px] font-mono text-slate-400">{vol.mount_point}</div>
                      </div>
                    </div>
                    <input
                      type="radio"
                      name="target_usb"
                      checked={targetUsb === vol.mount_point}
                      onChange={() => setTargetUsb(vol.mount_point)}
                      className="text-amber-400 focus:ring-0"
                    />
                  </label>
                ))}
              </div>
            )}
          </div>

          {/* Opções */}
          <div className="flex items-center gap-3 pt-1">
            <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={copyAudio}
                onChange={(e) => setCopyAudio(e.target.checked)}
                className="rounded border-slate-700 text-amber-500 focus:ring-0"
              />
              <span>Copiar arquivos de áudio físicos para a pasta <code>/Contents</code> do USB</span>
            </label>
          </div>

          {/* Resultado */}
          {exportResult && (
            <div className="p-3.5 bg-emerald-500/10 border border-emerald-500/30 rounded-xl text-xs text-emerald-300 space-y-1">
              <div className="font-bold flex items-center gap-1.5 text-sm">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                Exportação Concluída com Sucesso!
              </div>
              <div>• {exportResult.copied_tracks || 0} faixas adicionadas ao banco Rekordbox 6/7.</div>
              <div>• {exportResult.cues_converted || 0} Hot Cues Serato convertidos para marcadores Pioneer.</div>
              <div>• Banco gerado em: <code>{targetUsb}/PIONEER/rekordbox/exportLibrary.db</code></div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-serato-cardBorder bg-slate-900/40 flex items-center justify-between">
          <div className="text-[11px] text-slate-400 flex items-center gap-1">
            <Zap className="w-3.5 h-3.5 text-amber-400" />
            <span>Preserva 100% dos Hot Cues Serato Markers2</span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-bold text-slate-400 hover:text-white hover:bg-white/5 transition"
            >
              Fechar
            </button>
            <button
              onClick={() => handleExport(false)}
              disabled={isExporting || !targetUsb || !selectedCrate}
              className="px-5 py-2 rounded-xl text-xs font-bold text-black bg-gradient-to-r from-amber-400 to-orange-400 hover:opacity-90 transition disabled:opacity-50 flex items-center gap-1.5 shadow-md cursor-pointer"
            >
              {isExporting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Exportando...</span>
                </>
              ) : (
                <>
                  <span>Exportar para Pendrive</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </div>
        </div>

      </div>
    </div>
  );
};
