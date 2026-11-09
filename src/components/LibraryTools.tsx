import React, { useState, useEffect, useCallback } from 'react';
import { Library, Gauge, FileDown, FileUp, Undo2, Radar, Layers, Sparkles, RefreshCw, Trash2, Play, Eye } from 'lucide-react';
import { ConfirmModal } from './ConfirmModal';
import { PlayingTrackInfo } from './AudioPlayerBar';

interface LibraryToolsProps {
  onAddLog: (message: string) => void;
  mp3Path: string;
  seratoPath: string;
  onPlayTrack?: (track: PlayingTrackInfo) => void;
}

const isTauriEnv = () => typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);

async function call<T = any>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core');
  const raw = await invoke<string>(cmd, args);
  return JSON.parse(raw) as T;
}

const Card: React.FC<{ title: string; icon: React.ReactNode; children: React.ReactNode; hint?: string }> = ({ title, icon, children, hint }) => (
  <section className="bg-serato-card border border-serato-cardBorder rounded-xl p-4 space-y-3">
    <header className="flex items-center justify-between gap-2">
      <h4 className="flex items-center gap-2 text-[13px] font-semibold text-white">
        {icon}
        <span>{title}</span>
      </h4>
      {hint && <span className="text-[11px] text-serato-muted">{hint}</span>}
    </header>
    {children}
  </section>
);

