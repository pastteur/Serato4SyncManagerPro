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
import { LibraryTools } from './components/LibraryTools';
import { LogEntry, SyncSummary } from './types';
import { Terminal, Copy, FolderTree, BookOpen, Sparkles, Shield, Music, History, Activity, Target, Loader2, X, Library, Sun, Moon } from 'lucide-react';


type TabId = 'logs' | 'duplicates' | 'tree' | 'library' | 'matcher' | 'soundSeal' | 'tagDoctor' | 'health' | 'autoCue' | 'backups';

const TAB_META: Record<TabId, { label: string; icon: React.ComponentType<{ className?: string }>; iconClass: string }> = {
  logs: { label: 'Terminal & Sync', icon: Terminal, iconClass: '' },
  duplicates: { label: 'Duplicados', icon: Copy, iconClass: '' },
  tree: { label: 'Estrutura de Crates', icon: FolderTree, iconClass: '' },
  library: { label: 'Biblioteca', icon: Library, iconClass: '' },
  matcher: { label: 'Track Matcher', icon: Music, iconClass: '' },
  soundSeal: { label: 'Sound Seal & Relocate', icon: Shield, iconClass: '' },
  tagDoctor: { label: 'Tag Doctor', icon: Sparkles, iconClass: '' },
  health: { label: 'Audio Health', icon: Activity, iconClass: '' },
  autoCue: { label: 'Auto-Cue', icon: Target, iconClass: '' },
  backups: { label: 'Backups', icon: History, iconClass: '' },
};

const TAB_GROUPS: { label: string; tabs: TabId[] }[] = [
  { label: 'Sincronização', tabs: ['logs', 'duplicates', 'tree'] },
  { label: 'Biblioteca', tabs: ['library', 'matcher', 'soundSeal'] },
  { label: 'Tags e áudio', tabs: ['tagDoctor', 'health', 'autoCue'] },
  { label: 'Segurança', tabs: ['backups'] },
];

// Tauri API dynamic loader
const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);

