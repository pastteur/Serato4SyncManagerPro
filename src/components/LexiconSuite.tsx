import React, { useState, useEffect } from 'react';
import { 
  Search, HardDrive, Trash2, ShieldAlert, Sparkles, RefreshCw, 
  ArrowRight, CheckCircle2, Music, Radio, Key, Tag, Undo2, 
  Play, Pause, AlertTriangle, Layers, Zap, FolderSearch,
  Flame, Sliders, Wand2, TrendingUp, BarChart2, ShieldCheck, Check
} from 'lucide-react';
import { OrphanFilesModal } from './OrphanFilesModal';

interface AvailableCrateOption {
  nome_crate: string;
  nome_exibicao: string;
  total_faixas: number;
}

interface LexiconSuiteProps {
  mp3Path?: string;
  seratoPath?: string;
  availableCrates?: AvailableCrateOption[];
  onPlayTrack?: (track: { url: string; nome: string; artista?: string }) => void;
  onOpenFileInFinder?: (filePath: string) => void;
  onMoveToTrash?: (filePath: string, itemId: string) => Promise<boolean>;
  onAddLog?: (msg: string) => void;
  onOpenPioneerExport?: () => void;
}

export const LexiconSuite: React.FC<LexiconSuiteProps> = ({
  mp3Path,
  seratoPath,
  availableCrates = [],
  onPlayTrack,
  onOpenFileInFinder,
  onMoveToTrash,
  onAddLog,
  onOpenPioneerExport
}) => {
  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);

  // Estados da Busca FTS5
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [isSyncingFts, setIsSyncingFts] = useState<boolean>(false);

  // Estados dos Arquivos Órfãos
  const [orphanReport, setOrphanReport] = useState<any | null>(null);
  const [isScanningOrphans, setIsScanningOrphans] = useState<boolean>(false);
  const [isOrphanModalOpen, setIsOrphanModalOpen] = useState<boolean>(false);

  // Estados do DeckWatch
  const [deckwatchTrack, setDeckwatchTrack] = useState<any | null>(null);
  const [isDeckwatchLive, setIsDeckwatchLive] = useState<boolean>(false);

  // Estados do Key Converter
  const [targetKeyFormat, setTargetKeyFormat] = useState<'camelot' | 'musical' | 'openkey'>('camelot');

  // Estados de Undo de Receitas
  const [undoStatus, setUndoStatus] = useState<string | null>(null);

  // Estados do Energy Engine
  const [isAnalyzingEnergy, setIsAnalyzingEnergy] = useState<boolean>(false);
  const [energyProgress, setEnergyProgress] = useState<{
    processados: number;
    total: number;
    percentual: number;
    faixa_atual: string;
  } | null>(null);
  const [targetEnergyTag, setTargetEnergyTag] = useState<'grouping' | 'comment' | 'both'>('grouping');
  const [energyLimit, setEnergyLimit] = useState<number>(50);
  const [energyCrate, setEnergyCrate] = useState<string>('');
  const [energyResult, setEnergyResult] = useState<any | null>(null);
  const [energyPreview, setEnergyPreview] = useState<any | null>(null);
  const [isCommittingEnergy, setIsCommittingEnergy] = useState<boolean>(false);

  const sortedCrates = React.useMemo(() => {
    return [...availableCrates].sort((a, b) =>
      (a.nome_exibicao || a.nome_crate).localeCompare(b.nome_exibicao || b.nome_crate, undefined, { numeric: true })
    );
  }, [availableCrates]);

  // Estados do Set Curator (Ghost Curator)
  const [curatorCrate, setCuratorCrate] = useState<string>('');
  const [curatorProfile, setCuratorProfile] = useState<'warmup' | 'peak' | 'rollercoaster' | 'harmonic'>('warmup');
  const [curatorMaxTracks, setCuratorMaxTracks] = useState<number>(20);
  const [isCurating, setIsCurating] = useState<boolean>(false);
  const [curatedResult, setCuratedResult] = useState<any | null>(null);
  const [curatorPreview, setCuratorPreview] = useState<any | null>(null);
  const [excludeIncomplete, setExcludeIncomplete] = useState<boolean>(false);
  const [isCommittingCurator, setIsCommittingCurator] = useState<boolean>(false);

  // Listener do Progresso de Energia
  useEffect(() => {
    if (!isTauri) return;
    let unlisten: (() => void) | undefined;
    import('@tauri-apps/api/event').then(({ listen }) => {
      listen<string>('energy-progress', (event) => {
        try {
          const payload = JSON.parse(event.payload);
          if (payload.tipo === 'progresso') {
            const perc = payload.total > 0 ? Math.round((payload.processados / payload.total) * 100) : 0;
            setEnergyProgress({
              processados: payload.processados,
              total: payload.total,
              percentual: perc,
              faixa_atual: payload.faixa || ''
            });
          }
        } catch (e) {
          // ignore
        }
      }).then(u => { unlisten = u; });
    });
    return () => { if (unlisten) unlisten(); };
  }, [isTauri]);

  // Polling leve para DeckWatch (Now Playing)
  useEffect(() => {
    if (!isTauri) return;
    let isMounted = true;

    const checkDeck = async () => {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('get_deckwatch', { seratoPath: seratoPath || null });
        const data = JSON.parse(resJson);
        if (isMounted) {
          setDeckwatchTrack(data);
          setIsDeckwatchLive(data.is_live);
        }
      } catch (e) {
        // Silencioso
      }
    };

    checkDeck();
    const interval = setInterval(checkDeck, 4000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [isTauri, seratoPath]);

  // Busca instantânea FTS5 ao digitar (debounce 250ms)
  useEffect(() => {
    if (!isTauri || !searchQuery.trim()) {
      setSearchResults([]);
      return;
    }

    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('search_fts_library', { query: searchQuery, limit: 30 });
        const results = JSON.parse(resJson);
        setSearchResults(Array.isArray(results) ? results : []);
      } catch (e) {
        console.error(e);
      } finally {
        setIsSearching(false);
      }
    }, 250);

    return () => clearTimeout(timer);
  }, [searchQuery, isTauri]);

  // Sincroniza índice FTS5
  const handleSyncFts = async () => {
    if (!isTauri || !mp3Path) {
      alert('Selecione o diretório MP3 Master primeiro.');
      return;
    }
    setIsSyncingFts(true);
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('sync_fts_library', { mp3Path });
      const stats = JSON.parse(resJson);
      if (onAddLog) {
        onAddLog(`⚡ Índice FTS5 atualizado: ${stats.inserted || 0} novas faixas, ${stats.updated || 0} atualizadas.`);
      }
      alert('Índice SQLite FTS5 sincronizado com sucesso!');
    } catch (e: any) {
      alert(`Falha ao sincronizar FTS5: ${e}`);
    } finally {
      setIsSyncingFts(false);
    }
  };

  // Varredura de Arquivos Órfãos
  const handleScanOrphans = async () => {
    if (!isTauri || !mp3Path || !seratoPath) {
      alert('Selecione as pastas MP3 Master e _Serato_ para varrer órfãos.');
      return;
    }
    setIsScanningOrphans(true);
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('scan_unused_files', { mp3Path, seratoPath });
      const data = JSON.parse(resJson);
      setOrphanReport(data);
      if (onAddLog) {
        onAddLog(`🔍 Varredura de Órfãos: ${data.total_unused || 0} faixas encontradas (${data.total_unused_gb || 0} GB sem Crate).`);
      }
    } catch (e: any) {
      alert(`Erro ao escanear órfãos: ${e}`);
    } finally {
      setIsScanningOrphans(false);
    }
  };

  // Desfazer Última Receita (Undo)
  const handleUndoRecipe = async () => {
    if (!isTauri) return;
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('undo_recipe');
      const data = JSON.parse(resJson);
      if (data.sucesso) {
        setUndoStatus(`✅ Ação '${data.recipe_name}' desfeita com sucesso (${data.restored_count} arquivos restaurados).`);
        if (onAddLog) onAddLog(`↩️ Undo executado: ${data.recipe_name} (${data.restored_count} restaurados)`);
      } else {
        setUndoStatus(`⚠️ ${data.erro || 'Nenhuma ação para desfazer.'}`);
      }
    } catch (e: any) {
      setUndoStatus(`❌ Erro no Undo: ${e}`);
    }
  };

  // ETAPA 1 e 2: Análise Acústica e Apresentação de Prévia (Sem Gravação)
  const handleAnalyzeEnergyPreview = async () => {
    if (!isTauri || !mp3Path) {
      alert('Selecione o diretório MP3 Master primeiro.');
      return;
    }
    setIsAnalyzingEnergy(true);
    setEnergyProgress({ processados: 0, total: energyLimit, percentual: 0, faixa_atual: 'Analisando áudio...' });
    if (onAddLog) onAddLog(`⚡ Analisando Energy (1-10) em lote (${energyLimit} faixas) para prévia...`);

    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('analyze_energy_batch', {
        mp3Path,
        limit: energyLimit,
        write: false,
        targetTag: targetEnergyTag,
        seratoPath: energyCrate && seratoPath ? seratoPath : null,
        crateName: energyCrate || null
      });
      const data = JSON.parse(resJson);
      if (!data.sucesso) {
        throw new Error(data.erro || 'Análise de Energy não confirmada.');
      }
      setEnergyPreview(data);
      if (onAddLog) {
        onAddLog(`🔍 Prévia de Energy gerada: ${data.total || 0} faixas analisadas. Aguardando aprovação explícita.`);
      }
    } catch (e: any) {
      alert(`Erro na análise de Energy: ${e}`);
    } finally {
      setIsAnalyzingEnergy(false);
    }
  };

  // ETAPA 3 e 4: Aprovação e Execução no Botão AJUSTAR
  const handleCommitEnergy = async () => {
    if (!energyPreview || !mp3Path) return;
    setIsCommittingEnergy(true);
    if (onAddLog) onAddLog(`✍️ Gravando tags de Energy (${targetEnergyTag.toUpperCase()}) aprovadas pelo usuário...`);

    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('analyze_energy_batch', {
        mp3Path,
        limit: energyLimit,
        write: true,
        targetTag: targetEnergyTag,
        seratoPath: energyCrate && seratoPath ? seratoPath : null,
        crateName: energyCrate || null
      });
      const data = JSON.parse(resJson);
      if (!data.sucesso) {
        throw new Error(data.erro || 'Gravação de Energy não confirmada.');
      }
      setEnergyResult(data);
      setEnergyPreview(null);
      if (onAddLog) {
        onAddLog(`✅ Mapeamento de Energy gravado com sucesso: ${data.gravadas || 0} faixas marcadas no Serato.`);
      }
      alert(`Mapeamento de Energia concluído!\n${data.gravadas || 0} faixas gravadas com sucesso no Serato.`);
    } catch (e: any) {
      alert(`Erro ao gravar tags de Energy: ${e}`);
    } finally {
      setIsCommittingEnergy(false);
    }
  };

  // ETAPA 1 e 2: Análise e Prévia do Set Curado (Sem Gravação Física)
  const handleCurateSetPreview = async () => {
    if (!isTauri || !seratoPath || !curatorCrate.trim()) {
      alert('Selecione a pasta _Serato_ e digite o nome de uma Crate de origem.');
      return;
    }
    setIsCurating(true);
    if (onAddLog) onAddLog(`🎧 Ghost Curator: Gerando prévia do set da crate [${curatorCrate}] (Perfil: ${curatorProfile})...`);

    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('generate_curated_set', {
        seratoPath,
        crateName: curatorCrate.trim(),
        profile: curatorProfile,
        maxTracks: curatorMaxTracks,
        startTrack: null,
        commit: false,
        excludeIncomplete
      });
      const data = JSON.parse(resJson);
      if (data.sucesso) {
        setCuratorPreview(data);
        if (onAddLog) {
          onAddLog(`🔍 Ghost Curator: Prévia gerada com ${data.total_curated} faixas harmonizadas (Confiança média: ${Math.round((data.confianca_media || 0) * 100)}%). Aguardando aprovação.`);
        }
      } else {
        alert(`Erro na curadoria: ${data.erro || 'Falha ao analisar set'}`);
      }
    } catch (e: any) {
      alert(`Erro no Ghost Curator: ${e}`);
    } finally {
      setIsCurating(false);
    }
  };

  // ETAPA 3 e 4: Aprovação e Execução no Botão AJUSTAR
  const handleCommitCuratedSet = async () => {
    if (!curatorPreview || !seratoPath || !curatorCrate.trim()) return;
    setIsCommittingCurator(true);
    if (onAddLog) onAddLog(`💾 Gravando Crate curada aprovada [${curatorPreview.crate_name}] no Serato...`);

    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('generate_curated_set', {
        seratoPath,
        crateName: curatorCrate.trim(),
        profile: curatorProfile,
        maxTracks: curatorMaxTracks,
        startTrack: null,
        commit: true,
        excludeIncomplete
      });
      const data = JSON.parse(resJson);
      if (data.sucesso) {
        setCuratedResult(data);
        setCuratorPreview(null);
        if (onAddLog) {
          onAddLog(`🎯 Ghost Curator concluído: Crate [${data.crate_name}] gravada fisicamente com sucesso!`);
        }
        alert(data.mensagem || 'Crate curada gerada e gravada com sucesso no Serato!');
      } else {
        alert(`Erro ao gravar Crate: ${data.erro || 'Falha na gravação'}`);
      }
    } catch (e: any) {
      alert(`Erro ao gravar Ghost Curator: ${e}`);
    } finally {
      setIsCommittingCurator(false);
    }
  };

  return (
    <div className="space-y-6">
      
      {/* 1. Barra de Busca Instantânea SQLite FTS5 */}
      <div className="bg-serato-card border border-serato-cardBorder rounded-2xl p-5 shadow-lg space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-serato-cyan/10 border border-serato-cyan/30 rounded-xl text-serato-cyan">
              <Search className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                Busca Instantânea FTS5 (Full-Text Search)
                <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded bg-serato-cyan/10 text-serato-cyan border border-serato-cyan/30">
                  SQLite BM25
                </span>
              </h3>
              <p className="text-xs text-slate-400">
                Pesquisa instantânea em sub-milissegundos por artista, título, remix, álbum ou crate.
              </p>
            </div>
          </div>

          <button
            onClick={handleSyncFts}
            disabled={isSyncingFts || !mp3Path}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold bg-slate-800 hover:bg-slate-700 text-slate-300 transition disabled:opacity-50 cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isSyncingFts ? 'animate-spin text-serato-cyan' : ''}`} />
            <span>{isSyncingFts ? 'Indexando...' : 'Sincronizar Índice FTS'}</span>
          </button>
        </div>

        {/* Input */}
        <div className="relative">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Digite termos para buscar (ex: Alok Remix, Vintage Deep, 126 BPM)..."
            className="w-full bg-slate-900 border border-slate-700 rounded-xl pl-10 pr-4 py-2.5 text-sm text-white focus:outline-none focus:border-serato-cyan font-sans placeholder-slate-500 shadow-inner"
          />
          <Search className="w-4 h-4 text-slate-500 absolute left-3.5 top-3.5" />
          {isSearching && (
            <RefreshCw className="w-4 h-4 text-serato-cyan absolute right-3.5 top-3.5 animate-spin" />
          )}
        </div>

        {/* Resultados da Busca */}
        {searchResults.length > 0 && (
          <div className="max-h-64 overflow-y-auto space-y-1.5 border border-slate-800 rounded-xl p-2 bg-slate-950/60">
            {searchResults.map((t, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between p-2.5 rounded-lg bg-slate-900/60 hover:bg-slate-800/80 border border-slate-800/60 transition text-xs"
              >
                <div className="flex items-center gap-3 truncate">
                  <button
                    onClick={() => onPlayTrack && onPlayTrack({ url: t.filepath, nome: t.title || t.filename, artista: t.artist })}
                    className="p-1.5 rounded-lg bg-serato-cyan/10 hover:bg-serato-cyan/20 text-serato-cyan transition shrink-0"
                    title="Ouvir prévia"
                  >
                    <Play className="w-3.5 h-3.5" />
                  </button>
                  <div className="truncate">
                    <span className="font-bold text-white">{t.artist || 'Artista'}</span>
                    <span className="text-slate-400 mx-1.5">•</span>
                    <span className="text-slate-200">{t.title || t.filename}</span>
                    {t.remix_version && (
                      <span className="ml-2 text-[10px] font-mono px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400 border border-purple-500/30">
                        {t.remix_version}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2.5 shrink-0 font-mono text-[11px] text-slate-400">
                  {t.bpm > 0 && <span>{Math.round(t.bpm)} BPM</span>}
                  {t.key && <span className="text-amber-400">{t.key}</span>}
                  <span className="text-slate-500 truncate max-w-[120px]" title={t.crate_name}>
                    {t.crate_name || 'Raiz'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 2. Grid de Utilitários Avançados (Órfãos, Pioneer, Now Playing, Undo) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        
        {/* Card: Scanner de Arquivos Órfãos */}
        <div className="bg-serato-card border border-serato-cardBorder rounded-2xl p-5 shadow-lg space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="p-2 bg-amber-500/10 border border-amber-500/30 rounded-xl text-amber-400">
                <HardDrive className="w-5 h-5" />
              </div>
              <div>
                <h4 className="text-sm font-bold text-white">Scanner de Arquivos Órfãos</h4>
                <p className="text-xs text-slate-400">Encontra áudios no SSD fora de qualquer Crate.</p>
              </div>
            </div>

            <button
              onClick={handleScanOrphans}
              disabled={isScanningOrphans || !mp3Path}
              className="px-3 py-1.5 rounded-xl text-xs font-bold bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 transition disabled:opacity-50 cursor-pointer"
            >
              {isScanningOrphans ? 'Varrendo...' : 'Escanear Órfãos'}
            </button>
          </div>

          {orphanReport && (
            <div className="p-3 bg-slate-900/60 border border-slate-800 rounded-xl text-xs space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-slate-300">Faixas Órfãs Encontradas:</span>
                <span className="font-bold text-amber-400 font-mono">{orphanReport.total_unused} faixas</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-300">Espaço Ocupado sem Crate:</span>
                <span className="font-bold text-rose-400 font-mono">{orphanReport.total_unused_gb} GB</span>
              </div>
              <p className="text-[11px] text-slate-500">
                Essas faixas estão no HD mas não foram adicionadas a nenhuma playlist do Serato.
              </p>
              <div className="pt-2">
                <button
                  type="button"
                  onClick={() => setIsOrphanModalOpen(true)}
                  className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-xl text-xs font-bold bg-amber-400 hover:bg-amber-300 text-black transition cursor-pointer shadow-sm"
                >
                  <FolderSearch className="w-4 h-4" />
                  <span>Visualizar, Reproduzir & Tratar Órfãos</span>
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Card: Exportação Pioneer USB */}
        <div className="bg-serato-card border border-serato-cardBorder rounded-2xl p-5 shadow-lg space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="p-2 bg-orange-500/10 border border-orange-500/30 rounded-xl text-orange-400">
                <Zap className="w-5 h-5" />
              </div>
              <div>
                <h4 className="text-sm font-bold text-white">Exportador Pioneer CDJ USB</h4>
                <p className="text-xs text-slate-400">Gera exportLibrary.db para CDJ-3000 e Rekordbox.</p>
              </div>
            </div>

            <button
              onClick={onOpenPioneerExport}
              className="px-3 py-1.5 rounded-xl text-xs font-bold bg-gradient-to-r from-amber-400 to-orange-400 text-black hover:opacity-90 transition shadow cursor-pointer"
            >
              Abrir Exportador USB
            </button>
          </div>

          <div className="p-3 bg-slate-900/60 border border-slate-800 rounded-xl text-xs text-slate-400 space-y-1">
            <div>• Converte automaticamente marcadores <strong>Serato Markers2</strong> para Hot Cues Pioneer.</div>
            <div>• Organiza mídias em <code>/Contents/Artista/Álbum/Faixa.mp3</code>.</div>
          </div>
        </div>

        {/* Card: DeckWatch & Now Playing (OBS) */}
        <div className="bg-serato-card border border-serato-cardBorder rounded-2xl p-5 shadow-lg space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className={`p-2 rounded-xl border ${
                isDeckwatchLive
                  ? 'bg-rose-500/10 border-rose-500/30 text-rose-400 animate-pulse'
                  : 'bg-slate-800 border-slate-700 text-slate-400'
              }`}>
                <Radio className="w-5 h-5" />
              </div>
              <div>
                <h4 className="text-sm font-bold text-white flex items-center gap-2">
                  DeckWatch (Now Playing)
                  {isDeckwatchLive && (
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-400 border border-rose-500/30 uppercase font-bold">
                      Ao Vivo
                    </span>
                  )}
                </h4>
                <p className="text-xs text-slate-400">Monitor de reprodução em tempo real para OBS e lives.</p>
              </div>
            </div>
          </div>

          <div className="p-3 bg-slate-900/60 border border-slate-800 rounded-xl text-xs space-y-1">
            <span className="text-[10px] uppercase font-mono text-slate-500">Última Faixa Detectada:</span>
            <div className="font-bold text-white truncate text-sm">
              {deckwatchTrack?.full_name || 'Nenhuma faixa reproduzida recentemente'}
            </div>
            {deckwatchTrack?.played_at && (
              <div className="text-[10px] font-mono text-slate-400">
                Registrado às {deckwatchTrack.played_at}
              </div>
            )}
          </div>
        </div>

        {/* Card: Engine de Receitas & Undo */}
        <div className="bg-serato-card border border-serato-cardBorder rounded-2xl p-5 shadow-lg space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="p-2 bg-purple-500/10 border border-purple-500/30 rounded-xl text-purple-400">
                <Layers className="w-5 h-5" />
              </div>
              <div>
                <h4 className="text-sm font-bold text-white">Receitas & Histórico de Rollback</h4>
                <p className="text-xs text-slate-400">Reversão em 1 clique de renomeações em lote.</p>
              </div>
            </div>

            <button
              onClick={handleUndoRecipe}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition cursor-pointer"
            >
              <Undo2 className="w-3.5 h-3.5 text-purple-400" />
              <span>Desfazer Última Ação</span>
            </button>
          </div>

          {undoStatus && (
            <div className="p-2.5 bg-slate-900/60 border border-slate-800 rounded-xl text-xs text-slate-300">
              {undoStatus}
            </div>
          )}
        </div>

        {/* Card: Energy Engine (Mapeador de Energia Acústica no Serato) */}
        <div className="bg-serato-card border border-serato-cardBorder rounded-2xl p-5 shadow-lg space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="p-2 bg-rose-500/10 border border-rose-500/30 rounded-xl text-rose-400">
                <Flame className="w-5 h-5" />
              </div>
              <div>
                <h4 className="text-sm font-bold text-white flex items-center gap-2">
                  Energy Engine (1 a 10)
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30 uppercase font-bold">
                    Serato Ready
                  </span>
                </h4>
                <p className="text-xs text-slate-400">Analisa RMS e transientes, gravando na coluna do Serato.</p>
              </div>
            </div>

            <button
              onClick={handleAnalyzeEnergyPreview}
              disabled={isAnalyzingEnergy || !mp3Path}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold bg-rose-500 hover:bg-rose-400 text-black transition shadow cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isAnalyzingEnergy ? 'animate-spin' : ''}`} />
              <span>{isAnalyzingEnergy ? 'Analisando...' : 'Mapear Energia (Prévia)'}</span>
            </button>
          </div>

          <div className="p-3 bg-slate-900/60 border border-slate-800 rounded-xl text-xs space-y-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-slate-300">Crate / Subcrate Alvo:</span>
              <select
                value={energyCrate}
                onChange={(e) => setEnergyCrate(e.target.value)}
                disabled={isAnalyzingEnergy}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white font-mono text-[11px] max-w-[240px] focus:outline-none focus:border-rose-400 cursor-pointer"
              >
                <option value="">Toda a Biblioteca (Pasta Master)</option>
                {sortedCrates.map(c => (
                  <option key={c.nome_crate} value={c.nome_crate}>
                    {c.nome_exibicao || c.nome_crate.replace(/%%/g, ' > ')} ({c.total_faixas})
                  </option>
                ))}
              </select>
            </div>

            <div className="flex items-center justify-between gap-2">
              <span className="text-slate-300">Coluna Alvo no Serato:</span>
              <select
                value={targetEnergyTag}
                onChange={(e) => setTargetEnergyTag(e.target.value as any)}
                disabled={isAnalyzingEnergy}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white font-mono text-[11px] focus:outline-none focus:border-rose-400 cursor-pointer"
              >
                <option value="grouping">Grouping (TIT1) [Recomendado]</option>
                <option value="comment">Comments (COMM) [Mixed In Key]</option>
                <option value="both">Ambos (Grouping + Comments)</option>
              </select>
            </div>

            <div className="flex items-center justify-between gap-2">
              <span className="text-slate-300">Limite de Faixas:</span>
              <select
                value={energyLimit}
                onChange={(e) => setEnergyLimit(Number(e.target.value))}
                disabled={isAnalyzingEnergy}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white font-mono text-[11px] focus:outline-none focus:border-rose-400 cursor-pointer"
              >
                <option value={20}>20 Faixas</option>
                <option value={50}>50 Faixas</option>
                <option value={100}>100 Faixas</option>
                <option value={250}>250 Faixas</option>
                <option value={1000}>1.000 Faixas</option>
              </select>
            </div>

            {energyProgress && isAnalyzingEnergy && (
              <div className="space-y-1 pt-1">
                <div className="flex justify-between text-[10px] text-slate-400 font-mono">
                  <span className="truncate max-w-[200px]">{energyProgress.faixa_atual}</span>
                  <span>{energyProgress.percentual}%</span>
                </div>
                <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                  <div
                    className="bg-gradient-to-r from-rose-500 to-amber-400 h-full transition-all duration-200"
                    style={{ width: `${energyProgress.percentual}%` }}
                  />
                </div>
              </div>
            )}
            
            <p className="text-[10px] text-slate-500">
              💡 No Serato DJ Pro, clique com o botão direito nas colunas da biblioteca e marque <strong>Grouping</strong> para ordenar suas Crates do Warm-up ao Peak-Time!
            </p>
          </div>
        </div>

        {/* Card: Set Curator (Ghost Curator - Montador Algorítmico de Sets) */}
        <div className="bg-serato-card border border-serato-cardBorder rounded-2xl p-5 shadow-lg space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="p-2 bg-indigo-500/10 border border-indigo-500/30 rounded-xl text-indigo-400">
                <Wand2 className="w-5 h-5" />
              </div>
              <div>
                <h4 className="text-sm font-bold text-white flex items-center gap-2">
                  Ghost Curator (Set Builder)
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 uppercase font-bold">
                    Camelot + Flow
                  </span>
                </h4>
                <p className="text-xs text-slate-400">Monta sequências perfeitas por harmonia, BPM e curva de energia.</p>
              </div>
            </div>

            <button
              onClick={handleCurateSetPreview}
              disabled={isCurating || !seratoPath || !curatorCrate.trim()}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold bg-indigo-500 hover:bg-indigo-400 text-white transition shadow cursor-pointer disabled:opacity-50"
            >
              <Sparkles className={`w-3.5 h-3.5 ${isCurating ? 'animate-bounce' : ''}`} />
              <span>{isCurating ? 'Curando...' : 'Gerar Prévia de Crate'}</span>
            </button>
          </div>

          <div className="p-3 bg-slate-900/60 border border-slate-800 rounded-xl text-xs space-y-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-slate-300">Crate de Origem (Existente):</span>
              <select
                value={curatorCrate}
                onChange={(e) => setCuratorCrate(e.target.value)}
                disabled={isCurating}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white font-mono text-[11px] w-56 focus:outline-none focus:border-indigo-400 cursor-pointer"
              >
                <option value="">Selecione uma Crate...</option>
                {sortedCrates.map(c => (
                  <option key={c.nome_crate} value={c.nome_crate}>
                    {c.nome_exibicao || c.nome_crate.replace(/%%/g, ' > ')} ({c.total_faixas})
                  </option>
                ))}
              </select>
            </div>
            <p className="text-[10px] text-slate-500">
              💡 O Ghost Curator lê as faixas da crate selecionada acima e cria automaticamente uma nova playlist curada com o perfil escolhido.
            </p>

            <div className="flex items-center justify-between gap-2">
              <span className="text-slate-300">Curva de Energia (Flow):</span>
              <select
                value={curatorProfile}
                onChange={(e) => setCuratorProfile(e.target.value as any)}
                disabled={isCurating}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white font-mono text-[11px] focus:outline-none focus:border-indigo-400 cursor-pointer"
              >
                <option value="warmup">Warm-up (Crescente 3 ➔ 9)</option>
                <option value="peak">Peak-Time (Explosão 8 ➔ 10)</option>
                <option value="harmonic">Harmonic Flow (Camelot Puro)</option>
                <option value="rollercoaster">Montanha-russa de Pista</option>
              </select>
            </div>

            <div className="flex items-center justify-between gap-2">
              <span className="text-slate-300">Quantidade de Faixas:</span>
              <select
                value={curatorMaxTracks}
                onChange={(e) => setCuratorMaxTracks(Number(e.target.value))}
                disabled={isCurating}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white font-mono text-[11px] focus:outline-none focus:border-indigo-400 cursor-pointer"
              >
                <option value={10}>10 Músicas</option>
                <option value={15}>15 Músicas</option>
                <option value={20}>20 Músicas</option>
                <option value={30}>30 Músicas</option>
                <option value={50}>50 Músicas</option>
              </select>
            </div>

            <div className="flex items-center justify-between gap-2 pt-1 border-t border-slate-800">
              <span className="text-slate-300">Filtrar Incompletas:</span>
              <label className="flex items-center gap-2 cursor-pointer text-slate-300 text-[11px]">
                <input
                  type="checkbox"
                  checked={excludeIncomplete}
                  onChange={(e) => setExcludeIncomplete(e.target.checked)}
                  disabled={isCurating}
                  className="rounded bg-slate-800 border-slate-700 text-indigo-500 focus:ring-0"
                />
                <span>Excluir faixas sem análise acústica confiável</span>
              </label>
            </div>

            {curatedResult && (
              <div className="p-2 bg-indigo-950/60 border border-indigo-800 rounded text-[11px] text-indigo-300">
                ✅ Nova Crate <strong>{curatedResult.crate_name}</strong> gerada no Serato com {curatedResult.total_curated} faixas organizadas!
              </div>
            )}
          </div>
        </div>

      </div>

      {/* Modal de Prévia e Aprovação Obrigatória - Energy Engine */}
      {energyPreview && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4">
          <div className="bg-serato-card border border-serato-cardBorder rounded-2xl max-w-lg w-full p-5 space-y-4 shadow-2xl animate-in fade-in zoom-in duration-150">
            <div className="flex items-center gap-2.5 pb-2 border-b border-slate-800">
              <div className="p-2 bg-rose-500/10 border border-rose-500/30 rounded-xl text-rose-400">
                <Flame className="w-5 h-5" />
              </div>
              <div>
                <h4 className="text-sm font-bold text-white flex items-center gap-2">
                  Prévia de Mapeamento: Energy Engine
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30 uppercase">
                    {targetEnergyTag.toUpperCase()}
                  </span>
                </h4>
                <p className="text-xs text-slate-400 font-mono">
                  Plano: {energyPreview.operacao_id || 'ANALYSIS-PREVIEW'}
                </p>
              </div>
            </div>

            <div className="p-3 bg-slate-900/80 border border-slate-800 rounded-xl space-y-2 text-xs">
              <div className="flex items-center justify-between text-slate-300">
                <span>Total de faixas analisadas:</span>
                <strong className="text-white font-mono">{energyPreview.total || 0} faixas</strong>
              </div>
              <div className="flex items-center justify-between text-slate-300">
                <span>Coluna de destino no Serato:</span>
                <strong className="text-rose-400 font-mono">
                  {targetEnergyTag === 'grouping' ? 'Grouping (TIT1)' : targetEnergyTag === 'comment' ? 'Comment (COMM)' : 'Grouping + Comment'}
                </strong>
              </div>

              {energyPreview.resultados && energyPreview.resultados.length > 0 && (
                <div className="space-y-1 pt-1">
                  <span className="text-[11px] text-slate-400 uppercase tracking-wider font-semibold">
                    Amostra de Valores Calculados:
                  </span>
                  <div className="bg-slate-950 p-2 rounded border border-slate-800 space-y-1 font-mono text-[11px] text-slate-300 max-h-36 overflow-y-auto">
                    {energyPreview.resultados.slice(0, 10).map((r: any, idx: number) => (
                      <div key={idx} className="flex justify-between items-center py-0.5 border-b border-slate-900 last:border-0">
                        <span className="truncate max-w-[280px]">{idx + 1}. {r.nome}</span>
                        <span className="px-1.5 py-0.2 rounded bg-rose-950 text-rose-300 border border-rose-800 text-[10px] font-bold">
                          Energy {r.energy || 5} ({Math.round(r.rms_db || -18)} dB)
                        </span>
                      </div>
                    ))}
                    {energyPreview.resultados.length > 10 && (
                      <div className="text-slate-500 italic text-[10px] pt-1">
                        ... e mais {energyPreview.resultados.length - 10} faixa(s) analisada(s).
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div className="p-2 bg-emerald-950/40 border border-emerald-800/40 rounded text-[11px] text-emerald-400 flex items-center gap-1.5">
                <ShieldCheck className="w-4 h-4 shrink-0" />
                <span>Registrado no Journal de auditoria. Suporta restauração instantânea via botão Undo.</span>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setEnergyPreview(null)}
                disabled={isCommittingEnergy}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold transition cursor-pointer"
              >
                CANCELAR
              </button>
              <button
                type="button"
                onClick={handleCommitEnergy}
                disabled={isCommittingEnergy}
                className="px-5 py-2 rounded-xl bg-rose-500 hover:bg-rose-400 text-black text-xs font-bold transition shadow-lg shadow-rose-500/20 cursor-pointer flex items-center gap-1.5 disabled:opacity-50"
              >
                <Check className="w-4 h-4" />
                <span>{isCommittingEnergy ? 'Gravando...' : 'AJUSTAR'}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal de Prévia e Aprovação Obrigatória - Ghost Curator */}
      {curatorPreview && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4">
          <div className="bg-serato-card border border-serato-cardBorder rounded-2xl max-w-xl w-full p-5 space-y-4 shadow-2xl animate-in fade-in zoom-in duration-150">
            <div className="flex items-center gap-2.5 pb-2 border-b border-slate-800">
              <div className="p-2 bg-indigo-500/10 border border-indigo-500/30 rounded-xl text-indigo-400">
                <Wand2 className="w-5 h-5" />
              </div>
              <div>
                <h4 className="text-sm font-bold text-white flex items-center gap-2">
                  Prévia do Set Curado: {curatorPreview.crate_name}
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 uppercase">
                    {curatorProfile.toUpperCase()}
                  </span>
                </h4>
                <p className="text-xs text-slate-400 font-mono">
                  Plano: {curatorPreview.operacao_id || 'CURATOR-PLAN'}
                </p>
              </div>
            </div>

            <div className="p-3 bg-slate-900/80 border border-slate-800 rounded-xl space-y-2.5 text-xs">
              <div className="grid grid-cols-3 gap-2">
                <div className="p-2 bg-slate-950 rounded border border-slate-800 text-center">
                  <div className="text-[10px] text-slate-400">Total de Faixas</div>
                  <div className="text-base font-bold text-white font-mono">{curatorPreview.total_curated || 0}</div>
                </div>
                <div className="p-2 bg-slate-950 rounded border border-slate-800 text-center">
                  <div className="text-[10px] text-slate-400">Confiança Média</div>
                  <div className="text-base font-bold text-emerald-400 font-mono">
                    {Math.round((curatorPreview.confianca_media || 0) * 100)}%
                  </div>
                </div>
                <div className="p-2 bg-slate-950 rounded border border-slate-800 text-center">
                  <div className="text-[10px] text-slate-400">Incompletas / Sem Tom</div>
                  <div className="text-base font-bold text-amber-400 font-mono">
                    {curatorPreview.faixas_incompletas || 0}
                  </div>
                </div>
              </div>

              {curatorPreview.sequencia && curatorPreview.sequencia.length > 0 && (
                <div className="space-y-1 pt-1">
                  <span className="text-[11px] text-slate-400 uppercase tracking-wider font-semibold">
                    Sequência Harmônica Proposta:
                  </span>
                  <div className="bg-slate-950 p-2 rounded border border-slate-800 font-mono text-[11px] text-slate-300 max-h-40 overflow-y-auto space-y-1">
                    {curatorPreview.sequencia.map((item: any, idx: number) => (
                      <div key={idx} className="flex items-center justify-between py-0.5 border-b border-slate-900 last:border-0">
                        <span className="truncate max-w-[260px] text-slate-200">
                          {item.posicao || idx + 1}. {item.titulo || item.arquivo}
                        </span>
                        <div className="flex items-center gap-1.5 shrink-0 text-[10px]">
                          <span className="px-1 py-0.2 rounded bg-indigo-950 text-indigo-300 border border-indigo-800">
                            {item.camelot || '?'}
                          </span>
                          <span className="px-1 py-0.2 rounded bg-slate-800 text-slate-300 font-bold">
                            {item.bpm ? Math.round(item.bpm) : '?'} BPM
                          </span>
                          <span className="px-1 py-0.2 rounded bg-rose-950 text-rose-300">
                            E{item.energy || 5}
                          </span>
                          <span className={`px-1 py-0.2 rounded ${item.confianca >= 0.8 ? 'text-emerald-400' : item.confianca >= 0.5 ? 'text-amber-400' : 'text-rose-400'}`}>
                            {Math.round((item.confianca || 0) * 100)}%
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className="p-2 bg-emerald-950/40 border border-emerald-800/40 rounded text-[11px] text-emerald-400 flex items-center gap-1.5">
                <ShieldCheck className="w-4 h-4 shrink-0" />
                <span>A Crate física Serato só será gravada no disco após sua autorização explícita.</span>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setCuratorPreview(null)}
                disabled={isCommittingCurator}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold transition cursor-pointer"
              >
                CANCELAR
              </button>
              <button
                type="button"
                onClick={handleCommitCuratedSet}
                disabled={isCommittingCurator}
                className="px-5 py-2 rounded-xl bg-indigo-500 hover:bg-indigo-400 text-white text-xs font-bold transition shadow-lg shadow-indigo-500/20 cursor-pointer flex items-center gap-1.5 disabled:opacity-50"
              >
                <Check className="w-4 h-4" />
                <span>{isCommittingCurator ? 'Gravando Crate...' : 'AJUSTAR'}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal de Gerenciamento Completo de Órfãos (Visualizar, Reproduzir, Finder, Excluir) */}
      <OrphanFilesModal
        isOpen={isOrphanModalOpen}
        onClose={() => setIsOrphanModalOpen(false)}
        report={orphanReport}
        mp3Path={mp3Path || ''}
        seratoPath={seratoPath || ''}
        onOpenFileInFinder={onOpenFileInFinder}
        onPlayTrack={(track) => {
          if (onPlayTrack) {
            onPlayTrack({ url: track.caminho, nome: track.nome, artista: track.artista });
          }
        }}
        onMoveToTrash={onMoveToTrash}
        onAddLog={onAddLog}
        onUpdateReport={(updated) => setOrphanReport(updated)}
      />

    </div>
  );
};
