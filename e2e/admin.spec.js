// @ts-check
import { test, expect } from '@playwright/test';

const adminUrl = process.env.ADMIN_URL;
const adminUsername = process.env.ADMIN_USERNAME;
const adminPassword = process.env.ADMIN_PASSWORD;

async function login(page) {
  await page.goto(`${adminUrl}/admin/login`);
  await page.getByLabel('관리자 ID').fill(adminUsername);
  await page.getByLabel('비밀번호').fill(adminPassword);
  await page.getByRole('button', { name: '검수 화면으로 이동' }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading', { name: '주 관리자 업무공간' })).toBeVisible();
  await expect(page.getByRole('link', { name: '회원 역할·상태 관리' })).toBeVisible();
  await expect(page.getByRole('link', { name: '입시결과 등록' })).toBeVisible();
  await expect(page.getByRole('link', { name: '전문대학포털 수집' })).toBeVisible();
  await expect(page.getByRole('link', { name: '모집요강 자료 등록' })).toBeVisible();
}

test('admin reviews CSV validation without unnamed controls or console errors', async ({ page }) => {
  if (!adminUrl || !adminUsername || !adminPassword) {
    test.skip(true, 'ADMIN_URL, ADMIN_USERNAME, and ADMIN_PASSWORD are required');
  }
  const consoleErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await login(page);
  await page.getByRole('link', { name: '입시 규칙 검수·게시' }).click();
  await expect(page.getByRole('heading', { name: '규칙 검수 대기열' })).toBeVisible();
  await page.getByRole('link', { name: '성적 규칙 CSV 검토' }).click();
  await expect(page.getByRole('heading', { name: '성적 규칙 CSV 검토' })).toBeVisible();

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

  await page.getByLabel('score_rules.csv').setInputFiles({
    name: 'score_rules.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('schema_version\n1\n', 'utf8'),
  });
  await page.getByRole('button', { name: '검증하고 미리보기' }).click();
  await expect(page.getByRole('heading', { name: '오류' })).toBeVisible();
  await expect(page.getByText('헤더가 고정 CSV 양식과 일치하지 않습니다.')).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test('admin mobile page has no horizontal overflow', async ({ page }) => {
  if (!adminUrl || !adminUsername || !adminPassword) {
    test.skip(true, 'ADMIN_URL, ADMIN_USERNAME, and ADMIN_PASSWORD are required');
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth
  );
  expect(hasHorizontalOverflow).toBe(false);
  await expect(page.getByRole('link', { name: '입시 규칙 검수·게시' })).toBeVisible();
});

test.describe('admin without JavaScript', () => {
  test.use({ javaScriptEnabled: false });

  test('server-rendered login and role workspace remain usable', async ({ page }) => {
    if (!adminUrl || !adminUsername || !adminPassword) {
      test.skip(true, 'ADMIN_URL, ADMIN_USERNAME, and ADMIN_PASSWORD are required');
    }
    await login(page);
    await expect(page.getByRole('link', { name: '입시 규칙 검수·게시' })).toBeVisible();
  });
});
