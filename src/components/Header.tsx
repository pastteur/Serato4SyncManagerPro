import React, { useState, useEffect } from 'react';
import { Disc3, ShieldCheck, Cpu, HardDrive, Activity, Radio, Database } from 'lucide-react';
import { SeratoV4AuditModal } from './SeratoV4AuditModal';

interface HeaderProps {
  isRunning: boolean;
  mp3Path?: string;
  seratoPath?: string;
  onOpenGuide?: () => void;
  onAddLog?: (msg: string) => void;
}

interface SystemTelemetry {
  cpu_percent: number;
  ram_used_gb: number;
  ram_total_gb: number;
  ram_percent: number;
  disk_name: string;
  disk_free_gb: number;
  disk_total_gb: number;
  disk_percent: number;
  serato_running: boolean;
}

export const Header: React.FC<HeaderProps> = ({ isRunning, seratoPath }) => {
  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
  const [isV4ModalOpen, setIsV4ModalOpen] = useState<boolean>(false);
  
  const [telemetry, setTelemetry] = useState<SystemTelemetry>({
    cpu_percent: 0,
    ram_used_gb: 0,
    ram_total_gb: 0,
    ram_percent: 0,
    disk_name: 'Macintosh HD',
    disk_free_gb: 0,
    disk_total_gb: 0,
    disk_percent: 0,
    serato_running: false
  });

  useEffect(() => {
    let isMounted = true;

    const fetchTelemetry = async () => {
      if (!isTauri) return;
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const data = await invoke<SystemTelemetry>('get_system_telemetry');
        if (isMounted && data) {
          setTelemetry(data);
        }
      } catch (err) {
        // Silencioso em caso de polling temporário
      }
    };

    fetchTelemetry();
    const interval = setInterval(fetchTelemetry, 2500);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [isTauri]);

  // Cores dinâmicas de acordo com a carga
  const cpuColor = telemetry.cpu_percent > 85 ? 'text-rose-400' : telemetry.cpu_percent > 60 ? 'text-amber-400' : 'text-serato-cyan';
  const ramColor = telemetry.ram_percent > 85 ? 'text-rose-400' : telemetry.ram_percent > 75 ? 'text-amber-400' : 'text-purple-400';
  const diskColor = telemetry.disk_percent > 90 ? 'text-rose-400' : telemetry.disk_percent > 75 ? 'text-amber-400' : 'text-emerald-400';

  return (
    <header className="glass-panel border-b border-serato-cardBorder/80 px-5 py-2.5 flex items-center justify-between gap-4 relative z-10">
      
      {/* Lado Esquerdo: Logo & Info da Aplicação */}
      <div className="flex items-center space-x-3 shrink-0">
        <div className="p-2 bg-gradient-to-br from-serato-cyan/20 via-serato-purple/15 to-serato-gold/20 border border-serato-cyan/40 rounded-xl text-serato-cyan flex items-center justify-center shadow-glow-cyan">
          <Disc3 className={`w-7 h-7 ${isRunning ? 'animate-spin text-serato-cyan' : 'text-serato-cyan'}`} />
        </div>
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="text-base font-extrabold tracking-tight text-white flex items-center gap-1.5 font-sans">
              SERATO 5 <span className="text-serato-cyan">SYNC MANAGER PRO</span>
            </h1>
            <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded-full bg-serato-cyan/10 text-serato-cyan border border-serato-cyan/30 font-bold">
              v5.0 Engine
            </span>
          </div>
          <p className="text-[11px] text-serato-muted">
            Motor de Sincronização Inteligente • Apple Silicon • Serato DJ Pro 5
          </p>
        </div>
      </div>

      {/* Centro: HUD de Telemetria do Sistema & DJ (Espaço Otimizado) */}
      <div className="hidden md:flex items-center gap-2.5 flex-1 max-w-2xl justify-center font-mono text-[11px]">
        
        {/* Card 1: Hardware (CPU & RAM) */}
        <div className="bg-serato-card/90 border border-serato-cardBorder/80 px-3 py-1.5 rounded-lg flex items-center gap-3 shadow-inner hover:border-slate-700 transition">
          <div className="flex items-center gap-1.5" title={`Carga da CPU: ${telemetry.cpu_percent}%`}>
            <Activity className="w-3.5 h-3.5 text-serato-cyan animate-pulse shrink-0" />
            <span className="text-slate-400 text-[10px] font-sans font-semibold">CPU</span>
            <span className={`font-bold ${cpuColor}`}>
              {telemetry.cpu_percent}%
            </span>
          </div>

          <div className="h-3 w-px bg-slate-700/60" />

          <div className="flex items-center gap-1.5" title={`Memória RAM Usada: ${telemetry.ram_used_gb} GB de ${telemetry.ram_total_gb} GB (${telemetry.ram_percent}%)`}>
            <Cpu className="w-3.5 h-3.5 text-purple-400 shrink-0" />
            <span className="text-slate-400 text-[10px] font-sans font-semibold">RAM</span>
            <span className={`font-bold ${ramColor}`}>
              {telemetry.ram_used_gb} <span className="text-slate-500 font-normal">/ {telemetry.ram_total_gb} GB</span>
            </span>
          </div>
        </div>

        {/* Card 2: Armazenamento (SSD / Pendrive de Música) */}
        <div 
          className="bg-serato-card/90 border border-serato-cardBorder/80 px-3 py-1.5 rounded-lg flex items-center gap-2.5 shadow-inner hover:border-slate-700 transition"
          title={`Disco ${telemetry.disk_name}: ${telemetry.disk_free_gb} GB Livres de ${telemetry.disk_total_gb} GB (${telemetry.disk_percent}% ocupado)`}
        >
          <HardDrive className={`w-3.5 h-3.5 ${diskColor} shrink-0`} />
          <div className="flex flex-col">
            <div className="flex items-center gap-1.5 leading-none">
              <span className="text-slate-200 font-bold truncate max-w-[85px]">{telemetry.disk_name}:</span>
              <span className={`font-bold ${diskColor}`}>{telemetry.disk_free_gb} GB livres</span>
            </div>
            {/* Barra Slim de Ocupação do Disco */}
            <div className="w-full bg-slate-800 rounded-full h-1 mt-1 overflow-hidden border border-white/5">
              <div 
                className={`h-full transition-all duration-300 ${telemetry.disk_percent > 85 ? 'bg-rose-500' : 'bg-gradient-to-r from-emerald-500 to-teal-400'}`}
                style={{ width: `${Math.min(100, Math.max(2, telemetry.disk_percent))}%` }}
              />
            </div>
          </div>
        </div>

        {/* Card 3: Serato DJ Pro Live Status & Safety Lock */}
        <div 
          className={`border px-3 py-1.5 rounded-lg flex items-center gap-2 shadow-inner transition ${
            telemetry.serato_running 
              ? 'bg-amber-950/40 border-amber-500/50 text-amber-300' 
              : 'bg-slate-900/60 border-slate-800 text-slate-400'
          }`}
          title={telemetry.serato_running ? 'Serato DJ Pro está em execução ativa. Gravação bloqueada por segurança até fechar o Serato.' : 'Serato DJ Pro fechado. Gravação física liberada com segurança.'}
        >
          <Radio className={`w-3.5 h-3.5 shrink-0 ${telemetry.serato_running ? 'text-amber-400 animate-pulse' : 'text-slate-500'}`} />
          <span className="text-[10px] font-sans font-bold">Serato:</span>
          <span className="flex items-center gap-1 font-bold">
            <span className={`w-1.5 h-1.5 rounded-full ${telemetry.serato_running ? 'bg-amber-400 shadow-sm shadow-amber-400' : 'bg-emerald-400'}`} />
            <span>{telemetry.serato_running ? 'Aberto (Trava Ativa)' : 'Fechado (Pronto)'}</span>
          </span>
        </div>

      </div>

      {/* Lado Direito: Badges do Sistema & Esteira de Utilidades */}
      <div className="flex items-center space-x-2 shrink-0">
        <div className="flex items-center space-x-1.5 text-[11px] text-slate-400 bg-serato-card px-2.5 py-1.5 rounded-lg border border-serato-cardBorder font-sans">
          <Cpu className="w-3.5 h-3.5 text-serato-cyan" />
          <span>macOS Tahoe / Silicon</span>
        </div>
        <button
          type="button"
          onClick={() => setIsV4ModalOpen(true)}
          className="flex items-center space-x-1.5 text-[11px] text-serato-cyan bg-serato-cyan/10 hover:bg-serato-cyan/20 px-2.5 py-1.5 rounded-lg border border-serato-cyan/40 font-sans font-semibold transition cursor-pointer shadow-glow-cyan"
          title="Inspeciona a integridade física, bancos de streaming e status de migração SQLite do Serato 5"
        >
          <Database className="w-3.5 h-3.5 text-serato-cyan" />
          <span>Serato 5 Doctor</span>
        </button>
        <div className="flex items-center space-x-1.5 text-[11px] text-serato-neonGreen bg-serato-neonGreen/10 px-2.5 py-1.5 rounded-lg border border-serato-neonGreen/30 font-sans font-semibold">
          <ShieldCheck className="w-3.5 h-3.5 text-serato-neonGreen" />
          <span>SQLite Blindado</span>
        </div>
      </div>

      <SeratoV4AuditModal
        isOpen={isV4ModalOpen}
        onClose={() => setIsV4ModalOpen(false)}
        seratoPath={seratoPath}
      />
    </header>
  );
};
