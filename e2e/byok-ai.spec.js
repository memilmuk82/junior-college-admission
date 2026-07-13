// @ts-check
import { test, expect } from '@playwright/test';

const adminUrl = process.env.ADMIN_URL;
const adminUsername = process.env.ADMIN_USERNAME;
const adminPassword = process.env.ADMIN_PASSWORD;
const screenshotDir = process.env.SCREENSHOT_DIR || '/tmp';

async function login(page) {
  await page.goto(`${adminUrl}/admin/login`);
  await page.getByLabel('관리자 ID').fill(adminUsername);
  await page.getByLabel('비밀번호').fill(adminPassword);
  await page.getByRole('button', { name: '검수 화면으로 이동' }).click();
  await expect(page.getByRole('heading', { name: '규칙 검수 대기열' })).toBeVisible();
}

test('admin stores only a masked BYOK key and can delete it without JavaScript-only controls', async ({
  page,
}) => {
  if (!adminUrl || !adminUsername || !adminPassword) {
    test.skip(true, 'ADMIN_URL, ADMIN_USERNAME, and ADMIN_PASSWORD are required');
  }
  const consoleErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  await login(page);
  await page.getByRole('link', { name: 'BYOK AI 설정' }).click();
  await expect(page.getByRole('heading', { name: '선택적 AI 상담 초안' })).toBeVisible();
  await expect(page.getByText(/자격·점수·합격 가능성을 판단하지 않습니다/)).toBeVisible();

  await page.getByLabel('공급자', { exact: true }).selectOption('OPENAI');
  await page.getByLabel('API 키', { exact: true }).fill('synthetic-browser-provider-key-1234');
  await page.getByRole('button', { name: '암호화 저장 또는 교체' }).click();

  await expect(page.getByText('••••1234')).toBeVisible();
  await expect(page.locator('body')).not.toContainText('synthetic-browser-provider-key');
  const unnamedControls = await page
    .locator('input:not([type="hidden"]), textarea, select, button')
    .evaluateAll((controls) =>
      controls
        .filter(
          (control) =>
            !control.labels?.length &&
            !control.getAttribute('aria-label') &&
            !control.textContent?.trim()
        )
        .map((control) => control.outerHTML)
    );
  expect(unnamedControls).toEqual([]);
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth
  );
  expect(hasHorizontalOverflow).toBe(false);
  await page.screenshot({ path: `${screenshotDir}/byok-ai-settings.png`, fullPage: true });

  await page.getByRole('button', { name: '키 삭제' }).click();
  await expect(page.getByText('••••1234')).toHaveCount(0);
  expect(consoleErrors).toEqual([]);
});

test.describe('BYOK settings without JavaScript', () => {
  test.use({ javaScriptEnabled: false });

  test('server-rendered key form remains usable', async ({ page }) => {
    if (!adminUrl || !adminUsername || !adminPassword) {
      test.skip(true, 'ADMIN_URL, ADMIN_USERNAME, and ADMIN_PASSWORD are required');
    }
    await login(page);
    await page.getByRole('link', { name: 'BYOK AI 설정' }).click();
    await page.getByLabel('공급자', { exact: true }).selectOption('GEMINI');
    await page.getByLabel('API 키', { exact: true }).fill('synthetic-no-js-provider-key-5678');
    await page.getByRole('button', { name: '암호화 저장 또는 교체' }).click();
    await expect(page.getByText('••••5678')).toBeVisible();
    await page.getByRole('button', { name: '키 삭제' }).click();
    await expect(page.getByText('••••5678')).toHaveCount(0);
  });
});
