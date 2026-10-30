import React, { useState, useEffect } from 'react';
import { Activity, AlertTriangle, ShieldAlert, CheckCircle2, RefreshCw, Trash2, Eye, Filter, ArrowRight, Globe, Zap, DownloadCloud, FolderTree } from 'lucide-react';
import { CrateInfo } from './TagDoctor';
import { ConfirmModal } from './ConfirmModal';

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
  const [selectedCategory, setSelectedCategory] = useState<string>('todas');
  const [maxDuration, setMaxDuration] = useState<number>(60);
  const [totalScanned, setTotalScanned] = useState<number>(0);
  const [totalIssues, setTotalIssues] = useState<number>(0);
  const [categoryCounts, setCategoryCounts] = useState<{
    truncada: number;
    curta: number;
    baixa_qualidade: number;
    corrompida: number;
  }>({ truncada: 0, curta: 0, baixa_qualidade: 0, corrompida: 0 });

  // Crates
  const [cratesList, setCratesList] = useState<CrateInfo[]>([]);
  const [selectedCrate, setSelectedCrate] = useState<string>('');
  const [selectedSubcrate, setSelectedSubcrate] = useState<string>('');
  const [includeSubcrates, setIncludeSubcrates] = useState<boolean>(true);

  // Seleção e Reparação Online
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isRepairingOnline, setIsRepairingOnline] = useState<boolean>(false);
  const [repairProgress, setRepairProgress] = useState<{
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

  // Carrega Crates
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

  // Carrega Auditoria
  const loadHealthScan = async (cat: string = selectedCategory, dur: number = maxDuration) => {
    if (!mp3Path) {
      onAddLog('⚠️ Selecione a pasta MP3 antes de escanear.');
      return;
    }

    setIsLoading(true);
    const scopeLabel = selectedSubcrate
      ? `Subcrate: ${selectedCrate} -> ${selectedSubcrate}`
      : selectedCrate
        ? `Crate: ${selectedCrate}`
        : 'Biblioteca Completa';

    onAddLog(`🩺 Audio Health: Auditando saúde de ${scopeLabel} (Teto de faixa curta: < ${dur}s)...`);

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('scan_audio_health', {
          mp3Path,
          crateRaiz: selectedCrate || null,
          subcrate: selectedSubcrate || null,
          includeSubcrates,
          maxDuration: dur,
          categoria: cat,
          limit: 300,
          offset: 0
        });
        const data = JSON.parse(resJson);

        if (data.sucesso) {
          setItems(data.items || []);
          setTotalScanned(data.total_analisadas || 0);
          setTotalIssues(data.total_problemas || 0);
          if (data.categorias_contagem) {
            setCategoryCounts(data.categorias_contagem);
          }
          setSelectedIds(new Set((data.items || []).map((i: any) => i.id)));
          onAddLog(`✅ Audio Health: ${data.total_analisadas} faixas analisadas. ${data.total_problemas} evidências encontradas.`);
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

  useEffect(() => {
    loadCrates();
  }, [mp3Path]);

  // Listener de streaming para reparação online
  useEffect(() => {
    let unlistenProgress: (() => void) | undefined;
    let unlistenFinished: (() => void) | undefined;

    const setupListeners = async () => {
      if (isTauri) {
        const { listen } = await import('@tauri-apps/api/event');
        unlistenProgress = await listen<any>('audio-health-batch-progress', (event) => {
          const payload = event.payload;
          setRepairProgress({
            processados: payload.processados || 0,
            total: payload.total || 0,
            percentual: payload.percentual || 0,
            atualizados: payload.atualizados || 0,
            faixa_atual: payload.faixa_atual || '',
          });
        });

        unlistenFinished = await listen<any>('audio-health-batch-finished', (event) => {
          const payload = event.payload;
          setIsRepairingOnline(false);
          setRepairProgress(null);
          if (payload.sucesso) {
            onAddLog(`🎉 Correção Online concluída! ${payload.atualizados} faixas substituídas com versões 320kbps de alta fidelidade.`);
            loadHealthScan(selectedCategory, maxDuration);
          } else {
            onAddLog(`❌ Erro na correção online: ${payload.erro || 'Desconhecido'}`);
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

  // Mover faixa individual para lixeira
  const handleTrashSingle = (item: any) => {
    if (!onMoveToTrash) return;
    setModalConfig({
      isOpen: true,
      title: 'Mover Faixa Danificada para a Lixeira',
      message: `Deseja mover esta faixa com problema para a Lixeira?`,
      detail: `Arquivo: ${item.arquivo}\nMotivo: ${item.detalhes}`,
      confirmText: 'Mover para Lixeira',
      variant: 'danger',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        const ok = await onMoveToTrash(item.caminho, item.id);
        if (ok) {
          setItems(prev => prev.filter(i => i.id !== item.id));
          setSelectedIds(prev => {
            const next = new Set(prev);
            next.delete(item.id);
            return next;
          });
        }
      }
    });
  };

  // Mover selecionadas em massa para lixeira
  const handleTrashBatch = () => {
    if (!onMoveToTrash) return;
    const selectedItems = items.filter(i => selectedIds.has(i.id));
    if (selectedItems.length === 0) {
      onAddLog('⚠️ Selecione ao menos uma faixa para mover para a Lixeira.');
      return;
    }

    setModalConfig({
      isOpen: true,
      title: 'Mover Faixas Danificadas para a Lixeira',
      message: `Deseja mover as ${selectedItems.length} faixas com problemas selecionadas para a Lixeira?`,
      detail: 'As faixas selecionadas serão enviadas com segurança para o Lixo do macOS.',
      confirmText: `Mover ${selectedItems.length} faixas`,
      variant: 'danger',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        onAddLog(`🗑️ Movendo lote de ${selectedItems.length} faixas comprometidas para a Lixeira...`);
        let deletedCount = 0;

        for (const item of selectedItems) {
          const ok = await onMoveToTrash(item.caminho, item.id);
          if (ok) deletedCount++;
        }

        onAddLog(`✅ Concluído: ${deletedCount} faixas removidas para a Lixeira.`);
        setItems(prev => prev.filter(i => !selectedIds.has(i.id)));
        setSelectedIds(new Set());
      }
    });
  };

  // Correção online de uma única música
  const handleRepairSingleOnline = async (item: any) => {
    onAddLog(`🌐 Iniciando busca e download em 320kbps para: ${item.arquivo}...`);
    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('repair_track_online', {
          filepath: item.caminho
        });
        const data = JSON.parse(resJson);
        if (data.sucesso) {
          onAddLog(`🎉 ${item.arquivo}: ${data.mensagem}`);
          setItems(prev => prev.filter(i => i.id !== item.id));
        } else {
          onAddLog(`❌ Erro no download/substituição: ${data.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Falha: ${e}`);
    }
  };

  // Correção online em massa das selecionadas
  const handleRepairBatchOnline = () => {
    const selectedItems = items.filter(i => selectedIds.has(i.id));
    if (selectedItems.length === 0) {
      onAddLog('⚠️ Selecione ao menos uma música para reparar online.');
      return;
    }

    setModalConfig({
      isOpen: true,
      title: 'Correção Online e Substituição Automática',
      message: `Deseja buscar e substituir automaticamente as ${selectedItems.length} faixas selecionadas por versões completas em 320kbps?`,
      detail: 'Os arquivos originais corrompidos ou incompletos serão guardados em segurança na pasta de quarentena (~/SeratoSync/quarantine/).',
      confirmText: `Reparar ${selectedItems.length} faixas`,
      variant: 'warning',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsRepairingOnline(true);
        setRepairProgress({
          processados: 0,
          total: selectedItems.length,
          percentual: 0,
          atualizados: 0,
          faixa_atual: 'Iniciando downloads em alta qualidade...'
        });

        onAddLog(`🌐 Disparando correção online em massa de ${selectedItems.length} faixas via yt-dlp...`);

        try {
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            const filepaths = selectedItems.map(i => i.caminho);
            await invoke('batch_repair_online', {
              filepathsJson: JSON.stringify(filepaths)
            });
          }
        } catch (e) {
          setIsRepairingOnline(false);
          setRepairProgress(null);
          onAddLog(`❌ Falha na chamada da correção online: ${e}`);
        }
      }
    });
  };

  // Alterna seleção
  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === items.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map(i => i.id)));
    }
  };

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl p-4 shadow-2xl flex flex-col h-full flex-1 overflow-hidden min-h-0 space-y-3 relative">
      
      {/* Top Banner & Ações */}
      <div className="flex flex-wrap items-center justify-between pb-2.5 border-b border-serato-cardBorder shrink-0 gap-2">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Activity className="w-4 h-4 text-rose-500" />
            <span>Audio Health Doctor (Auditoria de Faixas Quebradas & Correção Online)</span>
            <span className="text-[10px] bg-rose-950/60 text-rose-400 px-2 py-0.5 rounded-full border border-rose-800/40 font-mono">
              320kbps Downloader Integrado
            </span>
          </h3>
          <p className="text-[11px] text-serato-muted">
            Rastreia cortes repentinos no meio da faixa, arquivos curtos (&lt; 60s), baixa fidelidade e substitui online automaticamente em 320kbps.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Mover Lote para Lixeira */}
          <button
            type="button"
            onClick={handleTrashBatch}
            disabled={isLoading || isRepairingOnline || selectedIds.size === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-rose-950/40 hover:bg-rose-900 text-rose-300 border border-rose-800/50 transition disabled:opacity-30 cursor-pointer"
            title="Move todas as faixas selecionadas para a Lixeira"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>Excluir Selecionadas ({selectedIds.size})</span>
          </button>

          {/* Botão de Correção Online */}
          <button
            type="button"
            onClick={handleRepairBatchOnline}
            disabled={isLoading || isRepairingOnline || selectedIds.size === 0}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold bg-gradient-to-r from-serato-cyan to-blue-500 hover:opacity-90 text-black shadow-lg shadow-serato-cyan/20 transition disabled:opacity-30 cursor-pointer"
            title="Busca e baixa versões completas em 320kbps substituindo as faixas selecionadas"
          >
            <DownloadCloud className={`w-3.5 h-3.5 ${isRepairingOnline ? 'animate-bounce' : ''}`} />
            <span>{isRepairingOnline ? 'Baixando em 320k...' : `🌐 Corrigir Online 320k (${selectedIds.size})`}</span>
          </button>

          {/* Botão de Auditoria */}
          <button
            type="button"
            onClick={() => loadHealthScan(selectedCategory, maxDuration)}
            disabled={isLoading || isRepairingOnline}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold bg-rose-600 hover:bg-rose-500 text-white shadow-lg shadow-rose-950/40 transition disabled:opacity-40 cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>{isLoading ? 'Analisando...' : '🩺 Auditar Saúde'}</span>
          </button>
        </div>
      </div>

      {/* Barra de Filtro de Crate e Duração Máxima Suspeita */}
      <div className="bg-serato-header/70 border border-serato-cardBorder p-2.5 rounded-lg flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-bold text-slate-300 flex items-center gap-1.5">
            <FolderTree className="w-4 h-4 text-serato-orange" />
            <span>Crate:</span>
          </span>

          <select
            value={selectedCrate}
            onChange={(e) => {
              setSelectedCrate(e.target.value);
              setSelectedSubcrate('');
            }}
            className="bg-serato-dark border border-serato-cardBorder text-slate-200 text-xs font-semibold rounded px-2.5 py-1 focus:outline-none cursor-pointer max-w-[200px]"
          >
            <option value="">📁 Todas as Crates (Biblioteca)</option>
            {cratesList.map(c => (
              <option key={c.nome} value={c.nome}>📁 {c.nome} ({c.total})</option>
            ))}
          </select>

          {selectedCrate && activeCrateData && activeCrateData.subcrates.length > 0 && (
            <select
              value={selectedSubcrate}
              onChange={(e) => setSelectedSubcrate(e.target.value)}
              className="bg-serato-dark border border-serato-cardBorder text-serato-cyan text-xs font-semibold rounded px-2.5 py-1 focus:outline-none cursor-pointer max-w-[180px]"
            >
              <option value="">↳ Todas as Subcrates</option>
              {activeCrateData.subcrates.map(sub => (
                <option key={sub.caminho_rel} value={sub.caminho_rel}>↳ {sub.nome}</option>
              ))}
            </select>
          )}

          {/* Duração Máxima Suspeita */}
          <div className="flex items-center gap-1.5 ml-3 bg-serato-dark px-2.5 py-1 rounded border border-serato-cardBorder">
            <span className="text-xs text-slate-300 font-medium">Pegar com duração menor que:</span>
            <select
              value={maxDuration}
              onChange={(e) => {
                const val = Number(e.target.value);
                setMaxDuration(val);
                loadHealthScan(selectedCategory, val);
              }}
              className="bg-slate-900 border border-slate-700 text-serato-gold text-xs font-bold rounded px-2 py-0.5"
            >
              <option value={30}>30 segundos</option>
              <option value={60}>60 segundos (1 min)</option>
              <option value={90}>90 segundos (1:30 min)</option>
              <option value={120}>120 segundos (2 min)</option>
            </select>
          </div>
        </div>

        <div className="text-serato-muted font-mono text-xs">
          Analisadas: <b className="text-white">{totalScanned.toLocaleString()}</b> • Evidências: <b className="text-rose-400">{totalIssues.toLocaleString()}</b>
        </div>
      </div>

      {/* Tabs / Chips de Destaque por Tipo de Problema */}
      <div className="flex items-center gap-2 overflow-x-auto shrink-0 pb-1">
        <button
          type="button"
          onClick={() => {
            setSelectedCategory('todas');
            loadHealthScan('todas', maxDuration);
          }}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold transition cursor-pointer border ${
            selectedCategory === 'todas'
              ? 'bg-slate-800 text-white border-serato-cyan shadow'
              : 'bg-serato-card text-slate-400 border-serato-cardBorder hover:text-white'
          }`}
        >
          <span>Todos os Problemas</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-slate-900 font-mono text-serato-cyan">
            {totalIssues}
          </span>
        </button>

        <button
          type="button"
          onClick={() => {
            setSelectedCategory('truncada');
            loadHealthScan('truncada', maxDuration);
          }}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold transition cursor-pointer border ${
            selectedCategory === 'truncada'
              ? 'bg-rose-950 text-rose-200 border-rose-500 shadow'
              : 'bg-serato-card text-rose-400/80 border-serato-cardBorder hover:text-rose-200'
          }`}
        >
          <span>🚨 Corte Repentino / Truncadas</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-rose-950 font-mono text-rose-300">
            {categoryCounts.truncada}
          </span>
        </button>

        <button
          type="button"
          onClick={() => {
            setSelectedCategory('curta');
            loadHealthScan('curta', maxDuration);
          }}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold transition cursor-pointer border ${
            selectedCategory === 'curta'
              ? 'bg-amber-950 text-amber-200 border-amber-500 shadow'
              : 'bg-serato-card text-amber-400/80 border-serato-cardBorder hover:text-amber-200'
          }`}
        >
          <span>✂️ Curtas / Jingles (&lt; {maxDuration}s)</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-amber-950 font-mono text-amber-300">
            {categoryCounts.curta}
          </span>
        </button>

        <button
          type="button"
          onClick={() => {
            setSelectedCategory('baixa_qualidade');
            loadHealthScan('baixa_qualidade', maxDuration);
          }}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold transition cursor-pointer border ${
            selectedCategory === 'baixa_qualidade'
              ? 'bg-indigo-950 text-indigo-200 border-indigo-500 shadow'
              : 'bg-serato-card text-indigo-400/80 border-serato-cardBorder hover:text-indigo-200'
          }`}
        >
          <span>📉 Baixa Qualidade (&lt; 192k)</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-indigo-950 font-mono text-indigo-300">
            {categoryCounts.baixa_qualidade}
          </span>
        </button>

        <button
          type="button"
          onClick={() => {
            setSelectedCategory('corrompida');
            loadHealthScan('corrompida', maxDuration);
          }}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold transition cursor-pointer border ${
            selectedCategory === 'corrompida'
              ? 'bg-red-950 text-red-200 border-red-500 shadow'
              : 'bg-serato-card text-red-400/80 border-serato-cardBorder hover:text-red-200'
          }`}
        >
          <span>❌ Arquivos Corrompidos / Vazios</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-red-950 font-mono text-red-300">
            {categoryCounts.corrompida}
          </span>
        </button>
      </div>

      {/* Banner de Progresso de Correção Online */}
      {isRepairingOnline && repairProgress && (
        <div className="bg-cyan-950/40 border border-serato-cyan/50 p-3 rounded-xl shadow-xl flex flex-col gap-1.5 shrink-0 animate-pulse">
          <div className="flex items-center justify-between text-xs font-bold text-white">
            <span className="flex items-center gap-2 text-serato-cyan">
              <DownloadCloud className="w-4 h-4 text-serato-cyan animate-bounce" />
              <span>Baixando versões 320kbps e substituindo arquivos comprometidos...</span>
            </span>
            <span className="font-mono text-serato-gold">
              {repairProgress.percentual}% ({repairProgress.processados} / {repairProgress.total})
            </span>
          </div>

          <div className="w-full bg-slate-900 rounded-full h-2.5 border border-serato-cardBorder overflow-hidden">
            <div
              className="bg-gradient-to-r from-serato-cyan to-blue-500 h-2.5 transition-all duration-200"
              style={{ width: `${Math.min(100, Math.max(1, repairProgress.percentual))}%` }}
            />
          </div>

          <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono truncate">
            <span className="truncate max-w-[70%]">
              Faixa: <b className="text-slate-200">{repairProgress.faixa_atual}</b>
            </span>
            <span className="text-serato-neonGreen font-semibold">
              ✅ {repairProgress.atualizados} substituídas em 320kbps
            </span>
          </div>
        </div>
      )}

      {/* Tabela de Diagnóstico */}
      <div className="flex-1 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20">
        <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder text-xs text-serato-muted font-mono flex items-center justify-between">
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={items.length > 0 && selectedIds.size === items.length}
              onChange={toggleSelectAll}
              className="rounded border-slate-700 bg-serato-dark text-serato-cyan focus:ring-0"
            />
            <span>{items.length} Faixas nesta Categoria</span>
          </div>
          <span>Ações: 🌐 Baixar 320k • 👁️ Finder • 🗑️ Lixeira</span>
        </div>

        <div className="overflow-y-auto flex-1 p-2 space-y-2">
          {items.length === 0 ? (
            <div className="py-12 text-center text-slate-500 text-xs">
              <CheckCircle2 className="w-8 h-8 opacity-20 text-emerald-400 mx-auto mb-2" />
              <p className="font-semibold text-slate-300">Nenhum problema encontrado nesta categoria.</p>
              <p className="text-slate-600 mt-1">Selecione uma Crate ou clique em "Auditar Saúde" para varrer o acervo.</p>
            </div>
          ) : (
            items.map((item) => {
              const isSelected = selectedIds.has(item.id);

              return (
                <div
                  key={item.id}
                  className={`border rounded-lg p-2.5 flex items-center justify-between gap-3 text-xs transition ${
                    item.categoria === 'truncada'
                      ? 'bg-rose-950/20 border-rose-900/50 hover:bg-rose-950/30'
                      : item.categoria === 'curta'
                      ? 'bg-amber-950/20 border-amber-900/50 hover:bg-amber-950/30'
                      : item.categoria === 'corrompida'
                      ? 'bg-red-950/20 border-red-900/50 hover:bg-red-950/30'
                      : 'bg-indigo-950/20 border-indigo-900/50 hover:bg-indigo-950/30'
                  } ${isSelected ? 'ring-1 ring-serato-cyan' : ''}`}
                >
                  <div className="flex items-center gap-3 truncate max-w-2xl">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelect(item.id)}
                      className="rounded border-slate-700 bg-serato-dark text-serato-cyan focus:ring-0"
                    />

                    {/* Badge de Destaque */}
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase shrink-0 font-mono ${
                        item.categoria === 'truncada'
                          ? 'bg-rose-950 text-rose-300 border border-rose-800 font-black'
                          : item.categoria === 'curta'
                          ? 'bg-amber-950 text-amber-300 border border-amber-800'
                          : item.categoria === 'corrompida'
                          ? 'bg-red-950 text-red-300 border border-red-800'
                          : 'bg-indigo-950 text-indigo-300 border border-indigo-800'
                      }`}
                    >
                      {item.categoria === 'truncada'
                        ? '⚠️ CORTE REPENTINO'
                        : item.categoria === 'curta'
                        ? '✂️ MUITO CURTA'
                        : item.categoria === 'corrompida'
                        ? '❌ CORROMPIDA'
                        : '📉 BAIXA QUALIDADE'}
                    </span>

                    <div className="truncate">
                      <div className="font-semibold text-white truncate" title={item.arquivo}>
                        {item.arquivo}
                      </div>
                      <div className="text-[10px] text-slate-400 truncate mt-0.5">
                        {item.detalhes} • <span className="text-slate-500 font-mono">({item.pasta})</span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0 font-mono text-[11px]">
                    <span className="text-slate-300">{item.duracao_seg}s</span>
                    {item.bitrate_kbps > 0 && (
                      <span className="text-serato-cyan">{item.bitrate_kbps} kbps</span>
                    )}

                    {/* Botão Baixar Online */}
                    <button
                      type="button"
                      onClick={() => handleRepairSingleOnline(item)}
                      disabled={isRepairingOnline}
                      className="flex items-center gap-1 px-2 py-1 rounded bg-cyan-950/50 hover:bg-cyan-900 text-serato-cyan border border-cyan-800/40 text-[11px] font-semibold transition cursor-pointer"
                      title="Baixa automaticamente versão 320kbps íntegra e substitui esta faixa"
                    >
                      <DownloadCloud className="w-3.5 h-3.5" />
                      <span>Baixar 320k</span>
                    </button>

                    {/* Revelar no Finder */}
                    {onOpenFileInFinder && (
                      <button
                        type="button"
                        onClick={() => onOpenFileInFinder(item.caminho)}
                        className="p-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-300 cursor-pointer"
                        title="Revelar no Finder"
                      >
                        <Eye className="w-3.5 h-3.5 text-serato-cyan" />
                      </button>
                    )}

                    {/* Mover para Lixeira */}
                    {onMoveToTrash && (
                      <button
                        type="button"
                        onClick={() => handleTrashSingle(item)}
                        className="p-1 rounded bg-rose-950/40 hover:bg-rose-900 text-rose-300 border border-rose-800/50 cursor-pointer"
                        title="Mover arquivo danificado para Lixeira"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              );
            })
          )}
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
