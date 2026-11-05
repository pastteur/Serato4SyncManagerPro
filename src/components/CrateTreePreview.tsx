import React, { useState, useMemo } from 'react';
import { 
  FolderTree, Music, Search, Disc, Folder, Eye, CheckCircle2, Sparkles, 
  ChevronRight, ChevronDown, Layers, AlertTriangle, Copy, Check, Filter, 
  FolderPlus, ChevronsDown, ChevronsUp, FileText
} from 'lucide-react';
import { SyncSummary, CrateTreeItem, CrateTrack } from '../types';

interface CrateTreePreviewProps {
  summary: SyncSummary | null;
  onOpenFileInFinder?: (filePath: string) => void;
}

export interface EnrichedCrateTrack extends CrateTrack {
  crate_nome: string;
  crate_exibicao: string;
  crate_master: string;
}

export const CrateTreePreview: React.FC<CrateTreePreviewProps> = ({ summary, onOpenFileInFinder }) => {
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

  // Helper para detectar subcrates dentro de subcrates (aninhamento multinível)
  const isNestedSubcrate = (item: CrateTreeItem) => {
    return item.subcrate.includes('%%') || item.nome_crate.split('%%').length > 2;
  };

  const getSubcrateDepth = (item: CrateTreeItem) => {
    return item.nome_crate.split('%%').length;
  };

  // Mapa de Crates do resumo ou dados de demonstração
  const cratesMap: Record<string, CrateTreeItem> = useMemo(() => {
    if (summary?.crates_arvore && Object.keys(summary.crates_arvore).length > 0) {
      return summary.crates_arvore;
    }

    // Dados de demonstração refletindo estrutura real do Serato 4
    return {
      'Sertanejo%%41': {
        nome_crate: 'Sertanejo%%41',
        nome_exibicao: 'Sertanejo -> 41',
        master: 'Sertanejo',
        subcrate: '41',
        total_faixas: 4,
        faixas: [
          { nome: '01 - Modão Raiz Acústico.mp3', caminho_rel: 'Music/MP3/Sertanejo/41/01 - Modão Raiz Acústico.mp3', formato: 'MP3' },
          { nome: '02 - Solteiro Forçado (Ao Vivo).mp3', caminho_rel: 'Music/MP3/Sertanejo/41/02 - Solteiro Forçado (Ao Vivo).mp3', formato: 'MP3' },
          { nome: '03 - Barulho do Foguete.mp3', caminho_rel: 'Music/MP3/Sertanejo/41/03 - Barulho do Foguete.mp3', formato: 'MP3' },
          { nome: '04 - Canudinho (Remix Club).flac', caminho_rel: 'Music/MP3/Sertanejo/41/04 - Canudinho (Remix Club).flac', formato: 'FLAC' },
        ]
      },
      'Sertanejo%%40': {
        nome_crate: 'Sertanejo%%40',
        nome_exibicao: 'Sertanejo -> 40',
        master: 'Sertanejo',
        subcrate: '40',
        total_faixas: 3,
        faixas: [
          { nome: '01 - Oi Balde.mp3', caminho_rel: 'Music/MP3/Sertanejo/40/01 - Oi Balde.mp3', formato: 'MP3' },
          { nome: '02 - Erro Gostoso.wav', caminho_rel: 'Music/MP3/Sertanejo/40/02 - Erro Gostoso.wav', formato: 'WAV' },
          { nome: '03 - Leão (Versão Estendida).mp3', caminho_rel: 'Music/MP3/Sertanejo/40/03 - Leão (Versão Estendida).mp3', formato: 'MP3' },
        ]
      },
      'Pop Rock%%EMO%%01': {
        nome_crate: 'Pop Rock%%EMO%%01',
        nome_exibicao: 'Pop Rock -> EMO -> 01',
        master: 'Pop Rock',
        subcrate: 'EMO%%01',
        total_faixas: 3,
        faixas: [
          { nome: '01 - Welcome To The Black Parade.mp3', caminho_rel: 'Music/MP3/Pop Rock/EMO/01/01 - Welcome To The Black Parade.mp3', formato: 'MP3' },
          { nome: '02 - Misery Business.mp3', caminho_rel: 'Music/MP3/Pop Rock/EMO/01/02 - Misery Business.mp3', formato: 'MP3' },
          { nome: '03 - In The End (2026 Remaster).wav', caminho_rel: 'Music/MP3/Pop Rock/EMO/01/03 - In The End (2026 Remaster).wav', formato: 'WAV' },
        ]
      },
      'Funk%%MegaFunk%%12': {
        nome_crate: 'Funk%%MegaFunk%%12',
        nome_exibicao: 'Funk -> MegaFunk -> 12',
        master: 'Funk',
        subcrate: 'MegaFunk%%12',
        total_faixas: 2,
        faixas: [
          { nome: '01 - MegaFunk SC Especial Verão.mp3', caminho_rel: 'Music/MP3/Funk/MegaFunk/12/01 - MegaFunk SC Especial Verão.mp3', formato: 'MP3' },
          { nome: '02 - Montagem Anos 2000.mp3', caminho_rel: 'Music/MP3/Funk/MegaFunk/12/02 - Montagem Anos 2000.mp3', formato: 'MP3' },
        ]
      }
    };
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
              
              {/* Botões Rápidos de Expandir / Recolher */}
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
            {Object.keys(groupedCrates).sort().map(master => {
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

            {/* Ações da Tabela: Copiar Lista e Busca */}
            <div className="flex items-center gap-2">
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
    </div>
  );
};
