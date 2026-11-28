import React, { useState, useMemo, useEffect } from 'react';
import {
  FolderTree, Music, Search, Disc, Folder, Eye, CheckCircle2, Sparkles,
  ChevronRight, ChevronDown, Layers, AlertTriangle, Copy, Check,
  ChevronsDown, ChevronsUp, Play, Wrench, ArrowDownAZ, ArrowUpAZ,
  Shuffle, Save, Edit3, MoreVertical, ShieldCheck, Sliders, GitMerge, X,
  ChevronLeft
} from 'lucide-react';
import { SyncSummary, CrateTreeItem, CrateTrack } from '../types';
import { PlayingTrackInfo } from './AudioPlayerBar';

interface CrateTreePreviewProps {
  summary: SyncSummary | null;
  onOpenFileInFinder?: (filePath: string) => void;
  onPlayTrack?: (track: PlayingTrackInfo) => void;
  seratoPath?: string;
  onAddLog?: (message: string) => void;
  onRefreshCrates?: () => void;
}

export interface EnrichedCrateTrack extends CrateTrack {
  crate_nome: string;
  crate_exibicao: string;
  crate_master: string;
}

const MASTER_PREFIX = '__MASTER__:';
const PAGE_SIZE = 100;

export const CrateTreePreview: React.FC<CrateTreePreviewProps> = ({
  summary,
  onOpenFileInFinder,
  onPlayTrack,
  seratoPath,
  onAddLog,
  onRefreshCrates
}) => {
  // '__ALL__' | '__MASTER__:<master>' | '<nome_crate>'
  const [selectedCrateKey, setSelectedCrateKey] = useState<string>('__ALL__');
  const [trackSearch, setTrackSearch] = useState<string>('');
  const [crateSearch, setCrateSearch] = useState<string>('');
  const [page, setPage] = useState<number>(1);

  const [expandedMasters, setExpandedMasters] = useState<Set<string>>(new Set());
  const [filterMode, setFilterMode] = useState<'all' | 'nested'>('all');
  const [copied, setCopied] = useState<boolean>(false);

  // Estados de Ações na Crate
  const [isToolRunning, setIsToolRunning] = useState<boolean>(false);
  const [toolStatus, setToolStatus] = useState<string | null>(null);
  const [prefixModalOpen, setPrefixModalOpen] = useState<boolean>(false);
  const [prefixInput, setPrefixInput] = useState<string>('01. ');
  const [toolPreview, setToolPreview] = useState<{
    action: string;
    sortMode?: string;
    prefix?: string;
    title: string;
    desc: string;
    crateName: string;
    target: 'master' | 'subcrate';
    count: number;
    sampleTracks: string[];
  } | null>(null);

  // Menu de Contexto + Modais
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    crateName: string;
    isMaster: boolean;
  } | null>(null);
  const [contextCrateName, setContextCrateName] = useState<string>('');
  const [mergeModalOpen, setMergeModalOpen] = useState<boolean>(false);
  const [mergeTargetCrate, setMergeTargetCrate] = useState<string>('');
  const [crossRefModalOpen, setCrossRefModalOpen] = useState<boolean>(false);
  const [crossRefCrate, setCrossRefCrate] = useState<string>('');
  const [subcrateSortMode, setSubcrateSortMode] = useState<'default' | 'count_desc' | 'count_asc'>('default');

  useEffect(() => {
    const handleClick = () => setContextMenu(null);
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setContextMenu(null);
        setPrefixModalOpen(false);
        setMergeModalOpen(false);
        setCrossRefModalOpen(false);
      }
    };
    window.addEventListener('click', handleClick);
    window.addEventListener('keydown', handleKey);
    return () => {
      window.removeEventListener('click', handleClick);
      window.removeEventListener('keydown', handleKey);
    };
  }, []);

  // Resetar página ao trocar filtro/crate
  useEffect(() => {
    setPage(1);
  }, [selectedCrateKey, trackSearch]);

  const isNestedSubcrate = (item: CrateTreeItem) =>
    item.subcrate.includes('%%') || item.nome_crate.split('%%').length > 2;

  const getSubcrateDepth = (item: CrateTreeItem) => item.nome_crate.split('%%').length;

  const cratesMap: Record<string, CrateTreeItem> = useMemo(() => {
    if (summary?.crates_arvore && Object.keys(summary.crates_arvore).length > 0) {
      return summary.crates_arvore;
    }
    return {};
  }, [summary]);

  const totalNestedCrates = useMemo(
    () => Object.values(cratesMap).filter(isNestedSubcrate).length,
    [cratesMap]
  );

  const groupedCrates = useMemo(() => {
    const groups: Record<string, CrateTreeItem[]> = {};
    const search = crateSearch.trim().toLowerCase();

    Object.values(cratesMap).forEach(item => {
      if (filterMode === 'nested' && !isNestedSubcrate(item)) return;
      const match =
        !search ||
        item.nome_crate.toLowerCase().includes(search) ||
        item.nome_exibicao.toLowerCase().includes(search) ||
        item.master.toLowerCase().includes(search) ||
        item.subcrate.toLowerCase().includes(search);

      if (match) {
        if (!groups[item.master]) groups[item.master] = [];
        groups[item.master].push(item);
      }
    });

    Object.keys(groups).forEach(master => {
      if (subcrateSortMode === 'count_desc') {
        groups[master].sort((a, b) => (b.faixas?.length || b.total_faixas) - (a.faixas?.length || a.total_faixas));
      } else if (subcrateSortMode === 'count_asc') {
        groups[master].sort((a, b) => (a.faixas?.length || a.total_faixas) - (b.faixas?.length || b.total_faixas));
      } else {
        groups[master].sort((a, b) => a.subcrate.localeCompare(b.subcrate, undefined, { numeric: true }));
      }
    });

    return groups;
  }, [cratesMap, crateSearch, filterMode, subcrateSortMode]);

  const allTracksAcrossCrates: EnrichedCrateTrack[] = useMemo(() => {
    const list: EnrichedCrateTrack[] = [];
    Object.values(cratesMap).forEach(crate => {
      (crate.faixas || []).forEach(f => {
        list.push({
          ...f,
          crate_nome: crate.nome_crate,
          crate_exibicao: crate.nome_exibicao,
          crate_master: crate.master
        });
      });
    });
    return list;
  }, [cratesMap]);

  const isAllSelected = selectedCrateKey === '__ALL__';
  const isMasterSelected = selectedCrateKey.startsWith(MASTER_PREFIX);
  const activeMasterName = isMasterSelected ? selectedCrateKey.slice(MASTER_PREFIX.length) : null;
  const activeCrate = !isAllSelected && !isMasterSelected && cratesMap[selectedCrateKey] ? cratesMap[selectedCrateKey] : null;

  // Faixas da seleção atual (Todas, Master ou Subcrate)
  const masterTracks: EnrichedCrateTrack[] = useMemo(() => {
    if (!activeMasterName) return [];
    const list: EnrichedCrateTrack[] = [];
    const subs = groupedCrates[activeMasterName] || [];
    subs.forEach(crate => {
      (crate.faixas || []).forEach(f => {
        list.push({
          ...f,
          crate_nome: crate.nome_crate,
          crate_exibicao: crate.nome_exibicao,
          crate_master: crate.master
        });
      });
    });
    return list;
  }, [activeMasterName, groupedCrates]);

  const displayedTracks = useMemo(() => {
    const term = trackSearch.trim().toLowerCase();
    let base: (CrateTrack | EnrichedCrateTrack)[] = [];

    if (isAllSelected) {
      base = allTracksAcrossCrates;
    } else if (isMasterSelected) {
      base = masterTracks;
    } else if (activeCrate) {
      base = activeCrate.faixas || [];
    }

    if (!term) return base;
    return base.filter(t => {
      const enriched = t as EnrichedCrateTrack;
      return (
        t.nome.toLowerCase().includes(term) ||
        (enriched.crate_exibicao && enriched.crate_exibicao.toLowerCase().includes(term)) ||
        (t.formato && t.formato.toLowerCase().includes(term))
      );
    });
  }, [isAllSelected, isMasterSelected, allTracksAcrossCrates, masterTracks, activeCrate, trackSearch]);

  // Paginação instantânea: nunca renderiza >100 nós <tr> no DOM de uma vez
  const totalPages = Math.max(1, Math.ceil(displayedTracks.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const paginatedTracks = useMemo(() => {
    const start = (safePage - 1) * PAGE_SIZE;
    return displayedTracks.slice(start, start + PAGE_SIZE);
  }, [displayedTracks, safePage]);

  const formatDistribution = useMemo(() => {
    const counts: Record<string, number> = {};
    displayedTracks.forEach(t => {
      const fmt = t.formato || 'OUTROS';
      counts[fmt] = (counts[fmt] || 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [displayedTracks]);

  const toggleMasterExpand = (master: string) => {
    setExpandedMasters(prev => {
      const next = new Set(prev);
      if (next.has(master)) next.delete(master);
      else next.add(master);
      return next;
    });
  };

  const handleSelectMaster = (master: string) => {
    setSelectedCrateKey(`${MASTER_PREFIX}${master}`);
    setExpandedMasters(prev => {
      const next = new Set(prev);
      next.add(master);
      return next;
    });
  };

  const handleExpandAll = () => setExpandedMasters(new Set(Object.keys(groupedCrates)));
  const handleCollapseAll = () => setExpandedMasters(new Set());

  const handleCopyTrackList = () => {
    const text = displayedTracks.map((t, i) => `${i + 1}. ${t.nome}`).join('\n');
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleOpenContextMenu = (e: React.MouseEvent, crateName: string, isMaster: boolean) => {
    e.preventDefault();
    e.stopPropagation();
    const menuWidth = 240;
    const menuHeight = 320;
    const x = Math.min(e.clientX, window.innerWidth - menuWidth - 12);
    const y = Math.min(e.clientY, window.innerHeight - menuHeight - 12);
    setContextMenu({ x, y, crateName, isMaster });
    setContextCrateName(crateName);
  };

  const resolveActiveActionTarget = (customCrateName?: string, forceIsMaster?: boolean) => {
    if (customCrateName) {
      const isM = forceIsMaster ?? (customCrateName.startsWith(MASTER_PREFIX) || (!cratesMap[customCrateName] && !!groupedCrates[customCrateName]));
      const cleanName = customCrateName.startsWith(MASTER_PREFIX)
        ? customCrateName.slice(MASTER_PREFIX.length)
        : customCrateName;
      return {
        crateName: cleanName,
        target: (isM ? 'master' : 'subcrate') as 'master' | 'subcrate',
      };
    }
    if (isMasterSelected && activeMasterName) {
      return { crateName: activeMasterName, target: 'master' as const };
    }
    if (!isAllSelected && activeCrate) {
      return { crateName: activeCrate.nome_crate, target: 'subcrate' as const };
    }
    return null;
  };

  const handlePlaylistToolAction = (
    action: string,
    sortMode?: string,
    prefix?: string,
    customCrateName?: string,
    forceIsMaster?: boolean
  ) => {
    const resolved = resolveActiveActionTarget(customCrateName, forceIsMaster);
    if (!resolved) {
      alert('Clique em uma Crate ou Subcrate à esquerda para aplicar esta ação.');
      return;
    }

    if (!seratoPath) {
      alert('Caminho da pasta _Serato_ não definido. Selecione a pasta do Serato no topo primeiro.');
      return;
    }

    setContextMenu(null);

    const { crateName, target } = resolved;
    let display = crateName;
    let count = 0;
    let sample: string[] = [];

    if (target === 'master') {
      const subs = groupedCrates[crateName] || [];
      const tracks = subs.flatMap(s => s.faixas || []);
      display = `${crateName} (${subs.length} playlist${subs.length === 1 ? '' : 's'})`;
      count = tracks.length;
      sample = tracks.slice(0, 5).map(f => f.nome);
    } else {
      const obj = cratesMap[crateName];
      display = obj?.nome_exibicao || crateName;
      count = obj?.faixas?.length || 0;
      sample = (obj?.faixas || []).slice(0, 5).map(f => f.nome);
    }

    let title = '';
    let desc = '';
    if (action === 'sort') {
      const modeNames: Record<string, string> = {
        az: 'Ordem Alfabética A–Z',
        za: 'Ordem Alfabética Z–A',
        shuffle: 'Embaralhar Faixas (Shuffle)'
      };
      title = modeNames[sortMode || 'az'] || 'Ordenar Crate';
      desc = `As faixas de [${display}] serão organizadas no formato ${modeNames[sortMode || 'az'] || sortMode} diretamente nos arquivos .crate do Serato.`;
    } else if (action === 'prefix') {
      title = `Adicionar Prefixo "${prefix}"`;
      desc = `O prefixo "${prefix}" será colocado no início do nome de [${display}] no Serato.`;
    } else if (action === 'capitalize') {
      title = 'Padronizar Maiúsculas (Title Case)';
      desc = `O nome de [${display}] será ajustado para iniciais maiúsculas.`;
    } else if (action === 'rewrite_order') {
      title = 'Salvar Ordem Atual no HD';
      desc = `A sequência atual das faixas em [${display}] será gravada permanentemente no arquivo .crate.`;
    }

    setToolPreview({
      action,
      sortMode,
      prefix,
      title,
      desc,
      crateName,
      target,
      count,
      sampleTracks: sample
    });
  };

  const handleExecuteApprovedTool = async () => {
    if (!toolPreview) return;
    const { action, sortMode, prefix, crateName, target } = toolPreview;
    setToolPreview(null);
    setIsToolRunning(true);
    setToolStatus(`Aplicando...`);

    const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
    if (!isTauri) {
      if (onAddLog) onAddLog(`[Simulação Web] Ação '${action}' aplicada em [${crateName}].`);
      setIsToolRunning(false);
      setToolStatus(null);
      return;
    }

    try {
      const targetCrateObj = cratesMap[crateName];
      const paths = action === 'rewrite_order' && targetCrateObj ? targetCrateObj.faixas.map(f => f.caminho_rel) : null;
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('crate_playlist_tools', {
        seratoPath,
        action,
        crateName,
        prefix: prefix || null,
        sortMode: sortMode || null,
        sources: null,
        paths,
        target
      });
      const data = JSON.parse(resJson);
      if (data.sucesso) {
        if (onAddLog) onAddLog(`🎯 Reorganização de Crates (${action}): ${data.mensagem || 'Concluída com sucesso.'}`);
        if (onRefreshCrates) onRefreshCrates();
        alert(data.mensagem || 'Operação concluída com sucesso!');
      } else {
        alert(`Erro na Crate: ${data.erro || 'Falha ao executar ação'}`);
      }
    } catch (e: unknown) {
      alert(`Falha: ${e}`);
    } finally {
      setIsToolRunning(false);
      setToolStatus(null);
    }
  };

  const handleExecuteMerge = async () => {
    if (!contextCrateName || !mergeTargetCrate) return;
    if (contextCrateName === mergeTargetCrate) {
      alert('Escolha uma crate de destino diferente da crate de origem.');
      return;
    }
    setMergeModalOpen(false);
    setIsToolRunning(true);
    setToolStatus(`Mesclando...`);

    const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
    if (!isTauri) {
      if (onAddLog) onAddLog(`[Simulação Web] Merge de [${contextCrateName}] em [${mergeTargetCrate}].`);
      setIsToolRunning(false);
      setToolStatus(null);
      return;
    }

    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('crate_playlist_tools', {
        seratoPath,
        action: 'merge',
        crateName: mergeTargetCrate,
        sources: [contextCrateName],
        prefix: null,
        sortMode: null,
        paths: null,
        target: 'subcrate'
      });
      const data = JSON.parse(resJson);
      if (data.sucesso) {
        if (onAddLog) onAddLog(`🔀 Fusão de Crates: ${data.mensagem}`);
        if (onRefreshCrates) onRefreshCrates();
        alert(data.mensagem || 'Crates mescladas com sucesso!');
      } else {
        alert(`Erro ao mesclar: ${data.erro || 'Falha ao mesclar crates'}`);
      }
    } catch (e: unknown) {
      alert(`Falha ao mesclar: ${e}`);
    } finally {
      setIsToolRunning(false);
      setToolStatus(null);
    }
  };

  const crossRefData = useMemo(() => {
    if (!crossRefCrate || !cratesMap[crossRefCrate]) return [];
    const sourceTracks = cratesMap[crossRefCrate].faixas || [];
    const results: { trackName: string; caminho: string; otherCrates: string[] }[] = [];

    sourceTracks.forEach(t => {
      const targetRel = t.caminho_rel || t.nome;
      const otherCrates: string[] = [];
      Object.entries(cratesMap).forEach(([cKey, cVal]) => {
        if (cKey !== crossRefCrate) {
          if ((cVal.faixas || []).some(f => (f.caminho_rel || f.nome) === targetRel)) {
            otherCrates.push(cVal.nome_exibicao || cKey);
          }
        }
      });
      if (otherCrates.length > 0) {
        results.push({ trackName: t.nome, caminho: targetRel, otherCrates });
      }
    });
    return results;
  }, [crossRefCrate, cratesMap]);

  const hasActionableSelection = isMasterSelected || (!isAllSelected && !!activeCrate);
  const activeSelectionTitle = isAllSelected
    ? 'Todas as Músicas da Biblioteca'
    : isMasterSelected
    ? `Pasta Master: ${activeMasterName}`
    : activeCrate
    ? activeCrate.nome_exibicao
    : 'Selecione uma Crate';

  const singleCrateSelectedForMerge = !isAllSelected && !isMasterSelected && activeCrate ? activeCrate.nome_crate : null;

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-2xl p-4 shadow-2xl flex flex-col h-full flex-1 overflow-hidden min-h-0 space-y-3">
      {/* Cabeçalho Limpo e Estatísticas */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-serato-cardBorder shrink-0">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <FolderTree className="w-4 h-4 text-emerald-400" />
            <span>Organizador de Crates & Playlists</span>
          </h3>
          <p className="text-[11px] text-serato-muted">
            Clique em qualquer pasta ou subpasta à esquerda para ver as músicas e aplicar ações diretas com segurança.
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono">
          <div className="bg-emerald-500/10 border border-emerald-500/30 px-2.5 py-1 rounded-lg text-emerald-300 font-bold">
            {Object.keys(cratesMap).length} crates
          </div>
          <div className="bg-serato-cyan/10 border border-serato-cyan/30 px-2.5 py-1 rounded-lg text-serato-cyan font-bold">
            {Object.keys(groupedCrates).length} estilos
          </div>
          <div className="bg-purple-500/10 border border-purple-500/30 px-2.5 py-1 rounded-lg text-purple-300 font-bold">
            {allTracksAcrossCrates.length.toLocaleString()} faixas
          </div>
          {totalNestedCrates > 0 && (
            <button
              type="button"
              onClick={() => setFilterMode(filterMode === 'nested' ? 'all' : 'nested')}
              className={`px-2.5 py-1 rounded-lg border font-mono font-bold transition cursor-pointer flex items-center gap-1 ${
                filterMode === 'nested'
                  ? 'bg-amber-950 text-amber-300 border-amber-500'
                  : 'bg-amber-500/10 text-amber-300 border-amber-500/30 hover:bg-amber-500/20'
              }`}
              title="Mostrar apenas subpastas muito profundas"
            >
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
              <span>{totalNestedCrates} aninhadas</span>
            </button>
          )}
        </div>
      </div>

      {/* Layout em 2 Colunas estilo Lexicon */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-3 flex-1 min-h-0 overflow-hidden">
        {/* Coluna Esquerda: Árvore de Playlists */}
        <div className="md:col-span-4 lg:col-span-4 bg-serato-card border border-serato-cardBorder rounded-xl flex flex-col overflow-hidden min-h-0">
          <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder space-y-2 shrink-0">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-bold text-slate-200 flex items-center gap-1.5 uppercase tracking-wide">
                <Folder className="w-3.5 h-3.5 text-amber-400" />
                Playlists ({Object.keys(groupedCrates).length})
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() =>
                    setSubcrateSortMode(m => (m === 'default' ? 'count_desc' : m === 'count_desc' ? 'count_asc' : 'default'))
                  }
                  className="px-1.5 py-0.5 rounded bg-serato-dark hover:bg-slate-700 text-[10px] text-slate-300 border border-white/10 cursor-pointer"
                  title="Alternar ordenação das subcrates"
                >
                  {subcrateSortMode === 'default' ? 'A–Z' : subcrateSortMode === 'count_desc' ? 'Maior↓' : 'Menor↑'}
                </button>
                <button
                  type="button"
                  onClick={handleExpandAll}
                  className="p-1 rounded bg-serato-dark hover:bg-slate-700 text-serato-cyan transition cursor-pointer"
                  title="Abrir todas as pastas"
                >
                  <ChevronsDown className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={handleCollapseAll}
                  className="p-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-400 hover:text-white transition cursor-pointer"
                  title="Fechar todas as pastas"
                >
                  <ChevronsUp className="w-3.5 h-3.5" />
                </button>
                {onRefreshCrates && (
                  <button
                    type="button"
                    onClick={onRefreshCrates}
                    className="p-1 rounded bg-serato-dark hover:bg-slate-700 text-emerald-400 transition cursor-pointer"
                    title="Recarregar Crates do Serato"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>

            <div className="relative">
              <Search className="w-3.5 h-3.5 text-serato-muted absolute left-2.5 top-2" />
              <input
                type="text"
                value={crateSearch}
                onChange={(e) => setCrateSearch(e.target.value)}
                placeholder="Buscar playlist ou estilo..."
                className="w-full pl-8 pr-7 py-1.5 text-xs bg-serato-dark border border-serato-cardBorder rounded-lg text-slate-200 placeholder-serato-muted focus:outline-none focus:border-emerald-400 font-sans"
              />
              {crateSearch && (
                <button
                  type="button"
                  onClick={() => setCrateSearch('')}
                  className="absolute right-2 top-2 text-slate-400 hover:text-white cursor-pointer"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          </div>

          <div className="overflow-y-auto flex-1 p-2 space-y-1.5">
            {/* Todas as Músicas */}
            <button
              type="button"
              onClick={() => setSelectedCrateKey('__ALL__')}
              className={`w-full text-left p-2.5 rounded-xl text-xs flex items-center justify-between transition cursor-pointer border ${
                isAllSelected
                  ? 'bg-emerald-500/15 text-emerald-300 border-emerald-400/60 font-bold shadow-sm'
                  : 'bg-black/40 text-slate-200 border-white/10 hover:bg-white/[0.05]'
              }`}
            >
              <div className="flex items-center gap-2 truncate">
                <div className={`p-1.5 rounded-lg ${isAllSelected ? 'bg-emerald-400 text-black' : 'bg-slate-800 text-emerald-400'}`}>
                  <Layers className="w-3.5 h-3.5" />
                </div>
                <div className="truncate">
                  <div className="font-bold text-xs">Todas as Músicas</div>
                  <div className="text-[10px] text-serato-muted font-normal">Visão geral da biblioteca</div>
                </div>
              </div>
              <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded-full ${
                isAllSelected ? 'bg-emerald-400 text-black' : 'bg-white/10 text-slate-300'
              }`}>
                {allTracksAcrossCrates.length.toLocaleString()}
              </span>
            </button>

            {Object.keys(cratesMap).length === 0 ? (
              <div className="py-12 px-4 text-center text-slate-400 space-y-3">
                <Disc className="w-8 h-8 mx-auto text-slate-600 opacity-60" />
                <p className="text-xs font-semibold text-slate-300">Nenhuma crate carregada.</p>
                {onRefreshCrates && (
                  <button
                    type="button"
                    onClick={onRefreshCrates}
                    className="px-4 py-2 rounded-xl text-xs font-bold bg-emerald-500 text-black hover:bg-emerald-400 transition cursor-pointer"
                  >
                    Carregar Crates Agora
                  </button>
                )}
              </div>
            ) : (
              Object.keys(groupedCrates).sort().map(master => {
                const subcrates = groupedCrates[master];
                const isExpanded = expandedMasters.has(master) || !!crateSearch.trim() || filterMode === 'nested';
                const nestedCountInMaster = subcrates.filter(isNestedSubcrate).length;
                const masterSelected = selectedCrateKey === `${MASTER_PREFIX}${master}`;
                const totalInMaster = subcrates.reduce((acc, s) => acc + (s.faixas?.length || s.total_faixas), 0);
                const hasMultipleSubs = subcrates.length > 1 || (subcrates[0] && subcrates[0].subcrate !== '');

                return (
                  <div
                    key={master}
                    className={`rounded-xl border transition overflow-hidden ${
                      masterSelected
                        ? 'border-serato-cyan/70 bg-serato-cyan/10'
                        : 'border-white/5 bg-black/25'
                    }`}
                  >
                    {/* Linha da Crate Master: Chevron expande/recolhe; clicar no nome SELECIONA a Crate Master */}
                    <div
                      onContextMenu={(e) => handleOpenContextMenu(e, master, true)}
                      className="w-full flex items-center text-xs font-bold hover:bg-white/[0.04] transition select-none group"
                    >
                      {hasMultipleSubs ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleMasterExpand(master);
                          }}
                          className="pl-2 pr-1 py-2 text-slate-400 hover:text-white cursor-pointer shrink-0"
                          title={isExpanded ? 'Recolher subpastas' : 'Mostrar subpastas'}
                        >
                          {isExpanded ? (
                            <ChevronDown className="w-3.5 h-3.5 text-amber-400" />
                          ) : (
                            <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
                          )}
                        </button>
                      ) : (
                        <span className="pl-2.5 pr-1 py-2 shrink-0" />
                      )}

                      <button
                        type="button"
                        onClick={() => {
                          if (!hasMultipleSubs && subcrates[0]) {
                            setSelectedCrateKey(subcrates[0].nome_crate);
                          } else {
                            handleSelectMaster(master);
                          }
                        }}
                        className={`flex-1 text-left px-1.5 py-2 flex items-center justify-between truncate cursor-pointer ${
                          masterSelected || (!hasMultipleSubs && subcrates[0] && selectedCrateKey === subcrates[0].nome_crate)
                            ? 'text-serato-cyan'
                            : 'text-amber-300'
                        }`}
                      >
                        <div className="flex items-center gap-2 truncate">
                          <Disc className="w-3.5 h-3.5 shrink-0" />
                          <span className="truncate">{master}</span>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0 ml-2 font-mono text-[10px]">
                          {nestedCountInMaster > 0 && (
                            <span className="px-1.5 py-0.2 rounded bg-amber-950/80 text-amber-300 border border-amber-700/60 font-bold">
                              {nestedCountInMaster}
                            </span>
                          )}
                          <span className="text-slate-400">
                            {hasMultipleSubs ? `${subcrates.length} • ` : ''}
                            {totalInMaster}
                          </span>
                        </div>
                      </button>

                      <button
                        type="button"
                        onClick={(e) => handleOpenContextMenu(e, master, true)}
                        className="p-1.5 text-slate-400 hover:text-serato-cyan opacity-50 group-hover:opacity-100 transition cursor-pointer"
                        title="Mais ações nesta Crate"
                      >
                        <MoreVertical className="w-3.5 h-3.5" />
                      </button>
                    </div>

                    {/* Subcrates */}
                    {hasMultipleSubs && isExpanded && (
                      <div className="pl-4 pr-1.5 py-1 space-y-1 bg-black/40 border-t border-white/5">
                        {subcrates.map(sub => {
                          const isSelected = selectedCrateKey === sub.nome_crate;
                          const isNested = isNestedSubcrate(sub);
                          const depth = getSubcrateDepth(sub);

                          return (
                            <div
                              key={sub.nome_crate}
                              onContextMenu={(e) => handleOpenContextMenu(e, sub.nome_crate, false)}
                              className={`w-full rounded-lg text-xs flex items-center justify-between transition border group ${
                                isSelected
                                  ? 'bg-serato-cyan/20 text-serato-cyan border-serato-cyan/60 font-semibold'
                                  : isNested
                                  ? 'bg-amber-950/15 border-amber-800/40 text-amber-200/90 hover:bg-amber-950/30'
                                  : 'text-slate-300 hover:bg-white/[0.04] hover:text-white border-transparent'
                              }`}
                            >
                              <button
                                type="button"
                                onClick={() => setSelectedCrateKey(sub.nome_crate)}
                                className="flex-1 text-left px-2 py-1.5 flex items-center justify-between truncate cursor-pointer"
                              >
                                <div className="flex items-center gap-1.5 truncate">
                                  <span className="text-slate-500 font-mono text-[10px]">└─</span>
                                  <span className="truncate">{sub.subcrate || sub.master}</span>
                                  {isNested && (
                                    <span className="text-[9px] font-mono px-1 rounded bg-amber-950 text-amber-300 border border-amber-700 font-bold shrink-0">
                                      Nível {depth}
                                    </span>
                                  )}
                                </div>
                                <span className="text-[10px] font-mono text-slate-400 shrink-0 ml-1">
                                  {sub.total_faixas}
                                </span>
                              </button>

                              <button
                                type="button"
                                onClick={(e) => handleOpenContextMenu(e, sub.nome_crate, false)}
                                className="p-1 text-slate-400 hover:text-serato-cyan opacity-40 group-hover:opacity-100 transition cursor-pointer"
                                title="Ações nesta subcrate"
                              >
                                <MoreVertical className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Coluna Direita: Ações Rápidas Estilo Lexicon + Tabela Paginada */}
        <div className="md:col-span-8 lg:col-span-8 bg-serato-card border border-serato-cardBorder rounded-xl flex flex-col overflow-hidden min-h-0">
          {/* Cabeçalho da seleção */}
          <div className="bg-serato-header px-3.5 py-2.5 border-b border-serato-cardBorder flex flex-wrap items-center justify-between gap-2 shrink-0">
            <div className="flex items-center gap-2 min-w-0">
              {isAllSelected ? (
                <Layers className="w-4 h-4 text-emerald-400 shrink-0" />
              ) : (
                <Music className="w-4 h-4 text-serato-cyan shrink-0" />
              )}
              <span className="text-xs font-bold text-white truncate max-w-[300px]" title={activeSelectionTitle}>
                {activeSelectionTitle}
              </span>
              <span className="text-[10px] bg-serato-cyan/15 text-serato-cyan px-2 py-0.5 rounded-full border border-serato-cyan/30 font-mono font-bold shrink-0">
                {displayedTracks.length.toLocaleString()} faixas
              </span>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCopyTrackList}
                disabled={displayedTracks.length === 0}
                className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-[11px] flex items-center gap-1.5 transition cursor-pointer disabled:opacity-40"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5 text-slate-400" />}
                <span>{copied ? 'Copiado!' : 'Copiar Nomes'}</span>
              </button>

              <div className="relative w-44">
                <Search className="w-3.5 h-3.5 text-serato-muted absolute left-2.5 top-2" />
                <input
                  type="text"
                  value={trackSearch}
                  onChange={(e) => setTrackSearch(e.target.value)}
                  placeholder="Filtrar músicas..."
                  className="w-full pl-8 pr-2 py-1 text-xs bg-serato-dark border border-serato-cardBorder rounded-lg text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-cyan font-sans"
                />
              </div>
            </div>
          </div>

          {/* Faixa de Ações Rápidas Estilo Lexicon (Visível e Direta) */}
          <div className="px-3.5 py-2 bg-black/30 border-b border-serato-cardBorder flex flex-wrap items-center gap-1.5 shrink-0">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mr-1 flex items-center gap-1">
              <Wrench className="w-3 h-3 text-emerald-400" />
              Ações na Crate:
            </span>

            {!hasActionableSelection ? (
              <span className="text-[11px] text-amber-300/90">
                Selecione qualquer <strong>Estilo (Master)</strong> ou <strong>Subcrate</strong> à esquerda para organizar ou renomear.
              </span>
            ) : (
              <>
                <button
                  type="button"
                  disabled={isToolRunning}
                  onClick={() => handlePlaylistToolAction('sort', 'az')}
                  className="px-2.5 py-1 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border border-emerald-500/30 text-[11px] font-semibold flex items-center gap-1 transition cursor-pointer disabled:opacity-40"
                >
                  <ArrowDownAZ className="w-3.5 h-3.5" />
                  <span>{toolStatus || 'Ordenar A–Z'}</span>
                </button>

                <button
                  type="button"
                  disabled={isToolRunning}
                  onClick={() => handlePlaylistToolAction('sort', 'za')}
                  className="px-2.5 py-1 rounded-lg bg-teal-500/15 hover:bg-teal-500/25 text-teal-300 border border-teal-500/30 text-[11px] font-semibold flex items-center gap-1 transition cursor-pointer disabled:opacity-40"
                >
                  <ArrowUpAZ className="w-3.5 h-3.5" />
                  <span>Z–A</span>
                </button>

                <button
                  type="button"
                  disabled={isToolRunning}
                  onClick={() => handlePlaylistToolAction('sort', 'shuffle')}
                  className="px-2.5 py-1 rounded-lg bg-purple-500/15 hover:bg-purple-500/25 text-purple-300 border border-purple-500/30 text-[11px] font-semibold flex items-center gap-1 transition cursor-pointer disabled:opacity-40"
                >
                  <Shuffle className="w-3.5 h-3.5" />
                  <span>Embaralhar</span>
                </button>

                <button
                  type="button"
                  disabled={isToolRunning}
                  onClick={() => setPrefixModalOpen(true)}
                  className="px-2.5 py-1 rounded-lg bg-serato-cyan/15 hover:bg-serato-cyan/25 text-serato-cyan border border-serato-cyan/30 text-[11px] font-semibold flex items-center gap-1 transition cursor-pointer disabled:opacity-40"
                >
                  <Edit3 className="w-3.5 h-3.5" />
                  <span>Prefixo</span>
                </button>

                <button
                  type="button"
                  disabled={isToolRunning}
                  onClick={() => handlePlaylistToolAction('capitalize')}
                  className="px-2.5 py-1 rounded-lg bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 border border-amber-500/30 text-[11px] font-semibold flex items-center gap-1 transition cursor-pointer disabled:opacity-40"
                >
                  <Disc className="w-3.5 h-3.5" />
                  <span>Maiúsculas</span>
                </button>

                {singleCrateSelectedForMerge && (
                  <>
                    <button
                      type="button"
                      disabled={isToolRunning}
                      onClick={() => {
                        setContextCrateName(singleCrateSelectedForMerge);
                        setMergeModalOpen(true);
                      }}
                      className="px-2.5 py-1 rounded-lg bg-sky-500/15 hover:bg-sky-500/25 text-sky-300 border border-sky-500/30 text-[11px] font-semibold flex items-center gap-1 transition cursor-pointer disabled:opacity-40"
                    >
                      <GitMerge className="w-3.5 h-3.5" />
                      <span>Mesclar</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setCrossRefCrate(singleCrateSelectedForMerge);
                        setCrossRefModalOpen(true);
                      }}
                      className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-[11px] font-semibold flex items-center gap-1 transition cursor-pointer"
                    >
                      <Layers className="w-3.5 h-3.5 text-amber-400" />
                      <span>Em Outras Crates</span>
                    </button>
                  </>
                )}
              </>
            )}
          </div>

          {/* Tabela Paginada (Máx 100 linhas no DOM = instantâneo) */}
          <div className="overflow-y-auto flex-1 p-1 bg-[#06080d]">
            {paginatedTracks.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-slate-500 text-xs py-12">
                <Music className="w-7 h-7 opacity-30 text-serato-cyan mb-2" />
                <p>Nenhuma faixa encontrada nesta seleção.</p>
              </div>
            ) : (
              <table className="w-full text-left text-xs">
                <thead className="bg-serato-dark/95 text-serato-muted font-mono uppercase text-[10px] border-b border-serato-cardBorder sticky top-0 backdrop-blur-sm z-10">
                  <tr>
                    <th className="py-2 px-2.5 w-12 text-center">#</th>
                    <th className="py-2 px-2.5">Título da Faixa</th>
                    {(isAllSelected || isMasterSelected) && <th className="py-2 px-2.5 w-48">Crate</th>}
                    <th className="py-2 px-2.5 w-20 text-center">Formato</th>
                    <th className="py-2 px-2.5 w-20 text-center">Ações</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-serato-cardBorder/40 font-mono text-[11px]">
                  {paginatedTracks.map((track, idx) => {
                    const globalIdx = (safePage - 1) * PAGE_SIZE + idx + 1;
                    const enrichedTrack = track as EnrichedCrateTrack;

                    return (
                      <tr key={`${track.caminho_rel}-${globalIdx}`} className="hover:bg-white/[0.03] transition">
                        <td className="py-1.5 px-2.5 text-center text-slate-500">{globalIdx}</td>
                        <td className="py-1.5 px-2.5 text-slate-200 font-sans font-medium truncate max-w-[300px]" title={track.nome}>
                          {track.nome}
                        </td>

                        {(isAllSelected || isMasterSelected) && (
                          <td className="py-1.5 px-2.5 font-sans truncate max-w-[190px]">
                            <button
                              type="button"
                              onClick={() => setSelectedCrateKey(enrichedTrack.crate_nome)}
                              className="text-left text-serato-cyan hover:underline truncate text-[11px] cursor-pointer"
                            >
                              {enrichedTrack.crate_exibicao || enrichedTrack.crate_master}
                            </button>
                          </td>
                        )}

                        <td className="py-1.5 px-2.5 text-center">
                          <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${
                            track.formato === 'FLAC' || track.formato === 'WAV'
                              ? 'bg-purple-950/70 text-purple-300 border border-purple-800/40'
                              : 'bg-cyan-950/70 text-cyan-300 border border-cyan-800/40'
                          }`}>
                            {track.formato || 'MP3'}
                          </span>
                        </td>

                        <td className="py-1.5 px-2.5 text-center">
                          <div className="flex items-center justify-center gap-1">
                            {onPlayTrack && (
                              <button
                                type="button"
                                onClick={() => onPlayTrack({
                                  caminho: track.caminho_abs || track.caminho_rel,
                                  nome: track.nome
                                })}
                                className="p-1 rounded hover:bg-slate-700 text-amber-400 hover:text-white transition cursor-pointer"
                                title="Ouvir prévia"
                              >
                                <Play className="w-3.5 h-3.5 fill-current" />
                              </button>
                            )}
                            {onOpenFileInFinder && (
                              <button
                                type="button"
                                onClick={() => onOpenFileInFinder(track.caminho_abs || track.caminho_rel)}
                                className="p-1 rounded hover:bg-slate-700 text-serato-cyan hover:text-white transition cursor-pointer"
                                title="Abrir pasta no Finder"
                              >
                                <Eye className="w-3.5 h-3.5" />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          {/* Rodapé com Paginação e Formatos */}
          <div className="bg-serato-header px-3.5 py-2 border-t border-serato-cardBorder text-[11px] text-serato-muted flex flex-wrap items-center justify-between shrink-0 gap-2">
            <div className="flex items-center gap-2 font-mono">
              {formatDistribution.slice(0, 5).map(([fmt, count]) => (
                <span key={fmt} className="text-slate-300 font-bold text-[10px]">
                  {count} <span className="font-normal text-slate-500">{fmt}</span>
                </span>
              ))}
            </div>

            {totalPages > 1 && (
              <div className="flex items-center gap-1.5 font-mono text-[11px]">
                <button
                  type="button"
                  disabled={safePage <= 1}
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 disabled:opacity-35 cursor-pointer flex items-center"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                </button>
                <span className="text-slate-300 px-1">
                  Página <strong className="text-white">{safePage}</strong> / {totalPages}
                </span>
                <button
                  type="button"
                  disabled={safePage >= totalPages}
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 disabled:opacity-35 cursor-pointer flex items-center"
                >
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            )}

            <div className="flex items-center gap-1 text-emerald-400 font-mono text-[10px]">
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>Backup automático ativo</span>
            </div>
          </div>
        </div>
      </div>

      {/* Menu de Contexto Flutuante (Botão Direito ou ⋮) */}
      {contextMenu && (
        <div
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
          className="fixed z-50 w-56 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl py-1.5 text-xs space-y-0.5"
        >
          <div className="px-3 py-1.5 text-[10px] font-bold text-emerald-400 uppercase tracking-wider border-b border-slate-800 truncate">
            {contextMenu.isMaster ? `Estilo Master: ${contextMenu.crateName}` : contextMenu.crateName}
          </div>
          <button
            type="button"
            onClick={() => handlePlaylistToolAction('sort', 'az', undefined, contextMenu.crateName, contextMenu.isMaster)}
            className="w-full text-left px-3 py-1.5 hover:bg-slate-800 flex items-center gap-2 text-slate-200 cursor-pointer"
          >
            <ArrowDownAZ className="w-3.5 h-3.5 text-emerald-400" />
            <span>Ordenar A–Z</span>
          </button>
          <button
            type="button"
            onClick={() => handlePlaylistToolAction('sort', 'za', undefined, contextMenu.crateName, contextMenu.isMaster)}
            className="w-full text-left px-3 py-1.5 hover:bg-slate-800 flex items-center gap-2 text-slate-200 cursor-pointer"
          >
            <ArrowUpAZ className="w-3.5 h-3.5 text-teal-400" />
            <span>Ordenar Z–A</span>
          </button>
          <button
            type="button"
            onClick={() => handlePlaylistToolAction('sort', 'shuffle', undefined, contextMenu.crateName, contextMenu.isMaster)}
            className="w-full text-left px-3 py-1.5 hover:bg-slate-800 flex items-center gap-2 text-slate-200 cursor-pointer"
          >
            <Shuffle className="w-3.5 h-3.5 text-purple-400" />
            <span>Embaralhar Faixas</span>
          </button>
          <div className="border-t border-slate-800 my-1" />
          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              if (contextMenu.isMaster) {
                setSelectedCrateKey(`${MASTER_PREFIX}${contextMenu.crateName}`);
              } else {
                setSelectedCrateKey(contextMenu.crateName);
              }
              setPrefixModalOpen(true);
            }}
            className="w-full text-left px-3 py-1.5 hover:bg-slate-800 flex items-center gap-2 text-slate-200 cursor-pointer"
          >
            <Edit3 className="w-3.5 h-3.5 text-serato-cyan" />
            <span>Adicionar Prefixo...</span>
          </button>
          <button
            type="button"
            onClick={() => handlePlaylistToolAction('capitalize', undefined, undefined, contextMenu.crateName, contextMenu.isMaster)}
            className="w-full text-left px-3 py-1.5 hover:bg-slate-800 flex items-center gap-2 text-slate-200 cursor-pointer"
          >
            <Disc className="w-3.5 h-3.5 text-amber-400" />
            <span>Capitalizar Nome</span>
          </button>
          {!contextMenu.isMaster && (
            <>
              <button
                type="button"
                onClick={() => handlePlaylistToolAction('rewrite_order', undefined, undefined, contextMenu.crateName, false)}
                className="w-full text-left px-3 py-1.5 hover:bg-slate-800 flex items-center gap-2 text-slate-200 cursor-pointer"
              >
                <Save className="w-3.5 h-3.5 text-sky-400" />
                <span>Gravar Ordem no HD</span>
              </button>
              <div className="border-t border-slate-800 my-1" />
              <button
                type="button"
                onClick={() => {
                  const targetName = contextMenu.crateName;
                  setContextMenu(null);
                  setContextCrateName(targetName);
                  setMergeModalOpen(true);
                }}
                className="w-full text-left px-3 py-1.5 hover:bg-slate-800 flex items-center gap-2 text-slate-200 cursor-pointer"
              >
                <GitMerge className="w-3.5 h-3.5 text-sky-400" />
                <span>Mesclar com outra Crate...</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  const targetName = contextMenu.crateName;
                  setContextMenu(null);
                  setCrossRefCrate(targetName);
                  setCrossRefModalOpen(true);
                }}
                className="w-full text-left px-3 py-1.5 hover:bg-slate-800 flex items-center gap-2 text-slate-200 cursor-pointer"
              >
                <Layers className="w-3.5 h-3.5 text-amber-400" />
                <span>Ver Faixas em Outras Crates</span>
              </button>
            </>
          )}
        </div>
      )}

      {/* Modal de Prefixo */}
      {prefixModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-serato-card border border-serato-cardBorder rounded-2xl max-w-sm w-full p-5 space-y-3 shadow-2xl">
            <h4 className="text-sm font-bold text-white flex items-center gap-2">
              <Edit3 className="w-4 h-4 text-serato-cyan" />
              <span>Adicionar Prefixo à Crate</span>
            </h4>
            <p className="text-xs text-slate-300">
              Digite o texto para colocar antes do nome de <strong>{activeMasterName || activeCrate?.nome_exibicao}</strong> (ex: <code className="text-amber-300">01. </code>):
            </p>
            <input
              type="text"
              value={prefixInput}
              onChange={(e) => setPrefixInput(e.target.value)}
              className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-xl text-xs text-white focus:outline-none focus:border-serato-cyan"
              autoFocus
            />
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setPrefixModalOpen(false)}
                className="px-3 py-1.5 rounded-xl bg-slate-800 text-slate-300 text-xs hover:bg-slate-700 cursor-pointer"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => {
                  setPrefixModalOpen(false);
                  if (prefixInput.trim()) {
                    handlePlaylistToolAction('prefix', undefined, prefixInput.trim());
                  }
                }}
                className="px-4 py-1.5 rounded-xl bg-emerald-500 text-black font-bold text-xs hover:bg-emerald-400 cursor-pointer"
              >
                Ver Prévia
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal de Mesclagem */}
      {mergeModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-serato-card border border-serato-cardBorder rounded-2xl max-w-md w-full p-5 space-y-3 shadow-2xl">
            <h4 className="text-sm font-bold text-white flex items-center gap-2">
              <GitMerge className="w-4 h-4 text-sky-400" />
              <span>Mesclar Crates</span>
            </h4>
            <p className="text-xs text-slate-300">
              Copiar todas as músicas de <strong>{contextCrateName}</strong> para outra crate sem duplicar faixas:
            </p>
            <select
              value={mergeTargetCrate}
              onChange={(e) => setMergeTargetCrate(e.target.value)}
              className="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-xl text-xs text-white focus:outline-none focus:border-serato-cyan"
            >
              <option value="">Selecione a Crate de destino...</option>
              {Object.values(cratesMap)
                .filter(c => c.nome_crate !== contextCrateName)
                .sort((a, b) => a.nome_exibicao.localeCompare(b.nome_exibicao))
                .map(c => (
                  <option key={c.nome_crate} value={c.nome_crate}>
                    {c.nome_exibicao} ({c.total_faixas})
                  </option>
                ))}
            </select>
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setMergeModalOpen(false)}
                className="px-3 py-1.5 rounded-xl bg-slate-800 text-slate-300 text-xs hover:bg-slate-700 cursor-pointer"
              >
                Cancelar
              </button>
              <button
                type="button"
                disabled={!mergeTargetCrate}
                onClick={handleExecuteMerge}
                className="px-4 py-1.5 rounded-xl bg-emerald-500 text-black font-bold text-xs hover:bg-emerald-400 disabled:opacity-40 cursor-pointer"
              >
                Mesclar Agora
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Cross Reference */}
      {crossRefModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-serato-card border border-serato-cardBorder rounded-2xl max-w-lg w-full p-5 space-y-3 shadow-2xl">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-bold text-white flex items-center gap-2">
                <Layers className="w-4 h-4 text-amber-400" />
                <span>Faixas repetidas em outras Crates</span>
              </h4>
              <button type="button" onClick={() => setCrossRefModalOpen(false)} className="text-slate-400 hover:text-white cursor-pointer">
                <X className="w-4 h-4" />
              </button>
            </div>
            {crossRefData.length === 0 ? (
              <p className="text-xs text-slate-400 py-4 text-center">
                Nenhuma faixa desta crate aparece em outras crates.
              </p>
            ) : (
              <div className="max-h-72 overflow-y-auto space-y-2 pr-1">
                {crossRefData.map((item, idx) => (
                  <div key={idx} className="p-2.5 rounded-xl bg-slate-900 border border-slate-800 text-xs">
                    <div className="font-semibold text-white truncate">{item.trackName}</div>
                    <div className="text-[11px] text-serato-cyan mt-0.5">
                      Também em: {item.otherCrates.join(', ')}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Modal de Prévia e Confirmação Obrigatória */}
      {toolPreview && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4">
          <div className="bg-serato-card border border-serato-cardBorder rounded-2xl max-w-md w-full p-5 space-y-4 shadow-2xl">
            <div className="flex items-center gap-2.5 pb-2 border-b border-slate-800">
              <div className="p-2 bg-emerald-500/15 border border-emerald-500/30 rounded-xl text-emerald-400">
                <Sliders className="w-5 h-5" />
              </div>
              <div>
                <h4 className="text-sm font-bold text-white">{toolPreview.title}</h4>
                <p className="text-xs text-slate-400">
                  Alvo: <strong className="text-white">{toolPreview.crateName}</strong> ({toolPreview.count} faixas)
                </p>
              </div>
            </div>

            <div className="p-3 bg-slate-900/80 border border-slate-800 rounded-xl space-y-2 text-xs">
              <div className="text-slate-200 font-medium">{toolPreview.desc}</div>
              {toolPreview.sampleTracks.length > 0 && (
                <div className="bg-slate-950 p-2 rounded border border-slate-800 space-y-1 font-mono text-[11px] text-slate-300 max-h-28 overflow-y-auto">
                  {toolPreview.sampleTracks.map((name, i) => (
                    <div key={i} className="truncate">{i + 1}. {name}</div>
                  ))}
                  {toolPreview.count > toolPreview.sampleTracks.length && (
                    <div className="text-slate-500 italic text-[10px]">
                      ... e mais {toolPreview.count - toolPreview.sampleTracks.length} faixa(s).
                    </div>
                  )}
                </div>
              )}
              <div className="p-2 bg-emerald-950/40 border border-emerald-800/40 rounded text-[11px] text-emerald-400 flex items-center gap-1.5">
                <ShieldCheck className="w-4 h-4 shrink-0" />
                <span>Backup automático (.bak) validado antes de gravar.</span>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-1">
              <button
                type="button"
                onClick={() => setToolPreview(null)}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold transition cursor-pointer"
              >
                CANCELAR
              </button>
              <button
                type="button"
                onClick={handleExecuteApprovedTool}
                className="px-5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-black text-xs font-bold transition shadow-lg shadow-emerald-500/20 cursor-pointer flex items-center gap-1.5"
              >
                <CheckCircle2 className="w-4 h-4" />
                <span>AJUSTAR</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
