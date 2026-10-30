import React, { useState, useEffect, useCallback } from 'react';
import { Header } from './components/Header';
import { PathSelector } from './components/PathSelector';
import { SyncControls } from './components/SyncControls';
import { TerminalLogs } from './components/TerminalLogs';
import { DuplicatesAudit } from './components/DuplicatesAudit';
import { CrateTreePreview } from './components/CrateTreePreview';
import { ArchitectureGuide } from './components/ArchitectureGuide';
import { TagDoctor } from './components/TagDoctor';
import { SoundSeal } from './components/SoundSeal';
import { TrackMatcher } from './components/TrackMatcher';
import { BackupManager } from './components/BackupManager';
import { AudioHealth } from './components/AudioHealth';
import { AutoCueGenerator } from './components/AutoCueGenerator';
import { LogEntry, SyncSummary } from './types';
import { Terminal, Copy, FolderTree, BookOpen, Sparkles, Shield, Music, History, Activity, Target } from 'lucide-react';

// Tauri API dynamic loader
const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);

export const App: React.FC = () => {
  const [mp3Path, setMp3Path] = useState<string>('');
  const [seratoPath, setSeratoPath] = useState<string>('');
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [exportCsv, setExportCsv] = useState<boolean>(true);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [summary, setSummary] = useState<SyncSummary | null>(null);
  const [activeTab, setActiveTab] = useState<'logs' | 'duplicates' | 'tree' | 'tagDoctor' | 'soundSeal' | 'matcher' | 'health' | 'autoCue' | 'backups' | 'guide'>('logs');

  const addLog = useCallback((message: string) => {
    const now = new Date();
    const timestamp = now.toTimeString().split(' ')[0];
    let type: LogEntry['type'] = 'info';

    if (message.includes('ANÁLISE') || message.includes('DRY-RUN')) type = 'analysis';
    else if (message.includes('🆕')) type = 'add';
    else if (message.includes('🗑️')) type = 'remove';
    else if (message.includes('🚨')) type = 'delete';
    else if (message.includes('📂 Nova Crate')) type = 'create';
    else if (message.includes('🔒') || message.includes('Trava Anti-Falso-Positivo') || message.includes('inalteradas')) type = 'cache';
    else if (message.includes('🎯') || message.includes('sucesso')) type = 'success';
    else if (message.includes('❌') || message.includes('ERRO')) type = 'error';
    else if (message.includes('⚠️')) type = 'warning';

    setLogs(prev => [
      ...prev,
      {
        id: `${Date.now()}-${Math.random().toString(36).substring(2, 6)}`,
        timestamp,
        message,
        type
      }
    ]);
  }, []);

  // Initial path detection
  const handleAutoDetect = useCallback(async () => {
    if (isTauri) {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const paths = await invoke<{ mp3: string; serato: string }>('get_detected_paths');
        if (paths.mp3) setMp3Path(paths.mp3);
        if (paths.serato) setSeratoPath(paths.serato);
        addLog(`🔍 Auto-detecção concluída: MP3=${paths.mp3} | Serato=${paths.serato}`);
      } catch (err) {
        addLog(`⚠️ Falha na auto-detecção via Tauri: ${err}`);
      }
    } else {
      // Browser Mock / Local Fallback
      setMp3Path('/Volumes/Pastteyr/Music/MP3');
      setSeratoPath('/Volumes/Pastteyr/Serato');
      addLog('🔍 Auto-detecção simulada em ambiente Web Dev.');
    }
  }, [addLog]);

  useEffect(() => {
    handleAutoDetect();
  }, [handleAutoDetect]);

  // Setup Tauri Event Listeners
  useEffect(() => {
    let unlistenLog: (() => void) | undefined;
    let unlistenFinish: (() => void) | undefined;

    if (isTauri) {
      import('@tauri-apps/api/event').then(({ listen }) => {
        listen<string>('sync-log', (event) => {
          const line = event.payload;
          if (line.startsWith('__PAYLOAD_JSON_SUMMARY__')) {
            try {
              const parsed = JSON.parse(line.replace('__PAYLOAD_JSON_SUMMARY__', ''));
              setSummary(parsed);
            } catch (e) {
              // ignore
            }
          } else {
            addLog(line);
          }
        }).then(unlisten => { unlistenLog = unlisten; });

        listen<any>('sync-finished', (event) => {
          setIsRunning(false);
          const data = event.payload;
          if (data && data.summary) {
            setSummary(data.summary);
          }
          addLog('🎯 Processo de sincronização encerrado pelo sistema.');
        }).then(unlisten => { unlistenFinish = unlisten; });
      });
    }

    return () => {
      if (unlistenLog) unlistenLog();
      if (unlistenFinish) unlistenFinish();
    };
  }, [addLog]);

  // Folder Selectors via @tauri-apps/plugin-dialog
  const handleSelectMp3 = async () => {
    if (isTauri) {
      try {
        const { open } = await import('@tauri-apps/plugin-dialog');
        const selected = await open({
          directory: true,
          multiple: false,
          title: 'Selecionar Pasta Master MP3'
        });
        if (selected && typeof selected === 'string') {
          setMp3Path(selected);
          addLog(`📂 Pasta MP3 Master selecionada: ${selected}`);
        }
      } catch (err) {
        addLog(`❌ Erro ao abrir diálogo do Finder: ${err}`);
      }
    } else {
      const promptVal = prompt('Informe o caminho da pasta MP3 Master:', mp3Path || '/Volumes/Pastteyr/Music/MP3');
      if (promptVal) {
        setMp3Path(promptVal);
        addLog(`📂 Pasta MP3 Master definida: ${promptVal}`);
      }
    }
  };

  const handleSelectSerato = async () => {
    if (isTauri) {
      try {
        const { open } = await import('@tauri-apps/plugin-dialog');
        const selected = await open({
          directory: true,
          multiple: false,
          title: 'Selecionar Pasta Serato'
        });
        if (selected && typeof selected === 'string') {
          setSeratoPath(selected);
          addLog(`📂 Pasta Serato selecionada: ${selected}`);
        }
      } catch (err) {
        addLog(`❌ Erro ao abrir diálogo do Finder: ${err}`);
      }
    } else {
      const promptVal = prompt('Informe o caminho da pasta Serato:', seratoPath || '/Volumes/Pastteyr/Serato');
      if (promptVal) {
        setSeratoPath(promptVal);
        addLog(`📂 Pasta Serato definida: ${promptVal}`);
      }
    }
  };

  // Start Sync Execution (supports dry-run / simulation)
  const handleStartSync = async (dryRun: boolean = false) => {
    if (!mp3Path || !seratoPath) {
      alert('Por favor, selecione ambas as pastas antes de iniciar.');
      return;
    }

    setIsRunning(true);
    setLogs([]);
    setActiveTab('logs');
    if (dryRun) {
      addLog(`🔍 Iniciando Modo Análise (Dry Run - Sem modificações físicas no HD)...`);
    } else {
      addLog(`⚡ Disparando motor de sincronização real Serato 4...`);
    }

    if (isTauri) {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        await invoke('start_sync', {
          mp3Path,
          seratoPath,
          exportCsv,
          dryRun
        });
      } catch (err) {
        setIsRunning(false);
        addLog(`❌ Erro ao invocar motor Python: ${err}`);
      }
    } else {
      // Simulation mode in Web Dev Server
      addLog(`[MODO DEV SIMULAÇÃO] Executando simulação de sincronização...`);
      setTimeout(() => {
        addLog(`📂 Lendo músicas de: ${mp3Path}`);
        addLog(`📂 Gravando crates em: ${seratoPath}/Subcrates`);
        addLog(`🔍 Realizando varredura profunda e auditoria de binários...`);
        addLog(`   🆕 3 nova(s) faixa(s) adicionada(s) na Crate [Sertanejo -> 41]`);
        addLog(`   🔒 Trava Anti-Falso-Positivo: 2 crates poupadas pelo cache.`);
        addLog(`🧹 Atualizando preferências (neworder.pref) com novidades decrescentes no topo...`);
        addLog(`🎯 Sincronização concluída com sucesso! Pode abrir o Serato DJ Pro 4.`);
        setSummary({
          sucesso: true,
          dry_run: dryRun,
          total_faixas: 1420,
          crates_gravadas: dryRun ? 0 : 1,
          crates_inalteradas: 15,
          faixas_adicionadas: 3,
          faixas_removidas: 0,
          total_duplicados: 2,
          csv_duplicados: '~/SeratoSync/logs/relatorio_duplicados_simulado.csv',
          duplicados: [
            {
              id: 'dup-1',
              nome: 'Eu Falo Tudo Que Ela Gosta De Escutar.mp3',
              copia: `${mp3Path}/Funk/01`,
              original: `${mp3Path}/MegaFunk/12`,
              caminho_copia: `${mp3Path}/Funk/01/Eu Falo Tudo Que Ela Gosta De Escutar.mp3`,
              caminho_original: `${mp3Path}/MegaFunk/12/Eu Falo Tudo Que Ela Gosta De Escutar.mp3`,
              tamanho: 4532306
            },
            {
              id: 'dup-2',
              nome: '20 Century Fox Intro X Fein.mp3',
              copia: `${mp3Path}/Eletronica/05`,
              original: `${mp3Path}/Sets/01`,
              caminho_copia: `${mp3Path}/Eletronica/05/20 Century Fox Intro X Fein.mp3`,
              caminho_original: `${mp3Path}/Sets/01/20 Century Fox Intro X Fein.mp3`,
              tamanho: 7928822
            }
          ],
          movimentacoes: ['🆕 3 nova(s) faixa(s) adicionada(s) na Crate [Sertanejo -> 41]']
        });
        setIsRunning(false);
      }, 1500);
    }
  };

  const handleOpenLogsFolder = async () => {
    if (isTauri) {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        await invoke('open_in_finder', { path: '~/SeratoSync/logs' });
      } catch (err) {
        addLog(`⚠️ Não foi possível abrir pasta no Finder: ${err}`);
      }
    } else {
      alert('No aplicativo desktop nativo, isso abre a pasta ~/SeratoSync/logs no Finder.');
    }
  };

  const handleOpenFileInFinder = async (filePath: string) => {
    if (isTauri) {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        await invoke('open_file_in_finder', { path: filePath });
        addLog(`🔍 Arquivo revelado no Finder: ${filePath.split('/').pop()}`);
      } catch (err) {
        addLog(`⚠️ Não foi possível revelar arquivo: ${err}`);
      }
    } else {
      alert(`Revelar arquivo no Finder: ${filePath}`);
    }
  };

  const handleMoveToTrash = async (filePath: string, itemId: string): Promise<boolean> => {
    if (isTauri) {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        await invoke('move_to_trash', { path: filePath });
        addLog(`🗑️ Cópia redundante movida para a Lixeira do Mac: ${filePath.split('/').pop()}`);
        if (summary) {
          setSummary({
            ...summary,
            duplicados: summary.duplicados.filter(d => d.id !== itemId),
            total_duplicados: Math.max(0, summary.total_duplicados - 1)
          });
        }
        return true;
      } catch (err) {
        addLog(`❌ Erro ao mover para a Lixeira: ${err}`);
        alert(`Erro ao mover para a Lixeira: ${err}`);
        return false;
      }
    } else {
      addLog(`[SIMULAÇÃO] Arquivo movido para a Lixeira: ${filePath.split('/').pop()}`);
      if (summary) {
        setSummary({
          ...summary,
          duplicados: summary.duplicados.filter(d => d.id !== itemId),
          total_duplicados: Math.max(0, summary.total_duplicados - 1)
        });
      }
      return true;
    }
  };

  return (
    <div className="flex flex-col h-screen bg-serato-dark text-slate-100 overflow-hidden font-sans select-none">
      <Header isRunning={isRunning} />

      {/* Main Container without Double Scrolling */}
      <main className="flex-1 min-h-0 flex flex-col p-3 md:p-5 space-y-3 overflow-hidden">
        {/* Step 1: Path Selection (Compact & Fixed) */}
        <div className="shrink-0">
          <PathSelector
            mp3Path={mp3Path}
            seratoPath={seratoPath}
            onSelectMp3={handleSelectMp3}
            onSelectSerato={handleSelectSerato}
            onAutoDetect={handleAutoDetect}
            disabled={isRunning}
          />
        </div>

        {/* Step 2: Controls & Metrics (Compact & Fixed) */}
        <div className="shrink-0">
          <SyncControls
            isRunning={isRunning}
            onStartSync={handleStartSync}
            canStart={Boolean(mp3Path && seratoPath)}
            exportCsv={exportCsv}
            setExportCsv={setExportCsv}
            summary={summary}
          />
        </div>

        {/* Navigation Tabs Bar (Compact & Fixed) */}
        <div className="flex items-center space-x-1 border-b border-serato-cardBorder pt-1 shrink-0">
          <button
            type="button"
            onClick={() => setActiveTab('logs')}
            className={`flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-t-lg transition-all border-t border-x cursor-pointer ${
              activeTab === 'logs'
                ? 'bg-serato-dark text-serato-cyan border-serato-cardBorder border-b-transparent shadow-md'
                : 'bg-transparent text-serato-muted hover:text-white border-transparent'
            }`}
          >
            <Terminal className="w-3.5 h-3.5" />
            <span>Terminal em Tempo Real</span>
            {logs.length > 0 && (
              <span className="text-[10px] bg-serato-card text-serato-muted px-1.5 py-0.2 rounded-full border border-serato-cardBorder font-mono">
                {logs.length}
              </span>
            )}
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('duplicates')}
            className={`flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-t-lg transition-all border-t border-x cursor-pointer ${
              activeTab === 'duplicates'
                ? 'bg-serato-dark text-serato-orange border-serato-cardBorder border-b-transparent shadow-md'
                : 'bg-transparent text-serato-muted hover:text-white border-transparent'
            }`}
          >
            <Copy className="w-3.5 h-3.5" />
            <span>Auditoria de Duplicados</span>
            {summary && summary.total_duplicados > 0 && (
              <span className="text-[10px] bg-serato-orange/20 text-serato-orange px-1.5 py-0.2 rounded-full font-mono border border-serato-orange/30">
                {summary.total_duplicados}
              </span>
            )}
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('tree')}
            className={`flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-t-lg transition-all border-t border-x cursor-pointer ${
              activeTab === 'tree'
                ? 'bg-serato-dark text-serato-gold border-serato-cardBorder border-b-transparent shadow-md'
                : 'bg-transparent text-serato-muted hover:text-white border-transparent'
            }`}
          >
            <FolderTree className="w-3.5 h-3.5" />
            <span>Estrutura de Crates (%%)</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('tagDoctor')}
            className={`flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-t-lg transition-all border-t border-x cursor-pointer ${
              activeTab === 'tagDoctor'
                ? 'bg-serato-dark text-cyan-400 border-serato-cardBorder border-b-transparent shadow-md'
                : 'bg-transparent text-serato-muted hover:text-white border-transparent'
            }`}
          >
            <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
            <span>Tag Doctor</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('soundSeal')}
            className={`flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-t-lg transition-all border-t border-x cursor-pointer ${
              activeTab === 'soundSeal'
                ? 'bg-serato-dark text-serato-cyan border-serato-cardBorder border-b-transparent shadow-md'
                : 'bg-transparent text-serato-muted hover:text-white border-transparent'
            }`}
          >
            <Shield className="w-3.5 h-3.5 text-serato-cyan" />
            <span>Sound Seal & Relocate</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('matcher')}
            className={`flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-t-lg transition-all border-t border-x cursor-pointer ${
              activeTab === 'matcher'
                ? 'bg-serato-dark text-[#1DB954] border-serato-cardBorder border-b-transparent shadow-md'
                : 'bg-transparent text-serato-muted hover:text-white border-transparent'
            }`}
          >
            <Music className="w-3.5 h-3.5 text-[#1DB954]" />
            <span>Track Matcher</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('health')}
            className={`flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-t-lg transition-all border-t border-x cursor-pointer ${
              activeTab === 'health'
                ? 'bg-serato-dark text-rose-400 border-serato-cardBorder border-b-transparent shadow-md'
                : 'bg-transparent text-serato-muted hover:text-white border-transparent'
            }`}
          >
            <Activity className="w-3.5 h-3.5 text-rose-400" />
            <span>Audio Health</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('autoCue')}
            className={`flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-t-lg transition-all border-t border-x cursor-pointer ${
              activeTab === 'autoCue'
                ? 'bg-serato-dark text-serato-gold border-serato-cardBorder border-b-transparent shadow-md'
                : 'bg-transparent text-serato-muted hover:text-white border-transparent'
            }`}
          >
            <Target className="w-3.5 h-3.5 text-serato-gold" />
            <span>Auto-Cue</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('backups')}
            className={`flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-t-lg transition-all border-t border-x cursor-pointer ${
              activeTab === 'backups'
                ? 'bg-serato-dark text-serato-neonGreen border-serato-cardBorder border-b-transparent shadow-md'
                : 'bg-transparent text-serato-muted hover:text-white border-transparent'
            }`}
          >
            <History className="w-3.5 h-3.5 text-serato-neonGreen" />
            <span>Backups</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('guide')}
            className={`flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold rounded-t-lg transition-all border-t border-x cursor-pointer ${
              activeTab === 'guide'
                ? 'bg-serato-dark text-slate-200 border-serato-cardBorder border-b-transparent shadow-md'
                : 'bg-transparent text-serato-muted hover:text-white border-transparent'
            }`}
          >
            <BookOpen className="w-3.5 h-3.5" />
            <span>Guia Serato 4</span>
          </button>
        </div>

        {/* Tab Contents: Dynamic Responsive Container Filling Remaining Space */}
        <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
          {activeTab === 'logs' && (
            <TerminalLogs
              logs={logs}
              onClear={() => setLogs([])}
              isRunning={isRunning}
            />
          )}

          {activeTab === 'duplicates' && (
            <DuplicatesAudit
              duplicates={summary?.duplicados || []}
              csvPath={summary?.csv_duplicados || null}
              onOpenLogsFolder={handleOpenLogsFolder}
              onExportCsv={handleOpenLogsFolder}
              onOpenFileInFinder={handleOpenFileInFinder}
              onMoveToTrash={handleMoveToTrash}
            />
          )}

          {activeTab === 'tree' && (
            <CrateTreePreview
              summary={summary}
              onOpenFileInFinder={handleOpenFileInFinder}
            />
          )}

          {activeTab === 'tagDoctor' && (
            <TagDoctor
              mp3Path={mp3Path}
              onAddLog={addLog}
            />
          )}

          {activeTab === 'soundSeal' && (
            <SoundSeal
              mp3Path={mp3Path}
              seratoPath={seratoPath}
              onAddLog={addLog}
              onOpenFileInFinder={handleOpenFileInFinder}
              onMoveToTrash={handleMoveToTrash}
            />
          )}

          {activeTab === 'matcher' && (
            <TrackMatcher
              mp3Path={mp3Path}
              seratoPath={seratoPath}
              onAddLog={addLog}
              onOpenFileInFinder={handleOpenFileInFinder}
            />
          )}

          {activeTab === 'health' && (
            <AudioHealth
              mp3Path={mp3Path}
              onAddLog={addLog}
              onOpenFileInFinder={handleOpenFileInFinder}
              onMoveToTrash={handleMoveToTrash}
            />
          )}

          {activeTab === 'autoCue' && (
            <AutoCueGenerator
              mp3Path={mp3Path}
              onAddLog={addLog}
              onOpenFileInFinder={handleOpenFileInFinder}
            />
          )}

          {activeTab === 'backups' && (
            <BackupManager
              onAddLog={addLog}
              onOpenLogsFolder={handleOpenLogsFolder}
            />
          )}

          {activeTab === 'guide' && (
            <div className="overflow-y-auto flex-1">
              <ArchitectureGuide />
            </div>
          )}
        </div>
      </main>
    </div>
  );
};
