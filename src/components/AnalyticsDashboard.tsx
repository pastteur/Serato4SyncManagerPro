import React, { useState, useEffect, useCallback } from 'react';
import {
  BarChart3, RefreshCw, ExternalLink, Loader2, Music, Disc,
  HardDrive, Activity, ShieldCheck, AlertTriangle, Zap, Clock,
  FolderTree, Sparkles, CheckCircle2, XCircle, Play, Flame, Grid, Calendar
} from 'lucide-react';

interface AnalyticsDashboardProps {
  mp3Path: string;
  seratoPath: string;
  onAddLog?: (message: string) => void;
}

interface RecentSync {
  id: number;
  iniciado_em: string;
  dry_run: boolean;
  estado: string;
  sucesso: boolean | null;
  duracao_seg: number | null;
}

interface JournalStats {
  total_syncs: number;
  syncs_sucesso: number;
  syncs_dry_run: number;
  total_tag_ops: number;
  total_crate_ops: number;
  recent_syncs: RecentSync[];
}

interface CrateMetric {
  nome: string;
  total: number;
  faltando: number;
}

interface TopPlayedTrack {
  titulo: string;
  artista: string;
  bpm: number | null;
  key: string;
  plays: number;
}

interface TopPlayedGenre {
  genero: string;
  plays: number;
  tracks: number;
}

interface RecentSession {
  id: number;
  nome: string;
  data: string;
  faixas: number;
}

interface SeratoPlaybackStats {
  available: boolean;
  total_db_assets?: number;
  total_plays?: number;
  play_distribution?: Record<string, number>;
  zero_play_gb?: number;
  beatgrid_locked_count?: number;
  overview_complete_count?: number;
  top_played_tracks?: TopPlayedTrack[];
  top_played_genres?: TopPlayedGenre[];
  recent_sessions?: RecentSession[];
}

interface AnalyticsData {
  sucesso: boolean;
  total_faixas: number;
  tamanho_gb: number;
  low_quality_gb?: number;
  total_duration_hours?: number;
  sem_bpm: number;
  sem_tom: number;
  baixa_qualidade: number;
  limiar_kbps?: number;
  sem_cues: number;
  crates?: number;
  referencias_quebradas?: number;
  total_crate_tracks?: number;
  top_crates?: CrateMetric[];
  bpm_ranges?: Record<string, number>;
  duration_ranges?: Record<string, number>;
  key_distribution?: Record<string, number>;
  genre_distribution?: Record<string, number>;
  decade_distribution?: Record<string, number>;
  bpm_key_matrix?: Record<string, Record<string, number>>;
  format_distribution?: Record<string, number>;
  bitrate_distribution?: Record<string, number>;
  journal_stats?: JournalStats;
  serato_playback?: SeratoPlaybackStats;
  erro?: string;
}

const RingGauge: React.FC<{ percent: number; label: string; colorClass: string; strokeColor: string }> = ({
  percent,
  label,
  colorClass,
  strokeColor,
}) => {
  const radius = 34;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, percent));
  const offset = circumference - (clamped / 100) * circumference;

  return (
    <div className="flex flex-col items-center justify-center">
      <div className="relative w-20 h-20 flex items-center justify-center">
        <svg className="w-20 h-20 -rotate-90" viewBox="0 0 80 80">
          <circle
            cx="40"
            cy="40"
            r={radius}
            fill="transparent"
            stroke="rgba(148,163,184,0.14)"
            strokeWidth="7"
          />
          <circle
            cx="40"
            cy="40"
            r={radius}
            fill="transparent"
            stroke={strokeColor}
            strokeWidth="7"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            className="transition-all duration-700"
          />
        </svg>
        <span className={`absolute text-sm font-mono font-extrabold ${colorClass}`}>
          {clamped}%
        </span>
      </div>
      <span className="text-[11px] font-semibold text-slate-300 mt-1 text-center">{label}</span>
    </div>
  );
};

const BPM_BUCKET_ORDER = ['< 90', '90–109', '110–119', '120–125', '126–132', '133+'];

