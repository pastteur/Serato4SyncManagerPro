import React, { useState, useMemo } from 'react';
import { 
  X, Trash2, Folder, Play, Search, AlertTriangle, ShieldCheck, 
  CheckSquare, Square, FolderPlus, Archive, CheckCircle2, Loader2, HardDrive
} from 'lucide-react';
import { PlayingTrackInfo } from './AudioPlayerBar';
import { ConfirmModal } from './ConfirmModal';

export interface OrphanFileItem {
  filepath: string;
  filename: string;
  rel_path: string;
  size_bytes: number;
  size_mb: number;
}

export interface OrphanReportData {
  sucesso: boolean;
  mp3_dir?: string;
  total_scanned?: number;
  total_unused?: number;
  total_unused_bytes?: number;
  total_unused_gb?: number;
  unused_files?: OrphanFileItem[];
}

interface OrphanFilesModalProps {
  isOpen: boolean;
  onClose: () => void;
  report: OrphanReportData | null;
  mp3Path: string;
  seratoPath: string;
  onOpenFileInFinder?: (filePath: string) => void;
  onPlayTrack?: (track: PlayingTrackInfo) => void;
  onMoveToTrash?: (filePath: string, itemId: string) => Promise<boolean>;
  onAddLog?: (message: string) => void;
  onUpdateReport?: (newReport: OrphanReportData) => void;
}

