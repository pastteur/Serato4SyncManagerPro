import React, { useState, useEffect, useMemo } from 'react';
import { Database, ShieldCheck, History, RotateCcw, CheckCircle2, AlertTriangle, FileArchive, FolderOpen, Search } from 'lucide-react';
import { ConfirmModal } from './ConfirmModal';

interface BackupManagerProps {
  onAddLog: (message: string) => void;
  onOpenLogsFolder: () => void;
}

export const BackupManager: React.FC<BackupManagerProps> = ({
  onAddLog,
  onOpenLogsFolder
}) => {
  const [backups, setBackups] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isRestoring, setIsRestoring] = useState<boolean>(false);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [cueBackups, setCueBackups] = useState<any[]>([]);
  const [isLoadingCues, setIsLoadingCues] = useState<boolean>(false);
  const [cueSearchTerm, setCueSearchTerm] = useState<string>('');

  const filteredBackups = useMemo(() => {
    if (!searchTerm.trim()) return backups;
    const q = searchTerm.toLowerCase();
    return backups.filter((b: any) =>
      b.nome?.toLowerCase().includes(q) ||
      b.data?.toLowerCase().includes(q)
    );
  }, [backups, searchTerm]);

  // Modal de Confirmação em Tela
  const [modalConfig, setModalConfig] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    detail?: string;
    confirmText?: string;
    variant?: 'danger' | 'warning' | 'info';
    onConfirm: () => void;
  }>({
    isOpen: false,
    title: '',
    message: '',
    onConfirm: () => {}
  });

  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);

  const loadBackups = async () => {
    if (!isTauri) return;
    setIsLoading(true);
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const res = await invoke<string>('list_serato_backups');
      const list = JSON.parse(res);
      setBackups(Array.isArray(list) ? list : []);
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadBackups();
    loadCueBackups();
  }, []);

  const loadCueBackups = async () => {
    if (!isTauri) return;
    setIsLoadingCues(true);
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const res = await invoke<string>('list_cue_backups', {
        search: cueSearchTerm.trim() || null
      });
      const data = JSON.parse(res);
      setCueBackups(Array.isArray(data.items) ? data.items : []);
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoadingCues(false);
    }
  };

  const handleRestoreCue = (item: any) => {
    setModalConfig({
      isOpen: true,
      title: 'Restaurar Hot Cues da Faixa',
      message: `Devolver os cues de "${item.filename}" ao estado anterior?`,
      detail: `Backup de: ${item.data}\nCues registrados no backup: ${item.quantidade_cues}\nCaminho: ${item.filepath}\n\nAs posições de cues gravadas depois desse backup serão substituídas. A faixa continua intacta; apenas as tags Serato são reescritas.`,
      confirmText: 'Restaurar Cues',
      variant: 'warning',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsRestoring(true);
        onAddLog(`⏪ Restaurando cues de ${item.filename}...`);
        try {
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            const res = await invoke<string>('restore_auto_cues', {
              filepath: item.filepath
            });
            const data = JSON.parse(res);
            if (data.sucesso) {
              onAddLog(`🎯 ${data.mensagem}`);
              loadCueBackups();
            } else {
              onAddLog(`❌ Erro ao restaurar cues: ${data.erro}`);
            }
          }
        } catch (e) {
          onAddLog(`❌ Falha: ${e}`);
        } finally {
          setIsRestoring(false);
        }
      }
    });
  };

  const handleCreateBackup = async () => {
    if (!isTauri) return;
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const res = await invoke<string>('backup_serato_db');
      const data = JSON.parse(res);
      if (data.sucesso) {
        onAddLog(`✅ Novo snapshot criado: ${data.arquivo} (${data.tamanho_mb} MB)`);
        loadBackups();
      } else {
        onAddLog(`❌ Erro ao criar backup: ${data.erro}`);
      }
    } catch (e) {
      onAddLog(`❌ Erro: ${e}`);
    }
  };

  const handleRestore = (backupItem: any) => {
    setModalConfig({
      isOpen: true,
      title: 'Restaurar Snapshot da Base de Dados',
      message: `Deseja restaurar a base de dados do Serato para a versão de ${backupItem.data}?`,
      detail: `Arquivo: ${backupItem.nome}\nO banco master.sqlite atual será substituído pelo conteúdo deste snapshot. Uma cópia do banco atual será salva automaticamente por segurança.`,
      confirmText: 'Restaurar Versão',
      variant: 'warning',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsRestoring(true);
        onAddLog(`⏪ Restaurando banco do Serato a partir de ${backupItem.nome}...`);

        try {
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            const res = await invoke<string>('restore_serato_db', {
              backupPath: backupItem.caminho
            });
            const data = JSON.parse(res);
            if (data.sucesso) {
              onAddLog(`🎯 ${data.mensagem}`);
              loadBackups();
            } else {
              onAddLog(`❌ Erro na restauração: ${data.erro}`);
            }
          }
        } catch (e) {
          onAddLog(`❌ Falha: ${e}`);
        } finally {
          setIsRestoring(false);
        }
      }
    });
  };

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl p-4 shadow-2xl flex flex-col h-full flex-1 overflow-hidden min-h-0 space-y-3">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between pb-2.5 border-b border-serato-cardBorder shrink-0 gap-2">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <History className="w-4 h-4 text-serato-neonGreen" />
            <span>Histórico de Snapshots & Restauração Segura (master.sqlite)</span>
            <span className="text-[10px] bg-serato-neonGreen/20 text-serato-neonGreen px-2 py-0.5 rounded-full border border-serato-neonGreen/30 font-mono">
              Zero Corrupção Garantida
            </span>
          </h3>
          <p className="text-[11px] text-serato-muted">
            Antes de qualquer alteração, o sistema gera backups automáticos e versionados em ~/pasync/backups/.
            A segunda lista recupera os Hot Cues gravados pelo Auto-Cue faixa por faixa.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onOpenLogsFolder}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-serato-card hover:bg-slate-700 text-slate-200 border border-serato-cardBorder transition cursor-pointer"
          >
            <FolderOpen className="w-3.5 h-3.5 text-serato-cyan" />
            <span>Abrir Pasta de Backups</span>
          </button>

          <button
            type="button"
            onClick={handleCreateBackup}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-serato-neonGreen hover:bg-emerald-300 text-black shadow-lg shadow-serato-neonGreen/20 transition cursor-pointer"
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>🛡️ Criar Novo Snapshot Agora</span>
          </button>
        </div>
      </div>

      {/* Lista de Backups */}
      <div className="flex-1 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20">
        <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder text-xs text-serato-muted font-mono flex items-center justify-between">
          <span>{filteredBackups.length} de {backups.length} Snapshots Armazenados</span>
          <span>Local: ~/pasync/backups/</span>
        </div>

        {/* Barra de Busca de Backups */}
        <div className="bg-serato-dark/60 p-2 border-b border-serato-cardBorder flex items-center gap-2 shrink-0">
          <div className="relative flex-1">
            <Search className="w-3.5 h-3.5 text-serato-muted absolute left-2.5 top-2.5" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Filtrar backups por data ou nome do arquivo..."
              className="w-full pl-8 pr-3 py-1.5 text-xs bg-serato-dark border border-serato-cardBorder rounded-lg text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-neonGreen transition font-sans"
            />
          </div>
        </div>

        <div className="overflow-y-auto flex-1 p-2 space-y-2">
          {filteredBackups.length === 0 ? (
            <div className="py-12 text-center text-slate-500 text-xs">
              <Database className="w-8 h-8 opacity-20 text-serato-neonGreen mx-auto mb-2" />
              <p>Nenhum snapshot encontrado.</p>
              <p className="text-slate-600 mt-1">Ajuste o filtro de busca ou clique em "Criar Novo Snapshot Agora".</p>
            </div>
          ) : (
            filteredBackups.map((item, idx) => (
              <div key={idx} className="bg-serato-card border border-serato-cardBorder p-3 rounded-lg flex items-center justify-between hover:bg-white/[0.02]">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded bg-serato-dark border border-white/5 text-serato-neonGreen">
                    <FileArchive className="w-4 h-4" />
                  </div>
                  <div>
                    <div className="font-semibold text-white text-xs">{item.nome}</div>
                    <div className="text-[10px] text-serato-muted font-mono flex items-center gap-3 mt-0.5">
                      <span>Data: {item.data}</span>
                      <span>•</span>
                      <span>Tamanho: <b className="text-slate-300">{item.tamanho_mb} MB</b></span>
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => handleRestore(item)}
                  disabled={isRestoring}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-serato-dark hover:bg-rose-950/40 text-slate-300 hover:text-rose-300 border border-serato-cardBorder hover:border-rose-800/40 transition cursor-pointer"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>Restaurar Esta Versão</span>
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Lista de Backups de Hot Cues (Auto-Cue) */}
      <div className="border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col shrink-0 max-h-[38%] bg-serato-card/20">
        <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder text-xs text-serato-muted font-mono flex items-center justify-between">
          <span>{cueBackups.length} Faixas com Backup de Hot Cues</span>
          <span>Local: ~/.serato_sync_cues_backup.sqlite</span>
        </div>

        <div className="bg-serato-dark/60 p-2 border-b border-serato-cardBorder flex items-center gap-2 shrink-0">
          <div className="relative flex-1">
            <Search className="w-3.5 h-3.5 text-serato-muted absolute left-2.5 top-2.5" />
            <input
              type="text"
              value={cueSearchTerm}
              onChange={(e) => setCueSearchTerm(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') loadCueBackups(); }}
              placeholder="Filtrar por nome da faixa ou caminho e pressione Enter..."
              className="w-full pl-8 pr-3 py-1.5 text-xs bg-serato-dark border border-serato-cardBorder rounded-lg text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-neonGreen transition font-sans"
            />
          </div>
          <button
            type="button"
            onClick={loadCueBackups}
            disabled={isLoadingCues}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-serato-card hover:bg-slate-700 text-slate-200 border border-serato-cardBorder transition cursor-pointer disabled:opacity-50"
          >
            {isLoadingCues ? 'Buscando...' : 'Buscar'}
          </button>
        </div>

        <div className="overflow-y-auto flex-1 p-2 space-y-2">
          {cueBackups.length === 0 ? (
            <div className="py-6 text-center text-slate-500 text-xs">
              <History className="w-7 h-7 opacity-20 text-serato-cyan mx-auto mb-2" />
              <p>Nenhum backup de Hot Cues registrado.</p>
              <p className="text-slate-600 mt-1">Os backups aparecem aqui depois que o Auto-Cue grava cues em alguma faixa.</p>
            </div>
          ) : (
            cueBackups.map((item, idx) => (
              <div key={`${item.filepath}-${idx}`} className="bg-serato-card border border-serato-cardBorder p-2.5 rounded-lg flex items-center justify-between gap-3 hover:bg-white/[0.02]">
                <div className="min-w-0">
                  <div className="font-semibold text-white text-xs truncate">{item.filename}</div>
                  <div className="text-[10px] text-serato-muted font-mono flex items-center gap-2 mt-0.5 flex-wrap">
                    <span>Backup: {item.created_at}</span>
                    <span>•</span>
                    <span>Cues: <b className="text-slate-300">{item.quantidade_cues}</b></span>
                    <span>•</span>
                    {item.arquivo_existe ? (
                      <span className="text-serato-neonGreen">arquivo presente</span>
                    ) : (
                      <span className="text-amber-400">arquivo ausente no disco</span>
                    )}
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => handleRestoreCue(item)}
                  disabled={isRestoring || !item.arquivo_existe}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-serato-dark hover:bg-cyan-950/40 text-slate-300 hover:text-cyan-300 border border-serato-cardBorder hover:border-cyan-800/40 transition cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>Restaurar Cues</span>
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      <ConfirmModal
        isOpen={modalConfig.isOpen}
        title={modalConfig.title}
        message={modalConfig.message}
        detail={modalConfig.detail}
        confirmText={modalConfig.confirmText}
        variant={modalConfig.variant}
        onConfirm={modalConfig.onConfirm}
        onCancel={() => setModalConfig(prev => ({ ...prev, isOpen: false }))}
      />
    </div>
  );
};