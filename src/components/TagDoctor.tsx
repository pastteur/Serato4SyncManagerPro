import React, { useState, useEffect, useMemo } from 'react';
import { Tag, Sparkles, ShieldCheck, RefreshCw, Search, ArrowRight, Music, ChevronLeft, ChevronRight, Folder, FolderTree, Disc3, Zap, CheckCircle2, Layers, ArrowUpDown, ArrowUp, ArrowDown, CheckSquare, Square, Filter, AlertTriangle } from 'lucide-react';
import { ConfirmModal } from './ConfirmModal';

export interface TagDoctorItem {
  id: string;
  caminho: string;
  arquivo_atual: string;
  arquivo_sugerido: string;
  nome_dj?: string;
  nome_crate?: string;
  nome_completo?: string;
  pasta: string;
  crate_raiz: string;
  crate_completa?: string;
  artista_atual: string;
  artista_sugerido: string;
  titulo_atual: string;
  titulo_sugerido: string;
  album_atual?: string;
  album_sugerido?: string;
  genero_atual?: string;
  genero_sugerido?: string;
  bpm: string;
  key: string;
  formato: string;
  precisa_limpeza: boolean;
  duplicata_hd?: boolean;
}

export interface CrateSubInfo {
  nome: string;
  caminho_rel: string;
  total: number;
}

export interface CrateInfo {
  nome: string;
  total: number;
  subcrates: CrateSubInfo[];
}

interface TagDoctorProps {
  mp3Path: string;
  onAddLog: (message: string) => void;
}

