import React, { useRef, useEffect, useState } from 'react';
import { Terminal, Trash2, ArrowDown, Copy, Check, Search } from 'lucide-react';
import { LogEntry } from '../types';

interface TerminalLogsProps {
  logs: LogEntry[];
  onClear: () => void;
  isRunning: boolean;
}

export const TerminalLogs: React.FC<TerminalLogsProps> = ({ logs, onClear, isRunning }) => {
  const terminalEndRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (autoScroll && terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  const handleCopyLogs = () => {
    const text = logs.map(l => `[${l.timestamp}] ${l.message}`).join('\n');
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const renderLogBadge = (type: LogEntry['type']) => {
    switch (type) {
      case 'analysis':
        return <span className="text-cyan-400 font-bold">🔍</span>;
      case 'add':
        return <span className="text-emerald-400 font-bold">🆕</span>;
      case 'remove':
        return <span className="text-red-400 font-bold">🗑️</span>;
      case 'delete':
        return <span className="text-rose-500 font-bold">🚨</span>;
      case 'create':
        return <span className="text-sky-400 font-bold">📂</span>;
      case 'cache':
        return <span className="text-amber-400 font-bold">🔒</span>;
      case 'success':
        return <span className="text-green-400 font-bold">🎯</span>;
      case 'error':
        return <span className="text-red-500 font-bold">❌</span>;
      case 'warning':
        return <span className="text-amber-400 font-bold">⚠️</span>;
      default:
        return <span className="text-slate-500 font-mono">›</span>;
    }
  };

  const getLogColor = (type: LogEntry['type']) => {
    switch (type) {
      case 'analysis':
        return 'text-cyan-300 font-medium';
      case 'add':
        return 'text-emerald-300';
      case 'remove':
        return 'text-rose-300';
      case 'delete':
        return 'text-rose-400 font-semibold';
      case 'create':
        return 'text-cyan-300';
      case 'cache':
        return 'text-amber-300';
      case 'success':
        return 'text-emerald-400 font-bold';
      case 'error':
        return 'text-rose-400 font-bold';
      case 'warning':
        return 'text-amber-300';
      default:
        return 'text-slate-300';
    }
  };

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl flex flex-col h-full flex-1 shadow-2xl overflow-hidden min-h-0">
      {/* Terminal Title Bar */}
      <div className="bg-serato-header px-4 py-2 border-b border-serato-cardBorder flex items-center justify-between shrink-0">
        <div className="flex items-center space-x-2">
          <div className="flex space-x-1.5">
            <div className="w-2.5 h-2.5 rounded-full bg-rose-500/80"></div>
            <div className="w-2.5 h-2.5 rounded-full bg-amber-500/80"></div>
            <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/80"></div>
          </div>
          <div className="h-3.5 w-px bg-slate-700 mx-1.5" />
          <div className="flex items-center gap-1.5 text-xs font-mono text-slate-300 font-semibold">
            <Terminal className="w-3.5 h-3.5 text-serato-cyan" />
            <span>Terminal de Auditoria em Tempo Real</span>
            {isRunning && (
              <span className="flex items-center gap-1 text-[10px] text-serato-cyan bg-serato-cyan/10 px-2 py-0.2 rounded-full border border-serato-cyan/30 animate-pulse ml-2">
                ● Ativo
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <button
            type="button"
            onClick={() => setAutoScroll(!autoScroll)}
            className={`text-xs px-2.5 py-1 rounded flex items-center gap-1 transition ${
              autoScroll ? 'bg-serato-cyan/20 text-serato-cyan border border-serato-cyan/40' : 'text-slate-400 hover:text-white'
            }`}
            title="Rolar automaticamente para a mensagem mais recente"
          >
            <ArrowDown className="w-3 h-3" />
            <span>Auto-Scroll</span>
          </button>

          <button
            type="button"
            onClick={handleCopyLogs}
            disabled={logs.length === 0}
            className="text-xs text-slate-400 hover:text-white px-2 py-1 rounded hover:bg-slate-800 transition flex items-center gap-1 disabled:opacity-30"
            title="Copiar todos os logs"
          >
            {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
            <span>{copied ? 'Copiado!' : 'Copiar'}</span>
          </button>

          <button
            type="button"
            onClick={onClear}
            disabled={logs.length === 0}
            className="text-xs text-slate-400 hover:text-rose-400 px-2 py-1 rounded hover:bg-rose-950/30 transition flex items-center gap-1 disabled:opacity-30"
            title="Limpar terminal"
          >
            <Trash2 className="w-3 h-3" />
            <span>Limpar</span>
          </button>
        </div>
      </div>

      {/* Terminal Body with auto-height and responsive scrolling */}
      <div className="flex-1 p-3.5 font-mono text-xs overflow-y-auto space-y-1 bg-[#050608] min-h-0">
        {logs.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-600 space-y-2 select-none">
            <Terminal className="w-8 h-8 opacity-30 text-serato-cyan" />
            <p className="text-center font-sans font-medium text-slate-400">Pronto para iniciar auditoria ou sincronização.</p>
            <p className="text-[11px] text-slate-600 font-sans">
              Utilize "Modo Análise" para inspecionar sem alterar o HD, ou "Iniciar Sincronização" para gravar.
            </p>
          </div>
        ) : (
          logs.map((log) => (
            <div key={log.id} className="flex items-start space-x-2 leading-relaxed hover:bg-white/[0.02] px-1 py-0.5 rounded">
              <span className="text-slate-500 shrink-0 text-[11px] select-none">
                [{log.timestamp}]
              </span>
              <span className="shrink-0 select-none">
                {renderLogBadge(log.type)}
              </span>
              <span className={`break-all ${getLogColor(log.type)}`}>
                {log.message}
              </span>
            </div>
          ))
        )}
        <div ref={terminalEndRef} />
      </div>
    </div>
  );
};
