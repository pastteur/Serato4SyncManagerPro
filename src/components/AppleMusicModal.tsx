import React, { useState, useEffect } from 'react';
import { X, Music2, CheckCircle2, Loader2, ArrowRight, Library, ListMusic } from 'lucide-react';

interface ApplePlaylist {
  id: string;
  name: string;
  count: number;
  track_ids: string[];
}

interface AppleMusicModalProps {
  isOpen: boolean;
  onClose: () => void;
  onImportTracks: (tracks: any[], playlistName: string) => void;
  onAddLog?: (msg: string) => void;
}

export const AppleMusicModal: React.FC<AppleMusicModalProps> = ({
  isOpen,
  onClose,
  onImportTracks,
  onAddLog
}) => {
  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
  
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [playlists, setPlaylists] = useState<ApplePlaylist[]>([]);
  const [selectedPlaylistId, setSelectedPlaylistId] = useState<string>('');
  const [libraryData, setLibraryData] = useState<any | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      loadAppleMusic();
    }
  }, [isOpen]);

  const loadAppleMusic = async () => {
    if (!isTauri) return;
    setIsLoading(true);
    setErrorMsg(null);

    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('extract_apple_music_library');
      const data = JSON.parse(resJson);

      if (data.sucesso) {
        setLibraryData(data);
        const pls = data.playlists || [];
        setPlaylists(pls);
        if (pls.length > 0) {
          setSelectedPlaylistId(pls[0].id);
        }
      } else {
        setErrorMsg(data.erro || 'Falha ao conectar à biblioteca Apple Music.');
      }
    } catch (err: any) {
      setErrorMsg(`Erro: ${err.message || err}`);
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  const handleConfirmImport = () => {
    if (!libraryData || !selectedPlaylistId) return;

    const targetPl = playlists.find(p => p.id === selectedPlaylistId);
    if (!targetPl) return;

    const tracksById: Record<string, any> = {};
    for (const t of libraryData.tracks || []) {
      tracksById[t.id] = t;
    }

    const playlistTracks: any[] = [];
    for (const tid of targetPl.track_ids) {
      if (tracksById[tid]) {
        const item = tracksById[tid];
        playlistTracks.push({
          artist: item.artist || '',
          title: item.title || '',
          clean_artist: item.artist || '',
          clean_title: item.title || '',
          raw: `${item.artist} - ${item.title}`,
          filepath: item.filepath,
          bpm: item.bpm,
          duration_ms: item.duration_ms
        });
      }
    }

    onImportTracks(playlistTracks, targetPl.name);
    if (onAddLog) {
      onAddLog(`🍎 Importadas ${playlistTracks.length} faixas da playlist '${targetPl.name}' do Apple Music.`);
    }
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="bg-serato-card border border-serato-cardBorder rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden flex flex-col">
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-serato-cardBorder bg-slate-900/50">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-gradient-to-br from-rose-500/20 to-pink-500/20 text-rose-400 border border-rose-500/30">
              <Music2 className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                Importar Playlists do Apple Music
                <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/30">
                  macOS Nativo
                </span>
              </h3>
              <p className="text-xs text-slate-400">
                Lê diretamente via iTunesLibrary.framework sem abrir o aplicativo.
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-white/5 transition">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Conteúdo */}
        <div className="p-6">
          {isLoading ? (
            <div className="py-12 flex flex-col items-center justify-center gap-3 text-slate-400">
              <Loader2 className="w-8 h-8 animate-spin text-rose-400" />
              <span className="text-xs font-mono">Conectando à biblioteca local do Apple Music...</span>
            </div>
          ) : errorMsg ? (
            <div className="p-4 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300">
              <div className="font-bold mb-1">Aviso de Acesso:</div>
              {errorMsg}
            </div>
          ) : playlists.length === 0 ? (
            <div className="py-8 text-center text-xs text-slate-400">
              Nenhuma playlist personalizada encontrada no Apple Music.
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center justify-between text-xs text-slate-400">
                <span className="font-mono uppercase font-bold text-slate-300">Selecione a Playlist:</span>
                <span className="font-mono">{playlists.length} playlists detectadas</span>
              </div>

              <div className="max-h-64 overflow-y-auto space-y-1.5 pr-1">
                {playlists.map(pl => (
                  <button
                    key={pl.id}
                    onClick={() => setSelectedPlaylistId(pl.id)}
                    className={`w-full flex items-center justify-between p-3 rounded-xl border text-left transition ${
                      selectedPlaylistId === pl.id
                        ? 'bg-rose-500/15 border-rose-400 text-white'
                        : 'bg-slate-900/50 border-slate-800 text-slate-300 hover:border-slate-700'
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <ListMusic className={`w-4 h-4 ${selectedPlaylistId === pl.id ? 'text-rose-400' : 'text-slate-500'}`} />
                      <span className="text-xs font-bold">{pl.name}</span>
                    </div>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-black/40 text-slate-400">
                      {pl.count} faixas
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-serato-cardBorder bg-slate-900/40 flex items-center justify-between">
          <div className="text-[11px] text-slate-400 font-mono">
            {libraryData ? `Total no Mac: ${libraryData.total_tracks || 0} faixas` : ''}
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-bold text-slate-400 hover:text-white hover:bg-white/5 transition"
            >
              Cancelar
            </button>
            <button
              onClick={handleConfirmImport}
              disabled={isLoading || !selectedPlaylistId}
              className="px-5 py-2 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-rose-500 to-pink-500 hover:opacity-90 transition disabled:opacity-50 flex items-center gap-1.5 shadow-md cursor-pointer"
            >
              <span>Importar no TrackMatcher</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>

      </div>
    </div>
  );
};
