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

async function openConsultation(page) {
  await page.getByRole('link', { name: '상담 시작' }).click();
  await expect(page.getByRole('heading', { name: '단계형 상담 시작' })).toBeVisible();
  await page.getByLabel('내부 익명 학생 코드').fill('synthetic-student');
  await expect(page.locator('input[name="program_ids"]')).toHaveCount(4);
}

async function completeInputsAndSubmit(page) {
  await page.getByLabel('과거 입시결과 기준연도(선택)').fill('2026');
  await page.getByLabel('위탁 학기 수').fill('1');
  await page.getByLabel('상담 메모').fill('합성 브라우저 상담 메모');
  await page.getByRole('button', { name: '선택 학과의 모든 전형 확인' }).click();
  await expect(page.getByRole('heading', { name: '지원자격 확인 완료' })).toBeVisible();
  await expect(page.locator('[data-consultation-result-row]')).toHaveCount(4);
}

test('Phase 13 search, group selection, statuses, average grades, and A4 outputs', async ({ page }) => {
  if (!adminUrl || !adminUsername || !adminPassword) {
    test.skip(true, 'ADMIN_URL, ADMIN_USERNAME, and ADMIN_PASSWORD are required');
  }
  const consoleErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  await login(page);
  await openConsultation(page);

  const search = page.getByLabel('대학명·학과명 검색');
  await search.fill('자격미달');
  await expect(page.locator('[data-program-option]:visible')).toHaveCount(1);
  await expect(page.locator('[data-program-option][hidden]')).toHaveCount(3);
  await page.getByRole('button', { name: '검색 결과 전체 선택' }).click();
  await expect(page.locator('[data-selection-count]')).toHaveText('1개 선택');
  await search.fill('');
  await expect(page.locator('[data-program-option]:visible')).toHaveCount(4);

  const institutionToggle = page.locator('[data-institution-toggle]');
  await expect(institutionToggle).toHaveCount(1);
  await institutionToggle.check();
  await expect(page.locator('[data-selection-count]')).toHaveText('4개 선택');
  await expect(page.locator('input[name="program_ids"]:checked')).toHaveCount(4);
  await completeInputsAndSubmit(page);

  const ineligibleRow = page.locator('[data-consultation-result-row]', {
    hasText: '합성 자격미달 학과',
  });
  await expect(ineligibleRow).toContainText('INELIGIBLE');
  await expect(ineligibleRow).toContainText('계산하지 않음');
  await expect(ineligibleRow).toContainText('NOT_EVALUATED');
  const preparingRow = page.locator('[data-consultation-result-row]', {
    hasText: '합성 준비중 학과',
  });
  await expect(preparingRow).toContainText('계산 기준 준비 중');
  await expect(preparingRow).toContainText('NOT_EVALUATED');
  await expect(page.getByText('2.00등급').first()).toBeVisible();
  await expect(page.locator('body')).not.toContainText('환산점수');

  await page.getByRole('button', { name: '학생용 A4 열기' }).click();
  await expect(page.getByRole('heading', { name: '학생용 상담 결과' })).toBeVisible();
  await expect(page.locator('body')).toContainText('합성 자격미달 학과');
  await expect(page.locator('body')).toContainText('합성 준비중 학과');
  await expect(page.locator('body')).toContainText('NOT_EVALUATED');
  await page.emulateMedia({ media: 'print' });
  const studentPdf = await page.pdf({ format: 'A4', printBackground: true });
  expect(studentPdf.length).toBeGreaterThan(1000);

  await page.emulateMedia({ media: 'screen' });
  await page.goto(`${adminUrl}/admin/consultations/new`);
  await page.getByLabel('내부 익명 학생 코드').fill('synthetic-student');
  await page.locator('[data-institution-toggle]').check();
  await page.getByLabel('위탁 학기 수').fill('1');
  await page.getByLabel('상담 메모').fill('합성 브라우저 상담 메모');
  await page.getByRole('button', { name: '선택 학과의 모든 전형 확인' }).click();
  await page.getByRole('button', { name: '교사용 A4 열기' }).click();
  await expect(page.getByRole('heading', { name: '교사용 상담 결과' })).toBeVisible();
  await expect(page.getByText('지원자격 trace').first()).toBeVisible();
  await expect(page.getByText('평균등급 계산 trace').first()).toBeVisible();
  await expect(page.getByText('합성 브라우저 상담 메모')).toBeVisible();
  await page.emulateMedia({ media: 'print' });
  const teacherPdf = await page.pdf({ format: 'A4', printBackground: true });
  expect(teacherPdf.length).toBeGreaterThan(1000);
  expect(consoleErrors).toEqual([]);
  await page.screenshot({
    path: `${screenshotDir}/phase13-consultation-teacher.png`,
    fullPage: true,
  });
});

test.describe('Phase 13 without JavaScript', () => {
  test.use({ javaScriptEnabled: false });

  test('multiple programs, statuses, and student print remain server rendered', async ({ page }) => {
    if (!adminUrl || !adminUsername || !adminPassword) {
      test.skip(true, 'ADMIN_URL, ADMIN_USERNAME, and ADMIN_PASSWORD are required');
    }
    await login(page);
    await openConsultation(page);
    const programs = page.locator('input[name="program_ids"]');
    for (let index = 0; index < 4; index += 1) await programs.nth(index).check();
    await completeInputsAndSubmit(page);
    await expect(page.locator('body')).toContainText('INELIGIBLE');
    await expect(page.locator('body')).toContainText('계산 기준 준비 중');
    await page.getByRole('button', { name: '학생용 A4 열기' }).click();
    await expect(page.getByRole('heading', { name: '학생용 상담 결과' })).toBeVisible();
  });
});
