import React from 'react';
import { Loader2, CircleDot, Clock } from 'lucide-react';

export type RunPhase = 'idle' | 'running' | 'done' | 'error';

export interface StatusBarProps {
  /** Fase atual da operação principal da aba */
  phase: RunPhase;
  /** Texto do que está acontecendo (ex.: "Cruzando faixas do HD...") */
  label?: string;
  /** Detalhe da direita: contagem, percentual, tempo */
  detail?: string;
  /** Percentual 0..100 quando houver progresso reportado */
  percent?: number | null;
  /** Resumo compacto do último resultado */
  summary?: string;
}

const Tone: Record<RunPhase, { bar: string; text: string; dot: string }> = {
  idle: { bar: 'border-serato-cardBorder', text: 'text-serato-muted', dot: 'text-serato-muted' },
  running: { bar: 'border-serato-cyan/50 bg-serato-cyan/[0.06]', text: 'text-serato-cyan', dot: 'text-serato-cyan' },
  done: { bar: 'border-serato-neonGreen/40 bg-serato-neonGreen/[0.05]', text: 'text-serato-neonGreen', dot: 'text-serato-neonGreen' },
  error: { bar: 'border-rose-700/50 bg-rose-950/20', text: 'text-rose-300', dot: 'text-rose-300' },
};

export const StatusBar: React.FC<StatusBarProps> = ({ phase, label, detail, percent, summary }) => {
  const tone = Tone[phase];
  const pct = typeof percent === 'number' ? Math.max(0, Math.min(100, percent)) : null;

  return (
    <div className={`shrink-0 flex items-center gap-3 border rounded-lg px-3 py-1.5 ${tone.bar}`} role="status" aria-live="polite">
      <div className={`flex items-center gap-2 text-[11px] font-semibold shrink-0 ${tone.text}`}>
        {phase === 'running' ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
          : phase === 'idle' ? <Clock className="w-3.5 h-3.5" />
          : <CircleDot className="w-3.5 h-3.5" />}
        <span className="uppercase tracking-wide">{phase === 'running' ? 'Em execução' : phase === 'done' ? 'Concluído' : phase === 'error' ? 'Erro' : 'Pronto'}</span>
      </div>

      <div className="min-w-0 flex-1 text-[11px] text-slate-300 truncate" title={label}>
        {label || (phase === 'idle' ? 'Nenhuma operação em andamento' : '')}
      </div>

      {pct !== null && (
        <div className="w-28 shrink-0 h-1.5 bg-serato-dark rounded-full overflow-hidden border border-serato-cardBorder">
          <div className={`h-full transition-all ${phase === 'error' ? 'bg-rose-400' : 'bg-serato-cyan'}`} style={{ width: `${pct}%` }} />
        </div>
      )}

      {summary && <div className="text-[11px] text-serato-muted shrink-0">{summary}</div>}
      {detail && <div className="text-[11px] font-mono text-white shrink-0">{detail}</div>}
    </div>
  );
};

export const ToolBar: React.FC<{ children: React.ReactNode; label?: string }> = ({ children, label }) => (
  <div className="shrink-0 flex flex-wrap items-center gap-2 border border-serato-cardBorder bg-serato-card/40 rounded-lg px-2.5 py-1.5">
    {label && <span className="text-[10px] uppercase tracking-wider text-serato-muted font-semibold mr-1">{label}</span>}
    {children}
  </div>
);
