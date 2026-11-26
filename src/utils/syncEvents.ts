export interface SyncFinishedPayload {
  success: boolean;
  exit_code?: number | null;
  message?: string;
  summary?: unknown;
}

export interface SyncFeedback {
  ok: boolean;
  logMessage: string;
  bannerType: 'success' | 'error';
  bannerMessage: string;
  summary?: unknown;
}

/**
 * Interpreta de forma segura o evento `sync-finished` emitido pelo backend Rust.
 * Só considera sucesso quando `payload.success === true` de forma explícita.
 */
export function interpretSyncFinishedEvent(payload: unknown): SyncFeedback {
  if (!payload || typeof payload !== 'object') {
    return {
      ok: false,
      logMessage: '❌ Sincronização encerrada com payload inválido ou ausente do backend.',
      bannerType: 'error',
      bannerMessage: 'Sincronização encerrada com resposta inválida ou ausente do backend.',
    };
  }

  const data = payload as Record<string, unknown>;
  const hasExplicitBool = typeof data.success === 'boolean';
  const normalizedSummary =
    data.summary && typeof data.summary === 'object' && !Array.isArray(data.summary)
      ? data.summary
      : undefined;
  const rawMessage =
    typeof data.message === 'string' && data.message.trim().length > 0
      ? data.message.trim()
      : undefined;

  if (!hasExplicitBool) {
    return {
      ok: false,
      logMessage: `❌ Sincronização encerrada sem status explícito${rawMessage ? `: ${rawMessage}` : '.'}`,
      bannerType: 'error',
      bannerMessage: rawMessage || 'Sincronização encerrada sem confirmação explícita de sucesso.',
      summary: normalizedSummary,
    };
  }

  if (data.success === true) {
    const msg = rawMessage || 'Sincronização concluída com sucesso.';
    return {
      ok: true,
      logMessage: `✅ ${msg}`,
      bannerType: 'success',
      bannerMessage: msg,
      summary: normalizedSummary,
    };
  }

  const errMsg = rawMessage || 'Falha na sincronização. Verifique os logs para detalhes.';
  return {
    ok: false,
    logMessage: `❌ Falha na sincronização: ${errMsg}`,
    bannerType: 'error',
    bannerMessage: errMsg,
    summary: normalizedSummary,
  };
}
