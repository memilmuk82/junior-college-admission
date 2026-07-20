// @ts-check
import { mkdirSync } from 'node:fs';

import { test, expect } from '@playwright/test';

const appUrl = process.env.PHASE17_E2E_URL
  || process.env.PUBLIC_CALCULATION_URL
  || process.env.ADMIN_URL;
const screenshotDir = process.env.SCREENSHOT_DIR || '/tmp/phase17-qa';

function requireEnvironment() {
  if (!appUrl) test.skip(true, 'PHASE17_E2E_URL is required');
  mkdirSync(screenshotDir, { recursive: true });
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
  const initialSources = page.locator('[data-derived-record-source]');
  const initialVocationalFlags = page.locator('[data-derived-vocational-semester]');
  await expect(initialSources).toHaveCount(60);
  await expect(initialVocationalFlags).toHaveCount(60);
  expect(
    await initialSources.evaluateAll((inputs) => inputs.every((input) => (
      input instanceof HTMLInputElement
      && input.value === (
        input.dataset.grade === '3' && input.dataset.semester === '1'
          ? 'VOCATIONAL_TRAINING_RECORD'
          : 'HOME_SCHOOL_RECORD'
      )
    ))),
  ).toBe(true);
  expect(
    await initialVocationalFlags.evaluateAll((inputs) => inputs.every((input) => (
      input instanceof HTMLInputElement
      && input.value === (
        input.dataset.grade === '3' && input.dataset.semester === '1' ? 'TRUE' : 'FALSE'
      )
    ))),
  ).toBe(true);
  await expect(page.locator('#rows-50-subject_name')).toHaveValue('');
  await expect(page.getByRole('heading', { name: /3학년 2학기.*선택 입력/ })).toBeVisible();
  await page.screenshot({ path: `${screenshotDir}/phase17-grade-input.png`, fullPage: true });

  await page.getByRole('button', { name: '입력값 확인하고 대학 선택으로' }).click();
  await expect(page.getByRole('heading', { name: '학생 성적 입력 검수' })).toBeVisible();
  await expect(page.locator('.row-checkbox:checked')).toHaveCount(31);
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
    await gradeThreeSources.evaluateAll((inputs) => inputs.every((input) => (
      input instanceof HTMLInputElement
      && input.value === (
        input.dataset.semester === '1'
          ? 'VOCATIONAL_TRAINING_RECORD'
          : 'HOME_SCHOOL_RECORD'
      )
    ))),
  ).toBe(true);
  expect(
    await gradeThreeVocationalFlags.evaluateAll((inputs) => inputs.every((input) => (
      input instanceof HTMLInputElement
      && input.value === (input.dataset.semester === '1' ? 'TRUE' : 'FALSE')
    ))),
  ).toBe(true);

  await page.getByRole('radio', { name: '일반고 졸업생' }).check();
  await expect(page.getByText('일반고 졸업생의 전 학년 성적은 원적교 학교생활기록부로 분류합니다.')).toBeVisible();
  const allSources = page.locator('[data-derived-record-source]');
  const allVocationalFlags = page.locator('[data-derived-vocational-semester]');
  expect(
    await allSources.evaluateAll((inputs) => inputs.every(
      (input) => input instanceof HTMLInputElement
        && input.value === 'HOME_SCHOOL_RECORD',
    )),
  ).toBe(true);
  expect(
    await allVocationalFlags.evaluateAll((inputs) => inputs.every(
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
  await expect(reviewedSources).toHaveCount(31);
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
