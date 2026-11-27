import { describe, expect, it } from 'bun:test';
import { interpretSyncFinishedEvent } from '../src/utils/syncEvents';

describe('interpretSyncFinishedEvent', () => {
  it('exibe sucesso apenas quando success === true e preserva mensagem do backend', () => {
    const res = interpretSyncFinishedEvent({
      success: true,
      exit_code: 0,
      message: 'Sincronização concluída com sucesso.',
    });
    expect(res.ok).toBe(true);
    expect(res.bannerType).toBe('success');
    expect(res.bannerMessage).toBe('Sincronização concluída com sucesso.');
    expect(res.logMessage).toContain('✅');
  });

  it('exibe erro quando success === false com mensagem do backend', () => {
    const res = interpretSyncFinishedEvent({
      success: false,
      exit_code: 1,
      message: 'Erro no motor Python (código 1): Falha na gravação da crate.',
    });
    expect(res.ok).toBe(false);
    expect(res.bannerType).toBe('error');
    expect(res.bannerMessage).toContain('Falha na gravação da crate');
    expect(res.logMessage).toContain('❌');
  });

  it('trata evento malformado sem status booleano como falha', () => {
    const res = interpretSyncFinishedEvent({ success: 'true', message: 'ambíguo' });
    expect(res.ok).toBe(false);
    expect(res.bannerType).toBe('error');
    expect(res.logMessage).toContain('❌');
  });

  it('trata evento ausente (undefined/null) sem travar a interface', () => {
    const resUndefined = interpretSyncFinishedEvent(undefined);
    expect(resUndefined.ok).toBe(false);
    expect(resUndefined.bannerType).toBe('error');

    const resNull = interpretSyncFinishedEvent(null);
    expect(resNull.ok).toBe(false);
    expect(resNull.bannerType).toBe('error');
  });

  it('propaga summary quando enviado no payload final de sync-finished', () => {
    const summaryObj = {
      sucesso: true,
      total_faixas: 120,
      crates_gravadas: 4,
    };
    const res = interpretSyncFinishedEvent({
      success: true,
      exit_code: 0,
      message: 'Sincronização concluída com sucesso.',
      summary: summaryObj,
    });
    expect(res.ok).toBe(true);
    expect(res.summary).toEqual(summaryObj);
  });

  it('normaliza summary nulo ou ausente para undefined sem quebrar o fluxo via sync-log', () => {
    const res = interpretSyncFinishedEvent({
      success: true,
      exit_code: 0,
      message: 'Sincronização concluída com sucesso.',
      summary: null,
    });
    expect(res.ok).toBe(true);
    expect(res.summary).toBeUndefined();
    expect(res.canApprove).toBe(false);
    expect(res.approvedPlanId).toBeNull();
  });

  it('QA-03: bloqueia aprovação quando feedback.success === false mesmo com summary positivo', () => {
    const res = interpretSyncFinishedEvent({
      success: false,
      exit_code: 1,
      message: 'Processo Python encerrou com erro',
      summary: {
        sucesso: true,
        dry_run: true,
        plan_id: 'plan-abc',
      },
    });
    expect(res.ok).toBe(false);
    expect(res.canApprove).toBe(false);
    expect(res.approvedPlanId).toBeNull();
  });

  it('QA-03: libera aprovação somente com success===true, dry_run===true, sucesso===true e plan_id válido', () => {
    const okRes = interpretSyncFinishedEvent({
      success: true,
      exit_code: 0,
      summary: {
        sucesso: true,
        dry_run: true,
        plan_id: 'plan-valid-001',
      },
    });
    expect(okRes.canApprove).toBe(true);
    expect(okRes.approvedPlanId).toBe('plan-valid-001');

    const partialRes = interpretSyncFinishedEvent({
      success: true,
      exit_code: 0,
      summary: {
        sucesso: true,
        dry_run: true,
        status_analise: 'parcial_com_erros',
        plan_id: 'plan-valid-001',
      },
    });
    expect(partialRes.canApprove).toBe(false);
    expect(partialRes.approvedPlanId).toBeNull();
  });
});
