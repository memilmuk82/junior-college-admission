// @ts-check
import { mkdirSync } from 'node:fs';

import { test, expect } from '@playwright/test';

const appUrl = process.env.PHASE17_E2E_URL
  || process.env.PUBLIC_CALCULATION_URL
  || process.env.ADMIN_URL;
const screenshotDir = process.env.SCREENSHOT_DIR || '/tmp/phase17-qa';
const authRequestIntervalMs = Number(
  process.env.E2E_AUTH_REQUEST_INTERVAL_MS || (appUrl?.startsWith('https://') ? '3200' : '0'),
);
let lastAuthRequestAt = 0;

function requireEnvironment() {
  if (!appUrl) test.skip(true, 'PHASE17_E2E_URL is required');
  mkdirSync(screenshotDir, { recursive: true });
}

async function paceAuthRequest() {
  const remaining = authRequestIntervalMs - (Date.now() - lastAuthRequestAt);
  if (remaining > 0) await new Promise((resolve) => setTimeout(resolve, remaining));
  lastAuthRequestAt = Date.now();
}

async function gotoLogin(page, suffix = '') {
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await paceAuthRequest();
    const response = await page.goto(`${appUrl}/auth/login${suffix}`);
    if (response?.status() !== 429) return;
  }
  throw new Error('운영 로그인 rate limit이 해제되지 않았습니다.');
}

async function demoPassword(page) {
  await gotoLogin(page);
  await expect(page.getByRole('heading', { name: '역할 통합 로그인' })).toBeVisible();
  const value = await page.locator('.demo-credentials dl').last().locator('code').textContent();
  expect(value).toBeTruthy();
  return value || '';
}

async function login(page, username, password, next = '') {
  const suffix = next ? `?next=${encodeURIComponent(next)}` : '';
  for (let attempt = 0; attempt < 5; attempt += 1) {
    if (next || await page.locator('input[name="username"]').count() === 0) {
      await gotoLogin(page, suffix);
    }
    await page.locator('input[name="username"]').fill(username);
    await page.locator('input[name="password"]').fill(password);
    await paceAuthRequest();
    const responsePromise = page.waitForResponse((response) => (
      response.url().startsWith(`${appUrl}/auth/login`)
        && response.request().method() === 'POST'
    ));
    await page.getByRole('button', { name: /^로그인/ }).click();
    const response = await responsePromise;
    if (response.status() !== 429) return;
    await gotoLogin(page, suffix);
  }
  throw new Error('운영 로그인 rate limit 안에서 데모 로그인을 완료하지 못했습니다.');
}

async function logout(page) {
  if (!page.url().endsWith('/dashboard')) await page.goto(`${appUrl}/dashboard`);
  const form = page.locator('form[action="/auth/logout"]');
  await expect(form).toBeVisible();
  // 로그아웃의 302 목적지도 rate limit 대상인 /auth/login이다.
  await paceAuthRequest();
  await form.getByRole('button', { name: '로그아웃' }).click();
  await expect(page).toHaveURL(/\/auth\/login/);
  if (await page.getByRole('heading', { name: '역할 통합 로그인' }).count() === 0) {
    await gotoLogin(page);
  }
}

