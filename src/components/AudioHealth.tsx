import React, { useState } from 'react';
import { Activity, AlertTriangle, ShieldAlert, CheckCircle2, RefreshCw, Trash2, Eye, Filter, ArrowRight, HelpCircle } from 'lucide-react';

interface AudioHealthProps {
  mp3Path: string;
  onAddLog: (message: string) => void;
  onOpenFileInFinder?: (filePath: string) => void;
  onMoveToTrash?: (filePath: string, itemId: string) => Promise<boolean>;
}

export const AudioHealth: React.FC<AudioHealthProps> = ({
  mp3Path,
  onAddLog,
  onOpenFileInFinder,
  onMoveToTrash
}) => {
  const [items, setItems] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [filterMode, setFilterMode] = useState<'issues' | 'all'>('issues');
  const [minDuration, setMinDuration] = useState<number>(60);
  const [totalScanned, setTotalScanned] = useState<number>(0);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);

  const loadHealthScan = async () => {
    if (!mp3Path) {
      alert('Selecione a pasta MP3 antes de escanear.');
      return;
    }

    setIsLoading(true);
    onAddLog(`🩺 Audio Health: Iniciando auditoria de integridade física das faixas em ${mp3Path}...`);

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('scan_audio_health', {
          mp3Path,
          minDuration,
          limit: 100,
          offset: 0,
          all: filterMode === 'all'
        });
        const data = JSON.parse(resJson);

        if (data.sucesso) {
          setItems(data.items || []);
          setTotalScanned(data.total_analisadas || 0);
          onAddLog(`✅ Audio Health: Auditoria concluída. ${data.total_analisadas} faixas analisadas (${data.items?.length || 0} listadas com atenção).`);
        } else {
          onAddLog(`❌ Erro no scanner de saúde: ${data.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Falha ao invocar scan_audio_health: ${e}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleTrashSingle = async (item: any) => {
    if (!onMoveToTrash) return;
    const confirmed = window.confirm(`Deseja mover esta faixa com problema para a Lixeira?\n\nArquivo: ${item.arquivo}\nMotivo: ${item.detalhes}`);
    if (!confirmed) return;

    const ok = await onMoveToTrash(item.caminho, item.id);
    if (ok) {
      setItems(prev => prev.filter(i => i.id !== item.id));
    }
  };

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl p-4 shadow-2xl flex flex-col h-full flex-1 overflow-hidden min-h-0 space-y-3">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between pb-2.5 border-b border-serato-cardBorder shrink-0 gap-2">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Activity className="w-4 h-4 text-rose-500" />
            <span>Audio Health Doctor (Auditoria de Faixas Quebradas & Integridade)</span>
            <span className="text-[10px] bg-rose-950/60 text-rose-400 px-2 py-0.5 rounded-full border border-rose-800/40 font-mono">
              Detecta Downloads Interrompidos & Curtas
            </span>
          </h3>
          <p className="text-[11px] text-serato-muted">
            Rastreia faixas cortadas no meio (1:30 min), áudios incompletos, vinhetas menores que 60s e arquivos com erro de reprodução.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={loadHealthScan}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-rose-600 hover:bg-rose-500 text-white shadow-lg shadow-rose-950/40 transition disabled:opacity-40 cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>{isLoading ? 'Analisando integridade...' : '🩺 Auditar Saúde do Áudio'}</span>
          </button>
        </div>
      </div>

      {/* Opções de Filtro */}
      <div className="bg-serato-card p-2.5 rounded-lg border border-serato-cardBorder flex flex-wrap items-center justify-between text-xs text-slate-300 shrink-0 gap-2">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <Filter className="w-3.5 h-3.5 text-serato-cyan" />
            <span>Exibir:</span>
            <select
              value={filterMode}
              onChange={(e) => setFilterMode(e.target.value as any)}
              className="bg-serato-dark border border-serato-cardBorder rounded px-2 py-0.5 text-white"
            >
              <option value="issues">Apenas com Problemas / Suspeitas</option>
              <option value="all">Todas as Faixas Analisadas</option>
            </select>
          </div>

          <div className="flex items-center gap-1.5 ml-2">
            <span>Duração Mínima:</span>
            <select
              value={minDuration}
              onChange={(e) => setMinDuration(Number(e.target.value))}
              className="bg-serato-dark border border-serato-cardBorder rounded px-2 py-0.5 text-white"
            >
              <option value={30}>30 segundos</option>
              <option value={60}>60 segundos (1 min)</option>
              <option value={90}>90 segundos (1:30 min)</option>
              <option value={120}>120 segundos (2 min)</option>
            </select>
          </div>
        </div>

        <div className="text-serato-muted font-mono text-[11px]">
          Analisadas: <b className="text-white">{totalScanned.toLocaleString()}</b>
        </div>
      </div>

      {/* Tabela de Diagnóstico */}
      <div className="flex-1 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20">
        <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder text-xs text-serato-muted font-mono flex items-center justify-between">
          <span>{items.length} Faixas em Destaque</span>
          <span>Diagnóstico de Reprodução & Qualidade</span>
        </div>

        <div className="overflow-y-auto flex-1 p-2 space-y-2">
          {items.length === 0 ? (
            <div className="py-12 text-center text-slate-500 text-xs">
              <CheckCircle2 className="w-8 h-8 opacity-20 text-emerald-400 mx-auto mb-2" />
              <p className="font-semibold text-slate-300">Nenhum problema detectado até o momento.</p>
              <p className="text-slate-600 mt-1">Clique em "Auditar Saúde do Áudio" para varrer o acervo.</p>
            </div>
          ) : (
            items.map((item) => (
              <div
                key={item.id}
                className={`border rounded-lg p-2.5 flex items-center justify-between gap-3 text-xs ${
                  item.status === 'saudavel'
                    ? 'bg-serato-card border-serato-cardBorder'
                    : item.tipo_problema === 'truncada_cortada' || item.severidade === 'critica'
                    ? 'bg-rose-950/20 border-rose-900/40'
                    : 'bg-amber-950/20 border-amber-900/40'
                }`}
              >
                <div className="flex items-center gap-3 truncate max-w-2xl">
                  {/* Badge de Status */}
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase shrink-0 font-mono ${
                      item.status === 'saudavel'
                        ? 'bg-emerald-950 text-emerald-400 border border-emerald-800/40'
                        : item.tipo_problema === 'truncada_cortada'
                        ? 'bg-rose-950 text-rose-300 border border-rose-800 font-black'
                        : 'bg-amber-950 text-amber-300 border border-amber-800'
                    }`}
                  >
                    {item.tipo_problema === 'truncada_cortada'
                      ? '⚠️ CORTADA / QUEBRADA'
                      : item.tipo_problema === 'muito_curta'
                      ? '⏳ MUITO CURTA'
                      : item.tipo_problema === 'baixa_fidelidade'
                      ? '📉 BAIXA QUALIDADE'
                      : item.status.toUpperCase()}
                  </span>

                  <div className="truncate">
                    <div className="font-semibold text-white truncate" title={item.arquivo}>
                      {item.arquivo}
                    </div>
                    <div className="text-[10px] text-slate-400 truncate mt-0.5">
                      {item.detalhes} • <span className="text-slate-500">({item.pasta})</span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0 font-mono text-[11px]">
                  <span className="text-slate-300">{item.duracao_seg}s</span>
                  {item.bitrate_kbps > 0 && (
                    <span className="text-serato-cyan">{item.bitrate_kbps} kbps</span>
                  )}

                  {onOpenFileInFinder && (
                    <button
                      type="button"
                      onClick={() => onOpenFileInFinder(item.caminho)}
                      className="p-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-300 ml-1 cursor-pointer"
                      title="Revelar no Finder"
                    >
                      <Eye className="w-3.5 h-3.5 text-serato-cyan" />
                    </button>
                  )}

                  {onMoveToTrash && item.status !== 'saudavel' && (
                    <button
                      type="button"
                      onClick={() => handleTrashSingle(item)}
                      className="p-1 rounded bg-rose-950/40 hover:bg-rose-900 text-rose-300 border border-rose-800/50 cursor-pointer"
                      title="Mover arquivo quebrado para Lixeira"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
