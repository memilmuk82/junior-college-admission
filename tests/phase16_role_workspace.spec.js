// @ts-check
import { test, expect } from '@playwright/test';

const appUrl = process.env.PHASE16_E2E_URL || process.env.ADMIN_URL;
const password = process.env.PHASE16_E2E_PASSWORD || 'phase16-e2e-password';
const prefix = process.env.PHASE16_E2E_PREFIX || 'phase16-e2e-';
const screenshotDir = process.env.SCREENSHOT_DIR || '/tmp';

const accounts = {
  admin: `${prefix}admin`,
  teacher: `${prefix}teacher`,
  student: `${prefix}student`,
  assistant: `${prefix}assistant`,
};

function requireEnvironment() {
  if (!appUrl) {
    test.skip(true, 'PHASE16_E2E_URL or ADMIN_URL is required');
  }
}

async function login(page, username, accountType = 'teacher') {
  await page.goto(`${appUrl}/auth/login?account_type=${accountType}`);
  await expect(page.getByRole('heading', { name: /로그인/ })).toBeVisible();
  await page.locator('input[name="username"]').fill(username);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole('button', { name: '로그인' }).click();
}

async function logout(page) {
  await page.goto(`${appUrl}/dashboard`);
  const logoutForm = page.locator('form[action="/auth/logout"]');
  await expect(logoutForm).toBeVisible();
  await logoutForm.getByRole('button', { name: '로그아웃' }).click();
  await expect(page).toHaveURL(/\/auth\/login/);
}