test('위탁 기본 성적표에서 빈 3-2로 2026 전체 대학 검색과 참고결과까지 간다', async ({ page }) => {
  requireEnvironment();
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.goto(`${appUrl}/calculate?example=1`);
  await expect(page.getByRole('radio', { name: '위탁학생 (기본)' })).toBeChecked();
  await expect(page.locator('[data-score-row]')).toHaveCount(60);
  await expect(page.locator('select[name$="record_source"]')).toHaveCount(0);
  await expect(page.locator('#rows-50-subject_name')).toHaveValue('');
  await expect(page.getByRole('heading', { name: /3학년 2학기.*선택 입력/ })).toBeVisible();
  await page.screenshot({ path: `${screenshotDir}/phase17-grade-input.png`, fullPage: true });

  await page.getByRole('button', { name: '입력값 확인하고 대학 선택으로' }).click();
  await expect(page.getByRole('heading', { name: '학생 성적 입력 검수' })).toBeVisible();
  await expect(page.locator('.row-checkbox:checked')).toHaveCount(10);
  await page.getByRole('button', { name: '확인 완료하고 대학 선택' }).click();

  await expect(page.getByRole('heading', { name: '비교할 대학과 학과를 선택하세요' })).toBeVisible();
  await expect(page.locator('select[name="admission_result_year"]')).toHaveValue('2026');
  await expect(page.locator('[data-institution-filter] option')).toHaveCount(44);
  expect(await page.locator('[data-program-option]').count()).toBeGreaterThanOrEqual(1048);
  await page.getByRole('button', { name: '보이는 항목 중 최대 5개 선택' }).click();
  await expect(page.locator('input[name="program_ids"]:checked')).toHaveCount(5);
  await expect(page.getByText('한 번에 최대 5개까지 선택할 수 있습니다.')).toBeVisible();
  for (let index = 0; index < 5; index += 1) {
    await page.locator('[data-selection-chips] button').first().click();
  }
  await expect(page.locator('input[name="program_ids"]:checked')).toHaveCount(0);
  await page.locator('[data-institution-filter]').selectOption({ label: '농협대학교' });
  await expect(page.locator('[data-program-group]:visible')).toHaveCount(1);
  await page.locator('[data-institution-filter]').selectOption({ label: '경기과학기술대학교' });
  const program = page.locator('[data-program-option]', { hasText: '경영학과' }).first();
  await expect(program).toBeVisible();
  await program.locator('input[name="program_ids"]').check();
  await page.screenshot({ path: `${screenshotDir}/phase17-university-picker.png`, fullPage: true });
  await page.getByRole('button', { name: '지원자격 확인 후 비교하기' }).click();

  await expect(page.getByRole('heading', { name: '지원자격과 대학별 반영 결과' })).toBeVisible();
  await expect(page.getByText('경기과학기술대학교').first()).toBeVisible();
  await expect(page.getByText(/2026학년도 공개 입시결과/).first()).toBeVisible();
  await expect(page.getByText(/평균 65\.0600/).first()).toBeVisible();
  await expect(page.getByText('직접 비교 불가').first()).toBeVisible();
  await page.screenshot({ path: `${screenshotDir}/phase17-2026-result.png`, fullPage: true });
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('일반고 졸업생은 3학년도 학교생활기록부로 분류하고 부적격 전형을 결과에서 제외한다', async ({ page }) => {
  requireEnvironment();
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.goto(`${appUrl}/calculate?example=1`);
  await expect(page).toHaveTitle(/학생 성적 입력/);
  const gradeThreeSources = page.locator(
    '[data-derived-record-source][data-grade="3"]',
  );
  const gradeThreeVocationalFlags = page.locator(
    '[data-derived-vocational-semester][data-grade="3"]',
  );
  await expect(gradeThreeSources).toHaveCount(20);
  expect(
    await gradeThreeSources.evaluateAll((inputs) => inputs.every(
      (input) => input instanceof HTMLInputElement
        && input.value === 'VOCATIONAL_TRAINING_RECORD',
    )),
  ).toBe(true);

  await page.getByRole('radio', { name: '일반고 졸업생' }).check();
  await expect(page.getByText('일반고 졸업생의 전 학년 성적은 원적교 학교생활기록부로 분류합니다.')).toBeVisible();
  expect(
    await gradeThreeSources.evaluateAll((inputs) => inputs.every(
      (input) => input instanceof HTMLInputElement
        && input.value === 'HOME_SCHOOL_RECORD',
    )),
  ).toBe(true);
  expect(
    await gradeThreeVocationalFlags.evaluateAll((inputs) => inputs.every(
      (input) => input instanceof HTMLInputElement && input.value === 'FALSE',
    )),
  ).toBe(true);
  const gradeThreeLabels = await page
    .locator('[data-term-source-label][data-grade="3"]')
    .allTextContents();
  expect(gradeThreeLabels).toEqual([
    '원적교 학교생활기록부',
    '원적교 학교생활기록부',
  ]);

  await page.getByRole('button', { name: '입력값 확인하고 대학 선택으로' }).click();
  await expect(page.getByRole('heading', { name: '학생 성적 입력 검수' })).toBeVisible();
  const reviewedSources = page.locator(
    'input[name^="rows-"][name$="-record_source"]',
  );
  await expect(reviewedSources).toHaveCount(10);
  expect(
    await reviewedSources.evaluateAll((inputs) => inputs.every(
      (input) => input instanceof HTMLInputElement
        && input.value === 'HOME_SCHOOL_RECORD',
    )),
  ).toBe(true);
  await page.getByRole('button', { name: '확인 완료하고 대학 선택' }).click();

  await expect(page.getByRole('heading', { name: '비교할 대학과 학과를 선택하세요' })).toBeVisible();
  await expect(page.locator('input[name="student_profile"]')).toHaveValue('GENERAL_GRADUATE');
  await expect(page.getByText('예외 대상인 일반고 졸업생 사실값을 서버에서 적용합니다.')).toBeVisible();
  await page.locator('select[name="admission_result_year"]').selectOption('2025');
  await page.locator('[data-institution-filter]').selectOption({ label: '동양미래대학교' });
  const hotel = page.locator(
    '[data-program-option][data-institution="동양미래대학교"]',
    { hasText: '호텔관광학과' },
  ).first();
  await expect(hotel).toBeVisible();
  await hotel.locator('input[name="program_ids"]').check();
  await page.getByRole('button', { name: '지원자격 확인 후 비교하기' }).click();

  await expect(page.getByRole('heading', { name: '지원자격과 대학별 반영 결과' })).toBeVisible();
  // 동양미래대 호텔관광학과의 공개 seed는 4개 전형이고, 일반고 졸업생에게
  // SUSI-1 특성화고 전형은 공식 규칙으로 INELIGIBLE이므로 결과 후보에서 빠져야 한다.
  await expect(page.getByRole('heading', { name: '전형별 결과 3건' })).toBeVisible();
  await expect(page.locator('[data-consultation-result-row]')).toHaveCount(3);
  await expect(page.locator('[data-consultation-result-row]', {
    hasText: '수시1차 · 특별전형 / 일반고',
  })).toBeVisible();
  await expect(page.locator('[data-consultation-result-row]', {
    hasText: '수시1차 · 특별전형 / 특성화고',
  })).toHaveCount(0);
  await expect(page.getByText('지원 불가', { exact: true })).toHaveCount(0);
  await page.screenshot({
    path: `${screenshotDir}/phase17-general-graduate-filtered.png`,
    fullPage: true,
  });
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('네 공개 데모 역할은 각 업무공간과 읽기 전용 경계를 보여준다', async ({ page }) => {
  requireEnvironment();
  const password = await demoPassword(page);
  for (const username of [
    'demo-student',
    'demo-teacher',
    'demo-main-admin',
    'demo-assistant-admin',
  ]) {
    await expect(page.getByText(username, { exact: true })).toBeVisible();
  }

  await login(page, 'demo-student', password, '/account/records');
  await expect(page).toHaveURL(/\/account\/records$/);
  await expect(page.getByRole('heading', { name: '저장 성적 관리' })).toBeVisible();
  await expect(page.getByRole('button', { name: '로그아웃' })).toBeVisible();
  await page.getByRole('link', { name: '내 업무공간' }).click();
  await expect(page.getByRole('heading', { name: '학생 업무공간' })).toBeVisible();
  await expect(page.getByRole('link', { name: '내 BYOK 분석' })).toBeVisible();
  await logout(page);

  await login(page, 'demo-teacher', password);
  await expect(page.getByRole('heading', { name: '교사 업무공간' })).toBeVisible();
  await expect(page.getByRole('link', { name: '학과·학급 학생 관리' })).toBeVisible();
  await expect(page.getByRole('link', { name: '학생 상담자료 만들기' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'BYOK AI 설정' })).toBeVisible();
  await logout(page);

  await login(page, 'demo-main-admin', password);
  await expect(page.getByRole('heading', { name: '주 관리자 업무공간' })).toBeVisible();
  for (const menu of [
    '회원 역할·상태 관리',
    '입시결과 등록',
    '전문대학포털 수집',
    '모집요강 자료 등록',
    '대학·학과·전형 기준정보',
    '입시 규칙 검수·게시',
  ]) {
    await expect(page.getByRole('link', { name: menu })).toBeVisible();
  }
  await page.getByRole('link', { name: '입시결과 등록' }).click();
  await expect(page.getByText('읽기 전용 공개 체험')).toBeVisible();
  await expect(page.locator('form[action="/admin/admission-results"]')).toHaveCount(0);
  await page.goto(`${appUrl}/admin/sources`);
  await expect(page.getByText('실제 업로드 파일명·해시·원문 URL')).toBeVisible();
  await expect(page.locator('form[action="/admin/sources/upload"]')).toHaveCount(0);
  await page.screenshot({ path: `${screenshotDir}/phase17-main-admin-readonly.png`, fullPage: true });
  await logout(page);

  await login(page, 'demo-assistant-admin', password);
  await expect(page.getByRole('heading', { name: '보조 관리자 승인 업무' })).toBeVisible();
  await expect(page.getByRole('link', { name: '계정 승인 요청' })).toBeVisible();
  await expect(page.getByRole('link', { name: '입시결과 등록' })).toHaveCount(0);
  await page.getByRole('link', { name: '계정 승인 요청' }).click();
  await expect(page.getByText('실제 회원 계정과 가입 정보는 표시하지 않으며')).toBeVisible();
  await page.screenshot({ path: `${screenshotDir}/phase17-assistant-admin.png`, fullPage: true });
  await logout(page);
});

test('학생과 교사 데모 BYOK는 브라우저 세션마다 격리되고 마스킹·삭제된다', async ({ page, browser }) => {
  requireEnvironment();
  const password = await demoPassword(page);
  await login(page, 'demo-student', password);
  await page.getByRole('link', { name: '내 BYOK 분석' }).click();
  await expect(page.getByText('세션별 BYOK 체험')).toBeVisible();
  const syntheticKey = 'phase17-browser-only-synthetic-7XQ9';
  await page.locator('#ai-provider').selectOption('OPENAI');
  await page.locator('#ai-api-key').fill(syntheticKey);
  await page.getByRole('button', { name: '암호화 저장 또는 교체' }).click();
  await expect(page.getByText('••••7XQ9')).toBeVisible();
  await expect(page.getByText(syntheticKey, { exact: true })).toHaveCount(0);
  await page.screenshot({ path: `${screenshotDir}/phase17-student-byok-masked.png`, fullPage: true });

  const isolated = await browser.newContext({ ignoreHTTPSErrors: true });
  const isolatedPage = await isolated.newPage();
  await login(isolatedPage, 'demo-student', password);
  await isolatedPage.getByRole('link', { name: '내 BYOK 분석' }).click();
  await expect(isolatedPage.getByText('••••7XQ9')).toHaveCount(0);
  await logout(isolatedPage);
  await isolated.close();

  await page.getByRole('button', { name: '키 삭제' }).click();
  await expect(page.getByText('저장된 공급자 키가 없습니다')).toBeVisible();
  await logout(page);

  await login(page, 'demo-teacher', password);
  await page.getByRole('link', { name: 'BYOK AI 설정' }).click();
  await expect(page.getByText('저장된 공급자 키가 없습니다')).toBeVisible();
  await logout(page);
});

test.describe('Phase 17 JavaScript 없는 SSR', () => {
  test.use({ javaScriptEnabled: false });

  test('60칸 성적과 2026 연도 선택이 JavaScript 없이 렌더링된다', async ({ page }) => {
    requireEnvironment();
    await page.goto(`${appUrl}/calculate?example=1`);
    await expect(page.locator('[data-score-row]')).toHaveCount(60);
    await page.getByRole('button', { name: '입력값 확인하고 대학 선택으로' }).click();
    await page.getByRole('button', { name: '확인 완료하고 대학 선택' }).click();
    await expect(page.locator('select[name="admission_result_year"]')).toHaveValue('2026');
    const firstProgram = page.locator('input[name="program_ids"]').first();
    await expect(firstProgram).toBeVisible();
    await firstProgram.check();
    await page.getByRole('button', { name: '지원자격 확인 후 비교하기' }).click();
    await expect(page.getByRole('heading', { name: '지원자격과 대학별 반영 결과' })).toBeVisible();
  });
});

test.describe('Phase 17 390px 모바일', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('성적 입력 핵심 화면에 가로 넘침이 없다', async ({ page }) => {
    requireEnvironment();
    await page.goto(`${appUrl}/calculate?example=1`);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.screenshot({ path: `${screenshotDir}/phase17-mobile-grade-input.png`, fullPage: true });
  });
});
