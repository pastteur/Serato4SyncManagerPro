import React from 'react';
import { Disc3, ShieldCheck, Cpu } from 'lucide-react';

interface HeaderProps {
  isRunning: boolean;
}

export const Header: React.FC<HeaderProps> = ({ isRunning }) => {
  return (
    <header className="bg-serato-header border-b border-serato-cardBorder px-6 py-3 flex items-center justify-between">
      <div className="flex items-center space-x-3">
        <div className="p-2 bg-gradient-to-br from-serato-gold/20 to-serato-cyan/20 border border-serato-cardBorder rounded-xl text-serato-gold flex items-center justify-center">
          <Disc3 className={`w-7 h-7 ${isRunning ? 'animate-spin text-serato-cyan' : 'text-serato-gold'}`} />
        </div>
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="text-lg font-bold tracking-tight text-white flex items-center gap-1.5">
              SERATO 4 <span className="text-serato-cyan">SYNC MANAGER PRO</span>
            </h1>
            <span className="text-[11px] font-mono uppercase px-2 py-0.5 rounded-full bg-serato-gold/10 text-serato-gold border border-serato-gold/30">
              v4.0 Híbrido
            </span>
          </div>
          <p className="text-xs text-serato-muted">
            Motor de Sincronização Inteligente • macOS Apple Silicon • Serato DJ Pro 4
          </p>
        </div>
      </div>

      <div className="flex items-center space-x-4">
        <div className="flex items-center space-x-1.5 text-xs text-serato-muted bg-serato-card px-3 py-1.5 rounded-lg border border-serato-cardBorder">
          <Cpu className="w-3.5 h-3.5 text-serato-cyan" />
          <span>macOS Tahoe / Silicon</span>
        </div>
        <div className="flex items-center space-x-1.5 text-xs text-serato-neonGreen bg-serato-neonGreen/10 px-3 py-1.5 rounded-lg border border-serato-neonGreen/30">
          <ShieldCheck className="w-3.5 h-3.5 text-serato-neonGreen" />
          <span>SQLite Blindado</span>
        </div>
      </div>
    </header>
  );
};
