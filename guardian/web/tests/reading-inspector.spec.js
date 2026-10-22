import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  // The playground is intentionally same-origin and local. Any attempted
  // external request is blocked so the test exercises the offline path.
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === '127.0.0.1' || url.hostname === 'localhost') return route.continue();
    return route.abort();
  });
  await page.goto('/');
  await expect(page.getByText('Local model ready')).toBeVisible({ timeout: 15000 });
});

test('preset selection follows the loaded fields and edits switch to Custom', async ({ page }) => {
  const fakeFlood = page.getByRole('button', { name: 'Fake flood · T5' });
  await fakeFlood.click();
  await expect(fakeFlood).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByLabel('Observed value in cm')).toHaveValue('180');

  await page.getByLabel('Z-score').fill('44');
  await expect(page.locator('.custom-state')).toHaveText('Custom');
  await expect(fakeFlood).toHaveAttribute('aria-pressed', 'false');
});

test('real saved model renders below-threshold, near-threshold and suspicious states', async ({ page }) => {
  await page.getByRole('button', { name: 'Normal', exact: true }).click();
  await page.getByRole('button', { name: 'Evaluate reading' }).click();
  await expect(page.locator('.result-state')).toContainText('Below alert threshold');
  await expect(page.locator('.probability')).toContainText('20.9');

  await page.getByLabel('Reading presets').getByRole('button', { name: 'Adaptive ramp' }).click();
  await page.getByRole('button', { name: 'Evaluate reading' }).click();
  await expect(page.locator('.result-state')).toContainText('Near threshold — ignored by scoring');

  await page.getByRole('button', { name: 'Fake flood · T5' }).click();
  await page.getByRole('button', { name: 'Evaluate reading' }).click();
  await expect(page.locator('.result-state')).toContainText('Suspicious pattern');
  await expect(page.locator('.probability')).toContainText('100.0');
});

test('JSON null renders unavailable without fabricating a probability', async ({ page }) => {
  await page.getByLabel('Observed value in cm').fill('');
  await page.getByRole('button', { name: 'Evaluate reading' }).click();
  await expect(page.locator('.result-state')).toContainText('Model unavailable — Guardian rules decide');
  await expect(page.locator('.probability')).toHaveCount(0);
  await expect(page.locator('.unavailable-callout')).toBeVisible();
});

test('presets are keyboard operable and local-only with external network blocked', async ({ page }) => {
  const smartSpoof = page.getByRole('button', { name: 'Smart spoof' });
  await smartSpoof.focus();
  await page.keyboard.press('Enter');
  await expect(smartSpoof).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Evaluate reading' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('.result-state')).toContainText('Suspicious pattern');
});

test('the unified dashboard displays backend pipeline results and the event trace', async ({ page }) => {
  await page.request.post('/api/reset');
  await page.getByRole('button', { name: 'Fake fire alert' }).click();
  await page.getByRole('button', { name: 'Run simulation' }).click();
  await expect(page.getByText('Fake fire alert', { exact: false }).first()).toBeVisible();
  await expect(page.locator('.demo-result-grid')).toContainText('compromised');
  await expect(page.locator('.demo-result-grid')).toContainText('blocked');
  await expect(page.locator('.pipeline-stages')).toContainText('Random Forest');
  await expect(page.getByText('Model features', { exact: true })).toBeVisible();
  await expect(page.locator('.demo-feature-list code').first()).toBeVisible();
  await expect(page.getByText('Score breakdown', { exact: true })).toBeVisible();
  await expect(page.getByText('Reputation change', { exact: true })).toBeVisible();
  await expect(page.locator('.demo-timeline')).toContainText('guardian verdict');
  await expect(page.locator('.demo-metric').filter({ hasText: 'Processed readings' })).not.toContainText('—');
});

test('a stopped advisory API shows no probability and leaves evaluation unavailable', async ({ page }) => {
  await page.route('**/api/capabilities', (route) => route.abort());
  await page.reload();
  await expect(page.getByText('Model unavailable — Guardian rules decide', { exact: true }).first()).toBeVisible();
  await expect(page.locator('.probability')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Evaluate reading' })).toHaveCount(0);
});
