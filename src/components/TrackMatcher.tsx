import React, { useState, useMemo } from 'react';
import { Music, Search, Sparkles, Download, CheckCircle2, AlertTriangle, ExternalLink, ArrowRight, FolderPlus, FileText, Globe, Folder, Zap } from 'lucide-react';

interface TrackMatcherProps {
  mp3Path: string;
  seratoPath: string;
  onAddLog: (message: string) => void;
  onOpenFileInFinder?: (filePath: string) => void;
}

export const TrackMatcher: React.FC<TrackMatcherProps> = ({
  mp3Path,
  seratoPath,
  onAddLog,
  onOpenFileInFinder
}) => {
  const [inputType, setInputType] = useState<'spotify' | 'text' | 'folder' | 'file'>('folder');
  const [inputData, setInputData] = useState<string>('');
  const [crateName, setCrateName] = useState<string>('Novidades Pack');
  const [isMatching, setIsMatching] = useState<boolean>(false);
  const [matchResult, setMatchResult] = useState<any>(null);
  const [exportSuccessMsg, setExportSuccessMsg] = useState<string | null>(null);

  // Filtros de busca e status para os resultados
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'found' | 'upgrades' | 'missing'>('all');

  const filteredEncontradas = useMemo(() => {
    if (!matchResult?.encontradas) return [];
    let list = matchResult.encontradas;
    if (statusFilter === 'upgrades') {
      list = list.filter((it: any) => it.upgrade_disponivel);
    }
    if (!searchTerm.trim()) return list;
    const q = searchTerm.toLowerCase();
    return list.filter((it: any) =>
      it.solicitado?.toLowerCase().includes(q) ||
      it.arquivo_local?.toLowerCase().includes(q) ||
      it.caminho_completo?.toLowerCase().includes(q)
    );
  }, [matchResult, searchTerm, statusFilter]);

  const filteredFaltantes = useMemo(() => {
    if (!matchResult?.faltantes) return [];
    if (!searchTerm.trim()) return matchResult.faltantes;
    const q = searchTerm.toLowerCase();
    return matchResult.faltantes.filter((it: any) =>
      it.solicitado?.toLowerCase().includes(q) ||
      it.caminho_novo?.toLowerCase().includes(q)
    );
  }, [matchResult, searchTerm]);

  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);

  const handleSelectIncomingFolder = async () => {
    if (isTauri) {
      try {
        const { open } = await import('@tauri-apps/plugin-dialog');
        const selected = await open({
          directory: true,
          multiple: false,
          title: 'Selecionar Pasta com Novas Músicas / Downloads'
        });
        if (selected && typeof selected === 'string') {
          setInputData(selected);
          onAddLog(`📂 Pasta de novidades selecionada: ${selected}`);
        }
      } catch (err) {
        console.error('Falha ao abrir diálogo de pasta:', err);
      }
    }
  };

  const handleRunMatch = async (exportCrateNow: boolean = false) => {
    if (!inputData.trim()) {
      onAddLog(
        inputType === 'folder'
          ? '⚠️ Selecione ou informe o caminho da pasta de novidades para cruzar.'
          : '⚠️ Informe o link do Spotify ou a lista de faixas para cruzar.'
      );
      return;
    }
    if (!mp3Path) {
      onAddLog('⚠️ Selecione a pasta MP3 Master antes de realizar o cruzamento.');
      return;
    }

    setIsMatching(true);
    setExportSuccessMsg(null);
    onAddLog(
      inputType === 'folder'
        ? `🎧 Track Matcher: Varrendo pasta de novidades e cruzando contra as 31.355 faixas do HD...`
        : `🎧 Track Matcher: Cruzando playlist contra suas 31.355 faixas do HD...`
    );

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const res = await invoke<string>('match_tracks', {
          inputType,
          inputData,
          mp3Path,
          seratoPath,
          exportCrate: exportCrateNow ? crateName : null
        });
        const parsed = JSON.parse(res);
        setMatchResult(parsed);

        if (parsed.sucesso) {
          if (parsed.tipo_origem === 'folder') {
            onAddLog(`✅ Track Matcher: ${parsed.total_solicitadas} faixas escaneadas na pasta. ${parsed.total_encontradas} já no HD (${parsed.total_upgrades || 0} upgrades de bitrate recomendados) e ${parsed.total_faltantes} faixas inéditas.`);
          } else {
            onAddLog(`✅ Track Matcher: ${parsed.total_encontradas} faixas encontradas no HD (${parsed.total_faltantes} faltantes).`);
          }

          if (parsed.export_serato && parsed.export_serato.sucesso) {
            setExportSuccessMsg(parsed.export_serato.mensagem);
            onAddLog(`🎯 ${parsed.export_serato.mensagem}`);
          }
        } else {
          onAddLog(`❌ Erro no Track Matcher: ${parsed.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Falha ao executar Track Matcher: ${e}`);
    } finally {
      setIsMatching(false);
    }
  };

  const handleCopyMissingToClipboard = () => {
    if (!matchResult || !matchResult.faltantes) return;
    const text = matchResult.faltantes.map((f: any) => f.solicitado).join('\n');
    navigator.clipboard.writeText(text);
    onAddLog(`📋 Lista de ${matchResult.faltantes.length} faixas faltantes copiada para a área de transferência!`);
  };

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl p-4 shadow-2xl flex flex-col h-full flex-1 overflow-hidden min-h-0 space-y-3">
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between pb-2.5 border-b border-serato-cardBorder shrink-0 gap-2">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Music className="w-4 h-4 text-serato-cyan" />
            <span>Track Matcher & Importador de Playlists (Spotify / Web)</span>
            <span className="text-[10px] bg-serato-neonGreen/20 text-serato-neonGreen px-2 py-0.5 rounded-full border border-serato-neonGreen/30 font-mono">
              Cruza com 31.355 músicas do HD
            </span>
          </h3>
          <p className="text-[11px] text-serato-muted">
            Cole uma playlist do Spotify, YouTube Music ou lista de texto. O sistema localiza o que você já tem no HD e cria a Crate no Serato instantaneamente.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {matchResult && matchResult.encontradas && matchResult.encontradas.length > 0 && (
            <button
              type="button"
              onClick={() => handleRunMatch(true)}
              disabled={isMatching}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-serato-cyan hover:bg-cyan-300 text-black shadow-lg shadow-serato-cyan/20 transition cursor-pointer"
            >
              <FolderPlus className="w-3.5 h-3.5" />
              <span>Gerar Crate no Serato ({matchResult.encontradas.length})</span>
            </button>
          )}

          <button
            type="button"
            onClick={() => handleRunMatch(false)}
            disabled={isMatching}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-bold bg-serato-card hover:bg-serato-cyan/20 text-serato-cyan border border-serato-cyan/40 transition disabled:opacity-40 cursor-pointer"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>{isMatching ? 'Cruzando...' : '🔍 Cruzar Playlist'}</span>
          </button>
        </div>
      </div>

      {/* Input Controls */}
      <div className="bg-serato-card p-3 rounded-lg border border-serato-cardBorder space-y-2.5 shrink-0">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs text-slate-300 font-semibold mr-1">Origem do Cruzamento:</span>
            
            <button
              type="button"
              onClick={() => {
                setInputType('folder');
                setInputData('');
              }}
              className={`px-2.5 py-1 text-xs rounded transition flex items-center gap-1.5 cursor-pointer ${
                inputType === 'folder'
                  ? 'bg-serato-gold text-black font-bold shadow'
                  : 'bg-serato-dark text-slate-400 hover:text-white border border-serato-cardBorder'
              }`}
            >
              <Folder className="w-3.5 h-3.5" />
              <span>📁 Pasta de Novidades (Downloads / Packs)</span>
            </button>

            <button
              type="button"
              onClick={() => {
                setInputType('text');
                setInputData('');
              }}
              className={`px-2.5 py-1 text-xs rounded transition flex items-center gap-1.5 cursor-pointer ${
                inputType === 'text'
                  ? 'bg-serato-cyan text-black font-bold'
                  : 'bg-serato-dark text-slate-400 hover:text-white border border-serato-cardBorder'
              }`}
            >
              <FileText className="w-3.5 h-3.5" />
              <span>Texto / Linhas</span>
            </button>

            <button
              type="button"
              onClick={() => {
                setInputType('spotify');
                setInputData('');
              }}
              className={`px-2.5 py-1 text-xs rounded transition flex items-center gap-1.5 cursor-pointer ${
                inputType === 'spotify'
                  ? 'bg-[#1DB954] text-black font-bold'
                  : 'bg-serato-dark text-slate-400 hover:text-white border border-serato-cardBorder'
              }`}
            >
              <Globe className="w-3.5 h-3.5" />
              <span>Spotify URL</span>
            </button>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">Nome da Crate:</span>
            <input
              type="text"
              value={crateName}
              onChange={(e) => setCrateName(e.target.value)}
              className="bg-serato-dark border border-serato-cardBorder px-2.5 py-1 text-xs rounded text-white font-mono w-44 focus:outline-none focus:border-serato-cyan"
            />
          </div>
        </div>

        {inputType === 'folder' ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={inputData}
                onChange={(e) => setInputData(e.target.value)}
                placeholder="Selecione ou cole o caminho da pasta de novos MP3s baixados (ex: /Users/pastteur/Downloads/Pack2026)..."
                className="flex-1 bg-serato-dark border border-serato-cardBorder px-3 py-1.5 text-xs rounded text-slate-200 placeholder-slate-500 font-mono focus:outline-none focus:border-serato-gold"
              />
              <button
                type="button"
                onClick={handleSelectIncomingFolder}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-bold bg-slate-800 hover:bg-slate-700 text-serato-gold border border-serato-gold/40 transition cursor-pointer shrink-0"
              >
                <Folder className="w-3.5 h-3.5 text-serato-gold" />
                <span>Procurar Pasta...</span>
              </button>
            </div>
            <div className="text-[11px] text-slate-400 bg-serato-dark/70 px-2.5 py-1 rounded border border-white/5 flex items-center gap-1.5">
              <Zap className="w-3.5 h-3.5 text-serato-gold shrink-0" />
              <span>
                Varre todos os novos MP3, FLAC, WAV desta pasta e cruza com os 31.355 arquivos do HD. Identifica upgrades de bitrate (ex: 320k vs 128k) e músicas novas que você ainda não possui.
              </span>
            </div>
          </div>
        ) : inputType === 'spotify' ? (
          <input
            type="text"
            value={inputData}
            onChange={(e) => setInputData(e.target.value)}
            placeholder="Cole aqui o link da playlist do Spotify: https://open.spotify.com/playlist/..."
            className="w-full bg-serato-dark border border-serato-cardBorder px-3 py-1.5 text-xs rounded text-slate-200 placeholder-slate-500 focus:outline-none focus:border-serato-cyan"
          />
        ) : (
          <textarea
            value={inputData}
            onChange={(e) => setInputData(e.target.value)}
            placeholder="Cole uma lista de faixas (uma por linha):&#10;Fresno - Porto Alegre&#10;Raimundos - Me lambe&#10;Pitty - Semana Que Vem"
            rows={3}
            className="w-full bg-serato-dark border border-serato-cardBorder p-2 text-xs rounded text-slate-200 placeholder-slate-500 font-mono focus:outline-none focus:border-serato-cyan"
          />
        )}
      </div>

      {exportSuccessMsg && (
        <div className="bg-emerald-950/60 border border-emerald-800/40 text-emerald-300 p-2.5 rounded-lg text-xs flex items-center gap-2 shrink-0">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{exportSuccessMsg}</span>
        </div>
      )}

      {/* Resultados do Cruzamento */}
      <div className="flex-1 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20">
        <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder text-xs flex items-center justify-between text-slate-300">
          <div className="flex items-center gap-3 flex-wrap">
            <span>Resultados: <b className="text-white">{matchResult?.total_solicitadas || 0}</b> faixas na pasta/lista</span>
            <span className="text-emerald-400 font-bold">✅ {matchResult?.total_encontradas || 0} já no HD</span>
            {matchResult?.total_upgrades > 0 && (
              <span className="text-serato-gold font-bold">🚀 {matchResult.total_upgrades} Upgrades de Qualidade</span>
            )}
            <span className="text-rose-400 font-bold">
              {matchResult?.tipo_origem === 'folder' ? '✨' : '⚠️'} {matchResult?.total_faltantes || 0} {matchResult?.tipo_origem === 'folder' ? 'inéditas / novas' : 'faltantes'}
            </span>
          </div>

          {matchResult && matchResult.total_faltantes > 0 && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCopyMissingToClipboard}
                className="text-[10px] px-2 py-0.5 rounded bg-serato-dark hover:bg-slate-700 text-slate-300 border border-serato-cardBorder cursor-pointer"
              >
                Copiar Lista {matchResult?.tipo_origem === 'folder' ? 'Inéditas' : 'Faltantes'}
              </button>
              {matchResult?.tipo_origem !== 'folder' && (
                <button
                  type="button"
                  onClick={() => onAddLog(`📥 Baixar Faltantes: Você pode colar as ${matchResult.total_faltantes} faixas faltantes no utilitário de download integrado ou no spotdl / yt-dlp.`)}
                  className="text-[10px] px-2.5 py-0.5 rounded bg-serato-orange hover:bg-amber-400 text-black font-bold flex items-center gap-1 cursor-pointer"
                >
                  <Download className="w-3 h-3" />
                  <span>📥 Baixar Faixas Faltantes</span>
                </button>
              )}
            </div>
          )}
        </div>

        {/* Barra de Filtros e Busca */}
        {matchResult && (
          <div className="bg-serato-dark/60 p-2 border-b border-serato-cardBorder flex flex-wrap items-center justify-between gap-2 shrink-0">
            <div className="relative flex-1 min-w-[220px]">
              <Search className="w-3.5 h-3.5 text-serato-muted absolute left-2.5 top-2.5" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Filtrar faixas solicitadas ou arquivos locais no HD..."
                className="w-full pl-8 pr-3 py-1.5 text-xs bg-serato-dark border border-serato-cardBorder rounded-lg text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-cyan transition font-sans"
              />
            </div>

            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => setStatusFilter('all')}
                className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition cursor-pointer border ${
                  statusFilter === 'all'
                    ? 'bg-serato-card text-white border-serato-cyan/50 shadow-sm'
                    : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
                }`}
              >
                Todas ({(matchResult.encontradas?.length || 0) + (matchResult.faltantes?.length || 0)})
              </button>

              {matchResult?.total_upgrades > 0 && (
                <button
                  type="button"
                  onClick={() => setStatusFilter('upgrades')}
                  className={`text-[11px] px-2.5 py-1 rounded-lg font-bold transition cursor-pointer border ${
                    statusFilter === 'upgrades'
                      ? 'bg-amber-950/80 text-serato-gold border-serato-gold shadow-sm'
                      : 'bg-serato-dark text-serato-gold/70 border-serato-cardBorder hover:text-serato-gold'
                  }`}
                >
                  🚀 Upgrades ({matchResult.total_upgrades})
                </button>
              )}

              <button
                type="button"
                onClick={() => setStatusFilter('found')}
                className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition cursor-pointer border ${
                  statusFilter === 'found'
                    ? 'bg-emerald-950/60 text-emerald-300 border-emerald-600/60 shadow-sm'
                    : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
                }`}
              >
                Já no HD ({matchResult.encontradas?.length || 0})
              </button>

              <button
                type="button"
                onClick={() => setStatusFilter('missing')}
                className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition cursor-pointer border ${
                  statusFilter === 'missing'
                    ? 'bg-rose-950/60 text-rose-300 border-rose-600/60 shadow-sm'
                    : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
                }`}
              >
                {matchResult?.tipo_origem === 'folder' ? 'Inéditas' : 'Faltantes'} ({matchResult.faltantes?.length || 0})
              </button>
            </div>
          </div>
        )}

        <div className="overflow-y-auto flex-1 p-2 space-y-1.5 text-xs font-mono">
          {!matchResult ? (
            <div className="py-12 text-center text-slate-500 font-sans">
              <Music className="w-8 h-8 opacity-20 text-serato-cyan mx-auto mb-2" />
              <p>Selecione uma pasta com novos áudios ou cole uma playlist acima e clique em "Cruzar Playlist".</p>
              <p className="text-[11px] text-slate-600 mt-1">O sistema buscará as músicas instantaneamente no seu HD Master.</p>
            </div>
          ) : (
            <>
              {(statusFilter === 'all' || statusFilter === 'found' || statusFilter === 'upgrades') && filteredEncontradas.map((item: any, idx: number) => (
                <div 
                  key={`found-${idx}`} 
                  className={`border p-2 rounded flex items-center justify-between transition ${
                    item.upgrade_disponivel
                      ? 'bg-amber-950/20 border-serato-gold/60 hover:bg-amber-950/30'
                      : 'bg-serato-card border-emerald-900/40 hover:bg-emerald-950/20'
                  }`}
                >
                  <div className="flex items-center gap-2 truncate max-w-2xl">
                    {item.upgrade_disponivel ? (
                      <span className="text-[10px] bg-amber-950 text-serato-gold border border-serato-gold/40 px-1.5 py-0.5 rounded font-bold shrink-0 flex items-center gap-1">
                        <Zap className="w-2.5 h-2.5 text-serato-gold" />
                        UPGRADE
                      </span>
                    ) : (
                      <span className="text-[10px] bg-emerald-950 text-emerald-400 px-1.5 py-0.2 rounded font-bold shrink-0">
                        {item.score}% MATCH
                      </span>
                    )}

                    <span className="text-white font-sans font-medium truncate">{item.solicitado}</span>
                    <ArrowRight className="w-3 h-3 text-slate-600 shrink-0" />
                    <span className="text-slate-400 text-[10px] truncate" title={item.caminho_completo}>{item.arquivo_local}</span>

                    {item.novo_bitrate !== undefined && (
                      <span className="text-[10px] font-mono shrink-0 ml-1">
                        {item.upgrade_disponivel ? (
                          <span className="text-emerald-400 font-bold bg-emerald-950/60 px-1 py-0.5 rounded border border-emerald-700/40">
                            {item.novo_bitrate}k {item.novo_formato} ➔ {item.lib_bitrate || '?'}k
                          </span>
                        ) : (
                          <span className="text-slate-500">
                            ({item.lib_bitrate || '?'}k)
                          </span>
                        )}
                      </span>
                    )}
                  </div>

                  {onOpenFileInFinder && (
                    <button
                      type="button"
                      onClick={() => onOpenFileInFinder(item.caminho_completo)}
                      className="p-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-300 ml-2 shrink-0 cursor-pointer"
                      title="Revelar no Finder"
                    >
                      <ExternalLink className="w-3 h-3 text-serato-cyan" />
                    </button>
                  )}
                </div>
              ))}

              {(statusFilter === 'all' || statusFilter === 'missing') && filteredFaltantes.map((item: any, idx: number) => (
                <div key={`missing-${idx}`} className="bg-serato-card border border-rose-950/50 p-2 rounded flex items-center justify-between opacity-90">
                  <div className="flex items-center gap-2 truncate max-w-xl">
                    <span className="text-[10px] bg-rose-950 text-rose-300 border border-rose-800/40 px-1.5 py-0.2 rounded font-bold shrink-0">
                      {matchResult?.tipo_origem === 'folder' ? 'INÉDITA / NOVA' : 'FALTANDO'}
                    </span>
                    <span className="text-slate-200 font-sans truncate">{item.solicitado}</span>
                    {item.novo_bitrate ? (
                      <span className="text-[10px] text-slate-500 font-mono">
                        ({item.novo_bitrate}k {item.novo_formato})
                      </span>
                    ) : null}
                  </div>
                  <span className="text-[10px] text-serato-orange shrink-0">
                    {matchResult?.tipo_origem === 'folder' ? 'Não existe no HD Master' : 'Não encontrada no HD'}
                  </span>
                </div>
              ))}

              {filteredEncontradas.length === 0 && filteredFaltantes.length === 0 && (
                <div className="py-8 text-center text-slate-500 font-sans">
                  Nenhuma faixa corresponde ao filtro "{searchTerm}".
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
