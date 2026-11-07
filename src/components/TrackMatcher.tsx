import React, { useState, useEffect, useMemo } from 'react';
import {
  Music, Search, Sparkles, Download, CheckCircle2, AlertTriangle,
  ExternalLink, ArrowRight, FolderPlus, FileText, Globe, Folder, Zap,
  CheckSquare, Square, RefreshCw, X, Layers, PlusCircle, Check,
  Clock, ShieldAlert, ShieldCheck, Hash
} from 'lucide-react';

interface TrackMatcherProps {
  mp3Path: string;
  seratoPath: string;
  onAddLog: (message: string) => void;
  onOpenFileInFinder?: (filePath: string) => void;
}

export const TrackMatcher: React.FC<TrackMatcherProps> = ({
  mp3Path,
  seratoPath,
  onAddLog,
  onOpenFileInFinder
}) => {
  const [inputType, setInputType] = useState<'spotify' | 'text' | 'folder' | 'file'>('folder');
  const [inputData, setInputData] = useState<string>('');
  const [crateName, setCrateName] = useState<string>('Novidades Pack');
  const [isMatching, setIsMatching] = useState<boolean>(false);
  const [matchResult, setMatchResult] = useState<any>(null);
  const [exportSuccessMsg, setExportSuccessMsg] = useState<string | null>(null);

  // Filtros de busca e status para os resultados
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'upgrades' | 'conflicts' | 'found' | 'missing'>('all');

  // Seleção granular de faixas com Checkboxes
  const [selectedFound, setSelectedFound] = useState<Set<string>>(new Set());
  const [selectedMissing, setSelectedMissing] = useState<Set<string>>(new Set());

  // Rastreamento de ações concluídas
  const [replacedUpgrades, setReplacedUpgrades] = useState<Set<string>>(new Set());
  const [integratedMissing, setIntegratedMissing] = useState<Set<string>>(new Set());

  // Estados de processamento
  const [isUpgrading, setIsUpgrading] = useState<boolean>(false);
  const [isIntegrating, setIsIntegrating] = useState<boolean>(false);

  // Lista de Crates do Serato / Pastas do HD
  const [cratesList, setCratesList] = useState<any[]>([]);

  // Modal de Integração de Músicas
  const [integrateModal, setIntegrateModal] = useState<{
    isOpen: boolean;
    itemsToIntegrate: any[];
    targetMode: 'existing' | 'new';
    selectedCrate: string;
    selectedSubcrate: string;
    newCrateName: string;
    isSaving: boolean;
    error?: string;
  }>({
    isOpen: false,
    itemsToIntegrate: [],
    targetMode: 'existing',
    selectedCrate: '',
    selectedSubcrate: '',
    newCrateName: 'Novidades 2026',
    isSaving: false
  });

  // Modal de Confirmação de Substituição de Upgrades
  const [upgradeModal, setUpgradeModal] = useState<{
    isOpen: boolean;
    itemsToUpgrade: any[];
    isProcessing: boolean;
  }>({
    isOpen: false,
    itemsToUpgrade: [],
    isProcessing: false
  });

  const isTauri = typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);

  // Helper para abrir no Finder nativo com fallback
  const revealPath = async (filePath?: string) => {
    if (!filePath) return;
    if (onOpenFileInFinder) {
      onOpenFileInFinder(filePath);
    } else if (isTauri) {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        await invoke('open_file_in_finder', { path: filePath });
      } catch (err) {
        console.error('Falha ao abrir no Finder:', err);
      }
    }
  };

  const formatSec = (sec?: number) => {
    if (!sec || sec <= 0) return '0:00';
    const s = Math.round(sec);
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return `${m}:${rem < 10 ? '0' : ''}${rem}`;
  };

  // Carrega a estrutura de crates e subcrates do usuário para a integração
  useEffect(() => {
    const loadCrates = async () => {
      if (!mp3Path || !isTauri) return;
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const res = await invoke<string>('list_crates_tag_doctor', { mp3Path });
        const parsed = JSON.parse(res);
        if (parsed.sucesso && parsed.crates) {
          setCratesList(parsed.crates);
          if (parsed.crates.length > 0) {
            setIntegrateModal(prev => ({
              ...prev,
              selectedCrate: parsed.crates[0].nome,
              selectedSubcrate: parsed.crates[0].subcrates?.[0]?.nome || ''
            }));
          }
        }
      } catch (err) {
        console.error('Falha ao carregar lista de crates no TrackMatcher:', err);
      }
    };
    loadCrates();
  }, [mp3Path]);

  const filteredEncontradas = useMemo(() => {
    if (!matchResult?.encontradas) return [];
    let list = matchResult.encontradas;
    if (statusFilter === 'upgrades') {
      list = list.filter((it: any) => it.upgrade_seguro && !it.versao_divergente && !it.duracao_incompativel);
    } else if (statusFilter === 'conflicts') {
      list = list.filter((it: any) => it.versao_divergente || it.duracao_incompativel);
    }
    if (!searchTerm.trim()) return list;
    const q = searchTerm.toLowerCase();
    return list.filter((it: any) =>
      it.solicitado?.toLowerCase().includes(q) ||
      it.arquivo_local?.toLowerCase().includes(q) ||
      it.caminho_completo?.toLowerCase().includes(q) ||
      it.pasta_origem?.toLowerCase().includes(q) ||
      it.crate_destino?.toLowerCase().includes(q)
    );
  }, [matchResult, searchTerm, statusFilter]);

  const filteredFaltantes = useMemo(() => {
    if (!matchResult?.faltantes) return [];
    if (!searchTerm.trim()) return matchResult.faltantes;
    const q = searchTerm.toLowerCase();
    return matchResult.faltantes.filter((it: any) =>
      it.solicitado?.toLowerCase().includes(q) ||
      it.caminho_novo?.toLowerCase().includes(q) ||
      it.pasta_origem?.toLowerCase().includes(q)
    );
  }, [matchResult, searchTerm]);

  // Contadores analíticos
  const totalSafeUpgrades = useMemo(() => {
    if (!matchResult?.encontradas) return 0;
    return matchResult.encontradas.filter((it: any) => it.upgrade_seguro && !it.versao_divergente && !it.duracao_incompativel).length;
  }, [matchResult]);

  const totalDivergentes = useMemo(() => {
    if (!matchResult?.encontradas) return 0;
    return matchResult.encontradas.filter((it: any) => it.versao_divergente || it.duracao_incompativel).length;
  }, [matchResult]);

  const selectedUpgradesCount = useMemo(() => {
    if (!matchResult?.encontradas) return 0;
    return matchResult.encontradas.filter((it: any) => it.upgrade_seguro && !it.versao_divergente && !it.duracao_incompativel && selectedFound.has(it.caminho_completo)).length;
  }, [matchResult, selectedFound]);

  const handleSelectIncomingFolder = async () => {
    if (isTauri) {
      try {
        const { open } = await import('@tauri-apps/plugin-dialog');
        const selected = await open({
          directory: true,
          multiple: false,
          title: 'Selecionar Pasta com Novas Músicas / Downloads'
        });
        if (selected && typeof selected === 'string') {
          setInputData(selected);
          onAddLog(`📂 Pasta de novidades selecionada: ${selected}`);
        }
      } catch (err) {
        console.error('Falha ao abrir diálogo de pasta:', err);
      }
    }
  };

  const handleRunMatch = async (exportCrateNow: boolean = false) => {
    if (!inputData.trim()) {
      onAddLog(
        inputType === 'folder'
          ? '⚠️ Selecione ou informe o caminho da pasta de novidades para cruzar.'
          : '⚠️ Informe o link do Spotify ou a lista de faixas para cruzar.'
      );
      return;
    }
    if (!mp3Path) {
      onAddLog('⚠️ Selecione a pasta MP3 Master antes de realizar o cruzamento.');
      return;
    }

    setIsMatching(true);
    setExportSuccessMsg(null);
    onAddLog(
      inputType === 'folder'
        ? `🎧 Track Matcher: Varrendo pasta de novidades e cruzando contra as faixas do HD...`
        : `🎧 Track Matcher: Cruzando playlist contra suas faixas do HD...`
    );

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const res = await invoke<string>('match_tracks', {
          inputType,
          inputData,
          mp3Path,
          seratoPath,
          exportCrate: exportCrateNow ? crateName : null
        });
        const parsed = JSON.parse(res);
        setMatchResult(parsed);

        if (parsed.sucesso) {
          // Seleciona inicialmente APENAS os upgrades 100% seguros (nunca remixes divergentes) e todas as inéditas
          const initFound = new Set<string>();
          (parsed.encontradas || []).forEach((it: any) => {
            if (it.upgrade_seguro && !it.versao_divergente && !it.duracao_incompativel) {
              initFound.add(it.caminho_completo);
            }
          });
          setSelectedFound(initFound);

          const initMissing = new Set<string>();
          (parsed.faltantes || []).forEach((it: any) => {
            initMissing.add(it.caminho_novo || it.solicitado);
          });
          setSelectedMissing(initMissing);

          if (parsed.tipo_origem === 'folder') {
            const divCount = parsed.total_divergentes || 0;
            const upCount = parsed.total_upgrades || 0;
            onAddLog(`✅ Track Matcher: ${parsed.total_solicitadas} faixas escaneadas na pasta. ${parsed.total_encontradas} já no HD (${upCount} upgrades seguros, ${divCount > 0 ? `⚠️ ${divCount} conflitos de remix/versão protegidos, ` : ''}${parsed.total_faltantes} faixas inéditas).`);
          } else {
            onAddLog(`✅ Track Matcher: ${parsed.total_encontradas} faixas encontradas no HD (${parsed.total_faltantes} faltantes).`);
          }

          if (parsed.export_serato && parsed.export_serato.sucesso) {
            setExportSuccessMsg(parsed.export_serato.mensagem);
            onAddLog(`🎯 ${parsed.export_serato.mensagem}`);
          }
        } else {
          onAddLog(`❌ Erro no Track Matcher: ${parsed.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Falha ao executar Track Matcher: ${e}`);
    } finally {
      setIsMatching(false);
    }
  };

  const handleCopyMissingToClipboard = () => {
    if (!matchResult || !matchResult.faltantes) return;
    const text = matchResult.faltantes.map((f: any) => f.solicitado).join('\n');
    navigator.clipboard.writeText(text);
    onAddLog(`📋 Lista de ${matchResult.faltantes.length} faixas faltantes copiada para a área de transferência!`);
  };

  // Toggle de seleção individual
  const toggleSelectFound = (path: string) => {
    setSelectedFound(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const toggleSelectMissing = (key: string) => {
    setSelectedMissing(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // Substituição de Upgrades no Próprio Local Físico do HD
  const handleTriggerUpgrades = (items: any[]) => {
    if (items.length === 0) return;
    setUpgradeModal({
      isOpen: true,
      itemsToUpgrade: items,
      isProcessing: false
    });
  };

  const handleConfirmReplaceUpgrades = async () => {
    const items = upgradeModal.itemsToUpgrade;
    if (items.length === 0) return;
    setUpgradeModal(prev => ({ ...prev, isProcessing: true }));
    setIsUpgrading(true);

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('replace_upgrades_track_matcher', {
          upgradesJson: JSON.stringify(items)
        });
        const parsed = JSON.parse(resJson);
        if (parsed.sucesso) {
          onAddLog(`🚀 ${parsed.mensagem}`);
          setReplacedUpgrades(prev => {
            const next = new Set(prev);
            items.forEach(it => next.add(it.caminho_completo));
            return next;
          });
          setUpgradeModal({ isOpen: false, itemsToUpgrade: [], isProcessing: false });
        } else {
          onAddLog(`❌ Falha na substituição de upgrades: ${parsed.erro}`);
        }
      }
    } catch (e) {
      onAddLog(`❌ Erro ao substituir upgrades: ${e}`);
    } finally {
      setIsUpgrading(false);
      setUpgradeModal(prev => ({ ...prev, isProcessing: false }));
    }
  };

  // Abrir Modal de Integração de Músicas
  const handleOpenIntegrateModal = (items: any[]) => {
    if (items.length === 0) {
      onAddLog('⚠️ Selecione ao menos uma faixa para integrar.');
      return;
    }
    setIntegrateModal(prev => ({
      ...prev,
      isOpen: true,
      itemsToIntegrate: items,
      isSaving: false,
      error: undefined
    }));
  };

  // Confirmação de Integração de Músicas na Crate
  const handleConfirmIntegrate = async () => {
    const { itemsToIntegrate, targetMode, selectedCrate, selectedSubcrate, newCrateName } = integrateModal;
    if (itemsToIntegrate.length === 0) return;

    let targetFolder = '';
    if (targetMode === 'existing') {
      if (!selectedCrate) {
        setIntegrateModal(prev => ({ ...prev, error: 'Selecione uma Crate de destino.' }));
        return;
      }
      if (selectedSubcrate) {
        targetFolder = `${mp3Path}/${selectedCrate}/${selectedSubcrate}`;
      } else {
        targetFolder = `${mp3Path}/${selectedCrate}`;
      }
    } else {
      if (!newCrateName.trim()) {
        setIntegrateModal(prev => ({ ...prev, error: 'Informe o nome da nova Crate.' }));
        return;
      }
      targetFolder = `${mp3Path}/${newCrateName.trim()}`;
    }

    setIntegrateModal(prev => ({ ...prev, isSaving: true, error: undefined }));
    setIsIntegrating(true);

    try {
      if (isTauri) {
        const { invoke } = await import('@tauri-apps/api/core');
        const resJson = await invoke<string>('integrate_tracks_to_crate', {
          tracksJson: JSON.stringify(itemsToIntegrate),
          targetFolder
        });
        const parsed = JSON.parse(resJson);
        if (parsed.sucesso) {
          onAddLog(`📥 ${parsed.mensagem}`);
          setIntegratedMissing(prev => {
            const next = new Set(prev);
            itemsToIntegrate.forEach(it => next.add(it.caminho_novo || it.solicitado));
            return next;
          });
          setIntegrateModal(prev => ({ ...prev, isOpen: false, itemsToIntegrate: [], isSaving: false }));
        } else {
          setIntegrateModal(prev => ({ ...prev, isSaving: false, error: parsed.erro }));
        }
      }
    } catch (e: any) {
      setIntegrateModal(prev => ({ ...prev, isSaving: false, error: e.toString() }));
    } finally {
      setIsIntegrating(false);
    }
  };

  // Crate ativa selecionada para dropdown de subcrates
  const activeCrateData = useMemo(() => {
    return cratesList.find(c => c.nome === integrateModal.selectedCrate);
  }, [cratesList, integrateModal.selectedCrate]);

  // Destino formatado para pré-visualização no modal
  const previewTargetDestination = useMemo(() => {
    if (integrateModal.targetMode === 'existing') {
      if (integrateModal.selectedSubcrate) {
        return `${mp3Path}/${integrateModal.selectedCrate}/${integrateModal.selectedSubcrate}`;
      }
      return `${mp3Path}/${integrateModal.selectedCrate}`;
    }
    return `${mp3Path}/${integrateModal.newCrateName.trim() || 'Nova_Crate'}`;
  }, [mp3Path, integrateModal]);

  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl p-4 shadow-2xl flex flex-col h-full flex-1 overflow-hidden min-h-0 space-y-3 relative">
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between pb-2.5 border-b border-serato-cardBorder shrink-0 gap-2">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <Music className="w-4 h-4 text-serato-cyan" />
            <span>Track Matcher & Importador de Playlists (Spotify / Pastas Locais)</span>
            <span className="text-[10px] bg-serato-neonGreen/20 text-serato-neonGreen px-2 py-0.5 rounded-full border border-serato-neonGreen/30 font-mono">
              Cruzamento Automático com o HD
            </span>
          </h3>
          <p className="text-[11px] text-serato-muted">
            Cruza novas pastas ou playlists com seu HD Master, detecta faixas inéditas para integrar e upgrades de bitrate para substituir no próprio local.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Botão de Substituir Upgrades Selecionados */}
          {selectedUpgradesCount > 0 && (
            <button
              type="button"
              onClick={() => {
                const itemsToUp = matchResult.encontradas.filter((it: any) => it.upgrade_disponivel && selectedFound.has(it.caminho_completo));
                handleTriggerUpgrades(itemsToUp);
              }}
              disabled={isUpgrading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-serato-gold hover:opacity-90 text-black shadow-lg shadow-amber-950/40 transition cursor-pointer"
            >
              <Zap className="w-3.5 h-3.5 fill-current" />
              <span>Substituir {selectedUpgradesCount} Upgrades</span>
            </button>
          )}

          {/* Botão de Integrar Músicas Selecionadas */}
          {matchResult?.tipo_origem === 'folder' && selectedMissing.size > 0 && (
            <button
              type="button"
              onClick={() => {
                const itemsToInt = matchResult.faltantes.filter((it: any) => selectedMissing.has(it.caminho_novo || it.solicitado));
                handleOpenIntegrateModal(itemsToInt);
              }}
              disabled={isIntegrating}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-950/40 transition cursor-pointer"
            >
              <PlusCircle className="w-3.5 h-3.5" />
              <span>Integrar {selectedMissing.size} Inéditas na Crate</span>
            </button>
          )}

          {/* Gerar Crate no Serato */}
          {matchResult && matchResult.encontradas && matchResult.encontradas.length > 0 && (
            <button
              type="button"
              onClick={() => handleRunMatch(true)}
              disabled={isMatching}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-serato-cyan hover:bg-cyan-300 text-black shadow-lg shadow-serato-cyan/20 transition cursor-pointer"
            >
              <FolderPlus className="w-3.5 h-3.5" />
              <span>Gerar Crate Serato ({matchResult.encontradas.length})</span>
            </button>
          )}

          <button
            type="button"
            onClick={() => handleRunMatch(false)}
            disabled={isMatching}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-bold bg-serato-card hover:bg-serato-cyan/20 text-serato-cyan border border-serato-cyan/40 transition disabled:opacity-40 cursor-pointer"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>{isMatching ? 'Cruzando...' : '🔍 Cruzar Playlist / Pasta'}</span>
          </button>
        </div>
      </div>

      {/* Input Controls */}
      <div className="bg-serato-card p-3 rounded-lg border border-serato-cardBorder space-y-2.5 shrink-0">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs text-slate-300 font-semibold mr-1">Origem do Cruzamento:</span>
            
            <button
              type="button"
              onClick={() => {
                setInputType('folder');
                setInputData('');
              }}
              className={`px-2.5 py-1 text-xs rounded transition flex items-center gap-1.5 cursor-pointer ${
                inputType === 'folder'
                  ? 'bg-serato-gold text-black font-bold shadow'
                  : 'bg-serato-dark text-slate-400 hover:text-white border border-serato-cardBorder'
              }`}
            >
              <Folder className="w-3.5 h-3.5" />
              <span>📁 Pasta de Novidades (Downloads / Packs)</span>
            </button>

            <button
              type="button"
              onClick={() => {
                setInputType('text');
                setInputData('');
              }}
              className={`px-2.5 py-1 text-xs rounded transition flex items-center gap-1.5 cursor-pointer ${
                inputType === 'text'
                  ? 'bg-serato-cyan text-black font-bold'
                  : 'bg-serato-dark text-slate-400 hover:text-white border border-serato-cardBorder'
              }`}
            >
              <FileText className="w-3.5 h-3.5" />
              <span>Texto / Linhas</span>
            </button>

            <button
              type="button"
              onClick={() => {
                setInputType('spotify');
                setInputData('');
              }}
              className={`px-2.5 py-1 text-xs rounded transition flex items-center gap-1.5 cursor-pointer ${
                inputType === 'spotify'
                  ? 'bg-[#1DB954] text-black font-bold'
                  : 'bg-serato-dark text-slate-400 hover:text-white border border-serato-cardBorder'
              }`}
            >
              <Globe className="w-3.5 h-3.5" />
              <span>Spotify URL</span>
            </button>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">Nome da Crate:</span>
            <input
              type="text"
              value={crateName}
              onChange={(e) => setCrateName(e.target.value)}
              className="bg-serato-dark border border-serato-cardBorder px-2.5 py-1 text-xs rounded text-white font-mono w-44 focus:outline-none focus:border-serato-cyan"
            />
          </div>
        </div>

        {inputType === 'folder' ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={inputData}
                onChange={(e) => setInputData(e.target.value)}
                placeholder="Selecione ou cole o caminho da pasta de novos MP3s baixados (ex: /Users/pastteur/Downloads/Pack2026)..."
                className="flex-1 bg-serato-dark border border-serato-cardBorder px-3 py-1.5 text-xs rounded text-slate-200 placeholder-slate-500 font-mono focus:outline-none focus:border-serato-gold"
              />
              <button
                type="button"
                onClick={handleSelectIncomingFolder}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-bold bg-slate-800 hover:bg-slate-700 text-serato-gold border border-serato-gold/40 transition cursor-pointer shrink-0"
              >
                <Folder className="w-3.5 h-3.5 text-serato-gold" />
                <span>Procurar Pasta...</span>
              </button>
            </div>
            <div className="text-[11px] text-slate-400 bg-serato-dark/70 px-2.5 py-1 rounded border border-white/5 flex items-center gap-1.5">
              <Zap className="w-3.5 h-3.5 text-serato-gold shrink-0" />
              <span>
                Varre todas as novas faixas desta pasta. Identifica automaticamente upgrades de bitrate para sobrescrever no próprio local do HD e faixas inéditas para copiar para qualquer Crate.
              </span>
            </div>
          </div>
        ) : inputType === 'spotify' ? (
          <input
            type="text"
            value={inputData}
            onChange={(e) => setInputData(e.target.value)}
            placeholder="Cole aqui o link da playlist do Spotify: https://open.spotify.com/playlist/..."
            className="w-full bg-serato-dark border border-serato-cardBorder px-3 py-1.5 text-xs rounded text-slate-200 placeholder-slate-500 focus:outline-none focus:border-serato-cyan"
          />
        ) : (
          <textarea
            value={inputData}
            onChange={(e) => setInputData(e.target.value)}
            placeholder="Cole uma lista de faixas (uma por linha):&#10;Fresno - Porto Alegre&#10;Raimundos - Me lambe&#10;Pitty - Semana Que Vem"
            rows={3}
            className="w-full bg-serato-dark border border-serato-cardBorder p-2 text-xs rounded text-slate-200 placeholder-slate-500 font-mono focus:outline-none focus:border-serato-cyan"
          />
        )}
      </div>

      {exportSuccessMsg && (
        <div className="bg-emerald-950/60 border border-emerald-800/40 text-emerald-300 p-2.5 rounded-lg text-xs flex items-center gap-2 shrink-0">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{exportSuccessMsg}</span>
        </div>
      )}

      {/* Resultados do Cruzamento */}
      <div className="flex-1 border border-serato-cardBorder rounded-lg overflow-hidden flex flex-col min-h-0 bg-serato-card/20">
        <div className="bg-serato-header px-3 py-2 border-b border-serato-cardBorder text-xs flex items-center justify-between text-slate-300">
          <div className="flex items-center gap-3 flex-wrap">
            <span>Resultados: <b className="text-white">{matchResult?.total_solicitadas || 0}</b> faixas analisadas</span>
            <span className="text-emerald-400 font-bold">✅ {matchResult?.total_encontradas || 0} já no HD</span>
            {totalSafeUpgrades > 0 && (
              <span className="text-serato-gold font-bold">🚀 {totalSafeUpgrades} Upgrades Seguros</span>
            )}
            {totalDivergentes > 0 && (
              <span className="text-rose-400 font-bold bg-rose-950/60 px-2 py-0.5 rounded border border-rose-800">
                ⚠️ {totalDivergentes} Conflitos de Remix/Duração (Protegidos)
              </span>
            )}
            <span className="text-cyan-400 font-bold">
              {matchResult?.tipo_origem === 'folder' ? '✨' : '⚠️'} {matchResult?.total_faltantes || 0} {matchResult?.tipo_origem === 'folder' ? 'inéditas / novas' : 'faltantes'}
            </span>
          </div>

          {matchResult && matchResult.total_faltantes > 0 && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCopyMissingToClipboard}
                className="text-[10px] px-2 py-0.5 rounded bg-serato-dark hover:bg-slate-700 text-slate-300 border border-serato-cardBorder cursor-pointer"
              >
                Copiar Lista {matchResult?.tipo_origem === 'folder' ? 'Inéditas' : 'Faltantes'}
              </button>
              {matchResult?.tipo_origem !== 'folder' && (
                <button
                  type="button"
                  onClick={() => onAddLog(`📥 Baixar Faltantes: Você pode colar as ${matchResult.total_faltantes} faixas faltantes no utilitário de download integrado ou no spotdl / yt-dlp.`)}
                  className="text-[10px] px-2.5 py-0.5 rounded bg-serato-orange hover:bg-amber-400 text-black font-bold flex items-center gap-1 cursor-pointer"
                >
                  <Download className="w-3 h-3" />
                  <span>📥 Baixar Faixas Faltantes</span>
                </button>
              )}
            </div>
          )}
        </div>

        {/* Barra de Filtros e Busca */}
        {matchResult && (
          <div className="bg-serato-dark/60 p-2 border-b border-serato-cardBorder flex flex-wrap items-center justify-between gap-2 shrink-0">
            <div className="relative flex-1 min-w-[220px]">
              <Search className="w-3.5 h-3.5 text-serato-muted absolute left-2.5 top-2.5" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Filtrar por nome de faixa, pasta de origem ou crate no HD..."
                className="w-full pl-8 pr-3 py-1.5 text-xs bg-serato-dark border border-serato-cardBorder rounded-lg text-slate-200 placeholder-serato-muted focus:outline-none focus:border-serato-cyan transition font-sans"
              />
            </div>

            <div className="flex items-center gap-1.5 flex-wrap">
              <button
                type="button"
                onClick={() => setStatusFilter('all')}
                className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition cursor-pointer border ${
                  statusFilter === 'all'
                    ? 'bg-serato-card text-white border-serato-cyan/50 shadow-sm'
                    : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
                }`}
              >
                Todas ({(matchResult.encontradas?.length || 0) + (matchResult.faltantes?.length || 0)})
              </button>

              {totalSafeUpgrades > 0 && (
                <button
                  type="button"
                  onClick={() => setStatusFilter('upgrades')}
                  className={`text-[11px] px-2.5 py-1 rounded-lg font-bold transition cursor-pointer border ${
                    statusFilter === 'upgrades'
                      ? 'bg-amber-950/80 text-serato-gold border-serato-gold shadow-sm'
                      : 'bg-serato-dark text-serato-gold/70 border-serato-cardBorder hover:text-serato-gold'
                  }`}
                >
                  🚀 Upgrades Seguros ({totalSafeUpgrades})
                </button>
              )}

              {totalDivergentes > 0 && (
                <button
                  type="button"
                  onClick={() => setStatusFilter('conflicts')}
                  className={`text-[11px] px-2.5 py-1 rounded-lg font-bold transition cursor-pointer border ${
                    statusFilter === 'conflicts'
                      ? 'bg-rose-950/90 text-rose-300 border-rose-600 shadow-sm'
                      : 'bg-serato-dark text-rose-400/80 border-rose-900/60 hover:text-rose-300'
                  }`}
                >
                  ⚠️ Conflitos / Remixes ({totalDivergentes})
                </button>
              )}

              <button
                type="button"
                onClick={() => setStatusFilter('found')}
                className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition cursor-pointer border ${
                  statusFilter === 'found'
                    ? 'bg-emerald-950/60 text-emerald-300 border-emerald-600/60 shadow-sm'
                    : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
                }`}
              >
                Já no HD ({matchResult.encontradas?.length || 0})
              </button>

              <button
                type="button"
                onClick={() => setStatusFilter('missing')}
                className={`text-[11px] px-2.5 py-1 rounded-lg font-medium transition cursor-pointer border ${
                  statusFilter === 'missing'
                    ? 'bg-cyan-950/60 text-cyan-300 border-cyan-600/60 shadow-sm'
                    : 'bg-serato-dark text-slate-400 border-serato-cardBorder hover:text-white'
                }`}
              >
                {matchResult?.tipo_origem === 'folder' ? 'Inéditas' : 'Faltantes'} ({matchResult.faltantes?.length || 0})
              </button>
            </div>
          </div>
        )}

        {/* Lista de Resultados */}
        <div className="overflow-y-auto flex-1 p-2 space-y-2 text-xs font-mono">
          {!matchResult ? (
            <div className="py-12 text-center text-slate-500 font-sans">
              <Music className="w-8 h-8 opacity-20 text-serato-cyan mx-auto mb-2" />
              <p>Selecione uma pasta com novos áudios ou cole uma playlist acima e clique em "Cruzar Playlist / Pasta".</p>
              <p className="text-[11px] text-slate-600 mt-1">O sistema buscará as músicas instantaneamente no seu HD Master com verificação de versões e impressões digitais de áudio.</p>
            </div>
          ) : (
            <>
              {/* Faixas Encontradas / Upgrades */}
              {(statusFilter === 'all' || statusFilter === 'found' || statusFilter === 'upgrades' || statusFilter === 'conflicts') && filteredEncontradas.map((item: any, idx: number) => {
                const isSelected = selectedFound.has(item.caminho_completo);
                const isReplaced = replacedUpgrades.has(item.caminho_completo);
                const isDivergent = item.versao_divergente || item.duracao_incompativel || (item.confianca === 'INCERTA');

                return (
                  <div 
                    key={`found-${idx}`} 
                    className={`border p-2.5 rounded-lg flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2.5 transition ${
                      isReplaced
                        ? 'bg-emerald-950/30 border-emerald-700/60'
                        : isDivergent
                        ? 'bg-rose-950/20 border-rose-800/60 hover:bg-rose-950/30'
                        : item.upgrade_seguro
                        ? 'bg-amber-950/20 border-serato-gold/60 hover:bg-amber-950/30'
                        : 'bg-serato-card border-emerald-900/40 hover:bg-emerald-950/20'
                    }`}
                  >
                    <div className="flex flex-col gap-1.5 flex-1 min-w-0 max-w-3xl">
                      {/* Linha 1: Checkbox, Badges de Status e Nomes */}
                      <div className="flex items-center gap-2 truncate">
                        {/* Checkbox: se for divergente (remix vs original), impede seleção para substituição acidental */}
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelectFound(item.caminho_completo)}
                          disabled={isDivergent}
                          className="rounded border-slate-700 bg-serato-dark text-serato-gold focus:ring-0 cursor-pointer shrink-0 disabled:opacity-30 disabled:cursor-not-allowed"
                          title={isDivergent ? 'Substituição bloqueada: versão divergente ou duração incompatível' : 'Selecionar para substituição'}
                        />

                        {isReplaced ? (
                          <span className="text-[10px] bg-emerald-950 text-emerald-300 border border-emerald-600 px-2 py-0.5 rounded font-bold shrink-0 flex items-center gap-1 font-mono">
                            <Check className="w-3 h-3 text-emerald-400" />
                            ATUALIZADO NO LOCAL
                          </span>
                        ) : item.versao_divergente ? (
                          <span className="text-[10px] bg-rose-950 text-rose-300 border border-rose-700 px-2 py-0.5 rounded font-bold shrink-0 flex items-center gap-1 font-mono">
                            <AlertTriangle className="w-3 h-3 text-rose-400" />
                            ⚠️ REMIX VS ORIGINAL (BLOQUEADO)
                          </span>
                        ) : item.duracao_incompativel ? (
                          <span className="text-[10px] bg-rose-950 text-rose-300 border border-rose-700 px-2 py-0.5 rounded font-bold shrink-0 flex items-center gap-1 font-mono">
                            <Clock className="w-3 h-3 text-rose-400" />
                            ⏱️ DURAÇÃO DIFERENTE (Δ {item.delta_duracao}s)
                          </span>
                        ) : item.upgrade_seguro ? (
                          <span className="text-[10px] bg-amber-950 text-serato-gold border border-serato-gold/60 px-2 py-0.5 rounded font-bold shrink-0 flex items-center gap-1 font-mono">
                            <Zap className="w-3 h-3 text-serato-gold fill-current" />
                            🚀 UPGRADE SEGURO
                          </span>
                        ) : (
                          <span className="text-[10px] bg-emerald-950 text-emerald-400 border border-emerald-800/40 px-1.5 py-0.5 rounded font-bold shrink-0 font-mono">
                            {item.score}% MATCH
                          </span>
                        )}

                        {item.confianca && (
                          <span className={`text-[9px] px-1.5 py-0.5 rounded font-mono font-bold shrink-0 border ${
                            item.confianca === 'ALTA'
                              ? 'bg-emerald-950/70 text-emerald-300 border-emerald-700/60'
                              : item.confianca === 'MEDIA'
                              ? 'bg-yellow-950/70 text-yellow-300 border-yellow-700/60'
                              : 'bg-rose-950/70 text-rose-300 border-rose-700/60'
                          }`}>
                            {item.confianca === 'ALTA' ? '🟢 ALTA CONFIANÇA' : item.confianca === 'MEDIA' ? '🟡 MÉDIA' : '🔴 INCERTA'}
                          </span>
                        )}

                        <span className="text-white font-sans font-medium truncate" title={item.solicitado}>{item.solicitado}</span>
                        <ArrowRight className="w-3 h-3 text-slate-600 shrink-0" />
                        <span className="text-slate-400 text-[11px] truncate font-sans" title={item.caminho_completo}>{item.arquivo_local}</span>
                      </div>

                      {/* Linha 2: Metadados Técnicos, Duração, Bitrates e Versões */}
                      <div className="flex items-center gap-2.5 text-[10px] font-mono flex-wrap pl-6">
                        {/* Bitrate */}
                        {item.novo_bitrate !== undefined && (
                          <span className={item.upgrade_seguro ? 'text-emerald-400 font-bold bg-emerald-950/60 px-1.5 py-0.5 rounded border border-emerald-700/40' : 'text-slate-400 bg-slate-900 px-1.5 py-0.5 rounded'}>
                            Qualidade: {item.novo_bitrate}k {item.novo_formato} ➔ {item.lib_bitrate || '?'}k {item.lib_formato}
                          </span>
                        )}

                        {/* Duração e Delta */}
                        {item.novo_duracao > 0 && item.lib_duracao > 0 && (
                          <span className={`px-1.5 py-0.5 rounded border flex items-center gap-1 ${
                            item.duracao_incompativel 
                              ? 'bg-rose-950/60 text-rose-300 border-rose-800' 
                              : 'bg-slate-900 text-slate-300 border-slate-800'
                          }`}>
                            <Clock className="w-2.5 h-2.5" />
                            <span>Duração: {formatSec(item.novo_duracao)} vs {formatSec(item.lib_duracao)} (Δ {item.delta_duracao}s)</span>
                          </span>
                        )}

                        {/* Versões comparadas */}
                        {(item.versao_novo !== 'Original / Álbum' || item.versao_lib !== 'Original / Álbum') && (
                          <span className={`px-1.5 py-0.5 rounded border ${
                            item.versao_divergente 
                              ? 'bg-rose-950/70 text-rose-300 border-rose-700 font-bold' 
                              : 'bg-slate-900 text-slate-400 border-slate-800'
                          }`}>
                            Versão: {item.versao_novo} ⟷ {item.versao_lib}
                          </span>
                        )}

                        {/* Hash de áudio puro SHA-256 (Audio Seal) */}
                        {item.audio_seal_novo && (
                          <span className="text-slate-500 bg-slate-950 px-1.5 py-0.5 rounded border border-white/5 flex items-center gap-1" title={`SHA-256 Audio Seal Novo: ${item.audio_seal_novo}\nSHA-256 Audio Seal HD: ${item.audio_seal_lib || 'Calculado no match'}`}>
                            <Hash className="w-2.5 h-2.5 text-slate-500" />
                            <span>Seal: {item.audio_seal_novo.slice(0, 8)}...</span>
                          </span>
                        )}
                      </div>

                      {/* Linha 3: Origem da Pasta ➔ Crate Destino no HD */}
                      <div className="flex items-center gap-2 text-[10px] font-mono pl-6 pt-0.5">
                        <span className="bg-slate-800/80 text-slate-300 px-1.5 py-0.5 rounded border border-slate-700/60 truncate max-w-xs" title={item.pasta_origem}>
                          📁 Origem: {item.pasta_origem ? item.pasta_origem.split('/').pop() : 'Downloads'}
                        </span>
                        <span className="text-serato-gold font-bold">➔</span>
                        <span className="bg-serato-cyan/20 text-serato-cyan px-1.5 py-0.5 rounded border border-serato-cyan/40 font-bold truncate max-w-xs" title={item.crate_destino}>
                          🎯 Serato Crate: {item.crate_destino || 'Raiz'}
                        </span>
                      </div>

                      {/* Alerta de Incompatibilidade se houver */}
                      {item.aviso_incompatibilidade && isDivergent && (
                        <div className="ml-6 text-[10px] text-rose-300 bg-rose-950/50 border border-rose-800/60 px-2 py-0.5 rounded font-sans flex items-center gap-1.5">
                          <AlertTriangle className="w-3 h-3 text-rose-400 shrink-0" />
                          <span>{item.aviso_incompatibilidade}</span>
                        </div>
                      )}
                    </div>

                    {/* Ações da Faixa: Botoes de Substituir, Integrar como Nova, e Abrir no Finder */}
                    <div className="flex items-center gap-1.5 shrink-0 self-end sm:self-center">
                      {/* Se for divergente (ex: Remix), permite integrar como nova faixa na Crate sem sobrescrever a original! */}
                      {isDivergent && item.caminho_novo && (
                        <button
                          type="button"
                          onClick={() => handleOpenIntegrateModal([item])}
                          className="flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-bold bg-emerald-950/70 hover:bg-emerald-900 text-emerald-300 border border-emerald-600/60 transition cursor-pointer shadow"
                          title="Salva este Remix como nova faixa na Crate sem sobrescrever a original"
                        >
                          <PlusCircle className="w-3 h-3 text-emerald-400" />
                          <span>Integrar Remix na Crate</span>
                        </button>
                      )}

                      {/* Se for Upgrade Seguro, botão de substituir no local */}
                      {item.upgrade_seguro && !isReplaced && (
                        <button
                          type="button"
                          onClick={() => handleTriggerUpgrades([item])}
                          disabled={isUpgrading}
                          className="flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-bold bg-serato-gold hover:opacity-90 text-black border border-amber-400 transition cursor-pointer shadow"
                          title="Sobrescreve o arquivo no local exato da biblioteca com a versão de maior bitrate"
                        >
                          <Zap className="w-3 h-3 fill-current" />
                          <span>Substituir no Local</span>
                        </button>
                      )}

                      {/* Abrir Pasta de Origem da Faixa Nova no Finder */}
                      {item.caminho_novo && (
                        <button
                          type="button"
                          onClick={() => revealPath(item.caminho_novo)}
                          className="flex items-center gap-1 px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[10px] font-semibold border border-slate-700 cursor-pointer"
                          title={`Revelar arquivo novo no Finder:\n${item.caminho_novo}`}
                        >
                          <Folder className="w-3 h-3 text-serato-gold" />
                          <span>Origem</span>
                        </button>
                      )}

                      {/* Abrir Pasta da Crate de Destino no Finder */}
                      {item.caminho_completo && (
                        <button
                          type="button"
                          onClick={() => revealPath(item.caminho_completo)}
                          className="flex items-center gap-1 px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[10px] font-semibold border border-slate-700 cursor-pointer"
                          title={`Revelar arquivo atual no HD no Finder:\n${item.caminho_completo}`}
                        >
                          <ExternalLink className="w-3 h-3 text-serato-cyan" />
                          <span>HD Crate</span>
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}

              {/* Faixas Inéditas / Faltantes */}
              {(statusFilter === 'all' || statusFilter === 'missing') && filteredFaltantes.map((item: any, idx: number) => {
                const key = item.caminho_novo || item.solicitado;
                const isSelected = selectedMissing.has(key);
                const isIntegrated = integratedMissing.has(key);

                return (
                  <div
                    key={`missing-${idx}`}
                    className={`border p-2.5 rounded-lg flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2.5 transition ${
                      isIntegrated
                        ? 'bg-emerald-950/30 border-emerald-700/60'
                        : 'bg-serato-card border-rose-950/50 hover:bg-rose-950/10'
                    }`}
                  >
                    <div className="flex flex-col gap-1 flex-1 min-w-0 max-w-3xl">
                      <div className="flex items-center gap-2 truncate">
                        {matchResult?.tipo_origem === 'folder' && (
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelectMissing(key)}
                            className="rounded border-slate-700 bg-serato-dark text-emerald-400 focus:ring-0 cursor-pointer shrink-0"
                          />
                        )}

                        {isIntegrated ? (
                          <span className="text-[10px] bg-emerald-950 text-emerald-300 border border-emerald-600 px-2 py-0.5 rounded font-bold shrink-0 flex items-center gap-1 font-mono">
                            <Check className="w-3 h-3 text-emerald-400" />
                            INTEGRADA NA CRATE
                          </span>
                        ) : (
                          <span className="text-[10px] bg-rose-950 text-rose-300 border border-rose-800/40 px-1.5 py-0.5 rounded font-bold shrink-0 font-mono">
                            {matchResult?.tipo_origem === 'folder' ? '✨ INÉDITA / NOVA' : '⚠️ FALTANDO'}
                          </span>
                        )}

                        <span className="text-slate-200 font-sans font-medium truncate">{item.solicitado}</span>
                      </div>

                      {/* Metadados e Pasta de Origem */}
                      <div className="flex items-center gap-2 text-[10px] font-mono pl-6 text-slate-400 flex-wrap">
                        {item.novo_bitrate ? (
                          <span className="bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                            {item.novo_bitrate}k {item.novo_formato} · {formatSec(item.novo_duracao)}
                          </span>
                        ) : null}

                        {item.pasta_origem && (
                          <span className="bg-slate-800/80 text-slate-300 px-1.5 py-0.5 rounded border border-slate-700/60 truncate max-w-xs" title={item.pasta_origem}>
                            📁 Pasta Origem: {item.pasta_origem.split('/').pop()}
                          </span>
                        )}

                        {item.audio_seal_novo && (
                          <span className="text-slate-500 bg-slate-950 px-1.5 py-0.5 rounded border border-white/5 flex items-center gap-1" title={item.audio_seal_novo}>
                            <Hash className="w-2.5 h-2.5 text-slate-500" />
                            <span>Seal: {item.audio_seal_novo.slice(0, 8)}...</span>
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0 self-end sm:self-center">
                      {/* Botão de Integrar faixa individual na Crate */}
                      {matchResult?.tipo_origem === 'folder' && !isIntegrated && (
                        <button
                          type="button"
                          onClick={() => handleOpenIntegrateModal([item])}
                          className="flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-bold bg-emerald-950/60 hover:bg-emerald-900 text-emerald-300 border border-emerald-600/50 transition cursor-pointer shadow"
                          title="Copia esta música inédita para uma Crate existente ou nova no HD"
                        >
                          <PlusCircle className="w-3 h-3 text-emerald-400" />
                          <span>Integrar em Crate...</span>
                        </button>
                      )}

                      {/* Abrir Pasta de Origem da Faixa Nova no Finder */}
                      {item.caminho_novo && (
                        <button
                          type="button"
                          onClick={() => revealPath(item.caminho_novo)}
                          className="flex items-center gap-1 px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[10px] font-semibold border border-slate-700 cursor-pointer"
                          title={`Revelar arquivo no Finder:\n${item.caminho_novo}`}
                        >
                          <Folder className="w-3 h-3 text-serato-gold" />
                          <span>Origem</span>
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}

              {filteredEncontradas.length === 0 && filteredFaltantes.length === 0 && (
                <div className="py-8 text-center text-slate-500 font-sans">
                  Nenhuma faixa corresponde ao filtro "{searchTerm}".
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Modal de Integração de Músicas na Crate (Crate Existente vs Nova Crate) */}
      {integrateModal.isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-slate-900 border border-emerald-500/40 rounded-xl p-5 max-w-lg w-full shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <div className="flex items-center gap-2">
                <FolderPlus className="w-5 h-5 text-emerald-400" />
                <h4 className="text-sm font-bold text-white">Integrar Faixas na Biblioteca Serato</h4>
              </div>
              <button
                onClick={() => setIntegrateModal(prev => ({ ...prev, isOpen: false }))}
                className="text-slate-400 hover:text-white p-1 rounded cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3">
              <div className="text-xs text-slate-300">
                Você selecionou <b className="text-emerald-400 font-mono">{integrateModal.itemsToIntegrate.length}</b> faixa(s) inédita(s) para copiar para sua biblioteca:
              </div>

              {/* Seletor de Modo: Crate Existente ou Nova Crate */}
              <div className="grid grid-cols-2 gap-2 bg-slate-950 p-1 rounded-lg border border-slate-800">
                <button
                  type="button"
                  onClick={() => setIntegrateModal(prev => ({ ...prev, targetMode: 'existing' }))}
                  className={`py-1.5 px-3 rounded text-xs font-bold transition flex items-center justify-center gap-1.5 cursor-pointer ${
                    integrateModal.targetMode === 'existing'
                      ? 'bg-emerald-600 text-white shadow'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  <Folder className="w-3.5 h-3.5" />
                  <span>Crate Existente</span>
                </button>

                <button
                  type="button"
                  onClick={() => setIntegrateModal(prev => ({ ...prev, targetMode: 'new' }))}
                  className={`py-1.5 px-3 rounded text-xs font-bold transition flex items-center justify-center gap-1.5 cursor-pointer ${
                    integrateModal.targetMode === 'new'
                      ? 'bg-emerald-600 text-white shadow'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  <PlusCircle className="w-3.5 h-3.5" />
                  <span>Criar Nova Crate</span>
                </button>
              </div>

              {integrateModal.targetMode === 'existing' ? (
                <div className="space-y-2.5 bg-slate-950/60 p-3 rounded-lg border border-slate-800">
                  <div className="space-y-1">
                    <label className="text-xs text-slate-300 font-semibold">Selecione a Crate Principal:</label>
                    <select
                      value={integrateModal.selectedCrate}
                      onChange={(e) => {
                        const newCr = e.target.value;
                        const crData = cratesList.find(c => c.nome === newCr);
                        setIntegrateModal(prev => ({
                          ...prev,
                          selectedCrate: newCr,
                          selectedSubcrate: crData?.subcrates?.[0]?.nome || ''
                        }));
                      }}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:border-emerald-500 focus:outline-none cursor-pointer"
                    >
                      {cratesList.map(c => (
                        <option key={c.nome} value={c.nome}>📁 {c.nome} ({c.total} faixas)</option>
                      ))}
                    </select>
                  </div>

                  {activeCrateData && activeCrateData.subcrates?.length > 0 && (
                    <div className="space-y-1">
                      <label className="text-xs text-slate-300 font-semibold">Subcrate (Opcional):</label>
                      <select
                        value={integrateModal.selectedSubcrate}
                        onChange={(e) => setIntegrateModal(prev => ({ ...prev, selectedSubcrate: e.target.value }))}
                        className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-serato-cyan font-mono focus:border-emerald-500 focus:outline-none cursor-pointer"
                      >
                        <option value="">↳ Na Raiz de {integrateModal.selectedCrate}</option>
                        {activeCrateData.subcrates.map((sub: any) => (
                          <option key={sub.nome} value={sub.nome}>↳ Subcrate: {sub.nome} ({sub.total} faixas)</option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-2 bg-slate-950/60 p-3 rounded-lg border border-slate-800">
                  <label className="text-xs text-slate-300 font-semibold">Nome da Nova Crate / Pasta:</label>
                  <input
                    type="text"
                    value={integrateModal.newCrateName}
                    onChange={(e) => setIntegrateModal(prev => ({ ...prev, newCrateName: e.target.value }))}
                    placeholder="Ex: Afro House 2026, Novidades Funk, etc."
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-mono focus:border-emerald-500 focus:outline-none"
                    autoFocus
                  />
                  <p className="text-[11px] text-slate-400">
                    💡 Uma nova pasta será criada na sua raiz de músicas do Serato.
                  </p>
                </div>
              )}

              {/* Pré-visualização do destino no HD */}
              <div className="text-[11px] bg-slate-950 p-2.5 rounded border border-white/5 space-y-1">
                <div className="text-slate-400 font-medium">Pasta de Destino no HD:</div>
                <div className="text-emerald-400 font-mono text-[11px] truncate" title={previewTargetDestination}>
                  {previewTargetDestination}
                </div>
              </div>

              {integrateModal.error && (
                <div className="text-xs text-rose-400 bg-rose-950/50 border border-rose-800 p-2 rounded">
                  {integrateModal.error}
                </div>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-white/10">
              <button
                type="button"
                onClick={() => setIntegrateModal(prev => ({ ...prev, isOpen: false }))}
                disabled={integrateModal.isSaving}
                className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-300 hover:bg-slate-700 transition cursor-pointer"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={handleConfirmIntegrate}
                disabled={integrateModal.isSaving}
                className="px-4 py-1.5 rounded-lg text-xs font-bold bg-emerald-600 hover:bg-emerald-500 text-white transition cursor-pointer shadow-lg shadow-emerald-950/40"
              >
                {integrateModal.isSaving ? 'Copiando Faixas...' : `Copiar e Integrar (${integrateModal.itemsToIntegrate.length} faixas)`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal de Confirmação de Substituição de Upgrades */}
      {upgradeModal.isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="bg-slate-900 border border-serato-gold/40 rounded-xl p-5 max-w-lg w-full shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <div className="flex items-center gap-2">
                <Zap className="w-5 h-5 text-serato-gold" />
                <h4 className="text-sm font-bold text-white">Substituir com Upgrade de Qualidade</h4>
              </div>
              <button
                onClick={() => setUpgradeModal({ isOpen: false, itemsToUpgrade: [], isProcessing: false })}
                className="text-slate-400 hover:text-white p-1 rounded cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-2.5 text-xs text-slate-300">
              <p>
                Deseja sobrescrever as <b className="text-serato-gold font-mono">{upgradeModal.itemsToUpgrade.length}</b> faixas antigas de menor qualidade pelas novas versões de alta fidelidade?
              </p>
              
              <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 space-y-1.5 text-[11px]">
                <div className="text-emerald-400 font-bold flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>Substituição no próprio local do HD</span>
                </div>
                <p className="text-slate-400">
                  Os arquivos serão sobrescritos exatamente onde já moram na sua biblioteca. Nenhuma pasta será movimentada.
                </p>
                <div className="text-serato-cyan font-bold flex items-center gap-1.5 pt-1">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>Preservação de Hot Cues e Beatgrid</span>
                </div>
                <p className="text-slate-400">
                  Todas as tags e marcadores do Serato DJ serão clonados para a nova faixa, e os áudios antigos serão guardados com segurança na quarentena.
                </p>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-white/10">
              <button
                type="button"
                onClick={() => setUpgradeModal({ isOpen: false, itemsToUpgrade: [], isProcessing: false })}
                disabled={upgradeModal.isProcessing}
                className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-300 hover:bg-slate-700 transition cursor-pointer"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={handleConfirmReplaceUpgrades}
                disabled={upgradeModal.isProcessing}
                className="px-4 py-1.5 rounded-lg text-xs font-bold bg-serato-gold hover:opacity-90 text-black transition cursor-pointer shadow-lg shadow-amber-950/40"
              >
                {upgradeModal.isProcessing ? 'Substituindo...' : `Substituir ${upgradeModal.itemsToUpgrade.length} Faixas no Local`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
