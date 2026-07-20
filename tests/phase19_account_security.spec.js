// @ts-check
import { mkdirSync } from 'node:fs';

import { test, expect } from '@playwright/test';

const appUrl = (process.env.PHASE19_E2E_URL || '').replace(/\/$/, '');
const accountIdentifier = process.env.PHASE19_ACCOUNT_IDENTIFIER || '';
const accountPassword = process.env.PHASE19_ACCOUNT_PASSWORD || '';
const screenshotDir = '/tmp/phase19-qa';
const authRequestIntervalMs = Number(
  process.env.E2E_AUTH_REQUEST_INTERVAL_MS || (appUrl.startsWith('https://') ? '3200' : '0'),
);
let lastAuthRequestAt = 0;

function requireUrl() {
  if (!appUrl) test.skip(true, 'PHASE19_E2E_URL is required');
  mkdirSync(screenshotDir, { recursive: true });
}

function requireAccount() {
  if (!accountIdentifier || !accountPassword) {
    test.skip(
      true,
      'PHASE19_ACCOUNT_IDENTIFIER and PHASE19_ACCOUNT_PASSWORD are required',
    );
  }
}

function collectRuntimeIssues(page) {
  /** @type {string[]} */
  const issues = [];
  page.on('console', (message) => {
    if (['error', 'warning'].includes(message.type())) {
      issues.push(`console:${message.type()}:${message.text()}`);
    }
  });
  page.on('pageerror', (error) => issues.push(`pageerror:${error.message}`));
  return issues;
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
    if (response?.status() !== 429) {
      expect(response?.status()).toBe(200);
      return;
    }
  }
  throw new Error('로그인 화면 rate limit이 해제되지 않았습니다.');
}

async function expectHealthyRenderedPage(page) {
  await expect(page.locator('main#main-content')).toBeVisible();
  await expect(page.locator('main#main-content')).not.toBeEmpty();
  await expect(
    page.locator('nextjs-portal, vite-error-overlay, #webpack-dev-server-client-overlay'),
  ).toHaveCount(0);
}

test('이메일 기반 로그인·가입·비밀번호 찾기 화면이 하나의 흐름으로 연결된다', async ({ page }) => {
  requireUrl();
  const runtimeIssues = collectRuntimeIssues(page);

  await gotoLogin(page);
  await expect(page).toHaveURL(/\/auth\/login\?account_type=teacher$/);
  await expect(page).toHaveTitle(/역할 통합 로그인/);
  await expect(page.getByRole('heading', { name: '역할 통합 로그인' })).toBeVisible();
  await expect(page.getByLabel('이메일 또는 기존 아이디')).toBeVisible();
  await expect(page.getByLabel('비밀번호', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '비밀번호를 잊으셨나요?' })).toBeVisible();
  const loginGuide = page.locator('.auth-action-guide');
  await expect(loginGuide).toContainText('무엇인가요?');
  await expect(loginGuide).toContainText('언제 쓰나요?');
  await expect(loginGuide).toContainText('완료되면');
  await expectHealthyRenderedPage(page);
  await page.screenshot({
    path: `${screenshotDir}/phase19-login-desktop.png`,
    fullPage: false,
  });

  await page.getByRole('link', { name: '학생 회원가입' }).click();
  await expect(page).toHaveURL(/\/auth\/register\?account_type=student$/);
  await expect(page).toHaveTitle(/학생 회원가입/);
  await expect(page.getByRole('heading', { name: '학생 회원가입' })).toBeVisible();
  await expect(page.locator('input[name="login_name"]')).toHaveCount(0);
  await expect(page.getByLabel('로그인 이메일')).toHaveAttribute('type', 'email');
  await expect(page.getByLabel('비밀번호', { exact: true })).toHaveAttribute(
    'autocomplete',
    'new-password',
  );
  await expect(page.getByLabel('비밀번호 확인')).toBeVisible();
  await expect(page.locator('.auth-action-guide')).toContainText(
    '관리자가 역할을 승인해야 업무공간이 열립니다',
  );
  await page.getByLabel('표시 이름').fill('합성 화면 검증 학생');
  await page.getByLabel('로그인 이메일').fill('rendered-check@route19.invalid');
  await page.getByLabel('비밀번호', { exact: true }).fill('route19-rendered-password');
  await page.getByLabel('비밀번호 확인').fill('route19-rendered-password');
  await expect(page.getByLabel('로그인 이메일')).toHaveValue(
    'rendered-check@route19.invalid',
  );
  await expectHealthyRenderedPage(page);
  await page.screenshot({
    path: `${screenshotDir}/phase19-registration-desktop.png`,
    fullPage: false,
  });

  await page.getByRole('link', { name: '이미 계정이 있으면 로그인' }).click();
  await expect(page).toHaveURL(/\/auth\/login\?account_type=student$/);
  await page.getByRole('link', { name: '비밀번호를 잊으셨나요?' }).click();
  await expect(page).toHaveURL(/\/auth\/password\/forgot$/);
  await expect(page).toHaveTitle(/비밀번호 재설정 요청/);
  await expect(page.getByRole('heading', { name: '비밀번호 재설정 요청' })).toBeVisible();
  await expect(page.getByLabel('이메일')).toHaveAttribute('autocomplete', 'email');
  await page.getByLabel('이메일').fill('rendered-check@route19.invalid');
  await expect(page.getByLabel('이메일')).toHaveValue('rendered-check@route19.invalid');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('button', { name: '재설정 링크 요청' })).toBeInViewport();
  await expectHealthyRenderedPage(page);
  await page.screenshot({
    path: `${screenshotDir}/phase19-forgot-password-mobile.png`,
    fullPage: false,
  });

  expect(runtimeIssues).toEqual([]);
});

