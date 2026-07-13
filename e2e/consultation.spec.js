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

async function submitConsultation(page) {
  await page.getByRole('link', { name: '상담 시작' }).click();
  await expect(page.getByRole('heading', { name: '단계형 상담 시작' })).toBeVisible();
  await page.getByLabel('내부 익명 학생 코드').fill('synthetic-student');
  await page.getByLabel('대학·학과·전형').selectOption({ index: 1 });
  await page.getByLabel('과거 입시결과 기준연도(선택)').fill('2026');
  await page.getByLabel('위탁 학기 수').fill('1');
  await page.getByLabel('상담 메모').fill('합성 브라우저 상담 메모');
  await page.getByRole('button', { name: '지원자격부터 확인' }).click();
  await expect(page.getByRole('heading', { name: '지원자격 확인 완료' })).toBeVisible();
}

test('teacher completes eligibility-first consultation and opens separate A4 outputs', async ({
  page,
}) => {
  if (!adminUrl || !adminUsername || !adminPassword) {
    test.skip(true, 'ADMIN_URL, ADMIN_USERNAME, and ADMIN_PASSWORD are required');
  }
  const consoleErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await login(page);
  await submitConsultation(page);
  await expect(page.getByText('2.00 / 9')).toBeVisible();
  await expect(page.getByText(/게시 승인된 동일 업무키 입시결과가 없습니다/)).toBeVisible();
  await page.screenshot({ path: `${screenshotDir}/consultation-result.png`, fullPage: true });

  await page.getByRole('button', { name: '학생용 A4 열기' }).click();
  await expect(page.getByRole('heading', { name: '학생용 상담 결과' })).toBeVisible();
  await expect(page.locator('body')).not.toContainText('합성 브라우저 상담 메모');
  await expect(page.locator('body')).not.toContainText('조건 평가 trace');
  await page.emulateMedia({ media: 'print' });
  const studentPrintColors = await page.evaluate(() => ({
    body: getComputedStyle(document.body).backgroundColor,
    sheet: getComputedStyle(document.querySelector('.print-sheet')).backgroundColor,
  }));
  expect(studentPrintColors).toEqual({ body: 'rgb(255, 255, 255)', sheet: 'rgb(255, 255, 255)' });
  await page.screenshot({ path: `${screenshotDir}/consultation-student-print.png`, fullPage: true });
  const studentPdf = await page.pdf({ format: 'A4', printBackground: true });
  expect(studentPdf.length).toBeGreaterThan(1000);
  expect((studentPdf.toString('latin1').match(/\/Type\s*\/Page\b/g) || []).length).toBe(1);

  await page.emulateMedia({ media: 'screen' });
  await page.goto(`${adminUrl}/admin/consultations/new`);
  await page.getByLabel('내부 익명 학생 코드').fill('synthetic-student');
  await page.getByLabel('대학·학과·전형').selectOption({ index: 1 });
  await page.getByLabel('위탁 학기 수').fill('1');
  await page.getByLabel('상담 메모').fill('합성 브라우저 상담 메모');
  await page.getByRole('button', { name: '지원자격부터 확인' }).click();
  await page.getByRole('button', { name: '교사용 A4 열기' }).click();
  await expect(page.getByRole('heading', { name: '교사용 상담 결과' })).toBeVisible();
  await expect(page.getByText('조건 평가 trace')).toBeVisible();
  await expect(page.getByText('성적 범위 trace')).toBeVisible();
  await expect(page.getByText('계산 trace', { exact: true })).toBeVisible();
  await expect(page.getByText('합성 브라우저 상담 메모')).toBeVisible();
  await page.emulateMedia({ media: 'print' });
  const teacherPrintColors = await page.evaluate(() => ({
    body: getComputedStyle(document.body).backgroundColor,
    sheet: getComputedStyle(document.querySelector('.print-sheet')).backgroundColor,
  }));
  expect(teacherPrintColors).toEqual({ body: 'rgb(255, 255, 255)', sheet: 'rgb(255, 255, 255)' });
  await page.screenshot({ path: `${screenshotDir}/consultation-teacher-print.png`, fullPage: true });
  const teacherPdf = await page.pdf({ format: 'A4', printBackground: true });
  expect(teacherPdf.length).toBeGreaterThan(1000);
  expect((teacherPdf.toString('latin1').match(/\/Type\s*\/Page\b/g) || []).length).toBe(2);
  expect(consoleErrors).toEqual([]);
});

test('consultation form remains usable on mobile without horizontal overflow', async ({ page }) => {
  if (!adminUrl || !adminUsername || !adminPassword) {
    test.skip(true, 'ADMIN_URL, ADMIN_USERNAME, and ADMIN_PASSWORD are required');
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page);
  await page.getByRole('link', { name: '상담 시작' }).click();
  await expect(page.getByRole('heading', { name: '단계형 상담 시작' })).toBeVisible();
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth
  );
  expect(hasHorizontalOverflow).toBe(false);
  await page.screenshot({ path: `${screenshotDir}/consultation-mobile.png`, fullPage: true });
});

test.describe('consultation without JavaScript', () => {
  test.use({ javaScriptEnabled: false });

  test('server-rendered eligibility-first result and student print remain usable', async ({ page }) => {
    if (!adminUrl || !adminUsername || !adminPassword) {
      test.skip(true, 'ADMIN_URL, ADMIN_USERNAME, and ADMIN_PASSWORD are required');
    }
    await login(page);
    await submitConsultation(page);
    await page.getByRole('button', { name: '학생용 A4 열기' }).click();
    await expect(page.getByRole('heading', { name: '학생용 상담 결과' })).toBeVisible();
  });
});
