import { test, expect } from '@playwright/test';

const apiKey = process.env.GUARDIAN_API_BEARER_KEY;

test('Twin reading authorizes and verifies a signed action token, then rejects replay', async ({ page }) => {
  test.skip(!apiKey, 'Set GUARDIAN_API_BEARER_KEY for the isolated local Twin test server.');
  await page.goto('/');

  const result = await page.evaluate(async (key) => {
    const runId = `pw-${crypto.randomUUID()}`;
    const readingId = `${runId}-reading`;
    const twinEvent = {
      event: 'readings',
      data: {
        run_id: runId,
        readings: [{
          run_id: runId,
          reading_id: readingId,
          device_id: `${runId}-device`,
          node_id: 'PWR-01',
          timestamp: new Date().toISOString(),
          tick: 1,
          sensor: 'load_kw',
          value: 450,
          unit: 'kW',
          lat: 37.27,
          lon: 9.87,
        }],
      },
    };
    const post = async (path, body, authenticated = true) => {
      const response = await fetch(path, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authenticated ? { Authorization: `Bearer ${key}` } : {}),
        },
        body: JSON.stringify(body),
      });
      return { status: response.status, body: await response.json() };
    };

    const missingKey = await post('/api/integrations/twin/event', twinEvent, false);
    const ingestion = await post('/api/integrations/twin/event', twinEvent);
    const authorization = await post('/api/actions/authorize', {
      run_id: runId,
      reading_id: readingId,
      action: 'set_grid_switch',
      parameters: { state: 'open' },
      risk_level: 'NONE',
      domain: 'Power',
    });
    let verification = { status: null, body: null };
    let replay = { status: null, body: null };
    if (authorization.status === 200) {
      const verifyBody = {
        token: authorization.body.token,
        action: authorization.body.action,
        parameters: { state: 'open' },
      };
      verification = await post('/api/actions/verify', verifyBody);
      replay = await post('/api/actions/verify', verifyBody);
    }

    const summary = {
      runId,
      missingKeyStatus: missingKey.status,
      twinIngestionStatus: ingestion.status,
      processedReadings: ingestion.body.processed,
      authorizationStatus: authorization.status,
      action: authorization.body.action,
      tokenIssued: Boolean(authorization.body.token),
      verificationStatus: verification.status,
      tokenVerified: verification.body.verified,
      replayStatus: replay.status,
      replayRejected: replay.status === 401,
      replayReason: replay.body.detail,
    };
    const output = document.createElement('pre');
    output.id = 'twin-test-result';
    output.style.cssText = 'position:fixed;inset:16px auto auto 16px;z-index:99999;max-width:650px;padding:16px;background:#08120f;color:#b8f16b;border:1px solid #526b45;border-radius:8px;font:14px/1.6 monospace;white-space:pre-wrap';
    output.textContent = `Twin + signed token browser test\\n${JSON.stringify(summary, null, 2)}`;
    document.body.append(output);
    return summary;
  }, apiKey);

  console.log('Twin/action-token browser test:', JSON.stringify(result));
  expect(result.missingKeyStatus).toBe(401);
  expect(result.twinIngestionStatus).toBe(200);
  expect(result.processedReadings).toBe(1);
  expect(result.authorizationStatus).toBe(200);
  expect(result.action).toBe('set_grid_switch');
  expect(result.tokenIssued).toBe(true);
  expect(result.verificationStatus).toBe(200);
  expect(result.tokenVerified).toBe(true);
  expect(result.replayStatus).toBe(401);
  expect(result.replayRejected).toBe(true);
  await expect(page.locator('#twin-test-result')).toContainText('"tokenVerified": true');
});
