import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  Activity, AlertTriangle, ShieldAlert, CheckCircle2, RefreshCw, Trash2,
  Eye, Filter, ArrowRight, Globe, Zap, DownloadCloud, FolderTree, Search,
  Play, Pause, Volume2, X, Edit3, ShieldCheck, AlertCircle, FileSpreadsheet
} from 'lucide-react';
import { CrateInfo } from './TagDoctor';
import { ConfirmModal } from './ConfirmModal';

interface AudioHealthProps {
  mp3Path: string;
  onAddLog: (message: string) => void;
  onOpenFileInFinder?: (filePath: string) => void;
  onMoveToTrash?: (filePath: string, itemId: string) => Promise<boolean>;
}

export const AudioHealth: React.FC<AudioHealthProps> = ({
  mp3Path,
  onAddLog,
  onOpenFileInFinder,
  onMoveToTrash
}) => {
  const [items, setItems] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [selectedCategory, setSelectedCategory] = useState<string>('todas');
  const [maxDuration, setMaxDuration] = useState<number>(60);
  const [totalScanned, setTotalScanned] = useState<number>(0);
  const [totalIssues, setTotalIssues] = useState<number>(0);
  const [categoryCounts, setCategoryCounts] = useState<{
    truncada: number;
    curta: number;
    baixa_qualidade: number;
    fake_320k: number;
    sample_rate: number;
    corrompida: number;
  }>({ truncada: 0, curta: 0, baixa_qualidade: 0, fake_320k: 0, sample_rate: 0, corrompida: 0 });

  // Progresso do Coletor de Dados (Scanner)
  const [scanProgress, setScanProgress] = useState<{
    processados: number;
    total: number;
    percentual: number;
    faixa?: string;
  } | null>(null);

  // Crates
  const [cratesList, setCratesList] = useState<CrateInfo[]>([]);
  const [selectedCrate, setSelectedCrate] = useState<string>('');
  const [selectedSubcrate, setSelectedSubcrate] = useState<string>('');
  const [includeSubcrates, setIncludeSubcrates] = useState<boolean>(true);

  // Seleção e Reparação Online
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isRepairingOnline, setIsRepairingOnline] = useState<boolean>(false);
  const [repairProgress, setRepairProgress] = useState<{
    processados: number;
    total: number;
    percentual: number;
    atualizados: number;
    faixa_atual: string;
  } | null>(null);

  // Varredura Prévia de Compatibilidade (Simulação Dry-Run)
  const [isPreAuditing, setIsPreAuditing] = useState<boolean>(false);
  const [preAuditProgress, setPreAuditProgress] = useState<{
    processados: number;
    total: number;
    percentual: number;
    compativeis: number;
    incompativeis: number;
    nao_encontrados: number;
    faixa_atual: string;
  } | null>(null);
  const [preAuditResults, setPreAuditResults] = useState<Record<string, {
    status: 'compativel' | 'incompativel' | 'nao_encontrado';
    duracao_local?: number;
    online_titulo?: string;
    online_duracao?: number;
    diferenca?: number;
    provedor?: string;
    mensagem: string;
  }>>({});

  // Player de Áudio Pré-Escuta Ilimitado com Seek Bar
  const [playingTrack, setPlayingTrack] = useState<any | null>(null);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [audioDuration, setAudioDuration] = useState<number>(0);
  const [volume, setVolume] = useState<number>(0.8);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Modal de Renomeação Imediata
  const [renameModal, setRenameModal] = useState<{
    isOpen: boolean;
    item: any | null;
    newName: string;
    isSaving: boolean;
    error?: string;
  }>({
    isOpen: false,
    item: null,
    newName: '',
    isSaving: false,
  });

  // Modal do Espectrograma de Áudio
  const [spectrogramModal, setSpectrogramModal] = useState<{
    isOpen: boolean;
    isLoading: boolean;
    item: any | null;
    imageData: string | null;
    erro: string | null;
  }>({ isOpen: false, isLoading: false, item: null, imageData: null, erro: null });

  // Normalização Local de Frequência 44.1k via FFmpeg
  const [isResamplingLocal, setIsResamplingLocal] = useState<boolean>(false);
  const [resampleProgress, setResampleProgress] = useState<{
    processados: number;
    total: number;
    percentual: number;
    atualizados: number;
    faixa_atual: string;
  } | null>(null);

  // Ação individual em processamento na linha da tabela
  const [processingSingleId, setProcessingSingleId] = useState<string | null>(null);
  const [processingSingleAction, setProcessingSingleAction] = useState<'repair' | 'resample' | null>(null);

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

  // Filtros de busca e severidade
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [severityFilter, setSeverityFilter] = useState<'all' | 'error' | 'warning'>('all');

  const filteredItems = useMemo(() => {
    let result = [...items];
    if (searchTerm.trim()) {
      const q = searchTerm.toLowerCase();
      result = result.filter(i =>
        i.arquivo.toLowerCase().includes(q) ||
        i.caminho.toLowerCase().includes(q) ||
        (i.diagnostico && i.diagnostico.toLowerCase().includes(q))
      );
    }
    if (severityFilter === 'error') {
      result = result.filter(i => i.status === 'corrompido' || i.severidade === 'critica' || i.severidade === 'alta');
    } else if (severityFilter === 'warning') {
      result = result.filter(i => i.status !== 'corrompido' && i.severidade !== 'critica');
    }
    return result;
  }, [items, searchTerm, severityFilter]);

  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
  const activeCrateData = cratesList.find(c => c.nome === selectedCrate);

  // Carrega Crates
  const loadCrates = async () => {
    if (!mp3Path) return;
    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('list_crates_tag_doctor', { mp3Path });
        const data = JSON.parse(resJson);
        if (data.sucesso && data.crates) {
          setCratesList(data.crates);
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Carrega Auditoria
  const loadHealthScan = async (
    cat: string = selectedCategory,
    dur: number = maxDuration,
    crateOverride?: string,
    subcrateOverride?: string
  ) => {
    if (!mp3Path) {
      onAddLog('⚠️ Selecione a pasta MP3 antes de escanear.');
      return;
    }

    setIsLoading(true);
    setScanProgress(null);
    const activeCrate = crateOverride !== undefined ? crateOverride : selectedCrate;
    const activeSub = subcrateOverride !== undefined ? subcrateOverride : selectedSubcrate;

    const scopeLabel = activeSub
      ? `Subcrate: ${activeCrate} -> ${activeSub}`
      : activeCrate
        ? `Crate: ${activeCrate}`
        : 'Biblioteca Completa';

    onAddLog(`🩺 Audio Health: Auditando saúde de ${scopeLabel} (Teto de faixa curta: < ${dur}s)...`);

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('scan_audio_health', {
          mp3Path,
          crateRaiz: activeCrate || null,
          subcrate: activeSub || null,
          includeSubcrates,
          maxDuration: dur,
          categoria: cat,
          limit: 300,
          offset: 0
        });
        const data = JSON.parse(resJson);

        if (data.sucesso) {
          setItems(data.items || []);
          setTotalScanned(data.total_analisadas || 0);
          setTotalIssues(data.total_problemas || 0);
          if (data.categorias_contagem) {
            setCategoryCounts(data.categorias_contagem);
          }
          setSelectedIds(new Set((data.items || []).map((i: any) => i.id)));
          onAddLog(`✅ Audio Health: ${data.total_analisadas} faixas analisadas. ${data.total_problemas} evidências encontradas.`);
        } else {
          onAddLog(`❌ Erro no scanner de saúde: ${data.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Falha ao invocar scan_audio_health: ${e}`);
    } finally {
      setIsLoading(false);
      setScanProgress(null);
    }
  };

  useEffect(() => {
    loadCrates();
  }, [mp3Path]);

  // Listener de streaming para scanner, reparação online, pré-auditoria e resample local
  useEffect(() => {
    let unlistenScan: (() => void) | undefined;
    let unlistenProgress: (() => void) | undefined;
    let unlistenFinished: (() => void) | undefined;
    let unlistenResampleProg: (() => void) | undefined;
    let unlistenResampleFin: (() => void) | undefined;
    let unlistenPreauditProg: (() => void) | undefined;
    let unlistenPreauditFin: (() => void) | undefined;

    const setupListeners = async () => {
      if (isTauri) {
        const { listen } = await import('@tauri-apps/api/event');
        unlistenScan = await listen<any>('audio-health-scan-progress', (event) => {
          setScanProgress(event.payload);
        });

        unlistenProgress = await listen<any>('audio-health-batch-progress', (event) => {
          const payload = event.payload;
          setRepairProgress({
            processados: payload.processados || 0,
            total: payload.total || 0,
            percentual: payload.percentual || 0,
            atualizados: payload.atualizados || 0,
            faixa_atual: payload.faixa_atual || '',
          });
        });

        unlistenFinished = await listen<any>('audio-health-batch-finished', (event) => {
          const payload = event.payload;
          setIsRepairingOnline(false);
          setRepairProgress(null);
          if (payload.sucesso) {
            onAddLog(`🎉 Correção Online concluída! ${payload.atualizados} faixas substituídas com versões 320kbps de alta fidelidade.`);
            loadHealthScan(selectedCategory, maxDuration);
          } else {
            onAddLog(`❌ Erro na correção online: ${payload.erro || 'Desconhecido'}`);
          }
        });

        unlistenPreauditProg = await listen<any>('audio-health-preaudit-progress', (event) => {
          const p = event.payload;
          setPreAuditProgress({
            processados: p.processados || 0,
            total: p.total || 0,
            percentual: p.percentual || 0,
            compativeis: p.compativeis || 0,
            incompativeis: p.incompativeis || 0,
            nao_encontrados: p.nao_encontrados || 0,
            faixa_atual: p.faixa_atual || '',
          });
          if (p.resultado_item && p.resultado_item.caminho) {
            setPreAuditResults(prev => ({
              ...prev,
              [p.resultado_item.caminho]: p.resultado_item
            }));
          }
        });

        unlistenPreauditFin = await listen<any>('audio-health-preaudit-finished', (event) => {
          const p = event.payload;
          setIsPreAuditing(false);
          setPreAuditProgress(null);
          if (p.sucesso) {
            if (p.resultados) {
              setPreAuditResults(prev => ({ ...prev, ...p.resultados }));
              // SELEÇÃO INTELIGENTE: Seleciona automaticamente APENAS as compatíveis!
              // Desmarca qualquer divergente (>10s) para proteção absoluta do usuário!
              const compIds = new Set<string>();
              items.forEach(it => {
                const res = p.resultados[it.caminho];
                if (res && res.status === 'compativel') {
                  compIds.add(it.id);
                }
              });
              setSelectedIds(compIds);
            }
            onAddLog(`✅ Varredura Prévia concluída! ${p.compativeis} compatíveis (selecionadas), ${p.incompativeis} divergentes (desmarcadas por segurança), ${p.nao_encontrados} não localizadas.`);
          } else {
            onAddLog(`❌ Erro na varredura prévia: ${p.erro || 'Desconhecido'}`);
          }
        });

        unlistenResampleProg = await listen<any>('audio-health-resample-progress', (event) => {
          const payload = event.payload;
          setResampleProgress({
            processados: payload.processados || 0,
            total: payload.total || 0,
            percentual: payload.percentual || 0,
            atualizados: payload.atualizados || 0,
            faixa_atual: payload.faixa_atual || '',
          });
        });

        unlistenResampleFin = await listen<any>('audio-health-resample-finished', (event) => {
          const payload = event.payload;
          setIsResamplingLocal(false);
          setResampleProgress(null);
          if (payload.sucesso) {
            onAddLog(`🎉 Normalização concluída! ${payload.atualizados} faixas convertidas com sucesso para 44.100 Hz (320kbps CBR).`);
            loadHealthScan(selectedCategory, maxDuration);
          } else {
            onAddLog(`❌ Erro na normalização: ${payload.erro || 'Desconhecido'}`);
          }
        });
      }
    };

    setupListeners();
    return () => {
      if (unlistenScan) unlistenScan();
      if (unlistenProgress) unlistenProgress();
      if (unlistenFinished) unlistenFinished();
      if (unlistenPreauditProg) unlistenPreauditProg();
      if (unlistenPreauditFin) unlistenPreauditFin();
      if (unlistenResampleProg) unlistenResampleProg();
      if (unlistenResampleFin) unlistenResampleFin();
    };
  }, [selectedCategory, maxDuration, items]);

  // Limpeza do player de áudio ao desmontar
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
    };
  }, []);

  // Player de Áudio Pré-Escuta
  const playTrack = async (item: any) => {
    if (playingTrack?.id === item.id) {
      if (audioRef.current) {
        if (isPlaying) {
          audioRef.current.pause();
          setIsPlaying(false);
        } else {
          audioRef.current.play().catch(e => onAddLog(`❌ Erro play: ${e}`));
          setIsPlaying(true);
        }
      }
      return;
    }

    try {
      let src = item.caminho;
      if (isTauri) {
        const { convertFileSrc } = await import('@tauri-apps/api/core');
        src = convertFileSrc(item.caminho);
      }
      if (!audioRef.current) {
        audioRef.current = new Audio(src);
      } else {
        audioRef.current.pause();
        audioRef.current.src = src;
      }
      audioRef.current.volume = volume;
      audioRef.current.currentTime = 0;
      setPlayingTrack(item);
      setCurrentTime(0);
      setAudioDuration(item.duracao_seg || 0);

      audioRef.current.onloadedmetadata = () => {
        if (audioRef.current) {
          setAudioDuration(audioRef.current.duration || item.duracao_seg || 0);
        }
      };

      audioRef.current.ontimeupdate = () => {
        if (audioRef.current) {
          setCurrentTime(audioRef.current.currentTime);
        }
      };

      audioRef.current.onended = () => {
        setIsPlaying(false);
      };

      await audioRef.current.play();
      setIsPlaying(true);
    } catch (err) {
      onAddLog(`❌ Falha ao reproduzir áudio: ${err}`);
    }
  };

  const stopPlayback = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    setIsPlaying(false);
    setPlayingTrack(null);
  };

  // Abre e gera o espectrograma acústico da faixa
  const handleOpenSpectrogram = async (item: any) => {
    setSpectrogramModal({
      isOpen: true,
      isLoading: true,
      item,
      imageData: null,
      erro: null
    });

    try {
      const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('get_audio_spectrogram', { filepath: item.caminho });
        const data = JSON.parse(resJson);
        if (data.sucesso && data.imagem_base64) {
          setSpectrogramModal(prev => ({
            ...prev,
            isLoading: false,
            imageData: data.imagem_base64,
            erro: null
          }));
        } else {
          setSpectrogramModal(prev => ({
            ...prev,
            isLoading: false,
            erro: data.erro || 'Falha ao renderizar espectrograma.'
          }));
        }
      }
    } catch (e) {
      setSpectrogramModal(prev => ({
        ...prev,
        isLoading: false,
        erro: String(e)
      }));
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = Number(e.target.value);
    setCurrentTime(time);
    if (audioRef.current) {
      audioRef.current.currentTime = time;
    }
  };

  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const vol = Number(e.target.value);
    setVolume(vol);
    if (audioRef.current) {
      audioRef.current.volume = vol;
    }
  };

  const formatTime = (secs: number) => {
    if (!secs || isNaN(secs)) return '0:00';
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  // Disparo da Varredura Prévia em Massa
  const handlePreAuditBatch = async () => {
    const targets = selectedIds.size > 0
      ? filteredItems.filter(i => selectedIds.has(i.id))
      : filteredItems;

    if (targets.length === 0) {
      onAddLog('⚠️ Nenhuma faixa disponível para pré-auditar.');
      return;
    }

    setIsPreAuditing(true);
    setPreAuditProgress({
      processados: 0,
      total: targets.length,
      percentual: 0,
      compativeis: 0,
      incompativeis: 0,
      nao_encontrados: 0,
      faixa_atual: 'Iniciando varredura prévia de compatibilidade...',
    });

    onAddLog(`🔍 Disparando Varredura Prévia em ${targets.length} faixas (comparação de duração online sem tocar nos arquivos)...`);

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const filepaths = targets.map(t => t.caminho);
        await invoke('batch_preaudit_online', {
          filepathsJson: JSON.stringify(filepaths)
        });
      }
    } catch (e) {
      setIsPreAuditing(false);
      setPreAuditProgress(null);
      onAddLog(`❌ Falha ao iniciar varredura prévia: ${e}`);
    }
  };

  // Abertura do Modal de Renomeação Imediata
  const openRenameModal = (item: any) => {
    setRenameModal({
      isOpen: true,
      item,
      newName: item.arquivo,
      isSaving: false,
    });
  };

  // Execução da Renomeação Imediata
  const handleConfirmRename = async () => {
    if (!renameModal.item || !renameModal.newName.trim()) return;
    setRenameModal(prev => ({ ...prev, isSaving: true, error: undefined }));
    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('rename_audio_track', {
          filepath: renameModal.item.caminho,
          newName: renameModal.newName.trim()
        });
        const data = JSON.parse(resJson);
        if (data.sucesso) {
          onAddLog(`✏️ ${data.mensagem}`);
          setItems(prev => prev.map(it => {
            if (it.id === renameModal.item.id) {
              return {
                ...it,
                arquivo: data.novo_nome,
                caminho: data.novo_caminho,
              };
            }
            return it;
          }));
          setRenameModal({ isOpen: false, item: null, newName: '', isSaving: false });
        } else {
          setRenameModal(prev => ({ ...prev, isSaving: false, error: data.erro }));
        }
      }
    } catch (e: any) {
      setRenameModal(prev => ({ ...prev, isSaving: false, error: e.toString() }));
    }
  };

  // Mover faixa individual para lixeira
  const handleTrashSingle = (item: any) => {
    if (!onMoveToTrash) return;
    setModalConfig({
      isOpen: true,
      title: 'Mover Faixa Danificada para a Lixeira',
      message: `Deseja mover esta faixa com problema para a Lixeira?`,
      detail: `Arquivo: ${item.arquivo}\nMotivo: ${item.detalhes}`,
      confirmText: 'Mover para Lixeira',
      variant: 'danger',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        const ok = await onMoveToTrash(item.caminho, item.id);
        if (ok) {
          setItems(prev => prev.filter(i => i.id !== item.id));
          setSelectedIds(prev => {
            const next = new Set(prev);
            next.delete(item.id);
            return next;
          });
        }
      }
    });
  };

  // Mover selecionadas em massa para lixeira
  const handleTrashBatch = () => {
    if (!onMoveToTrash) return;
    const selectedItems = items.filter(i => selectedIds.has(i.id));
    if (selectedItems.length === 0) {
      onAddLog('⚠️ Selecione ao menos uma faixa para mover para a Lixeira.');
      return;
    }

    setModalConfig({
      isOpen: true,
      title: 'Mover Faixas Danificadas para a Lixeira',
      message: `Deseja mover as ${selectedItems.length} faixas com problemas selecionadas para a Lixeira?`,
      detail: 'As faixas selecionadas serão enviadas com segurança para o Lixo do macOS.',
      confirmText: `Mover ${selectedItems.length} faixas`,
      variant: 'danger',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        onAddLog(`🗑️ Movendo lote de ${selectedItems.length} faixas comprometidas para a Lixeira...`);
        let deletedCount = 0;

        for (const item of selectedItems) {
          const ok = await onMoveToTrash(item.caminho, item.id);
          if (ok) deletedCount++;
        }

        onAddLog(`✅ Concluído: ${deletedCount} faixas removidas para a Lixeira.`);
        setItems(prev => prev.filter(i => !selectedIds.has(i.id)));
        setSelectedIds(new Set());
      }
    });
  };

  // Correção online de uma única música com barra de status ativa
  const handleRepairSingleOnline = async (item: any) => {
    setProcessingSingleId(item.id);
    setProcessingSingleAction('repair');
    setIsRepairingOnline(true);
    setRepairProgress({
      processados: 0,
      total: 1,
      percentual: 35,
      atualizados: 0,
      faixa_atual: `Baixando versão oficial 320k: ${item.arquivo}...`
    });
    onAddLog(`🌐 Iniciando busca e download em 320kbps para: ${item.arquivo}...`);
    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('repair_track_online', {
          filepath: item.caminho
        });
        const data = JSON.parse(resJson);
        if (data.sucesso) {
          setRepairProgress({
            processados: 1,
            total: 1,
            percentual: 100,
            atualizados: 1,
            faixa_atual: `✅ Concluído: ${item.arquivo}`
          });
          onAddLog(`🎉 ${item.arquivo}: ${data.mensagem}`);
          setItems(prev => prev.filter(i => i.id !== item.id));
        } else {
          onAddLog(`❌ Erro no download/substituição: ${data.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Falha: ${e}`);
    } finally {
      setTimeout(() => {
        setProcessingSingleId(null);
        setProcessingSingleAction(null);
        setIsRepairingOnline(false);
        setRepairProgress(null);
      }, 500);
    }
  };

  // Correção online em massa das selecionadas
  const handleRepairBatchOnline = () => {
    const selectedItems = items.filter(i => selectedIds.has(i.id));
    if (selectedItems.length === 0) {
      onAddLog('⚠️ Selecione ao menos uma música para reparar online.');
      return;
    }

    setModalConfig({
      isOpen: true,
      title: 'Correção Online e Substituição Automática',
      message: `Deseja buscar e substituir automaticamente as ${selectedItems.length} faixas selecionadas por versões completas em 320kbps?`,
      detail: 'Os arquivos originais corrompidos ou incompletos serão guardados em segurança na pasta de quarentena (~/SeratoSync/quarantine/).',
      confirmText: `Reparar ${selectedItems.length} faixas`,
      variant: 'warning',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsRepairingOnline(true);
        setRepairProgress({
          processados: 0,
          total: selectedItems.length,
          percentual: 0,
          atualizados: 0,
          faixa_atual: 'Iniciando downloads em alta qualidade...'
        });

        onAddLog(`🌐 Disparando correção online em massa de ${selectedItems.length} faixas via yt-dlp...`);

        try {
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            const filepaths = selectedItems.map(i => i.caminho);
            await invoke('batch_repair_online', {
              filepathsJson: JSON.stringify(filepaths)
            });
          }
        } catch (e) {
          setIsRepairingOnline(false);
          setRepairProgress(null);
          onAddLog(`❌ Falha na chamada da correção online: ${e}`);
        }
      }
    });
  };

  // Normalização de Frequência Local em Lote via FFmpeg
  const handleBatchResample = () => {
    const selectedItems = items.filter(i => selectedIds.has(i.id));
    if (selectedItems.length === 0) return;

    setModalConfig({
      isOpen: true,
      title: 'Normalizar Frequência para 44.100 Hz',
      message: `Deseja normalizar ${selectedItems.length} faixas para a frequência padrão DJ (44.100 Hz a 320 kbps CBR)?\n\n⚡ A operação usa o FFmpeg localmente em alta velocidade sem precisar baixar nada da internet.\n🔒 Suas tags ID3 e marcadores Serato serão 100% preservados.`,
      confirmText: `Normalizar ${selectedItems.length} Faixas`,
      variant: 'info',
      onConfirm: async () => {
        setModalConfig(prev => ({ ...prev, isOpen: false }));
        setIsResamplingLocal(true);
        setResampleProgress({
          processados: 0,
          total: selectedItems.length,
          percentual: 0,
          atualizados: 0,
          faixa_atual: 'Iniciando FFmpeg...'
        });
        onAddLog(`⚡ Audio Health: Normalizando frequência de ${selectedItems.length} faixas para 44.100 Hz...`);

        try {
          if (isTauri) {
            const { invoke } = await import('@tauri-apps/api/core');
            const filepaths = selectedItems.map(i => i.caminho);
            await invoke('batch_resample_local', {
              filepathsJson: JSON.stringify(filepaths)
            });
          }
        } catch (e) {
          setIsResamplingLocal(false);
          setResampleProgress(null);
          onAddLog(`❌ Falha na normalização local: ${e}`);
        }
      }
    });
  };

  // Normalizar frequência individual com barra de status ativa
  const handleResampleSingle = async (item: any) => {
    setProcessingSingleId(item.id);
    setProcessingSingleAction('resample');
    setIsResamplingLocal(true);
    setResampleProgress({
      processados: 0,
      total: 1,
      percentual: 50,
      atualizados: 0,
      faixa_atual: `Normalizando para 44.100 Hz: ${item.arquivo}...`
    });
    onAddLog(`⚡ Audio Health: Normalizando ${item.arquivo} para 44.100 Hz...`);
    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('resample_track_local', {
          filepath: item.caminho
        });
        const data = JSON.parse(resJson);
        if (data.sucesso) {
          setResampleProgress({
            processados: 1,
            total: 1,
            percentual: 100,
            atualizados: 1,
            faixa_atual: `✅ Concluído: ${item.arquivo}`
          });
          onAddLog(`✅ ${data.mensagem}`);
          setItems(prev => prev.filter(i => i.id !== item.id));
        } else {
          onAddLog(`❌ Erro no resample: ${data.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Falha no resample: ${e}`);
    } finally {
      setTimeout(() => {
        setProcessingSingleId(null);
        setProcessingSingleAction(null);
        setIsResamplingLocal(false);
        setResampleProgress(null);
      }, 500);
    }
  };

  // Alterna seleção
  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === items.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map(i => i.id)));
    }
  };

  const handleExportCsv = () => {
    if (filteredItems.length === 0) return;
    const headers = ["Nome", "Categoria", "Bitrate_kbps", "SampleRate_Hz", "Duracao_Segundos", "Problema", "Caminho"];
    const rows = filteredItems.map(item => [
      `"${(item.arquivo || item.nome || '').replace(/"/g, '""')}"`,
      `"${(item.categoria || '').replace(/"/g, '""')}"`,
      item.bitrate || 0,
      item.sample_rate || 0,
      (item.duracao || 0).toFixed(1),
      `"${(item.motivo || item.detalhe || '').replace(/"/g, '""')}"`,
      `"${(item.caminho || '').replace(/"/g, '""')}"`
    ]);
    const csvContent = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const blob = new Blob(["\uFEFF" + csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const now = new Date();
    const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '') + '_' + now.toTimeString().slice(0, 8).replace(/:/g, '');
    link.setAttribute('href', url);
    link.setAttribute('download', `diagnostico_audio_health_${dateStr}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    onAddLog(`📊 Relatório CSV de saúde de áudio exportado (${filteredItems.length} faixas).`);
  };

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl p-4 shadow-2xl flex flex-col h-full flex-1 overflow-hidden min-h-0 space-y-3 relative">
      
      {/* Top Banner & Ações */}
      <div className="flex flex-wrap items-center justify-between pb-2.5 border-b border-serato-cardBorder shrink-0 gap-2">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Activity className="w-4 h-4 text-rose-500" />
            <span>Audio Health Doctor (Auditoria de Faixas Quebradas & Correção Online)</span>
            <span className="text-[10px] bg-rose-950/60 text-rose-400 px-2 py-0.5 rounded-full border border-rose-800/40 font-mono">
              320kbps Downloader Integrado
            </span>
          </h3>
          <p className="text-[11px] text-serato-muted">
            Rastreia cortes repentinos no meio da faixa, arquivos curtos (&lt; 60s), baixa fidelidade e substitui online automaticamente em 320kbps.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Varredura Prévia de Compatibilidade (Dry-Run / Simulação) */}
          <button
            type="button"
            onClick={handlePreAuditBatch}
            disabled={isLoading || isRepairingOnline || isPreAuditing || filteredItems.length === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-emerald-950/70 hover:bg-emerald-900 text-emerald-300 border border-emerald-500/50 transition disabled:opacity-30 cursor-pointer shadow-lg shadow-emerald-950/20"
            title="Consulta a duração online sem alterar nenhum arquivo e sinaliza quais são 100% seguras para substituição"
          >
            <ShieldCheck className={`w-3.5 h-3.5 ${isPreAuditing ? 'animate-spin text-emerald-400' : 'text-emerald-400'}`} />
            <span>{isPreAuditing ? 'Auditando Online...' : `🔍 Pré-Auditar Compatibilidade`}</span>
          </button>

          {/* Mover Lote para Lixeira */}
          <button
            type="button"
            onClick={handleTrashBatch}
            disabled={isLoading || isRepairingOnline || isPreAuditing || selectedIds.size === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-rose-950/40 hover:bg-rose-900 text-rose-300 border border-rose-800/50 transition disabled:opacity-30 cursor-pointer"
            title="Move todas as faixas selecionadas para a Lixeira"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>Excluir Selecionadas ({selectedIds.size})</span>
          </button>

          {/* Botão de Correção Online */}
          <button
            type="button"
            onClick={handleRepairBatchOnline}
            disabled={isLoading || isRepairingOnline || isPreAuditing || selectedIds.size === 0}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold bg-gradient-to-r from-serato-cyan to-blue-500 hover:opacity-90 text-black shadow-lg shadow-serato-cyan/20 transition disabled:opacity-30 cursor-pointer"
            title="Busca e baixa versões completas em 320kbps substituindo as faixas com problemas selecionadas com trava de segurança de ±10s"
          >
            <DownloadCloud className={`w-3.5 h-3.5 ${isRepairingOnline ? 'animate-bounce' : ''}`} />
            <span>{isRepairingOnline ? 'Baixando em 320k...' : `🌐 Corrigir Online 320k (${selectedIds.size})`}</span>
          </button>

          {/* Botão de Auditoria */}
          <button
            type="button"
            onClick={() => loadHealthScan(selectedCategory, maxDuration)}
            disabled={isLoading || isRepairingOnline || isResamplingLocal || isPreAuditing}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold bg-rose-600 hover:bg-rose-500 text-white shadow-lg shadow-rose-950/40 transition disabled:opacity-40 cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>{isLoading ? 'Analisando...' : '🩺 Auditar Saúde'}</span>
          </button>

          {/* Exportar Diagnóstico CSV */}
          <button
            type="button"
            onClick={handleExportCsv}
            disabled={isLoading || filteredItems.length === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition disabled:opacity-30 cursor-pointer"
            title="Exporta a lista de problemas de áudio (truncadas, fake 320k, baixa qualidade) em formato CSV"
          >
            <FileSpreadsheet className="w-3.5 h-3.5 text-serato-gold" />
            <span>Exportar CSV</span>
          </button>
        </div>
      </div>

      {/* Barra de Filtro de Crate e Duração Máxima Suspeita */}
      <div className="bg-serato-header/70 border border-serato-cardBorder p-2.5 rounded-lg flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-bold text-slate-300 flex items-center gap-1.5">
            <FolderTree className="w-4 h-4 text-serato-orange" />
            <span>Crate:</span>
          </span>

          <select
            value={selectedCrate}
            onChange={(e) => {
              const newCrate = e.target.value;
              setSelectedCrate(newCrate);
              setSelectedSubcrate('');
              loadHealthScan(selectedCategory, maxDuration, newCrate, '');
            }}
            className="bg-serato-dark border border-serato-cardBorder text-slate-200 text-xs font-semibold rounded px-2.5 py-1 focus:outline-none cursor-pointer max-w-[200px]"
          >
            <option value="">📁 Todas as Crates (Biblioteca)</option>
            {cratesList.map(c => (
              <option key={c.nome} value={c.nome}>📁 {c.nome} ({c.total})</option>
            ))}
          </select>

          {selectedCrate && activeCrateData && activeCrateData.subcrates.length > 0 && (
            <select
              value={selectedSubcrate}
              onChange={(e) => {
                const newSub = e.target.value;
                setSelectedSubcrate(newSub);
                loadHealthScan(selectedCategory, maxDuration, selectedCrate, newSub);
              }}
              className="bg-serato-dark border border-serato-cardBorder text-serato-cyan text-xs font-semibold rounded px-2.5 py-1 focus:outline-none cursor-pointer max-w-[180px]"
            >
              <option value="">↳ Todas as Subcrates</option>
              {activeCrateData.subcrates.map(sub => (
                <option key={sub.caminho_rel} value={sub.caminho_rel}>↳ {sub.nome}</option>
              ))}
            </select>
          )}

          {/* Duração Máxima Suspeita */}
          <div className="flex items-center gap-1.5 ml-3 bg-serato-dark px-2.5 py-1 rounded border border-serato-cardBorder">
            <span className="text-xs text-slate-300 font-medium">Pegar com duração menor que:</span>
            <select
              value={maxDuration}
              onChange={(e) => {
                const val = Number(e.target.value);
                setMaxDuration(val);
                loadHealthScan(selectedCategory, val);
              }}
              className="bg-slate-900 border border-slate-700 text-serato-gold text-xs font-bold rounded px-2 py-0.5"
            >
              <option value={30}>30 segundos</option>
              <option value={60}>60 segundos (1 min)</option>
              <option value={90}>90 segundos (1:30 min)</option>
              <option value={120}>120 segundos (2 min)</option>
            </select>
          </div>
        </div>

        <div className="text-serato-muted font-mono text-xs">
          Analisadas: <b className="text-white">{totalScanned.toLocaleString()}</b> • Evidências: <b className="text-rose-400">{totalIssues.toLocaleString()}</b>
        </div>
      </div>

      {/* Tabs / Chips de Destaque por Tipo de Problema */}
      <div className="flex items-center gap-2 overflow-x-auto shrink-0 pb-1">
        <button
          type="button"
          onClick={() => {
            setSelectedCategory('todas');
            loadHealthScan('todas', maxDuration);
          }}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold transition cursor-pointer border ${
            selectedCategory === 'todas'
              ? 'bg-slate-800 text-white border-serato-cyan shadow'
              : 'bg-serato-card text-slate-400 border-serato-cardBorder hover:text-white'
          }`}
        >
          <span>Todos os Problemas</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-slate-900 font-mono text-serato-cyan">
            {totalIssues}
          </span>
        </button>

        <button
          type="button"
          onClick={() => {
            setSelectedCategory('truncada');
            loadHealthScan('truncada', maxDuration);
          }}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold transition cursor-pointer border ${
            selectedCategory === 'truncada'
              ? 'bg-rose-950 text-rose-200 border-rose-500 shadow'
              : 'bg-serato-card text-rose-400/80 border-serato-cardBorder hover:text-rose-200'
          }`}
        >
          <span>🚨 Corte Repentino / Truncadas</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-rose-950 font-mono text-rose-300">
            {categoryCounts.truncada}
          </span>
        </button>

        <button
          type="button"
          onClick={() => {
            setSelectedCategory('curta');
            loadHealthScan('curta', maxDuration);
          }}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold transition cursor-pointer border ${
            selectedCategory === 'curta'
              ? 'bg-amber-950 text-amber-200 border-amber-500 shadow'
              : 'bg-serato-card text-amber-400/80 border-serato-cardBorder hover:text-amber-200'
          }`}
        >
          <span>✂️ Curtas / Jingles (&lt; {maxDuration}s)</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-amber-950 font-mono text-amber-300">
            {categoryCounts.curta}
          </span>
        </button>

        <button
          type="button"
          onClick={() => {
            setSelectedCategory('baixa_qualidade');
            loadHealthScan('baixa_qualidade', maxDuration);
          }}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold transition cursor-pointer border ${
            selectedCategory === 'baixa_qualidade'
              ? 'bg-indigo-950 text-indigo-200 border-indigo-500 shadow'
              : 'bg-serato-card text-indigo-400/80 border-serato-cardBorder hover:text-indigo-200'
          }`}
        >
          <span>📉 Baixa Qualidade (&lt; 192k)</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-indigo-950 font-mono text-indigo-300">
            {categoryCounts.baixa_qualidade}
          </span>
        </button>

        <button
          type="button"
          onClick={() => {
            setSelectedCategory('fake_320k');
            loadHealthScan('fake_320k', maxDuration);
          }}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold transition cursor-pointer border ${
            selectedCategory === 'fake_320k'
              ? 'bg-purple-950 text-purple-200 border-purple-500 shadow'
              : 'bg-serato-card text-purple-400/80 border-serato-cardBorder hover:text-purple-200'
          }`}
        >
          <span>🎭 Fake 320k (Upsampled)</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-purple-950 font-mono text-purple-300">
            {categoryCounts.fake_320k || 0}
          </span>
        </button>

        <button
          type="button"
          onClick={() => {
            setSelectedCategory('corrompida');
            loadHealthScan('corrompida', maxDuration);
          }}
          className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold transition cursor-pointer border ${
            selectedCategory === 'corrompida'
              ? 'bg-red-950 text-red-200 border-red-500 shadow'
              : 'bg-serato-card text-red-400/80 border-serato-cardBorder hover:text-red-200'
          }`}
        >
          <span>❌ Arquivos Corrompidos / Vazios</span>
          <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-red-950 font-mono text-red-300">
            {categoryCounts.corrompida}
          </span>
        </button>
      </div>

      {/* Barra de Progresso Real-time Slim (Estilo Tag Doctor / Sound Seal) */}
      {(isLoading || isRepairingOnline || isResamplingLocal || isPreAuditing) && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-slate-900/90 border border-slate-700/60 rounded-lg text-xs shrink-0 shadow-lg animate-in fade-in duration-200">
          <div className="flex items-center gap-2 overflow-hidden flex-1 mr-3 min-w-0">
            {isLoading && (
              <>
                <RefreshCw className="w-3.5 h-3.5 text-rose-400 animate-spin shrink-0" />
                <span className="text-rose-400 font-bold truncate">Auditando Integridade dos Arquivos:</span>
                <span className="text-slate-300 truncate text-[11px]">
                  {scanProgress?.faixa || 'Iniciando auditoria física...'}
                </span>
              </>
            )}
            {isPreAuditing && (
              <>
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 animate-spin shrink-0" />
                <span className="text-emerald-400 font-bold truncate">Varredura Prévia de Compatibilidade:</span>
                <span className="text-slate-300 truncate text-[11px]">
                  {preAuditProgress?.faixa_atual || 'Consultando fontes oficiais...'}
                </span>
              </>
            )}
            {isRepairingOnline && (
              <>
                <DownloadCloud className="w-3.5 h-3.5 text-serato-cyan animate-bounce shrink-0" />
                <span className="text-serato-cyan font-bold truncate">Baixando Versões 320k (44.1kHz):</span>
                <span className="text-slate-300 truncate text-[11px]">
                  {repairProgress?.faixa_atual || 'Processando substituições...'}
                </span>
              </>
            )}
            {isResamplingLocal && (
              <>
                <Zap className="w-3.5 h-3.5 text-purple-400 animate-bounce shrink-0" />
                <span className="text-purple-400 font-bold truncate">Normalizando para 44.100 Hz (FFmpeg):</span>
                <span className="text-slate-300 truncate text-[11px]">
                  {resampleProgress?.faixa_atual || 'Processando resample local...'}
                </span>
              </>
            )}
          </div>

          <div className="flex items-center gap-2.5 shrink-0 font-mono text-[11px]">
            {isLoading && scanProgress && (
              <span className="text-rose-400 font-bold">
                {scanProgress.percentual}% ({scanProgress.processados.toLocaleString()}/{scanProgress.total.toLocaleString()})
              </span>
            )}
            {isPreAuditing && preAuditProgress && (
              <span className="text-emerald-300 font-bold flex items-center gap-1.5">
                <span>{preAuditProgress.percentual}% ({preAuditProgress.processados}/{preAuditProgress.total})</span>
                <span className="text-emerald-400">🟢 {preAuditProgress.compativeis}</span>
                <span className="text-rose-400">🔴 {preAuditProgress.incompativeis}</span>
              </span>
            )}
            {isRepairingOnline && repairProgress && (
              <span className="text-serato-cyan font-bold">
                {repairProgress.percentual}% ({repairProgress.processados}/{repairProgress.total}) • ✅ {repairProgress.atualizados}
              </span>
            )}
            {isResamplingLocal && resampleProgress && (
              <span className="text-purple-300 font-bold">
                {resampleProgress.percentual}% ({resampleProgress.processados}/{resampleProgress.total}) • ✅ {resampleProgress.atualizados}
              </span>
            )}

            <div className="w-24 bg-slate-950 rounded-full h-1.5 overflow-hidden ml-1 border border-white/5">
              <div
                className={`h-full transition-all duration-150 ${
                  isLoading
                    ? 'bg-gradient-to-r from-rose-500 to-amber-500'
                    : isPreAuditing
                      ? 'bg-gradient-to-r from-emerald-500 to-teal-400'
                      : isRepairingOnline
                        ? 'bg-gradient-to-r from-serato-cyan to-blue-500'
                        : 'bg-gradient-to-r from-purple-500 to-indigo-500'
                }`}
                style={{
                  width: `${Math.min(100, Math.max(1,
                    isLoading && scanProgress ? scanProgress.percentual :
                    isPreAuditing && preAuditProgress ? preAuditProgress.percentual :
                    isRepairingOnline && repairProgress ? repairProgress.percentual :
                    isResamplingLocal && resampleProgress ? resampleProgress.percentual : 100
                  ))}%`
                }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Tabela de Diagnóstico */}
      <div className="flex-1 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20">
        <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder text-xs text-serato-muted font-mono flex items-center justify-between">
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={filteredItems.length > 0 && selectedIds.size === filteredItems.length}
              onChange={toggleSelectAll}
              className="rounded border-slate-700 bg-serato-dark text-serato-cyan focus:ring-0"
            />
            <span>{filteredItems.length} de {items.length} Faixas</span>
          </div>
          <span>Ações: 🌐 Baixar 320k • 👁️ Finder • 🗑️ Lixeira</span>
        </div>

        {/* Barra de Busca e Filtros Rápidos */}
        <div className="bg-serato-dark/60 p-2 border-b border-serato-cardBorder flex flex-wrap items-center justify-between gap-2 shrink-0">
          <div className="relative flex-1 min-w-[240px]">
            <Search className="w-3.5 h-3.5 text-serato-muted absolute left-2.5 top-2.5" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Filtrar faixas por nome, caminho ou detalhe do diagnóstico..."
              className="w-full pl-8 pr-3 py-1.5 text-xs bg-serato-dark border border-serato-cardBorder rounded-lg text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-cyan transition font-sans"
            />
          </div>

          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setSeverityFilter('all')}
              className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition cursor-pointer border ${
                severityFilter === 'all'
                  ? 'bg-serato-card text-white border-rose-500/50 shadow-sm'
                  : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
              }`}
            >
              Todas ({items.length})
            </button>
            <button
              type="button"
              onClick={() => setSeverityFilter('error')}
              className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition cursor-pointer border ${
                severityFilter === 'error'
                  ? 'bg-rose-950/60 text-rose-300 border-rose-600/60 shadow-sm'
                  : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
              }`}
            >
              Críticas / Erros
            </button>
            <button
              type="button"
              onClick={() => setSeverityFilter('warning')}
              className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition cursor-pointer border ${
                severityFilter === 'warning'
                  ? 'bg-amber-950/60 text-amber-300 border-amber-600/60 shadow-sm'
                  : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
              }`}
            >
              Avisos / Curtas
            </button>
          </div>
        </div>

        <div className="overflow-y-auto flex-1 p-2 space-y-2">
          {filteredItems.length === 0 ? (
            <div className="py-12 text-center text-slate-500 text-xs">
              <CheckCircle2 className="w-8 h-8 opacity-20 text-emerald-400 mx-auto mb-2" />
              <p className="font-semibold text-slate-300">Nenhum problema encontrado com os filtros ativos.</p>
              <p className="text-slate-600 mt-1">Ajuste a busca ou selecione outra categoria.</p>
            </div>
          ) : (
            filteredItems.map((item) => {
              const isSelected = selectedIds.has(item.id);

              return (
                <div
                  key={item.id}
                  className={`border rounded-lg p-2.5 flex items-center justify-between gap-3 text-xs transition ${
                    item.categoria === 'truncada'
                      ? 'bg-rose-950/20 border-rose-900/50 hover:bg-rose-950/30'
                      : item.categoria === 'curta'
                      ? 'bg-amber-950/20 border-amber-900/50 hover:bg-amber-950/30'
                      : item.categoria === 'corrompida'
                      ? 'bg-red-950/20 border-red-900/50 hover:bg-red-950/30'
                      : item.categoria === 'fake_320k'
                      ? 'bg-purple-950/20 border-purple-900/50 hover:bg-purple-950/30'
                      : 'bg-indigo-950/20 border-indigo-900/50 hover:bg-indigo-950/30'
                  } ${isSelected ? 'ring-1 ring-serato-cyan' : ''}`}
                >
                  <div className="flex items-center gap-3 truncate max-w-2xl">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelect(item.id)}
                      className="rounded border-slate-700 bg-serato-dark text-serato-cyan focus:ring-0"
                    />

                    {/* Badge de Destaque */}
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase shrink-0 font-mono ${
                        item.categoria === 'truncada'
                          ? 'bg-rose-950 text-rose-300 border border-rose-800 font-black'
                          : item.categoria === 'curta'
                          ? 'bg-amber-950 text-amber-300 border border-amber-800'
                          : item.categoria === 'corrompida'
                          ? 'bg-red-950 text-red-300 border border-red-800'
                          : item.categoria === 'fake_320k'
                          ? 'bg-purple-950 text-purple-300 border border-purple-800 font-black'
                          : 'bg-indigo-950 text-indigo-300 border border-indigo-800'
                      }`}
                    >
                      {item.categoria === 'truncada'
                        ? '⚠️ CORTE REPENTINO'
                        : item.categoria === 'curta'
                        ? '✂️ MUITO CURTA'
                        : item.categoria === 'corrompida'
                        ? '❌ CORROMPIDA'
                        : item.categoria === 'fake_320k'
                        ? '🎭 FAKE 320 KBPS'
                        : '📉 BAIXA QUALIDADE'}
                    </span>

                    <div className="truncate">
                      <div className="font-semibold text-white truncate" title={item.arquivo}>
                        {item.arquivo}
                      </div>
                      <div className="text-[10px] text-slate-400 truncate mt-0.5">
                        {item.detalhes} • <span className="text-slate-500 font-mono">({item.pasta})</span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0 font-mono text-[11px]">
                    {/* Badge de Varredura Prévia de Compatibilidade */}
                    {preAuditResults[item.caminho] && (
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold flex items-center gap-1 border shrink-0 ${
                          preAuditResults[item.caminho].status === 'compativel'
                            ? 'bg-emerald-950/80 text-emerald-300 border-emerald-500/50'
                            : preAuditResults[item.caminho].status === 'incompativel'
                            ? 'bg-rose-950/80 text-rose-300 border-rose-500/50'
                            : 'bg-amber-950/80 text-amber-300 border-amber-500/50'
                        }`}
                        title={preAuditResults[item.caminho].mensagem}
                      >
                        {preAuditResults[item.caminho].status === 'compativel' && '🟢 Compatível'}
                        {preAuditResults[item.caminho].status === 'incompativel' && '🔴 Divergente'}
                        {preAuditResults[item.caminho].status === 'nao_encontrado' && '🟡 Não Localizado'}
                        {preAuditResults[item.caminho].diferenca !== undefined && ` (${preAuditResults[item.caminho].diferenca}s)`}
                      </span>
                    )}

                    <span className="text-slate-300">{item.duracao_seg}s</span>
                    {item.bitrate_kbps > 0 && (
                      <span className="text-serato-cyan">{item.bitrate_kbps} kbps</span>
                    )}
                    {item.sample_rate > 0 && (
                      <span className="text-slate-500 text-[10px] bg-slate-900 px-1 py-0.2 rounded border border-white/5">
                        {item.sample_rate} Hz
                      </span>
                    )}

                    {/* Botão Visualizar Espectrograma */}
                    <button
                      type="button"
                      onClick={() => handleOpenSpectrogram(item)}
                      className="p-1.5 rounded bg-serato-dark hover:bg-slate-700 text-purple-300 border border-purple-500/30 hover:border-purple-400 transition cursor-pointer"
                      title="Abrir Espectrograma Acústico (Auditoria de Frequências e Fake 320k)"
                    >
                      <Activity className="w-3.5 h-3.5 text-purple-400" />
                    </button>

                    {/* Botão Play / Ouvir com Player Ilimitado */}
                    <button
                      type="button"
                      onClick={() => playTrack(item)}
                      className={`p-1.5 rounded transition cursor-pointer flex items-center justify-center border ${
                        playingTrack?.id === item.id && isPlaying
                          ? 'bg-serato-cyan text-black border-cyan-300 shadow-md shadow-serato-cyan/30'
                          : 'bg-serato-dark hover:bg-slate-700 text-slate-300 border-white/5'
                      }`}
                      title={playingTrack?.id === item.id && isPlaying ? "Pausar áudio" : "Ouvir áudio local com barra de busca"}
                    >
                      {playingTrack?.id === item.id && isPlaying ? (
                        <Pause className="w-3.5 h-3.5 fill-current" />
                      ) : (
                        <Play className="w-3.5 h-3.5 fill-current ml-0.5" />
                      )}
                    </button>

                    {/* Botão Renomear Imediato */}
                    <button
                      type="button"
                      onClick={() => openRenameModal(item)}
                      className="p-1.5 rounded bg-serato-dark hover:bg-slate-700 text-slate-300 border border-white/5 cursor-pointer"
                      title="Renomear faixa e atualizar tags ID3 sem sair do app"
                    >
                      <Edit3 className="w-3.5 h-3.5 text-serato-gold" />
                    </button>

                    {/* Botão Baixar Online */}
                    <button
                      type="button"
                      onClick={() => handleRepairSingleOnline(item)}
                      disabled={isRepairingOnline || isResamplingLocal}
                      className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] font-semibold transition cursor-pointer border ${
                        processingSingleId === item.id && processingSingleAction === 'repair'
                          ? 'bg-cyan-900 text-white border-cyan-400 animate-pulse'
                          : 'bg-cyan-950/50 hover:bg-cyan-900 text-serato-cyan border border-cyan-800/40 disabled:opacity-40'
                      }`}
                      title="Baixa automaticamente versão 320kbps íntegra (44.1kHz) e substitui esta faixa (com trava de segurança de ±10s)"
                    >
                      {processingSingleId === item.id && processingSingleAction === 'repair' ? (
                        <>
                          <RefreshCw className="w-3 h-3 text-serato-cyan animate-spin" />
                          <span>Baixando 320k...</span>
                        </>
                      ) : (
                        <>
                          <DownloadCloud className="w-3.5 h-3.5" />
                          <span>Baixar 320k</span>
                        </>
                      )}
                    </button>

                    {/* Revelar no Finder */}
                    {onOpenFileInFinder && (
                      <button
                        type="button"
                        onClick={() => onOpenFileInFinder(item.caminho)}
                        className="p-1 rounded bg-serato-dark hover:bg-slate-700 text-slate-300 cursor-pointer"
                        title="Revelar no Finder"
                      >
                        <Eye className="w-3.5 h-3.5 text-serato-cyan" />
                      </button>
                    )}

                    {/* Mover para Lixeira */}
                    {onMoveToTrash && (
                      <button
                        type="button"
                        onClick={() => handleTrashSingle(item)}
                        className="p-1 rounded bg-rose-950/40 hover:bg-rose-900 text-rose-300 border border-rose-800/50 cursor-pointer"
                        title="Mover arquivo danificado para Lixeira"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Dock do Player de Áudio Ilimitado com Barra de Rolagem */}
      {playingTrack && (
        <div className="bg-slate-900 border border-serato-cyan/40 p-2.5 rounded-lg flex items-center justify-between gap-3 shadow-2xl shrink-0 animate-in slide-in-from-bottom duration-200">
          <div className="flex items-center gap-2.5 min-w-0 max-w-[280px]">
            <button
              onClick={() => playTrack(playingTrack)}
              className="p-2 rounded-full bg-serato-cyan text-black hover:opacity-90 font-bold shrink-0 cursor-pointer shadow-md shadow-serato-cyan/20"
              title={isPlaying ? "Pausar" : "Tocar"}
            >
              {isPlaying ? <Pause className="w-4 h-4 fill-current" /> : <Play className="w-4 h-4 fill-current ml-0.5" />}
            </button>
            <div className="min-w-0">
              <div className="text-xs font-bold text-white truncate" title={playingTrack.arquivo}>
                {playingTrack.arquivo}
              </div>
              <div className="text-[10px] text-serato-cyan font-mono flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                <span>Ouvindo áudio local no HD</span>
              </div>
            </div>
          </div>

          {/* Seek Bar com rolagem ilimitada */}
          <div className="flex-1 flex items-center gap-2.5 max-w-xl px-2">
            <span className="text-[11px] font-mono text-slate-400 w-11 text-right">{formatTime(currentTime)}</span>
            <input
              type="range"
              min={0}
              max={audioDuration || 100}
              step={0.1}
              value={currentTime}
              onChange={handleSeek}
              className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-serato-cyan hover:accent-cyan-300"
            />
            <span className="text-[11px] font-mono text-slate-400 w-11">{formatTime(audioDuration)}</span>
          </div>

          {/* Volume e Botão Fechar */}
          <div className="flex items-center gap-2 shrink-0">
            <Volume2 className="w-3.5 h-3.5 text-slate-400" />
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={volume}
              onChange={handleVolumeChange}
              className="w-16 h-1 bg-slate-800 rounded appearance-none cursor-pointer accent-slate-400"
              title={`Volume: ${Math.round(volume * 100)}%`}
            />
            <button
              onClick={stopPlayback}
              className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-white cursor-pointer ml-1"
              title="Fechar player"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Modal de Renomeação Rápida */}
      {renameModal.isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-slate-900 border border-serato-gold/40 rounded-xl p-5 max-w-lg w-full shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <div className="flex items-center gap-2">
                <Edit3 className="w-4 h-4 text-serato-gold" />
                <h4 className="text-sm font-bold text-white">Renomear Faixa</h4>
              </div>
              <button
                onClick={() => setRenameModal({ isOpen: false, item: null, newName: '', isSaving: false })}
                className="text-slate-400 hover:text-white p-1 rounded"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-2">
              <label className="text-xs text-slate-300 font-semibold">Novo Nome do Arquivo:</label>
              <input
                type="text"
                value={renameModal.newName}
                onChange={(e) => setRenameModal(prev => ({ ...prev, newName: e.target.value }))}
                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-mono focus:border-serato-gold focus:outline-none"
                placeholder="Artista - Titulo.mp3"
                autoFocus
              />
              <p className="text-[11px] text-slate-400">
                💡 O arquivo físico no HD será renomeado e as tags ID3 (Título e Artista) serão sincronizadas automaticamente.
              </p>
              {renameModal.error && (
                <div className="text-xs text-rose-400 bg-rose-950/50 border border-rose-800 p-2 rounded">
                  {renameModal.error}
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-white/10">
              <button
                type="button"
                onClick={() => setRenameModal({ isOpen: false, item: null, newName: '', isSaving: false })}
                disabled={renameModal.isSaving}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-300 hover:bg-slate-700 transition cursor-pointer"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={handleConfirmRename}
                disabled={renameModal.isSaving || !renameModal.newName.trim()}
                className="px-4 py-1.5 rounded-lg text-xs font-bold bg-serato-gold hover:opacity-90 text-black transition cursor-pointer disabled:opacity-50"
              >
                {renameModal.isSaving ? 'Salvando...' : 'Salvar Novo Nome'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Visualizador do Espectrograma Acústico */}
      {spectrogramModal.isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 animate-in fade-in">
          <div className="bg-serato-dark border border-purple-500/40 rounded-2xl shadow-2xl w-full max-w-3xl flex flex-col overflow-hidden">
            <div className="bg-serato-header px-5 py-3 border-b border-serato-cardBorder flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Activity className="w-5 h-5 text-purple-400" />
                <span className="text-sm font-bold text-white font-sans">
                  Auditoria Espectral Acústica • {spectrogramModal.item?.arquivo}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setSpectrogramModal({ isOpen: false, isLoading: false, item: null, imageData: null, erro: null })}
                className="text-slate-400 hover:text-white p-1 rounded transition cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-5 space-y-4">
              {spectrogramModal.isLoading ? (
                <div className="py-20 flex flex-col items-center justify-center gap-3">
                  <div className="w-8 h-8 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
                  <span className="text-xs text-purple-300 font-semibold">Renderizando espectrograma de frequências via FFmpeg...</span>
                </div>
              ) : spectrogramModal.erro ? (
                <div className="p-4 bg-rose-950/40 border border-rose-800 rounded-xl text-rose-300 text-xs">
                  {spectrogramModal.erro}
                </div>
              ) : spectrogramModal.imageData ? (
                <div className="space-y-3">
                  <div className="border border-white/10 rounded-xl overflow-hidden bg-black flex justify-center shadow-inner">
                    <img
                      src={spectrogramModal.imageData}
                      alt="Espectrograma Acústico"
                      className="w-full max-h-72 object-contain"
                    />
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs">
                    <div className="p-2.5 rounded-lg bg-slate-900/80 border border-white/5">
                      <div className="text-[10px] text-slate-400 font-bold uppercase">Corte em 16.000 Hz</div>
                      <div className="text-rose-400 font-semibold mt-0.5">MP3 128 kbps típico</div>
                      <div className="text-[10px] text-slate-500 mt-1">Corte abrupto indica áudio de rádio/YouTube comprimido.</div>
                    </div>
                    <div className="p-2.5 rounded-lg bg-slate-900/80 border border-white/5">
                      <div className="text-[10px] text-slate-400 font-bold uppercase">Corte em 17.500 Hz</div>
                      <div className="text-amber-400 font-semibold mt-0.5">MP3 192 kbps</div>
                      <div className="text-[10px] text-slate-500 mt-1">Qualidade intermediária aceitável para pistas menores.</div>
                    </div>
                    <div className="p-2.5 rounded-lg bg-slate-900/80 border border-white/5">
                      <div className="text-[10px] text-slate-400 font-bold uppercase">Acima de 20.000 Hz</div>
                      <div className="text-emerald-400 font-semibold mt-0.5">320 kbps Genuíno / Lossless</div>
                      <div className="text-[10px] text-slate-500 mt-1">Armônicos e transientes de alta fidelidade preservados.</div>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="px-5 py-3 bg-slate-950/60 border-t border-white/5 flex items-center justify-between text-xs text-slate-400">
              <span>Bitrate Informado: <strong>{spectrogramModal.item?.bitrate_kbps || 0} kbps</strong></span>
              <button
                type="button"
                onClick={() => setSpectrogramModal({ isOpen: false, isLoading: false, item: null, imageData: null, erro: null })}
                className="px-4 py-1.5 rounded-lg bg-slate-800 text-slate-200 hover:bg-slate-700 transition cursor-pointer font-semibold"
              >
                Fechar
              </button>
            </div>
          </div>
        </div>
      )}

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
 // comment 
