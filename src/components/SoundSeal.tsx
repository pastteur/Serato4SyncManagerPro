import React, { useState, useEffect } from 'react';
import { Shield, Sparkles, RefreshCw, AlertCircle, CheckCircle2, Search, ArrowRight, Music, Disc3, Folder, Trash2, Eye } from 'lucide-react';

interface SoundSealProps {
  mp3Path: string;
  seratoPath: string;
  onAddLog: (message: string) => void;
  onOpenFileInFinder?: (filePath: string) => void;
}

export const SoundSeal: React.FC<SoundSealProps> = ({
  mp3Path,
  seratoPath,
  onAddLog,
  onOpenFileInFinder
}) => {
  const [activeSubTab, setActiveSubTab] = useState<'seal' | 'relocate'>('seal');
  const [status, setStatus] = useState<any>(null);
  const [isScanning, setIsScanning] = useState<boolean>(false);
  const [duplicatesBySound, setDuplicatesBySound] = useState<any[]>([]);
  const [relocateResults, setRelocateResults] = useState<any[]>([]);
  const [isScanningRelocate, setIsScanningRelocate] = useState<boolean>(false);

  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);

  // Carrega status ao iniciar
  const loadStatus = async () => {
    if (!isTauri) return;
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const res = await invoke<string>('get_sound_seal_status');
      const parsed = JSON.parse(res);
      setStatus(parsed);
    } catch (e) {
      console.error(e);
    }
  };

  const loadDuplicatesBySound = async () => {
    if (!isTauri) return;
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const res = await invoke<string>('get_sound_seal_duplicates');
      const parsed = JSON.parse(res);
      if (parsed.sucesso) {
        setDuplicatesBySound(parsed.duplicados_som || []);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    loadStatus();
    loadDuplicatesBySound();
  }, []);

  // Iniciar varredura do Sound Seal
  const handleStartSealScan = async () => {
    if (!mp3Path) {
      alert('Selecione a pasta MP3 antes de iniciar.');
      return;
    }
    setIsScanning(true);
    onAddLog(`🧬 Sound Seal: Extraindo assinaturas acústicas SHA-256 em ${mp3Path}...`);

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const res = await invoke<string>('scan_sound_seals', {
          mp3Path,
          batch: 500
        });
        const parsed = JSON.parse(res);
        setStatus(parsed);
        loadDuplicatesBySound();
        onAddLog(`✅ Sound Seal: Varredura concluída. ${parsed.total_selados} faixas seladas com sucesso.`);
      }
    } catch (e) {
      onAddLog(`❌ Erro no Sound Seal: ${e}`);
    } finally {
      setIsScanning(false);
    }
  };

  // Scanner de Relocate de Músicas Perdidas
  const handleScanRelocate = async () => {
    if (!seratoPath || !mp3Path) {
      alert('Selecione as pastas MP3 e Serato antes de iniciar o Relocate.');
      return;
    }
    setIsScanningRelocate(true);
    onAddLog(`🔍 Relocate: Rastreador de faixas perdidas ativado...`);

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const res = await invoke<string>('scan_missing_relocate', {
          mp3Path,
          seratoPath
        });
        const parsed = JSON.parse(res);
        if (parsed.sucesso) {
          setRelocateResults(parsed.analisadas || []);
          onAddLog(`✅ Relocate: Análise concluída. ${parsed.total_perdidas} faixas ausentes verificadas.`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Erro no Relocate: ${e}`);
    } finally {
      setIsScanningRelocate(false);
    }
  };

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl p-4 shadow-2xl flex flex-col h-full flex-1 overflow-hidden min-h-0 space-y-3">
      {/* Sub-Tabs Switcher */}
      <div className="flex items-center justify-between pb-2 border-b border-serato-cardBorder shrink-0">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setActiveSubTab('seal')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition flex items-center gap-1.5 cursor-pointer ${
              activeSubTab === 'seal'
                ? 'bg-serato-cyan/20 text-serato-cyan border border-serato-cyan/40'
                : 'text-serato-muted hover:text-white'
            }`}
          >
            <Shield className="w-3.5 h-3.5" />
            <span>Sound Seal (Selo Sonoro SHA-256)</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveSubTab('relocate')}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition flex items-center gap-1.5 cursor-pointer ${
              activeSubTab === 'relocate'
                ? 'bg-serato-orange/20 text-serato-orange border border-serato-orange/40'
                : 'text-serato-muted hover:text-white'
            }`}
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Relocate de Músicas Perdidas</span>
          </button>
        </div>

        {activeSubTab === 'seal' ? (
          <button
            type="button"
            onClick={handleStartSealScan}
            disabled={isScanning}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-serato-cyan hover:bg-cyan-300 text-black shadow-lg shadow-serato-cyan/20 transition disabled:opacity-40 cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isScanning ? 'animate-spin' : ''}`} />
            <span>{isScanning ? 'Ouvindo faixas...' : '🧬 Iniciar Sound Seal'}</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={handleScanRelocate}
            disabled={isScanningRelocate}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-serato-orange hover:bg-amber-400 text-black shadow-lg shadow-serato-orange/20 transition disabled:opacity-40 cursor-pointer"
          >
            <Search className="w-3.5 h-3.5" />
            <span>{isScanningRelocate ? 'Procurando...' : '🔍 Rastrear Músicas Perdidas'}</span>
          </button>
        )}
      </div>

      {/* Conteúdo da Sub-Aba Sound Seal */}
      {activeSubTab === 'seal' && (
        <div className="flex-1 flex flex-col min-h-0 space-y-3">
          {/* Card explicativo idêntico ao Music Library Doctor */}
          <div className="bg-gradient-to-r from-cyan-950/40 to-slate-900 border border-cyan-800/30 rounded-xl p-3.5 flex flex-col md:flex-row items-center justify-between gap-4 shrink-0">
            <div className="space-y-1">
              <h4 className="text-xs font-bold text-white flex items-center gap-1.5">
                <Sparkles className="w-4 h-4 text-serato-cyan" />
                <span>O Selo do Som: SHA-256 Criptográfico</span>
              </h4>
              <p className="text-[11px] text-slate-300 max-w-2xl leading-relaxed">
                Extrai a assinatura acústica pura do arquivo. Nome, tags e pasta podem mudar à vontade: <b>o selo do som nunca muda</b>. Permite achar músicas renomeadas, pegar cópias com tags diferentes e salvar relocações sem errar.
              </p>
            </div>

            <div className="flex items-center gap-4 text-xs font-mono shrink-0">
              <div className="bg-black/40 px-3 py-2 rounded-lg border border-white/5 text-center">
                <div className="text-[10px] text-serato-muted uppercase">Seladas</div>
                <div className="text-base font-bold text-serato-cyan">{status?.total_selados?.toLocaleString() || 0}</div>
              </div>
              <div className="bg-black/40 px-3 py-2 rounded-lg border border-white/5 text-center">
                <div className="text-[10px] text-serato-muted uppercase">Cópias por Som</div>
                <div className="text-base font-bold text-serato-gold">{status?.total_faixas_com_copia_som?.toLocaleString() || 0}</div>
              </div>
            </div>
          </div>

          {/* Tabela de Cópias Reconhecidas Pelo Som */}
          <div className="flex-1 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20">
            <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder text-xs font-semibold text-slate-200 flex items-center justify-between">
              <span>Cópias Reconhecidas por Assinatura Sonora ({duplicatesBySound.length} grupos identificados)</span>
              <span className="text-[10px] text-serato-muted font-mono">Mesmo som, nomes ou tags divergentes</span>
            </div>

            <div className="overflow-y-auto flex-1 p-2 space-y-2">
              {duplicatesBySound.length === 0 ? (
                <div className="py-12 text-center text-slate-500 text-xs">
                  <Music className="w-8 h-8 opacity-20 text-serato-cyan mx-auto mb-2" />
                  <p>Nenhuma cópia redundante de som identificada ainda.</p>
                  <p className="text-[11px] text-slate-600 mt-1">Clique em "Iniciar Sound Seal" para rodar a indexação acústica contínua.</p>
                </div>
              ) : (
                duplicatesBySound.map((group, idx) => (
                  <div key={idx} className="bg-serato-card border border-serato-cardBorder rounded-lg p-2.5 space-y-1.5 text-xs">
                    <div className="flex items-center justify-between font-mono text-[10px] text-serato-muted border-b border-white/5 pb-1">
                      <span className="text-serato-cyan">SELO SHA-256: {group.seal.substring(0, 16)}...</span>
                      <span className="text-serato-gold font-bold">{group.total_copias} arquivos com o mesmo áudio</span>
                    </div>

                    <div className="space-y-1 pt-1">
                      {group.faixas.map((f: any, fIdx: number) => (
                        <div key={fIdx} className="flex items-center justify-between hover:bg-white/[0.02] p-1 rounded">
                          <div className="flex items-center gap-2 truncate max-w-xl">
                            <span className={`text-[10px] px-1.5 py-0.2 rounded font-mono ${fIdx === 0 ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/40' : 'bg-amber-950/60 text-amber-300 border border-amber-800/40'}`}>
                              {fIdx === 0 ? 'Referência' : 'Cópia'}
                            </span>
                            <span className="text-slate-200 truncate" title={f.caminho}>{f.nome}</span>
                            <span className="text-[10px] text-slate-500 truncate">({f.crate})</span>
                          </div>

                          <div className="flex items-center gap-2 shrink-0">
                            {f.bpm && <span className="text-[10px] font-mono text-slate-400">{Math.round(parseFloat(f.bpm))} BPM</span>}
                            {f.key && <span className="text-[10px] font-mono text-serato-cyan">{f.key}</span>}
                            {onOpenFileInFinder && (
                              <button
                                type="button"
                                onClick={() => onOpenFileInFinder(f.caminho)}
                                className="p-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-300"
                                title="Revelar no Finder"
                              >
                                <Eye className="w-3 h-3 text-serato-cyan" />
                              </button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* Conteúdo da Sub-Aba Relocate */}
      {activeSubTab === 'relocate' && (
        <div className="flex-1 flex flex-col min-h-0 space-y-3">
          <div className="bg-serato-card border border-serato-cardBorder p-3 rounded-lg flex items-center justify-between text-xs text-slate-300 shrink-0">
            <div>
              <h4 className="font-bold text-white flex items-center gap-2">
                <span>Relocate Inteligente de Músicas Ausentes</span>
                <span className="text-[10px] bg-serato-orange/20 text-serato-orange px-2 py-0.5 rounded-full border border-serato-orange/30">
                  Sem download · Preserva Hot Cues
                </span>
              </h4>
              <p className="text-[11px] text-serato-muted mt-0.5">
                Rastreia faixas que foram movidas ou renomeadas, incluindo arquivos que foram parar na Lixeira (.Trashes).
              </p>
            </div>
          </div>

          <div className="flex-1 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20">
            <div className="overflow-y-auto flex-1 p-2 space-y-2">
              {relocateResults.length === 0 ? (
                <div className="py-12 text-center text-slate-500 text-xs">
                  <CheckCircle2 className="w-8 h-8 opacity-20 text-emerald-400 mx-auto mb-2" />
                  <p className="font-semibold text-slate-300">Nenhuma faixa perdida reportada no momento.</p>
                  <p className="text-slate-600 mt-1">Todas as faixas das suas crates foram encontradas no disco.</p>
                </div>
              ) : (
                relocateResults.map((item, idx) => (
                  <div key={idx} className="bg-serato-card border border-serato-cardBorder rounded-lg p-3 space-y-2 text-xs">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] bg-rose-950/60 text-rose-400 px-2 py-0.5 rounded border border-rose-800/40 font-bold uppercase">
                          Perdida no Serato
                        </span>
                        <span className="font-semibold text-white">{item.nome}</span>
                        <span className="text-[10px] text-slate-500">Crate: {item.crate}</span>
                      </div>

                      {item.in_trash && (
                        <span className="text-[10px] bg-amber-950/60 text-amber-300 px-2 py-0.5 rounded border border-amber-800/40 font-bold">
                          ⚠️ ENCONTRADO NA LIXEIRA (.Trashes)
                        </span>
                      )}
                    </div>

                    {/* Candidatos sugeridos */}
                    <div className="space-y-1 bg-black/30 p-2 rounded border border-white/5">
                      <div className="text-[10px] text-serato-muted uppercase font-mono">Correspondências encontradas:</div>
                      {item.candidatos && item.candidatos.length > 0 ? (
                        item.candidatos.map((cand: any, cIdx: number) => (
                          <div key={cIdx} className="flex items-center justify-between p-1 hover:bg-white/[0.02] rounded">
                            <div className="flex items-center gap-2 truncate max-w-lg">
                              <span className={`text-[10px] px-1.5 py-0.2 rounded font-bold font-mono ${cand.score === 100 ? 'bg-emerald-950/60 text-emerald-400' : 'bg-cyan-950/60 text-cyan-300'}`}>
                                {cand.score}% CONF
                              </span>
                              <span className="text-slate-200 truncate">{cand.nome}</span>
                            </div>

                            <div className="flex items-center gap-2">
                              {cand.bpm && <span className="text-[10px] font-mono text-slate-400">{Math.round(parseFloat(cand.bpm))} BPM</span>}
                              {cand.key && <span className="text-[10px] font-mono text-serato-cyan">{cand.key}</span>}
                              <button
                                type="button"
                                onClick={() => alert(`Religar faixa ao Serato: ${cand.caminho}`)}
                                className="px-2 py-0.5 rounded bg-serato-cyan hover:bg-cyan-300 text-black font-bold text-[10px] cursor-pointer"
                              >
                                Religar →
                              </button>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="text-[11px] text-slate-500 italic">Nenhum arquivo correspondente localizado no HD.</div>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
