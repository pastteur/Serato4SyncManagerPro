export interface DuplicateItem {
  id: string;
  nome: string;
  copia: string;
  original: string;
  caminho_copia?: string;
  caminho_original?: string;
  tamanho: number;
}

export interface CrateTrack {
  nome: string;
  caminho_rel: string;
  caminho_abs?: string;
  formato: string;
}

export interface CrateTreeItem {
  nome_crate: string;
  nome_exibicao: string;
  master: string;
  subcrate: string;
  total_faixas: number;
  faixas: CrateTrack[];
}

export interface SyncSummary {
  sucesso: boolean;
  dry_run?: boolean;
  total_faixas: number;
  crates_gravadas: number;
  crates_inalteradas: number;
  faixas_adicionadas: number;
  faixas_removidas: number;
  total_duplicados: number;
  csv_duplicados: string | null;
  duplicados: DuplicateItem[];
  crates_arvore?: Record<string, CrateTreeItem>;
  movimentacoes: string[];
}

export interface LogEntry {
  id: string;
  timestamp: string;
  message: string;
  type: 'info' | 'add' | 'remove' | 'delete' | 'create' | 'success' | 'warning' | 'error' | 'cache' | 'analysis';
}
