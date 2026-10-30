import React from 'react';
import { Folder, HardDrive, Laptop, Sparkles, AlertCircle } from 'lucide-react';

interface PathSelectorProps {
  mp3Path: string;
  seratoPath: string;
  onSelectMp3: () => void;
  onSelectSerato: () => void;
  onAutoDetect: () => void;
  disabled: boolean;
}

export const PathSelector: React.FC<PathSelectorProps> = ({
  mp3Path,
  seratoPath,
  onSelectMp3,
  onSelectSerato,
  onAutoDetect,
  disabled
}) => {
  const isMp3External = mp3Path.startsWith('/Volumes/');
  const isSeratoExternal = seratoPath.startsWith('/Volumes/');

  return (
    <div className="bg-serato-card border border-serato-cardBorder rounded-xl p-4 shadow-lg">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-serato-muted flex items-center gap-1.5">
          <Folder className="w-3.5 h-3.5 text-serato-gold" />
          Mapeamento Dinâmico de Dispositivos & Diretórios
        </h2>
        <button
          type="button"
          onClick={onAutoDetect}
          disabled={disabled}
          className="text-xs flex items-center gap-1 text-serato-cyan hover:text-serato-cyan/80 bg-serato-cyan/10 hover:bg-serato-cyan/20 px-2.5 py-1 rounded-md border border-serato-cyan/30 transition-all disabled:opacity-50"
          title="Detectar automaticamente HDs conectados e pastas locais"
        >
          <Sparkles className="w-3.5 h-3.5" />
          <span>Auto-Detectar</span>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Selector 1: MP3 Master */}
        <div className="bg-serato-dark/70 border border-serato-cardBorder rounded-lg p-3 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-bold text-serato-gold flex items-center gap-1">
                1. Pasta MP3 Master
              </span>
              {mp3Path ? (
                <span className={`text-[10px] font-mono flex items-center gap-1 px-1.5 py-0.5 rounded border ${
                  isMp3External 
                    ? 'bg-purple-950/40 text-purple-300 border-purple-700/40' 
                    : 'bg-blue-950/40 text-blue-300 border-blue-700/40'
                }`}>
                  {isMp3External ? <HardDrive className="w-2.5 h-2.5" /> : <Laptop className="w-2.5 h-2.5" />}
                  {isMp3External ? 'HD Externo' : 'Armazenamento Interno'}
                </span>
              ) : null}
            </div>

            <div 
              className="font-mono text-xs text-slate-300 truncate bg-black/40 px-2.5 py-2 rounded border border-white/5 mb-2.5 select-all"
              title={mp3Path || "Nenhuma pasta selecionada"}
            >
              {mp3Path || <span className="text-serato-muted italic">Nenhuma pasta MP3 selecionada...</span>}
            </div>
          </div>

          <button
            type="button"
            onClick={onSelectMp3}
            disabled={disabled}
            className="w-full py-2 px-3 text-xs font-medium rounded-md bg-serato-hover hover:bg-slate-700/80 text-white border border-slate-700 transition flex items-center justify-center gap-2 hover:border-serato-gold/50 disabled:opacity-50"
          >
            <Folder className="w-4 h-4 text-serato-gold" />
            <span>Selecionar MP3 Master...</span>
          </button>
        </div>

        {/* Selector 2: Pasta Serato */}
        <div className="bg-serato-dark/70 border border-serato-cardBorder rounded-lg p-3 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-bold text-serato-cyan flex items-center gap-1">
                2. Pasta de Sistema Serato
              </span>
              {seratoPath ? (
                <span className={`text-[10px] font-mono flex items-center gap-1 px-1.5 py-0.5 rounded border ${
                  isSeratoExternal 
                    ? 'bg-purple-950/40 text-purple-300 border-purple-700/40' 
                    : 'bg-blue-950/40 text-blue-300 border-blue-700/40'
                }`}>
                  {isSeratoExternal ? <HardDrive className="w-2.5 h-2.5" /> : <Laptop className="w-2.5 h-2.5" />}
                  {isSeratoExternal ? 'HD Externo' : 'Armazenamento Interno'}
                </span>
              ) : null}
            </div>

            <div 
              className="font-mono text-xs text-slate-300 truncate bg-black/40 px-2.5 py-2 rounded border border-white/5 mb-2.5 select-all"
              title={seratoPath || "Nenhuma pasta selecionada"}
            >
              {seratoPath || <span className="text-serato-muted italic">Nenhuma pasta Serato selecionada...</span>}
            </div>
          </div>

          <button
            type="button"
            onClick={onSelectSerato}
            disabled={disabled}
            className="w-full py-2 px-3 text-xs font-medium rounded-md bg-serato-hover hover:bg-slate-700/80 text-white border border-slate-700 transition flex items-center justify-center gap-2 hover:border-serato-cyan/50 disabled:opacity-50"
          >
            <Folder className="w-4 h-4 text-serato-cyan" />
            <span>Selecionar Pasta Serato...</span>
          </button>
        </div>
      </div>

      {(!mp3Path || !seratoPath) && (
        <div className="mt-3 flex items-center gap-1.5 text-xs text-amber-400/90 bg-amber-950/30 border border-amber-800/30 px-3 py-1.5 rounded-lg">
          <AlertCircle className="w-3.5 h-3.5 shrink-0" />
          <span>Selecione a pasta de músicas e a pasta Serato antes de iniciar a sincronização.</span>
        </div>
      )}
    </div>
  );
};
