import React from 'react';
import { Zap, Loader2, Music, CheckCircle2, Copy, Shield, FileSpreadsheet, Search } from 'lucide-react';
import { SyncSummary } from '../types';

interface SyncControlsProps {
  isRunning: boolean;
  onStartSync: (dryRun: boolean) => void;
  canStart: boolean;
  exportCsv: boolean;
  setExportCsv: (val: boolean) => void;
  summary: SyncSummary | null;
}

export const SyncControls: React.FC<SyncControlsProps> = ({
  isRunning,
  onStartSync,
  canStart,
  exportCsv,
  setExportCsv,
  summary
}) => {
  return (
    <div className="bg-serato-card border border-serato-cardBorder rounded-xl p-3.5 shadow-lg flex flex-col md:flex-row items-center justify-between gap-3 shrink-0">
      {/* Metrics Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 w-full md:w-auto flex-1">
        <div className="bg-serato-dark/80 border border-serato-cardBorder p-2 rounded-lg flex items-center space-x-2">
          <div className="p-1.5 rounded bg-serato-cyan/10 text-serato-cyan border border-serato-cyan/20">
            <Music className="w-3.5 h-3.5" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-semibold text-serato-muted">Total Mapeado</div>
            <div className="text-sm font-bold text-white font-mono leading-tight">
              {summary ? summary.total_faixas.toLocaleString() : '---'}
            </div>
          </div>
        </div>

        <div className="bg-serato-dark/80 border border-serato-cardBorder p-2 rounded-lg flex items-center space-x-2">
          <div className="p-1.5 rounded bg-serato-neonGreen/10 text-serato-neonGreen border border-serato-neonGreen/20">
            <CheckCircle2 className="w-3.5 h-3.5" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-semibold text-serato-muted">
              {summary?.dry_run ? 'A Gravar' : 'Regravadas'}
            </div>
            <div className="text-sm font-bold text-serato-neonGreen font-mono leading-tight">
              {summary ? summary.crates_gravadas : '---'}
            </div>
          </div>
        </div>

        <div className="bg-serato-dark/80 border border-serato-cardBorder p-2 rounded-lg flex items-center space-x-2">
          <div className="p-1.5 rounded bg-serato-gold/10 text-serato-gold border border-serato-gold/20">
            <Shield className="w-3.5 h-3.5" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-semibold text-serato-muted">Poupadas Cache</div>
            <div className="text-sm font-bold text-serato-gold font-mono leading-tight">
              {summary ? summary.crates_inalteradas : '---'}
            </div>
          </div>
        </div>

        <div className="bg-serato-dark/80 border border-serato-cardBorder p-2 rounded-lg flex items-center space-x-2">
          <div className="p-1.5 rounded bg-serato-orange/10 text-serato-orange border border-serato-orange/20">
            <Copy className="w-3.5 h-3.5" />
          </div>
          <div>
            <div className="text-[10px] uppercase font-semibold text-serato-muted">Duplicados</div>
            <div className="text-sm font-bold text-serato-orange font-mono leading-tight">
              {summary ? summary.total_duplicados : '---'}
            </div>
          </div>
        </div>
      </div>

      {/* Action CTA with Dry-Run & Sync Buttons */}
      <div className="flex flex-wrap items-center gap-2.5 w-full md:w-auto justify-end">
        <label className="flex items-center gap-1.5 text-xs text-serato-muted cursor-pointer select-none mr-1">
          <input
            type="checkbox"
            checked={exportCsv}
            onChange={(e) => setExportCsv(e.target.checked)}
            disabled={isRunning}
            className="rounded bg-serato-dark border-serato-cardBorder text-serato-cyan focus:ring-0 focus:ring-offset-0 cursor-pointer"
          />
          <FileSpreadsheet className="w-3.5 h-3.5 text-serato-gold" />
          <span>Salvar CSV</span>
        </label>

        {/* Button 1: Somente Análise (Dry Run - Sem Alterações) */}
        <button
          type="button"
          onClick={() => onStartSync(true)}
          disabled={!canStart || isRunning}
          className={`px-3.5 py-2 rounded-lg font-semibold text-xs tracking-wide transition-all shadow border flex items-center justify-center gap-1.5 cursor-pointer ${
            isRunning
              ? 'bg-slate-800 text-slate-500 border-slate-700 cursor-not-allowed'
              : !canStart
              ? 'bg-slate-900 text-slate-600 border-slate-800 cursor-not-allowed'
              : 'bg-serato-hover hover:bg-slate-800 text-serato-cyan border-serato-cyan/40 hover:border-serato-cyan hover:shadow-cyan-950/30'
          }`}
          title="Verificar adições, remoções e duplicatas sem modificar nenhum arquivo no disco"
        >
          <Search className="w-3.5 h-3.5" />
          <span>Modo Análise (Sem Alterar)</span>
        </button>

        {/* Button 2: Sincronização Real */}
        <button
          type="button"
          onClick={() => onStartSync(false)}
          disabled={!canStart || isRunning}
          className={`px-5 py-2 rounded-lg font-bold text-xs tracking-wide transition-all shadow flex items-center justify-center gap-1.5 cursor-pointer ${
            isRunning
              ? 'bg-slate-700 text-slate-400 cursor-not-allowed border border-slate-600'
              : !canStart
              ? 'bg-slate-800 text-slate-500 cursor-not-allowed border border-slate-700'
              : 'bg-gradient-to-r from-serato-gold to-yellow-500 hover:from-yellow-400 hover:to-amber-500 text-black shadow-serato-gold/20 hover:scale-[1.02] active:scale-[0.98]'
          }`}
          title="Gravar crates (.crate), atualizar neworder.pref e cache no HD"
        >
          {isRunning ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin text-black" />
              <span>Processando...</span>
            </>
          ) : (
            <>
              <Zap className="w-3.5 h-3.5 fill-current text-black" />
              <span>INICIAR SINCRONIZAÇÃO</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
};
