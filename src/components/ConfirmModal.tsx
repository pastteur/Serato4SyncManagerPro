import React, { useEffect } from 'react';
import { AlertTriangle, Trash2, Sparkles, CheckCircle2, X } from 'lucide-react';

export interface ConfirmModalProps {
  isOpen: boolean;
  title: string;
  message: string;
  detail?: string;
  confirmText?: string;
  cancelText?: string;
  variant?: 'danger' | 'warning' | 'info' | 'success';
  onConfirm: () => void;
  onCancel: () => void;
}

export const ConfirmModal: React.FC<ConfirmModalProps> = ({
  isOpen,
  title,
  message,
  detail,
  confirmText = 'Confirmar',
  cancelText = 'Cancelar',
  variant = 'warning',
  onConfirm,
  onCancel
}) => {
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onCancel();
      } else if (e.key === 'Enter') {
        onConfirm();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onConfirm, onCancel]);

  if (!isOpen) return null;

  const getIcon = () => {
    switch (variant) {
      case 'danger':
        return <Trash2 className="w-5 h-5 text-rose-400" />;
      case 'info':
        return <Sparkles className="w-5 h-5 text-serato-cyan" />;
      case 'success':
        return <CheckCircle2 className="w-5 h-5 text-emerald-400" />;
      case 'warning':
      default:
        return <AlertTriangle className="w-5 h-5 text-serato-gold" />;
    }
  };

  const getConfirmButtonClasses = () => {
    switch (variant) {
      case 'danger':
        return 'bg-rose-600 hover:bg-rose-500 text-white shadow-rose-950/60 shadow-lg';
      case 'info':
        return 'bg-serato-cyan hover:bg-cyan-300 text-black shadow-serato-cyan/30 shadow-lg';
      case 'success':
        return 'bg-emerald-500 hover:bg-emerald-400 text-black shadow-emerald-950/40 shadow-lg';
      case 'warning':
      default:
        return 'bg-serato-gold hover:bg-yellow-400 text-black shadow-serato-gold/30 shadow-lg';
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-150 select-none"
      onClick={onCancel}
    >
      <div
        className="bg-serato-dark border border-slate-700/80 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4 relative"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Botão de Fechar no Topo */}
        <button
          type="button"
          onClick={onCancel}
          className="absolute top-4 right-4 p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition cursor-pointer"
          title="Fechar (Esc)"
        >
          <X className="w-4 h-4" />
        </button>

        {/* Cabeçalho */}
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-slate-900 border border-slate-800 shrink-0">
            {getIcon()}
          </div>
          <div>
            <h3 className="text-base font-bold text-white leading-tight">{title}</h3>
            <p className="text-xs text-slate-400 mt-0.5">Aguardando sua confirmação para prosseguir.</p>
          </div>
        </div>

        {/* Mensagem Principal */}
        <div className="text-sm text-slate-200 leading-relaxed whitespace-pre-line py-1">
          {message}
        </div>

        {/* Detalhes Técnicos / Informações extras se houver */}
        {detail && (
          <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-3 text-xs font-mono text-slate-300 max-h-32 overflow-y-auto whitespace-pre-wrap break-all">
            {detail}
          </div>
        )}

        {/* Botões de Ação */}
        <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition cursor-pointer"
          >
            {cancelText}
          </button>

          <button
            type="button"
            onClick={onConfirm}
            className={`px-5 py-2 rounded-xl text-xs font-bold transition cursor-pointer ${getConfirmButtonClasses()}`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
};
