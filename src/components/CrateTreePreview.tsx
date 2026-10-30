import React, { useState, useMemo } from 'react';
import { FolderTree, Music, Search, Disc, Folder, Eye, CheckCircle2, Sparkles } from 'lucide-react';
import { SyncSummary, CrateTreeItem } from '../types';

interface CrateTreePreviewProps {
  summary: SyncSummary | null;
  onOpenFileInFinder?: (filePath: string) => void;
}

export const CrateTreePreview: React.FC<CrateTreePreviewProps> = ({ summary, onOpenFileInFinder }) => {
  const [selectedCrateKey, setSelectedCrateKey] = useState<string>('');
  const [trackSearch, setTrackSearch] = useState<string>('');
  const [crateSearch, setCrateSearch] = useState<string>('');

  // Extract crates from summary or use sample demonstration data
  const cratesMap: Record<string, CrateTreeItem> = useMemo(() => {
    if (summary?.crates_arvore && Object.keys(summary.crates_arvore).length > 0) {
      return summary.crates_arvore;
    }

    // Interactive Demo Sample Data (reflecting Serato 4 style + descending subcrates)
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

  // Group crates by master style (with search filter)
  const groupedCrates = useMemo(() => {
    const groups: Record<string, CrateTreeItem[]> = {};
    const search = crateSearch.trim().toLowerCase();

    Object.values(cratesMap).forEach(item => {
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

    // Sort subcrates descending within each group
    Object.keys(groups).forEach(master => {
      groups[master].sort((a, b) => b.subcrate.localeCompare(a.subcrate, undefined, { numeric: true }));
    });

    return groups;
  }, [cratesMap, crateSearch]);

  // Automatically select the first crate if none is selected
  const activeCrateKey = useMemo(() => {
    if (selectedCrateKey && cratesMap[selectedCrateKey]) {
      return selectedCrateKey;
    }
    const keys = Object.keys(cratesMap);
    return keys.length > 0 ? keys[0] : '';
  }, [selectedCrateKey, cratesMap]);

  const activeCrate = activeCrateKey ? cratesMap[activeCrateKey] : null;

  // Filter tracks in active crate
  const filteredTracks = useMemo(() => {
    if (!activeCrate) return [];
    if (!trackSearch.trim()) return activeCrate.faixas;
    const term = trackSearch.toLowerCase();
    return activeCrate.faixas.filter(t => t.nome.toLowerCase().includes(term));
  }, [activeCrate, trackSearch]);

  const isDemo = !summary?.crates_arvore || Object.keys(summary.crates_arvore).length === 0;

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl p-4 shadow-2xl flex flex-col h-full flex-1 overflow-hidden min-h-0 space-y-3">
      {/* Top Bar with Description and Demo Badge */}
      <div className="flex items-center justify-between pb-2 border-b border-serato-cardBorder shrink-0">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <FolderTree className="w-4 h-4 text-serato-cyan" />
            <span>Navegador de Crates & Subcrates (Serato DJ Pro 4)</span>
            {isDemo && (
              <span className="text-[10px] bg-serato-gold/20 text-serato-gold px-2 py-0.5 rounded-full border border-serato-gold/30 font-mono flex items-center gap-1">
                <Sparkles className="w-3 h-3" />
                Demonstração Interativa (Execute uma sincronização para ver sua biblioteca real)
              </span>
            )}
          </h3>
          <p className="text-[11px] text-serato-muted">
            Navegue pelas pastas e subpastas como dentro do Serato DJ. Estilos ordenados de A-Z com subcrates numéricas decrescentes.
          </p>
        </div>

        <div className="flex items-center space-x-2 text-xs font-mono text-serato-gold">
          <span>{Object.keys(cratesMap).length} Crates Mapeadas</span>
        </div>
      </div>

      {/* Two-Column Serato Browser */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-3 flex-1 min-h-0 overflow-hidden">
        {/* Left Column: Crate Navigation Tree */}
        <div className="md:col-span-5 bg-serato-card border border-serato-cardBorder rounded-lg flex flex-col overflow-hidden min-h-0">
          <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder flex items-center justify-between shrink-0 gap-2">
            <span className="text-xs font-bold text-slate-200 flex items-center gap-1.5 uppercase tracking-wide shrink-0">
              <Folder className="w-3.5 h-3.5 text-serato-gold" />
              Playlists ({Object.keys(cratesMap).length})
            </span>
            <div className="relative flex-1 max-w-[160px]">
              <Search className="w-3 h-3 text-serato-muted absolute left-2 top-2" />
              <input
                type="text"
                value={crateSearch}
                onChange={(e) => setCrateSearch(e.target.value)}
                placeholder="Filtrar crates..."
                className="w-full pl-6 pr-2 py-1 text-[11px] bg-serato-dark border border-serato-cardBorder rounded text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-cyan"
              />
            </div>
          </div>

          <div className="overflow-y-auto flex-1 p-2 space-y-2.5">
            {Object.keys(groupedCrates).sort().map(master => {
              const subcrates = groupedCrates[master];
              return (
                <div key={master} className="space-y-1">
                  {/* Master Style Item */}
                  <div className="text-xs font-bold text-serato-gold flex items-center gap-1.5 px-2 py-1 bg-black/40 rounded border border-white/5">
                    <Disc className="w-3.5 h-3.5 text-serato-gold" />
                    <span>{master}</span>
                    <span className="text-[10px] text-slate-500 font-mono ml-auto">
                      {subcrates.length} lote(s)
                    </span>
                  </div>

                  {/* Subcrates in descending order */}
                  <div className="pl-3 space-y-1">
                    {subcrates.map(sub => {
                      const isSelected = activeCrateKey === sub.nome_crate;
                      return (
                        <button
                          key={sub.nome_crate}
                          type="button"
                          onClick={() => setSelectedCrateKey(sub.nome_crate)}
                          className={`w-full text-left px-2.5 py-1.5 rounded text-xs flex items-center justify-between transition cursor-pointer ${
                            isSelected
                              ? 'bg-serato-cyan/20 text-serato-cyan border border-serato-cyan/50 font-semibold shadow-sm'
                              : 'text-slate-300 hover:bg-white/[0.04] hover:text-white border border-transparent'
                          }`}
                        >
                          <div className="flex items-center gap-1.5 truncate">
                            <span className="text-slate-500 font-mono text-[11px]">└─</span>
                            <span className="truncate">{sub.subcrate || sub.master}</span>
                          </div>
                          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-black/50 text-slate-400 shrink-0 ml-1">
                            {sub.total_faixas} faixas
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Column: Tracks Browser of Selected Crate */}
        <div className="md:col-span-7 bg-serato-card border border-serato-cardBorder rounded-lg flex flex-col overflow-hidden min-h-0">
          <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder flex items-center justify-between shrink-0">
            <div className="flex items-center space-x-2">
              <Music className="w-3.5 h-3.5 text-serato-cyan" />
              <span className="text-xs font-bold text-white truncate max-w-[280px]">
                {activeCrate ? activeCrate.nome_exibicao : 'Selecione uma Crate'}
              </span>
              {activeCrate && (
                <span className="text-[10px] bg-serato-cyan/20 text-serato-cyan px-2 py-0.2 rounded-full border border-serato-cyan/30 font-mono">
                  {activeCrate.total_faixas} faixas
                </span>
              )}
            </div>

            <div className="relative w-44">
              <Search className="w-3 h-3 text-serato-muted absolute left-2 top-2" />
              <input
                type="text"
                value={trackSearch}
                onChange={(e) => setTrackSearch(e.target.value)}
                placeholder="Buscar faixa..."
                className="w-full pl-6 pr-2 py-1 text-[11px] bg-serato-dark border border-serato-cardBorder rounded text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-cyan"
              />
            </div>
          </div>

          <div className="overflow-y-auto flex-1 p-1 bg-[#06080d]">
            {filteredTracks.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-slate-600 text-xs py-10">
                <Music className="w-6 h-6 opacity-30 text-serato-cyan mb-1" />
                <p>Nenhuma faixa encontrada nesta crate.</p>
              </div>
            ) : (
              <table className="w-full text-left text-xs">
                <thead className="bg-serato-dark/90 text-serato-muted font-mono uppercase text-[10px] border-b border-serato-cardBorder sticky top-0">
                  <tr>
                    <th className="py-1.5 px-2 w-8 text-center">#</th>
                    <th className="py-1.5 px-2">Título da Faixa</th>
                    <th className="py-1.5 px-2 w-16 text-center">Formato</th>
                    <th className="py-1.5 px-2 w-10 text-center">Ação</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-serato-cardBorder/40 font-mono text-[11px]">
                  {filteredTracks.map((track, idx) => (
                    <tr key={idx} className="hover:bg-white/[0.03] transition">
                      <td className="py-1.5 px-2 text-center text-slate-500">{idx + 1}</td>
                      <td className="py-1.5 px-2 text-slate-200 font-sans font-medium truncate max-w-[280px]" title={track.nome}>
                        {track.nome}
                      </td>
                      <td className="py-1.5 px-2 text-center">
                        <span className={`text-[10px] px-1.5 py-0.2 rounded font-mono font-bold ${
                          track.formato === 'FLAC' || track.formato === 'WAV'
                            ? 'bg-purple-950/70 text-purple-300 border border-purple-800/40'
                            : 'bg-cyan-950/70 text-cyan-300 border border-cyan-800/40'
                        }`}>
                          {track.formato}
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
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="bg-serato-header px-3 py-1.5 border-t border-serato-cardBorder text-[10px] text-serato-muted flex items-center justify-between shrink-0">
            <span>Caminho no Serato: <code className="text-slate-300">{activeCrate?.nome_crate}.crate</code></span>
            <span className="flex items-center gap-1 text-serato-neonGreen">
              <CheckCircle2 className="w-3 h-3" />
              Tags ptrk relativas
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
