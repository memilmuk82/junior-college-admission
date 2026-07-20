// @ts-check
import { mkdirSync } from 'node:fs';

import { test, expect } from '@playwright/test';

const appUrl = (process.env.PHASE18_E2E_URL || '').replace(/\/$/, '');
const adminUsername = process.env.PHASE18_ADMIN_USERNAME || '';
const adminPassword = process.env.PHASE18_ADMIN_PASSWORD || '';
const screenshotDir = '/tmp/phase18-qa';
const authRequestIntervalMs = Number(
  process.env.E2E_AUTH_REQUEST_INTERVAL_MS || (appUrl.startsWith('https://') ? '3200' : '0'),
);
let lastAuthRequestAt = 0;

function requireEnvironment() {
  if (!appUrl || !adminUsername || !adminPassword) {
    test.skip(
      true,
      'PHASE18_E2E_URL, PHASE18_ADMIN_USERNAME, PHASE18_ADMIN_PASSWORD are required',
    );
  }
  mkdirSync(screenshotDir, { recursive: true });
}

async function paceAuthRequest() {
  const remaining = authRequestIntervalMs - (Date.now() - lastAuthRequestAt);
  if (remaining > 0) await new Promise((resolve) => setTimeout(resolve, remaining));
  lastAuthRequestAt = Date.now();
}

async function gotoLogin(page) {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await paceAuthRequest();
    const response = await page.goto(`${appUrl}/auth/login?account_type=teacher`);
    if (response?.status() !== 429) return;
  }
  throw new Error('운영 로그인 rate limit이 해제되지 않았습니다.');
}

async function login(page) {
  await gotoLogin(page);
  await expect(page.getByRole('heading', { name: '역할 통합 로그인' })).toBeVisible();
  await page.locator('input[name="username"]').fill(adminUsername);
  await page.locator('input[name="password"]').fill(adminPassword);
  await paceAuthRequest();
  const responsePromise = page.waitForResponse((response) => (
    response.url().startsWith(`${appUrl}/auth/login`)
      && response.request().method() === 'POST'
  ));
  await page.getByRole('button', { name: /^로그인/ }).click();
  const response = await responsePromise;
  expect(response.status()).not.toBe(429);
  expect(response.status()).toBe(302);
}

async function demoPassword(page) {
  await gotoLogin(page);
  const value = await page.locator('.demo-credentials dl').last().locator('code').textContent();
  expect(value).toBeTruthy();
  return value || '';
}

async function logout(page) {
  if (!page.url().endsWith('/dashboard')) await page.goto(`${appUrl}/dashboard`);
  const form = page.locator('form[action="/auth/logout"]');
  await expect(form).toBeVisible();
  await paceAuthRequest();
  await form.getByRole('button', { name: '로그아웃' }).click();
  await expect(page).toHaveURL(/\/auth\/login/);
  await expect(page.getByRole('heading', { name: '역할 통합 로그인' })).toBeVisible();
}

async function expectNoFrameworkOverlay(page) {
  await expect(
    page.locator('nextjs-portal, vite-error-overlay, #webpack-dev-server-client-overlay'),
  ).toHaveCount(0);
}

