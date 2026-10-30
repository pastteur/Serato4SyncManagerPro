import React, { useState, useEffect } from 'react';
import { Tag, Sparkles, ShieldCheck, RefreshCw, Search, ArrowRight, Music, ChevronLeft, ChevronRight, Folder, FolderTree, Disc3, Zap, CheckCircle2, Layers } from 'lucide-react';
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
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [renameFilesOnDisk, setRenameFilesOnDisk] = useState<boolean>(false);
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

  const [totalFound, setTotalFound] = useState<number>(0);
  const [totalDirty, setTotalDirty] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const pageSize = 50;

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

  // Carrega lista de faixas conforme filtros e paginação
  const loadScan = async (
    targetPage: number = page,
    search: string = searchTerm,
    crate: string = selectedCrate,
    sub: string = selectedSubcrate,
    incSubs: boolean = includeSubcrates,
    mode: 'full' | 'crate' | 'dj' = namingMode
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
        const offset = (targetPage - 1) * pageSize;
        const resJson = await invoke<string>('scan_tags_doctor', {
          mp3Path,
          limit: pageSize,
          offset,
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
    }
  };

  // Escuta eventos de streaming do batch apply
  useEffect(() => {
    let unlistenProgress: (() => void) | undefined;
    let unlistenFinished: (() => void) | undefined;

    const setupListeners = async () => {
      const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
      if (isTauri) {
        const { listen } = await import('@tauri-apps/api/event');
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
      }
    };

    setupListeners();
    loadCrates();

    return () => {
      if (unlistenProgress) unlistenProgress();
      if (unlistenFinished) unlistenFinished();
    };
  }, [mp3Path]);

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
      title: 'Aplicar Correções na Página',
      message: msg,
      confirmText: `Aplicar em ${selectedItems.length} Faixas`,
      variant: 'info',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsApplying(true);
        onAddLog(`✍️ Gravando tags higienizadas em ${selectedItems.length} arquivo(s)...`);

        try {
          const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            const resJson = await invoke<string>('apply_tags_doctor', {
              itemsJson: JSON.stringify(selectedItems),
              renameFiles: renameFilesOnDisk
            });
            const data = JSON.parse(resJson);

            if (data.sucesso) {
              onAddLog(`🎯 Concluído! ${data.atualizados} música(s) atualizadas com sucesso nas tags oficiais.`);
              loadScan(page, searchTerm, selectedCrate, selectedSubcrate, includeSubcrates);
            } else {
              onAddLog(`❌ Erro ao gravar tags: ${data.erro}`);
            }
          }
        } catch (e) {
          onAddLog(`❌ Falha ao gravar tags: ${e}`);
        } finally {
          setIsApplying(false);
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
      ? `⚡ Deseja aplicar a higienização de tags ID3 e RENOMEAR FISICAMENTE no disco em:\n\n📂 ${targetLabel}\n🎯 Faixas: ${countLabel}\n\nO Serato continuará lendo normalmente os Beatgrids e Cues.`
      : `⚡ Deseja regravar as tags ID3 oficiais (preservando Serato Markers) em:\n\n📂 ${targetLabel}\n🎯 Faixas: ${countLabel}\n\n(Os nomes dos arquivos no HD não serão alterados)`;

    setModalConfig({
      isOpen: true,
      title: 'Higienização de Tags em Lote',
      message: msg,
      confirmText: 'Sim, Executar Lote',
      variant: 'warning',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsBatchApplying(true);
        setBatchProgress({
          processados: 0,
          total: totalFound,
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
    setPage(1);
    loadScan(1, searchTerm, crateName, '', includeSubcrates);
  };

  // Mudança de Subcrate
  const handleSubcrateChange = (subPath: string) => {
    setSelectedSubcrate(subPath);
    setPage(1);
    loadScan(1, searchTerm, selectedCrate, subPath, includeSubcrates);
  };

  // Toggle incluir subcrates
  const handleToggleIncludeSubcrates = (inc: boolean) => {
    setIncludeSubcrates(inc);
    setPage(1);
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
  const batchButtonLabel = selectedSubcrate
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

          {/* Botão Aplicar Página */}
          <button
            type="button"
            onClick={handleApplyCleanPage}
            disabled={isLoading || isApplying || isBatchApplying || selectedIds.size === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-600 transition disabled:opacity-40 cursor-pointer"
            title="Aplica as tags somente para as faixas selecionadas nesta página"
          >
            <Sparkles className="w-3.5 h-3.5 text-serato-cyan" />
            <span>{isApplying ? 'Gravando...' : `✍️ Aplicar Página (${selectedIds.size})`}</span>
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
              loadScan(page, searchTerm, selectedCrate, selectedSubcrate, includeSubcrates, newMode);
            }}
            className="bg-serato-dark border border-serato-cardBorder text-serato-cyan text-xs font-semibold rounded px-2.5 py-1 focus:outline-none cursor-pointer"
          >
            <option value="full">🌟 Artista - Título (Versão/Remix) - Crate - Álbum</option>
            <option value="crate">📂 Artista - Título (Versão/Remix) - Crate</option>
            <option value="dj">🎵 Artista - Título (Versão/Remix) Clássico</option>
          </select>

          <label className="flex items-center gap-2 text-xs text-slate-300 ml-3 cursor-pointer">
            <input
              type="checkbox"
              checked={renameFilesOnDisk}
              onChange={(e) => setRenameFilesOnDisk(e.target.checked)}
              className="rounded border-slate-700 bg-serato-dark text-serato-cyan focus:ring-0"
            />
            <span>Renomear arquivo no HD</span>
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

      {/* Tabela De / Para (Antes vs Depois) */}
      <div className="flex-1 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20">
        <div className="overflow-y-auto flex-1">
          <table className="w-full text-left text-xs">
            <thead className="bg-serato-header text-serato-muted font-mono uppercase text-[10px] border-b border-serato-cardBorder sticky top-0 z-10">
              <tr>
                <th className="py-2 px-3 w-8 text-center">
                  <input
                    type="checkbox"
                    checked={items.length > 0 && selectedIds.size === items.length}
                    onChange={toggleSelectAll}
                    className="rounded border-slate-700 bg-serato-dark text-serato-cyan focus:ring-0"
                  />
                </th>
                <th className="py-2 px-3">Como Está no Disco (Original)</th>
                <th className="py-2 px-3 w-36">Crate / Pasta Raiz</th>
                <th className="py-2 px-3 w-6 text-center"></th>
                <th className="py-2 px-3">Tags Oficiais & Nome Sugerido</th>
                <th className="py-2 px-3 w-28 text-center">BPM & Tom</th>
                <th className="py-2 px-3 w-16 text-center">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-serato-cardBorder/40 font-mono text-[11px]">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-slate-500 font-sans">
                    <Music className="w-8 h-8 opacity-20 text-serato-cyan mx-auto mb-2" />
                    <p className="font-semibold text-slate-400">Nenhuma faixa carregada no momento.</p>
                    <p className="text-xs text-slate-600 mt-1">Selecione uma Crate ou clique em "Escanear" para analisar e ver as melhorias sugeridas.</p>
                  </td>
                </tr>
              ) : (
                items.map((item) => {
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
                          <span className="text-serato-cyan">{item.artista_sugerido || 'Desconhecido'}</span>
                          <span className="text-slate-500">-</span>
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
                        {item.precisa_limpeza ? (
                          <span className="text-[10px] px-2 py-0.5 rounded-full bg-serato-gold/20 text-serato-gold border border-serato-gold/30 font-bold">
                            Ajustar
                          </span>
                        ) : (
                          <span className="text-[10px] px-2 py-0.5 rounded-full bg-serato-neonGreen/20 text-serato-neonGreen border border-serato-neonGreen/30 font-bold">
                            Limpo
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Paginação */}
        <div className="bg-serato-header px-3 py-2 border-t border-serato-cardBorder flex items-center justify-between text-xs text-serato-muted shrink-0">
          <div>
            Exibindo página <b className="text-white">{page}</b> de <b className="text-white">{Math.max(1, Math.ceil(totalFound / pageSize))}</b> ({totalFound.toLocaleString()} faixas no escopo selecionado)
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                const newP = Math.max(1, page - 1);
                setPage(newP);
                loadScan(newP, searchTerm, selectedCrate, selectedSubcrate, includeSubcrates);
              }}
              disabled={page <= 1 || isLoading}
              className="flex items-center gap-1 px-2.5 py-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-300 disabled:opacity-30 border border-serato-cardBorder cursor-pointer"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              <span>Anterior</span>
            </button>

            <button
              type="button"
              onClick={() => {
                const maxP = Math.ceil(totalFound / pageSize);
                if (page < maxP) {
                  const newP = page + 1;
                  setPage(newP);
                  loadScan(newP, searchTerm, selectedCrate, selectedSubcrate, includeSubcrates);
                }
              }}
              disabled={page >= Math.ceil(totalFound / pageSize) || isLoading}
              className="flex items-center gap-1 px-2.5 py-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-300 disabled:opacity-30 border border-serato-cardBorder cursor-pointer"
            >
              <span>Próxima</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
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