export const OrphanFilesModal: React.FC<OrphanFilesModalProps> = ({
  isOpen,
  onClose,
  report,
  mp3Path,
  seratoPath,
  onOpenFileInFinder,
  onPlayTrack,
  onMoveToTrash,
  onAddLog,
  onUpdateReport,
}) => {
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [sortBy, setSortBy] = useState<'name' | 'size_desc' | 'size_asc'>('size_desc');
  const [isProcessing, setIsProcessing] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  // Modal de Aprovação Obrigatória (Princípio Analisar -> Prévia -> Ajustar)
  const [confirmConfig, setConfirmConfig] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    count: number;
    variant: 'danger' | 'warning' | 'info' | 'success';
    action: () => Promise<void>;
  }>({
    isOpen: false,
    title: '',
    message: '',
    count: 0,
    variant: 'warning',
    action: async () => {},
  });

  const filesList: OrphanFileItem[] = useMemo(() => {
    return report?.unused_files || [];
  }, [report]);

  // Filtro e Ordenação
  const filteredFiles = useMemo(() => {
    let result = [...filesList];
    const s = searchTerm.trim().toLowerCase();
    if (s) {
      result = result.filter(f => 
        f.filename.toLowerCase().includes(s) || 
        f.rel_path.toLowerCase().includes(s)
      );
    }

    if (sortBy === 'name') {
      result.sort((a, b) => a.filename.localeCompare(b.filename));
    } else if (sortBy === 'size_desc') {
      result.sort((a, b) => b.size_bytes - a.size_bytes);
    } else if (sortBy === 'size_asc') {
      result.sort((a, b) => a.size_bytes - b.size_bytes);
    }
    return result;
  }, [filesList, searchTerm, sortBy]);

  if (!isOpen) return null;

  const toggleSelectAll = () => {
    if (selectedPaths.size === filteredFiles.length && filteredFiles.length > 0) {
      setSelectedPaths(new Set());
    } else {
      setSelectedPaths(new Set(filteredFiles.map(f => f.filepath)));
    }
  };

  const toggleSelect = (filepath: string) => {
    const next = new Set(selectedPaths);
    if (next.has(filepath)) {
      next.delete(filepath);
    } else {
      next.add(filepath);
    }
    setSelectedPaths(next);
  };

  // Remover arquivos da lista local após ação bem-sucedida
  const removeFilesFromState = (pathsToRemove: Set<string>) => {
    const updated = filesList.filter(f => !pathsToRemove.has(f.filepath));
    const totalBytes = updated.reduce((acc, f) => acc + f.size_bytes, 0);
    const newReport: OrphanReportData = {
      ...report,
      sucesso: true,
      total_unused: updated.length,
      total_unused_bytes: totalBytes,
      total_unused_gb: Math.round((totalBytes / (1024 * 1024 * 1024)) * 100) / 100,
      unused_files: updated,
    };
    if (onUpdateReport) onUpdateReport(newReport);
    setSelectedPaths(new Set());
  };

  // Ação 1: Mover Selecionados para Lixeira do macOS
  const handleBatchTrash = () => {
    const targets = Array.from(selectedPaths);
    if (targets.length === 0) return;

    setConfirmConfig({
      isOpen: true,
      title: 'Mover Faixas Órfãs para a Lixeira',
      message: `Deseja mover as ${targets.length} faixa(s) órfã(s) selecionada(s) para a Lixeira do macOS? Os arquivos ainda poderão ser restaurados pela Lixeira caso necessário.`,
      count: targets.length,
      variant: 'danger',
      action: async () => {
        setIsProcessing(true);
        setStatusMessage('Movendo arquivos para a Lixeira do macOS...');
        let movedCount = 0;
        try {
          const { invoke } = await import('@tauri-apps/api/core');
          for (const fp of targets) {
            try {
              await invoke('move_to_trash', { path: fp });
              movedCount++;
            } catch {
              // Continua para o próximo
            }
          }
          removeFilesFromState(new Set(targets));
          if (onAddLog) {
            onAddLog(`🗑️ ${movedCount} faixa(s) órfã(s) movida(s) para a Lixeira.`);
          }
          setStatusMessage(`✅ ${movedCount} faixas movidas com sucesso para a Lixeira.`);
        } catch (e: any) {
          alert(`Erro ao mover para a Lixeira: ${e}`);
        } finally {
          setIsProcessing(false);
          setConfirmConfig(prev => ({ ...prev, isOpen: false }));
        }
      }
    });
  };

  // Ação 2: Mover Selecionados para Quarentena
  const handleBatchQuarantine = () => {
    const targets = Array.from(selectedPaths);
    if (targets.length === 0) return;

    setConfirmConfig({
      isOpen: true,
      title: 'Mover para Quarentena Segura',
      message: `As ${targets.length} faixa(s) selecionada(s) serão movidas para a pasta '_Quarentena_Orfaos' dentro de '${mp3Path}'. Nenhum arquivo será excluído.`,
      count: targets.length,
      variant: 'warning',
      action: async () => {
        setIsProcessing(true);
        setStatusMessage('Movendo arquivos para quarentena...');
        try {
          const { invoke } = await import('@tauri-apps/api/core');
          const resJson = await invoke<string>('quarantine_orphan_files', {
            mp3Path,
            seratoPath: seratoPath || '',
            files: targets,
            dest: '_Quarentena_Orfaos'
          });
          const res = JSON.parse(resJson);
          if (res.sucesso) {
            removeFilesFromState(new Set(targets));
            if (onAddLog) {
              onAddLog(`🛡️ ${res.moved_count} faixa(s) órfã(s) isolada(s) em ${res.destination}`);
            }
            setStatusMessage(`✅ ${res.moved_count} faixas isoladas com sucesso em quarentena.`);
          } else {
            alert(res.erro || 'Falha ao mover para quarentena.');
          }
        } catch (e: any) {
          alert(`Erro na quarentena: ${e}`);
        } finally {
          setIsProcessing(false);
          setConfirmConfig(prev => ({ ...prev, isOpen: false }));
        }
      }
    });
  };

  // Ação 3: Criar Crate "Órfãos" no Serato
  const handleCreateOrphanCrate = () => {
    const targets = Array.from(selectedPaths.size > 0 ? selectedPaths : new Set(filesList.map(f => f.filepath)));
    if (targets.length === 0) return;

    setConfirmConfig({
      isOpen: true,
      title: "Criar Crate '_Órfãos_Detectados' no Serato",
      message: `Será criada uma nova Crate chamada '_Órfãos_Detectados' no Serato contendo as ${targets.length} faixas selecionadas, permitindo inspecioná-las diretamente no Serato DJ Pro.`,
      count: targets.length,
      variant: 'info',
      action: async () => {
        setIsProcessing(true);
        setStatusMessage('Criando crate no Serato...');
        try {
          const { invoke } = await import('@tauri-apps/api/core');
          const resJson = await invoke<string>('crate_add_paths', {
            seratoPath,
            crateName: '_Órfãos_Detectados',
            paths: targets
          });
          const res = JSON.parse(resJson);
          if (res.sucesso) {
            if (onAddLog) {
              onAddLog(`📂 Crate '_Órfãos_Detectados' criada com sucesso no Serato (${targets.length} faixas).`);
            }
            setStatusMessage(`✅ Crate '_Órfãos_Detectados' criada com sucesso no Serato!`);
          } else {
            alert(res.erro || 'Falha ao criar crate no Serato.');
          }
        } catch (e: any) {
          alert(`Erro ao criar crate: ${e}`);
        } finally {
          setIsProcessing(false);
          setConfirmConfig(prev => ({ ...prev, isOpen: false }));
        }
      }
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden">
        
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20">
              <HardDrive className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base leading-tight flex items-center gap-2">
                <span>Gerenciador de Arquivos Órfãos</span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-amber-400/10 text-amber-400 border border-amber-400/20 font-mono">
                  {filesList.length} faixas ({report?.total_unused_gb || 0} GB)
                </span>
              </h3>
              <p className="text-xs text-slate-400">
                Arquivos de áudio presentes no HD que não pertencem a nenhuma Crate do Serato
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Toolbar */}
        <div className="p-4 border-b border-slate-800 bg-slate-950/30 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 flex-1 min-w-[240px]">
            <div className="relative flex-1">
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-2.5" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Filtrar por nome ou pasta..."
                className="w-full pl-8 pr-3 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded-xl text-slate-200 placeholder-slate-500 focus:outline-none focus:border-serato-cyan font-sans"
              />
            </div>

            <select
              value={sortBy}
              onChange={(e: any) => setSortBy(e.target.value)}
              className="px-2.5 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded-xl text-slate-300 focus:outline-none cursor-pointer font-sans"
            >
              <option value="size_desc">Maior Tamanho</option>
              <option value="size_asc">Menor Tamanho</option>
              <option value="name">Nome (A-Z)</option>
            </select>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={toggleSelectAll}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 transition cursor-pointer"
            >
              {selectedPaths.size === filteredFiles.length && filteredFiles.length > 0 ? (
                <>
                  <CheckSquare className="w-3.5 h-3.5 text-serato-cyan" />
                  <span>Desmarcar Todos</span>
                </>
              ) : (
                <>
                  <Square className="w-3.5 h-3.5 text-slate-400" />
                  <span>Selecionar Todos ({filteredFiles.length})</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Status Message */}
        {statusMessage && (
          <div className="px-6 py-2 bg-slate-950 border-b border-slate-800 text-xs text-serato-cyan font-mono flex items-center justify-between">
            <span>{statusMessage}</span>
            <button onClick={() => setStatusMessage(null)} className="text-slate-500 hover:text-white">✕</button>
          </div>
        )}

        {/* Tabela de Arquivos */}
        <div className="flex-1 min-h-0 overflow-y-auto divide-y divide-slate-800/60 p-2">
          {filteredFiles.length === 0 ? (
            <div className="py-20 text-center text-slate-500 space-y-2">
              <CheckCircle2 className="w-8 h-8 mx-auto text-emerald-400 opacity-80" />
              <p className="text-sm font-semibold text-slate-300">Nenhum arquivo órfão encontrado!</p>
              <p className="text-xs text-slate-500">Todas as faixas analisadas estão vinculadas a crates do Serato.</p>
            </div>
          ) : (
            filteredFiles.map((file) => {
              const isSelected = selectedPaths.has(file.filepath);
              return (
                <div
                  key={file.filepath}
                  className={`px-3 py-2.5 rounded-xl flex items-center justify-between gap-3 text-xs transition ${
                    isSelected ? 'bg-serato-cyan/10 border border-serato-cyan/20' : 'hover:bg-slate-800/40'
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelect(file.filepath)}
                      className="rounded bg-slate-900 border-slate-700 text-serato-cyan focus:ring-0 cursor-pointer"
                    />

                    <div className="min-w-0 flex-1">
                      <div className="font-semibold text-slate-200 truncate leading-snug">
                        {file.filename}
                      </div>
                      <div className="text-[10px] text-slate-400 font-mono truncate" title={file.rel_path}>
                        {file.rel_path}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    <span className="font-mono text-[11px] text-amber-400/90 font-semibold">
                      {file.size_mb} MB
                    </span>

                    {/* Botões de Ação por Linha */}
                    <div className="flex items-center gap-1">
                      {onPlayTrack && (
                        <button
                          type="button"
                          onClick={() => onPlayTrack({ caminho: file.filepath, nome: file.filename })}
                          className="p-1.5 rounded-lg bg-slate-800 hover:bg-serato-cyan hover:text-black text-slate-300 transition cursor-pointer"
                          title="Reproduzir faixa"
                        >
                          <Play className="w-3.5 h-3.5 fill-current" />
                        </button>
                      )}

                      {onOpenFileInFinder && (
                        <button
                          type="button"
                          onClick={() => onOpenFileInFinder(file.filepath)}
                          className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition cursor-pointer"
                          title="Mostrar no macOS Finder"
                        >
                          <Folder className="w-3.5 h-3.5 text-serato-cyan" />
                        </button>
                      )}

                      {onMoveToTrash && (
                        <button
                          type="button"
                          onClick={() => {
                            // BUG FIX #5: substitui confirm() nativo do browser pelo
                            // ConfirmModal padronizado do design system, garantindo UX
                            // consistente e supressão correta de playerShortcuts.
                            setConfirmConfig({
                              isOpen: true,
                              title: 'Mover para Lixeira',
                              message: `Mover "${file.filename}" para a Lixeira do macOS?`,
                              count: 1,
                              variant: 'danger',
                              action: async () => {
                                const ok = await onMoveToTrash(file.filepath, file.filepath);
                                if (ok) {
                                  removeFilesFromState(new Set([file.filepath]));
                                }
                              },
                            });
                          }}
                          className="p-1.5 rounded-lg bg-slate-800 hover:bg-rose-500/20 text-slate-400 hover:text-rose-400 transition cursor-pointer"
                          title="Mover para Lixeira"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer com Ações em Lote */}
        <div className="px-6 py-4 border-t border-slate-800 bg-slate-950/80 flex flex-wrap items-center justify-between gap-3">
          <div className="text-xs text-slate-400 font-mono">
            {selectedPaths.size > 0 ? (
              <span className="text-serato-cyan font-bold">
                {selectedPaths.size} faixa(s) selecionada(s)
              </span>
            ) : (
              <span>Nenhuma faixa selecionada</span>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={handleCreateOrphanCrate}
              disabled={isProcessing || filesList.length === 0}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition disabled:opacity-50 cursor-pointer"
              title="Cria uma Crate no Serato com todas as faixas órfãs"
            >
              <FolderPlus className="w-3.5 h-3.5 text-serato-gold" />
              <span>Criar Crate no Serato</span>
            </button>

            <button
              onClick={handleBatchQuarantine}
              disabled={isProcessing || selectedPaths.size === 0}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 transition disabled:opacity-50 cursor-pointer"
              title="Move as faixas selecionadas para a pasta _Quarentena_Orfaos"
            >
              <Archive className="w-3.5 h-3.5" />
              <span>Mover para Quarentena ({selectedPaths.size})</span>
            </button>

            <button
              onClick={handleBatchTrash}
              disabled={isProcessing || selectedPaths.size === 0}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-500/30 transition disabled:opacity-50 cursor-pointer"
              title="Move as faixas selecionadas para a Lixeira do Mac"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>Mover para Lixeira ({selectedPaths.size})</span>
            </button>

            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 transition cursor-pointer"
            >
              Fechar
            </button>
          </div>
        </div>

        {/* Modal de Confirmação com Botão AJUSTAR */}
        <ConfirmModal
          isOpen={confirmConfig.isOpen}
          title={confirmConfig.title}
          message={confirmConfig.message}
          variant={confirmConfig.variant}
          confirmText="AJUSTAR"
          cancelText="CANCELAR"
          onConfirm={confirmConfig.action}
          onCancel={() => setConfirmConfig(prev => ({ ...prev, isOpen: false }))}
        />
      </div>
    </div>
  );
};
