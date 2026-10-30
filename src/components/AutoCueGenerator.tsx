import React, { useState } from 'react';
import { Target, Sparkles, CheckCircle2, Play, Music, ArrowRight, RefreshCw, Layers } from 'lucide-react';

interface AutoCueGeneratorProps {
  mp3Path: string;
  onAddLog: (message: string) => void;
  onOpenFileInFinder?: (filePath: string) => void;
}

export const AutoCueGenerator: React.FC<AutoCueGeneratorProps> = ({
  mp3Path,
  onAddLog,
  onOpenFileInFinder
}) => {
  const [selectedFile, setSelectedFile] = useState<string>('');
  const [cuePreview, setCuePreview] = useState<any>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isApplying, setIsApplying] = useState<boolean>(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);

  const handleCalculatePreview = async () => {
    if (!selectedFile.trim()) {
      alert('Informe o caminho do arquivo MP3.');
      return;
    }

    setIsLoading(true);
    setSuccessMsg(null);
    onAddLog(`🎯 Auto-Cue: Calculando os 5 Hot Cues para: ${selectedFile.split('/').pop()}...`);

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('preview_auto_cues', {
          filepath: selectedFile
        });
        const data = JSON.parse(resJson);
        if (data.sucesso) {
          setCuePreview(data);
          onAddLog(`✅ Hot Cues calculados com precisão métrica (${data.bpm || 'Auto'} BPM · ${roundSec(data.duracao)}s).`);
        } else {
          onAddLog(`❌ Erro no cálculo: ${data.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Falha: ${e}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleApplyCues = async () => {
    if (!selectedFile.trim()) return;

    setIsApplying(true);
    onAddLog(`✍️ Auto-Cue: Gravando marcadores no Serato Markers2...`);

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('apply_auto_cues', {
          filepath: selectedFile
        });
        const data = JSON.parse(resJson);
        if (data.sucesso) {
          setSuccessMsg(data.mensagem);
          onAddLog(`🎯 ${data.mensagem}`);
        } else {
          onAddLog(`❌ Erro ao gravar: ${data.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Falha: ${e}`);
    } finally {
      setIsApplying(false);
    }
  };

  const roundSec = (val: number) => Math.round(val || 0);
  const formatTime = (ms: number) => {
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec < 10 ? '0' : ''}${sec}`;
  };

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl p-4 shadow-2xl flex flex-col h-full flex-1 overflow-hidden min-h-0 space-y-3">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between pb-2.5 border-b border-serato-cardBorder shrink-0 gap-2">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Target className="w-4 h-4 text-serato-gold" />
            <span>Auto-Cue Generator (Geração Automática de Hot Cues para Serato)</span>
            <span className="text-[10px] bg-serato-gold/20 text-serato-gold px-2 py-0.5 rounded-full border border-serato-gold/30 font-mono">
              Padrão Mixed In Key / Lexicon
            </span>
          </h3>
          <p className="text-[11px] text-serato-muted">
            Calcula os 5 pontos de transição musical (Intro, Drop 1, Breakdown, Drop 2 e Outro) e grava nos marcadores do Serato.
          </p>
        </div>
      </div>

      {/* Input de Seleção */}
      <div className="bg-serato-card p-3 rounded-lg border border-serato-cardBorder space-y-2 shrink-0">
        <label className="text-xs text-slate-300 font-semibold block">Caminho da Faixa para Preparação de Cues:</label>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={selectedFile}
            onChange={(e) => setSelectedFile(e.target.value)}
            placeholder="Exemplo: /Volumes/Pastteyr/Music/MP3/Funk/01/NomeDaMusica.mp3"
            className="flex-1 bg-serato-dark border border-serato-cardBorder px-3 py-1.5 text-xs rounded text-slate-200 placeholder-slate-500 font-mono focus:outline-none focus:border-serato-gold"
          />

          <button
            type="button"
            onClick={handleCalculatePreview}
            disabled={isLoading || !selectedFile.trim()}
            className="px-3 py-1.5 rounded-lg text-xs font-bold bg-serato-gold hover:bg-yellow-400 text-black shadow-lg shadow-serato-gold/20 transition disabled:opacity-40 cursor-pointer flex items-center gap-1.5 shrink-0"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>{isLoading ? 'Calculando...' : '🎯 Calcular Cues'}</span>
          </button>
        </div>
      </div>

      {successMsg && (
        <div className="bg-emerald-950/60 border border-emerald-800/40 text-emerald-300 p-2.5 rounded-lg text-xs flex items-center gap-2 shrink-0">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      {/* Pré-visualização da Linha do Tempo e Cues */}
      <div className="flex-1 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20 p-4 space-y-4">
        {!cuePreview ? (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-500 text-xs">
            <Layers className="w-8 h-8 opacity-20 text-serato-gold mx-auto mb-2" />
            <p className="font-semibold text-slate-400">Nenhum cálculo de Hot Cues em exibição.</p>
            <p className="text-[11px] text-slate-600 mt-1">Cole o caminho de uma faixa acima e clique em "Calcular Cues".</p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between text-xs font-mono text-slate-300 pb-2 border-b border-serato-cardBorder">
              <div>
                Duração: <b className="text-white">{roundSec(cuePreview.duracao)}s</b> | BPM:{' '}
                <b className="text-serato-cyan">{cuePreview.bpm || 'Automático'}</b>
              </div>

              <button
                type="button"
                onClick={handleApplyCues}
                disabled={isApplying}
                className="px-4 py-1.5 rounded-lg text-xs font-bold bg-serato-neonGreen hover:bg-emerald-400 text-black shadow-lg shadow-emerald-950/40 transition cursor-pointer flex items-center gap-1.5"
              >
                <CheckCircle2 className="w-3.5 h-3.5" />
                <span>{isApplying ? 'Gravando no Serato...' : '✍️ Gravar Cues na Música'}</span>
              </button>
            </div>

            {/* Linha do Tempo Visual */}
            <div className="space-y-1.5">
              <div className="text-[10px] text-serato-muted uppercase font-mono">Linha do Tempo de Mixagem:</div>
              <div className="h-6 bg-serato-dark border border-serato-cardBorder rounded-lg relative overflow-hidden flex items-center px-1">
                {cuePreview.cues.map((c: any) => {
                  const pct = Math.min(98, (c.pos_ms / (cuePreview.duracao * 1000)) * 100);
                  return (
                    <div
                      key={c.index}
                      className="absolute top-0 bottom-0 w-1 flex items-center justify-center"
                      style={{ left: `${pct}%`, backgroundColor: c.color_hex }}
                      title={`${c.label} (${formatTime(c.pos_ms)})`}
                    >
                      <div className="w-2.5 h-2.5 rounded-full border border-black shadow-md" style={{ backgroundColor: c.color_hex }} />
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Lista dos 5 Hot Cues para o Controlador */}
            <div className="grid grid-cols-1 sm:grid-cols-5 gap-2.5 pt-2">
              {cuePreview.cues.map((c: any) => (
                <div
                  key={c.index}
                  className="bg-serato-card border border-serato-cardBorder p-2.5 rounded-lg space-y-1 text-center"
                >
                  <div className="flex items-center justify-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: c.color_hex }} />
                    <span className="text-[10px] font-bold text-slate-300 uppercase font-mono">Cue {c.index + 1}</span>
                  </div>
                  <div className="font-bold text-white text-xs">{c.label}</div>
                  <div className="text-xs font-mono font-bold text-serato-cyan">{formatTime(c.pos_ms)}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
