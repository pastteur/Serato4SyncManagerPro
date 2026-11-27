export interface SyncFinishedPayload {
  success: boolean;
  exit_code?: number | null;
  message?: string;
  summary?: unknown;
}

export interface SyncFeedback {
  ok: boolean;
  canApprove: boolean;
  approvedPlanId: string | null;
  logMessage: string;
  bannerType: 'success' | 'error';
  bannerMessage: string;
  summary?: unknown;
}

/**
 * Valida todas as condições obrigatórias para liberar a aprovação (botão Ajustar)
 * após uma execução de análise (QA-03).
 */
export function evaluateSyncPlanApproval(
  feedbackOk: boolean,
  summary: unknown
): { canApprove: boolean; approvedPlanId: string | null } {
  if (!feedbackOk || !summary || typeof summary !== 'object' || Array.isArray(summary)) {
    return { canApprove: false, approvedPlanId: null };
  }
  const sum = summary as Record<string, unknown>;
  const hasValidPlanId = typeof sum.plan_id === 'string' && sum.plan_id.trim().length > 0;
  const hasImpeditiveErrors = sum.status_analise === 'parcial_com_erros' || sum.estado_parcial === true;
  if (sum.dry_run === true && sum.sucesso === true && hasValidPlanId && !hasImpeditiveErrors) {
    return { canApprove: true, approvedPlanId: (sum.plan_id as string).trim() };
  }
  return { canApprove: false, approvedPlanId: null };
}

/**
 * Interpreta de forma segura o evento `sync-finished` emitido pelo backend Rust.
 * Só considera sucesso quando `payload.success === true` de forma explícita.
 */
export function interpretSyncFinishedEvent(payload: unknown): SyncFeedback {
  if (!payload || typeof payload !== 'object') {
    return {
      ok: false,
      canApprove: false,
      approvedPlanId: null,
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
      canApprove: false,
      approvedPlanId: null,
      logMessage: `❌ Sincronização encerrada sem status explícito${rawMessage ? `: ${rawMessage}` : '.'}`,
      bannerType: 'error',
      bannerMessage: rawMessage || 'Sincronização encerrada sem confirmação explícita de sucesso.',
      summary: normalizedSummary,
    };
  }

  if (data.success === true) {
    const sumObj = normalizedSummary as Record<string, unknown> | undefined;
    const isPartial =
      sumObj?.estado_parcial === true || sumObj?.status_analise === 'parcial_com_erros';
    if (isPartial) {
      const msg =
        rawMessage || 'Operação concluída parcialmente com alertas. Verifique os logs.';
      return {
        ok: true,
        canApprove: false,
        approvedPlanId: null,
        logMessage: `⚠️ ${msg}`,
        bannerType: 'error',
        bannerMessage: msg,
        summary: normalizedSummary,
      };
    }
    const msg = rawMessage || 'Sincronização concluída com sucesso.';
    const approval = evaluateSyncPlanApproval(true, normalizedSummary);
    return {
      ok: true,
      canApprove: approval.canApprove,
      approvedPlanId: approval.approvedPlanId,
      logMessage: `✅ ${msg}`,
      bannerType: 'success',
      bannerMessage: msg,
      summary: normalizedSummary,
    };
  }

  const sumObj = normalizedSummary as Record<string, unknown> | undefined;
  const isPlanInvalidated = sumObj?.plan_invalidated === true;
  const isCancelled =
    typeof rawMessage === 'string' && rawMessage.toLowerCase().includes('cancelad');
  const errMsg = isPlanInvalidated
    ? 'Plano invalidado: a biblioteca ou crates foram alteradas após a análise. Execute o Modo Análise novamente.'
    : isCancelled
    ? rawMessage || 'Operação cancelada.'
    : rawMessage || 'Falha na sincronização. Verifique os logs para detalhes.';
  return {
    ok: false,
    canApprove: false,
    approvedPlanId: null,
    logMessage: `❌ ${isPlanInvalidated ? 'Plano invalidado' : isCancelled ? 'Operação cancelada' : 'Falha na sincronização'}: ${errMsg}`,
    bannerType: 'error',
    bannerMessage: errMsg,
    summary: normalizedSummary,
  };
}