test('Phase 16 역할별 업무공간과 교사-학생 성적 연결은 SSR 폼으로 동작한다', async ({ page }) => {
  requireEnvironment();
  const consoleErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });

  await login(page, accounts.admin);
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading', { name: '주 관리자 업무공간' })).toBeVisible();
  await expect(page.getByRole('link', { name: '회원 역할·상태 관리' })).toHaveAttribute(
    'href',
    '/admin/members',
  );
  await expect(page.getByRole('link', { name: '입시결과 등록' })).toHaveAttribute(
    'href',
    '/admin/admission-results',
  );
  await expect(page.getByRole('link', { name: '전문대학포털 수집' })).toHaveAttribute(
    'href',
    '/admin/admission-results#procollege-collection',
  );
  await expect(page.getByRole('link', { name: '모집요강 자료 등록' })).toHaveAttribute(
    'href',
    '/admin/sources',
  );
  await logout(page);

  await login(page, accounts.assistant);
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading', { name: '보조 관리자 승인 업무' })).toBeVisible();
  await expect(page.getByRole('link', { name: '계정 승인 요청' })).toBeVisible();
  await expect(page.getByRole('link', { name: '학과·학급 학생 관리' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: '학생 상담자료 만들기' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /BYOK/ })).toHaveCount(0);
  await page.goto(`${appUrl}/admin/ai/settings`);
  await expect(page.getByText('Forbidden')).toBeVisible();
  await page.goto(`${appUrl}/dashboard`);
  await logout(page);
  // The immediately preceding navigation intentionally verifies a 403. Start
  // console-health collection for the successful teacher/student flow here.
  consoleErrors.length = 0;

  await login(page, accounts.teacher);
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading', { name: '교사 업무공간' })).toBeVisible();
  await expect(page.getByRole('link', { name: '학과·학급 학생 관리' })).toHaveAttribute(
    'href',
    '/teacher/classrooms',
  );
  await expect(page.getByRole('link', { name: '학생 상담자료 만들기' })).toHaveAttribute(
    'href',
    '/admin/consultations/new',
  );
  await expect(page.getByRole('link', { name: 'BYOK AI 설정' })).toHaveAttribute(
    'href',
    '/admin/ai/settings',
  );

  await page.getByRole('link', { name: '학과·학급 학생 관리' }).click();
  await expect(page.getByRole('heading', { name: '학과·학급과 학생 성적' })).toBeVisible();
  const suffix = `${Date.now()}`;
  const department = `합성학과${suffix}`;
  const classroom = `3-E2E-${suffix}`;
  const courseSubject = `합성 연결 성적 과목 ${suffix}`;
  await page.locator('form[action="/teacher/classrooms"] input[name="academic_year"]').fill('2027');
  await page.locator('form[action="/teacher/classrooms"] input[name="department_name"]').fill(department);
  await page.locator('form[action="/teacher/classrooms"] input[name="class_name"]').fill(classroom);
  await page.getByRole('button', { name: '학급 만들기' }).click();
  await expect(page.getByText(`${department} · ${classroom}`)).toBeVisible();

  const classCard = page.locator('.classroom-card', { hasText: `${department} · ${classroom}` });
  const anonymousCode = `SYN-${suffix}`;
  await classCard.locator('input[name="anonymous_code"]').fill(anonymousCode);
  await classCard.getByRole('button', { name: '학생 추가·연결코드 발급' }).click();
  await expect(page.getByRole('heading', { name: '학생 연결 코드' })).toBeVisible();
  const connectionCode = await page.locator('[data-connection-code]').textContent();
  expect(connectionCode).toMatch(/^[A-Za-z0-9_-]{20,64}$/);
  await expect(page.getByText('원문은 DB에 저장되지 않아 화면을 벗어나면 다시 확인할 수 없습니다.')).toBeVisible();

  await page.getByRole('link', { name: new RegExp(`^${anonymousCode}`) }).click();
  await expect(page.getByRole('heading', { name: `${anonymousCode} 성적·상담` })).toBeVisible();
  const courseForm = page.locator('form[action*="/courses"]');
  await courseForm.locator('input[name="academic_year"]').fill('2027');
  await courseForm.locator('select[name="grade"]').selectOption('3');
  await courseForm.locator('select[name="semester"]').selectOption('1');
  await courseForm.locator('select[name="record_source"]').selectOption('MANUAL_INPUT');
  await courseForm.locator('input[name="subject_name"]').fill(courseSubject);
  await courseForm.locator('input[name="credits"]').fill('3');
  await courseForm.locator('input[name="rank_grade"]').fill('2');
  await courseForm.getByRole('button', { name: '검수 완료 과목으로 추가' }).click();
  await expect(page.getByText(courseSubject)).toBeVisible();
  await page.screenshot({ path: `${screenshotDir}/phase16-teacher-classroom.png`, fullPage: true });
  await logout(page);

  await login(page, accounts.student, 'student');
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading', { name: '학생 업무공간' })).toBeVisible();
  await expect(page.getByRole('link', { name: '내 성적·상담 자료' })).toHaveAttribute(
    'href',
    '/account/records',
  );
  await expect(page.getByRole('link', { name: '내 BYOK 분석' })).toHaveAttribute(
    'href',
    '/admin/ai/settings',
  );
  await expect(page.getByRole('link', { name: '학과·학급 학생 관리' })).toHaveCount(0);
  await page.getByRole('link', { name: '내 성적·상담 자료' }).click();
  await expect(page.getByRole('heading', { name: '저장 성적 관리' })).toBeVisible();
  await page.getByLabel('연결 코드').fill(connectionCode || '');
  await page.getByLabel('위 공유 범위와 연결 해제 효과를 확인했습니다.').check();
  await page.getByRole('button', { name: '학급 연결' }).click();
  await expect(page.getByRole('status')).toContainText('교사 학급 연결이 완료되었습니다.');
  await expect(page.getByText(`${department} · ${classroom}`)).toBeVisible();
  await expect(page.getByText(courseSubject)).toBeVisible();
  const sharedCourseRow = page.locator('tbody tr', { hasText: courseSubject });
  await expect(sharedCourseRow).toContainText('연결 학생 성적');
  await expect(sharedCourseRow).toContainText('읽기 전용 공유');
  await expect(sharedCourseRow.locator('form[action$="/edit"]')).toHaveCount(0);
  await page.screenshot({ path: `${screenshotDir}/phase16-student-linked-records.png`, fullPage: true });

  expect(consoleErrors).toEqual([]);
});

test.describe('Phase 16 JavaScript 없는 SSR 연결 흐름', () => {
  test.use({ javaScriptEnabled: false });

  test('학생 업무공간과 연결 코드 폼은 JavaScript 없이 렌더링된다', async ({ page }) => {
    requireEnvironment();
    await login(page, accounts.student, 'student');
    await expect(page.getByRole('heading', { name: '학생 업무공간' })).toBeVisible();
    await page.getByRole('link', { name: '내 성적·상담 자료' }).click();
    await expect(page.getByRole('heading', { name: '교사 학급 연결' })).toBeVisible();
    await expect(page.locator('form[action="/account/classroom-links"]')).toBeVisible();
  });
});

test.describe('Phase 16 학생 모바일 화면', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('업무공간과 성적·연결 화면에 가로 넘침이 없다', async ({ page }) => {
    requireEnvironment();
    await login(page, accounts.student, 'student');
    await expect(page.getByRole('heading', { name: '학생 업무공간' })).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.getByRole('link', { name: '내 성적·상담 자료' }).click();
    await expect(page.getByRole('heading', { name: '교사 학급 연결' })).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await page.screenshot({ path: `${screenshotDir}/phase16-student-mobile.png`, fullPage: true });
  });
});