const Btn: React.FC<{ onClick: () => void; disabled?: boolean; tone?: 'primary' | 'neutral' | 'danger'; children: React.ReactNode }> = ({ onClick, disabled, tone = 'neutral', children }) => {
  const tones = {
    primary: 'bg-serato-cyan text-black hover:bg-cyan-300',
    neutral: 'bg-serato-dark text-slate-200 border border-serato-cardBorder hover:bg-serato-hover',
    danger: 'bg-serato-dark text-rose-300 border border-serato-cardBorder hover:bg-rose-950/40',
  } as const;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${tones[tone]}`}
    >
      {children}
    </button>
  );
};

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <label className="flex flex-col gap-1 text-[11px] text-serato-muted">
    <span>{label}</span>
    {children}
  </label>
);

const inputCls = 'bg-serato-dark border border-serato-cardBorder rounded-lg px-2 py-1.5 text-xs text-slate-100 focus:outline-none focus:border-serato-cyan';

const EmptyState: React.FC<{ text: string }> = ({ text }) => (
  <div className="py-4 text-center text-[11px] text-serato-muted border border-dashed border-serato-cardBorder rounded-lg">{text}</div>
);

export const LibraryTools: React.FC<LibraryToolsProps> = ({ onAddLog, mp3Path, seratoPath, onPlayTrack }) => {
  const isTauri = isTauriEnv();
  const ready = Boolean(mp3Path && seratoPath);

  // Saúde
  const [health, setHealth] = useState<any>(null);
  const [busyHealth, setBusyHealth] = useState(false);

  // BPM / tom
  const [analysisWrite, setAnalysisWrite] = useState<boolean>(false);
  const [analysisIncludeFilled, setAnalysisIncludeFilled] = useState<boolean>(false);
  const [analysisRows, setAnalysisRows] = useState<any[]>([]);
  const [analysisProgress, setAnalysisProgress] = useState<{ processados: number; total: number } | null>(null);
  const [busyAnalysis, setBusyAnalysis] = useState(false);

  // Crates
  const [refs, setRefs] = useState<any>(null);
  const [m3uPath, setM3uPath] = useState<string>('');
  const [importName, setImportName] = useState<string>('');

  // Crates inteligentes
  const [smartName, setSmartName] = useState<string>('');
  const [smartBpmMin, setSmartBpmMin] = useState<string>('');
  const [smartBpmMax, setSmartBpmMax] = useState<string>('');
  const [smartKeys, setSmartKeys] = useState<string>('');
  const [smartCues, setSmartCues] = useState<'any' | 'yes' | 'no'>('any');
  const [smartBitrate, setSmartBitrate] = useState<string>('');
  const [smartPreview, setSmartPreview] = useState<number | null>(null);
  const [smartRules, setSmartRules] = useState<any[]>([]);

  // Novidades
  const [newFiles, setNewFiles] = useState<any>(null);

  // Desfazer
  const [ops, setOps] = useState<any[]>([]);
  const [confirm, setConfirm] = useState<{ open: boolean; title: string; message: string; detail?: string; run: () => void }>({
    open: false, title: '', message: '', run: () => {},
  });

  const loadOps = useCallback(async () => {
    if (!isTauri) return;
    try {
      const res = await call<any>('list_journal', { limit: 50 });
      setOps(Array.isArray(res.items) ? res.items : []);
    } catch (e) {
      console.error(e);
    }
  }, [isTauri]);

  const loadSmartRules = useCallback(async () => {
    if (!isTauri) return;
    try {
      const res = await call<any>('smart_crate_list');
      setSmartRules(Array.isArray(res.items) ? res.items : []);
    } catch (e) {
      console.error(e);
    }
  }, [isTauri]);

  useEffect(() => {
    loadOps();
    loadSmartRules();
  }, [loadOps, loadSmartRules]);

  // Progresso do lote de análise vem por evento emitido pelo backend
  useEffect(() => {
    if (!isTauri) return;
    let unlisten: (() => void) | undefined;
    (async () => {
      const { listen } = await import('@tauri-apps/api/event');
      unlisten = await listen<string>('analysis-progress', (event) => {
        try {
          const data = JSON.parse(event.payload);
          if (data.tipo === 'progresso') {
            setAnalysisProgress({ processados: data.processados, total: data.total });
            setAnalysisRows(prev => [data.resultado, ...prev].slice(0, 200));
          }
        } catch {
          /* linha inválida: ignorar */
        }
      });
    })();
    return () => { if (unlisten) unlisten(); };
  }, [isTauri]);

  const runHealth = async () => {
    if (!isTauri || !ready) return;
    setBusyHealth(true);
    try {
      const res = await call<any>('library_health', { mp3Path, seratoPath });
      setHealth(res);
      onAddLog(`📊 Saúde da biblioteca: ${res.total_faixas} faixas, ${res.sem_bpm} sem BPM, ${res.sem_tom} sem tom.`);
    } catch (e) {
      onAddLog(`❌ Saúde da biblioteca: ${e}`);
    } finally {
      setBusyHealth(false);
    }
  };

  const runAnalysis = () => {
    if (!isTauri || !mp3Path) return;
    const doRun = async () => {
      setBusyAnalysis(true);
      setAnalysisRows([]);
      setAnalysisProgress(null);
      onAddLog(`🎚️ Análise de BPM/Tom iniciada em toda a biblioteca (${analysisWrite ? 'gravando tags' : 'somente leitura'}).`);
      try {
        const res = await call<any>('analyze_tracks_batch', {
          mp3Path, limit: 0, write: analysisWrite, includeFilled: analysisIncludeFilled,
        });
        onAddLog(`✅ Análise concluída: ${res.analisadas} analisadas, ${res.gravadas} gravadas, ${res.erros} erros.`);
        loadOps();
      } catch (e) {
        onAddLog(`❌ Análise de BPM/Tom: ${e}`);
      } finally {
        setBusyAnalysis(false);
      }
    };
    if (analysisWrite) {
      setConfirm({
        open: true,
        title: 'Gravar BPM e tom nas tags?',
        message: 'Serão gravados BPM e tom (Camelot) em todas as faixas MP3 da biblioteca que ainda não têm esses campos.',
        detail: 'Cada alteração fica registrada no journal e pode ser desfeita na seção "Desfazer". Recomendado: rode a análise sem gravar primeiro e confira os resultados.',
        run: () => { setConfirm(c => ({ ...c, open: false })); doRun(); },
      });
    } else {
      doRun();
    }
  };

  const runRefs = async () => {
    if (!isTauri || !seratoPath) return;
    try {
      const res = await call<any>('check_crate_references', { seratoPath });
      setRefs(res);
      onAddLog(`🔎 Referências verificadas: ${res.crates_verificadas} crates, ${res.referencias_quebradas} referências quebradas.`);
    } catch (e) {
      onAddLog(`❌ Verificação de crates: ${e}`);
    }
  };

  const exportM3u = async (crateFile: string) => {
    try {
      const res = await call<any>('export_crate_m3u', { seratoPath, crateFile });
      if (res.sucesso) onAddLog(`📤 ${res.mensagem} → ${res.arquivo}`);
      else onAddLog(`❌ Exportação: ${res.erro}`);
    } catch (e) {
      onAddLog(`❌ Exportação: ${e}`);
    }
  };

  const importM3u = () => {
    if (!m3uPath.trim() || !importName.trim()) return;
    setConfirm({
      open: true,
      title: 'Criar crate a partir do M3U?',
      message: `Será criada a crate "${importName.trim()}" com as faixas do arquivo que existem dentro da biblioteca.`,
      detail: 'Faixas fora da raiz da biblioteca ou inexistentes são ignoradas e listadas no retorno.',
      run: async () => {
        setConfirm(c => ({ ...c, open: false }));
        try {
          const res = await call<any>('import_m3u_crate', { seratoPath, m3uPath: m3uPath.trim(), crateName: importName.trim() });
          if (res.sucesso) onAddLog(`🎯 ${res.mensagem} (ignoradas: ${res.ignoradas})`);
          else onAddLog(`❌ Importação M3U: ${res.erro}`);
        } catch (e) {
          onAddLog(`❌ Importação M3U: ${e}`);
        }
      },
    });
  };

  const smartConfig = () => {
    const regras: Record<string, unknown> = {};
    if (smartBpmMin.trim()) regras.bpm_min = Number(smartBpmMin);
    if (smartBpmMax.trim()) regras.bpm_max = Number(smartBpmMax);
    const keys = smartKeys.split(',').map(k => k.trim().toUpperCase()).filter(Boolean);
    if (keys.length) regras.camelot = keys;
    if (smartCues === 'yes') regras.com_cues = true;
    if (smartCues === 'no') regras.com_cues = false;
    if (smartBitrate.trim()) regras.bitrate_min = Number(smartBitrate);
    return JSON.stringify({ nome: smartName.trim(), regras });
  };

  const smartPrev = async () => {
    try {
      const res = await call<any>('smart_crate_create', { mp3Path, seratoPath, configJson: smartConfig(), dryRun: true });
      if (res.sucesso) setSmartPreview(res.total);
      else onAddLog(`❌ Prévia: ${res.erro}`);
    } catch (e) {
      onAddLog(`❌ Prévia: ${e}`);
    }
  };

  const smartCreate = async () => {
    if (!smartName.trim()) return;
    try {
      const res = await call<any>('smart_crate_create', { mp3Path, seratoPath, configJson: smartConfig(), dryRun: false });
      if (res.sucesso) {
        onAddLog(`🎯 ${res.mensagem}`);
        loadSmartRules();
      } else {
        onAddLog(`❌ Crate inteligente: ${res.erro}`);
      }
    } catch (e) {
      onAddLog(`❌ Crate inteligente: ${e}`);
    }
  };

  const smartRefreshAll = async () => {
    try {
      const res = await call<any>('smart_crate_refresh', { mp3Path, seratoPath });
      onAddLog(`🔄 Crates inteligentes regeneradas: ${res.atualizadas} de ${res.itens?.length ?? 0}.`);
    } catch (e) {
      onAddLog(`❌ Regeneração: ${e}`);
    }
  };

  const smartRemove = async (nome: string) => {
    try {
      await call<any>('smart_crate_delete', { nome });
      loadSmartRules();
    } catch (e) {
      onAddLog(`❌ Remoção: ${e}`);
    }
  };

  const runNewFiles = async () => {
    try {
      const res = await call<any>('scan_new_tracks', { mp3Path });
      setNewFiles(res);
      onAddLog(res.linha_base ? `🛰️ ${res.mensagem}` : `🛰️ ${res.total_novos} faixa(s) nova(s) desde a última verificação.`);
    } catch (e) {
      onAddLog(`❌ Novas faixas: ${e}`);
    }
  };

  const undoOne = (op: any) => {
    setConfirm({
      open: true,
      title: 'Desfazer esta alteração?',
      message: `Restaurar as tags de "${op.nome}" ao estado anterior à operação "${op.acao}".`,
      detail: `Registrada em ${op.criado_em}. O áudio não é alterado.`,
      run: async () => {
        setConfirm(c => ({ ...c, open: false }));
        try {
          const res = await call<any>('undo_journal', { opId: op.id });
          if (res.sucesso) onAddLog(`⏪ ${res.mensagem}`);
          else onAddLog(`❌ Desfazer: ${res.erro}`);
          loadOps();
        } catch (e) {
          onAddLog(`❌ Desfazer: ${e}`);
        }
      },
    });
  };

  if (!isTauri) {
    return <EmptyState text="Ferramentas disponíveis apenas no aplicativo desktop." />;
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-3">
      {!ready && (
        <EmptyState text="Selecione a pasta MP3 e a pasta _Serato_ no topo da tela para usar as ferramentas de biblioteca." />
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {/* Saúde */}
        <Card title="Saúde da biblioteca" icon={<Gauge className="w-4 h-4 text-serato-cyan" />} hint="leitura apenas">
          <Btn onClick={runHealth} disabled={!ready || busyHealth}>
            <RefreshCw className={`w-3.5 h-3.5 ${busyHealth ? 'animate-spin' : ''}`} />
            <span>{busyHealth ? 'Calculando...' : 'Atualizar relatório'}</span>
          </Btn>
          {!health ? (
            <EmptyState text="Nenhum relatório ainda. Clique em Atualizar para medir a biblioteca." />
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {[
                ['Faixas', health.total_faixas],
                ['Tamanho (GB)', health.tamanho_gb],
                ['Sem BPM', health.sem_bpm],
                ['Sem tom', health.sem_tom],
                [`< ${health.limiar_kbps} kbps`, health.baixa_qualidade],
                ['Sem cues', health.sem_cues],
                ['Crates', health.crates ?? '—'],
                ['Refs. quebradas', health.referencias_quebradas ?? '—'],
              ].map(([label, value]) => (
                <div key={String(label)} className="bg-serato-dark border border-serato-cardBorder rounded-lg p-2">
                  <div className="text-[10px] text-serato-muted uppercase tracking-wide">{label}</div>
                  <div className="text-base font-semibold text-white font-mono">{value}</div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Novidades */}
        <Card title="Novas faixas" icon={<Radar className="w-4 h-4 text-serato-neonGreen" />} hint="compara com a última verificação">
          <Btn onClick={runNewFiles} disabled={!ready}>
            <Radar className="w-3.5 h-3.5" />
            <span>Verificar novidades</span>
          </Btn>
          {!newFiles ? (
            <EmptyState text="Na primeira verificação o app registra uma linha de base. Depois, mostra o que entrou na pasta." />
          ) : newFiles.linha_base ? (
            <p className="text-[11px] text-serato-muted">{newFiles.mensagem}</p>
          ) : newFiles.total_novos === 0 ? (
            <EmptyState text={`Nenhuma faixa nova. Removidas desde a última verificação: ${newFiles.removidos}.`} />
          ) : (
            <div className="max-h-40 overflow-y-auto space-y-1">
              <p className="text-[11px] text-serato-muted">{newFiles.total_novos} nova(s) · removidas: {newFiles.removidos}</p>
              {newFiles.novos.map((n: any) => (
                <div key={n.arquivo} className="text-[11px] font-mono text-slate-300 truncate flex items-center gap-1.5" title={n.arquivo}>
                  {onPlayTrack && (
                    <button
                      type="button"
                      onClick={() => onPlayTrack({
                        caminho: n.arquivo,
                        nome: n.nome
                      })}
                      className="p-0.5 rounded hover:bg-slate-700 text-serato-gold hover:text-white transition cursor-pointer shrink-0"
                      title="Tocar no Player nativo"
                    >
                      <Play className="w-2.5 h-2.5 fill-current" />
                    </button>
                  )}
                  <span className="truncate">{n.nome}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* BPM / Tom */}
      <Card title="BPM e tonalidade (Camelot)" icon={<Sparkles className="w-4 h-4 text-serato-gold" />} hint="análise local de toda a biblioteca, sem internet">
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-slate-300">
            <input type="checkbox" checked={analysisWrite} onChange={e => setAnalysisWrite(e.target.checked)} />
            Gravar nas tags (MP3)
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-300">
            <input type="checkbox" checked={analysisIncludeFilled} onChange={e => setAnalysisIncludeFilled(e.target.checked)} />
            Incluir já preenchidas
          </label>
          <Btn tone="primary" onClick={runAnalysis} disabled={!mp3Path || busyAnalysis}>
            <Play className="w-3.5 h-3.5" />
            <span>{busyAnalysis ? 'Analisando biblioteca toda...' : 'Analisar biblioteca toda'}</span>
          </Btn>
        </div>
        {analysisProgress && (
          <div className="space-y-1">
            <div className="h-1.5 w-full bg-serato-dark rounded-full overflow-hidden">
              <div className="h-full bg-serato-cyan transition-all"
                style={{ width: `${Math.round((analysisProgress.processados / Math.max(1, analysisProgress.total)) * 100)}%` }} />
            </div>
            <p className="text-[11px] text-serato-muted font-mono">{analysisProgress.processados} / {analysisProgress.total}</p>
          </div>
        )}
        {analysisRows.length === 0 ? (
          <EmptyState text="Os resultados aparecem aqui durante a análise. Confiança baixa indica que o BPM ou o tom devem ser conferidos." />
        ) : (
          <div className="max-h-64 overflow-auto border border-serato-cardBorder rounded-lg">
            <table className="w-full text-[11px]">
              <thead className="sticky top-0 bg-serato-header text-serato-muted">
                <tr>
                  <th className="text-left px-2 py-1.5 font-medium">Faixa</th>
                  <th className="text-right px-2 py-1.5 font-medium">BPM</th>
                  <th className="text-right px-2 py-1.5 font-medium">Confiança</th>
                  <th className="text-left px-2 py-1.5 font-medium">Tom</th>
                  <th className="text-left px-2 py-1.5 font-medium">Camelot</th>
                  <th className="text-left px-2 py-1.5 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {analysisRows.map((r, i) => (
                  <tr key={`${r.arquivo}-${i}`} className="border-t border-serato-cardBorder">
                    <td className="px-2 py-1 text-slate-200 truncate max-w-[220px]" title={r.arquivo}>
                      <div className="flex items-center gap-1.5 truncate">
                        {onPlayTrack && (
                          <button
                            type="button"
                            onClick={() => onPlayTrack({
                              caminho: r.arquivo,
                              nome: r.nome,
                              bpm: r.bpm ? parseFloat(r.bpm) : undefined
                            })}
                            className="p-1 rounded hover:bg-slate-700 text-serato-gold hover:text-white transition cursor-pointer shrink-0"
                            title="Tocar no Player nativo"
                          >
                            <Play className="w-3 h-3 fill-current" />
                          </button>
                        )}
                        <span className="truncate">{r.nome}</span>
                      </div>
                    </td>
                    <td className="px-2 py-1 text-right font-mono text-white">{r.bpm ?? '—'}</td>
                    <td className={`px-2 py-1 text-right font-mono ${r.bpm_confianca < 0.5 ? 'text-serato-orange' : 'text-serato-neonGreen'}`}>
                      {r.bpm_confianca !== undefined ? Math.round(r.bpm_confianca * 100) + '%' : '—'}
                    </td>
                    <td className="px-2 py-1 text-slate-300">{r.tom || '—'}</td>
                    <td className="px-2 py-1 font-mono text-serato-gold">{r.camelot || '—'}</td>
                    <td className="px-2 py-1 text-slate-400">{r.erro ? <span className="text-rose-300">{r.erro}</span> : r.gravado ? 'gravado' : 'analisado'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {/* Crates: referências e M3U */}
        <Card title="Crates: referências e M3U" icon={<Layers className="w-4 h-4 text-serato-orange" />}>
          <Btn onClick={runRefs} disabled={!seratoPath}>
            <Eye className="w-3.5 h-3.5" />
            <span>Verificar referências quebradas</span>
          </Btn>
          {refs && (
            <div className="max-h-48 overflow-y-auto space-y-1.5">
              <p className="text-[11px] text-serato-muted">
                {refs.crates_verificadas} crates · {refs.referencias_quebradas} referências quebradas
              </p>
              {refs.crates.map((c: any) => (
                <div key={c.crate} className="flex items-center justify-between gap-2 bg-serato-dark border border-serato-cardBorder rounded-lg px-2 py-1.5">
                  <div className="min-w-0">
                    <div className="text-xs text-slate-200 truncate" title={c.nome}>{c.nome}</div>
                    <div className={`text-[10px] font-mono ${c.faltando > 0 ? 'text-serato-orange' : 'text-serato-muted'}`}>
                      {c.total} faixas · {c.faltando} faltando
                    </div>
                  </div>
                  <button type="button" onClick={() => exportM3u(c.crate)}
                    className="shrink-0 inline-flex items-center gap-1 text-[11px] text-serato-cyan hover:text-cyan-300 cursor-pointer">
                    <FileDown className="w-3.5 h-3.5" /> M3U
                  </button>
                </div>
              ))}
            </div>
          )}
          <div className="border-t border-serato-cardBorder pt-3 space-y-2">
            <p className="text-[11px] text-serato-muted">Importar um M3U como nova crate</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <input className={inputCls} placeholder="Caminho do arquivo .m3u" value={m3uPath} onChange={e => setM3uPath(e.target.value)} />
              <input className={inputCls} placeholder="Nome da nova crate" value={importName} onChange={e => setImportName(e.target.value)} />
            </div>
            <Btn onClick={importM3u} disabled={!m3uPath.trim() || !importName.trim() || !seratoPath}>
              <FileUp className="w-3.5 h-3.5" />
              <span>Importar M3U</span>
            </Btn>
          </div>
        </Card>

        {/* Crates inteligentes */}
        <Card title="Crates inteligentes" icon={<Library className="w-4 h-4 text-serato-cyan" />} hint="regras que se regeneram">
          <div className="grid grid-cols-2 gap-2">
            <Field label="Nome da crate">
              <input className={inputCls} value={smartName} onChange={e => setSmartName(e.target.value)} placeholder="Ex.: Tech House 120-124" />
            </Field>
            <Field label="Qualquer tom (Camelot, vírgula)">
              <input className={inputCls} value={smartKeys} onChange={e => setSmartKeys(e.target.value)} placeholder="8A, 8B, 9A" />
            </Field>
            <Field label="BPM mínimo">
              <input className={inputCls} type="number" value={smartBpmMin} onChange={e => setSmartBpmMin(e.target.value)} />
            </Field>
            <Field label="BPM máximo">
              <input className={inputCls} type="number" value={smartBpmMax} onChange={e => setSmartBpmMax(e.target.value)} />
            </Field>
            <Field label="Cues do Serato">
              <select className={inputCls} value={smartCues} onChange={e => setSmartCues(e.target.value as any)}>
                <option value="any">Qualquer</option>
                <option value="yes">Com cues</option>
                <option value="no">Sem cues</option>
              </select>
            </Field>
            <Field label="Bitrate mínimo (kbps)">
              <input className={inputCls} type="number" value={smartBitrate} onChange={e => setSmartBitrate(e.target.value)} placeholder="320" />
            </Field>
          </div>
          <div className="flex items-center gap-2">
            <Btn onClick={smartPrev} disabled={!ready}>
              <Eye className="w-3.5 h-3.5" /><span>Prévia</span>
            </Btn>
            <Btn tone="primary" onClick={smartCreate} disabled={!ready || !smartName.trim()}>
              <Play className="w-3.5 h-3.5" /><span>Criar / atualizar crate</span>
            </Btn>
            {smartPreview !== null && <span className="text-[11px] text-serato-muted font-mono">prévia: {smartPreview} faixas</span>}
          </div>

          <div className="border-t border-serato-cardBorder pt-3 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-[11px] text-serato-muted">Regras salvas ({smartRules.length})</p>
              <Btn onClick={smartRefreshAll} disabled={!ready || smartRules.length === 0}>
                <RefreshCw className="w-3.5 h-3.5" /><span>Regenerar todas</span>
              </Btn>
            </div>
            {smartRules.length === 0 ? (
              <EmptyState text="Nenhuma regra salva. Ao criar uma crate inteligente, ela fica aqui para ser regenerada quando a biblioteca mudar." />
            ) : (
              smartRules.map(r => (
                <div key={r.nome} className="flex items-center justify-between gap-2 bg-serato-dark border border-serato-cardBorder rounded-lg px-2 py-1.5">
                  <span className="text-xs text-slate-200 truncate">{r.nome}</span>
                  <button type="button" onClick={() => smartRemove(r.nome)} title="Remover regra (a crate no Serato permanece)"
                    className="text-slate-400 hover:text-rose-300 cursor-pointer">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* Desfazer */}
      <Card title="Desfazer alterações" icon={<Undo2 className="w-4 h-4 text-serato-muted" />} hint="journal unificado: Auto-Cue e análise">
        {ops.length === 0 ? (
          <EmptyState text="Nenhuma alteração registrada. Gravações de Hot Cues e de BPM/tom aparecem aqui e podem ser desfeitas." />
        ) : (
          <div className="max-h-72 overflow-y-auto space-y-1.5">
            {ops.map(op => (
              <div key={op.id} className="flex items-center justify-between gap-3 bg-serato-dark border border-serato-cardBorder rounded-lg px-2.5 py-1.5">
                <div className="min-w-0">
                  <div className="text-xs text-slate-200 truncate" title={op.arquivo}>{op.nome}</div>
                  <div className="text-[10px] text-serato-muted font-mono">{op.criado_em} · {op.acao}</div>
                </div>
                {op.desfeita ? (
                  <span className="text-[10px] text-serato-muted">desfeita</span>
                ) : (
                  <button type="button" onClick={() => undoOne(op)}
                    className="shrink-0 inline-flex items-center gap-1 text-[11px] text-slate-300 hover:text-white cursor-pointer">
                    <Undo2 className="w-3.5 h-3.5" /> Desfazer
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <ConfirmModal
        isOpen={confirm.open}
        title={confirm.title}
        message={confirm.message}
        detail={confirm.detail}
        confirmText="Confirmar"
        variant="warning"
        onConfirm={confirm.run}
        onCancel={() => setConfirm(c => ({ ...c, open: false }))}
      />
    </div>
  );
};