export const AnalyticsDashboard: React.FC<AnalyticsDashboardProps> = ({
  mp3Path,
  seratoPath,
  onAddLog,
}) => {
  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState<boolean>(false);

  const loadAnalytics = useCallback(async () => {
    if (!isTauri) return;
    if (!mp3Path || !mp3Path.trim()) {
      setError('Selecione a pasta MP3 Master acima para gerar os gráficos da biblioteca.');
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('library_health', {
        mp3Path,
        seratoPath: seratoPath || '',
      });
      const parsed: AnalyticsData = JSON.parse(resJson);
      if (parsed.sucesso) {
        setData(parsed);
      } else {
        setError(parsed.erro || 'Falha ao carregar métricas da biblioteca.');
      }
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [isTauri, mp3Path, seratoPath]);

  useEffect(() => {
    if (mp3Path && !data && !loading) {
      loadAnalytics();
    }
  }, [mp3Path, data, loading, loadAnalytics]);

  const handleExportHtml = async () => {
    if (!isTauri || !mp3Path) return;
    setIsExporting(true);
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const resJson = await invoke<string>('export_html_report', {
        mp3Path,
        seratoPath: seratoPath || '',
      });
      const parsed = JSON.parse(resJson);
      if (parsed.sucesso && parsed.arquivo) {
        if (onAddLog) onAddLog(`📊 Relatório HTML executivo gerado: ${parsed.arquivo}`);
        await invoke('open_in_browser', { pathOrUrl: parsed.arquivo });
      }
    } catch (e) {
      if (onAddLog) onAddLog(`⚠️ Erro ao exportar relatório HTML: ${e}`);
    } finally {
      setIsExporting(false);
    }
  };

  const total = data?.total_faixas || 0;
  const comBpm = Math.max(0, total - (data?.sem_bpm || 0));
  const comTom = Math.max(0, total - (data?.sem_tom || 0));
  const comCues = Math.max(0, total - (data?.sem_cues || 0));
  const altaQual = Math.max(0, total - (data?.baixa_qualidade || 0));

  const pctBpm = total > 0 ? Math.round((comBpm / total) * 100) : 0;
  const pctTom = total > 0 ? Math.round((comTom / total) * 100) : 0;
  const pctCues = total > 0 ? Math.round((comCues / total) * 100) : 0;
  const pctQual = total > 0 ? Math.round((altaQual / total) * 100) : 0;
  const healthScore = total > 0 ? Math.round((pctBpm + pctTom + pctCues + pctQual) / 4) : 0;

  const bpmEntries = Object.entries(data?.bpm_ranges || {});
  const maxBpmCount = Math.max(1, ...bpmEntries.map(([, v]) => v));

  const keyEntries = Object.entries(data?.key_distribution || {});
  const maxKeyCount = Math.max(1, ...keyEntries.map(([, v]) => v));

  const topCrates = data?.top_crates || [];
  const maxCrateTracks = Math.max(1, ...topCrates.map((c) => c.total));

  const formatEntries = Object.entries(data?.format_distribution || {});
  const bitrateEntries = Object.entries(data?.bitrate_distribution || {});
  const durationEntries = Object.entries(data?.duration_ranges || {});
  const maxDurCount = Math.max(1, ...durationEntries.map(([, v]) => v));

  const genreEntries = Object.entries(data?.genre_distribution || {});
  const maxGenreCount = Math.max(1, ...genreEntries.map(([, v]) => v));

  const decadeEntries = Object.entries(data?.decade_distribution || {});
  const maxDecadeCount = Math.max(1, ...decadeEntries.map(([, v]) => v));

  const pb = data?.serato_playback;
  const playDistEntries = Object.entries(pb?.play_distribution || {});
  const maxPlayDist = Math.max(1, ...playDistEntries.map(([, v]) => v));
  const topPlayedTracks = pb?.top_played_tracks || [];
  const maxTrackPlays = Math.max(1, ...topPlayedTracks.map((t) => t.plays));
  const topPlayedGenres = pb?.top_played_genres || [];
  const maxGenrePlays = Math.max(1, ...topPlayedGenres.map((g) => g.plays));
  const recentSessions = pb?.recent_sessions || [];

  const dbAssets = pb?.total_db_assets || 0;
  const pctBeatgridLocked = dbAssets > 0 ? Math.round(((pb?.beatgrid_locked_count || 0) / dbAssets) * 100) : 0;
  const pctOverviewComplete = dbAssets > 0 ? Math.round(((pb?.overview_complete_count || 0) / dbAssets) * 100) : 0;

  // Heatmap BPM x Key (top 12 Camelot keys presentes)
  const matrix = data?.bpm_key_matrix || {};
  const activeKeys = keyEntries
    .filter(([k]) => k !== 'Sem Tom')
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
    .map(([k]) => k);
  let maxMatrixCell = 1;
  for (const row of BPM_BUCKET_ORDER) {
    for (const col of activeKeys) {
      const val = matrix[row]?.[col] || 0;
      if (val > maxMatrixCell) maxMatrixCell = val;
    }
  }

  // Economia / Desperdício de Disco
  const totalGb = data?.tamanho_gb || 0;
  const zeroPlayGb = pb?.zero_play_gb || 0;
  const lowQualGb = data?.low_quality_gb || 0;
  const activeGb = Math.max(0, Number((totalGb - lowQualGb).toFixed(2)));

  const journal = data?.journal_stats;

  return (
    <div className="flex flex-col gap-3 pb-4">
      {/* Barra de Controle Superior */}
      <div className="glass-panel border border-serato-cardBorder rounded-2xl p-3.5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-serato-cyan/15 border border-serato-cyan/40 text-serato-cyan shadow-glow-cyan">
            <BarChart3 className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              Central de Analytics & Diagnóstico Geral
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-serato-purple/15 text-purple-300 border border-purple-500/30">
                Serato 5 Telemetry
              </span>
            </h3>
            <p className="text-[11px] text-serato-muted">
              Reproduções reais no Serato, matriz BPM × Key, gêneros, décadas, crates, disco e performance.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={loadAnalytics}
            disabled={loading || !mp3Path}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold bg-serato-cyan text-black hover:bg-cyan-300 disabled:opacity-50 transition cursor-pointer shadow-glow-cyan"
          >
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            <span>{loading ? 'Analisando...' : 'Atualizar Gráficos'}</span>
          </button>

          <button
            type="button"
            onClick={handleExportHtml}
            disabled={isExporting || !mp3Path}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold bg-amber-400/15 text-amber-300 border border-amber-400/40 hover:bg-amber-400/25 disabled:opacity-50 transition cursor-pointer"
          >
            {isExporting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ExternalLink className="w-3.5 h-3.5" />}
            <span>Relatório HTML</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-2xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {loading && !data && (
        <div className="glass-panel border border-serato-cardBorder rounded-2xl py-20 flex flex-col items-center justify-center gap-3 text-serato-muted">
          <Loader2 className="w-8 h-8 animate-spin text-serato-cyan" />
          <span className="text-xs font-mono">Mapeando biblioteca, Plays do Serato, BPM, Keys e Crates...</span>
        </div>
      )}

      {data && (
        <>
          {/* KPIs Principais */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4 space-y-1">
              <div className="flex items-center justify-between text-[10px] font-mono uppercase text-serato-muted">
                <span>Músicas na Biblioteca</span>
                <Music className="w-4 h-4 text-serato-cyan" />
              </div>
              <div className="text-2xl font-mono font-extrabold text-white">{total.toLocaleString()}</div>
              <div className="text-[11px] text-serato-muted">
                {totalGb} GB • {data.total_duration_hours ?? 0}h de áudio
              </div>
            </div>

            <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4 space-y-1">
              <div className="flex items-center justify-between text-[10px] font-mono uppercase text-serato-muted">
                <span>Crates & Alocações</span>
                <FolderTree className="w-4 h-4 text-purple-400" />
              </div>
              <div className="text-2xl font-mono font-extrabold text-white">
                {(data.crates ?? 0).toLocaleString()}
              </div>
              <div className="text-[11px] text-serato-muted">
                {(data.total_crate_tracks ?? 0).toLocaleString()} entradas •{' '}
                <span className={(data.referencias_quebradas || 0) > 0 ? 'text-rose-400 font-bold' : 'text-emerald-400'}>
                  {data.referencias_quebradas ?? 0} quebradas
                </span>
              </div>
            </div>

            <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4 space-y-1">
              <div className="flex items-center justify-between text-[10px] font-mono uppercase text-serato-muted">
                <span>Plays no Serato</span>
                <Play className="w-4 h-4 text-amber-400" />
              </div>
              <div className="text-2xl font-mono font-extrabold text-amber-300">
                {pb?.available ? (pb.total_plays ?? 0).toLocaleString() : '—'}
              </div>
              <div className="text-[11px] text-serato-muted">
                {pb?.available
                  ? `${dbAssets.toLocaleString()} faixas no SQLite • ${recentSessions.length} sessões`
                  : 'Banco SQLite do Serato não detectado'}
              </div>
            </div>

            <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4 space-y-1">
              <div className="flex items-center justify-between text-[10px] font-mono uppercase text-serato-muted">
                <span>Saúde Geral</span>
                <ShieldCheck className="w-4 h-4 text-emerald-400" />
              </div>
              <div className="text-2xl font-mono font-extrabold text-emerald-400">{healthScore}%</div>
              <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden mt-1">
                <div
                  className="h-full bg-gradient-to-r from-serato-cyan via-emerald-400 to-serato-neonGreen transition-all duration-700"
                  style={{ width: `${healthScore}%` }}
                />
              </div>
            </div>
          </div>

          {/* Linha 2: Gauges de Saúde + Economia/Desperdício de Disco + Formatos */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4">
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
                  <Sparkles className="w-3.5 h-3.5 text-serato-cyan" />
                  Saúde dos Metadados
                </h4>
                <span className="text-[10px] font-mono text-serato-muted">{total.toLocaleString()} faixas</span>
              </div>
              <div className="grid grid-cols-2 gap-3 py-1">
                <RingGauge percent={pctBpm} label={`Com BPM (${comBpm})`} colorClass="text-serato-cyan" strokeColor="#00e5ff" />
                <RingGauge percent={pctTom} label={`Com Tom (${comTom})`} colorClass="text-purple-400" strokeColor="#a855f7" />
                <RingGauge percent={pctCues} label={`Com Cues (${comCues})`} colorClass="text-emerald-400" strokeColor="#00e676" />
                <RingGauge percent={pctQual} label={`Qualidade ≥${data.limiar_kbps ?? 192}k`} colorClass="text-amber-400" strokeColor="#ffd700" />
              </div>
            </div>

            <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4 flex flex-col justify-between">
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2 mb-3">
                  <HardDrive className="w-3.5 h-3.5 text-amber-400" />
                  Eficiência & Desperdício de Disco
                </h4>
                <div className="space-y-2.5 text-[11px]">
                  <div className="p-2.5 rounded-xl bg-serato-card/70 border border-serato-cardBorder flex items-center justify-between">
                    <span className="text-slate-300">Biblioteca Ativa (≥192k)</span>
                    <span className="font-mono font-bold text-emerald-400">{activeGb} GB</span>
                  </div>
                  <div className="p-2.5 rounded-xl bg-rose-500/10 border border-rose-500/25 flex items-center justify-between">
                    <span className="text-rose-200">Baixa Qualidade (&lt;{data.limiar_kbps ?? 192}k)</span>
                    <span className="font-mono font-bold text-rose-400">{lowQualGb} GB ({data.baixa_qualidade} faixas)</span>
                  </div>
                  <div className="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/25 flex items-center justify-between">
                    <span className="text-amber-200">Nunca Tocadas (0 plays)</span>
                    <span className="font-mono font-bold text-amber-300">
                      {pb?.available ? `${zeroPlayGb} GB (${pb.play_distribution?.['0 plays'] ?? 0} faixas)` : 'Requer Serato SQLite'}
                    </span>
                  </div>
                </div>
              </div>
              <div className="pt-3 flex flex-wrap gap-1.5">
                {formatEntries.map(([ext, count]) => (
                  <span
                    key={ext}
                    className="text-[10px] font-mono px-2 py-0.5 rounded-md bg-serato-card border border-serato-cardBorder text-slate-200"
                  >
                    <strong className="text-serato-cyan">{ext}</strong>: {count}
                  </span>
                ))}
              </div>
            </div>

            <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4 flex flex-col justify-between">
              <h4 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2 mb-3">
                <Activity className="w-3.5 h-3.5 text-emerald-400" />
                Qualidade (Bitrate) & Preparação Serato
              </h4>
              <div className="space-y-1.5">
                {bitrateEntries.map(([label, count]) => {
                  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
                  return (
                    <div key={label} className="text-[11px]">
                      <div className="flex justify-between text-slate-300 font-mono mb-0.5">
                        <span>{label}</span>
                        <span>{count} ({pct}%)</span>
                      </div>
                      <div className="w-full h-1.5 bg-slate-800/80 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-amber-400 to-serato-cyan rounded-full"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
              {pb?.available && (
                <div className="pt-3 mt-2 border-t border-serato-cardBorder/80 grid grid-cols-2 gap-2 text-[11px]">
                  <div className="p-2 rounded-lg bg-serato-card/80 border border-serato-cardBorder">
                    <div className="text-[10px] text-serato-muted">Beatgrid Travado</div>
                    <div className="font-mono font-bold text-serato-cyan">{pctBeatgridLocked}% ({pb.beatgrid_locked_count})</div>
                  </div>
                  <div className="p-2 rounded-lg bg-serato-card/80 border border-serato-cardBorder">
                    <div className="text-[10px] text-serato-muted">Overview Completo</div>
                    <div className="font-mono font-bold text-emerald-400">{pctOverviewComplete}% ({pb.overview_complete_count})</div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Linha 3: Seção de Reproduções no Serato (Plays) */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            {/* Top 15 Mais Tocadas */}
            <div className="lg:col-span-2 glass-panel border border-serato-cardBorder rounded-2xl p-4">
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
                  <Flame className="w-3.5 h-3.5 text-amber-400" />
                  Top 15 Músicas Mais Tocadas (Serato Play Count)
                </h4>
                <span className="text-[10px] font-mono text-serato-muted">
                  {pb?.available ? `${pb.total_plays ?? 0} execuções totais` : 'SQLite indisponível'}
                </span>
              </div>
              {topPlayedTracks.length === 0 ? (
                <div className="py-10 text-center text-xs text-serato-muted">
                  Nenhuma contagem de reprodução registrada no banco SQLite do Serato.
                </div>
              ) : (
                <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
                  {topPlayedTracks.map((t, idx) => {
                    const wPct = Math.max(4, Math.round((t.plays / maxTrackPlays) * 100));
                    const label = t.artista ? `${t.artista} — ${t.titulo}` : t.titulo;
                    return (
                      <div key={`${label}-${idx}`} className="text-[11px]">
                        <div className="flex justify-between items-center gap-2 mb-0.5">
                          <span className="text-slate-200 truncate" title={label}>
                            <span className="text-serato-muted font-mono mr-1.5">#{idx + 1}</span>
                            {label}
                          </span>
                          <span className="font-mono text-amber-300 font-bold shrink-0">
                            {t.plays}x {t.bpm ? `• ${Math.round(t.bpm)}bpm` : ''} {t.key ? `• ${t.key}` : ''}
                          </span>
                        </div>
                        <div className="w-full h-1.5 bg-slate-800/80 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-amber-500 to-serato-cyan rounded-full"
                            style={{ width: `${wPct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Distribuição de Plays + Sessões */}
            <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4 flex flex-col justify-between gap-3">
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2 mb-3">
                  <Play className="w-3.5 h-3.5 text-serato-cyan" />
                  Distribuição de Reproduções
                </h4>
                {playDistEntries.length === 0 ? (
                  <div className="text-xs text-serato-muted">Sem dados de plays.</div>
                ) : (
                  <div className="space-y-2">
                    {playDistEntries.map(([bucket, count]) => {
                      const wPct = Math.max(3, Math.round((count / maxPlayDist) * 100));
                      const isZero = bucket.startsWith('0');
                      return (
                        <div key={bucket} className="text-[11px]">
                          <div className="flex justify-between font-mono text-slate-300 mb-0.5">
                            <span>{bucket}</span>
                            <span className={isZero ? 'text-amber-300' : 'text-serato-cyan'}>{count}</span>
                          </div>
                          <div className="w-full h-1.5 bg-slate-800/80 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${isZero ? 'bg-amber-400/80' : 'bg-gradient-to-r from-serato-cyan to-emerald-400'}`}
                              style={{ width: `${wPct}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="pt-2 border-t border-serato-cardBorder/80">
                <h5 className="text-[10px] font-mono uppercase text-serato-muted mb-2">
                  Últimas Sessões (Serato History)
                </h5>
                {recentSessions.length === 0 ? (
                  <div className="text-[11px] text-serato-muted">Nenhuma sessão registrada.</div>
                ) : (
                  <div className="space-y-1 max-h-28 overflow-y-auto pr-1 text-[11px] font-mono">
                    {recentSessions.map((s) => (
                      <div key={s.id} className="flex items-center justify-between text-slate-300">
                        <span className="truncate max-w-[160px]" title={s.nome}>{s.nome}</span>
                        <span className="text-serato-cyan">{s.faixas} faixas</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Linha 4: BPM + Top Crates */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4">
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
                  <Activity className="w-3.5 h-3.5 text-serato-cyan" />
                  Distribuição por Faixa de BPM
                </h4>
                <span className="text-[10px] font-mono text-serato-muted">7 faixas</span>
              </div>
              <div className="h-44 flex items-end justify-between gap-2 pt-4 pb-1 px-1">
                {bpmEntries.map(([range, count]) => {
                  const hPct = Math.max(4, Math.round((count / maxBpmCount) * 100));
                  const isMissing = range === 'Sem BPM';
                  return (
                    <div key={range} className="flex-1 flex flex-col items-center h-full justify-end group">
                      <span className="text-[10px] font-mono text-slate-300 mb-1 opacity-80 group-hover:opacity-100">
                        {count}
                      </span>
                      <div className="w-full flex-1 flex items-end">
                        <div
                          className={`w-full rounded-t-lg transition-all duration-500 ${
                            isMissing
                              ? 'bg-rose-500/60 border border-rose-400/50'
                              : 'bg-gradient-to-t from-serato-cyan/40 to-serato-cyan border border-serato-cyan/50 shadow-glow-cyan'
                          }`}
                          style={{ height: `${count === 0 ? 3 : hPct}%` }}
                          title={`${range}: ${count} músicas`}
                        />
                      </div>
                      <span className="text-[9px] font-mono text-serato-muted mt-1.5 text-center truncate w-full">
                        {range}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4">
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
                  <Disc className="w-3.5 h-3.5 text-purple-400" />
                  Músicas por Crate (Top 12)
                </h4>
                <span className="text-[10px] font-mono text-serato-muted">
                  {data.crates ?? 0} crates totais
                </span>
              </div>
              {topCrates.length === 0 ? (
                <div className="h-44 flex items-center justify-center text-xs text-serato-muted">
                  Nenhuma crate encontrada na pasta Serato selecionada.
                </div>
              ) : (
                <div className="space-y-2 max-h-44 overflow-y-auto pr-1">
                  {topCrates.map((c) => {
                    const wPct = Math.max(3, Math.round((c.total / maxCrateTracks) * 100));
                    return (
                      <div key={c.nome} className="text-[11px]">
                        <div className="flex justify-between items-center mb-0.5 gap-2">
                          <span className="text-slate-200 font-medium truncate" title={c.nome}>{c.nome}</span>
                          <span className="font-mono text-serato-cyan shrink-0">
                            {c.total}
                            {c.faltando > 0 && (
                              <span className="text-rose-400 ml-1">({c.faltando} off)</span>
                            )}
                          </span>
                        </div>
                        <div className="w-full h-1.5 bg-slate-800/80 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-purple-500 to-serato-cyan rounded-full"
                            style={{ width: `${wPct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          {/* Linha 5: Variações de Key (Camelot) + Matriz Heatmap BPM × Key */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
                  <Sparkles className="w-3.5 h-3.5 text-purple-400" />
                  Variações de Key (Roda de Camelot)
                </h4>
                <div className="flex items-center gap-2 text-[10px] font-mono">
                  <span className="text-serato-cyan">■ Minor (A)</span>
                  <span className="text-purple-400">■ Major (B)</span>
                  <span className="text-rose-400">■ Sem Tom</span>
                </div>
              </div>
              {keyEntries.length === 0 ? (
                <div className="py-8 text-center text-xs text-serato-muted">Sem dados de tonalidade.</div>
              ) : (
                <div className="h-40 flex items-end gap-1.5 pt-4 pb-1 overflow-x-auto">
                  {keyEntries.map(([keyCode, count]) => {
                    const hPct = Math.max(4, Math.round((count / maxKeyCount) * 100));
                    const isMissing = keyCode === 'Sem Tom';
                    const isMajor = keyCode.endsWith('B');
                    const barColor = isMissing
                      ? 'bg-rose-500/70'
                      : isMajor
                      ? 'bg-gradient-to-t from-purple-600/50 to-purple-400'
                      : 'bg-gradient-to-t from-serato-cyan/40 to-serato-cyan';
                    return (
                      <div key={keyCode} className="min-w-[24px] flex-1 flex flex-col items-center h-full justify-end">
                        <span className="text-[9px] font-mono text-slate-300 mb-1">{count}</span>
                        <div className="w-full flex-1 flex items-end">
                          <div
                            className={`w-full rounded-t-md ${barColor} transition-all duration-500`}
                            style={{ height: `${count === 0 ? 3 : hPct}%` }}
                            title={`${keyCode}: ${count} músicas`}
                          />
                        </div>
                        <span className="text-[9px] font-mono text-serato-muted mt-1 truncate">
                          {keyCode === 'Sem Tom' ? 'N/A' : keyCode}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Heatmap BPM x Key */}
            <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4">
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
                  <Grid className="w-3.5 h-3.5 text-serato-cyan" />
                  Matriz Heatmap BPM × Key (Top 12 Keys)
                </h4>
                <span className="text-[10px] font-mono text-serato-muted">Densidade harmônica</span>
              </div>
              {activeKeys.length === 0 ? (
                <div className="py-12 text-center text-xs text-serato-muted">Sem dados cruzados de BPM e Key.</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-[10px] font-mono border-separate border-spacing-1">
                    <thead>
                      <tr>
                        <th className="text-left text-serato-muted pr-1">BPM</th>
                        {activeKeys.map((k) => (
                          <th key={k} className="text-center text-slate-300">{k}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {BPM_BUCKET_ORDER.map((bucket) => (
                        <tr key={bucket}>
                          <td className="text-serato-muted pr-1 whitespace-nowrap">{bucket}</td>
                          {activeKeys.map((k) => {
                            const val = matrix[bucket]?.[k] || 0;
                            const alpha = val === 0 ? 0.06 : Math.min(0.9, 0.2 + (val / maxMatrixCell) * 0.7);
                            return (
                              <td
                                key={k}
                                title={`${bucket} BPM • ${k}: ${val} faixas`}
                                className="text-center rounded py-1 text-[9px]"
                                style={{
                                  backgroundColor: val === 0 ? 'rgba(148,163,184,0.06)' : `rgba(0, 229, 255, ${alpha})`,
                                  color: val > maxMatrixCell * 0.45 ? '#05070c' : '#cbd5e1',
                                  fontWeight: val > 0 ? 700 : 400,
                                }}
                              >
                                {val > 0 ? val : '·'}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          {/* Linha 6: Gêneros (Biblioteca vs Mais Tocados) + Duração + Décadas */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            {/* Gêneros na Biblioteca */}
            <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4">
              <h4 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2 mb-3">
                <Music className="w-3.5 h-3.5 text-serato-cyan" />
                Gêneros na Biblioteca (Top 10)
              </h4>
              <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                {genreEntries.map(([g, count]) => {
                  const wPct = Math.max(3, Math.round((count / maxGenreCount) * 100));
                  return (
                    <div key={g} className="text-[11px]">
                      <div className="flex justify-between text-slate-300 mb-0.5 gap-2">
                        <span className="truncate">{g}</span>
                        <span className="font-mono text-serato-cyan shrink-0">{count}</span>
                      </div>
                      <div className="w-full h-1.5 bg-slate-800/80 rounded-full overflow-hidden">
                        <div className="h-full bg-serato-cyan rounded-full" style={{ width: `${wPct}%` }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Gêneros Mais Tocados no Serato */}
            <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4">
              <h4 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2 mb-3">
                <Flame className="w-3.5 h-3.5 text-amber-400" />
                Gêneros Mais Tocados (Serato)
              </h4>
              {topPlayedGenres.length === 0 ? (
                <div className="py-12 text-center text-xs text-serato-muted">
                  Sem dados de plays por gênero no SQLite.
                </div>
              ) : (
                <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                  {topPlayedGenres.map((g) => {
                    const wPct = Math.max(3, Math.round((g.plays / maxGenrePlays) * 100));
                    return (
                      <div key={g.genero} className="text-[11px]">
                        <div className="flex justify-between text-slate-300 mb-0.5 gap-2">
                          <span className="truncate">{g.genero}</span>
                          <span className="font-mono text-amber-300 shrink-0">{g.plays} plays</span>
                        </div>
                        <div className="w-full h-1.5 bg-slate-800/80 rounded-full overflow-hidden">
                          <div className="h-full bg-gradient-to-r from-amber-500 to-serato-gold rounded-full" style={{ width: `${wPct}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Duração & Décadas */}
            <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4 flex flex-col justify-between gap-3">
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2 mb-2.5">
                  <Clock className="w-3.5 h-3.5 text-emerald-400" />
                  Duração das Faixas
                </h4>
                <div className="grid grid-cols-4 gap-2 h-20 items-end">
                  {durationEntries.map(([dur, count]) => {
                    const hPct = Math.max(6, Math.round((count / maxDurCount) * 100));
                    return (
                      <div key={dur} className="flex flex-col items-center h-full justify-end">
                        <span className="text-[9px] font-mono text-slate-300 mb-0.5">{count}</span>
                        <div className="w-full flex-1 flex items-end">
                          <div className="w-full bg-emerald-400/80 rounded-t" style={{ height: `${count === 0 ? 4 : hPct}%` }} />
                        </div>
                        <span className="text-[9px] font-mono text-serato-muted mt-1">{dur}</span>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="pt-2 border-t border-serato-cardBorder/80">
                <h4 className="text-[10px] font-mono uppercase text-serato-muted flex items-center gap-1.5 mb-2">
                  <Calendar className="w-3 h-3 text-purple-400" /> Décadas de Lançamento
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {decadeEntries.map(([dec, count]) => (
                    <span
                      key={dec}
                      className="text-[10px] font-mono px-2 py-0.5 rounded bg-serato-card border border-serato-cardBorder text-slate-200"
                      style={{ opacity: Math.max(0.6, count / maxDecadeCount) }}
                    >
                      <strong className="text-purple-300">{dec}</strong>: {count}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Linha 7: Performance & Histórico de Execuções do App (Journal) */}
          <div className="glass-panel border border-serato-cardBorder rounded-2xl p-4">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-xs font-bold uppercase tracking-wider text-white flex items-center gap-2">
                <Zap className="w-3.5 h-3.5 text-serato-cyan" />
                Performance do App (Sincronizações no Journal)
              </h4>
              <span className="text-[10px] font-mono text-serato-muted">
                {journal?.total_syncs ?? 0} syncs • {journal?.total_tag_ops ?? 0} ops de tags • {journal?.total_crate_ops ?? 0} ops de crate
              </span>
            </div>
            {!journal || journal.recent_syncs.length === 0 ? (
              <div className="py-4 text-center text-xs text-serato-muted">
                Nenhuma execução de sincronização registrada ainda no journal.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-[11px] font-mono">
                  <thead>
                    <tr className="text-serato-muted border-b border-serato-cardBorder/80">
                      <th className="py-1.5 pr-3">ID</th>
                      <th className="py-1.5 pr-3">Iniciado em</th>
                      <th className="py-1.5 pr-3">Modo</th>
                      <th className="py-1.5 pr-3">Estado</th>
                      <th className="py-1.5 pr-3">Duração</th>
                      <th className="py-1.5">Resultado</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-serato-cardBorder/50">
                    {journal.recent_syncs.map((s) => (
                      <tr key={s.id} className="hover:bg-serato-hover/40">
                        <td className="py-1.5 pr-3 text-slate-400">#{s.id}</td>
                        <td className="py-1.5 pr-3 text-slate-200">{s.iniciado_em.replace('T', ' ').slice(0, 19)}</td>
                        <td className="py-1.5 pr-3">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] ${s.dry_run ? 'bg-amber-500/15 text-amber-300' : 'bg-serato-cyan/15 text-serato-cyan'}`}>
                            {s.dry_run ? 'Dry-Run' : 'Sync Real'}
                          </span>
                        </td>
                        <td className="py-1.5 pr-3 text-slate-300">{s.estado}</td>
                        <td className="py-1.5 pr-3 text-slate-300">{s.duracao_seg !== null ? `${s.duracao_seg}s` : '—'}</td>
                        <td className="py-1.5">
                          {s.sucesso === true ? (
                            <span className="inline-flex items-center gap-1 text-emerald-400">
                              <CheckCircle2 className="w-3 h-3" /> OK
                            </span>
                          ) : s.sucesso === false ? (
                            <span className="inline-flex items-center gap-1 text-rose-400">
                              <XCircle className="w-3 h-3" /> Erro
                            </span>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};
