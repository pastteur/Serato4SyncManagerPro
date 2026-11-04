import React, { useState, useEffect, useMemo } from 'react';
import { Shield, ShieldCheck, Sparkles, RefreshCw, AlertCircle, CheckCircle2, Search, ArrowRight, Music, Disc3, Folder, Trash2, Eye, CheckSquare, Square, Zap, RotateCcw, XCircle } from 'lucide-react';
import { ConfirmModal } from './ConfirmModal';

interface SoundSealProps {
  mp3Path: string;
  seratoPath: string;
  onAddLog: (message: string) => void;
  onOpenFileInFinder?: (filePath: string) => void;
  onMoveToTrash?: (filePath: string, itemId: string) => Promise<boolean>;
}

export const SoundSeal: React.FC<SoundSealProps> = ({
  mp3Path,
  seratoPath,
  onAddLog,
  onOpenFileInFinder,
  onMoveToTrash
}) => {
  const [activeSubTab, setActiveSubTab] = useState<'seal' | 'relocate'>('seal');
  const [status, setStatus] = useState<any>(null);
  const [isScanning, setIsScanning] = useState<boolean>(false);
  const [duplicatesBySound, setDuplicatesBySound] = useState<any[]>([]);
  const [relocateResults, setRelocateResults] = useState<any[]>([]);
  const [isScanningRelocate, setIsScanningRelocate] = useState<boolean>(false);

  // Seleção e Exclusão em Massa de Cópias por Som
  const [selectedCopyPaths, setSelectedCopyPaths] = useState<Set<string>>(new Set());
  const [isTrashingBatch, setIsTrashingBatch] = useState<boolean>(false);
  const [trashProgress, setTrashProgress] = useState<{
    current: number;
    total: number;
    fileName: string;
  } | null>(null);

  // Progresso em tempo real das varreduras de Sound Seal e Relocate
  const [sealScanProgress, setSealScanProgress] = useState<{
    processados: number;
    total: number;
    percentual: number;
    novos?: number;
    faixa?: string;
  } | null>(null);

  const [relocateScanProgress, setRelocateScanProgress] = useState<{
    processados: number;
    total: number;
    percentual: number;
    faixa?: string;
    etapa?: string;
  } | null>(null);

  // Seleção e Relocalização em Massa
  const [selectedRelinkItems, setSelectedRelinkItems] = useState<Map<string, { rel_path: string; source_path: string; nome: string }>>(new Map());
  const [selectedLostTracks, setSelectedLostTracks] = useState<Set<string>>(new Set());
  const [isRelinkingBatch, setIsRelinkingBatch] = useState<boolean>(false);
  const [relinkProgress, setRelinkProgress] = useState<{
    processados: number;
    total: number;
    percentual: number;
    atualizados: number;
    faixa_atual: string;
  } | null>(null);

  // Remover faixas perdidas das crates do Serato
  const [isRemovingLost, setIsRemovingLost] = useState<boolean>(false);
  const [removeLostResult, setRemoveLostResult] = useState<any>(null);

  // Modal de Confirmação em Tela (sem popups nativos que travam)
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

  // Filtros de Busca e Status para Sound Seal e Relocate
  const [sealSearch, setSealSearch] = useState<string>('');
  const [sealFilter, setSealFilter] = useState<'all' | 'selected' | 'moreThan2'>('all');
  const [relocateSearch, setRelocateSearch] = useState<string>('');
  const [relocateFilter, setRelocateFilter] = useState<'all' | 'withCandidate' | 'noCandidate'>('all');

  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);

  // Carrega status ao iniciar
  const loadStatus = async () => {
    if (!isTauri) return;
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const res = await invoke<string>('get_sound_seal_status');
      if (res && res.trim()) {
        try {
          const parsed = JSON.parse(res);
          setStatus(parsed);
        } catch (err) {
          console.error('JSON inválido em loadStatus:', res);
        }
      }
    } catch (e) {
      console.error('Falha ao carregar status do Sound Seal:', e);
    }
  };

  const loadDuplicatesBySound = async (preserveSelection: boolean = false) => {
    if (!isTauri) return;
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const res = await invoke<string>('get_sound_seal_duplicates');
      if (res && res.trim()) {
        try {
          const parsed = JSON.parse(res);
          if (parsed && parsed.sucesso) {
            const groups = parsed.duplicados_som || [];
            setDuplicatesBySound(groups);

            if (!preserveSelection) {
              // Pré-seleciona todas as cópias redundantes apenas na primeira carga geral
              const initialSelected = new Set<string>();
              groups.forEach((g: any) => {
                (g.faixas || []).slice(1).forEach((f: any) => {
                  initialSelected.add(f.caminho);
                });
              });
              setSelectedCopyPaths(initialSelected);
            } else {
              // Preserva rigorosamente as escolhas manuais que o usuário já fez (sem remarcar tudo)
              setSelectedCopyPaths(prev => {
                const validPaths = new Set<string>();
                const allAvailableCopies = new Set<string>();
                groups.forEach((g: any) => {
                  (g.faixas || []).slice(1).forEach((f: any) => allAvailableCopies.add(f.caminho));
                });
                prev.forEach(p => {
                  if (allAvailableCopies.has(p)) validPaths.add(p);
                });
                return validPaths;
              });
            }
          }
        } catch (err) {
          console.error('JSON inválido em loadDuplicatesBySound:', res);
        }
      }
    } catch (e) {
      console.error('Falha ao carregar duplicatas por som:', e);
    }
  };

  useEffect(() => {
    loadStatus();
    loadDuplicatesBySound();
  }, []);

  // Listener para batch relink e varreduras em tempo real
  useEffect(() => {
    let unlistenProgress: (() => void) | undefined;
    let unlistenFinished: (() => void) | undefined;
    let unlistenSealScan: (() => void) | undefined;
    let unlistenRelocateScan: (() => void) | undefined;

    const setupListeners = async () => {
      if (isTauri) {
        const { listen } = await import('@tauri-apps/api/event');
        unlistenSealScan = await listen<any>('sound-seal-scan-progress', (event) => {
          setSealScanProgress(event.payload);
        });

        unlistenRelocateScan = await listen<any>('relocate-scan-progress', (event) => {
          setRelocateScanProgress(event.payload);
        });

        unlistenProgress = await listen<any>('sound-seal-relink-progress', (event) => {
          const payload = event.payload;
          setRelinkProgress({
            processados: payload.processados || 0,
            total: payload.total || 0,
            percentual: payload.percentual || 0,
            atualizados: payload.atualizados || 0,
            faixa_atual: payload.faixa_atual || '',
          });
        });

        unlistenFinished = await listen<any>('sound-seal-relink-finished', (event) => {
          const payload = event.payload;
          setIsRelinkingBatch(false);
          setRelinkProgress(null);
          if (payload.sucesso) {
            onAddLog(`🎉 Relocalização concluída! ${payload.atualizados} faixas religadas com sucesso ao Serato.`);
            handleScanRelocate();
          } else {
            onAddLog(`❌ Erro no lote de relocalização: ${payload.erro || 'Desconhecido'}`);
          }
        });
      }
    };

    setupListeners();
    return () => {
      if (unlistenSealScan) unlistenSealScan();
      if (unlistenRelocateScan) unlistenRelocateScan();
      if (unlistenProgress) unlistenProgress();
      if (unlistenFinished) unlistenFinished();
    };
  }, []);

  // Listas filtradas com busca e status em tempo real
  const filteredDuplicatesBySound = useMemo(() => {
    let result = [...duplicatesBySound];
    if (sealSearch.trim()) {
      const q = sealSearch.toLowerCase();
      result = result.filter(g =>
        g.seal?.toLowerCase().includes(q) ||
        (g.faixas || []).some((f: any) => f.caminho?.toLowerCase().includes(q) || f.nome?.toLowerCase().includes(q))
      );
    }
    if (sealFilter === 'selected') {
      result = result.filter(g =>
        (g.faixas || []).some((f: any) => selectedCopyPaths.has(f.caminho))
      );
    } else if (sealFilter === 'moreThan2') {
      result = result.filter(g => g.total_copias > 2);
    }
    return result;
  }, [duplicatesBySound, sealSearch, sealFilter, selectedCopyPaths]);

  const filteredRelocateResults = useMemo(() => {
    let result = [...relocateResults];
    if (relocateSearch.trim()) {
      const q = relocateSearch.toLowerCase();
      result = result.filter(r =>
        r.faixa_perdida?.toLowerCase().includes(q) ||
        (r.candidatos || []).some((c: any) => c.nome?.toLowerCase().includes(q) || c.caminho?.toLowerCase().includes(q))
      );
    }
    if (relocateFilter === 'withCandidate') {
      result = result.filter(r => r.candidatos && r.candidatos.length > 0);
    } else if (relocateFilter === 'noCandidate') {
      result = result.filter(r => !r.candidatos || r.candidatos.length === 0);
    }
    return result;
  }, [relocateResults, relocateSearch, relocateFilter]);

  // Iniciar varredura do Sound Seal
  const handleStartSealScan = async () => {
    if (!mp3Path) {
      onAddLog('⚠️ Selecione a pasta MP3 antes de iniciar.');
      return;
    }
    setIsScanning(true);
    setSealScanProgress(null);
    onAddLog(`🧬 Sound Seal: Extraindo assinaturas acústicas SHA-256 em ${mp3Path}...`);

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const res = await invoke<string>('scan_sound_seals', {
          mp3Path,
          batch: 0
        });
        if (!res || !res.trim()) throw new Error('O motor retornou resposta vazia.');
        let parsed: any;
        try {
          parsed = JSON.parse(res);
        } catch (jsonErr) {
          throw new Error(`Resposta JSON inválida do motor: ${res.slice(0, 150)}`);
        }
        setStatus(parsed);
        loadDuplicatesBySound(true);
        const totalSel = parsed.total_selados ?? parsed.total_processados ?? 0;
        onAddLog(`✅ Sound Seal: Varredura concluída. ${Number(totalSel).toLocaleString()} faixas seladas com sucesso.`);
      }
    } catch (e) {
      onAddLog(`❌ Erro no Sound Seal: ${e}`);
    } finally {
      setIsScanning(false);
      setSealScanProgress(null);
    }
  };

  // Scanner de Relocate de Músicas Perdidas
  const handleScanRelocate = async () => {
    if (!seratoPath || !mp3Path) {
      onAddLog('⚠️ Selecione as pastas MP3 e Serato antes de iniciar o Relocate.');
      return;
    }
    setIsScanningRelocate(true);
    setRelocateScanProgress(null);
    onAddLog(`🔍 Relocate: Rastreador de faixas perdidas ativado...`);

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const res = await invoke<string>('scan_missing_relocate', {
          mp3Path,
          seratoPath
        });
        if (!res || !res.trim()) throw new Error('O motor retornou resposta vazia.');
        let parsed: any;
        try {
          parsed = JSON.parse(res);
        } catch (jsonErr) {
          throw new Error(`Resposta JSON inválida do motor: ${res.slice(0, 150)}`);
        }
        if (parsed.sucesso) {
          const items = parsed.analisadas || [];
          setRelocateResults(items);

          // Pré-seleciona correspondências com 100% de confiança ou encontradas no Lixo
          const relinkMap = new Map<string, { rel_path: string; source_path: string; nome: string }>();
          items.forEach((it: any) => {
            if (it.in_trash && it.trash_path) {
              relinkMap.set(it.faixa_perdida, {
                rel_path: it.faixa_perdida,
                source_path: it.trash_path,
                nome: it.nome
              });
            } else if (it.candidatos && it.candidatos.length > 0 && it.candidatos[0].score >= 87) {
              relinkMap.set(it.faixa_perdida, {
                rel_path: it.faixa_perdida,
                source_path: it.candidatos[0].caminho,
                nome: it.nome
              });
            }
          });
          setSelectedRelinkItems(relinkMap);
          onAddLog(`✅ Relocate: ${parsed.total_perdidas} faixas ausentes verificadas (${relinkMap.size} com correspondência confirmada).`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Erro no Relocate: ${e}`);
    } finally {
      setIsScanningRelocate(false);
      setRelocateScanProgress(null);
    }
  };

  // Total de cópias redundantes (excluindo os originais de referência)
  const allCopyPaths: string[] = [];
  duplicatesBySound.forEach(g => {
    (g.faixas || []).slice(1).forEach((f: any) => allCopyPaths.push(f.caminho));
  });

  // Toggle de seleção de uma cópia
  const toggleSelectCopy = (path: string) => {
    setSelectedCopyPaths(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  // Selecionar todas as cópias redundantes
  const handleSelectAllCopies = () => {
    setSelectedCopyPaths(new Set(allCopyPaths));
  };

  // Desmarcar todas as cópias
  const handleDeselectAllCopies = () => {
    setSelectedCopyPaths(new Set());
  };

  // Redefinir manualmente qual arquivo é a Referência Protegida (Master) de um grupo
  const handleSetMaster = async (seal: string, filepath: string, nome: string, crate: string) => {
    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        await invoke('set_sound_seal_master', {
          audioSeal: seal,
          filepath
        });
      }

      // Atualiza o estado em memória instantaneamente sem recarregar a tela
      setDuplicatesBySound(prev => prev.map(g => {
        if (g.seal !== seal) return g;
        const faixas = [...(g.faixas || [])];
        const targetIdx = faixas.findIndex((f: any) => f.caminho === filepath);
        if (targetIdx === -1) return g;

        // Move o novo master para a posição 0 e atualiza is_master
        const [targetTrack] = faixas.splice(targetIdx, 1);
        const updatedTarget = { ...targetTrack, is_master: true };
        const updatedOthers = faixas.map((f: any) => ({ ...f, is_master: false }));
        return {
          ...g,
          faixas: [updatedTarget, ...updatedOthers]
        };
      }));

      // Desmarca o novo arquivo protegido de qualquer exclusão pendente
      setSelectedCopyPaths(prev => {
        const next = new Set(prev);
        next.delete(filepath);
        return next;
      });

      onAddLog(`🛡️ Sound Seal: Arquivo protegido redefinido com sucesso!`);
      onAddLog(`📍 Pasta protegida: ${crate} -> ${nome}`);
    } catch (e) {
      onAddLog(`❌ Erro ao definir arquivo protegido: ${e}`);
    }
  };

  // Marcar todas as cópias de um bloco específico
  const handleSelectGroupCopies = (group: any) => {
    setSelectedCopyPaths(prev => {
      const next = new Set(prev);
      (group.faixas || []).slice(1).forEach((f: any) => next.add(f.caminho));
      return next;
    });
  };

  // Desmarcar todas as cópias de um bloco específico
  const handleDeselectGroupCopies = (group: any) => {
    setSelectedCopyPaths(prev => {
      const next = new Set(prev);
      (group.faixas || []).forEach((f: any) => next.delete(f.caminho));
      return next;
    });
  };

  // Excluir cópias selecionadas apenas deste bloco específico
  const handleTrashGroupCopies = (group: any) => {
    if (!onMoveToTrash) return;
    const groupCopiesToTrash = (group.faixas || []).slice(1).filter((f: any) => selectedCopyPaths.has(f.caminho));
    if (groupCopiesToTrash.length === 0) {
      onAddLog('⚠️ Nenhuma cópia marcada para exclusão neste bloco.');
      return;
    }

    setModalConfig({
      isOpen: true,
      title: 'Excluir Cópias Deste Bloco',
      message: `Deseja mover as ${groupCopiesToTrash.length} cópia(s) marcada(s) deste bloco para a Lixeira do Mac?\n\n🔒 O arquivo protegido permanecerá 100% preservado nesta pasta.\n\nDemais blocos da biblioteca NÃO serão afetados.`,
      confirmText: `Mover ${groupCopiesToTrash.length} cópia(s)`,
      variant: 'danger',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        onAddLog(`🗑️ Sound Seal: Movendo ${groupCopiesToTrash.length} cópia(s) do bloco para a Lixeira...`);
        let deleted = 0;
        const toDeletePaths = new Set<string>(groupCopiesToTrash.map((f: any) => String(f.caminho)));

        for (const f of groupCopiesToTrash) {
          const ok = await onMoveToTrash(f.caminho, f.caminho);
          if (ok) deleted++;
        }

        // Remove referências perdidas das crates do Serato
        if (isTauri && seratoPath && mp3Path) {
          try {
            const { invoke } = await import('@tauri-apps/api/core');
            await invoke('remove_lost_tracks', {
              mp3Path,
              seratoPath,
              targetPath: null,
              targetPaths: JSON.stringify(Array.from(toDeletePaths))
            });
          } catch (e) {
            console.error('Falha ao purgar referências de crates:', e);
          }
        }

        // Atualização instantânea em memória apenas deste bloco
        setDuplicatesBySound(prev => prev.map(g => {
          if (g.seal !== group.seal) return g;
          const remaining = (g.faixas || []).filter((f: any) => !toDeletePaths.has(f.caminho));
          return {
            ...g,
            faixas: remaining,
            total_copias: remaining.length
          };
        }).filter(g => (g.total_copias || 0) >= 2));

        setSelectedCopyPaths(prev => {
          const next = new Set(prev);
          toDeletePaths.forEach(p => next.delete(p));
          return next;
        });

        loadStatus();
        onAddLog(`✅ Concluído: ${deleted} cópias do bloco removidas com sucesso.`);
      }
    });
  };

  // Exclusão individual de uma cópia
  const handleTrashSingleCopy = (caminho: string, nome: string) => {
    if (!onMoveToTrash) return;
    setModalConfig({
      isOpen: true,
      title: 'Mover Cópia para a Lixeira',
      message: `Deseja mover esta cópia para a Lixeira do Mac?\n\nFaixa: ${nome}\n\nA faixa de referência original será 100% PRESERVADA.`,
      confirmText: 'Mover para Lixeira',
      variant: 'danger',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        const ok = await onMoveToTrash(caminho, caminho);
        if (ok) {
          setDuplicatesBySound(prev => prev.map(g => ({
            ...g,
            faixas: g.faixas.filter((f: any) => f.caminho !== caminho),
            total_copias: g.faixas.filter((f: any) => f.caminho !== caminho).length
          })).filter(g => g.faixas.length > 1));

          setSelectedCopyPaths(prev => {
            const next = new Set(prev);
            next.delete(caminho);
            return next;
          });
          loadStatus();
        }
      }
    });
  };

  // Exclusão em Massa de todas as cópias selecionadas
  const handleBatchTrashCopies = () => {
    if (!onMoveToTrash) return;
    if (selectedCopyPaths.size === 0) {
      setModalConfig({
        isOpen: true,
        title: 'Nenhuma Cópia Selecionada',
        message: 'Por favor, selecione ao menos uma cópia redundante para mover para a Lixeira.',
        confirmText: 'OK',
        variant: 'info',
        onConfirm: () => setModalConfig(prev => ({ ...prev, isOpen: false }))
      });
      return;
    }

    const count = selectedCopyPaths.size;
    setModalConfig({
      isOpen: true,
      title: 'Mover Cópias Redundantes para Lixeira',
      message: `Deseja mover as ${count} cópias redundantes selecionadas para a Lixeira do Mac?\n\n🔒 As faixas de referência (originais) serão 100% PRESERVADAS.\n\nEsta ação liberará espaço no disco mantendo a melhor cópia de cada áudio.`,
      confirmText: `Sim, Mover ${count} Cópias`,
      variant: 'danger',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsTrashingBatch(true);
        setTrashProgress({ current: 0, total: count, fileName: 'Iniciando...' });
        onAddLog(`🗑️ Sound Seal: Movendo ${count} cópias redundantes para a Lixeira...`);

        let trashedCount = 0;
        const toTrash = Array.from(selectedCopyPaths);

        for (let i = 0; i < toTrash.length; i++) {
          const p = toTrash[i];
          const name = p.split('/').pop() || '';
          setTrashProgress({ current: i + 1, total: count, fileName: name });

          const ok = await onMoveToTrash(p, p);
          if (ok) trashedCount++;
        }

        // Purgar referências das crates e database V2 do Serato para não virarem faixas perdidas
        if (isTauri && toTrash.length > 0) {
          try {
            const { invoke } = await import('@tauri-apps/api/core');
            await invoke('remove_lost_tracks', {
              mp3Path,
              seratoPath,
              targetPath: null,
              targetPaths: JSON.stringify(toTrash)
            });
          } catch (e) {
            console.error('Falha ao purgar referências de crates:', e);
          }
        }

        // Atualização instantânea da interface em memória
        const trashedSet = new Set(toTrash);
        setDuplicatesBySound(prev => prev.map(g => ({
          ...g,
          faixas: (g.faixas || []).filter((f: any) => !trashedSet.has(f.caminho)),
          total_copias: (g.faixas || []).filter((f: any) => !trashedSet.has(f.caminho)).length
        })).filter(g => (g.total_copias || 0) >= 2));

        setIsTrashingBatch(false);
        setTrashProgress(null);
        onAddLog(`✅ Concluído: ${trashedCount} cópias redundantes movidas para a Lixeira e removidas do Serato.`);
        setSelectedCopyPaths(new Set());
        loadDuplicatesBySound(true);
        loadStatus();
      }
    });
  };

  // Exclusão de todas as faixas atualmente visíveis na tabela do Relocate
  const handleRemoveTableLostTracks = () => {
    if (!seratoPath || !mp3Path) {
      onAddLog('⚠️ Selecione as pastas MP3 e Serato antes de remover faixas perdidas.');
      return;
    }
    const count = filteredRelocateResults.length;
    if (count === 0) {
      onAddLog('ℹ️ Nenhuma faixa na tabela para excluir.');
      return;
    }

    setModalConfig({
      isOpen: true,
      title: '🗑️ Excluir Toda a Tabela do Relocate',
      message: `Deseja remover do Serato todas as ${count} faixas perdidas exibidas na tabela atual?\n\n⚠️ Esta ação eliminará essas referências de todas as crates e da biblioteca central (database V2).\n\nBackups de segurança (.bak) serão criados automaticamente.`,
      confirmText: `Excluir Toda a Tabela (${count})`,
      variant: 'danger',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsRemovingLost(true);
        onAddLog(`🗑️ Excluindo ${count} faixas da tabela do Serato...`);
        try {
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            const pathsList = filteredRelocateResults.map((it: any) => it.faixa_perdida);
            const resJson = await invoke<string>('remove_lost_tracks', {
              mp3Path,
              seratoPath,
              targetPath: null,
              targetPaths: JSON.stringify(pathsList)
            });
            const data = JSON.parse(resJson);
            if (data.sucesso) {
              onAddLog(`✅ Concluído! ${data.total_removidas} referência(s) da tabela excluída(s) do Serato.`);
              const removedSet = new Set(pathsList);
              setRelocateResults(prev => prev.filter(r => !removedSet.has(r.faixa_perdida)));
              setSelectedLostTracks(prev => {
                const next = new Set(prev);
                pathsList.forEach(p => next.delete(p));
                return next;
              });
              setSelectedRelinkItems(prev => {
                const next = new Map(prev);
                pathsList.forEach(p => next.delete(p));
                return next;
              });
            } else {
              onAddLog(`❌ Erro: ${data.erro || 'Desconhecido'}`);
            }
          }
        } catch (e) {
          onAddLog(`❌ Falha: ${e}`);
        } finally {
          setIsRemovingLost(false);
        }
      }
    });
  };

  // Exclusão das faixas marcadas com checkbox no Relocate
  const handleRemoveSelectedLostTracks = () => {
    if (!seratoPath || !mp3Path) {
      onAddLog('⚠️ Selecione as pastas MP3 e Serato antes de remover faixas perdidas.');
      return;
    }
    const count = selectedLostTracks.size;
    if (count === 0) {
      setModalConfig({
        isOpen: true,
        title: 'Nenhuma Faixa Selecionada',
        message: 'Por favor, selecione ao menos uma faixa na tabela para excluir.',
        confirmText: 'OK',
        variant: 'info',
        onConfirm: () => setModalConfig(prev => ({ ...prev, isOpen: false }))
      });
      return;
    }

    setModalConfig({
      isOpen: true,
      title: '🗑️ Excluir Faixas Selecionadas do Serato',
      message: `Deseja remover as ${count} faixas selecionadas de todas as crates e do banco central (database V2) do Serato?\n\nBackups de segurança (.bak) serão criados automaticamente.`,
      confirmText: `Excluir ${count} Faixa(s)`,
      variant: 'danger',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsRemovingLost(true);
        onAddLog(`🗑️ Excluindo ${count} faixas selecionadas do Serato...`);
        try {
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            const pathsList = Array.from(selectedLostTracks);
            const resJson = await invoke<string>('remove_lost_tracks', {
              mp3Path,
              seratoPath,
              targetPath: null,
              targetPaths: JSON.stringify(pathsList)
            });
            const data = JSON.parse(resJson);
            if (data.sucesso) {
              onAddLog(`✅ Concluído! ${data.total_removidas} referência(s) excluída(s) do Serato.`);
              const removedSet = new Set(pathsList);
              setRelocateResults(prev => prev.filter(r => !removedSet.has(r.faixa_perdida)));
              setSelectedLostTracks(new Set());
              setSelectedRelinkItems(prev => {
                const next = new Map(prev);
                pathsList.forEach(p => next.delete(p));
                return next;
              });
            } else {
              onAddLog(`❌ Erro: ${data.erro || 'Desconhecido'}`);
            }
          }
        } catch (e) {
          onAddLog(`❌ Falha: ${e}`);
        } finally {
          setIsRemovingLost(false);
        }
      }
    });
  };

  // Seleção rápida da tabela do Relocate
  const handleSelectAllRelocate = () => {
    setSelectedLostTracks(new Set(filteredRelocateResults.map(it => it.faixa_perdida)));
    const relinkMap = new Map(selectedRelinkItems);
    filteredRelocateResults.forEach(it => {
      const best = it.candidatos && it.candidatos.length > 0 ? it.candidatos[0] : null;
      if (it.in_trash && it.trash_path) {
        relinkMap.set(it.faixa_perdida, { rel_path: it.faixa_perdida, source_path: it.trash_path, nome: it.nome });
      } else if (best) {
        relinkMap.set(it.faixa_perdida, { rel_path: it.faixa_perdida, source_path: best.caminho, nome: it.nome });
      }
    });
    setSelectedRelinkItems(relinkMap);
  };

  const handleDeselectAllRelocate = () => {
    setSelectedLostTracks(new Set());
    setSelectedRelinkItems(new Map());
  };

  // Exclusão individual de uma referência perdida
  const handleRemoveSingleLostTrack = (relPath: string, nome: string) => {
    if (!seratoPath || !mp3Path) {
      onAddLog('⚠️ Selecione as pastas MP3 e Serato antes de remover faixas perdidas.');
      return;
    }

    setModalConfig({
      isOpen: true,
      title: '🗑️ Excluir Evidência do Serato',
      message: `Deseja remover a referência perdida desta faixa do Serato?\n\nFaixa: ${nome}\nCaminho: ${relPath}\n\n⚠️ Esta linha será excluída de todas as crates e da biblioteca central (database V2). Backups de segurança (.bak) serão criados automaticamente.`,
      confirmText: 'Excluir do Serato',
      variant: 'danger',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        onAddLog(`🗑️ Removendo referência de "${nome}" do Serato...`);
        try {
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            const resJson = await invoke<string>('remove_lost_tracks', {
              mp3Path,
              seratoPath,
              targetPath: relPath,
              targetPaths: null
            });
            const data = JSON.parse(resJson);
            if (data.sucesso) {
              onAddLog(`✅ Evidência removida com sucesso! ${data.total_removidas} referência(s) excluída(s) do Serato.`);
              setRelocateResults(prev => prev.filter(r => r.faixa_perdida !== relPath));
              setSelectedRelinkItems(prev => {
                const next = new Map(prev);
                next.delete(relPath);
                return next;
              });
            } else {
              onAddLog(`❌ Erro ao remover evidência: ${data.erro || 'Desconhecido'}`);
            }
          }
        } catch (e) {
          onAddLog(`❌ Falha ao excluir faixa: ${e}`);
        }
      }
    });
  };

  // Exclusão em lote de todas as faixas sem correspondência no HD
  const handleRemoveNoCandidateLostTracks = () => {
    if (!seratoPath || !mp3Path) {
      onAddLog('⚠️ Selecione as pastas MP3 e Serato antes de remover faixas perdidas.');
      return;
    }

    const noCandidates = relocateResults.filter(it => !it.candidatos || it.candidatos.length === 0);
    if (noCandidates.length === 0) {
      onAddLog('ℹ️ Nenhuma faixa sem correspondência encontrada para remover.');
      return;
    }

    const count = noCandidates.length;
    setModalConfig({
      isOpen: true,
      title: '🗑️ Excluir Faixas Sem Correspondência',
      message: `Deseja remover as ${count} faixas perdidas sem nenhum arquivo correspondente no HD?\n\n⚠️ Esta ação eliminará essas referências das crates e da biblioteca central (database V2), limpando os "fantasmas" que não tocam no Serato.\n\nBackups (.bak) serão criados automaticamente.`,
      confirmText: `Excluir ${count} Faixas Fantasmas`,
      variant: 'danger',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsRemovingLost(true);
        onAddLog(`🗑️ Excluindo ${count} faixas sem correspondência do Serato...`);
        try {
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            const pathsList = noCandidates.map(it => it.faixa_perdida);
            const resJson = await invoke<string>('remove_lost_tracks', {
              mp3Path,
              seratoPath,
              targetPath: null,
              targetPaths: JSON.stringify(pathsList)
            });
            const data = JSON.parse(resJson);
            if (data.sucesso) {
              onAddLog(`✅ Concluído! ${data.total_removidas} referências fantasmas removidas do Serato.`);
              const removedSet = new Set(pathsList);
              setRelocateResults(prev => prev.filter(r => !removedSet.has(r.faixa_perdida)));
              setSelectedRelinkItems(prev => {
                const next = new Map(prev);
                pathsList.forEach(p => next.delete(p));
                return next;
              });
            } else {
              onAddLog(`❌ Erro: ${data.erro || 'Desconhecido'}`);
            }
          }
        } catch (e) {
          onAddLog(`❌ Falha: ${e}`);
        } finally {
          setIsRemovingLost(false);
        }
      }
    });
  };

  // Remover todas as faixas perdidas de todas as crates e do banco do Serato
  const handleRemoveLostTracks = () => {
    if (!seratoPath || !mp3Path) {
      onAddLog('⚠️ Selecione as pastas MP3 e Serato antes de remover faixas perdidas.');
      return;
    }
    const totalLost = relocateResults.length;
    setModalConfig({
      isOpen: true,
      title: '🗑️ Remover Todas as Faixas Perdidas do Serato',
      message: `Deseja remover todas as ${totalLost} faixas perdidas das crates e da biblioteca central (database V2) do Serato?\n\n⚠️ Esta ação reescreve os arquivos eliminando referências a arquivos inexistentes.\n\nBackups .bak serão criados automaticamente. Reinicie o Serato DJ após a operação.`,
      confirmText: `Remover ${totalLost} Referências Perdidas`,
      variant: 'danger',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsRemovingLost(true);
        setRemoveLostResult(null);
        onAddLog(`🗑️ Removendo ${totalLost} faixas perdidas de todas as crates e da biblioteca do Serato...`);
        try {
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            const resJson = await invoke<string>('remove_lost_tracks', {
              mp3Path,
              seratoPath,
              targetPath: null,
              targetPaths: null
            });
            const data = JSON.parse(resJson);
            setRemoveLostResult(data);
            if (data.sucesso) {
              onAddLog(`✅ Concluído! ${data.total_removidas} entradas removidas (${data.crates_removidas || 0} em crates, ${data.database_v2_removidas || 0} na database V2). Reinicie o Serato DJ para ver as mudanças.`);
              handleScanRelocate();
            } else {
              onAddLog(`❌ Erro: ${data.erro || 'Desconhecido'}`);
            }
          }
        } catch (e) {
          onAddLog(`❌ Falha ao remover faixas: ${e}`);
        } finally {
          setIsRemovingLost(false);
        }
      }
    });
  };

  // Religar faixa individual
  const handleRelinkSingle = async (relPath: string, sourcePath: string, nome: string) => {
    onAddLog(`⚡ Relocate: Religando ${nome} ao Serato...`);
    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('relink_track', {
          mp3Path,
          relPath,
          sourcePath
        });
        const data = JSON.parse(resJson);
        if (data.sucesso) {
          onAddLog(`✅ ${data.mensagem}`);
          setRelocateResults(prev => prev.filter(r => r.faixa_perdida !== relPath));
          setSelectedRelinkItems(prev => {
            const next = new Map(prev);
            next.delete(relPath);
            return next;
          });
        } else {
          onAddLog(`❌ Erro ao religar: ${data.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Falha: ${e}`);
    }
  };

  // Religar todas as faixas selecionadas em massa
  const handleBatchRelink = () => {
    if (selectedRelinkItems.size === 0) {
      setModalConfig({
        isOpen: true,
        title: 'Nenhuma Correspondência',
        message: 'Nenhuma correspondência selecionada para relocalizar.',
        confirmText: 'OK',
        variant: 'info',
        onConfirm: () => setModalConfig(prev => ({ ...prev, isOpen: false }))
      });
      return;
    }

    const count = selectedRelinkItems.size;
    setModalConfig({
      isOpen: true,
      title: 'Religar Faixas ao Serato',
      message: `Deseja religar automaticamente as ${count} faixas perdidas selecionadas ao Serato?\n\nOs arquivos encontrados serão restaurados aos seus locais esperados para tocar imediatamente.`,
      confirmText: `Religar ${count} Faixas`,
      variant: 'info',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsRelinkingBatch(true);
        setRelinkProgress({
          processados: 0,
          total: count,
          percentual: 0,
          atualizados: 0,
          faixa_atual: 'Iniciando relocalização...'
        });

        onAddLog(`⚡ Disparando relocalização em massa de ${count} faixas perdidas...`);

        try {
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            const items = Array.from(selectedRelinkItems.values());
            await invoke('batch_relink_tracks', {
              mp3Path,
              itemsJson: JSON.stringify(items)
            });
          }
        } catch (e) {
          setIsRelinkingBatch(false);
          setRelinkProgress(null);
          onAddLog(`❌ Erro ao disparar relocalização em lote: ${e}`);
        }
      }
    });
  };

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl p-4 shadow-2xl flex flex-col h-full flex-1 overflow-hidden min-h-0 space-y-3 relative">
      
      {/* Sub-Tabs Switcher & Ações */}
      <div className="flex flex-wrap items-center justify-between pb-2 border-b border-serato-cardBorder shrink-0 gap-2">
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

        {/* Botões do Topo Conforme Sub-Aba Ativa */}
        <div className="flex items-center gap-2 flex-wrap">
          {activeSubTab === 'seal' ? (
            <>
              {/* Botão de Ação em Massa: Mover Cópias para Lixeira */}
              <button
                type="button"
                onClick={handleBatchTrashCopies}
                disabled={isScanning || isTrashingBatch || selectedCopyPaths.size === 0}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold bg-rose-900/60 hover:bg-rose-800 text-rose-200 border border-rose-700/50 shadow-lg shadow-rose-950/40 transition disabled:opacity-30 cursor-pointer"
                title="Move todas as cópias redundantes selecionadas para a Lixeira, mantendo a referência protegida"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>{isTrashingBatch ? 'Movendo...' : `🗑️ Mover Cópias para Lixeira (${selectedCopyPaths.size})`}</span>
              </button>

              <button
                type="button"
                onClick={handleStartSealScan}
                disabled={isScanning || isTrashingBatch}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold bg-serato-cyan hover:bg-cyan-300 text-black shadow-lg shadow-serato-cyan/20 transition disabled:opacity-40 cursor-pointer"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isScanning ? 'animate-spin' : ''}`} />
                <span>{isScanning ? 'Ouvindo faixas...' : '🧬 Iniciar Sound Seal'}</span>
              </button>
            </>
          ) : (
            <>
              {/* Botão de Ação em Massa: Religar Todas as Músicas */}
              <button
                type="button"
                onClick={handleBatchRelink}
                disabled={isScanningRelocate || isRelinkingBatch || selectedRelinkItems.size === 0}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold bg-gradient-to-r from-serato-cyan to-blue-500 hover:opacity-90 text-black shadow-lg shadow-serato-cyan/20 transition disabled:opacity-30 cursor-pointer"
                title="Restaura e religa todas as faixas encontradas com alta precisão"
              >
                <Zap className={`w-3.5 h-3.5 ${isRelinkingBatch ? 'animate-bounce' : ''}`} />
                <span>{isRelinkingBatch ? 'Religando...' : `⚡ Religar Selecionadas (${selectedRelinkItems.size})`}</span>
              </button>

              <button
                type="button"
                onClick={handleScanRelocate}
                disabled={isScanningRelocate || isRelinkingBatch}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold bg-serato-orange hover:bg-amber-400 text-black shadow-lg shadow-serato-orange/20 transition disabled:opacity-40 cursor-pointer"
              >
                <Search className={`w-3.5 h-3.5 ${isScanningRelocate ? 'animate-spin' : ''}`} />
                <span>{isScanningRelocate ? 'Procurando...' : '🔍 Rastrear Músicas Perdidas'}</span>
              </button>

              {relocateResults.length > 0 && (
                <>
                  {relocateResults.some(it => !it.candidatos || it.candidatos.length === 0) && (
                    <button
                      type="button"
                      onClick={handleRemoveNoCandidateLostTracks}
                      disabled={isScanningRelocate || isRelinkingBatch || isRemovingLost}
                      className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold bg-amber-950/80 hover:bg-amber-900 text-amber-200 border border-amber-700/60 shadow-lg shadow-amber-950/40 transition disabled:opacity-30 cursor-pointer"
                      title="Exclui apenas as faixas perdidas que não possuem nenhum arquivo correspondente no HD"
                    >
                      <Trash2 className="w-3.5 h-3.5 text-amber-400" />
                      <span>{`🗑️ Excluir Sem Correspondência (${relocateResults.filter(it => !it.candidatos || it.candidatos.length === 0).length})`}</span>
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={handleRemoveLostTracks}
                    disabled={isScanningRelocate || isRelinkingBatch || isRemovingLost}
                    className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold bg-rose-900/70 hover:bg-rose-800 text-rose-200 border border-rose-700/50 shadow-lg shadow-rose-950/40 transition disabled:opacity-30 cursor-pointer"
                    title="Remove entradas inexistentes de todas as crates e da biblioteca central do Serato (backup automático)"
                  >
                    <XCircle className={`w-3.5 h-3.5 ${isRemovingLost ? 'animate-spin' : ''}`} />
                    <span>{isRemovingLost ? 'Excluindo do Serato...' : `🗑️ Excluir Todas Perdidas (${relocateResults.length})`}</span>
                  </button>
                </>
              )}
            </>
          )}
        </div>
      </div>

      {/* Barra de Progresso Real-time Slim (Estilo Tag Doctor) */}
      {(isScanning || isScanningRelocate || isRelinkingBatch || isTrashingBatch) && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-slate-900/90 border border-slate-700/60 rounded-lg text-xs shrink-0 shadow-lg animate-in fade-in duration-200">
          <div className="flex items-center gap-2 overflow-hidden flex-1 mr-3 min-w-0">
            {isScanning && (
              <>
                <RefreshCw className="w-3.5 h-3.5 text-serato-cyan animate-spin shrink-0" />
                <span className="text-serato-cyan font-bold truncate">Varrendo Biblioteca (Sound Seal):</span>
                <span className="text-slate-300 truncate text-[11px]">
                  {sealScanProgress?.faixa || 'Iniciando extração acústica SHA-256...'}
                </span>
              </>
            )}
            {isScanningRelocate && (
              <>
                <Search className="w-3.5 h-3.5 text-serato-orange animate-spin shrink-0" />
                <span className="text-serato-orange font-bold truncate">Rastreando Faixas Perdidas:</span>
                <span className="text-slate-300 truncate text-[11px]">
                  {relocateScanProgress?.faixa || 'Inspecionando crates e database V2...'}
                </span>
              </>
            )}
            {isRelinkingBatch && (
              <>
                <Zap className="w-3.5 h-3.5 text-serato-cyan animate-bounce shrink-0" />
                <span className="text-serato-cyan font-bold truncate">Religando faixas ao Serato:</span>
                <span className="text-slate-300 truncate text-[11px]">
                  {relinkProgress?.faixa_atual || 'Processando relocalizações...'}
                </span>
              </>
            )}
            {isTrashingBatch && (
              <>
                <Trash2 className="w-3.5 h-3.5 text-rose-400 animate-pulse shrink-0" />
                <span className="text-rose-400 font-bold truncate">Movendo cópias redundantes:</span>
                <span className="text-slate-300 truncate text-[11px]">
                  {trashProgress?.fileName || 'Processando lixeira...'}
                </span>
              </>
            )}
          </div>

          <div className="flex items-center gap-2.5 shrink-0 font-mono text-[11px]">
            {isScanning && sealScanProgress && (
              <span className="text-serato-cyan font-bold">
                {sealScanProgress.percentual}% ({sealScanProgress.processados.toLocaleString()}/{sealScanProgress.total.toLocaleString()})
                {sealScanProgress.novos !== undefined && sealScanProgress.novos > 0 && ` • +${sealScanProgress.novos} novas`}
              </span>
            )}
            {isScanningRelocate && relocateScanProgress && (
              <span className="text-serato-orange font-bold">
                {relocateScanProgress.percentual}% ({relocateScanProgress.processados.toLocaleString()}/{relocateScanProgress.total.toLocaleString()})
              </span>
            )}
            {isRelinkingBatch && relinkProgress && (
              <span className="text-serato-cyan font-bold">
                {relinkProgress.percentual}% ({relinkProgress.processados.toLocaleString()}/{relinkProgress.total.toLocaleString()}) • ✅ {relinkProgress.atualizados}
              </span>
            )}
            {isTrashingBatch && trashProgress && (
              <span className="text-rose-300 font-bold">
                {Math.round((trashProgress.current / Math.max(1, trashProgress.total)) * 100)}% ({trashProgress.current}/{trashProgress.total})
              </span>
            )}

            <div className="w-24 bg-slate-950 rounded-full h-1.5 overflow-hidden ml-1 border border-white/5">
              <div
                className={`h-full transition-all duration-150 ${
                  isScanning
                    ? 'bg-gradient-to-r from-serato-cyan to-blue-500'
                    : isScanningRelocate
                      ? 'bg-gradient-to-r from-amber-500 to-serato-orange'
                      : isRelinkingBatch
                        ? 'bg-gradient-to-r from-serato-cyan to-emerald-400'
                        : 'bg-gradient-to-r from-rose-500 to-amber-500'
                }`}
                style={{
                  width: `${Math.min(100, Math.max(1,
                    isScanning && sealScanProgress ? sealScanProgress.percentual :
                    isScanningRelocate && relocateScanProgress ? relocateScanProgress.percentual :
                    isRelinkingBatch && relinkProgress ? relinkProgress.percentual :
                    isTrashingBatch && trashProgress ? Math.round((trashProgress.current / Math.max(1, trashProgress.total)) * 100) : 100
                  ))}%`
                }}
              />
            </div>
          </div>
        </div>
      )}

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
                <div className="text-base font-bold text-serato-gold">{status?.total_faixas_com_copia_som?.toLocaleString() || allCopyPaths.length}</div>
              </div>
            </div>
          </div>

          {/* Banner de Progresso de Exclusão em Lote */}
          {isTrashingBatch && trashProgress && (
            <div className="bg-rose-950/40 border border-rose-700/50 p-3 rounded-xl shadow-xl flex flex-col gap-1.5 shrink-0 animate-pulse">
              <div className="flex items-center justify-between text-xs font-bold text-white">
                <span className="flex items-center gap-2 text-rose-300">
                  <Trash2 className="w-4 h-4 text-rose-400 animate-bounce" />
                  <span>Movendo cópias redundantes selecionadas para a Lixeira...</span>
                </span>
                <span className="font-mono text-serato-gold">
                  {trashProgress.current} de {trashProgress.total} faixas
                </span>
              </div>

              <div className="w-full bg-slate-900 rounded-full h-2.5 border border-serato-cardBorder overflow-hidden">
                <div
                  className="bg-gradient-to-r from-rose-500 to-amber-500 h-2.5 transition-all duration-150"
                  style={{ width: `${Math.min(100, (trashProgress.current / trashProgress.total) * 100)}%` }}
                />
              </div>

              <div className="text-[11px] text-slate-400 font-mono truncate">
                Faixa: <b className="text-slate-200">{trashProgress.fileName}</b>
              </div>
            </div>
          )}

          {/* Tabela de Cópias Reconhecidas Pelo Som */}
          <div className="flex-1 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20">
            <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder text-xs font-semibold text-slate-200 flex items-center justify-between shrink-0">
              <div className="flex items-center gap-3">
                <span>Cópias Reconhecidas por Assinatura Sonora ({filteredDuplicatesBySound.length} de {duplicatesBySound.length} grupos)</span>
                
                {/* Botões Rápidos de Seleção */}
                <div className="flex items-center gap-1.5 ml-2">
                  <button
                    type="button"
                    onClick={handleSelectAllCopies}
                    className="text-[11px] px-2 py-0.5 rounded bg-serato-dark hover:bg-slate-700 text-serato-cyan border border-serato-cardBorder font-mono transition cursor-pointer"
                  >
                    Marcar Todas as Cópias ({allCopyPaths.length})
                  </button>
                  <button
                    type="button"
                    onClick={handleDeselectAllCopies}
                    className="text-[11px] px-2 py-0.5 rounded bg-serato-dark hover:bg-slate-700 text-slate-400 border border-serato-cardBorder font-mono transition cursor-pointer"
                  >
                    Desmarcar
                  </button>
                </div>
              </div>

              <span className="text-[10px] text-serato-muted font-mono">Mesmo som, nomes ou tags divergentes</span>
            </div>

            {/* Barra de Filtros e Busca da Sub-Aba Sound Seal */}
            <div className="bg-serato-dark/60 p-2 border-b border-serato-cardBorder flex flex-wrap items-center justify-between gap-2 shrink-0">
              <div className="relative flex-1 min-w-[220px]">
                <Search className="w-3.5 h-3.5 text-serato-muted absolute left-2.5 top-2.5" />
                <input
                  type="text"
                  value={sealSearch}
                  onChange={(e) => setSealSearch(e.target.value)}
                  placeholder="Filtrar por nome de faixa, caminho ou selo SHA-256..."
                  className="w-full pl-8 pr-3 py-1.5 text-xs bg-serato-dark border border-serato-cardBorder rounded-lg text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-cyan transition font-sans"
                />
              </div>

              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => setSealFilter('all')}
                  className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition cursor-pointer border ${
                    sealFilter === 'all'
                      ? 'bg-serato-card text-white border-serato-cyan/50 shadow-sm'
                      : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
                  }`}
                >
                  Todas ({duplicatesBySound.length})
                </button>
                <button
                  type="button"
                  onClick={() => setSealFilter('selected')}
                  className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition cursor-pointer border ${
                    sealFilter === 'selected'
                      ? 'bg-amber-950/60 text-amber-300 border-amber-600/60 shadow-sm'
                      : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
                  }`}
                >
                  Marcadas para Excluir
                </button>
                <button
                  type="button"
                  onClick={() => setSealFilter('moreThan2')}
                  className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition cursor-pointer border ${
                    sealFilter === 'moreThan2'
                      ? 'bg-serato-card text-serato-gold border-serato-gold/50 shadow-sm'
                      : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
                  }`}
                >
                  &gt; 2 Cópias
                </button>
              </div>
            </div>

            <div className="overflow-y-auto flex-1 p-2 space-y-2">
              {filteredDuplicatesBySound.length === 0 ? (
                <div className="py-12 text-center text-slate-500 text-xs">
                  <Music className="w-8 h-8 opacity-20 text-serato-cyan mx-auto mb-2" />
                  <p>Nenhuma cópia encontrada com os filtros selecionados.</p>
                  <p className="text-[11px] text-slate-600 mt-1">Ajuste a busca ou clique em "Iniciar Sound Seal" para rodar a indexação acústica contínua.</p>
                </div>
              ) : (
                filteredDuplicatesBySound.map((group: any, idx: number) => {
                  const groupCopies = (group.faixas || []).slice(1);
                  const selectedInGroupCount = groupCopies.filter((f: any) => selectedCopyPaths.has(f.caminho)).length;

                  return (
                    <div key={idx} className="bg-serato-card border border-serato-cardBorder rounded-lg p-2.5 space-y-2 text-xs">
                      {/* Cabeçalho do Bloco Acústico com Ações Exclusivas do Bloco */}
                      <div className="flex flex-wrap items-center justify-between font-mono text-[10px] text-serato-muted border-b border-white/5 pb-1.5 gap-2">
                        <div className="flex items-center gap-2">
                          <span className="text-serato-cyan font-bold">SELO SHA-256: {group.seal.substring(0, 18)}...</span>
                          <span className="text-slate-500">•</span>
                          <span className="text-serato-gold font-bold">{group.total_copias} arquivos com o mesmo áudio</span>
                        </div>

                        {/* Ações Rápidas por Bloco */}
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => handleSelectGroupCopies(group)}
                            className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-serato-cyan border border-slate-700 text-[10px] font-mono cursor-pointer transition"
                            title="Marcar todas as cópias deste bloco específico para exclusão"
                          >
                            Marcar Cópias ({groupCopies.length})
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeselectGroupCopies(group)}
                            className="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-400 border border-slate-700 text-[10px] font-mono cursor-pointer transition"
                            title="Desmarcar todas as cópias deste bloco específico"
                          >
                            Desmarcar
                          </button>
                          {selectedInGroupCount > 0 && onMoveToTrash && (
                            <button
                              type="button"
                              onClick={() => handleTrashGroupCopies(group)}
                              className="px-2.5 py-0.5 rounded bg-rose-950 hover:bg-rose-900 text-rose-300 border border-rose-700 text-[10px] font-bold cursor-pointer transition flex items-center gap-1 shadow-sm animate-in fade-in"
                              title="Move apenas as cópias marcadas deste bloco para a Lixeira, preservando a faixa protegida"
                            >
                              <Trash2 className="w-3 h-3 text-rose-400" />
                              <span>Excluir Bloco ({selectedInGroupCount})</span>
                            </button>
                          )}
                        </div>
                      </div>

                      <div className="space-y-1 pt-0.5">
                        {group.faixas.map((f: any, fIdx: number) => {
                          const isReference = f.is_master || fIdx === 0;
                          const isSelected = selectedCopyPaths.has(f.caminho);

                          return (
                            <div
                              key={fIdx}
                              className={`flex items-center justify-between p-1.5 rounded transition ${
                                isReference
                                  ? 'bg-emerald-950/25 border border-emerald-800/40'
                                  : isSelected
                                  ? 'bg-amber-950/20 border border-amber-900/40'
                                  : 'hover:bg-white/[0.02]'
                              }`}
                            >
                              <div className="flex items-center gap-2.5 truncate max-w-xl">
                                {/* Checkbox para cópias redundantes */}
                                {!isReference ? (
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => toggleSelectCopy(f.caminho)}
                                    className="rounded border-slate-700 bg-serato-dark text-serato-gold focus:ring-0 shrink-0 cursor-pointer"
                                    title="Marcar para exclusão"
                                  />
                                ) : (
                                  <span className="w-3.5 h-3.5 flex items-center justify-center shrink-0">
                                    <Shield className="w-3.5 h-3.5 text-emerald-400" />
                                  </span>
                                )}

                                {/* Orientação do Arquivo Protegido vs Cópia */}
                                {isReference ? (
                                  <span
                                    className="text-[10px] px-2 py-0.5 rounded font-mono font-bold uppercase shrink-0 bg-emerald-950 text-emerald-300 border border-emerald-800 flex items-center gap-1 shadow-sm"
                                    title="Esta faixa é a Referência Protegida (Master). Ela NUNCA será excluída e permanecerá nesta pasta."
                                  >
                                    <Shield className="w-3 h-3 text-emerald-400" />
                                    <span>Protegido (Master)</span>
                                  </span>
                                ) : (
                                  <div className="flex items-center gap-1 shrink-0">
                                    <span className="text-[10px] px-1.5 py-0.2 rounded font-mono font-bold uppercase bg-amber-950 text-amber-300 border border-amber-800">
                                      Cópia
                                    </span>
                                    <button
                                      type="button"
                                      onClick={() => handleSetMaster(group.seal, f.caminho, f.nome, f.crate)}
                                      className="text-[10px] px-2 py-0.5 rounded font-mono font-semibold bg-slate-800 hover:bg-emerald-950 text-slate-300 hover:text-emerald-300 border border-slate-700 hover:border-emerald-600 transition flex items-center gap-1 cursor-pointer shadow-sm"
                                      title={`Definir este arquivo como a Referência Protegida definitiva (preservando nesta pasta "${f.crate}") e transformando as outras em cópias`}
                                    >
                                      <ShieldCheck className="w-3 h-3 text-emerald-400" />
                                      <span>Tornar Protegido</span>
                                    </button>
                                  </div>
                                )}

                                <span className={`truncate ${isReference ? 'font-semibold text-white' : 'text-slate-300'}`} title={f.caminho}>
                                  {f.nome}
                                </span>
                                <span className="text-[10px] text-slate-400 shrink-0 font-medium">({f.crate})</span>
                              </div>

                              <div className="flex items-center gap-2 shrink-0 font-mono text-[11px]">
                                {f.bpm && <span className="text-slate-400">{Math.round(parseFloat(f.bpm))} BPM</span>}
                                {f.key && <span className="text-serato-cyan font-bold">{f.key}</span>}

                                {onOpenFileInFinder && (
                                  <button
                                    type="button"
                                    onClick={() => onOpenFileInFinder(f.caminho)}
                                    className="p-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-300 cursor-pointer transition"
                                    title="Revelar no Finder"
                                  >
                                    <Eye className="w-3.5 h-3.5 text-serato-cyan" />
                                  </button>
                                )}

                                {/* Botão de Lixeira Individual na cópia */}
                                {!isReference && onMoveToTrash && (
                                  <button
                                    type="button"
                                    onClick={() => handleTrashSingleCopy(f.caminho, f.nome)}
                                    className="p-1 rounded bg-rose-950/50 hover:bg-rose-900 text-rose-300 border border-rose-800/40 cursor-pointer transition"
                                    title="Mover esta cópia para a Lixeira"
                                  >
                                    <Trash2 className="w-3.5 h-3.5" />
                                  </button>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })
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

          {/* Banner de Progresso de Relocalização em Lote */}
          {isRelinkingBatch && relinkProgress && (
            <div className="bg-cyan-950/40 border border-serato-cyan/50 p-3 rounded-xl shadow-xl flex flex-col gap-1.5 shrink-0 animate-pulse">
              <div className="flex items-center justify-between text-xs font-bold text-white">
                <span className="flex items-center gap-2 text-serato-cyan">
                  <Zap className="w-4 h-4 text-serato-orange animate-bounce" />
                  <span>Religando faixas ausentes ao Serato...</span>
                </span>
                <span className="font-mono text-serato-gold">
                  {relinkProgress.percentual}% ({relinkProgress.processados} / {relinkProgress.total})
                </span>
              </div>

              <div className="w-full bg-slate-900 rounded-full h-2.5 border border-serato-cardBorder overflow-hidden">
                <div
                  className="bg-gradient-to-r from-serato-cyan to-blue-500 h-2.5 transition-all duration-150"
                  style={{ width: `${Math.min(100, Math.max(1, relinkProgress.percentual))}%` }}
                />
              </div>

              <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono truncate">
                <span className="truncate max-w-[70%]">
                  Faixa: <b className="text-slate-200">{relinkProgress.faixa_atual}</b>
                </span>
                <span className="text-serato-neonGreen font-semibold">
                  ✅ {relinkProgress.atualizados} faixas religadas
                </span>
              </div>
            </div>
          )}

          <div className="flex-1 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20">
            {/* Barra de Filtros, Seleção e Ações da Sub-Aba Relocate */}
            <div className="bg-serato-dark/70 p-2 border-b border-serato-cardBorder flex flex-wrap items-center justify-between gap-2 shrink-0">
              <div className="relative flex-1 min-w-[200px]">
                <Search className="w-3.5 h-3.5 text-serato-muted absolute left-2.5 top-2.5" />
                <input
                  type="text"
                  value={relocateSearch}
                  onChange={(e) => setRelocateSearch(e.target.value)}
                  placeholder="Filtrar faixas perdidas ou crates..."
                  className="w-full pl-8 pr-3 py-1 text-xs bg-serato-dark border border-serato-cardBorder rounded-lg text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-cyan transition font-sans"
                />
              </div>

              {/* Filtros de Status */}
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setRelocateFilter('all')}
                  className={`text-[11px] px-2 py-0.5 rounded font-medium transition cursor-pointer border ${
                    relocateFilter === 'all'
                      ? 'bg-serato-card text-white border-serato-orange/50 shadow-sm'
                      : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
                  }`}
                >
                  Todas ({relocateResults.length})
                </button>
                <button
                  type="button"
                  onClick={() => setRelocateFilter('withCandidate')}
                  className={`text-[11px] px-2 py-0.5 rounded font-medium transition cursor-pointer border ${
                    relocateFilter === 'withCandidate'
                      ? 'bg-emerald-950/60 text-emerald-300 border-emerald-600/60 shadow-sm'
                      : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
                  }`}
                >
                  Com Candidato ({relocateResults.filter(it => it.candidatos && it.candidatos.length > 0).length})
                </button>
                <button
                  type="button"
                  onClick={() => setRelocateFilter('noCandidate')}
                  className={`text-[11px] px-2 py-0.5 rounded font-medium transition cursor-pointer border ${
                    relocateFilter === 'noCandidate'
                      ? 'bg-rose-950/60 text-rose-300 border-rose-600/60 shadow-sm'
                      : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
                  }`}
                >
                  Sem Candidato ({relocateResults.filter(it => !it.candidatos || it.candidatos.length === 0).length})
                </button>
              </div>

              {/* Botões de Seleção e Exclusão em Massa da Tabela */}
              <div className="flex items-center gap-1.5 flex-wrap">
                <button
                  type="button"
                  onClick={handleSelectAllRelocate}
                  disabled={filteredRelocateResults.length === 0}
                  className="flex items-center gap-1 px-2 py-0.5 rounded bg-serato-dark hover:bg-slate-800 text-slate-300 border border-serato-cardBorder cursor-pointer transition text-[11px] disabled:opacity-40"
                  title="Seleciona todas as faixas exibidas na tabela"
                >
                  <CheckSquare className="w-3 h-3 text-serato-cyan" />
                  <span>Selecionar Tudo ({filteredRelocateResults.length})</span>
                </button>

                {selectedLostTracks.size > 0 && (
                  <button
                    type="button"
                    onClick={handleDeselectAllRelocate}
                    className="flex items-center gap-1 px-1.5 py-0.5 rounded text-slate-400 hover:text-slate-200 cursor-pointer transition text-[11px]"
                  >
                    <Square className="w-3 h-3" />
                    <span>Desmarcar ({selectedLostTracks.size})</span>
                  </button>
                )}

                {selectedLostTracks.size > 0 && (
                  <button
                    type="button"
                    onClick={handleRemoveSelectedLostTracks}
                    disabled={isRemovingLost}
                    className="flex items-center gap-1 px-2.5 py-0.5 rounded bg-rose-950/80 hover:bg-rose-900 text-rose-200 border border-rose-700/60 shadow-sm cursor-pointer transition text-[11px] font-bold"
                    title="Exclui as referências marcadas de todas as crates e do banco V2"
                  >
                    <Trash2 className="w-3 h-3 text-rose-400" />
                    <span>Excluir Selecionadas ({selectedLostTracks.size})</span>
                  </button>
                )}

                {filteredRelocateResults.length > 0 && (
                  <button
                    type="button"
                    onClick={handleRemoveTableLostTracks}
                    disabled={isRemovingLost}
                    className="flex items-center gap-1 px-2.5 py-0.5 rounded bg-rose-900/90 hover:bg-rose-800 text-white border border-rose-600 shadow-md cursor-pointer transition text-[11px] font-bold"
                    title="Exclui todas as faixas desta visualização de todas as crates e da database V2 do Serato"
                  >
                    <XCircle className="w-3 h-3 text-rose-300" />
                    <span>🗑️ Excluir Toda a Tabela ({filteredRelocateResults.length})</span>
                  </button>
                )}
              </div>
            </div>

            <div className="overflow-y-auto flex-1 p-2 space-y-2">
              {filteredRelocateResults.length === 0 ? (
                <div className="py-12 text-center text-slate-500 text-xs">
                  <CheckCircle2 className="w-8 h-8 opacity-20 text-emerald-400 mx-auto mb-2" />
                  <p className="font-semibold text-slate-300">Nenhuma faixa perdida encontrada com os filtros selecionados.</p>
                  <p className="text-slate-600 mt-1">Ajuste o termo de busca ou verifique suas crates.</p>
                </div>
              ) : (
                filteredRelocateResults.map((item: any, idx: number) => {
                  const bestCandidate = item.candidatos && item.candidatos.length > 0 ? item.candidatos[0] : null;
                  const isChecked = selectedLostTracks.has(item.faixa_perdida) || selectedRelinkItems.has(item.faixa_perdida);

                  return (
                    <div key={idx} className="bg-serato-card border border-serato-cardBorder rounded-lg p-3 space-y-2 text-xs">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 truncate max-w-lg">
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => {
                              setSelectedLostTracks(prev => {
                                const next = new Set(prev);
                                if (next.has(item.faixa_perdida)) next.delete(item.faixa_perdida);
                                else next.add(item.faixa_perdida);
                                return next;
                              });
                              setSelectedRelinkItems(prev => {
                                const next = new Map(prev);
                                if (next.has(item.faixa_perdida)) {
                                  next.delete(item.faixa_perdida);
                                } else if (item.in_trash && item.trash_path) {
                                  next.set(item.faixa_perdida, {
                                    rel_path: item.faixa_perdida,
                                    source_path: item.trash_path,
                                    nome: item.nome
                                  });
                                } else if (bestCandidate) {
                                  next.set(item.faixa_perdida, {
                                    rel_path: item.faixa_perdida,
                                    source_path: bestCandidate.caminho,
                                    nome: item.nome
                                  });
                                }
                                return next;
                              });
                            }}
                            className="rounded border-slate-700 bg-serato-dark text-serato-cyan focus:ring-0 shrink-0 cursor-pointer"
                          />

                          <span className="text-[10px] bg-rose-950/60 text-rose-400 px-2 py-0.5 rounded border border-rose-800/40 font-bold uppercase shrink-0">
                            Perdida no Serato
                          </span>
                          <span className="font-semibold text-white truncate" title={item.faixa_perdida}>{item.nome}</span>
                          <span className="text-[10px] text-slate-500 shrink-0">Crate: {item.crate}</span>
                        </div>

                        <div className="flex items-center gap-2">
                          {item.in_trash && (
                            <div className="flex items-center gap-2">
                              <span className="text-[10px] bg-amber-950/60 text-amber-300 px-2 py-0.5 rounded border border-amber-800/40 font-bold font-mono">
                                ⚠️ ENCONTRADO NA LIXEIRA (.Trashes)
                              </span>
                              <button
                                type="button"
                                onClick={() => handleRelinkSingle(item.faixa_perdida, item.trash_path, item.nome)}
                                className="px-2 py-0.5 rounded bg-amber-500 hover:bg-amber-400 text-black font-bold text-[10px] cursor-pointer"
                              >
                                Restaurar do Lixo ♻️
                              </button>
                            </div>
                          )}

                          <button
                            type="button"
                            onClick={() => handleRemoveSingleLostTrack(item.faixa_perdida, item.nome)}
                            className="px-2.5 py-1 rounded bg-rose-950/70 hover:bg-rose-900 text-rose-300 border border-rose-800/50 text-[10px] font-bold cursor-pointer flex items-center gap-1 transition shadow-sm"
                            title="Remove a linha e referência desta faixa do Serato (Crates e database V2)"
                          >
                            <Trash2 className="w-3 h-3 text-rose-400" />
                            <span>Excluir do Serato</span>
                          </button>
                        </div>
                      </div>

                      {/* Candidatos sugeridos */}
                      <div className="space-y-1 bg-black/30 p-2 rounded border border-white/5">
                        <div className="text-[10px] text-serato-muted uppercase font-mono">Correspondências encontradas pelo Sound Seal:</div>
                        {item.candidatos && item.candidatos.length > 0 ? (
                          item.candidatos.map((cand: any, cIdx: number) => (
                            <div key={cIdx} className="flex items-center justify-between p-1 hover:bg-white/[0.02] rounded">
                              <div className="flex items-center gap-2 truncate max-w-lg">
                                <span className={`text-[10px] px-1.5 py-0.2 rounded font-bold font-mono ${cand.score === 100 ? 'bg-emerald-950/60 text-emerald-400' : 'bg-cyan-950/60 text-cyan-300'}`}>
                                  {cand.score}% CONF
                                </span>
                                <span className="text-slate-200 truncate" title={cand.caminho}>{cand.nome}</span>
                              </div>

                              <div className="flex items-center gap-2">
                                {cand.bpm && <span className="text-[10px] font-mono text-slate-400">{Math.round(parseFloat(cand.bpm))} BPM</span>}
                                {cand.key && <span className="text-[10px] font-mono text-serato-cyan">{cand.key}</span>}
                                <button
                                  type="button"
                                  onClick={() => handleRelinkSingle(item.faixa_perdida, cand.caminho, item.nome)}
                                  className="px-2 py-0.5 rounded bg-serato-cyan hover:bg-cyan-300 text-black font-bold text-[10px] cursor-pointer"
                                >
                                  Religar →
                                </button>
                              </div>
                            </div>
                          ))
                        ) : (
                          <div className="flex items-center justify-between p-1.5">
                            <span className="text-[11px] text-slate-400 italic">Nenhum arquivo correspondente localizado no HD.</span>
                            <button
                              type="button"
                              onClick={() => handleRemoveSingleLostTrack(item.faixa_perdida, item.nome)}
                              className="px-2.5 py-1 rounded bg-rose-900/60 hover:bg-rose-800 text-rose-200 border border-rose-700/60 font-bold text-[10px] cursor-pointer flex items-center gap-1.5 transition shadow"
                              title="Exclui definitivamente a linha desta faixa que não existe mais no banco do Serato"
                            >
                              <Trash2 className="w-3 h-3 text-rose-300" />
                              <span>Excluir Linha do Banco de Dados</span>
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}

      {/* Modal de Confirmação em Tela Integrado (Zero Travamento de Popups) */}
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
