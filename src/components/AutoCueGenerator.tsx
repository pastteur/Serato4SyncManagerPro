import React, { useState, useEffect, useMemo } from 'react';
import { Target, Sparkles, CheckCircle2, Play, Music, ArrowRight, RefreshCw, Layers, FolderTree, Zap, Eye, Search } from 'lucide-react';
import { CrateInfo } from './TagDoctor';
import { ConfirmModal } from './ConfirmModal';

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

  // Crate & Subcrate selection
  const [cratesList, setCratesList] = useState<CrateInfo[]>([]);
  const [selectedCrate, setSelectedCrate] = useState<string>('');
  const [selectedSubcrate, setSelectedSubcrate] = useState<string>('');
  const [includeSubcrates, setIncludeSubcrates] = useState<boolean>(true);

  // Crate Tracks Table
  const [tracks, setTracks] = useState<any[]>([]);
  const [totalTracks, setTotalTracks] = useState<number>(0);
  const [gravadasCount, setGravadasCount] = useState<number>(0);
  const [pendentesCount, setPendentesCount] = useState<number>(0);
  const [selectedTrackIds, setSelectedTrackIds] = useState<Set<string>>(new Set());

  // Batch Generation State
  const [isBatchRunning, setIsBatchRunning] = useState<boolean>(false);
  const [batchProgress, setBatchProgress] = useState<{
    processados: number;
    total: number;
    percentual: number;
    atualizados: number;
    faixa_atual: string;
  } | null>(null);

  // Modal de Confirmação em Tela (sem popups nativos que travam)
  const [modalConfig, setModalConfig] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    detail?: string;
    confirmText?: string;
    variant?: 'danger' | 'warning' | 'info';
    onConfirm: () => void;
  }>({
    isOpen: false,
    title: '',
    message: '',
    onConfirm: () => {}
  });

  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
  const activeCrateData = cratesList.find(c => c.nome === selectedCrate);

  // Filtros de busca e status para Hot Cues
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'pending' | 'hasCues' | 'selected'>('all');

  const filteredTracks = useMemo(() => {
    let result = [...tracks];
    if (searchTerm.trim()) {
      const q = searchTerm.toLowerCase();
      result = result.filter(t =>
        t.arquivo.toLowerCase().includes(q) ||
        t.pasta.toLowerCase().includes(q) ||
        t.caminho.toLowerCase().includes(q)
      );
    }
    if (statusFilter === 'pending') {
      result = result.filter(t => !t.tem_cues);
    } else if (statusFilter === 'hasCues') {
      result = result.filter(t => t.tem_cues);
    } else if (statusFilter === 'selected') {
      result = result.filter(t => selectedTrackIds.has(t.id));
    }
    return result;
  }, [tracks, searchTerm, statusFilter, selectedTrackIds]);

  // Carrega lista de Crates
  const loadCrates = async () => {
    if (!mp3Path) return;
    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('list_crates_tag_doctor', { mp3Path });
        const data = JSON.parse(resJson);
        if (data.sucesso && data.crates) {
          setCratesList(data.crates);
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Carrega faixas da Crate selecionada
  const loadCrateTracks = async (crate: string = selectedCrate, sub: string = selectedSubcrate, inc: boolean = includeSubcrates) => {
    if (!mp3Path) return;
    setIsLoading(true);
    onAddLog(`🎯 Auto-Cue: Mapeando faixas na crate "${crate || 'Todas'}"...`);

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('scan_crate_cues', {
          mp3Path,
          crateRaiz: crate || null,
          subcrate: sub || null,
          includeSubcrates: inc,
          limit: 200,
          offset: 0
        });
        const data = JSON.parse(resJson);
        if (data.sucesso) {
          setTracks(data.items || []);
          setTotalTracks(data.total || 0);
          setGravadasCount(data.gravadas || 0);
          setPendentesCount(data.pendentes || 0);
          onAddLog(`✅ Auto-Cue: ${data.total} faixas mapeadas (${data.gravadas} já com Hot Cues, ${data.pendentes} pendentes).`);
        } else {
          onAddLog(`❌ Erro no scan de cues: ${data.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Falha: ${e}`);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadCrates();
  }, [mp3Path]);

  // Listener para batch cues
  useEffect(() => {
    let unlistenProgress: (() => void) | undefined;
    let unlistenFinished: (() => void) | undefined;

    const setupListeners = async () => {
      if (isTauri) {
        const { listen } = await import('@tauri-apps/api/event');
        unlistenProgress = await listen<any>('auto-cue-batch-progress', (event) => {
          const payload = event.payload;
          setBatchProgress({
            processados: payload.processados || 0,
            total: payload.total || 0,
            percentual: payload.percentual || 0,
            atualizados: payload.atualizados || 0,
            faixa_atual: payload.faixa_atual || '',
          });
        });

        unlistenFinished = await listen<any>('auto-cue-batch-finished', (event) => {
          const payload = event.payload;
          setIsBatchRunning(false);
          setBatchProgress(null);
          if (payload.sucesso) {
            onAddLog(`🎉 Auto-Cues gerados com sucesso! ${payload.atualizados} faixas preparadas.`);
            loadCrateTracks(selectedCrate, selectedSubcrate, includeSubcrates);
          } else {
            onAddLog(`❌ Erro no lote de Auto-Cues: ${payload.erro || 'Desconhecido'}`);
          }
        });
      }
    };

    setupListeners();
    return () => {
      if (unlistenProgress) unlistenProgress();
      if (unlistenFinished) unlistenFinished();
    };
  }, []);

  // Calcula prévia para a faixa clicada
  const handleSelectTrackForPreview = async (trackPath: string) => {
    setSelectedFile(trackPath);
    setIsLoading(true);
    onAddLog(`🎯 Auto-Cue: Calculando os 5 Hot Cues para: ${trackPath.split('/').pop()}...`);

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('preview_auto_cues', {
          filepath: trackPath
        });
        const data = JSON.parse(resJson);
        if (data.sucesso) {
          setCuePreview(data);
          onAddLog(`✅ Hot Cues calculados (${data.bpm || 'Auto'} BPM · ${roundSec(data.duracao)}s).`);
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

  // Grava Hot Cues na música ativa
  const handleApplySingle = async () => {
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
          onAddLog(`🎯 ${data.mensagem}`);
          setTracks(prev => prev.map(t => t.caminho === selectedFile ? { ...t, tem_cues: true, status: 'Gravado' } : t));
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

  // Gravação em lote para toda a Crate
  const handleBatchApplyCrate = (onlyPending: boolean = false) => {
    const scopeLabel = selectedSubcrate
      ? `Subcrate "${selectedCrate} -> ${selectedSubcrate}"`
      : selectedCrate
        ? `Crate "${selectedCrate}" ${includeSubcrates ? '(e todas as suas subcrates)' : '(apenas faixas na raiz)'}`
        : 'Toda a Biblioteca';

    const countLabel = onlyPending ? `${pendentesCount} faixas pendentes` : `${totalTracks} faixas`;

    setModalConfig({
      isOpen: true,
      title: 'Geração e Gravação em Massa de Hot Cues',
      message: `Deseja gerar e gravar os 5 Hot Cues oficiais do Serato em ${countLabel}?`,
      detail: `Escopo: ${scopeLabel}\nOs marcadores serão gravados em GEOB:Serato Markers2 para acionamento direto nos pads do controlador.`,
      confirmText: 'Gravar Hot Cues',
      variant: 'warning',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsBatchRunning(true);
        setBatchProgress({
          processados: 0,
          total: totalTracks,
          percentual: 0,
          atualizados: 0,
          faixa_atual: 'Iniciando cálculo e gravação...'
        });

        onAddLog(`⚡ Disparando geração em lote de Hot Cues para ${scopeLabel}...`);

        try {
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            await invoke('batch_apply_crate_cues', {
              mp3Path,
              crateRaiz: selectedCrate || null,
              subcrate: selectedSubcrate || null,
              includeSubcrates,
              onlyPending
            });
          }
        } catch (e) {
          setIsBatchRunning(false);
          setBatchProgress(null);
          onAddLog(`❌ Erro ao disparar lote: ${e}`);
        }
      }
    });
  };

  const roundSec = (val: number) => Math.round(val || 0);
  const formatTime = (ms: number) => {
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec < 10 ? '0' : ''}${sec}`;
  };

  const toggleSelectTrack = (id: string) => {
    setSelectedTrackIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedTrackIds.size === tracks.length) {
      setSelectedTrackIds(new Set());
    } else {
      setSelectedTrackIds(new Set(tracks.map(t => t.id)));
    }
  };

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl p-4 shadow-2xl flex flex-col h-full flex-1 overflow-hidden min-h-0 space-y-3 relative">
      
      {/* Top Banner & Ações */}
      <div className="flex flex-wrap items-center justify-between pb-2.5 border-b border-serato-cardBorder shrink-0 gap-2">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Target className="w-4 h-4 text-serato-gold" />
            <span>Auto-Cue Generator (Geração Automática de Hot Cues por Crate)</span>
            <span className="text-[10px] bg-serato-gold/20 text-serato-gold px-2 py-0.5 rounded-full border border-serato-gold/30 font-mono">
              Intro • Drop 1 • Break • Drop 2 • Outro
            </span>
          </h3>
          <p className="text-[11px] text-serato-muted">
            Separação por Crates/Subcrates: calcula os 5 pontos de mixagem ideais e grava nas tags do Serato DJ Pro.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Botão Gerar nas Pendentes */}
          <button
            type="button"
            onClick={() => handleBatchApplyCrate(true)}
            disabled={isLoading || isBatchRunning || pendentesCount === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-600 transition disabled:opacity-30 cursor-pointer"
            title="Gera Hot Cues apenas nas faixas que ainda não possuem marcadores"
          >
            <Sparkles className="w-3.5 h-3.5 text-serato-gold" />
            <span>Gerar nas Pendentes ({pendentesCount})</span>
          </button>

          {/* Botão Gerar em Toda a Crate */}
          <button
            type="button"
            onClick={() => handleBatchApplyCrate(false)}
            disabled={isLoading || isBatchRunning || totalTracks === 0}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold bg-gradient-to-r from-serato-gold via-amber-500 to-serato-orange hover:opacity-90 text-black shadow-lg shadow-serato-gold/20 transition disabled:opacity-40 cursor-pointer"
            title="Gera Hot Cues para todas as faixas desta Crate"
          >
            <Zap className={`w-3.5 h-3.5 ${isBatchRunning ? 'animate-bounce' : ''}`} />
            <span>{isBatchRunning ? 'Gravando Cues...' : `⚡ Gerar na Crate (${totalTracks})`}</span>
          </button>

          {/* Botão Mapear Crate */}
          <button
            type="button"
            onClick={() => loadCrateTracks(selectedCrate, selectedSubcrate, includeSubcrates)}
            disabled={isLoading || isBatchRunning}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-serato-card hover:bg-serato-gold/20 text-serato-gold border border-serato-gold/40 transition disabled:opacity-40 cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>{isLoading ? 'Mapeando...' : '🔍 Mapear Crate'}</span>
          </button>
        </div>
      </div>

      {/* Seletor de Crate & Subcrate */}
      <div className="bg-serato-header/70 border border-serato-cardBorder p-2.5 rounded-lg flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-bold text-slate-300 flex items-center gap-1.5">
            <FolderTree className="w-4 h-4 text-serato-gold" />
            <span>Selecionar Crate:</span>
          </span>

          <select
            value={selectedCrate}
            onChange={(e) => {
              const val = e.target.value;
              setSelectedCrate(val);
              setSelectedSubcrate('');
              loadCrateTracks(val, '', includeSubcrates);
            }}
            className="bg-serato-dark border border-serato-cardBorder text-slate-200 text-xs font-semibold rounded px-2.5 py-1.5 focus:outline-none cursor-pointer max-w-[220px]"
          >
            <option value="">📁 Todas as Crates (Biblioteca)</option>
            {cratesList.map(c => (
              <option key={c.nome} value={c.nome}>📁 {c.nome} ({c.total} faixas)</option>
            ))}
          </select>

          {selectedCrate && (
            <div className="flex items-center gap-2 ml-1">
              <label className="flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer bg-serato-dark px-2 py-1 rounded border border-serato-cardBorder">
                <input
                  type="checkbox"
                  checked={includeSubcrates && !selectedSubcrate}
                  onChange={(e) => {
                    const inc = e.target.checked;
                    setIncludeSubcrates(inc);
                    loadCrateTracks(selectedCrate, selectedSubcrate, inc);
                  }}
                  disabled={!!selectedSubcrate || isBatchRunning}
                  className="rounded border-slate-700 bg-serato-dark text-serato-gold focus:ring-0"
                />
                <span className="text-[11px] font-medium">Incluir todas as subcrates</span>
              </label>

              {activeCrateData && activeCrateData.subcrates.length > 0 && (
                <select
                  value={selectedSubcrate}
                  onChange={(e) => {
                    const sub = e.target.value;
                    setSelectedSubcrate(sub);
                    loadCrateTracks(selectedCrate, sub, includeSubcrates);
                  }}
                  className="bg-serato-dark border border-serato-cardBorder text-serato-cyan text-xs font-semibold rounded px-2.5 py-1.5 focus:outline-none cursor-pointer max-w-[180px]"
                >
                  <option value="">↳ Todas as Subcrates</option>
                  {activeCrateData.subcrates.map(sub => (
                    <option key={sub.caminho_rel} value={sub.caminho_rel}>↳ {sub.nome}</option>
                  ))}
                </select>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center gap-4 text-xs font-mono">
          <span className="text-slate-400">Total: <b className="text-white">{totalTracks}</b></span>
          <span className="text-slate-400">Com Hot Cues: <b className="text-serato-neonGreen">{gravadasCount}</b></span>
          <span className="text-slate-400">Pendentes: <b className="text-serato-gold">{pendentesCount}</b></span>
        </div>
      </div>

      {/* Banner de Progresso do Lote */}
      {isBatchRunning && batchProgress && (
        <div className="bg-amber-950/40 border border-serato-gold/50 p-3 rounded-xl shadow-xl flex flex-col gap-1.5 shrink-0 animate-pulse">
          <div className="flex items-center justify-between text-xs font-bold text-white">
            <span className="flex items-center gap-2 text-serato-gold">
              <Zap className="w-4 h-4 text-serato-gold animate-bounce" />
              <span>Gravando Hot Cues oficiais em lote: {selectedCrate ? `Crate "${selectedCrate}"` : 'Biblioteca'}...</span>
            </span>
            <span className="font-mono text-serato-gold">
              {batchProgress.percentual}% ({batchProgress.processados} / {batchProgress.total})
            </span>
          </div>

          <div className="w-full bg-slate-900 rounded-full h-2.5 border border-serato-cardBorder overflow-hidden">
            <div
              className="bg-gradient-to-r from-serato-gold via-amber-400 to-serato-orange h-2.5 transition-all duration-200"
              style={{ width: `${Math.min(100, Math.max(1, batchProgress.percentual))}%` }}
            />
          </div>

          <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono truncate">
            <span className="truncate max-w-[70%]">
              🎵 Faixa atual: <b className="text-slate-200">{batchProgress.faixa_atual}</b>
            </span>
            <span className="text-serato-neonGreen font-semibold">
              ✅ {batchProgress.atualizados} marcadas no Serato
            </span>
          </div>
        </div>
      )}

      {/* Área Principal: Lista de Faixas da Crate & Prévia dos Cues */}
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-3 min-h-0 overflow-hidden">
        
        {/* Coluna Esquerda: Tabela de Músicas da Crate (7 cols) */}
        <div className="lg:col-span-7 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20">
          <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder text-xs text-serato-muted font-mono flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={filteredTracks.length > 0 && selectedTrackIds.size === filteredTracks.length}
                onChange={toggleSelectAll}
                className="rounded border-slate-700 bg-serato-dark text-serato-gold focus:ring-0"
              />
              <span>Faixas ({filteredTracks.length} de {tracks.length})</span>
            </div>
            <span>Clique para Prévia dos 5 Cues</span>
          </div>

          {/* Barra de Busca e Filtros Rápidos de Cues */}
          <div className="bg-serato-dark/60 p-2 border-b border-serato-cardBorder flex flex-wrap items-center justify-between gap-2 shrink-0">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="w-3.5 h-3.5 text-serato-muted absolute left-2.5 top-2.5" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Filtrar por nome de faixa, pasta ou caminho..."
                className="w-full pl-8 pr-3 py-1.5 text-xs bg-serato-dark border border-serato-cardBorder rounded-lg text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-gold transition font-sans"
              />
            </div>

            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => setStatusFilter('all')}
                className={`text-[11px] px-2 py-0.5 rounded-lg font-medium transition cursor-pointer border ${
                  statusFilter === 'all'
                    ? 'bg-serato-card text-white border-serato-gold/50 shadow-sm'
                    : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
                }`}
              >
                Todas ({tracks.length})
              </button>
              <button
                type="button"
                onClick={() => setStatusFilter('pending')}
                className={`text-[11px] px-2 py-0.5 rounded-lg font-medium transition cursor-pointer border ${
                  statusFilter === 'pending'
                    ? 'bg-amber-950/60 text-amber-300 border-amber-600/60 shadow-sm'
                    : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
                }`}
              >
                Pendentes ({pendentesCount})
              </button>
              <button
                type="button"
                onClick={() => setStatusFilter('hasCues')}
                className={`text-[11px] px-2 py-0.5 rounded-lg font-medium transition cursor-pointer border ${
                  statusFilter === 'hasCues'
                    ? 'bg-emerald-950/60 text-emerald-300 border-emerald-600/60 shadow-sm'
                    : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
                }`}
              >
                Com Cues ({gravadasCount})
              </button>
            </div>
          </div>

          <div className="overflow-y-auto flex-1 divide-y divide-serato-cardBorder/40">
            {filteredTracks.length === 0 ? (
              <div className="py-16 text-center text-slate-500 text-xs">
                <Music className="w-8 h-8 opacity-20 text-serato-gold mx-auto mb-2" />
                <p className="font-semibold text-slate-300">Nenhuma faixa encontrada com os filtros selecionados.</p>
                <p className="text-slate-600 mt-1">Ajuste o termo de busca ou selecione outra Crate.</p>
              </div>
            ) : (
              filteredTracks.map((t) => {
                const isCurrent = selectedFile === t.caminho;
                const isSelected = selectedTrackIds.has(t.id);

                return (
                  <div
                    key={t.id}
                    onClick={() => handleSelectTrackForPreview(t.caminho)}
                    className={`p-2.5 flex items-center justify-between gap-3 text-xs cursor-pointer transition ${
                      isCurrent
                        ? 'bg-amber-950/30 border-l-2 border-serato-gold'
                        : 'hover:bg-white/[0.03]'
                    }`}
                  >
                    <div className="flex items-center gap-2.5 truncate max-w-md">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={(e) => {
                          e.stopPropagation();
                          toggleSelectTrack(t.id);
                        }}
                        className="rounded border-slate-700 bg-serato-dark text-serato-gold focus:ring-0"
                      />

                      <div className="truncate">
                        <div className={`font-semibold truncate ${isCurrent ? 'text-serato-gold' : 'text-slate-200'}`}>
                          {t.arquivo}
                        </div>
                        <div className="text-[10px] text-slate-500 truncate font-mono">
                          {t.pasta}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0 font-mono text-[11px]">
                      {t.bpm > 0 && (
                        <span className="text-slate-400">{t.bpm} BPM</span>
                      )}
                      <span className="text-slate-500">{t.duracao_seg}s</span>

                      {t.tem_cues ? (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-950 text-emerald-400 border border-emerald-800/40 font-bold">
                          🎯 Gravado
                        </span>
                      ) : (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-950 text-amber-300 border border-amber-800/40 font-bold">
                          ⏳ Pendente
                        </span>
                      )}

                      {onOpenFileInFinder && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onOpenFileInFinder(t.caminho);
                          }}
                          className="p-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-300"
                          title="Revelar no Finder"
                        >
                          <Eye className="w-3.5 h-3.5 text-serato-cyan" />
                        </button>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Coluna Direita: Pré-visualização Métrica e Gravação Individual (5 cols) */}
        <div className="lg:col-span-5 border border-serato-cardBorder rounded-lg p-3 bg-serato-card/20 flex flex-col justify-between overflow-y-auto space-y-3">
          <div>
            <div className="flex items-center justify-between pb-2 border-b border-serato-cardBorder">
              <span className="text-xs font-bold text-white flex items-center gap-1.5">
                <Target className="w-4 h-4 text-serato-gold" />
                <span>Prévia dos 5 Hot Cues</span>
              </span>

              {cuePreview && (
                <button
                  type="button"
                  onClick={handleApplySingle}
                  disabled={isApplying}
                  className="px-3 py-1 rounded bg-serato-neonGreen hover:bg-emerald-400 text-black text-xs font-bold transition cursor-pointer flex items-center gap-1"
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>{isApplying ? 'Gravando...' : 'Gravar Cues'}</span>
                </button>
              )}
            </div>

            {!cuePreview ? (
              <div className="py-20 text-center text-slate-500 text-xs">
                <Layers className="w-8 h-8 opacity-20 text-serato-gold mx-auto mb-2" />
                <p className="font-semibold text-slate-400">Nenhuma faixa selecionada para prévia.</p>
                <p className="text-[11px] text-slate-600 mt-1">Clique em qualquer faixa na lista à esquerda para calcular a métrica de Hot Cues.</p>
              </div>
            ) : (
              <div className="space-y-3 pt-2">
                <div className="text-xs text-slate-300 font-mono">
                  Faixa: <b className="text-white truncate block">{selectedFile.split('/').pop()}</b>
                  Duração: <b className="text-serato-cyan">{roundSec(cuePreview.duracao)}s</b> | BPM: <b className="text-serato-gold">{cuePreview.bpm || 'Auto'}</b>
                </div>

                {/* Linha do Tempo */}
                <div className="space-y-1">
                  <span className="text-[10px] text-serato-muted uppercase font-mono">Linha do Tempo Visual:</span>
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

                {/* Pads do Controlador */}
                <div className="space-y-1.5 pt-1">
                  <span className="text-[10px] text-serato-muted uppercase font-mono">Mapeamento dos Pads no Controlador:</span>
                  <div className="grid grid-cols-1 sm:grid-cols-5 gap-1.5">
                    {cuePreview.cues.map((c: any) => (
                      <div
                        key={c.index}
                        className="bg-serato-card border border-serato-cardBorder p-2 rounded-lg text-center space-y-0.5"
                      >
                        <div className="flex items-center justify-center gap-1">
                          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: c.color_hex }} />
                          <span className="text-[9px] font-bold text-slate-300 uppercase font-mono">Pad {c.index + 1}</span>
                        </div>
                        <div className="font-bold text-white text-[11px] truncate">{c.label}</div>
                        <div className="text-[10px] font-mono font-bold text-serato-cyan">{formatTime(c.pos_ms)}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <ConfirmModal
        isOpen={modalConfig.isOpen}
        title={modalConfig.title}
        message={modalConfig.message}
        detail={modalConfig.detail}
        confirmText={modalConfig.confirmText}
        variant={modalConfig.variant}
        onConfirm={modalConfig.onConfirm}
        onCancel={() => setModalConfig(prev => ({ ...prev, isOpen: false }))}
      />
    </div>
  );
};
