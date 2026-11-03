import React, { useState, useEffect, useMemo } from 'react';
import { Activity, AlertTriangle, ShieldAlert, CheckCircle2, RefreshCw, Trash2, Eye, Filter, ArrowRight, Globe, Zap, DownloadCloud, FolderTree, Search } from 'lucide-react';
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
    sample_rate: number;
    corrompida: number;
  }>({ truncada: 0, curta: 0, baixa_qualidade: 0, sample_rate: 0, corrompida: 0 });

  // Progresso do Coletor de Dados (Scanner)
  const [scanProgress, setScanProgress] = useState<{
    processados: number;
    total: number;
    percentual: number;
    faixa?: string;
  } | null>(null);

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

  // Normalização Local de Frequência 44.1k via FFmpeg
  const [isResamplingLocal, setIsResamplingLocal] = useState<boolean>(false);
  const [resampleProgress, setResampleProgress] = useState<{
    processados: number;
    total: number;
    percentual: number;
    atualizados: number;
    faixa_atual: string;
  } | null>(null);

  // Ação individual em processamento na linha da tabela
  const [processingSingleId, setProcessingSingleId] = useState<string | null>(null);
  const [processingSingleAction, setProcessingSingleAction] = useState<'repair' | 'resample' | null>(null);

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

  // Filtros de busca e severidade
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [severityFilter, setSeverityFilter] = useState<'all' | 'error' | 'warning'>('all');

  const filteredItems = useMemo(() => {
    let result = [...items];
    if (searchTerm.trim()) {
      const q = searchTerm.toLowerCase();
      result = result.filter(i =>
        i.arquivo.toLowerCase().includes(q) ||
        i.caminho.toLowerCase().includes(q) ||
        (i.diagnostico && i.diagnostico.toLowerCase().includes(q))
      );
    }
    if (severityFilter === 'error') {
      result = result.filter(i => i.status === 'corrompido' || i.severidade === 'critica' || i.severidade === 'alta');
    } else if (severityFilter === 'warning') {
      result = result.filter(i => i.status !== 'corrompido' && i.severidade !== 'critica');
    }
    return result;
  }, [items, searchTerm, severityFilter]);

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
    setScanProgress(null);
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
      setScanProgress(null);
    }
  };

  useEffect(() => {
    loadCrates();
  }, [mp3Path]);

  // Listener de streaming para scanner, reparação online e resample local
  useEffect(() => {
    let unlistenScan: (() => void) | undefined;
    let unlistenProgress: (() => void) | undefined;
    let unlistenFinished: (() => void) | undefined;
    let unlistenResampleProg: (() => void) | undefined;
    let unlistenResampleFin: (() => void) | undefined;

    const setupListeners = async () => {
      if (isTauri) {
        const { listen } = await import('@tauri-apps/api/event');
        unlistenScan = await listen<any>('audio-health-scan-progress', (event) => {
          setScanProgress(event.payload);
        });

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

        unlistenResampleProg = await listen<any>('audio-health-resample-progress', (event) => {
          const payload = event.payload;
          setResampleProgress({
            processados: payload.processados || 0,
            total: payload.total || 0,
            percentual: payload.percentual || 0,
            atualizados: payload.atualizados || 0,
            faixa_atual: payload.faixa_atual || '',
          });
        });

        unlistenResampleFin = await listen<any>('audio-health-resample-finished', (event) => {
          const payload = event.payload;
          setIsResamplingLocal(false);
          setResampleProgress(null);
          if (payload.sucesso) {
            onAddLog(`🎉 Normalização concluída! ${payload.atualizados} faixas convertidas com sucesso para 44.100 Hz (320kbps CBR).`);
            loadHealthScan(selectedCategory, maxDuration);
          } else {
            onAddLog(`❌ Erro na normalização: ${payload.erro || 'Desconhecido'}`);
          }
        });
      }
    };

    setupListeners();
    return () => {
      if (unlistenScan) unlistenScan();
      if (unlistenProgress) unlistenProgress();
      if (unlistenFinished) unlistenFinished();
      if (unlistenResampleProg) unlistenResampleProg();
      if (unlistenResampleFin) unlistenResampleFin();
    };
  }, [selectedCategory, maxDuration]);

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

  // Correção online de uma única música com barra de status ativa
  const handleRepairSingleOnline = async (item: any) => {
    setProcessingSingleId(item.id);
    setProcessingSingleAction('repair');
    setIsRepairingOnline(true);
    setRepairProgress({
      processados: 0,
      total: 1,
      percentual: 35,
      atualizados: 0,
      faixa_atual: `Baixando versão oficial 320k: ${item.arquivo}...`
    });
    onAddLog(`🌐 Iniciando busca e download em 320kbps para: ${item.arquivo}...`);
    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('repair_track_online', {
          filepath: item.caminho
        });
        const data = JSON.parse(resJson);
        if (data.sucesso) {
          setRepairProgress({
            processados: 1,
            total: 1,
            percentual: 100,
            atualizados: 1,
            faixa_atual: `✅ Concluído: ${item.arquivo}`
          });
          onAddLog(`🎉 ${item.arquivo}: ${data.mensagem}`);
          setItems(prev => prev.filter(i => i.id !== item.id));
        } else {
          onAddLog(`❌ Erro no download/substituição: ${data.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Falha: ${e}`);
    } finally {
      setTimeout(() => {
        setProcessingSingleId(null);
        setProcessingSingleAction(null);
        setIsRepairingOnline(false);
        setRepairProgress(null);
      }, 500);
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

  // Normalização de Frequência Local em Lote via FFmpeg
  const handleBatchResample = () => {
    const selectedItems = items.filter(i => selectedIds.has(i.id));
    if (selectedItems.length === 0) return;

    setModalConfig({
      isOpen: true,
      title: 'Normalizar Frequência para 44.100 Hz',
      message: `Deseja normalizar ${selectedItems.length} faixas para a frequência padrão DJ (44.100 Hz a 320 kbps CBR)?\n\n⚡ A operação usa o FFmpeg localmente em alta velocidade sem precisar baixar nada da internet.\n🔒 Suas tags ID3 e marcadores Serato serão 100% preservados.`,
      confirmText: `Normalizar ${selectedItems.length} Faixas`,
      variant: 'info',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsResamplingLocal(true);
        setResampleProgress({
          processados: 0,
          total: selectedItems.length,
          percentual: 0,
          atualizados: 0,
          faixa_atual: 'Iniciando FFmpeg...'
        });
        onAddLog(`⚡ Audio Health: Normalizando frequência de ${selectedItems.length} faixas para 44.100 Hz...`);

        try {
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            const filepaths = selectedItems.map(i => i.caminho);
            await invoke('batch_resample_local', {
              filepathsJson: JSON.stringify(filepaths)
            });
          }
        } catch (e) {
          setIsResamplingLocal(false);
          setResampleProgress(null);
          onAddLog(`❌ Falha na normalização local: ${e}`);
        }
      }
    });
  };

  // Normalizar frequência individual com barra de status ativa
  const handleResampleSingle = async (item: any) => {
    setProcessingSingleId(item.id);
    setProcessingSingleAction('resample');
    setIsResamplingLocal(true);
    setResampleProgress({
      processados: 0,
      total: 1,
      percentual: 50,
      atualizados: 0,
      faixa_atual: `Normalizando para 44.100 Hz: ${item.arquivo}...`
    });
    onAddLog(`⚡ Audio Health: Normalizando ${item.arquivo} para 44.100 Hz...`);
    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('resample_track_local', {
          filepath: item.caminho
        });
        const data = JSON.parse(resJson);
        if (data.sucesso) {
          setResampleProgress({
            processados: 1,
            total: 1,
            percentual: 100,
            atualizados: 1,
            faixa_atual: `✅ Concluído: ${item.arquivo}`
          });
          onAddLog(`✅ ${data.mensagem}`);
          setItems(prev => prev.filter(i => i.id !== item.id));
        } else {
          onAddLog(`❌ Erro no resample: ${data.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Falha no resample: ${e}`);
    } finally {
      setTimeout(() => {
        setProcessingSingleId(null);
        setProcessingSingleAction(null);
        setIsResamplingLocal(false);
        setResampleProgress(null);
      }, 500);
    }
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
            disabled={isLoading || isRepairingOnline || isResamplingLocal || selectedIds.size === 0}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold bg-gradient-to-r from-serato-cyan to-blue-500 hover:opacity-90 text-black shadow-lg shadow-serato-cyan/20 transition disabled:opacity-30 cursor-pointer"
            title="Busca e baixa versões completas em 320kbps (44.1kHz) substituindo as faixas selecionadas"
          >
            <DownloadCloud className={`w-3.5 h-3.5 ${isRepairingOnline ? 'animate-bounce' : ''}`} />
            <span>{isRepairingOnline ? 'Baixando em 320k...' : `🌐 Corrigir Online 320k (${selectedIds.size})`}</span>
          </button>

          {/* Botão de Normalização 44.1k FFmpeg */}
          <button
            type="button"
            onClick={handleBatchResample}
            disabled={isLoading || isRepairingOnline || isResamplingLocal || selectedIds.size === 0}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold bg-purple-900/80 hover:bg-purple-800 text-purple-200 border border-purple-600/50 shadow-lg shadow-purple-950/40 transition disabled:opacity-30 cursor-pointer"
            title="Converte e normaliza arquivos para 44.100 Hz (320kbps CBR) localmente via FFmpeg"
          >
            <Zap className={`w-3.5 h-3.5 ${isResamplingLocal ? 'animate-bounce text-purple-300' : 'text-purple-400'}`} />
            <span>{isResamplingLocal ? 'Normalizando...' : `⚡ Normalizar 44.1k (${selectedIds.size})`}</span>
          </button>

          {/* Botão de Auditoria */}
          <button
            type="button"
            onClick={() => loadHealthScan(selectedCategory, maxDuration)}
            disabled={isLoading || isRepairingOnline || isResamplingLocal}
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
            setSelectedCategory('sample_rate');
            loadHealthScan('sample_rate', maxDuration);
          }}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold transition cursor-pointer border ${
            selectedCategory === 'sample_rate'
              ? 'bg-purple-950 text-purple-200 border-purple-500 shadow'
              : 'bg-serato-card text-purple-400/80 border-serato-cardBorder hover:text-purple-200'
          }`}
        >
          <span>📻 Frequência Não-DJ (≠ 44.1k)</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-purple-950 font-mono text-purple-300">
            {categoryCounts.sample_rate || 0}
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

      {/* Barra de Progresso Real-time Slim (Estilo Tag Doctor / Sound Seal) */}
      {(isLoading || isRepairingOnline || isResamplingLocal) && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-slate-900/90 border border-slate-700/60 rounded-lg text-xs shrink-0 shadow-lg animate-in fade-in duration-200">
          <div className="flex items-center gap-2 overflow-hidden flex-1 mr-3 min-w-0">
            {isLoading && (
              <>
                <RefreshCw className="w-3.5 h-3.5 text-rose-400 animate-spin shrink-0" />
                <span className="text-rose-400 font-bold truncate">Auditando Integridade dos Arquivos:</span>
                <span className="text-slate-300 truncate text-[11px]">
                  {scanProgress?.faixa || 'Iniciando auditoria física...'}
                </span>
              </>
            )}
            {isRepairingOnline && (
              <>
                <DownloadCloud className="w-3.5 h-3.5 text-serato-cyan animate-bounce shrink-0" />
                <span className="text-serato-cyan font-bold truncate">Baixando Versões 320k (44.1kHz):</span>
                <span className="text-slate-300 truncate text-[11px]">
                  {repairProgress?.faixa_atual || 'Processando substituições...'}
                </span>
              </>
            )}
            {isResamplingLocal && (
              <>
                <Zap className="w-3.5 h-3.5 text-purple-400 animate-bounce shrink-0" />
                <span className="text-purple-400 font-bold truncate">Normalizando para 44.100 Hz (FFmpeg):</span>
                <span className="text-slate-300 truncate text-[11px]">
                  {resampleProgress?.faixa_atual || 'Processando resample local...'}
                </span>
              </>
            )}
          </div>

          <div className="flex items-center gap-2.5 shrink-0 font-mono text-[11px]">
            {isLoading && scanProgress && (
              <span className="text-rose-400 font-bold">
                {scanProgress.percentual}% ({scanProgress.processados.toLocaleString()}/{scanProgress.total.toLocaleString()})
              </span>
            )}
            {isRepairingOnline && repairProgress && (
              <span className="text-serato-cyan font-bold">
                {repairProgress.percentual}% ({repairProgress.processados}/{repairProgress.total}) • ✅ {repairProgress.atualizados}
              </span>
            )}
            {isResamplingLocal && resampleProgress && (
              <span className="text-purple-300 font-bold">
                {resampleProgress.percentual}% ({resampleProgress.processados}/{resampleProgress.total}) • ✅ {resampleProgress.atualizados}
              </span>
            )}

            <div className="w-24 bg-slate-950 rounded-full h-1.5 overflow-hidden ml-1 border border-white/5">
              <div
                className={`h-full transition-all duration-150 ${
                  isLoading
                    ? 'bg-gradient-to-r from-rose-500 to-amber-500'
                    : isRepairingOnline
                      ? 'bg-gradient-to-r from-serato-cyan to-blue-500'
                      : 'bg-gradient-to-r from-purple-500 to-indigo-500'
                }`}
                style={{
                  width: `${Math.min(100, Math.max(1,
                    isLoading && scanProgress ? scanProgress.percentual :
                    isRepairingOnline && repairProgress ? repairProgress.percentual :
                    isResamplingLocal && resampleProgress ? resampleProgress.percentual : 100
                  ))}%`
                }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Tabela de Diagnóstico */}
      <div className="flex-1 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20">
        <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder text-xs text-serato-muted font-mono flex items-center justify-between">
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={filteredItems.length > 0 && selectedIds.size === filteredItems.length}
              onChange={toggleSelectAll}
              className="rounded border-slate-700 bg-serato-dark text-serato-cyan focus:ring-0"
            />
            <span>{filteredItems.length} de {items.length} Faixas</span>
          </div>
          <span>Ações: 🌐 Baixar 320k • 👁️ Finder • 🗑️ Lixeira</span>
        </div>

        {/* Barra de Busca e Filtros Rápidos */}
        <div className="bg-serato-dark/60 p-2 border-b border-serato-cardBorder flex flex-wrap items-center justify-between gap-2 shrink-0">
          <div className="relative flex-1 min-w-[240px]">
            <Search className="w-3.5 h-3.5 text-serato-muted absolute left-2.5 top-2.5" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Filtrar faixas por nome, caminho ou detalhe do diagnóstico..."
              className="w-full pl-8 pr-3 py-1.5 text-xs bg-serato-dark border border-serato-cardBorder rounded-lg text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-cyan transition font-sans"
            />
          </div>

          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setSeverityFilter('all')}
              className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition cursor-pointer border ${
                severityFilter === 'all'
                  ? 'bg-serato-card text-white border-rose-500/50 shadow-sm'
                  : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
              }`}
            >
              Todas ({items.length})
            </button>
            <button
              type="button"
              onClick={() => setSeverityFilter('error')}
              className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition cursor-pointer border ${
                severityFilter === 'error'
                  ? 'bg-rose-950/60 text-rose-300 border-rose-600/60 shadow-sm'
                  : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
              }`}
            >
              Críticas / Erros
            </button>
            <button
              type="button"
              onClick={() => setSeverityFilter('warning')}
              className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition cursor-pointer border ${
                severityFilter === 'warning'
                  ? 'bg-amber-950/60 text-amber-300 border-amber-600/60 shadow-sm'
                  : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
              }`}
            >
              Avisos / Curtas
            </button>
          </div>
        </div>

        <div className="overflow-y-auto flex-1 p-2 space-y-2">
          {filteredItems.length === 0 ? (
            <div className="py-12 text-center text-slate-500 text-xs">
              <CheckCircle2 className="w-8 h-8 opacity-20 text-emerald-400 mx-auto mb-2" />
              <p className="font-semibold text-slate-300">Nenhum problema encontrado com os filtros ativos.</p>
              <p className="text-slate-600 mt-1">Ajuste a busca ou selecione outra categoria.</p>
            </div>
          ) : (
            filteredItems.map((item) => {
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
                      : item.categoria === 'sample_rate'
                      ? 'bg-purple-950/20 border-purple-900/50 hover:bg-purple-950/30'
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
                          : item.categoria === 'sample_rate'
                          ? 'bg-purple-950 text-purple-300 border border-purple-800'
                          : 'bg-indigo-950 text-indigo-300 border border-indigo-800'
                      }`}
                    >
                      {item.categoria === 'truncada'
                        ? '⚠️ CORTE REPENTINO'
                        : item.categoria === 'curta'
                        ? '✂️ MUITO CURTA'
                        : item.categoria === 'corrompida'
                        ? '❌ CORROMPIDA'
                        : item.categoria === 'sample_rate'
                        ? '📻 NÃO-44.1k'
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
                    {item.sample_rate > 0 && item.sample_rate !== 44100 && (
                      <span className="text-purple-300 text-[10px] bg-purple-950/80 px-1 py-0.2 rounded border border-purple-700/50">
                        {item.sample_rate} Hz
                      </span>
                    )}

                    {/* Botão Normalizar Frequência Local */}
                    {item.categoria === 'sample_rate' && (
                      <button
                        type="button"
                        onClick={() => handleResampleSingle(item)}
                        disabled={isResamplingLocal || isRepairingOnline}
                        className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] font-semibold transition cursor-pointer border ${
                          processingSingleId === item.id && processingSingleAction === 'resample'
                            ? 'bg-purple-900 text-purple-200 border-purple-400 animate-pulse'
                            : 'bg-purple-950/60 hover:bg-purple-900 text-purple-300 border-purple-700/50 disabled:opacity-40'
                        }`}
                        title="Normaliza frequência para 44.100 Hz (320kbps CBR) localmente via FFmpeg"
                      >
                        {processingSingleId === item.id && processingSingleAction === 'resample' ? (
                          <>
                            <RefreshCw className="w-3 h-3 text-purple-300 animate-spin" />
                            <span>Convertendo...</span>
                          </>
                        ) : (
                          <>
                            <Zap className="w-3 h-3 text-purple-400" />
                            <span>44.1k</span>
                          </>
                        )}
                      </button>
                    )}

                    {/* Botão Baixar Online */}
                    <button
                      type="button"
                      onClick={() => handleRepairSingleOnline(item)}
                      disabled={isRepairingOnline || isResamplingLocal}
                      className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] font-semibold transition cursor-pointer border ${
                        processingSingleId === item.id && processingSingleAction === 'repair'
                          ? 'bg-cyan-900 text-white border-cyan-400 animate-pulse'
                          : 'bg-cyan-950/50 hover:bg-cyan-900 text-serato-cyan border border-cyan-800/40 disabled:opacity-40'
                      }`}
                      title="Baixa automaticamente versão 320kbps íntegra (44.1kHz) e substitui esta faixa"
                    >
                      {processingSingleId === item.id && processingSingleAction === 'repair' ? (
                        <>
                          <RefreshCw className="w-3 h-3 text-serato-cyan animate-spin" />
                          <span>Baixando 320k...</span>
                        </>
                      ) : (
                        <>
                          <DownloadCloud className="w-3.5 h-3.5" />
                          <span>Baixar 320k</span>
                        </>
                      )}
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
