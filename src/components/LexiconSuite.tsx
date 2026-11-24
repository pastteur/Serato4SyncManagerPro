import React, { useState, useEffect } from 'react';
import { 
  Search, HardDrive, Trash2, ShieldAlert, Sparkles, RefreshCw, 
  ArrowRight, CheckCircle2, Music, Radio, Key, Tag, Undo2, 
  Play, Pause, AlertTriangle, Layers, Zap, FolderSearch,
  Flame, Sliders, Wand2, TrendingUp, BarChart2
} from 'lucide-react';

interface LexiconSuiteProps {
  mp3Path?: string;
  seratoPath?: string;
  onPlayTrack?: (track: { url: string; nome: string; artista?: string }) => void;
  onAddLog?: (msg: string) => void;
  onOpenPioneerExport?: () => void;
}

export const LexiconSuite: React.FC<LexiconSuiteProps> = ({
  mp3Path,
  seratoPath,
  onPlayTrack,
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
  const [energyResult, setEnergyResult] = useState<any | null>(null);

  // Estados do Set Curator (Ghost Curator)
  const [curatorCrate, setCuratorCrate] = useState<string>('');
  const [curatorProfile, setCuratorProfile] = useState<'warmup' | 'peak' | 'rollercoaster' | 'harmonic'>('warmup');
  const [curatorMaxTracks, setCuratorMaxTracks] = useState<number>(20);
  const [isCurating, setIsCurating] = useState<boolean>(false);
  const [curatedResult, setCuratedResult] = useState<any | null>(null);

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

  // Dispara Mapeamento de Energia Acústica
  const handleAnalyzeEnergy = async () => {
    if (!isTauri || !mp3Path) {
      alert('Selecione o diretório MP3 Master primeiro.');
      return;
    }
    setIsAnalyzingEnergy(true);
    setEnergyProgress({ processados: 0, total: energyLimit, percentual: 0, faixa_atual: 'Iniciando análise...' });
    if (onAddLog) onAddLog(`⚡ Iniciando cálculo de Energy (1-10) em lote (${energyLimit} faixas) -> Destino: ${targetEnergyTag.toUpperCase()}...`);

    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('analyze_energy_batch', {
        mp3Path,
        limit: energyLimit,
        write: true,
        targetTag: targetEnergyTag
      });
      const data = JSON.parse(resJson);
      setEnergyResult(data);
      if (onAddLog) {
        onAddLog(`✅ Análise de Energy concluída: ${data.gravadas || 0} faixas marcadas com sucesso em ID3v2.3 (${targetEnergyTag}).`);
      }
      alert(`Mapeamento de Energia concluído!\n${data.gravadas || 0} faixas atualizadas com Energy no Serato.`);
    } catch (e: any) {
      alert(`Erro na análise de Energy: ${e}`);
    } finally {
      setIsAnalyzingEnergy(false);
    }
  };

  // Dispara Ghost Curator / Set Curator
  const handleCurateSet = async () => {
    if (!isTauri || !seratoPath || !curatorCrate.trim()) {
      alert('Selecione a pasta _Serato_ e digite o nome de uma Crate de origem.');
      return;
    }
    setIsCurating(true);
    if (onAddLog) onAddLog(`🎧 Ghost Curator: Gerando set curado da crate [${curatorCrate}] (Perfil: ${curatorProfile})...`);

    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('generate_curated_set', {
        seratoPath,
        crateName: curatorCrate.trim(),
        profile: curatorProfile,
        maxTracks: curatorMaxTracks,
        startTrack: null
      });
      const data = JSON.parse(resJson);
      if (data.sucesso) {
        setCuratedResult(data);
        if (onAddLog) {
          onAddLog(`🎯 Ghost Curator concluído: Nova crate [${data.crate_name}] gravada com ${data.total_curated} faixas harmonizadas!`);
        }
        alert(data.mensagem || 'Crate curada gerada com sucesso no Serato!');
      } else {
        alert(`Erro na curadoria: ${data.erro || 'Falha ao gerar set'}`);
      }
    } catch (e: any) {
      alert(`Erro no Ghost Curator: ${e}`);
    } finally {
      setIsCurating(false);
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
              onClick={handleAnalyzeEnergy}
              disabled={isAnalyzingEnergy || !mp3Path}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold bg-rose-500 hover:bg-rose-400 text-black transition shadow cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isAnalyzingEnergy ? 'animate-spin' : ''}`} />
              <span>{isAnalyzingEnergy ? 'Analisando...' : 'Mapear Energia'}</span>
            </button>
          </div>

          <div className="p-3 bg-slate-900/60 border border-slate-800 rounded-xl text-xs space-y-2">
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
              onClick={handleCurateSet}
              disabled={isCurating || !seratoPath || !curatorCrate.trim()}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold bg-indigo-500 hover:bg-indigo-400 text-white transition shadow cursor-pointer disabled:opacity-50"
            >
              <Sparkles className={`w-3.5 h-3.5 ${isCurating ? 'animate-bounce' : ''}`} />
              <span>{isCurating ? 'Curando...' : 'Gerar Crate Curada'}</span>
            </button>
          </div>

          <div className="p-3 bg-slate-900/60 border border-slate-800 rounded-xl text-xs space-y-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-slate-300">Crate de Origem:</span>
              <input
                type="text"
                value={curatorCrate}
                onChange={(e) => setCuratorCrate(e.target.value)}
                placeholder="Ex: Funk%%12 ou Sertanejo"
                disabled={isCurating}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-white text-xs w-48 focus:outline-none focus:border-indigo-400"
              />
            </div>

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

            {curatedResult && (
              <div className="p-2 bg-indigo-950/60 border border-indigo-800 rounded text-[11px] text-indigo-300">
                ✅ Nova Crate <strong>{curatedResult.crate_name}</strong> gerada no Serato com {curatedResult.total_curated} faixas organizadas!
              </div>
            )}
          </div>
        </div>

      </div>

    </div>
  );
};
