import React, { useState, useMemo } from 'react';
import { 
  FolderTree, Music, Search, Disc, Folder, Eye, CheckCircle2, Sparkles, 
  ChevronRight, ChevronDown, Layers, AlertTriangle, Copy, Check, Filter, 
  FolderPlus, ChevronsDown, ChevronsUp, FileText, Play,
  Wrench, ArrowDownAZ, ArrowUpAZ, Shuffle, Save, Edit3, MoreVertical,
  ShieldCheck, Sliders
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

export const CrateTreePreview: React.FC<CrateTreePreviewProps> = ({ 
  summary, 
  onOpenFileInFinder, 
  onPlayTrack,
  seratoPath,
  onAddLog,
  onRefreshCrates
}) => {
  // Estado de seleção: '__ALL__' seleciona a biblioteca geral com todas as músicas alocadas
  const [selectedCrateKey, setSelectedCrateKey] = useState<string>('__ALL__');
  const [trackSearch, setTrackSearch] = useState<string>('');
  const [crateSearch, setCrateSearch] = useState<string>('');
  
  // Controle de expansão das crates (inicia recolhido por padrão)
  const [expandedMasters, setExpandedMasters] = useState<Set<string>>(new Set());
  
  // Filtro para evidenciar subcrates aninhadas (subcrates dentro de subcrates)
  const [filterMode, setFilterMode] = useState<'all' | 'nested'>('all');
  
  // Feedback visual de cópia da lista
  const [copied, setCopied] = useState<boolean>(false);

  // Estados de Playlist Tools
  const [showToolsMenu, setShowToolsMenu] = useState<boolean>(false);
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
    count: number;
    sampleTracks: string[];
  } | null>(null);

  // Helper para detectar subcrates dentro de subcrates (aninhamento multinível)
  const isNestedSubcrate = (item: CrateTreeItem) => {
    return item.subcrate.includes('%%') || item.nome_crate.split('%%').length > 2;
  };

  const getSubcrateDepth = (item: CrateTreeItem) => {
    return item.nome_crate.split('%%').length;
  };

  // Mapa de Crates do resumo real da biblioteca Serato
  const cratesMap: Record<string, CrateTreeItem> = useMemo(() => {
    if (summary?.crates_arvore && Object.keys(summary.crates_arvore).length > 0) {
      return summary.crates_arvore;
    }
    return {};
  }, [summary]);

  // Contagem de subcrates aninhadas em toda a biblioteca
  const totalNestedCrates = useMemo(() => {
    return Object.values(cratesMap).filter(isNestedSubcrate).length;
  }, [cratesMap]);

  // Agrupamento de crates por Estilo Master (ordenadas de A-Z)
  const groupedCrates = useMemo(() => {
    const groups: Record<string, CrateTreeItem[]> = {};
    const search = crateSearch.trim().toLowerCase();

    Object.values(cratesMap).forEach(item => {
      // Se o filtro de aninhadas estiver ativo, só inclui as que forem aninhadas
      if (filterMode === 'nested' && !isNestedSubcrate(item)) {
        return;
      }

      const match = !search ||
        item.nome_crate.toLowerCase().includes(search) ||
        item.nome_exibicao.toLowerCase().includes(search) ||
        item.master.toLowerCase().includes(search) ||
        item.subcrate.toLowerCase().includes(search);

      if (match) {
        if (!groups[item.master]) {
          groups[item.master] = [];
        }
        groups[item.master].push(item);
      }
    });

    // Ordena as subcrates em ordem decrescente (mais recente primeiro)
    Object.keys(groups).forEach(master => {
      groups[master].sort((a, b) => b.subcrate.localeCompare(a.subcrate, undefined, { numeric: true }));
    });

    return groups;
  }, [cratesMap, crateSearch, filterMode]);

  // Lista com TODAS as faixas alocadas em crates (com crate de origem mapeada)
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

  // Total de faixas únicas na biblioteca (desduplicadas por caminho)
  const totalUniqueTracks = useMemo(() => {
    const paths = new Set<string>();
    allTracksAcrossCrates.forEach(t => paths.add(t.caminho_rel || t.nome));
    return paths.size;
  }, [allTracksAcrossCrates]);

  // Crate ativa atual (ou '__ALL__')
  const isAllSelected = selectedCrateKey === '__ALL__';
  const activeCrate = !isAllSelected && cratesMap[selectedCrateKey] ? cratesMap[selectedCrateKey] : null;

  // Filtragem das faixas exibidas na tabela
  const displayedTracks = useMemo(() => {
    const term = trackSearch.trim().toLowerCase();

    if (isAllSelected) {
      if (!term) return allTracksAcrossCrates;
      return allTracksAcrossCrates.filter(t => 
        t.nome.toLowerCase().includes(term) ||
        t.crate_exibicao.toLowerCase().includes(term) ||
        (t.formato && t.formato.toLowerCase().includes(term))
      );
    }

    if (!activeCrate) return [];
    if (!term) return activeCrate.faixas;
    return activeCrate.faixas.filter(t => 
      t.nome.toLowerCase().includes(term) || 
      (t.formato && t.formato.toLowerCase().includes(term))
    );
  }, [isAllSelected, allTracksAcrossCrates, activeCrate, trackSearch]);

  // Distribuição de formatos de áudio da seleção atual
  const formatDistribution = useMemo(() => {
    const counts: Record<string, number> = {};
    const list = isAllSelected ? displayedTracks : (activeCrate?.faixas || []);
    list.forEach(t => {
      const fmt = t.formato || 'OUTROS';
      counts[fmt] = (counts[fmt] || 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [isAllSelected, displayedTracks, activeCrate]);

  // Alternar expansão de uma master específica
  const toggleMaster = (master: string) => {
    setExpandedMasters(prev => {
      const next = new Set(prev);
      if (next.has(master)) next.delete(master);
      else next.add(master);
      return next;
    });
  };

  // Expandir todas
  const handleExpandAll = () => {
    setExpandedMasters(new Set(Object.keys(groupedCrates)));
  };

  // Recolher todas (minimizar tudo)
  const handleCollapseAll = () => {
    setExpandedMasters(new Set());
  };

  // Copiar nomes das faixas para a área de transferência
  const handleCopyTrackList = () => {
    const text = displayedTracks.map((t, i) => `${i + 1}. ${t.nome}`).join('\n');
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // Prepara e exibe a Prévia para aprovação obrigatória (Princípio Analisar -> Prévia -> Ajustar)
  const handlePlaylistToolAction = (action: string, sortMode?: string, prefix?: string) => {
    if (!activeCrate || isAllSelected) {
      alert('Selecione uma Crate específica para aplicar ferramentas de Playlist.');
      return;
    }

    if (!seratoPath) {
      alert('Caminho da pasta _Serato_ não definido. Selecione a unidade no topo primeiro.');
      return;
    }

    setShowToolsMenu(false);

    let title = '';
    let desc = '';
    if (action === 'sort') {
      const modeNames: Record<string, string> = {
        az: 'Alfabética A-Z (por Título)',
        za: 'Alfabética Z-A (por Título)',
        shuffle: 'Embaralhar Faixas (Shuffle Aleatório)'
      };
      title = `Reordenar Crate: ${modeNames[sortMode || 'az'] || sortMode}`;
      desc = `As faixas da Crate serão reordenadas fisicamente dentro do arquivo Serato .crate de acordo com: ${modeNames[sortMode || 'az'] || sortMode}.`;
    } else if (action === 'prefix') {
      title = `Adicionar Prefixo "${prefix}"`;
      desc = `O prefixo "${prefix}" será inserido no início do nome da Crate no Serato.`;
    } else if (action === 'capitalize') {
      title = 'Capitalizar Nome da Crate';
      desc = 'O nome da Crate será padronizado em Title Case (Primeiras Letras Maiúsculas).';
    } else if (action === 'rewrite_order') {
      title = 'Salvar Ordem Atual das Faixas';
      desc = 'A sequência exibida na tela será fixada de forma permanente no arquivo binário .crate.';
    }

    const sample = (activeCrate.faixas || []).slice(0, 5).map(f => f.nome);

    setToolPreview({
      action,
      sortMode,
      prefix,
      title,
      desc,
      crateName: activeCrate.nome_crate,
      count: activeCrate.faixas.length,
      sampleTracks: sample
    });
  };

  // Executa exclusivamente o plano aprovado após confirmação no botão AJUSTAR
  const handleExecuteApprovedTool = async () => {
    if (!toolPreview || !activeCrate) return;
    const { action, sortMode, prefix } = toolPreview;
    setToolPreview(null);
    setIsToolRunning(true);
    setToolStatus(`Executando ${action}...`);

    const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
    if (!isTauri) {
      if (onAddLog) onAddLog(`[Simulação Web] Playlist Tool '${action}' executada na Crate [${activeCrate.nome_crate}].`);
      setIsToolRunning(false);
      setToolStatus(null);
      return;
    }

    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('crate_playlist_tools', {
        seratoPath,
        action,
        crateName: activeCrate.nome_crate,
        prefix: prefix || null,
        sortMode: sortMode || null,
        sources: null,
        paths: action === 'rewrite_order' ? activeCrate.faixas.map(f => f.caminho_rel) : null,
        target: 'subcrate'
      });
      const data = JSON.parse(resJson);
      if (data.sucesso) {
        if (onAddLog) onAddLog(`🎯 Playlist Tool '${action}': ${data.mensagem || 'Operação realizada com sucesso.'}`);
        alert(data.mensagem || 'Operação realizada com sucesso na Crate!');
      } else {
        alert(`Erro na Crate: ${data.erro || 'Falha ao executar ação'}`);
      }
    } catch (e: any) {
      alert(`Falha: ${e}`);
    } finally {
      setIsToolRunning(false);
      setToolStatus(null);
    }
  };

  const isDemo = !summary?.crates_arvore || Object.keys(summary.crates_arvore).length === 0;

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl p-4 shadow-2xl flex flex-col h-full flex-1 overflow-hidden min-h-0 space-y-3">
      {/* Barra Superior com Métricas da Biblioteca e Filtro de Alerta */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-serato-cardBorder shrink-0">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <FolderTree className="w-4 h-4 text-serato-cyan" />
            <span>Navegador de Crates & Subcrates (Serato DJ Pro 4)</span>
            {isDemo && (
              <span className="text-[10px] bg-serato-gold/20 text-serato-gold px-2 py-0.5 rounded-full border border-serato-gold/30 font-mono flex items-center gap-1">
                <Sparkles className="w-3 h-3" />
                Demonstração
              </span>
            )}
          </h3>
          <p className="text-[11px] text-serato-muted">
            Estrutura hierárquica do Serato DJ. Navegue de forma limpa por estilos minimizados e localize subcrates aninhadas indevidamente.
          </p>
        </div>

        {/* Pílulas de Estatísticas da Coleção */}
        <div className="flex items-center gap-2 text-xs font-mono">
          <div className="bg-black/40 border border-white/5 px-2.5 py-1 rounded-lg text-slate-300">
            <span className="text-serato-gold font-bold">{Object.keys(cratesMap).length}</span> playlists
          </div>
          <div className="bg-black/40 border border-white/5 px-2.5 py-1 rounded-lg text-slate-300">
            <span className="text-serato-cyan font-bold">{Object.keys(groupedCrates).length}</span> estilos
          </div>
          <div className="bg-black/40 border border-white/5 px-2.5 py-1 rounded-lg text-slate-300">
            <span className="text-purple-400 font-bold">{allTracksAcrossCrates.length.toLocaleString()}</span> alocações
          </div>
          {totalNestedCrates > 0 && (
            <button
              type="button"
              onClick={() => setFilterMode(filterMode === 'nested' ? 'all' : 'nested')}
              className={`px-2.5 py-1 rounded-lg border font-mono font-bold transition cursor-pointer flex items-center gap-1 ${
                filterMode === 'nested'
                  ? 'bg-amber-950 text-amber-300 border-amber-600 shadow-sm'
                  : 'bg-black/40 text-amber-400/80 border-amber-700/40 hover:text-amber-300'
              }`}
              title="Filtrar apenas as subcrates que possuem subpastas dentro delas para identificar erros de movimentação"
            >
              <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
              <span>{totalNestedCrates} aninhadas</span>
            </button>
          )}
        </div>
      </div>

      {/* Navegador em 2 Colunas */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-3 flex-1 min-h-0 overflow-hidden">
        
        {/* Coluna Esquerda: Árvore de Crates (Estilos Minimizados + "Todos" no Topo) */}
        <div className="md:col-span-5 bg-serato-card border border-serato-cardBorder rounded-lg flex flex-col overflow-hidden min-h-0">
          
          {/* Cabeçalho da Lista de Playlists */}
          <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder flex items-center justify-between shrink-0 gap-2">
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-xs font-bold text-slate-200 flex items-center gap-1.5 uppercase tracking-wide">
                <Folder className="w-3.5 h-3.5 text-serato-gold" />
                Playlists ({Object.keys(groupedCrates).length})
              </span>
              
              {/* Botões Rápidos de Expandir / Recolher / Recarregar */}
              <div className="flex items-center gap-1 ml-1">
                <button
                  type="button"
                  onClick={handleExpandAll}
                  className="p-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-400 hover:text-white transition cursor-pointer"
                  title="Expandir todas as pastas"
                >
                  <ChevronsDown className="w-3 h-3 text-serato-cyan" />
                </button>
                <button
                  type="button"
                  onClick={handleCollapseAll}
                  className="p-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-400 hover:text-white transition cursor-pointer"
                  title="Recolher todas as pastas (minimizar)"
                >
                  <ChevronsUp className="w-3 h-3 text-slate-400" />
                </button>
                {onRefreshCrates && (
                  <button
                    type="button"
                    onClick={onRefreshCrates}
                    className="p-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-400 hover:text-white transition cursor-pointer"
                    title="Recarregar crates da pasta Serato"
                  >
                    <Sparkles className="w-3 h-3 text-amber-400" />
                  </button>
                )}
              </div>
            </div>

            {/* Busca de Crates */}
            <div className="relative flex-1 max-w-[150px]">
              <Search className="w-3 h-3 text-serato-muted absolute left-2 top-2" />
              <input
                type="text"
                value={crateSearch}
                onChange={(e) => setCrateSearch(e.target.value)}
                placeholder="Filtrar..."
                className="w-full pl-6 pr-2 py-1 text-[11px] bg-serato-dark border border-serato-cardBorder rounded text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-cyan font-sans"
              />
            </div>
          </div>

          {/* Lista com Rolagem */}
          <div className="overflow-y-auto flex-1 p-2 space-y-2">
            
            {/* BOTÃO ESPECIAL "TODOS": Acima de todas as crates (antes de Axé) */}
            <button
              type="button"
              onClick={() => setSelectedCrateKey('__ALL__')}
              className={`w-full text-left p-2.5 rounded-lg text-xs flex items-center justify-between transition cursor-pointer border ${
                isAllSelected
                  ? 'bg-serato-cyan/20 text-serato-cyan border-serato-cyan font-bold shadow-lg shadow-serato-cyan/10'
                  : 'bg-black/50 text-slate-200 border-white/10 hover:bg-white/[0.05] hover:border-serato-cyan/40'
              }`}
            >
              <div className="flex items-center gap-2 truncate">
                <div className={`p-1 rounded ${isAllSelected ? 'bg-serato-cyan text-black' : 'bg-slate-800 text-serato-cyan'}`}>
                  <Layers className="w-3.5 h-3.5" />
                </div>
                <div className="truncate">
                  <div className="font-bold text-[11px] uppercase tracking-wide">Todas as Músicas</div>
                  <div className="text-[10px] text-serato-muted font-normal font-sans">Listar faixas de todas as crates</div>
                </div>
              </div>

              <div className="text-right shrink-0 font-mono ml-2">
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                  isAllSelected 
                    ? 'bg-serato-cyan text-black border-serato-cyan font-bold' 
                    : 'bg-serato-cyan/10 text-serato-cyan border-serato-cyan/30'
                }`}>
                  {allTracksAcrossCrates.length.toLocaleString()}
                </span>
              </div>
            </button>

            {/* Aviso quando o filtro de Aninhadas estiver ativo */}
            {filterMode === 'nested' && (
              <div className="bg-amber-950/40 border border-amber-800/60 p-2 rounded text-[11px] text-amber-300 flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                  <span>Exibindo apenas as {totalNestedCrates} subcrates com aninhamento profundo.</span>
                </div>
                <button
                  type="button"
                  onClick={() => setFilterMode('all')}
                  className="text-[10px] underline hover:text-white cursor-pointer shrink-0 font-bold"
                >
                  Ver Todas
                </button>
              </div>
            )}

            {/* Árvore de Masters e Subcrates (Minimizadas por Padrão) */}
            {Object.keys(cratesMap).length === 0 ? (
              <div className="py-12 px-4 text-center text-slate-400 space-y-3">
                <Disc className="w-8 h-8 mx-auto text-slate-600 opacity-60" />
                <p className="text-xs font-semibold text-slate-300">Nenhuma crate carregada em memória.</p>
                <p className="text-[11px] text-slate-500">
                  Carregue suas crates reais a partir da pasta _Serato_ configurada.
                </p>
                {onRefreshCrates && (
                  <button
                    type="button"
                    onClick={onRefreshCrates}
                    className="px-3.5 py-1.5 rounded-lg text-xs font-bold bg-serato-cyan/20 text-serato-cyan border border-serato-cyan/40 hover:bg-serato-cyan/30 transition cursor-pointer"
                  >
                    Carregar Crates do Disco
                  </button>
                )}
              </div>
            ) : Object.keys(groupedCrates).sort().map(master => {
              const subcrates = groupedCrates[master];
              const isExpanded = expandedMasters.has(master) || !!crateSearch.trim() || filterMode === 'nested';
              const nestedCountInMaster = subcrates.filter(isNestedSubcrate).length;

              return (
                <div key={master} className="rounded border border-white/5 bg-black/25 overflow-hidden">
                  
                  {/* Cabeçalho do Estilo Master: Clicável para Expandir/Minimizar */}
                  <button
                    type="button"
                    onClick={() => toggleMaster(master)}
                    className="w-full text-left px-2.5 py-1.5 flex items-center justify-between text-xs font-bold text-serato-gold hover:bg-white/[0.04] transition cursor-pointer select-none"
                  >
                    <div className="flex items-center gap-2 truncate">
                      {isExpanded ? (
                        <ChevronDown className="w-3.5 h-3.5 text-serato-gold shrink-0 transition-transform" />
                      ) : (
                        <ChevronRight className="w-3.5 h-3.5 text-slate-500 shrink-0 transition-transform" />
                      )}
                      <Disc className="w-3.5 h-3.5 text-serato-gold shrink-0" />
                      <span className="truncate">{master}</span>
                    </div>

                    <div className="flex items-center gap-1.5 shrink-0 ml-2 font-mono text-[10px]">
                      {nestedCountInMaster > 0 && (
                        <span 
                          className="px-1.5 py-0.2 rounded bg-amber-950/80 text-amber-300 border border-amber-700/60 flex items-center gap-1 font-bold"
                          title={`${nestedCountInMaster} subcrate(s) aninhada(s) dentro de subcrates neste estilo`}
                        >
                          <AlertTriangle className="w-2.5 h-2.5 text-amber-400" />
                          <span>{nestedCountInMaster}</span>
                        </span>
                      )}
                      <span className="text-slate-500">
                        {subcrates.length} sub
                      </span>
                    </div>
                  </button>

                  {/* Subcrates (visíveis apenas se expandido) */}
                  {isExpanded && (
                    <div className="pl-3 pr-1 py-1 space-y-1 bg-black/40 border-t border-white/5">
                      {subcrates.map(sub => {
                        const isSelected = selectedCrateKey === sub.nome_crate;
                        const isNested = isNestedSubcrate(sub);
                        const depth = getSubcrateDepth(sub);

                        return (
                          <button
                            key={sub.nome_crate}
                            type="button"
                            onClick={() => setSelectedCrateKey(sub.nome_crate)}
                            className={`w-full text-left px-2.5 py-1.5 rounded text-xs flex items-center justify-between transition cursor-pointer border ${
                              isSelected
                                ? 'bg-serato-cyan/20 text-serato-cyan border-serato-cyan/50 font-semibold shadow-sm'
                                : isNested
                                ? 'bg-amber-950/15 border-amber-800/40 text-amber-200/90 hover:bg-amber-950/30 hover:border-amber-700'
                                : 'text-slate-300 hover:bg-white/[0.04] hover:text-white border-transparent'
                            }`}
                          >
                            <div className="flex items-center gap-1.5 truncate">
                              <span className="text-slate-500 font-mono text-[10px]">└─</span>
                              <span className="truncate">{sub.subcrate || sub.master}</span>
                              
                              {/* Alerta de Subcrate Aninhada */}
                              {isNested && (
                                <span 
                                  className="text-[9px] font-mono px-1 py-0.2 rounded bg-amber-950 text-amber-300 border border-amber-700 font-bold shrink-0 flex items-center gap-0.5"
                                  title={`Subcrate aninhada em ${depth} níveis. Nome completo: ${sub.nome_exibicao}`}
                                >
                                  <AlertTriangle className="w-2.5 h-2.5 text-amber-400" />
                                  <span>Nível {depth}</span>
                                </span>
                              )}
                            </div>

                            <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-black/50 text-slate-400 shrink-0 ml-1">
                              {sub.total_faixas} faixas
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Coluna Direita: Tabela de Faixas (da Crate Selecionada ou de "TODAS") */}
        <div className="md:col-span-7 bg-serato-card border border-serato-cardBorder rounded-lg flex flex-col overflow-hidden min-h-0">
          
          {/* Cabeçalho da Tabela de Músicas */}
          <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder flex flex-wrap items-center justify-between shrink-0 gap-2">
            <div className="flex items-center space-x-2 truncate">
              {isAllSelected ? (
                <Layers className="w-4 h-4 text-serato-cyan shrink-0" />
              ) : (
                <Music className="w-3.5 h-3.5 text-serato-cyan shrink-0" />
              )}
              <span className="text-xs font-bold text-white truncate max-w-[260px]">
                {isAllSelected 
                  ? 'Todas as Músicas da Biblioteca' 
                  : (activeCrate ? activeCrate.nome_exibicao : 'Selecione uma Crate')}
              </span>
              <span className="text-[10px] bg-serato-cyan/20 text-serato-cyan px-2 py-0.2 rounded-full border border-serato-cyan/30 font-mono shrink-0">
                {displayedTracks.length} faixas
              </span>
            </div>

            {/* Ações da Tabela: Playlist Tools, Copiar Lista e Busca */}
            <div className="flex items-center gap-2 relative">
              <div className="relative">
                <button
                  type="button"
                  onClick={() => {
                    if (isAllSelected || !activeCrate) {
                      setShowToolsMenu(prev => !prev);
                      return;
                    }
                    setShowToolsMenu(prev => !prev);
                  }}
                  disabled={isToolRunning}
                  className={`px-2 py-1 rounded border text-[11px] font-mono flex items-center gap-1 transition cursor-pointer ${
                    !isAllSelected && activeCrate
                      ? 'bg-serato-card hover:bg-slate-700 text-serato-cyan border-serato-cyan/40'
                      : 'bg-slate-800/80 hover:bg-slate-700 text-slate-300 border-slate-700'
                  }`}
                  title={!isAllSelected && activeCrate
                    ? 'Menu de Ferramentas de Crate e Playlist'
                    : 'Selecione uma Crate específica à esquerda para usar as ferramentas'}
                >
                  <Wrench className="w-3 h-3 text-serato-cyan" />
                  <span>{toolStatus || 'Playlist Tools ▾'}</span>
                </button>

                {/* Dropdown Menu de Playlist Tools */}
                {showToolsMenu && (isAllSelected || !activeCrate) && (
                  <div className="absolute right-0 top-8 z-30 w-64 bg-slate-900 border border-slate-700 rounded-lg shadow-2xl p-3 text-xs space-y-1.5 animate-in fade-in duration-100">
                    <div className="font-bold text-serato-cyan flex items-center gap-1.5">
                      <Wrench className="w-3.5 h-3.5" />
                      <span>Ferramentas da Crate</span>
                    </div>
                    <p className="text-[11px] text-slate-300 leading-relaxed">
                      Selecione uma <strong>Crate ou Subcrate</strong> específica na lista à esquerda para habilitar: Prefixo, Capitalizar Nome, Ordenar (A-Z / Z-A / Shuffle) e Salvar Ordem no HD.
                    </p>
                  </div>
                )}

                {showToolsMenu && !isAllSelected && activeCrate && (
                    <div className="absolute right-0 top-8 z-30 w-52 bg-slate-900 border border-slate-700 rounded-lg shadow-2xl py-1 text-xs space-y-0.5 animate-in fade-in duration-100">
                      <div className="px-3 py-1 text-[10px] font-bold text-slate-400 uppercase tracking-wider border-b border-slate-800">
                        Ferramentas da Crate
                      </div>

                      <button
                        type="button"
                        onClick={() => {
                          setShowToolsMenu(false);
                          setPrefixModalOpen(true);
                        }}
                        className="w-full text-left px-3 py-1.5 hover:bg-slate-800 flex items-center gap-2 text-slate-200 hover:text-white transition cursor-pointer"
                      >
                        <Edit3 className="w-3.5 h-3.5 text-serato-cyan" />
                        <span>Adicionar Prefixo...</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handlePlaylistToolAction('capitalize')}
                        className="w-full text-left px-3 py-1.5 hover:bg-slate-800 flex items-center gap-2 text-slate-200 hover:text-white transition cursor-pointer"
                      >
                        <Disc className="w-3.5 h-3.5 text-amber-400" />
                        <span>Capitalizar Nome (Title Case)</span>
                      </button>

                      <div className="border-t border-slate-800 my-1" />

                      <button
                        type="button"
                        onClick={() => handlePlaylistToolAction('sort', 'az')}
                        className="w-full text-left px-3 py-1.5 hover:bg-slate-800 flex items-center gap-2 text-slate-200 hover:text-white transition cursor-pointer"
                      >
                        <ArrowDownAZ className="w-3.5 h-3.5 text-serato-neonGreen" />
                        <span>Ordenar Faixas (A-Z)</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handlePlaylistToolAction('sort', 'za')}
                        className="w-full text-left px-3 py-1.5 hover:bg-slate-800 flex items-center gap-2 text-slate-200 hover:text-white transition cursor-pointer"
                      >
                        <ArrowUpAZ className="w-3.5 h-3.5 text-emerald-400" />
                        <span>Ordenar Faixas (Z-A)</span>
                      </button>

                      <button
                        type="button"
                        onClick={() => handlePlaylistToolAction('sort', 'shuffle')}
                        className="w-full text-left px-3 py-1.5 hover:bg-slate-800 flex items-center gap-2 text-slate-200 hover:text-white transition cursor-pointer"
                      >
                        <Shuffle className="w-3.5 h-3.5 text-purple-400" />
                        <span>Embaralhar Faixas (Shuffle)</span>
                      </button>

                      <div className="border-t border-slate-800 my-1" />

                      <button
                        type="button"
                        onClick={() => handlePlaylistToolAction('rewrite_order')}
                        className="w-full text-left px-3 py-1.5 hover:bg-slate-800 flex items-center gap-2 text-slate-200 hover:text-white transition cursor-pointer"
                      >
                        <Save className="w-3.5 h-3.5 text-sky-400" />
                        <span>Gravar Ordem Atual no HD</span>
                      </button>
                    </div>
                  )}
              </div>

              <button
                type="button"
                onClick={handleCopyTrackList}
                disabled={displayedTracks.length === 0}
                className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 text-[11px] font-mono flex items-center gap-1 transition cursor-pointer disabled:opacity-40"
                title="Copiar lista de faixas para a Área de Transferência"
              >
                {copied ? (
                  <>
                    <Check className="w-3 h-3 text-emerald-400" />
                    <span className="text-emerald-400 font-bold">Copiado!</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3 h-3 text-slate-400" />
                    <span>Copiar Lista</span>
                  </>
                )}
              </button>

              <div className="relative w-40">
                <Search className="w-3 h-3 text-serato-muted absolute left-2 top-2" />
                <input
                  type="text"
                  value={trackSearch}
                  onChange={(e) => setTrackSearch(e.target.value)}
                  placeholder="Buscar faixa..."
                  className="w-full pl-6 pr-2 py-1 text-[11px] bg-serato-dark border border-serato-cardBorder rounded text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-cyan font-sans"
                />
              </div>
            </div>
          </div>

          {/* Tabela de Faixas com Rolagem */}
          <div className="overflow-y-auto flex-1 p-1 bg-[#06080d]">
            {displayedTracks.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-slate-600 text-xs py-10">
                <Music className="w-6 h-6 opacity-30 text-serato-cyan mb-1" />
                <p>Nenhuma faixa encontrada nesta visualização.</p>
              </div>
            ) : (
              <table className="w-full text-left text-xs">
                <thead className="bg-serato-dark/95 text-serato-muted font-mono uppercase text-[10px] border-b border-serato-cardBorder sticky top-0 backdrop-blur-sm z-10">
                  <tr>
                    <th className="py-1.5 px-2 w-10 text-center">#</th>
                    <th className="py-1.5 px-2">Título da Faixa</th>
                    {isAllSelected && <th className="py-1.5 px-2 w-48">Crate / Playlist</th>}
                    <th className="py-1.5 px-2 w-16 text-center">Formato</th>
                    <th className="py-1.5 px-2 w-10 text-center">Ação</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-serato-cardBorder/40 font-mono text-[11px]">
                  {displayedTracks.map((track, idx) => {
                    const enrichedTrack = track as EnrichedCrateTrack;

                    return (
                      <tr key={idx} className="hover:bg-white/[0.03] transition">
                        <td className="py-1.5 px-2 text-center text-slate-500 font-mono">{idx + 1}</td>
                        <td className="py-1.5 px-2 text-slate-200 font-sans font-medium truncate max-w-[280px]" title={track.nome}>
                          {track.nome}
                        </td>

                        {/* Coluna Crate / Playlist (exibida apenas quando "Todos" está selecionado) */}
                        {isAllSelected && (
                          <td className="py-1.5 px-2 text-slate-400 font-sans truncate max-w-[190px]">
                            <button
                              type="button"
                              onClick={() => setSelectedCrateKey(enrichedTrack.crate_nome)}
                              className="text-left text-serato-cyan hover:underline truncate text-[11px] cursor-pointer"
                              title={`Ir para a playlist: ${enrichedTrack.crate_exibicao}`}
                            >
                              {enrichedTrack.crate_exibicao || enrichedTrack.crate_master}
                            </button>
                          </td>
                        )}

                        <td className="py-1.5 px-2 text-center">
                          <span className={`text-[10px] px-1.5 py-0.2 rounded font-mono font-bold ${
                            track.formato === 'FLAC' || track.formato === 'WAV'
                              ? 'bg-purple-950/70 text-purple-300 border border-purple-800/40'
                              : 'bg-cyan-950/70 text-cyan-300 border border-cyan-800/40'
                          }`}>
                            {track.formato || 'MP3'}
                          </span>
                        </td>

                        <td className="py-1.5 px-2 text-center">
                          <div className="flex items-center justify-center gap-1">
                            {onPlayTrack && (
                              <button
                                type="button"
                                onClick={() => onPlayTrack({
                                  caminho: track.caminho_abs || track.caminho_rel,
                                  nome: track.nome
                                })}
                                className="p-1 rounded hover:bg-slate-700 text-serato-gold hover:text-white transition cursor-pointer"
                                title="Tocar no Player nativo"
                              >
                                <Play className="w-3.5 h-3.5 fill-current hover:scale-110 transition-transform" />
                              </button>
                            )}

                            {onOpenFileInFinder && (
                              <button
                                type="button"
                                onClick={() => onOpenFileInFinder(track.caminho_abs || track.caminho_rel)}
                                className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-white transition cursor-pointer"
                                title="Revelar no Finder"
                              >
                                <Eye className="w-3.5 h-3.5 text-serato-cyan hover:scale-110 transition-transform" />
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

          {/* Rodapé da Tabela com Resumo de Formatos e Informação Serato */}
          <div className="bg-serato-header px-3 py-1.5 border-t border-serato-cardBorder text-[10px] text-serato-muted flex flex-wrap items-center justify-between shrink-0 gap-2">
            <div className="flex items-center gap-2">
              <span>Distribuição de Formatos:</span>
              <div className="flex items-center gap-1.5 font-mono">
                {formatDistribution.map(([fmt, count]) => (
                  <span key={fmt} className="text-slate-300 font-bold">
                    {count} <span className="font-normal text-slate-500">{fmt}</span>
                  </span>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-1 text-serato-neonGreen font-mono">
              <CheckCircle2 className="w-3 h-3" />
              <span>Sincronizado no Serato V2</span>
            </div>
          </div>
        </div>
      </div>

      {/* Modal de Prefixo de Crate (Playlist Tools) */}
      {prefixModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-serato-card border border-serato-cardBorder rounded-xl max-w-sm w-full p-4 space-y-3 shadow-2xl">
            <h4 className="text-xs font-bold text-white flex items-center gap-2">
              <Edit3 className="w-4 h-4 text-serato-cyan" />
              <span>Adicionar Prefixo à Crate</span>
            </h4>
            <p className="text-[11px] text-slate-400">
              Digite o prefixo para adicionar ao nome da crate <b>{activeCrate?.nome_exibicao}</b> (ex: <code className="text-amber-300">01. </code> ou <code className="text-amber-300">[WARM] </code>):
            </p>
            <input
              type="text"
              value={prefixInput}
              onChange={(e) => setPrefixInput(e.target.value)}
              className="w-full px-3 py-1.5 bg-slate-900 border border-slate-700 rounded text-xs text-white focus:outline-none focus:border-serato-cyan"
              autoFocus
            />
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setPrefixModalOpen(false)}
                className="px-3 py-1 rounded bg-slate-800 text-slate-300 text-xs hover:bg-slate-700 cursor-pointer"
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
                className="px-3 py-1 rounded bg-serato-cyan text-black font-bold text-xs hover:bg-cyan-300 cursor-pointer"
              >
                Avançar para Prévia
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal de Prévia e Aprovação Obrigatória (Playlist Tools) */}
      {toolPreview && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4">
          <div className="bg-serato-card border border-serato-cardBorder rounded-2xl max-w-md w-full p-5 space-y-4 shadow-2xl animate-in fade-in zoom-in duration-150">
            <div className="flex items-center gap-2.5 pb-2 border-b border-slate-800">
              <div className="p-2 bg-amber-500/10 border border-amber-500/30 rounded-xl text-amber-400">
                <Sliders className="w-5 h-5" />
              </div>
              <div>
                <h4 className="text-sm font-bold text-white flex items-center gap-2">
                  Prévia de Alteração: {toolPreview.title}
                </h4>
                <p className="text-xs text-slate-400">
                  Crate: <strong className="text-white">{toolPreview.crateName}</strong> ({toolPreview.count} faixas)
                </p>
              </div>
            </div>

            <div className="p-3 bg-slate-900/80 border border-slate-800 rounded-xl space-y-2 text-xs">
              <div className="text-slate-300 font-medium">
                {toolPreview.desc}
              </div>
              {toolPreview.sampleTracks.length > 0 && (
                <div className="space-y-1 pt-1">
                  <span className="text-[11px] text-slate-400 uppercase tracking-wider font-semibold">
                    Amostra de faixas afetadas:
                  </span>
                  <div className="bg-slate-950 p-2 rounded border border-slate-800 space-y-1 font-mono text-[11px] text-slate-300 max-h-28 overflow-y-auto">
                    {toolPreview.sampleTracks.map((name, i) => (
                      <div key={i} className="truncate">
                        {i + 1}. {name}
                      </div>
                    ))}
                    {toolPreview.count > toolPreview.sampleTracks.length && (
                      <div className="text-slate-500 italic text-[10px]">
                        ... e mais {toolPreview.count - toolPreview.sampleTracks.length} faixa(s).
                      </div>
                    )}
                  </div>
                </div>
              )}
              <div className="p-2 bg-emerald-950/40 border border-emerald-800/40 rounded text-[11px] text-emerald-400 flex items-center gap-1.5">
                <ShieldCheck className="w-4 h-4 shrink-0" />
                <span>Backup atômico verificado com SHA-256 (.bak) criado antes da gravação física.</span>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
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
                className="px-5 py-2 rounded-xl bg-serato-cyan hover:bg-cyan-300 text-black text-xs font-bold transition shadow-lg shadow-serato-cyan/20 cursor-pointer flex items-center gap-1.5"
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
