import React, { useState, useEffect, useRef } from 'react';
import { Play, Pause, Volume2, VolumeX, X, Disc, FastForward, Rewind } from 'lucide-react';

export interface PlayingTrackInfo {
  caminho: string;
  nome: string;
  artista?: string;
  titulo?: string;
  cues?: Array<{ id: number; nome: string; pos_ms: number; cor?: string }>;
  bpm?: number;
}

interface AudioPlayerBarProps {
  track: PlayingTrackInfo | null;
  onClose: () => void;
  onAddLog?: (msg: string) => void;
}

export const AudioPlayerBar: React.FC<AudioPlayerBarProps> = ({ track, onClose, onAddLog }) => {
  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [duration, setDuration] = useState<number>(0);
  const [volume, setVolume] = useState<number>(0.8);
  const [isMuted, setIsMuted] = useState<boolean>(false);

  // Inicializa ou troca de música
  useEffect(() => {
    if (!track) {
      if (audioRef.current) {
        audioRef.current.pause();
      }
      setIsPlaying(false);
      return;
    }

    const loadAudio = async () => {
      let src = track.caminho;
      if (isTauri) {
        try {
          const { convertFileSrc } = await import('@tauri-apps/api/core');
          src = convertFileSrc(track.caminho);
        } catch (e) {
          // fallback src
        }
      }

      if (!audioRef.current) {
        audioRef.current = new Audio(src);
      } else {
        audioRef.current.pause();
        audioRef.current.src = src;
      }

      audioRef.current.volume = isMuted ? 0 : volume;
      audioRef.current.currentTime = 0;

      audioRef.current.onloadedmetadata = () => {
        if (audioRef.current) {
          setDuration(audioRef.current.duration || 0);
        }
      };

      audioRef.current.ontimeupdate = () => {
        if (audioRef.current) {
          setCurrentTime(audioRef.current.currentTime);
        }
      };

      audioRef.current.onended = () => {
        setIsPlaying(false);
      };

      audioRef.current.play().then(() => {
        setIsPlaying(true);
      }).catch(err => {
        if (onAddLog) onAddLog(`⚠️ Não foi possível iniciar reprodução de áudio: ${err}`);
        setIsPlaying(false);
      });
    };

    loadAudio();

    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
      }
    };
  }, [track, isTauri]);

  // Controle de Play/Pause
  const togglePlay = () => {
    if (!audioRef.current || !track) return;
    if (isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
    } else {
      audioRef.current.play().then(() => {
        setIsPlaying(true);
      }).catch(e => {
        if (onAddLog) onAddLog(`⚠️ Erro ao reproduzir: ${e}`);
      });
    }
  };

  // Salto para Cue Point específico (1..5)
  const jumpToTime = (seconds: number) => {
    if (!audioRef.current) return;
    audioRef.current.currentTime = Math.max(0, Math.min(seconds, duration));
    if (!isPlaying) {
      audioRef.current.play().then(() => setIsPlaying(true)).catch(() => {});
    }
  };

  // Controle de Volume
  const handleVolumeChange = (newVol: number) => {
    setVolume(newVol);
    setIsMuted(newVol === 0);
    if (audioRef.current) {
      audioRef.current.volume = newVol;
    }
  };

  const toggleMute = () => {
    if (!audioRef.current) return;
    if (isMuted) {
      audioRef.current.volume = volume || 0.8;
      setIsMuted(false);
    } else {
      audioRef.current.volume = 0;
      setIsMuted(true);
    }
  };

  // Formatação de Tempo (mm:ss)
  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  // Atalhos de teclado quando a barra estiver visível (Espaço para Play/Pause, 1..5 para Cues)
  useEffect(() => {
    if (!track) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignora se estiver digitando em input/textarea ou elemento editável
      const target = e.target as HTMLElement;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
        return;
      }

      if (e.code === 'Space') {
        e.preventDefault();
        togglePlay();
        return;
      }

      // Atalhos de busca rápida (Setas Esquerda/Direita)
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        const step = e.shiftKey ? 15 : 5;
        jumpToTime((audioRef.current?.currentTime || currentTime) - step);
        return;
      }

      if (e.key === 'ArrowRight') {
        e.preventDefault();
        const step = e.shiftKey ? 15 : 5;
        jumpToTime((audioRef.current?.currentTime || currentTime) + step);
        return;
      }

      // Atalhos numéricos 1 a 5 para Hot Cues se existirem
      if (['1', '2', '3', '4', '5'].includes(e.key) && track.cues && track.cues.length > 0) {
        const cueIndex = parseInt(e.key, 10) - 1;
        if (track.cues[cueIndex]) {
          e.preventDefault();
          const cueMs = track.cues[cueIndex].pos_ms;
          jumpToTime(cueMs / 1000);
        }
        return;
      }

      // Atalho de mudo (M)
      if (e.key === 'm' || e.key === 'M') {
        e.preventDefault();
        toggleMute();
        return;
      }

      // Atalhos de volume (Setas Cima/Baixo)
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        handleVolumeChange(Math.min(1, Number((volume + 0.05).toFixed(2))));
        return;
      }

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        handleVolumeChange(Math.max(0, Number((volume - 0.05).toFixed(2))));
        return;
      }

      // Fechar player com Escape
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        return;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [track, isPlaying, duration, volume, isMuted, onClose]);

  if (!track) return null;

  const CUE_COLORS: Record<number, string> = {
    0: 'bg-rose-500 text-white',      // Cue 1: Intro / Kick (Vermelho)
    1: 'bg-blue-500 text-white',      // Cue 2: Drop 1 (Azul)
    2: 'bg-amber-400 text-black',     // Cue 3: Breakdown (Amarelo)
    3: 'bg-emerald-500 text-white',   // Cue 4: Drop 2 (Verde)
    4: 'bg-orange-500 text-white',    // Cue 5: Outro (Laranja)
  };

  return (
    <aside 
      aria-label="Player de áudio e pré-escuta de Hot Cues"
      className="shrink-0 bg-serato-header/95 border-t border-serato-cardBorder px-4 py-2 flex items-center justify-between gap-4 backdrop-blur shadow-2xl z-20 select-none animate-in slide-in-from-bottom-2 duration-150"
    >
      {/* Informações da Faixa */}
      <div className="flex items-center gap-3 min-w-0 max-w-xs md:max-w-sm">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-serato-cyan/20 to-serato-gold/20 border border-serato-cardBorder flex items-center justify-center shrink-0">
          <Disc className={`w-4 h-4 text-serato-cyan ${isPlaying ? 'animate-spin' : ''}`} />
        </div>
        <div className="truncate leading-tight">
          <div className="text-xs font-bold text-white truncate" title={track.titulo || track.nome}>
            {track.artista ? `${track.artista} - ` : ''}{track.titulo || track.nome}
          </div>
          <div className="text-[10px] text-serato-muted truncate font-mono">
            {track.bpm ? `${Math.round(track.bpm)} BPM • ` : ''}{track.caminho.split('/').pop()}
          </div>
        </div>
      </div>

      {/* Controles de Transporte & Barra de Progresso */}
      <div className="flex-1 max-w-xl flex flex-col items-center gap-1">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => jumpToTime(currentTime - 5)}
            className="text-slate-400 hover:text-white transition p-1 cursor-pointer"
            title="Voltar 5s"
          >
            <Rewind className="w-3.5 h-3.5" />
          </button>

          <button
            type="button"
            onClick={togglePlay}
            className="w-7 h-7 rounded-full bg-serato-cyan text-black flex items-center justify-center hover:bg-cyan-300 transition shadow-md cursor-pointer"
            title={isPlaying ? "Pausar (Espaço)" : "Reproduzir (Espaço)"}
          >
            {isPlaying ? <Pause className="w-3.5 h-3.5 fill-current" /> : <Play className="w-3.5 h-3.5 fill-current ml-0.5" />}
          </button>

          <button
            type="button"
            onClick={() => jumpToTime(currentTime + 5)}
            className="text-slate-400 hover:text-white transition p-1 cursor-pointer"
            title="Avançar 5s"
          >
            <FastForward className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Linha de Tempo com Marcadores de Hot Cues */}
        <div className="w-full flex items-center gap-2 text-[10px] font-mono text-slate-400">
          <span>{formatTime(currentTime)}</span>
          <div className="flex-1 relative flex items-center">
            <input
              type="range"
              min={0}
              max={duration || 100}
              step={0.1}
              value={currentTime}
              onChange={(e) => jumpToTime(parseFloat(e.target.value))}
              className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-serato-cyan"
            />

            {/* Marcadores de Hot Cues sobrepostos na barra */}
            {duration > 0 && track.cues && track.cues.map((cue, idx) => {
              const cueSec = cue.pos_ms / 1000;
              const posPercent = Math.min(100, Math.max(0, (cueSec / duration) * 100));
              return (
                <button
                  key={cue.id || idx}
                  type="button"
                  onClick={() => jumpToTime(cueSec)}
                  style={{ left: `${posPercent}%` }}
                  className={`absolute -top-1 w-2.5 h-3.5 rounded-sm transform -translate-x-1/2 hover:scale-125 transition-transform shadow cursor-pointer z-10 ${CUE_COLORS[idx] || 'bg-serato-gold text-black'}`}
                  title={`${cue.nome || `Cue ${idx + 1}`} (${formatTime(cueSec)}) - Tecla [${idx + 1}]`}
                />
              );
            })}
          </div>
          <span>{formatTime(duration)}</span>
        </div>
      </div>

      {/* Hot Cue Pads Rápidos de DJ (Pads 1 a 5) & Volume */}
      <div className="flex items-center gap-3 shrink-0">
        {track.cues && track.cues.length > 0 && (
          <div className="flex items-center gap-1 bg-black/40 border border-white/5 p-1 rounded-lg">
            {track.cues.slice(0, 5).map((cue, idx) => (
              <button
                key={cue.id || idx}
                type="button"
                onClick={() => jumpToTime(cue.pos_ms / 1000)}
                className={`w-5 h-5 rounded text-[10px] font-bold flex items-center justify-center transition hover:opacity-90 shadow-sm cursor-pointer ${CUE_COLORS[idx] || 'bg-slate-700 text-white'}`}
                title={`Saltar para ${cue.nome || `Cue ${idx + 1}`} (Atalho: tecla ${idx + 1})`}
              >
                {idx + 1}
              </button>
            ))}
          </div>
        )}

        {/* Volume */}
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={toggleMute}
            className="text-slate-400 hover:text-white transition cursor-pointer"
            title={isMuted ? "Desmutar" : "Mutar"}
          >
            {isMuted || volume === 0 ? <VolumeX className="w-3.5 h-3.5 text-rose-400" /> : <Volume2 className="w-3.5 h-3.5 text-slate-300" />}
          </button>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={isMuted ? 0 : volume}
            onChange={(e) => handleVolumeChange(parseFloat(e.target.value))}
            className="w-16 h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-serato-gold"
            title={`Volume: ${Math.round((isMuted ? 0 : volume) * 100)}%`}
          />
        </div>

        {/* Fechar Player */}
        <button
          type="button"
          onClick={onClose}
          className="text-slate-500 hover:text-white p-1 rounded transition cursor-pointer"
          title="Fechar player"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </aside>
  );
};
// git-hash-salt: 1
