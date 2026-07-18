// @ts-check
import { test, expect } from '@playwright/test';

const adminUrl = process.env.ADMIN_URL;
const adminUsername = process.env.ADMIN_USERNAME;
const adminPassword = process.env.ADMIN_PASSWORD;
const referenceXlsxPath = process.env.REFERENCE_XLSX_PATH;

async function login(page) {
  await page.goto(`${adminUrl}/admin/login`);
  await page.getByLabel('관리자 ID').fill(adminUsername);
  await page.getByLabel('비밀번호').fill(adminPassword);
  await page.getByRole('button', { name: '검수 화면으로 이동' }).click();
  await expect(page.getByRole('heading', { name: '규칙 검수 대기열' })).toBeVisible();
}

async function selectContaining(form, fieldName, text) {
  const select = form.locator(`select[name="${fieldName}"]`);
  const value = await select.locator('option', { hasText: text }).getAttribute('value');
  expect(value).toBeTruthy();
  await select.selectOption(value);
}

test('관리자가 2027 결과 CSV를 2028 상담 자료로 preview하고 게시한다', async ({ page }) => {
  if (!adminUrl || !adminUsername || !adminPassword) {
    test.skip(true, 'ADMIN_URL, ADMIN_USERNAME, and ADMIN_PASSWORD are required');
  }
  const suffix = `${Date.now()}`;
  const institutionName = `합성 Import 전문대 ${suffix}`;
  const institutionCode = `P14-E2E-${suffix}`;
  const programName = `합성 Import 학과 ${suffix}`;
  const programCode = `PROGRAM-${suffix}`;
  const sourceCode = `P14-E2E-SOURCE-${suffix}`;
  const consoleErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });

  await login(page);
  await page.goto(`${adminUrl}/admin/catalog`);

  let form = page.locator('form[action="/admin/catalog/institutions"]');
  await form.locator('input[name="code"]').fill(institutionCode);
  await form.locator('input[name="name"]').fill(institutionName);
  await form.getByRole('button', { name: '대학 등록' }).click();

  form = page.locator('form[action="/admin/catalog/campuses"]');
  await selectContaining(form, 'institution_id', institutionName);
  await form.locator('input[name="code"]').fill('MAIN');
  await form.locator('input[name="name"]').fill('본교');
  await form.getByRole('button', { name: '캠퍼스 등록' }).click();

  form = page.locator('form[action="/admin/catalog/programs"]');
  await selectContaining(form, 'campus_id', institutionName);
  await form.locator('input[name="code"]').fill(programCode);
  await form.locator('input[name="name"]').fill(programName);
  await form.getByRole('button', { name: '학과 등록' }).click();

  form = page.locator('form[action="/admin/catalog/admission-rounds"]');
  await selectContaining(form, 'institution_id', institutionName);
  await form.locator('input[name="academic_year"]').fill('2028');
  await form.locator('input[name="code"]').fill('SUSI-1');
  await form.locator('input[name="name"]').fill('수시1차');
  await form.getByRole('button', { name: '모집시기 등록' }).click();

  form = page.locator('form[action="/admin/catalog/admission-tracks"]');
  await selectContaining(form, 'admission_round_id', institutionName);
  await selectContaining(form, 'program_id', programName);
  await form.locator('input[name="code"]').fill('SPECIAL-GENERAL-HS');
  await form.locator('input[name="name"]').fill('특별전형 / 일반고');
  await form.getByRole('button', { name: '전형 등록' }).click();

  await page.goto(`${adminUrl}/admin/admission-results`);
  const csv = [
    '대학명,캠퍼스명,모집시기,전공명,전형구분1,전형구분2,모집인원,합격자평균,합격자최저',
    `${institutionName},본교,수시1차,${programName},특별전형,일반고,0,4.30,5.40`,
  ].join('\n');
  await page.locator('input[name="result_file"]').setInputFiles({
    name: 'synthetic-2027-results.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(csv, 'utf8'),
  });
  await page.locator('input[name="source_code"]').fill(sourceCode);
  await page.locator('input[name="source_dataset_version"]').fill('2027-V1');
  await page.locator('input[name="result_academic_year"]').fill('2027');
  await page.locator('input[name="target_academic_year"]').fill('');
  await page.locator('input[name="source_reference"]').fill('synthetic-public-e2e');
  await page.getByRole('button', { name: '미리보기 만들기' }).click();
  await expect(page.getByRole('heading', { name: '자동 열 mapping 확인' })).toBeVisible();
  await expect(page.locator('body')).toContainText('average_score');
  await expect(page.locator('body')).toContainText('합격자평균');
  await page.getByRole('button', { name: '열 mapping 확정하고 행 미리보기' }).click();

  await expect(page.getByRole('heading', { name: `${sourceCode} / 2027-V1` })).toBeVisible();
  await expect(page.locator('body')).toContainText('2027');
  await expect(page.locator('body')).toContainText('2028');
  await expect(page.locator('body')).toContainText('1 / 1 / 0 / 0 / 0');
  await expect(page.locator('body')).toContainText('VALID / STAGED');
  await page.getByRole('button', { name: '유효 행 게시' }).click();
  await expect(page.locator('body')).toContainText('PUBLISHED');
  await expect(page.locator('body')).toContainText('1 / 1 / 0 / 0 / 1');
  await expect(page.locator('body')).toContainText('상담 조회 가능 결과연도');
  await expect(page.locator('body')).toContainText('2027');
  expect(consoleErrors).toEqual([]);
});

test('기준 XLSX 공개 결과 3470행을 두 시트에서 검수한다', async ({ page }) => {
  if (!adminUrl || !adminUsername || !adminPassword || !referenceXlsxPath) {
    test.skip(
      true,
      'ADMIN_URL, ADMIN_USERNAME, ADMIN_PASSWORD, and REFERENCE_XLSX_PATH are required',
    );
  }
  const consoleErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  await login(page);
  await page.goto(`${adminUrl}/admin/admission-results`);
  await page.locator('input[name="result_file"]').setInputFiles(referenceXlsxPath);
  await page.locator('input[name="source_code"]').fill(`REFERENCE-XLSX-${Date.now()}`);
  await page.locator('input[name="source_dataset_version"]').fill('2025-FULL-PREVIEW-V1');
  await page.locator('input[name="result_academic_year"]').fill('2025');
  await page.locator('input[name="target_academic_year"]').fill('2027');
  await page.locator('input[name="source_reference"]').fill('verified-reference-xlsx');
  await page.getByRole('button', { name: '미리보기 만들기' }).click();
  await expect(page.getByRole('heading', { name: '자동 열 mapping 확인' })).toBeVisible();
  await expect(page.locator('body')).toContainText('합격자평균');
  await page.getByRole('button', { name: '열 mapping 확정하고 행 미리보기' }).click();

  await expect(page.locator('body')).toContainText('2025 수시(1차) 결과');
  await expect(page.locator('body')).toContainText('2025 수시(2차) 결과');
  await expect(page.locator('body')).toContainText('3470 / 482 / 2981 / 7 / 0');
  await expect(page.locator('body')).toContainText('2025');
  await expect(page.locator('body')).toContainText('2027');
  expect(consoleErrors).toEqual([]);
});
