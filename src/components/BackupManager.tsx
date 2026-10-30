import React, { useState, useEffect } from 'react';
import { Database, ShieldCheck, History, RotateCcw, CheckCircle2, AlertTriangle, FileArchive, FolderOpen } from 'lucide-react';
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
  }, []);

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
          <span>{backups.length} Snapshots Armazenados</span>
          <span>Local: ~/pasync/backups/</span>
        </div>

        <div className="overflow-y-auto flex-1 p-2 space-y-2">
          {backups.length === 0 ? (
            <div className="py-12 text-center text-slate-500 text-xs">
              <Database className="w-8 h-8 opacity-20 text-serato-neonGreen mx-auto mb-2" />
              <p>Nenhum snapshot gravado no momento.</p>
              <p className="text-slate-600 mt-1">Clique em "Criar Novo Snapshot Agora" para proteger sua base.</p>
            </div>
          ) : (
            backups.map((item, idx) => (
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
