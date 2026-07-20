// @ts-check
import { test, expect } from '@playwright/test';

const publicUrl = process.env.PUBLIC_CALCULATION_URL;

const pastedGrades = `학년도\t학년\t학기\t교과\t과목\t이수단위\t석차등급
2025\t1\t1\t국어\t국어\t4\t2
2025\t1\t1\t수학\t수학\t4\t3
2025\t1\t2\t영어\t영어\t4\t2
2025\t1\t2\t사회\t통합사회\t3\t3
2026\t2\t1\t국어\t문학\t4\t2
2026\t2\t1\t수학\t수학Ⅰ\t4\t2
2026\t2\t2\t영어\t영어Ⅰ\t4\t1
2026\t2\t2\t과학\t통합과학\t3\t2
2027\t3\t1\t국어\t화법과 작문\t3\t2
2027\t3\t1\t수학\t확률과 통계\t3\t2`;

async function startWithPastedGrades(page) {
  await page.goto(`${publicUrl}/calculate?example=1`);
  await expect(page.getByRole('heading', { name: /학생부 성적을 학기별로 입력/ })).toBeVisible();
  await expect(page.getByText('합성 예시 성적을 불러왔습니다')).toBeVisible();
  await expect(page.locator('[data-preview-program]')).toHaveCount(0);
  await expect(page.getByText(/성적 확인 다음 단계에서 대학·학과를 선택합니다/)).toBeVisible();
  await expect(page.getByRole('radio', { name: '위탁학생 (기본)' })).toBeChecked();
  await expect(page.locator('[data-score-row]')).toHaveCount(60);
  await expect(page.getByText(/선택 입력 · 비워도 계산 가능/)).toBeVisible();
  await expect(page.locator('#record-source')).toHaveCount(0);
  await page.getByRole('radio', { name: '표 붙여넣기' }).check();
  await page.locator('#pasted-table').fill(pastedGrades);
  await page.getByRole('button', { name: '입력값 확인하고 대학 선택으로' }).click();
  await expect(page.getByRole('heading', { name: '학생 성적 입력 검수' })).toBeVisible();
  await expect(page.locator('.row-checkbox:checked')).toHaveCount(10);
}

async function startWithEditedExample(page) {
  await page.goto(`${publicUrl}/calculate?example=1`);
  await expect(page.getByRole('heading', { name: /학생부 성적을 학기별로 입력/ })).toBeVisible();
  await expect(page.getByText('합성 예시 성적을 불러왔습니다')).toBeVisible();
  await expect(page.locator('[data-preview-program]')).toHaveCount(0);
  await expect(page.getByRole('radio', { name: '위탁학생 (기본)' })).toBeChecked();
  await expect(page.locator('[data-score-row]')).toHaveCount(60);
  await expect(page.locator('select[name$="record_source"]')).toHaveCount(0);
  await page.locator('#rows-0-rank_grade').fill('3');
  await page.getByRole('button', { name: '입력값 확인하고 대학 선택으로' }).click();
  await expect(page.getByRole('heading', { name: '학생 성적 입력 검수' })).toBeVisible();
  await expect(page.locator('#rows-0-rank_grade')).toHaveValue('3');
  await expect(page.locator('.row-checkbox:checked')).toHaveCount(10);
}

async function chooseDongyangHotelAndCalculate(page) {
  await page.getByRole('button', { name: '확인 완료하고 대학 선택' }).click();
  await expect(page.getByRole('heading', { name: '비교할 대학과 학과를 선택하세요' })).toBeVisible();
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
  await expect(page.getByText('호텔관광학과').first()).toBeVisible();
  await expect(page.getByText('판정 이유·반영 과목·공식 근거 보기').first()).toBeVisible();
  await expect(page.getByText(/평균 5\.7000/).first()).toBeVisible();
  await expect(page.getByText(/최저 6\.3000/).first()).toBeVisible();
  await expect(page.getByText(/경쟁률 8\.4000/).first()).toBeVisible();
  await expect(page.getByText(/모집 47/).first()).toBeVisible();
  await expect(page.getByText('2025학년도', { exact: true }).first()).toBeVisible();
}

test('anonymous actual-data calculation changes result and prints both A4 views', async ({ page }) => {
  test.skip(!publicUrl, 'PUBLIC_CALCULATION_URL is required');
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await startWithEditedExample(page);
  await chooseDongyangHotelAndCalculate(page);
  await expect(page.getByText('1.71등급').first()).toBeVisible();
  const calculationId = page.url().match(/\/calculate\/([^/]+)\/results$/)?.[1];
  expect(calculationId).toBeTruthy();
  await page.getByText('판정 이유·반영 과목·공식 근거 보기').first().click();
  await expect(page.getByText(/영어Ⅰ.*1등급/).first()).toBeVisible();

  await page.getByRole('button', { name: '학생용 A4 열기' }).click();
  await expect(page.getByRole('heading', { name: '학생용 계산 결과' })).toBeVisible();
  await page.emulateMedia({ media: 'print' });
  expect((await page.pdf({ format: 'A4', printBackground: true })).length).toBeGreaterThan(1000);

  await page.emulateMedia({ media: 'screen' });
  await page.goto(`${publicUrl}/input/review/${calculationId}`);
  await page.locator('#rows-6-rank_grade').fill('9');
  await chooseDongyangHotelAndCalculate(page);
  await expect(page.getByText('2.21등급').first()).toBeVisible();
  const completeCsrf = await page.locator('form[action$="/complete"] input[name="csrf_token"]').inputValue();

  await page.getByRole('button', { name: '교사용 A4 열기' }).click();
  await expect(page.getByRole('heading', { name: '교사용 계산 근거' })).toBeVisible();
  await expect(page.getByText('평균등급 계산 trace').first()).toBeVisible();
  await page.emulateMedia({ media: 'print' });
  expect((await page.pdf({ format: 'A4', printBackground: true })).length).toBeGreaterThan(1000);
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);

  await page.request.post(`${publicUrl}/calculate/${calculationId}/complete`, {
    form: { csrf_token: completeCsrf },
  });
  await page.goto(publicUrl);
  await expect(page.getByRole('heading', { name: /학생부 성적을 학기별로 입력/ })).toBeVisible();
  const expired = await page.goto(`${publicUrl}/calculate/${calculationId}/targets`);
  expect(expired?.status()).toBe(404);
});

test.describe('without JavaScript', () => {
  test.use({ javaScriptEnabled: false });
  test('direct SSR path reaches actual calculation and student print', async ({ page }) => {
    test.skip(!publicUrl, 'PUBLIC_CALCULATION_URL is required');
    await startWithEditedExample(page);
    await chooseDongyangHotelAndCalculate(page);
    await expect(page.getByText('1.71등급').first()).toBeVisible();
    await page.getByRole('button', { name: '학생용 A4 열기' }).click();
    await expect(page.getByRole('heading', { name: '학생용 계산 결과' })).toBeVisible();
  });
});

test.describe('390px mobile', () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test('core inputs and results stay inside the page viewport', async ({ page }) => {
    test.skip(!publicUrl, 'PUBLIC_CALCULATION_URL is required');
    await startWithPastedGrades(page);
    await chooseDongyangHotelAndCalculate(page);
    const viewportFits = await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    );
    expect(viewportFits).toBe(true);
    await expect(page.getByText('1.71등급').first()).toBeVisible();
  });
});