export const TagDoctor: React.FC<TagDoctorProps> = ({ mp3Path, onAddLog }) => {
  const [items, setItems] = useState<TagDoctorItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isApplying, setIsApplying] = useState<boolean>(false);
  const [isEnriching, setIsEnriching] = useState<boolean>(false);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [renameFilesOnDisk, setRenameFilesOnDisk] = useState<boolean>(true);
  const [namingMode, setNamingMode] = useState<'full' | 'crate' | 'dj'>('full');

  // Crate e Subcrate Selection
  const [cratesList, setCratesList] = useState<CrateInfo[]>([]);
  const [selectedCrate, setSelectedCrate] = useState<string>('');
  const [selectedSubcrate, setSelectedSubcrate] = useState<string>('');
  const [includeSubcrates, setIncludeSubcrates] = useState<boolean>(true);
  const [isLoadingCrates, setIsLoadingCrates] = useState<boolean>(false);

  // Batch Execution Progress State
  const [isBatchApplying, setIsBatchApplying] = useState<boolean>(false);
  const [batchProgress, setBatchProgress] = useState<{
    processados: number;
    total: number;
    percentual: number;
    atualizados: number;
    faixa_atual: string;
  } | null>(null);

  // Apply Selected Progress State (Barra de Status Aplicar Selecionadas)
  const [applyProgress, setApplyProgress] = useState<{
    processados: number;
    total: number;
    percentual: number;
    atualizados: number;
    faixa_atual: string;
  } | null>(null);

  // Enrich Missing Artists & Titles Progress State (Barra de Status Auto-Completar)
  const [enrichProgress, setEnrichProgress] = useState<{
    processados: number;
    total: number;
    percentual: number;
    enriquecidos: number;
    faixa_atual: string;
  } | null>(null);

  // Scan Execution Progress State (Barra de Status em Tempo Real)
  const [scanProgress, setScanProgress] = useState<{
    processados: number;
    total: number;
    percentual: number;
    crate: string;
    faixa: string;
  } | null>(null);

  const [totalFound, setTotalFound] = useState<number>(0);
  const [totalDirty, setTotalDirty] = useState<number>(0);
  const [displayLimit, setDisplayLimit] = useState<number>(0); // 0 = Sem limite / Tudo numa lista só
  const [visibleCount, setVisibleCount] = useState<number>(100); // Janela virtual de rolagem contínua (zero travamento)
  const [statusFilter, setStatusFilter] = useState<'all' | 'dirty' | 'clean'>('all');
  const [sortField, setSortField] = useState<'arquivo' | 'crate' | 'tag' | 'bpm' | 'status'>('status');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

  const [backupStatus, setBackupStatus] = useState<string | null>(null);

  // Modal de Confirmação em Tela
  const [modalConfig, setModalConfig] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    confirmText?: string;
    variant?: 'danger' | 'warning' | 'info';
    onConfirm: () => void;
  }>({
    isOpen: false,
    title: '',
    message: '',
    onConfirm: () => {}
  });

  // Subcrates da Crate selecionada atualmente
  const activeCrateData = cratesList.find(c => c.nome === selectedCrate);

  // Total de músicas em todas as crates combinadas
  const totalLibraryCount = cratesList.reduce((acc, c) => acc + c.total, 0);

  // Calcula nome sugerido baseado no modo selecionado
  const getSuggestedName = (item: TagDoctorItem, mode: 'full' | 'crate' | 'dj'): string => {
    if (mode === 'full' && item.nome_completo) return item.nome_completo;
    if (mode === 'crate' && item.nome_crate) return item.nome_crate;
    if (mode === 'dj' && item.nome_dj) return item.nome_dj;
    return item.arquivo_sugerido;
  };

  // Carrega lista de Crates e Subcrates
  const loadCrates = async () => {
    if (!mp3Path) return;
    setIsLoadingCrates(true);
    try {
      const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('list_crates_tag_doctor', { mp3Path });
        const data = JSON.parse(resJson);
        if (data.sucesso && data.crates) {
          setCratesList(data.crates);
        }
      }
    } catch (e) {
      console.error('Falha ao listar crates:', e);
    } finally {
      setIsLoadingCrates(false);
    }
  };

  // Carrega lista de faixas conforme filtros (tudo numa lista só ou com limite customizável)
  const loadScan = async (
    targetPage: number = 1,
    search: string = searchTerm,
    crate: string = selectedCrate,
    sub: string = selectedSubcrate,
    incSubs: boolean = includeSubcrates,
    mode: 'full' | 'crate' | 'dj' = namingMode,
    limit: number = displayLimit
  ) => {
    if (!mp3Path) {
      onAddLog('⚠️ Selecione a pasta MP3 Master antes de rodar o Higienizador de Tags.');
      return;
    }

    setIsLoading(true);
    const filterLabel = sub
      ? `Subcrate: ${crate} -> ${sub}`
      : crate
        ? `Crate: ${crate} ${incSubs ? '(com subcrates)' : '(apenas raiz)'}`
        : 'Biblioteca Completa';

    onAddLog(`🔍 Higienizador: Escaneando ${filterLabel}...`);

    try {
      const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('scan_tags_doctor', {
          mp3Path,
          limit: limit <= 0 ? 0 : limit,
          offset: 0,
          search: search || null,
          crateRaiz: crate || null,
          subcrate: sub || null,
          includeSubcrates: incSubs,
          namingMode: mode
        });
        const data = JSON.parse(resJson);

        if (data.sucesso) {
          setItems(data.items || []);
          setTotalFound(data.total_encontrados || 0);
          setTotalDirty(data.total_precisam_limpeza || 0);
          const dirtyOnPage = (data.items || [])
            .filter((it: TagDoctorItem) => it.precisa_limpeza)
            .map((it: TagDoctorItem) => it.id);
          setSelectedIds(new Set(dirtyOnPage));
          onAddLog(`✅ Análise concluída: ${data.total_encontrados} faixas verificadas (${data.total_precisam_limpeza} precisam de ajuste).`);
        } else {
          onAddLog(`❌ Erro no scanner de tags: ${data.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Falha ao invocar scan_tags_doctor: ${e}`);
    } finally {
      setIsLoading(false);
      setScanProgress(null);
    }
  };

  // Itens filtrados e ordenados em tempo real (sem abas)
  const filteredAndSortedItems = useMemo(() => {
    let result = [...items];

    if (statusFilter === 'dirty') {
      result = result.filter(it => it.precisa_limpeza);
    } else if (statusFilter === 'clean') {
      result = result.filter(it => !it.precisa_limpeza);
    }

    result.sort((a, b) => {
      let cmp = 0;
      if (sortField === 'arquivo') {
        cmp = a.arquivo_atual.localeCompare(b.arquivo_atual, undefined, { numeric: true, sensitivity: 'base' });
      } else if (sortField === 'crate') {
        cmp = (a.crate_completa || a.crate_raiz).localeCompare(b.crate_completa || b.crate_raiz);
      } else if (sortField === 'tag') {
        const artA = `${a.artista_sugerido || ''} - ${a.titulo_sugerido || ''}`;
        const artB = `${b.artista_sugerido || ''} - ${b.titulo_sugerido || ''}`;
        cmp = artA.localeCompare(artB, undefined, { numeric: true, sensitivity: 'base' });
      } else if (sortField === 'bpm') {
        const bpmA = parseFloat(a.bpm) || 0;
        const bpmB = parseFloat(b.bpm) || 0;
        cmp = bpmA - bpmB;
      } else if (sortField === 'status') {
        cmp = (a.precisa_limpeza === b.precisa_limpeza) ? 0 : a.precisa_limpeza ? 1 : -1;
      }
      return sortOrder === 'asc' ? cmp : -cmp;
    });

    return result;
  }, [items, statusFilter, sortField, sortOrder]);

  // Reseta a paginação virtual de rolagem contínua ao alterar filtros ou busca
  useEffect(() => {
    setVisibleCount(100);
  }, [statusFilter, sortField, sortOrder, searchTerm, selectedCrate, selectedSubcrate]);

  // Apenas a fatia visível no DOM para manter a UI a 60 FPS estáveis sem travamento
  const visibleItems = useMemo(() => {
    return filteredAndSortedItems.slice(0, visibleCount);
  }, [filteredAndSortedItems, visibleCount]);

  const handleSort = (field: 'arquivo' | 'crate' | 'tag' | 'bpm' | 'status') => {
    if (sortField === field) {
      setSortOrder(prev => prev === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortOrder(field === 'status' ? 'desc' : 'asc');
    }
  };

  const handleSelectAllDisplayed = () => {
    setSelectedIds(new Set(filteredAndSortedItems.map(it => it.id)));
  };

  const handleSelectOnlyPending = () => {
    setSelectedIds(new Set(filteredAndSortedItems.filter(it => it.precisa_limpeza).map(it => it.id)));
  };

  const handleDeselectAll = () => {
    setSelectedIds(new Set());
  };

  // Escuta eventos de streaming do batch apply, apply selected, enrich e scan progress
  useEffect(() => {
    let unlistenProgress: (() => void) | undefined;
    let unlistenFinished: (() => void) | undefined;
    let unlistenScanProgress: (() => void) | undefined;
    let unlistenApplyProgress: (() => void) | undefined;
    let unlistenApplyFinished: (() => void) | undefined;
    let unlistenEnrichProgress: (() => void) | undefined;
    let unlistenEnrichFinished: (() => void) | undefined;

    const setupListeners = async () => {
      const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
      if (isTauri) {
        const { listen } = await import('@tauri-apps/api/event');

        unlistenScanProgress = await listen<any>('tag-doctor-scan-progress', (event) => {
          const payload = event.payload;
          setScanProgress({
            processados: payload.processados || 0,
            total: payload.total || 0,
            percentual: payload.percentual || 0,
            crate: payload.crate || '',
            faixa: payload.faixa || '',
          });
        });

        // Batch Apply Events
        unlistenProgress = await listen<any>('tag-doctor-batch-progress', (event) => {
          const payload = event.payload;
          setBatchProgress({
            processados: payload.processados || 0,
            total: payload.total || 0,
            percentual: payload.percentual || 0,
            atualizados: payload.atualizados || 0,
            faixa_atual: payload.faixa_atual || '',
          });
        });

        unlistenFinished = await listen<any>('tag-doctor-batch-finished', (event) => {
          const payload = event.payload;
          setIsBatchApplying(false);
          setBatchProgress(null);
          if (payload.sucesso) {
            onAddLog(`🎉 Higienização em lote finalizada! ${payload.atualizados} de ${payload.total} faixas atualizadas com sucesso.`);
            loadScan(1, searchTerm, selectedCrate, selectedSubcrate, includeSubcrates);
            loadCrates();
          } else {
            onAddLog(`❌ Erro no processamento em lote: ${payload.erro || 'Desconhecido'}`);
          }
        });

        // Apply Selected Progress Events
        unlistenApplyProgress = await listen<any>('tag-doctor-apply-progress', (event) => {
          const payload = event.payload;
          setApplyProgress({
            processados: payload.processados || 0,
            total: payload.total || 0,
            percentual: payload.percentual || 0,
            atualizados: payload.atualizados || 0,
            faixa_atual: payload.faixa_atual || '',
          });
        });

        unlistenApplyFinished = await listen<any>('tag-doctor-apply-finished', (event) => {
          const payload = event.payload;
          setIsApplying(false);
          setApplyProgress(null);
          if (payload.sucesso) {
            onAddLog(`🎉 Tags gravadas com sucesso em ${payload.atualizados} de ${payload.total || payload.total_solicitados || 0} faixa(s)!`);
            loadScan(1, searchTerm, selectedCrate, selectedSubcrate, includeSubcrates);
            loadCrates();
          } else {
            onAddLog(`❌ Erro ao gravar tags: ${payload.erro || 'Desconhecido'}`);
          }
        });

        // Enrich Artists Progress Events
        unlistenEnrichProgress = await listen<any>('tag-doctor-enrich-progress', (event) => {
          const payload = event.payload;
          setEnrichProgress({
            processados: payload.processados || 0,
            total: payload.total || 0,
            percentual: payload.percentual || 0,
            enriquecidos: payload.enriquecidos || 0,
            faixa_atual: payload.faixa_atual || '',
          });
        });

        unlistenEnrichFinished = await listen<any>('tag-doctor-enrich-finished', (event) => {
          const payload = event.payload;
          setIsEnriching(false);
          setEnrichProgress(null);
          if (payload.sucesso) {
            if (payload.items && payload.items.length > 0) {
              const updatedMap = new Map<string, TagDoctorItem>(payload.items.map((it: TagDoctorItem) => [it.id, it]));
              setItems(prev => prev.map(it => updatedMap.get(it.id) || it));
            }
            onAddLog(`✅ ${payload.enriquecidos || payload.total_enriquecidos || 0} faixa(s) identificadas com Artista & Título via MusicBrainz / Catálogo!`);
          } else {
            onAddLog(`❌ Erro ao auto-completar: ${payload.erro || 'Desconhecido'}`);
          }
        });
      }
    };

    setupListeners();
    loadCrates();

    return () => {
      if (unlistenScanProgress) unlistenScanProgress();
      if (unlistenProgress) unlistenProgress();
      if (unlistenFinished) unlistenFinished();
      if (unlistenApplyProgress) unlistenApplyProgress();
      if (unlistenApplyFinished) unlistenApplyFinished();
      if (unlistenEnrichProgress) unlistenEnrichProgress();
      if (unlistenEnrichFinished) unlistenEnrichFinished();
    };
  }, [mp3Path]);

  // Identificação inteligente de Artistas e Títulos Faltantes via MusicBrainz e Catálogo Local
  const handleEnrichArtists = async () => {
    const targetItems = selectedIds.size > 0
      ? items.filter(it => selectedIds.has(it.id))
      : items;

    if (targetItems.length === 0) {
      setModalConfig({
        isOpen: true,
        title: 'Nenhuma Música Carregada',
        message: 'Por favor, carregue músicas na tabela antes de executar o auto-completar.',
        confirmText: 'OK',
        variant: 'info',
        onConfirm: () => setModalConfig(prev => ({ ...prev, isOpen: false }))
      });
      return;
    }

    setEnrichProgress({
      processados: 0,
      total: targetItems.length,
      percentual: 0,
      enriquecidos: 0,
      faixa_atual: 'Iniciando identificação...'
    });
    setIsEnriching(true);
    onAddLog(`🔍 Consultando metadados e MusicBrainz para ${targetItems.length} faixa(s)...`);

    try {
      const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        await invoke('enrich_missing_artists', {
          itemsJson: JSON.stringify(targetItems)
        });
      }
    } catch (e) {
      setIsEnriching(false);
      setEnrichProgress(null);
      onAddLog(`❌ Erro ao auto-completar artistas e títulos: ${e}`);
    }
  };

  // Backup seguro do master.sqlite
  const handleBackupDb = async () => {
    try {
      onAddLog('🛡️ Iniciando backup de segurança do banco do Serato (master.sqlite)...');
      const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('backup_serato_db');
        const data = JSON.parse(resJson);
        if (data.sucesso) {
          setBackupStatus(`Backup OK (${data.tamanho_mb} MB)`);
          onAddLog(`✅ ${data.mensagem}: ${data.arquivo}`);
        } else {
          onAddLog(`❌ Erro no backup: ${data.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Falha ao invocar backup_serato_db: ${e}`);
    }
  };

  // Aplicação de tags para as faixas selecionadas da página
  const handleApplyCleanPage = () => {
    const selectedItems = items
      .filter(it => selectedIds.has(it.id))
      .map(it => ({
        ...it,
        arquivo_sugerido: getSuggestedName(it, namingMode)
      }));

    if (selectedItems.length === 0) {
      setModalConfig({
        isOpen: true,
        title: 'Nenhuma Música Selecionada',
        message: 'Por favor, selecione ao menos uma música na tabela para aplicar as correções.',
        confirmText: 'OK',
        variant: 'info',
        onConfirm: () => setModalConfig(prev => ({ ...prev, isOpen: false }))
      });
      return;
    }

    const msg = renameFilesOnDisk
      ? `Deseja regravar as tags ID3 e RENOMEAR os ${selectedItems.length} arquivos selecionados no disco?`
      : `Deseja regravar as tags ID3 oficiais dos ${selectedItems.length} arquivos selecionados?\n\n(Os nomes físicos no HD não serão alterados)`;

    setModalConfig({
      isOpen: true,
      title: 'Aplicar Correções Selecionadas',
      message: msg,
      confirmText: `Aplicar em ${selectedItems.length} Faixas`,
      variant: 'info',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setApplyProgress({
          processados: 0,
          total: selectedItems.length,
          percentual: 0,
          atualizados: 0,
          faixa_atual: 'Iniciando gravação...'
        });
        setIsApplying(true);
        onAddLog(`✍️ Gravando tags higienizadas em ${selectedItems.length} arquivo(s)...`);

        try {
          const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            await invoke('apply_tags_doctor', {
              itemsJson: JSON.stringify(selectedItems),
              renameFiles: renameFilesOnDisk
            });
          }
        } catch (e) {
          setIsApplying(false);
          setApplyProgress(null);
          onAddLog(`❌ Falha ao gravar tags: ${e}`);
        }
      }
    });
  };

  // Aplicação em Lote (Crate inteira com subcrates, ou Subcrate específica, ou Toda a Biblioteca)
  const handleBatchApplyCrate = () => {
    const targetLabel = selectedSubcrate
      ? `Subcrate "${selectedCrate} -> ${selectedSubcrate}"`
      : selectedCrate
        ? `Crate "${selectedCrate}" ${includeSubcrates ? '(e todas as suas subcrates)' : '(apenas arquivos da raiz)'}`
        : 'TODA A BIBLIOTECA (todas as crates e subcrates)';

    const countLabel = `${totalFound.toLocaleString()} faixas encontradas (${totalDirty.toLocaleString()} precisam de ajuste)`;

    const msg = renameFilesOnDisk
      ? `⚡ Deseja aplicar a higienização de tags ID3 e RENOMEAR FISICAMENTE no disco em:\n\n📂 ${targetLabel}\n🎯 Faixas a processar: ${totalDirty.toLocaleString()} faixas que precisam de ajuste\n\n(Propagandas de sites e URLs serão eliminadas e os Beatgrids/Cues continuarão 100% íntegros)`
      : `⚡ Deseja regravar as tags ID3 oficiais (preservando Serato Markers) em:\n\n📂 ${targetLabel}\n🎯 Faixas a processar: ${totalDirty.toLocaleString()} faixas que precisam de ajuste\n\n(Atenção: Os nomes físicos dos arquivos no HD não serão alterados)`;

    setModalConfig({
      isOpen: true,
      title: renameFilesOnDisk ? '⚡ Higienização Completa (Tags + Renomear no HD)' : '⚡ Higienizar Tags ID3 em Lote',
      message: msg,
      confirmText: 'Sim, Executar Lote',
      variant: 'warning',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsBatchApplying(true);
        setBatchProgress({
          processados: 0,
          total: totalDirty,
          percentual: 0,
          atualizados: 0,
          faixa_atual: 'Iniciando varredura e gravação em lote...'
        });

        onAddLog(`⚡ Disparando processamento em lote para ${targetLabel}...`);

        try {
          const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            await invoke('batch_apply_tags_doctor', {
              mp3Path,
              crateRaiz: selectedCrate || null,
              subcrate: selectedSubcrate || null,
              includeSubcrates,
              namingMode,
              renameFiles: renameFilesOnDisk,
              search: searchTerm || null
            });
          }
        } catch (e) {
          setIsBatchApplying(false);
          setBatchProgress(null);
          onAddLog(`❌ Erro ao disparar lote: ${e}`);
        }
      }
    });
  };

  // Mudança de Crate Raiz
  const handleCrateChange = (crateName: string) => {
    setSelectedCrate(crateName);
    setSelectedSubcrate(''); // Reseta subcrate
    loadScan(1, searchTerm, crateName, '', includeSubcrates);
  };

  // Mudança de Subcrate
  const handleSubcrateChange = (subPath: string) => {
    setSelectedSubcrate(subPath);
    loadScan(1, searchTerm, selectedCrate, subPath, includeSubcrates);
  };

  // Toggle incluir subcrates
  const handleToggleIncludeSubcrates = (inc: boolean) => {
    setIncludeSubcrates(inc);
    loadScan(1, searchTerm, selectedCrate, selectedSubcrate, inc);
  };

  // Toggle de seleção individual
  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Toggle de todos da página
  const toggleSelectAll = () => {
    if (selectedIds.size === items.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map(it => it.id)));
    }
  };

  // Rótulo do botão em lote
  const batchButtonLabel = totalDirty === 0
    ? 'Tudo 100% Higienizado'
    : selectedSubcrate
      ? `⚡ Aplicar na Subcrate (${totalDirty.toLocaleString()})`
      : selectedCrate
        ? `⚡ Aplicar na Crate ${selectedCrate} (${totalDirty.toLocaleString()})`
        : `⚡ Aplicar na Biblioteca (${totalDirty.toLocaleString()})`;

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl p-4 shadow-2xl flex flex-col h-full flex-1 overflow-hidden min-h-0 space-y-3 relative">
      
      {/* Top Banner & Ações Rápidas */}
      <div className="flex flex-wrap items-center justify-between pb-3 border-b border-serato-cardBorder shrink-0 gap-3">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Tag className="w-4 h-4 text-serato-cyan" />
            <span>Higienizador de Tags ID3 & Padronizador de Nomes</span>
            <span className="text-[10px] bg-serato-neonGreen/20 text-serato-neonGreen px-2 py-0.5 rounded-full border border-serato-neonGreen/30 font-mono">
              Preservação 100% de Remixes, BPM, Key & Cues
            </span>
          </h3>
          <p className="text-[11px] text-serato-muted">
            Limpa propagandas da web, preserva todas as versões e remixes, identifica a Crate raiz e grava tags oficiais sem tocar na base do Serato.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Botão de Backup do Banco */}
          <button
            type="button"
            onClick={handleBackupDb}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-serato-card hover:bg-slate-700 text-slate-200 border border-serato-cardBorder transition cursor-pointer"
            title="Gera cópia de segurança do master.sqlite do Serato"
          >
            <ShieldCheck className="w-3.5 h-3.5 text-serato-neonGreen" />
            <span>{backupStatus || 'Backup master.sqlite'}</span>
          </button>

          {/* Botão de Analisar */}
          <button
            type="button"
            onClick={() => loadScan(1, searchTerm, selectedCrate, selectedSubcrate, includeSubcrates)}
            disabled={isLoading || isApplying || isBatchApplying}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-serato-card hover:bg-serato-cyan/20 text-serato-cyan border border-serato-cyan/40 transition disabled:opacity-40 cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>{isLoading ? 'Analisando...' : '🔍 Escanear'}</span>
          </button>

          {/* Botão Aplicar Selecionadas com Status em Tempo Real */}
          <button
            type="button"
            onClick={handleApplyCleanPage}
            disabled={isLoading || isApplying || isBatchApplying || isEnriching || selectedIds.size === 0}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition cursor-pointer ${
              isApplying
                ? 'bg-emerald-950/90 text-emerald-300 border-emerald-500 shadow-lg shadow-emerald-900/40 animate-pulse'
                : 'bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-600 disabled:opacity-40'
            }`}
            title="Aplica as tags e renomeia somente para as faixas selecionadas"
          >
            <Sparkles className={`w-3.5 h-3.5 ${isApplying ? 'animate-spin text-emerald-400' : 'text-serato-cyan'}`} />
            <span>
              {isApplying
                ? `✍️ Gravando... ${applyProgress ? `${applyProgress.percentual}% (${applyProgress.processados}/${applyProgress.total})` : ''}`
                : `✍️ Aplicar Selecionadas (${selectedIds.size})`}
            </span>
          </button>

          {/* Botão Auto-Identificar Artistas e Títulos via MusicBrainz com Status em Tempo Real */}
          <button
            type="button"
            onClick={handleEnrichArtists}
            disabled={isLoading || isApplying || isBatchApplying || isEnriching || items.length === 0}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition cursor-pointer shadow-sm ${
              isEnriching
                ? 'bg-sky-950/90 text-sky-300 border-sky-500 shadow-lg shadow-sky-900/40 animate-pulse'
                : 'bg-cyan-950/80 hover:bg-cyan-900 text-serato-cyan border-cyan-700/60 disabled:opacity-40'
            }`}
            title="Consulta o catálogo e MusicBrainz para identificar artistas e títulos das faixas que estão sem artista ou desconhecidas"
          >
            <Music className={`w-3.5 h-3.5 ${isEnriching ? 'animate-bounce text-sky-300' : 'text-serato-cyan'}`} />
            <span>
              {isEnriching
                ? `🎧 Identificando... ${enrichProgress ? `${enrichProgress.percentual}% (${enrichProgress.processados}/${enrichProgress.total})` : ''}`
                : '🎧 Auto-Completar Artistas & Títulos'}
            </span>
          </button>

          {/* Botão de Execução em Lote por Crate ou Biblioteca */}
          <button
            type="button"
            onClick={handleBatchApplyCrate}
            disabled={isLoading || isApplying || isBatchApplying || totalFound === 0}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold bg-gradient-to-r from-serato-orange via-amber-500 to-serato-gold hover:opacity-90 text-black shadow-lg shadow-serato-orange/20 transition disabled:opacity-40 cursor-pointer"
            title="Processa e higieniza todas as faixas da Crate ou subcrate de uma só vez"
          >
            <Zap className={`w-3.5 h-3.5 ${isBatchApplying ? 'animate-bounce' : ''}`} />
            <span>{isBatchApplying ? 'Processando Lote...' : batchButtonLabel}</span>
          </button>
        </div>
      </div>

      {/* Barra de Filtro Inteligente por Crate & Subcrate */}
      <div className="bg-serato-header/70 border border-serato-cardBorder p-2.5 rounded-lg flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-bold text-slate-300 flex items-center gap-1.5">
            <FolderTree className="w-4 h-4 text-serato-orange" />
            <span>Filtrar por Crate:</span>
          </span>

          {/* Seletor Crate Raiz */}
          <select
            value={selectedCrate}
            onChange={(e) => handleCrateChange(e.target.value)}
            disabled={isLoading || isBatchApplying}
            className="bg-serato-dark border border-serato-cardBorder text-slate-200 text-xs font-semibold rounded px-2.5 py-1.5 focus:outline-none focus:border-serato-orange cursor-pointer max-w-[240px]"
          >
            <option value="">📁 Todas as Crates ({totalLibraryCount > 0 ? `${totalLibraryCount.toLocaleString()} faixas` : 'Biblioteca Completa'})</option>
            {cratesList.map(c => (
              <option key={c.nome} value={c.nome}>
                📁 {c.nome} ({c.total.toLocaleString()} faixas)
              </option>
            ))}
          </select>

          {/* Seletor de Subcrate (quando uma crate está ativa) */}
          {selectedCrate && (
            <div className="flex items-center gap-2 ml-1">
              <label className="flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer bg-serato-dark px-2 py-1 rounded border border-serato-cardBorder">
                <input
                  type="checkbox"
                  checked={includeSubcrates && !selectedSubcrate}
                  onChange={(e) => handleToggleIncludeSubcrates(e.target.checked)}
                  disabled={!!selectedSubcrate || isBatchApplying}
                  className="rounded border-slate-700 bg-serato-dark text-serato-orange focus:ring-0"
                />
                <span className="text-[11px] font-medium">Incluir todas as subcrates ({activeCrateData?.subcrates.length || 0})</span>
              </label>

              {activeCrateData && activeCrateData.subcrates.length > 0 && (
                <select
                  value={selectedSubcrate}
                  onChange={(e) => handleSubcrateChange(e.target.value)}
                  disabled={isLoading || isBatchApplying}
                  className="bg-serato-dark border border-serato-cardBorder text-serato-cyan text-xs font-semibold rounded px-2.5 py-1.5 focus:outline-none focus:border-serato-cyan cursor-pointer max-w-[200px]"
                >
                  <option value="">↳ Todas as Subcrates ({activeCrateData.total.toLocaleString()} faixas)</option>
                  {activeCrateData.subcrates.map(sub => (
                    <option key={sub.caminho_rel} value={sub.caminho_rel}>
                      ↳ {sub.nome} ({sub.total} faixas)
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}
        </div>

        {/* Informação contextual do filtro selecionado */}
        <div className="flex items-center gap-3 text-xs font-mono">
          <span className="text-slate-400">
            Escopo: <b className="text-white">{selectedSubcrate ? `${selectedCrate} -> ${selectedSubcrate}` : (selectedCrate || 'Biblioteca Completa')}</b>
          </span>
          <span className="text-slate-400">
            Total no Escopo: <b className="text-serato-cyan">{totalFound.toLocaleString()}</b>
          </span>
          <span className="text-slate-400">
            Para Ajustar: <b className="text-serato-gold">{totalDirty.toLocaleString()}</b>
          </span>
        </div>
      </div>

      {/* Barra de Opções de Nomenclatura e Busca */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-serato-card px-3 py-2 rounded-lg border border-serato-cardBorder shrink-0">
        
        {/* Seletor de Modelo de Nome */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-300 font-semibold flex items-center gap-1">
            <Disc3 className="w-3.5 h-3.5 text-serato-cyan" />
            <span>Formato do Nome:</span>
          </span>

          <select
            value={namingMode}
            onChange={(e) => {
              const newMode = e.target.value as 'full' | 'crate' | 'dj';
              setNamingMode(newMode);
              loadScan(1, searchTerm, selectedCrate, selectedSubcrate, includeSubcrates, newMode);
            }}
            className="bg-serato-dark border border-serato-cardBorder text-serato-cyan text-xs font-semibold rounded px-2.5 py-1 focus:outline-none cursor-pointer"
          >
            <option value="full">🌟 Artista - Título (Versão/Remix) - Crate - Álbum</option>
            <option value="crate">📂 Artista - Título (Versão/Remix) - Crate</option>
            <option value="dj">🎵 Artista - Título (Versão/Remix) Clássico</option>
          </select>

          <label className={`flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg border transition-all cursor-pointer ${
            renameFilesOnDisk 
              ? 'bg-serato-cyan/15 border-serato-cyan/40 text-serato-cyan font-medium' 
              : 'bg-slate-800/40 border-slate-700 text-slate-400'
          }`}>
            <input
              type="checkbox"
              checked={renameFilesOnDisk}
              onChange={(e) => setRenameFilesOnDisk(e.target.checked)}
              className="rounded border-slate-700 bg-serato-dark text-serato-cyan focus:ring-0"
            />
            <span>Renomear arquivos no HD (remover propagandas da web)</span>
          </label>
        </div>

        {/* Busca */}
        <div className="relative w-64">
          <Search className="w-3.5 h-3.5 text-serato-muted absolute left-2.5 top-2.5" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && loadScan(1, searchTerm, selectedCrate, selectedSubcrate, includeSubcrates)}
            placeholder="Filtrar por nome, artista ou remix..."
            className="w-full pl-8 pr-3 py-1 text-xs bg-serato-dark border border-serato-cardBorder rounded-md text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-cyan"
          />
        </div>
      </div>

      {/* Alerta de renomeação no HD desativada */}
      {!renameFilesOnDisk && totalDirty > 0 && (
        <div className="w-full bg-amber-950/40 border border-amber-600/50 rounded-lg px-3 py-2 flex items-center justify-between text-xs text-amber-300 shrink-0">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-serato-gold shrink-0" />
            <span>
              <b>Atenção:</b> A opção <u>Renomear arquivos no HD</u> está desmarcada. Para retirar definitivamente essas {totalDirty} faixas da lista e padronizar os nomes físicos no disco, marque a caixa acima antes de aplicar.
            </span>
          </div>
          <button
            type="button"
            onClick={() => setRenameFilesOnDisk(true)}
            className="text-[11px] underline font-bold hover:text-white cursor-pointer ml-3 whitespace-nowrap bg-amber-900/60 hover:bg-amber-800 px-2 py-1 rounded border border-amber-600/60 transition"
          >
            Ativar Renomeação no HD
          </button>
        </div>
      )}

      {/* Barra de Status e Progresso em Tempo Real durante a Varredura */}
      {isLoading && (
        <div className="bg-slate-900/90 border border-serato-cyan/60 p-3.5 rounded-xl shadow-2xl flex flex-col gap-2 shrink-0 backdrop-blur animate-in fade-in duration-200">
          <div className="flex items-center justify-between text-xs font-bold text-white">
            <span className="flex items-center gap-2 text-serato-cyan">
              <RefreshCw className="w-4 h-4 text-serato-cyan animate-spin" />
              <span>
                {scanProgress
                  ? `Analisando ${scanProgress.crate ? `Crate "${scanProgress.crate}"` : 'Biblioteca Completa'}...`
                  : 'Iniciando varredura rápida de tags ID3 e nomes...'}
              </span>
            </span>
            <span className="font-mono text-serato-cyan font-bold text-sm">
              {scanProgress ? `${scanProgress.percentual}%` : 'Carregando...'}
              {scanProgress && scanProgress.total > 0 && (
                <span className="text-xs text-slate-400 font-normal ml-2">
                  ({scanProgress.processados.toLocaleString()} / {scanProgress.total.toLocaleString()} faixas)
                </span>
              )}
            </span>
          </div>

          {/* Barra de Progresso com Gradiente Serato */}
          <div className="w-full bg-slate-950 rounded-full h-3 border border-serato-cardBorder overflow-hidden shadow-inner">
            <div
              className={`h-3 transition-all duration-150 rounded-full ${
                scanProgress
                  ? 'bg-gradient-to-r from-cyan-500 via-serato-cyan to-blue-500 shadow-lg shadow-cyan-500/30'
                  : 'bg-gradient-to-r from-serato-cyan to-blue-600 animate-pulse w-full'
              }`}
              style={scanProgress ? { width: `${Math.min(100, Math.max(1, scanProgress.percentual))}%` } : undefined}
            />
          </div>

          <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono truncate">
            <span className="truncate max-w-[75%]">
              {scanProgress?.faixa ? (
                <>🎵 Em análise: <b className="text-slate-200">{scanProgress.faixa}</b></>
              ) : (
                <>⚡ Leitura de alta velocidade (checagem de nomes, tags e Serato cues)...</>
              )}
            </span>
            <span className="text-serato-cyan/90 font-semibold flex items-center gap-1">
              <span className="inline-block w-2 h-2 rounded-full bg-serato-cyan animate-ping mr-1" />
              Varrendo disco
            </span>
          </div>
        </div>
      )}

      {/* Modal / Overlay de Progresso em Tempo Real quando Executando em Lote */}
      {isBatchApplying && batchProgress && (
        <div className="bg-cyan-950/40 border border-serato-cyan/50 p-4 rounded-xl shadow-xl flex flex-col gap-2 shrink-0 animate-pulse">
          <div className="flex items-center justify-between text-xs font-bold text-white">
            <span className="flex items-center gap-2 text-serato-cyan">
              <Zap className="w-4 h-4 text-serato-orange animate-bounce" />
              <span>Higienizando em lote: {selectedCrate ? `Crate "${selectedCrate}"` : 'Biblioteca Completa'}...</span>
            </span>
            <span className="font-mono text-serato-gold">
              {batchProgress.percentual}% ({batchProgress.processados.toLocaleString()} / {batchProgress.total.toLocaleString()} faixas)
            </span>
          </div>

          {/* Barra de Progresso */}
          <div className="w-full bg-slate-900 rounded-full h-3 border border-serato-cardBorder overflow-hidden">
            <div
              className="bg-gradient-to-r from-serato-cyan via-amber-400 to-serato-orange h-3 transition-all duration-200"
              style={{ width: `${Math.min(100, Math.max(1, batchProgress.percentual))}%` }}
            />
          </div>

          <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono truncate">
            <span className="truncate max-w-[70%]">
              🎵 Faixa atual: <b className="text-slate-200">{batchProgress.faixa_atual}</b>
            </span>
            <span className="text-serato-neonGreen font-semibold">
              ✅ {batchProgress.atualizados.toLocaleString()} faixas ajustadas
            </span>
          </div>
        </div>
      )}

      {/* Barra de Status e Progresso em Tempo Real: Aplicando Faixas Selecionadas */}
      {isApplying && applyProgress && (
        <div className="bg-emerald-950/50 border border-emerald-500/60 p-4 rounded-xl shadow-2xl flex flex-col gap-2 shrink-0 animate-in fade-in duration-200">
          <div className="flex items-center justify-between text-xs font-bold text-white">
            <span className="flex items-center gap-2 text-emerald-400">
              <Sparkles className="w-4 h-4 text-emerald-400 animate-spin" />
              <span>Gravando tags ID3 oficiais nas faixas selecionadas...</span>
            </span>
            <span className="font-mono text-emerald-300 font-bold text-sm">
              {applyProgress.percentual}% ({applyProgress.processados.toLocaleString()} / {applyProgress.total.toLocaleString()} faixas)
            </span>
          </div>

          {/* Barra de Progresso com Gradiente Esmeralda */}
          <div className="w-full bg-slate-950 rounded-full h-3 border border-emerald-900/60 overflow-hidden shadow-inner">
            <div
              className="bg-gradient-to-r from-emerald-500 via-teal-400 to-cyan-400 h-3 transition-all duration-150 rounded-full shadow-lg shadow-emerald-500/30"
              style={{ width: `${Math.min(100, Math.max(1, applyProgress.percentual))}%` }}
            />
          </div>

          <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono truncate">
            <span className="truncate max-w-[70%]">
              🎵 Faixa atual: <b className="text-slate-200">{applyProgress.faixa_atual || 'Gravando tags...'}</b>
            </span>
            <span className="text-serato-neonGreen font-semibold shrink-0">
              ✅ {applyProgress.atualizados.toLocaleString()} gravada(s)
            </span>
          </div>
        </div>
      )}

      {/* Barra de Status e Progresso em Tempo Real: Auto-Completando Artistas & Títulos */}
      {isEnriching && enrichProgress && (
        <div className="bg-sky-950/50 border border-sky-500/60 p-4 rounded-xl shadow-2xl flex flex-col gap-2 shrink-0 animate-in fade-in duration-200">
          <div className="flex items-center justify-between text-xs font-bold text-white">
            <span className="flex items-center gap-2 text-sky-400">
              <Music className="w-4 h-4 text-sky-400 animate-bounce" />
              <span>Auto-Completando Artistas & Títulos via Nuvem/Cache e MusicBrainz...</span>
            </span>
            <span className="font-mono text-sky-300 font-bold text-sm">
              {enrichProgress.percentual}% ({enrichProgress.processados.toLocaleString()} / {enrichProgress.total.toLocaleString()} faixas)
            </span>
          </div>

          {/* Barra de Progresso com Gradiente Índigo/Sky */}
          <div className="w-full bg-slate-950 rounded-full h-3 border border-sky-900/60 overflow-hidden shadow-inner">
            <div
              className="bg-gradient-to-r from-sky-500 via-indigo-500 to-purple-500 h-3 transition-all duration-150 rounded-full shadow-lg shadow-sky-500/30"
              style={{ width: `${Math.min(100, Math.max(1, enrichProgress.percentual))}%` }}
            />
          </div>

          <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono truncate">
            <span className="truncate max-w-[70%]">
              🔍 Consultando: <b className="text-slate-200">{enrichProgress.faixa_atual || 'Pesquisando na base...'}</b>
            </span>
            <span className="text-sky-300 font-semibold shrink-0">
              ✨ {enrichProgress.enriquecidos.toLocaleString()} identificada(s)
            </span>
          </div>
        </div>
      )}

      {/* Barra de Filtros Rápidos, Seleção e Exibição Contínua */}
      <div className="bg-serato-header/50 border border-serato-cardBorder p-2 rounded-lg flex flex-wrap items-center justify-between gap-3 shrink-0">
        {/* Pílulas de Status */}
        <div className="flex items-center gap-1.5 bg-serato-dark/80 p-1 rounded-lg border border-serato-cardBorder text-xs">
          <button
            type="button"
            onClick={() => setStatusFilter('all')}
            className={`px-2.5 py-1 rounded font-semibold transition cursor-pointer ${
              statusFilter === 'all'
                ? 'bg-serato-card text-white shadow-sm border border-serato-cardBorder'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Todas ({items.length})
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter('dirty')}
            className={`px-2.5 py-1 rounded font-semibold transition cursor-pointer flex items-center gap-1.5 ${
              statusFilter === 'dirty'
                ? 'bg-amber-950/40 text-amber-300 shadow-sm border border-amber-600/50'
                : 'text-slate-400 hover:text-amber-400'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-serato-gold inline-block"></span>
            Para Ajustar ({items.filter(it => it.precisa_limpeza).length})
          </button>
          <button
            type="button"
            onClick={() => setStatusFilter('clean')}
            className={`px-2.5 py-1 rounded font-semibold transition cursor-pointer flex items-center gap-1.5 ${
              statusFilter === 'clean'
                ? 'bg-emerald-950/40 text-emerald-300 shadow-sm border border-emerald-600/50'
                : 'text-slate-400 hover:text-emerald-400'
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-serato-neonGreen inline-block"></span>
            Limpas ({items.filter(it => !it.precisa_limpeza).length})
          </button>
        </div>

        {/* Botões de Seleção Rápida */}
        <div className="flex items-center gap-2 text-xs">
          <button
            type="button"
            onClick={handleSelectAllDisplayed}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-serato-dark hover:bg-slate-800 text-slate-300 border border-serato-cardBorder cursor-pointer transition font-medium"
            title="Seleciona todas as faixas exibidas na lista para aplicação imediata"
          >
            <CheckSquare className="w-3.5 h-3.5 text-serato-cyan" />
            <span>Selecionar Tudo ({filteredAndSortedItems.length})</span>
          </button>

          <button
            type="button"
            onClick={handleSelectOnlyPending}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-serato-dark hover:bg-slate-800 text-amber-300 border border-amber-600/40 cursor-pointer transition font-medium"
            title="Seleciona apenas as faixas que precisam de ajuste"
          >
            <Sparkles className="w-3.5 h-3.5 text-serato-gold" />
            <span>Selecionar Pendentes ({filteredAndSortedItems.filter(it => it.precisa_limpeza).length})</span>
          </button>

          {selectedIds.size > 0 && (
            <button
              type="button"
              onClick={handleDeselectAll}
              className="flex items-center gap-1 px-2 py-1 rounded text-slate-400 hover:text-slate-200 cursor-pointer transition"
            >
              <Square className="w-3.5 h-3.5" />
              <span>Desmarcar ({selectedIds.size})</span>
            </button>
          )}
        </div>

        {/* Seletor de Limite de Exibição (Sem Abas) */}
        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-400 font-medium">Exibição:</span>
          <select
            value={displayLimit}
            onChange={(e) => {
              const newLimit = parseInt(e.target.value, 10);
              setDisplayLimit(newLimit);
              loadScan(1, searchTerm, selectedCrate, selectedSubcrate, includeSubcrates, namingMode, newLimit);
            }}
            className="bg-serato-dark border border-serato-cardBorder text-slate-200 font-semibold rounded px-2.5 py-1 focus:outline-none cursor-pointer"
          >
            <option value={0}>♾️ Toda a Biblioteca (sem abas)</option>
            <option value={1000}>1.000 faixas</option>
            <option value={500}>500 faixas</option>
            <option value={200}>200 faixas</option>
          </select>
        </div>
      </div>

      {/* Tabela De / Para (Antes vs Depois) */}
      <div className="flex-1 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20">
        <div 
          className="overflow-y-auto flex-1"
          onScroll={(e) => {
            const el = e.currentTarget;
            if (el.scrollTop + el.clientHeight >= el.scrollHeight - 350) {
              if (visibleCount < filteredAndSortedItems.length) {
                setVisibleCount(prev => Math.min(prev + 100, filteredAndSortedItems.length));
              }
            }
          }}
        >
          <table className="w-full text-left text-xs">
            <thead className="bg-serato-header text-serato-muted font-mono uppercase text-[10px] border-b border-serato-cardBorder sticky top-0 z-10 select-none">
              <tr>
                <th className="py-2.5 px-3 w-8 text-center">
                  <input
                    type="checkbox"
                    checked={filteredAndSortedItems.length > 0 && selectedIds.size === filteredAndSortedItems.length}
                    onChange={() => {
                      if (selectedIds.size === filteredAndSortedItems.length) {
                        setSelectedIds(new Set());
                      } else {
                        setSelectedIds(new Set(filteredAndSortedItems.map(it => it.id)));
                      }
                    }}
                    className="rounded border-slate-700 bg-serato-dark text-serato-cyan focus:ring-0 cursor-pointer"
                  />
                </th>

                <th 
                  onClick={() => handleSort('arquivo')} 
                  className="py-2.5 px-3 cursor-pointer hover:text-white transition"
                  title="Clique para ordenar por nome do arquivo no disco"
                >
                  <div className="flex items-center gap-1.5">
                    <span>Como Está no Disco (Original)</span>
                    {sortField === 'arquivo' ? (
                      sortOrder === 'asc' ? <ArrowUp className="w-3 h-3 text-serato-cyan" /> : <ArrowDown className="w-3 h-3 text-serato-cyan" />
                    ) : (
                      <ArrowUpDown className="w-3 h-3 opacity-30" />
                    )}
                  </div>
                </th>

                <th 
                  onClick={() => handleSort('crate')} 
                  className="py-2.5 px-3 w-40 cursor-pointer hover:text-white transition"
                  title="Clique para ordenar por Crate / Pasta"
                >
                  <div className="flex items-center gap-1.5">
                    <span>Crate / Pasta Raiz</span>
                    {sortField === 'crate' ? (
                      sortOrder === 'asc' ? <ArrowUp className="w-3 h-3 text-serato-cyan" /> : <ArrowDown className="w-3 h-3 text-serato-cyan" />
                    ) : (
                      <ArrowUpDown className="w-3 h-3 opacity-30" />
                    )}
                  </div>
                </th>

                <th className="py-2.5 px-3 w-6 text-center"></th>

                <th 
                  onClick={() => handleSort('tag')} 
                  className="py-2.5 px-3 cursor-pointer hover:text-white transition"
                  title="Clique para ordenar por Artista & Título Sugerido"
                >
                  <div className="flex items-center gap-1.5">
                    <span>Tags Oficiais & Nome Sugerido</span>
                    {sortField === 'tag' ? (
                      sortOrder === 'asc' ? <ArrowUp className="w-3 h-3 text-serato-cyan" /> : <ArrowDown className="w-3 h-3 text-serato-cyan" />
                    ) : (
                      <ArrowUpDown className="w-3 h-3 opacity-30" />
                    )}
                  </div>
                </th>

                <th 
                  onClick={() => handleSort('bpm')} 
                  className="py-2.5 px-3 w-28 text-center cursor-pointer hover:text-white transition"
                  title="Clique para ordenar por BPM"
                >
                  <div className="flex items-center justify-center gap-1.5">
                    <span>BPM & Tom</span>
                    {sortField === 'bpm' ? (
                      sortOrder === 'asc' ? <ArrowUp className="w-3 h-3 text-serato-cyan" /> : <ArrowDown className="w-3 h-3 text-serato-cyan" />
                    ) : (
                      <ArrowUpDown className="w-3 h-3 opacity-30" />
                    )}
                  </div>
                </th>

                <th 
                  onClick={() => handleSort('status')} 
                  className="py-2.5 px-3 w-20 text-center cursor-pointer hover:text-white transition"
                  title="Clique para ordenar por Status (Ajustar primeiro ou Limpo primeiro)"
                >
                  <div className="flex items-center justify-center gap-1.5">
                    <span>Status</span>
                    {sortField === 'status' ? (
                      sortOrder === 'asc' ? <ArrowUp className="w-3 h-3 text-serato-cyan" /> : <ArrowDown className="w-3 h-3 text-serato-cyan" />
                    ) : (
                      <ArrowUpDown className="w-3 h-3 opacity-30" />
                    )}
                  </div>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-serato-cardBorder/40 font-mono text-[11px]">
              {filteredAndSortedItems.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-slate-500 font-sans">
                    <Music className="w-8 h-8 opacity-20 text-serato-cyan mx-auto mb-2" />
                    <p className="font-semibold text-slate-400">Nenhuma faixa encontrada com os filtros atuais.</p>
                    <p className="text-xs text-slate-600 mt-1">Experimente alternar o filtro de status ou a busca por texto.</p>
                  </td>
                </tr>
              ) : (
                visibleItems.map((item) => {
                  const isSelected = selectedIds.has(item.id);
                  const suggestedFileName = getSuggestedName(item, namingMode);

                  return (
                    <tr
                      key={item.id}
                      className={`hover:bg-white/[0.03] transition ${isSelected ? 'bg-cyan-950/10' : ''}`}
                    >
                      {/* Checkbox */}
                      <td className="py-2 px-3 text-center">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelect(item.id)}
                          className="rounded border-slate-700 bg-serato-dark text-serato-cyan focus:ring-0"
                        />
                      </td>

                      {/* Como Está Agora */}
                      <td className="py-2 px-3">
                        <div className="font-sans font-medium text-slate-300 truncate max-w-[260px]" title={item.arquivo_atual}>
                          {item.arquivo_atual}
                        </div>
                        <div className="text-[10px] text-slate-500 truncate max-w-[260px]">
                          Art: {item.artista_atual || '—'} | Tit: {item.titulo_atual || '—'}
                        </div>
                      </td>

                      {/* Crate / Pasta Raiz */}
                      <td className="py-2 px-3">
                        <div className="flex items-center gap-1.5">
                          <Folder className="w-3.5 h-3.5 text-serato-orange shrink-0" />
                          <span className="font-sans font-semibold text-slate-200 text-xs px-2 py-0.5 rounded bg-serato-card border border-serato-cardBorder truncate max-w-[130px]" title={item.crate_completa || item.crate_raiz}>
                            {item.crate_completa || item.crate_raiz || 'Geral'}
                          </span>
                        </div>
                      </td>

                      {/* Seta indicadora */}
                      <td className="py-2 px-3 text-center text-serato-cyan">
                        <ArrowRight className="w-3.5 h-3.5 mx-auto opacity-70" />
                      </td>

                      {/* Como Vai Ficar */}
                      <td className="py-2 px-3">
                        <div className="font-sans font-semibold text-white flex items-center gap-1.5 truncate max-w-[340px]">
                          {item.artista_sugerido ? (
                            <>
                              <span className="text-serato-cyan font-bold">{item.artista_sugerido}</span>
                              <span className="text-slate-500">-</span>
                            </>
                          ) : (
                            <span className="text-slate-400 italic text-[10px] bg-slate-800/80 px-1.5 py-0.5 rounded border border-slate-700/60 shrink-0">
                              (Sem Artista)
                            </span>
                          )}
                          <span className="text-white">{item.titulo_sugerido}</span>
                          {item.album_sugerido && (
                            <>
                              <span className="text-slate-500">-</span>
                              <span className="text-slate-400 text-[10px] italic">[{item.album_sugerido}]</span>
                            </>
                          )}
                        </div>
                        <div className="text-[10px] text-serato-gold truncate max-w-[340px]">
                          Novo Nome: {suggestedFileName}
                        </div>
                      </td>

                      {/* BPM & Key */}
                      <td className="py-2 px-3 text-center">
                        <div className="flex items-center justify-center gap-1.5">
                          {item.bpm && (
                            <span className="text-[10px] px-1.5 py-0.2 rounded bg-serato-dark text-slate-300 border border-white/10 font-bold">
                              {Math.round(parseFloat(item.bpm))} BPM
                            </span>
                          )}
                          {item.key && (
                            <span className="text-[10px] px-1.5 py-0.2 rounded bg-cyan-950/60 text-serato-cyan border border-cyan-800/40 font-bold">
                              {item.key}
                            </span>
                          )}
                          {!item.bpm && !item.key && (
                            <span className="text-[10px] text-slate-600">—</span>
                          )}
                        </div>
                      </td>

                      {/* Status */}
                      <td className="py-2 px-3 text-center">
                        <div className="flex flex-col items-center gap-1">
                          {item.precisa_limpeza ? (
                            <span className="text-[10px] px-2 py-0.5 rounded-full bg-serato-gold/20 text-serato-gold border border-serato-gold/30 font-bold">
                              Ajustar
                            </span>
                          ) : (
                            <span className="text-[10px] px-2 py-0.5 rounded-full bg-serato-neonGreen/20 text-serato-neonGreen border border-serato-neonGreen/30 font-bold">
                              Limpo
                            </span>
                          )}
                          {item.duplicata_hd && (
                            <span className="text-[9px] px-1.5 py-0.2 rounded bg-amber-950/60 text-amber-300 border border-amber-800/50" title="Já existe outro arquivo no disco com o nome limpo pretendido. Trata-se de uma duplicata no disco.">
                              ⚠️ Duplicata HD
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}

              {/* Gatilho de rolagem contínua sem travar o DOM */}
              {visibleCount < filteredAndSortedItems.length && (
                <tr>
                  <td colSpan={7} className="text-center py-3 bg-serato-dark/40 border-t border-serato-cardBorder">
                    <button
                      type="button"
                      onClick={() => setVisibleCount(prev => Math.min(prev + 200, filteredAndSortedItems.length))}
                      className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 text-xs text-serato-cyan border border-slate-700 font-medium cursor-pointer transition shadow-sm"
                    >
                      ⬇️ Carregar mais faixas (+200) ou continue rolando a tela... (exibindo {visibleItems.length.toLocaleString()} de {filteredAndSortedItems.length.toLocaleString()})
                    </button>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Rodapé da Lista Contínua (Sem Abas de 50) */}
        <div className="bg-serato-header px-4 py-2.5 border-t border-serato-cardBorder flex items-center justify-between text-xs text-serato-muted shrink-0 font-mono">
          <div className="flex items-center gap-2">
            <span>Exibindo <b className="text-white">{visibleItems.length.toLocaleString()}</b> de <b className="text-white">{filteredAndSortedItems.length.toLocaleString()}</b> faixas na lista contínua</span>
            {totalDirty > 0 && (
              <span className="text-amber-400 bg-amber-950/40 px-2 py-0.5 rounded border border-amber-800/40 font-semibold text-[11px]">
                ⚠️ {totalDirty.toLocaleString()} precisam de ajuste no escopo total
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <span className="text-serato-cyan font-bold">
              {selectedIds.size > 0 ? `☑️ ${selectedIds.size.toLocaleString()} faixa(s) selecionada(s)` : 'Nenhuma selecionada'}
            </span>
          </div>
        </div>
      </div>

      {/* Modal de Confirmação em Tela Integrado */}
      <ConfirmModal
        isOpen={modalConfig.isOpen}
        title={modalConfig.title}
        message={modalConfig.message}
        confirmText={modalConfig.confirmText}
        variant={modalConfig.variant}
        onConfirm={modalConfig.onConfirm}
        onCancel={() => setModalConfig(prev => ({ ...prev, isOpen: false }))}
      />
    </div>
  );
};