test('로그인한 계정은 보안 화면을 확인하되 운영 비밀번호를 변경하지 않는다', async ({ page }) => {
  requireUrl();
  requireAccount();
  const runtimeIssues = collectRuntimeIssues(page);

  await gotoLogin(page);
  await page.getByLabel('이메일 또는 기존 아이디').fill(accountIdentifier);
  await page.getByLabel('비밀번호', { exact: true }).fill(accountPassword);
  await paceAuthRequest();
  const loginResponsePromise = page.waitForResponse((response) => (
    response.url().startsWith(`${appUrl}/auth/login`)
      && response.request().method() === 'POST'
  ));
  await page.getByRole('button', { name: /^로그인/ }).click();
  const loginResponse = await loginResponsePromise;
  expect(loginResponse.status()).toBe(302);
  await expect(page).not.toHaveURL(/\/auth\/login/);

  const securityResponse = await page.goto(`${appUrl}/account/security`);
  expect(securityResponse?.status()).toBe(200);
  await expect(page).toHaveURL(/\/account\/security$/);
  await expect(page).toHaveTitle(/계정 보안/);
  await expect(page.getByRole('heading', { name: '회원정보·로그인 보안' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '기본 회원정보' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '비밀번호 변경' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '이메일 변경·인증' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Google 계정 연결' })).toBeVisible();
  const securityGuides = page.locator('.account-security-grid .auth-action-guide');
  await expect(securityGuides).toHaveCount(3);
  await expect(securityGuides.nth(0)).toContainText('다른 로그인 세션은 종료');
  await expect(securityGuides.nth(1)).toContainText('자료·역할은 유지');
  await expect(securityGuides.nth(2)).toContainText('자료 자동 병합은 하지 않습니다');
  await expectHealthyRenderedPage(page);

  const passwordSection = page.locator('section').filter({
    has: page.getByRole('heading', { name: '비밀번호 변경' }),
  });
  const currentPassword = passwordSection.getByLabel('현재 비밀번호');
  await expect(currentPassword).toBeEnabled();
  await currentPassword.fill(accountPassword);
  await expect(currentPassword).toHaveValue(accountPassword);
  await currentPassword.clear();
  await expect(currentPassword).toHaveValue('');
  await page.screenshot({
    path: `${screenshotDir}/phase19-account-security-desktop.png`,
    fullPage: false,
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: '비밀번호 변경' })).toBeVisible();
  const hasHorizontalOverflow = await page.evaluate(() => (
    document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
  ));
  expect(hasHorizontalOverflow).toBe(false);
  await page.screenshot({
    path: `${screenshotDir}/phase19-account-security-mobile.png`,
    fullPage: false,
  });

  const logoutForm = page.locator('form[action="/auth/logout"]');
  await expect(logoutForm).toBeVisible();
  await paceAuthRequest();
  await logoutForm.getByRole('button', { name: '로그아웃' }).click();
  await expect(page).toHaveURL(/\/auth\/login/);
  await expect(page.getByRole('heading', { name: '역할 통합 로그인' })).toBeVisible();
  expect(runtimeIssues).toEqual([]);
});
