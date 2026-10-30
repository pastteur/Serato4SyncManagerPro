import React, { useState, useMemo } from 'react';
import { Copy, Search, FileSpreadsheet, FolderOpen, BarChart3, Database, Eye, Trash2, CheckCircle2, CheckSquare, Square, AlertTriangle } from 'lucide-react';
import { DuplicateItem } from '../types';

interface DuplicatesAuditProps {
  duplicates: DuplicateItem[];
  csvPath: string | null;
  onOpenLogsFolder: () => void;
  onExportCsv?: () => void;
  onOpenFileInFinder?: (filePath: string) => void;
  onMoveToTrash?: (filePath: string, itemId: string) => Promise<boolean>;
}

export const DuplicatesAudit: React.FC<DuplicatesAuditProps> = ({
  duplicates,
  csvPath,
  onOpenLogsFolder,
  onExportCsv,
  onOpenFileInFinder,
  onMoveToTrash
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedFolderFilter, setSelectedFolderFilter] = useState<string>('all');
  const [deletedIds, setDeletedIds] = useState<Set<string>>(new Set());
  const [isDeletingId, setIsDeletingId] = useState<string | null>(null);
  const [selectedBatchIds, setSelectedBatchIds] = useState<Set<string>>(new Set());
  const [isBatchDeleting, setIsBatchDeleting] = useState<boolean>(false);
  const [batchProgress, setBatchProgress] = useState<{ current: number; total: number } | null>(null);

  // Filtra itens deletados
  const activeDuplicates = useMemo(() => {
    return duplicates.filter(d => !deletedIds.has(d.id));
  }, [duplicates, deletedIds]);

  // Lista de pastas únicas
  const uniqueFolders = useMemo(() => {
    const folders = new Set<string>();
    duplicates.forEach(d => {
      const folderName = d.copia.split('/').pop() || 'Desconhecida';
      folders.add(folderName);
    });
    return Array.from(folders).sort();
  }, [duplicates]);

  const filteredDuplicates = useMemo(() => {
    return activeDuplicates.filter(d => {
      const matchesSearch = !searchTerm.trim() ||
        d.nome.toLowerCase().includes(searchTerm.toLowerCase()) ||
        d.copia.toLowerCase().includes(searchTerm.toLowerCase()) ||
        d.original.toLowerCase().includes(searchTerm.toLowerCase());

      const folderName = d.copia.split('/').pop() || '';
      const matchesFolder = selectedFolderFilter === 'all' || folderName === selectedFolderFilter;

      return matchesSearch && matchesFolder;
    });
  }, [activeDuplicates, searchTerm, selectedFolderFilter]);

  // Estatísticas por pasta
  const folderStats = useMemo(() => {
    const counts: Record<string, number> = {};
    activeDuplicates.forEach(d => {
      const folder = d.copia.split('/').pop() || 'Desconhecida';
      counts[folder] = (counts[folder] || 0) + 1;
    });
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5);
  }, [activeDuplicates]);

  const totalBytes = useMemo(() => {
    return activeDuplicates.reduce((acc, curr) => acc + (curr.tamanho || 0), 0);
  }, [activeDuplicates]);

  const formatSize = (bytes: number) => {
    if (!bytes) return '0 B';
    const mb = bytes / (1024 * 1024);
    if (mb > 1024) return `${(mb / 1024).toFixed(2)} GB`;
    return `${mb.toFixed(1)} MB`;
  };

  // Toggle de seleção individual
  const toggleSelect = (id: string) => {
    setSelectedBatchIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Toggle de todos visíveis
  const toggleSelectAllVisible = () => {
    const visibleIds = filteredDuplicates.map(d => d.id);
    const allSelected = visibleIds.every(id => selectedBatchIds.has(id));

    if (allSelected) {
      setSelectedBatchIds(prev => {
        const next = new Set(prev);
        visibleIds.forEach(id => next.delete(id));
        return next;
      });
    } else {
      setSelectedBatchIds(prev => {
        const next = new Set(prev);
        visibleIds.forEach(id => next.add(id));
        return next;
      });
    }
  };

  // Selecionar todos os da pasta atual
  const handleSelectCurrentFolder = () => {
    setSelectedBatchIds(prev => {
      const next = new Set(prev);
      filteredDuplicates.forEach(d => next.add(d.id));
      return next;
    });
  };

  // Exclusão individual
  const handleTrashClick = async (item: DuplicateItem) => {
    const targetPath = item.caminho_copia || `${item.copia}/${item.nome}`;
    const confirmed = window.confirm(
      `Deseja mover a cópia redundante para a Lixeira do macOS?\n\nFaixa: ${item.nome}\nPasta: ${item.copia}\n\nNota: A faixa original permanecerá 100% segura e intacta.`
    );
    if (!confirmed) return;

    if (onMoveToTrash) {
      setIsDeletingId(item.id);
      const success = await onMoveToTrash(targetPath, item.id);
      setIsDeletingId(null);
      if (success) {
        setDeletedIds(prev => new Set(prev).add(item.id));
        setSelectedBatchIds(prev => {
          const next = new Set(prev);
          next.delete(item.id);
          return next;
        });
      }
    }
  };

  // Exclusão em Lote
  const handleBatchTrash = async () => {
    const toDelete = activeDuplicates.filter(d => selectedBatchIds.has(d.id));
    if (toDelete.length === 0) {
      alert('Selecione ao menos uma faixa duplicada para excluir.');
      return;
    }

    const confirmed = window.confirm(
      `⚠️ ATENÇÃO: Deseja mover ${toDelete.length} faixas duplicadas para a Lixeira?\n\nAs faixas originais serão preservadas intactas.\nEsta ação liberará espaço no disco de forma segura.`
    );
    if (!confirmed) return;

    if (!onMoveToTrash) return;

    setIsBatchDeleting(true);
    setBatchProgress({ current: 0, total: toDelete.length });

    const newDeleted = new Set(deletedIds);

    for (let i = 0; i < toDelete.length; i++) {
      const item = toDelete[i];
      const targetPath = item.caminho_copia || `${item.copia}/${item.nome}`;
      setBatchProgress({ current: i + 1, total: toDelete.length });

      try {
        const success = await onMoveToTrash(targetPath, item.id);
        if (success) {
          newDeleted.add(item.id);
        }
      } catch (err) {
        console.error(`Falha ao excluir ${item.nome}:`, err);
      }
    }

    setDeletedIds(newDeleted);
    setSelectedBatchIds(new Set());
    setIsBatchDeleting(false);
    setBatchProgress(null);
  };

  const isAllVisibleSelected = filteredDuplicates.length > 0 &&
    filteredDuplicates.every(d => selectedBatchIds.has(d.id));

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl p-4 shadow-2xl flex flex-col h-full flex-1 overflow-hidden min-h-0 space-y-3">
      {/* Header and Actions Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-2.5 pb-2.5 border-b border-serato-cardBorder shrink-0">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Copy className="w-4 h-4 text-serato-orange" />
            <span>Auditoria Detalhada de Faixas Duplicadas</span>
            <span className="text-xs bg-serato-orange/15 text-serato-orange px-2 py-0.5 rounded-full border border-serato-orange/30 font-mono">
              {activeDuplicates.length} cópias redundantes
            </span>
            {deletedIds.size > 0 && (
              <span className="text-xs bg-emerald-950/60 text-emerald-400 px-2 py-0.5 rounded-full border border-emerald-700/40 font-mono flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" />
                {deletedIds.size} movidas para lixeira
              </span>
            )}
          </h3>
          <p className="text-[11px] text-serato-muted">
            Revise as faixas repetidas e exclua apenas as cópias para economizar espaço sem perder metadados do Serato.
          </p>
        </div>

        <div className="flex items-center space-x-2">
          {/* Botão de Exclusão em Lote */}
          {selectedBatchIds.size > 0 && (
            <button
              type="button"
              onClick={handleBatchTrash}
              disabled={isBatchDeleting}
              className="text-xs font-bold px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white shadow-lg shadow-rose-900/40 transition flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>
                {isBatchDeleting
                  ? `Excluindo (${batchProgress?.current}/${batchProgress?.total})...`
                  : `🗑️ Mover ${selectedBatchIds.size} para Lixeira`}
              </span>
            </button>
          )}

          {onExportCsv && (
            <button
              type="button"
              onClick={onExportCsv}
              className="text-xs font-semibold px-2.5 py-1.5 rounded-lg bg-serato-gold/10 hover:bg-serato-gold/20 text-serato-gold border border-serato-gold/30 transition flex items-center gap-1.5 cursor-pointer"
            >
              <FileSpreadsheet className="w-3.5 h-3.5" />
              <span>Exportar CSV (;)</span>
            </button>
          )}

          <button
            type="button"
            onClick={onOpenLogsFolder}
            className="text-xs font-semibold px-2.5 py-1.5 rounded-lg bg-serato-card hover:bg-slate-700 text-slate-200 border border-serato-cardBorder transition flex items-center gap-1.5 cursor-pointer"
          >
            <FolderOpen className="w-3.5 h-3.5 text-serato-cyan" />
            <span>Pasta de Logs</span>
          </button>
        </div>
      </div>

      {activeDuplicates.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-slate-500 space-y-2 select-none py-10">
          <Database className="w-10 h-10 mx-auto text-serato-muted/40" />
          <p className="text-sm font-medium text-slate-400">Nenhuma faixa duplicada na biblioteca.</p>
          <p className="text-xs text-slate-600">Sua coleção está limpa e organizada sem arquivos repetidos.</p>
        </div>
      ) : (
        <>
          {/* Summary & Top Folders Stats */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-2.5 shrink-0">
            <div className="bg-serato-card border border-serato-cardBorder p-2.5 rounded-lg flex flex-col justify-between">
              <span className="text-[10px] font-semibold text-serato-muted uppercase tracking-wider">Espaço a Liberar</span>
              <div className="text-lg font-bold text-serato-gold font-mono mt-0.5">
                {formatSize(totalBytes)}
              </div>
              <span className="text-[10px] text-serato-muted">Excluindo todas as cópias</span>
            </div>

            <div className="bg-serato-card border border-serato-cardBorder p-2.5 rounded-lg md:col-span-3 flex flex-col justify-between">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] font-semibold text-serato-muted uppercase flex items-center gap-1 tracking-wider">
                  <BarChart3 className="w-3 h-3 text-serato-cyan" />
                  Top Pastas com Duplicatas
                </span>
                <span className="text-[10px] text-serato-muted font-mono">{uniqueFolders.length} pastas afetadas</span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                {folderStats.map(([folder, count]) => (
                  <div key={folder} className="bg-black/30 p-1.5 rounded border border-white/5">
                    <div className="text-[10px] text-slate-300 truncate" title={folder}>{folder}</div>
                    <div className="text-xs font-mono font-bold text-serato-cyan">{count} cópias</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Filters & Batch Controls Bar */}
          <div className="flex flex-wrap items-center justify-between gap-2 shrink-0 bg-serato-card/60 p-2 rounded-lg border border-serato-cardBorder">
            <div className="flex items-center gap-2 flex-1 min-w-[280px]">
              <div className="relative flex-1">
                <Search className="w-3.5 h-3.5 text-serato-muted absolute left-2.5 top-2.5" />
                <input
                  type="text"
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  placeholder="Filtrar por nome de faixa, pasta de cópia ou pasta original..."
                  className="w-full pl-8 pr-3 py-1.5 text-xs bg-serato-card border border-serato-cardBorder rounded-lg text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-cyan transition font-sans"
                />
              </div>

              <select
                value={selectedFolderFilter}
                onChange={(e) => setSelectedFolderFilter(e.target.value)}
                className="bg-serato-card border border-serato-cardBorder rounded-lg px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-serato-cyan cursor-pointer"
              >
                <option value="all">Todas as Pastas ({activeDuplicates.length})</option>
                {uniqueFolders.map(folder => (
                  <option key={folder} value={folder}>{folder}</option>
                ))}
              </select>
            </div>

            {/* Ações Rápidas de Seleção */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleSelectCurrentFolder}
                className="text-xs px-2.5 py-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-300 border border-serato-cardBorder transition cursor-pointer"
              >
                Selecionar Todas ({filteredDuplicates.length})
              </button>
              {selectedBatchIds.size > 0 && (
                <button
                  type="button"
                  onClick={() => setSelectedBatchIds(new Set())}
                  className="text-xs px-2 py-1 text-slate-400 hover:text-white"
                >
                  Limpar Seleção
                </button>
              )}
            </div>
          </div>

          {/* Duplicates Full Table with Individual and Batch Actions */}
          <div className="flex-1 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20">
            <div className="overflow-y-auto flex-1">
              <table className="w-full text-left text-xs">
                <thead className="bg-serato-header text-serato-muted font-mono uppercase text-[10px] border-b border-serato-cardBorder sticky top-0 z-10">
                  <tr>
                    <th className="py-2 px-3 w-8 text-center">
                      <input
                        type="checkbox"
                        checked={isAllVisibleSelected}
                        onChange={toggleSelectAllVisible}
                        className="rounded border-slate-700 bg-serato-dark text-serato-orange focus:ring-0 cursor-pointer"
                        title="Selecionar todos os visíveis"
                      />
                    </th>
                    <th className="py-2 px-3">Faixa e Metadados</th>
                    <th className="py-2 px-3">Localização da Cópia (Redundante)</th>
                    <th className="py-2 px-3">Localização da Original (Preservar)</th>
                    <th className="py-2 px-3 text-right">Tamanho</th>
                    <th className="py-2 px-3 text-center">Ações</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-serato-cardBorder/50 font-mono text-[11px]">
                  {filteredDuplicates.map((item) => {
                    const copyPath = item.caminho_copia || `${item.copia}/${item.nome}`;
                    const isSelected = selectedBatchIds.has(item.id);

                    return (
                      <tr
                        key={item.id}
                        className={`hover:bg-serato-card/80 transition ${isSelected ? 'bg-orange-950/15' : ''}`}
                      >
                        {/* Checkbox de seleção */}
                        <td className="py-2 px-3 text-center">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelect(item.id)}
                            className="rounded border-slate-700 bg-serato-dark text-serato-orange focus:ring-0 cursor-pointer"
                          />
                        </td>

                        {/* Track Name */}
                        <td className="py-2 px-3 text-white font-sans font-medium">
                          <div className="flex items-center gap-1.5">
                            <span className="w-2 h-2 rounded-full bg-serato-orange shrink-0" />
                            <span className="truncate max-w-[220px] font-semibold text-slate-100" title={item.nome}>
                              {item.nome}
                            </span>
                          </div>
                        </td>

                        {/* Copy Location */}
                        <td className="py-2 px-3">
                          <div className="flex items-center space-x-1.5">
                            <span className="text-[10px] bg-amber-950/50 text-amber-300 px-1.5 py-0.2 rounded border border-amber-800/40 shrink-0 font-sans">
                              Cópia
                            </span>
                            <span className="text-slate-300 truncate max-w-[190px]" title={item.copia}>
                              {item.copia.split('/').slice(-2).join('/')}
                            </span>
                          </div>
                        </td>

                        {/* Original Location */}
                        <td className="py-2 px-3">
                          <div className="flex items-center space-x-1.5">
                            <span className="text-[10px] bg-emerald-950/50 text-emerald-300 px-1.5 py-0.2 rounded border border-emerald-800/40 shrink-0 font-sans">
                              Original
                            </span>
                            <span className="text-slate-400 truncate max-w-[190px]" title={item.original}>
                              {item.original.split('/').slice(-2).join('/')}
                            </span>
                          </div>
                        </td>

                        {/* Size */}
                        <td className="py-2 px-3 text-right text-serato-muted">
                          {formatSize(item.tamanho)}
                        </td>

                        {/* Actions */}
                        <td className="py-2 px-3">
                          <div className="flex items-center justify-center space-x-1.5">
                            {onOpenFileInFinder && (
                              <button
                                type="button"
                                onClick={() => onOpenFileInFinder(copyPath)}
                                className="p-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-300 hover:text-white border border-serato-cardBorder transition cursor-pointer"
                                title="Revelar arquivo de cópia no Finder"
                              >
                                <Eye className="w-3.5 h-3.5 text-serato-cyan" />
                              </button>
                            )}

                            {onMoveToTrash && (
                              <button
                                type="button"
                                onClick={() => handleTrashClick(item)}
                                disabled={isDeletingId === item.id || isBatchDeleting}
                                className="p-1 rounded bg-rose-950/30 hover:bg-rose-900/50 text-rose-300 border border-rose-800/40 transition disabled:opacity-40 cursor-pointer"
                                title="Mover cópia para a Lixeira do macOS"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Table Footer with Summary */}
            <div className="bg-serato-header px-3 py-1.5 border-t border-serato-cardBorder text-[11px] text-serato-muted flex items-center justify-between shrink-0">
              <div className="flex items-center gap-3">
                <span>Exibindo {filteredDuplicates.length} de {activeDuplicates.length} duplicatas</span>
                {selectedBatchIds.size > 0 && (
                  <span className="text-serato-orange font-bold font-mono">
                    ({selectedBatchIds.size} selecionadas para excluir)
                  </span>
                )}
              </div>
              {csvPath && (
                <span className="truncate max-w-[400px]">CSV: <code className="text-slate-300">{csvPath}</code></span>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
};