test('실사용 주 관리자는 관리자와 교사 업무 및 암호화 BYOK 메타를 함께 확인한다', async ({ page }) => {
  requireEnvironment();
  let consoleErrorCount = 0;
  let pageErrorCount = 0;
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrorCount += 1;
  });
  page.on('pageerror', () => {
    pageErrorCount += 1;
  });

  await login(page);
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page).toHaveTitle(/역할별 업무공간/);
  await expect(page.getByRole('heading', { name: '주 관리자 업무공간' })).toBeVisible();
  await expectNoFrameworkOverlay(page);

  const expectedAdminLinks = [
    ['회원 역할·상태 관리', '/admin/members'],
    ['입시결과 등록', '/admin/admission-results'],
    ['전문대학포털 수집', '/admin/admission-results#procollege-collection'],
    ['모집요강 자료 등록', '/admin/sources'],
    ['대학·학과·전형 기준정보', '/admin/catalog'],
    ['입시 규칙 검수·게시', '/admin/rules'],
  ];
  for (const [name, href] of expectedAdminLinks) {
    await expect(page.getByRole('link', { name })).toHaveAttribute('href', href);
  }
  await expect(page.getByRole('heading', { name: '교사 업무' })).toBeVisible();
  await expect(page.getByRole('link', { name: '학과·학급 학생 관리' })).toHaveAttribute(
    'href',
    '/teacher/classrooms',
  );
  await expect(page.getByRole('link', { name: '학생 상담자료 만들기' })).toHaveAttribute(
    'href',
    '/admin/consultations/new',
  );
  await expect(page.getByRole('link', { name: '내 BYOK AI 설정' })).toHaveAttribute(
    'href',
    '/admin/ai/settings',
  );
  await page.screenshot({
    path: `${screenshotDir}/phase18-main-admin-workspace.png`,
    fullPage: true,
  });

  const classroomsResponse = await page.goto(`${appUrl}/teacher/classrooms`);
  expect(classroomsResponse?.status()).toBe(200);
  await expect(page).toHaveTitle(/학과·학급 학생 관리/);
  await expect(page.getByRole('heading', { name: '학과·학급과 학생 성적' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '학과·학급 추가' })).toBeVisible();
  const classroomForm = page.locator('form[action="/teacher/classrooms"]');
  await expect(classroomForm).toBeVisible();
  await expect(classroomForm.locator('input[name="academic_year"]')).toHaveValue('2027');
  await expect(classroomForm.locator('input[name="department_name"]')).toBeEditable();
  await expect(classroomForm.locator('input[name="class_name"]')).toBeEditable();
  await expect(classroomForm.getByRole('button', { name: '학급 만들기' })).toBeEnabled();
  await expectNoFrameworkOverlay(page);
  await page.screenshot({
    path: `${screenshotDir}/phase18-main-admin-classrooms.png`,
    fullPage: true,
  });

  const byokResponse = await page.goto(`${appUrl}/admin/ai/settings`);
  expect(byokResponse?.status()).toBe(200);
  await expect(page).toHaveTitle(/BYOK AI 설정/);
  await expect(page.getByRole('heading', { name: '내 공급자 키' })).toBeVisible();
  const openAiRow = page.locator('tbody tr', {
    has: page.getByRole('cell', { name: 'OPENAI', exact: true }),
  }).first();
  await expect(openAiRow).toBeVisible();
  const hasMaskedMetadata = await openAiRow.locator('td').nth(1).evaluate((cell) => (
    /^••••[^\s]{4}$/u.test(cell.textContent?.trim() || '')
  ));
  expect(hasMaskedMetadata).toBe(true);
  await expect(page.locator('#ai-api-key')).toHaveAttribute('type', 'password');
  await expect(page.locator('#ai-api-key')).toHaveValue('');
  const rawOpenAiKeyIsPresent = await page.locator('html').evaluate((element) => (
    /sk-(?:(?:proj|svcacct)-)?[A-Za-z0-9_-]{12,}/u.test(element.outerHTML)
  ));
  expect(rawOpenAiKeyIsPresent).toBe(false);
  await expectNoFrameworkOverlay(page);
  await page.screenshot({
    path: `${screenshotDir}/phase18-main-admin-byok-masked.png`,
    fullPage: true,
  });

  await page.goto(`${appUrl}/dashboard`);
  await expect(page.getByRole('link', { name: '회원 역할·상태 관리' })).toHaveAttribute(
    'href',
    '/admin/members',
  );
  await expect(page.getByRole('link', { name: '모집요강 자료 등록' })).toHaveAttribute(
    'href',
    '/admin/sources',
  );

  await logout(page);
  await page.screenshot({
    path: `${screenshotDir}/phase18-logged-out.png`,
    fullPage: false,
  });
  expect(consoleErrorCount).toBe(0);
  expect(pageErrorCount).toBe(0);
});

test('기존 데모 로그인 세션에서도 실사용 주 관리자로 전환할 수 있다', async ({ page }) => {
  requireEnvironment();
  const publicPassword = await demoPassword(page);
  await page.locator('input[name="username"]').fill('demo-main-admin');
  await page.locator('input[name="password"]').fill(publicPassword);
  await paceAuthRequest();
  const demoLoginResponse = page.waitForResponse((response) => (
    response.url().startsWith(`${appUrl}/auth/login`)
      && response.request().method() === 'POST'
  ));
  await page.getByRole('button', { name: /^로그인/ }).click();
  expect((await demoLoginResponse).status()).toBe(302);
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading', { name: '주 관리자 업무공간' })).toBeVisible();

  await login(page);
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByText('메인 관리자 교사 · ADMIN')).toBeVisible();
  await expect(page.getByRole('heading', { name: '교사 업무' })).toBeVisible();
  await page.screenshot({
    path: `${screenshotDir}/phase18-demo-session-account-switch.png`,
    fullPage: false,
  });
  await logout(page);
});
