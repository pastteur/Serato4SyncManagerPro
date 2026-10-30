import React, { useState } from 'react';
import { Music, Search, Sparkles, Download, CheckCircle2, AlertTriangle, ExternalLink, ArrowRight, FolderPlus, FileText, Globe } from 'lucide-react';

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
  const [inputType, setInputType] = useState<'spotify' | 'text' | 'file'>('text');
  const [inputData, setInputData] = useState<string>('');
  const [crateName, setCrateName] = useState<string>('Playlist Matcher');
  const [isMatching, setIsMatching] = useState<boolean>(false);
  const [matchResult, setMatchResult] = useState<any>(null);
  const [exportSuccessMsg, setExportSuccessMsg] = useState<string | null>(null);

  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);

  const handleRunMatch = async (exportCrateNow: boolean = false) => {
    if (!inputData.trim()) {
      onAddLog('⚠️ Informe o link do Spotify ou a lista de faixas para cruzar.');
      return;
    }
    if (!mp3Path) {
      onAddLog('⚠️ Selecione a pasta MP3 antes de realizar o cruzamento.');
      return;
    }

    setIsMatching(true);
    setExportSuccessMsg(null);
    onAddLog(`🎧 Track Matcher: Cruzando playlist contra suas 31.355 faixas do HD...`);

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
          onAddLog(`✅ Track Matcher: ${parsed.total_encontradas} faixas encontradas no HD (${parsed.total_faltantes} faltantes).`);
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
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-300 font-semibold">Origem da Playlist:</span>
            <button
              type="button"
              onClick={() => setInputType('text')}
              className={`px-2.5 py-1 text-xs rounded transition flex items-center gap-1 cursor-pointer ${
                inputType === 'text'
                  ? 'bg-serato-cyan text-black font-bold'
                  : 'bg-serato-dark text-slate-400 hover:text-white border border-serato-cardBorder'
              }`}
            >
              <FileText className="w-3 h-3" />
              <span>Texto / Linhas</span>
            </button>

            <button
              type="button"
              onClick={() => setInputType('spotify')}
              className={`px-2.5 py-1 text-xs rounded transition flex items-center gap-1 cursor-pointer ${
                inputType === 'spotify'
                  ? 'bg-[#1DB954] text-black font-bold'
                  : 'bg-serato-dark text-slate-400 hover:text-white border border-serato-cardBorder'
              }`}
            >
              <Globe className="w-3 h-3" />
              <span>Spotify URL</span>
            </button>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">Nome da Crate:</span>
            <input
              type="text"
              value={crateName}
              onChange={(e) => setCrateName(e.target.value)}
              className="bg-serato-dark border border-serato-cardBorder px-2.5 py-1 text-xs rounded text-white font-mono w-48 focus:outline-none focus:border-serato-cyan"
            />
          </div>
        </div>

        {inputType === 'spotify' ? (
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
          <div className="flex items-center gap-3">
            <span>Resultados: <b className="text-white">{matchResult?.total_solicitadas || 0}</b> solicitadas</span>
            <span className="text-emerald-400 font-bold">✅ {matchResult?.total_encontradas || 0} no HD</span>
            <span className="text-rose-400 font-bold">⚠️ {matchResult?.total_faltantes || 0} faltantes</span>
          </div>

          {matchResult && matchResult.total_faltantes > 0 && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCopyMissingToClipboard}
                className="text-[10px] px-2 py-0.5 rounded bg-serato-dark hover:bg-slate-700 text-slate-300 border border-serato-cardBorder cursor-pointer"
              >
                Copiar Lista Faltantes
              </button>
              <button
                type="button"
                onClick={() => onAddLog(`📥 Baixar Faltantes: Você pode colar as ${matchResult.total_faltantes} faixas faltantes no utilitário de download integrado ou no spotdl / yt-dlp.`)}
                className="text-[10px] px-2.5 py-0.5 rounded bg-serato-orange hover:bg-amber-400 text-black font-bold flex items-center gap-1 cursor-pointer"
              >
                <Download className="w-3 h-3" />
                <span>📥 Baixar Faixas Faltantes</span>
              </button>
            </div>
          )}
        </div>

        <div className="overflow-y-auto flex-1 p-2 space-y-1.5 text-xs font-mono">
          {!matchResult ? (
            <div className="py-12 text-center text-slate-500 font-sans">
              <Music className="w-8 h-8 opacity-20 text-serato-cyan mx-auto mb-2" />
              <p>Cole uma playlist acima e clique em "Cruzar Playlist".</p>
              <p className="text-[11px] text-slate-600 mt-1">O sistema buscará as músicas instantaneamente no seu HD.</p>
            </div>
          ) : (
            <>
              {matchResult.encontradas && matchResult.encontradas.map((item: any, idx: number) => (
                <div key={idx} className="bg-serato-card border border-emerald-900/40 p-2 rounded flex items-center justify-between hover:bg-emerald-950/20">
                  <div className="flex items-center gap-2 truncate max-w-xl">
                    <span className="text-[10px] bg-emerald-950 text-emerald-400 px-1.5 py-0.2 rounded font-bold">
                      {item.score}% MATCH
                    </span>
                    <span className="text-white font-sans font-medium">{item.solicitado}</span>
                    <ArrowRight className="w-3 h-3 text-slate-600" />
                    <span className="text-slate-400 text-[10px] truncate" title={item.caminho_completo}>{item.arquivo_local}</span>
                  </div>

                  {onOpenFileInFinder && (
                    <button
                      type="button"
                      onClick={() => onOpenFileInFinder(item.caminho_completo)}
                      className="p-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-300"
                      title="Revelar no Finder"
                    >
                      <ExternalLink className="w-3 h-3 text-serato-cyan" />
                    </button>
                  )}
                </div>
              ))}

              {matchResult.faltantes && matchResult.faltantes.map((item: any, idx: number) => (
                <div key={idx} className="bg-serato-card border border-rose-950/50 p-2 rounded flex items-center justify-between opacity-80">
                  <div className="flex items-center gap-2 truncate max-w-xl">
                    <span className="text-[10px] bg-rose-950 text-rose-400 px-1.5 py-0.2 rounded font-bold">
                      FALTANDO
                    </span>
                    <span className="text-slate-300 font-sans">{item.solicitado}</span>
                  </div>
                  <span className="text-[10px] text-serato-orange">Não encontrada no HD</span>
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