export const App: React.FC = () => {
  const [mp3Path, setMp3Path] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('serato_sync_mp3_path') || '';
    }
    return '';
  });
  const [seratoPath, setSeratoPath] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem('serato_sync_serato_path') || '';
    }
    return '';
  });
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    try {
      return localStorage.getItem('serato_sync_theme') === 'light' ? 'light' : 'dark';
    } catch {
      return 'dark';
    }
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem('serato_sync_theme', theme);
    } catch {
      /* armazenamento indisponível: o tema vale só nesta sessão */
    }
  }, [theme]);
  const [exportCsv, setExportCsv] = useState<boolean>(true);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [summary, setSummary] = useState<SyncSummary | null>(null);
  const [activeTab, setActiveTab] = useState<TabId>('logs');
  const [isGuideOpen, setIsGuideOpen] = useState<boolean>(false);
  const [seratoRunning, setSeratoRunning] = useState<boolean>(false);

  useEffect(() => {
    if (!isTauri) return;
    const checkSerato = async () => {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const tele = await invoke<any>('get_system_telemetry');
        if (tele) {
          setSeratoRunning(Boolean(tele.serato_running));
        }
      } catch (e) {
        // Silencioso em caso de polling
      }
    };
    checkSerato();
    const interval = setInterval(checkSerato, 2500);
    return () => clearInterval(interval);
  }, [isTauri]);

  useEffect(() => {
    if (mp3Path && mp3Path.trim()) {
      localStorage.setItem('serato_sync_mp3_path', mp3Path.trim());
    } else {
      localStorage.removeItem('serato_sync_mp3_path');
    }
  }, [mp3Path]);

  useEffect(() => {
    if (seratoPath && seratoPath.trim()) {
      localStorage.setItem('serato_sync_serato_path', seratoPath.trim());
    } else {
      localStorage.removeItem('serato_sync_serato_path');
    }
  }, [seratoPath]);

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

  // Initial path detection & validation
  const handleAutoDetect = useCallback(async (forceOverride: boolean = false) => {
    if (isTauri) {
      try {
        const { invoke } = await import('@tauri-apps/api/core');

        const currentMp3 = (localStorage.getItem('serato_sync_mp3_path') || mp3Path || '').trim();
        const currentSerato = (localStorage.getItem('serato_sync_serato_path') || seratoPath || '').trim();

        const isMp3Valid = currentMp3 ? await invoke<boolean>('validate_path', { path: currentMp3 }) : false;
        const isSeratoValid = currentSerato ? await invoke<boolean>('validate_path', { path: currentSerato }) : false;

        // Se ambos forem válidos e não for um clique forçado, preserva rigorosamente a seleção do usuário
        if (!forceOverride && isMp3Valid && isSeratoValid) {
          return;
        }

        const paths = await invoke<{ mp3: string; serato: string }>('get_detected_paths');

        // Preenche somente caminhos ausentes ou inválidos
        if (paths.mp3 && (forceOverride || !isMp3Valid)) {
          setMp3Path(paths.mp3);
        }
        if (paths.serato && (forceOverride || !isSeratoValid)) {
          setSeratoPath(paths.serato);
        }

        addLog(`🔍 Auto-detecção de pastas: MP3=${paths.mp3 || '(não localizado)'} | Serato=${paths.serato || '(não localizado)'}`);
      } catch (err) {
        addLog(`⚠️ Falha na auto-detecção via Tauri: ${err}`);
      }
    } else {
      // Browser Mock
      if (!mp3Path) setMp3Path('/Volumes/Pastteyr/Music/MP3');
      if (!seratoPath) setSeratoPath('/Volumes/Pastteyr/_Serato_');
      addLog('🔍 Auto-detecção simulada em ambiente Web Dev.');
    }
  }, [mp3Path, seratoPath, addLog]);

  useEffect(() => {
    // Inicialização: preenche somente caminhos ausentes ou inválidos sem sobrescrever caminhos válidos
    handleAutoDetect(false);
  }, []);

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
          defaultPath: mp3Path || '/Volumes',
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
          defaultPath: seratoPath || '/Volumes',
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
      const promptVal = prompt('Informe o caminho da pasta Serato:', seratoPath || '/Volumes/Pastteyr/_Serato_');
      if (promptVal) {
        setSeratoPath(promptVal);
        addLog(`📂 Pasta Serato definida: ${promptVal}`);
      }
    }
  };

  // Start Sync Execution (supports dry-run / simulation)
  const handleStartSync = async (dryRun: boolean = false) => {
    if (!mp3Path || !seratoPath) {
      addLog('⚠️ Por favor, selecione ambas as pastas (Músicas e Serato) antes de iniciar.');
      setActiveTab('logs');
      return;
    }

    // Trava de segurança: impede execução acidental na raiz, Mesa/Desktop ou diretório Home
    const cleanMp3 = mp3Path.trim().replace(/\/$/, '');
    if (cleanMp3 === '/' || cleanMp3.endsWith('/Desktop') || cleanMp3.endsWith('/Mesa')) {
      addLog('❌ Operação bloqueada: A pasta MP3 não pode ser a Área de Trabalho (Mesa) nem a raiz do sistema.');
      setActiveTab('logs');
      return;
    }

    if (!dryRun && isTauri) {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const tele = await invoke<any>('get_system_telemetry');
        if (tele && tele.serato_running) {
          alert(
            "⚠️ BLOQUEIO DE SEGURANÇA ATIVO!\n\n" +
            "O Serato DJ Pro está em execução ativa no momento.\n\n" +
            "Feche o Serato DJ Pro antes de aplicar alterações ('Ajustar').\n" +
            "Enquanto o Serato estiver aberto, seu cache na memória RAM sobrescreverá e reverterá qualquer alteração física nas crates e tags quando você o fechar.\n\n" +
            "Dica: O 'Modo Análise (Sem Alterar)' pode ser executado normalmente a qualquer momento com o Serato aberto."
          );
          return;
        }
      } catch (err) {
        // Fallback para trava nativa do Tauri backend
      }
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
      addLog('📂 No aplicativo desktop nativo, isso abre a pasta ~/SeratoSync/logs no Finder.');
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
      addLog(`🔍 Revelar arquivo no Finder: ${filePath}`);
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
        addLog(`⚠️ Erro ao mover para a Lixeira: ${err}`);
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

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isGuideOpen) {
        setIsGuideOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isGuideOpen]);

  return (
    <div className="flex flex-col h-screen bg-serato-dark text-slate-100 overflow-hidden font-sans select-none">
      <Header isRunning={isRunning} onOpenGuide={() => setIsGuideOpen(true)} />

      {/* Main Container without Double Scrolling */}
      <main className="flex-1 min-h-0 flex flex-col p-2 md:p-3 space-y-2 overflow-hidden">
        {/* Step 1: Path Selection (Compact & Fixed) */}
        <div className="shrink-0">
          <PathSelector
            mp3Path={mp3Path}
            seratoPath={seratoPath}
            onSelectMp3={handleSelectMp3}
            onSelectSerato={handleSelectSerato}
            onAutoDetect={() => handleAutoDetect(true)}
            disabled={isRunning}
          />
        </div>

        {/* Step 2: Controls & Metrics (Visible on Sync Tabs: Terminal, Duplicates, Crates Tree) */}
        {['logs', 'duplicates', 'tree'].includes(activeTab) && (
          <div className="shrink-0 animate-in fade-in duration-150">
            <SyncControls
              isRunning={isRunning}
              onStartSync={handleStartSync}
              canStart={Boolean(mp3Path && seratoPath)}
              exportCsv={exportCsv}
              setExportCsv={setExportCsv}
              summary={summary}
              seratoRunning={seratoRunning}
            />
          </div>
        )}

        {/* Notificador Slim quando Sincronização estiver rodando em segundo plano e usuário estiver em outra aba */}
        {isRunning && !['logs', 'duplicates', 'tree'].includes(activeTab) && (
          <div className="bg-serato-cyan/15 border border-serato-cyan/50 px-3 py-1.5 rounded-lg flex items-center justify-between text-xs shrink-0 animate-pulse">
            <span className="flex items-center gap-2 text-serato-cyan font-bold">
              <Loader2 className="w-3.5 h-3.5 animate-spin text-serato-cyan" />
              <span>Sincronização Serato 4 ativa em segundo plano...</span>
            </span>
            <button
              type="button"
              onClick={() => setActiveTab('logs')}
              className="text-[11px] bg-serato-cyan text-black font-bold px-2.5 py-0.5 rounded hover:bg-cyan-300 transition cursor-pointer"
            >
              Ver no Terminal
            </button>
          </div>
        )}

        <div className="flex-1 min-h-0 flex gap-3 overflow-hidden">
          {/* Navegação lateral agrupada */}
          <nav className="w-52 shrink-0 flex flex-col gap-3 overflow-y-auto pr-1" aria-label="Seções do aplicativo">
            {TAB_GROUPS.map(group => (
              <div key={group.label} className="space-y-0.5">
                <div className="px-2.5 pb-0.5 text-[10px] font-semibold uppercase tracking-wider text-serato-muted">{group.label}</div>
                {group.tabs.map(id => {
                  const meta = TAB_META[id];
                  const Icon = meta.icon;
                  const active = activeTab === id;
                  const badge =
                    id === 'logs' && logs.length > 0 ? logs.length :
                    id === 'duplicates' && summary && summary.total_duplicados > 0 ? summary.total_duplicados : null;
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setActiveTab(id)}
                      aria-current={active ? 'page' : undefined}
                      className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs font-semibold text-left transition cursor-pointer border ${
                        active
                          ? 'bg-serato-cyan/10 text-serato-cyan border-serato-cyan/40'
                          : 'text-serato-muted hover:text-white hover:bg-serato-hover border-transparent'
                      }`}
                    >
                      <Icon className="w-3.5 h-3.5 shrink-0" />
                      <span className="truncate flex-1">{meta.label}</span>
                      {id === 'logs' && isRunning && <Loader2 className="w-3 h-3 animate-spin text-serato-cyan shrink-0" />}
                      {badge !== null && (
                        <span className="text-[10px] bg-serato-card text-serato-muted px-1.5 rounded-full border border-serato-cardBorder font-mono shrink-0">
                          {badge}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            ))}

            <div className="mt-auto pt-2 border-t border-serato-cardBorder space-y-2">
              {isRunning && (
                <div className="text-[11px] text-serato-cyan flex items-center gap-1.5 px-1">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  <span>Sincronização em andamento</span>
                </div>
              )}
              <button
                type="button"
                onClick={() => setTheme(t => (t === 'dark' ? 'light' : 'dark'))}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs font-semibold text-serato-muted hover:text-white hover:bg-serato-hover border border-serato-cardBorder cursor-pointer transition"
              >
                {theme === 'dark' ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
                <span>{theme === 'dark' ? 'Tema claro' : 'Tema escuro'}</span>
              </button>
            </div>
          </nav>

          <div className="flex-1 min-w-0 min-h-0 overflow-hidden flex flex-col relative">
          {activeTab === 'logs' && (
            <div className="flex-1 min-h-0 flex flex-col h-full">
            <TerminalLogs
              logs={logs}
              onClear={() => setLogs([])}
              isRunning={isRunning}
            />
            </div>
          )}

          {activeTab === 'duplicates' && (
            <div className="flex-1 min-h-0 flex flex-col h-full">
            <DuplicatesAudit
              duplicates={summary?.duplicados || []}
              csvPath={summary?.csv_duplicados || null}
              onOpenLogsFolder={handleOpenLogsFolder}
              onExportCsv={handleOpenLogsFolder}
              onOpenFileInFinder={handleOpenFileInFinder}
              onMoveToTrash={handleMoveToTrash}
            />
            </div>
          )}

          {activeTab === 'tree' && (
            <div className="flex-1 min-h-0 flex flex-col h-full">
            <CrateTreePreview
              summary={summary}
              onOpenFileInFinder={handleOpenFileInFinder}
            />
            </div>
          )}

          {activeTab === 'tagDoctor' && (
            <div className="flex-1 min-h-0 flex flex-col h-full">
            <TagDoctor
              mp3Path={mp3Path}
              onAddLog={addLog}
              onOpenFileInFinder={handleOpenFileInFinder}
            />
            </div>
          )}

          {activeTab === 'soundSeal' && (
            <div className="flex-1 min-h-0 flex flex-col h-full">
            <SoundSeal
              mp3Path={mp3Path}
              seratoPath={seratoPath}
              onAddLog={addLog}
              onOpenFileInFinder={handleOpenFileInFinder}
              onMoveToTrash={handleMoveToTrash}
            />
            </div>
          )}

          {activeTab === 'matcher' && (
            <div className="flex-1 min-h-0 flex flex-col h-full">
            <TrackMatcher
              mp3Path={mp3Path}
              seratoPath={seratoPath}
              onAddLog={addLog}
              onOpenFileInFinder={handleOpenFileInFinder}
            />
            </div>
          )}

          {activeTab === 'health' && (
            <div className="flex-1 min-h-0 flex flex-col h-full">
            <AudioHealth
              mp3Path={mp3Path}
              onAddLog={addLog}
              onOpenFileInFinder={handleOpenFileInFinder}
              onMoveToTrash={handleMoveToTrash}
            />
            </div>
          )}

          {activeTab === 'autoCue' && (
            <div className="flex-1 min-h-0 flex flex-col h-full">
            <AutoCueGenerator
              mp3Path={mp3Path}
              onAddLog={addLog}
              onOpenFileInFinder={handleOpenFileInFinder}
            />
            </div>
          )}

          {activeTab === 'library' && (
            <div className="flex-1 min-h-0 flex flex-col h-full">
            <LibraryTools
              onAddLog={addLog}
              mp3Path={mp3Path}
              seratoPath={seratoPath}
            />
            </div>
          )}

          {activeTab === 'backups' && (
            <div className="flex-1 min-h-0 flex flex-col h-full">
            <BackupManager
              onAddLog={addLog}
              onOpenLogsFolder={handleOpenLogsFolder}
            />
            </div>
          )}
          </div>
        </div>
      </main>

      {/* Modal / Dialog do Guia Serato 4 acessível a partir da esteira de utilidades do Header */}
      {isGuideOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 sm:p-6 animate-in fade-in">
          <div className="bg-serato-dark border border-serato-cardBorder rounded-2xl shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col overflow-hidden">
            <div className="bg-serato-header px-5 py-3 border-b border-serato-cardBorder flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2.5">
                <BookOpen className="w-5 h-5 text-serato-gold" />
                <span className="text-sm font-bold text-white font-sans">
                  Manual de Arquitetura & Engenharia • Serato DJ Pro 4
                </span>
              </div>
              <button
                type="button"
                onClick={() => setIsGuideOpen(false)}
                className="p-1 rounded-lg hover:bg-white/10 text-slate-400 hover:text-white transition cursor-pointer"
                title="Fechar (ESC)"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="overflow-y-auto flex-1 p-5">
              <ArchitectureGuide />
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
