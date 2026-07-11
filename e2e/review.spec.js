// @ts-check
import { test, expect } from '@playwright/test';

const desktopUrl = process.env.REVIEW_URL_DESKTOP;
const mobileUrl = process.env.REVIEW_URL_MOBILE;
const noJavaScriptUrl = process.env.REVIEW_URL_NO_JS;
const screenshotDir = process.env.SCREENSHOT_DIR || '/tmp';

test('teacher reviews, edits, selects, and confirms rows', async ({ page }) => {
  if (!desktopUrl) test.skip(true, 'REVIEW_URL_DESKTOP is required');
  const consoleErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(desktopUrl);

  await expect(page).toHaveTitle(/학생 성적 입력 검수/);
  await expect(page.getByRole('heading', { name: '학생 성적 입력 검수' })).toBeVisible();
  await expect(page.getByText('OCR 결과는 교사 확인이 필요합니다')).toBeVisible();
  await expect(page.locator('body')).not.toContainText('synthetic-original');

  const unnamedControls = await page
    .locator('input:not([type="hidden"]), button')
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

  const rowCheckboxes = page.locator('.row-checkbox');
  await rowCheckboxes.nth(0).check();
  await rowCheckboxes.nth(2).check();
  await expect(page.locator('#selected-row-count')).toHaveText('2');
  await page.locator('#rows-0-subject_name').fill('교사 브라우저 수정 과목');
  await page.screenshot({ path: `${screenshotDir}/review-desktop.png`, fullPage: true });
  await page.getByRole('button', { name: '선택한 행 확정' }).click();

  await expect(page.getByRole('heading', { name: '입력 확정이 완료되었습니다' })).toBeVisible();
  await expect(page.getByText('2개 행을 저장했습니다.')).toBeVisible();
  expect(consoleErrors).toEqual([]);
});

test('mobile layout keeps controls readable and updates selected count', async ({ page }) => {
  if (!mobileUrl) test.skip(true, 'REVIEW_URL_MOBILE is required');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(mobileUrl);

  await expect(page.getByRole('heading', { name: '학생 성적 입력 검수' })).toBeVisible();
  await page.locator('.row-checkbox').first().check();
  await expect(page.locator('#selected-row-count')).toHaveText('1');
  await expect(page.getByRole('button', { name: '선택한 행 확정' })).toBeVisible();
  const hasHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth
  );
  expect(hasHorizontalOverflow).toBe(false);
  await page.screenshot({ path: `${screenshotDir}/review-mobile.png`, fullPage: true });
  await page.locator('.row-checkbox').first().uncheck();
  await page.getByRole('button', { name: '선택한 행 확정' }).click();
  await expect(page.getByRole('heading', { name: '입력 내용을 확인하세요' })).toBeVisible();
  await expect(page.getByText('저장할 행을 선택하세요.')).toBeVisible();
  await page.screenshot({ path: `${screenshotDir}/review-mobile-error.png`, fullPage: true });
});

test.describe('without JavaScript', () => {
  test.use({ javaScriptEnabled: false });

  test('core confirmation flow still works', async ({ page }) => {
    if (!noJavaScriptUrl) test.skip(true, 'REVIEW_URL_NO_JS is required');
    await page.goto(noJavaScriptUrl);
    await page.locator('.row-checkbox').first().check();
    await page.getByRole('button', { name: '선택한 행 확정' }).click();
    await expect(page.getByRole('heading', { name: '입력 확정이 완료되었습니다' })).toBeVisible();
    await expect(page.getByText('1개 행을 저장했습니다.')).toBeVisible();
  });
});
