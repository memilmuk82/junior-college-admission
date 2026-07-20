// @ts-check
import { mkdirSync } from 'node:fs';

import { test, expect } from '@playwright/test';

const phase20E2eUrl = process.env.PHASE20_E2E_URL;
if (!phase20E2eUrl) {
  throw new Error(
    'PHASE20_E2E_URL is required (for example: https://admission.example.com/demo).',
  );
}

const appUrl = phase20E2eUrl.replace(/\/$/, '');
const screenshotDir = process.env.SCREENSHOT_DIR || '/tmp/phase20-qa';

const roleHeadings = {
  '학생': '학생 업무공간',
  '교사': '교사 업무공간',
  '주 관리자': '주 관리자 업무공간',
  '보조 관리자': '보조 관리자 승인 업무',
};

test.describe.configure({ mode: 'serial' });

test.beforeAll(() => {
  mkdirSync(screenshotDir, { recursive: true });
});

function route(pathname) {
  return `${appUrl}${pathname}`;
}

function sameOriginDemoUrl(rawUrl) {
  const target = new URL(rawUrl, appUrl);
  return `${new URL(appUrl).origin}${target.pathname}${target.search}`;
}

function collectRuntimeIssues(page) {
  /** @type {string[]} */
  const issues = [];
  page.on('console', (message) => {
    if (message.type() === 'error') {
      issues.push(`console:${message.text()}`);
    }
  });
  page.on('pageerror', (error) => issues.push(`pageerror:${error.message}`));
  return issues;
}

async function expectRenderedPage(page) {
  await expect(page.locator('main')).toBeVisible();
  expect((await page.locator('main').innerText()).trim()).not.toBe('');
  await expect(
    page.locator('nextjs-portal, vite-error-overlay, #webpack-dev-server-client-overlay'),
  ).toHaveCount(0);
}

async function openDemoLogin(page) {
  const response = await page.goto(route('/auth/login'));
  expect(response?.status()).toBe(200);
  await expect(page).toHaveURL(/\/demo\/auth\/login(?:\?.*)?$/);
  await expect(page.getByRole('heading', { name: '역할 통합 로그인' })).toBeVisible();
  await expect(page.getByRole('heading', { name: /전체 기능 체험 계정/ })).toBeVisible();
  await expectRenderedPage(page);
}

async function demoPublicPassword(page) {
  await openDemoLogin(page);
  const password = (await page.locator('.demo-credentials code').last().innerText()).trim();
  expect(password.length).toBeGreaterThanOrEqual(12);
  return password;
}

async function startRole(page, roleLabel) {
  await openDemoLogin(page);
  await page.getByRole('button', {
    name: `${roleLabel} 기능 체험 시작`,
    exact: true,
  }).click();
  await expect(page).toHaveURL(/\/demo\/dashboard$/);
  await expect(page.getByRole('heading', { name: roleHeadings[roleLabel] })).toBeVisible();
  await expect(page.getByText(
    roleLabel === '보조 관리자'
      ? '운영과 분리된 승인 전용 체험 환경입니다.'
      : '운영과 분리된 전체 기능 체험 환경입니다.',
  )).toBeVisible();
  await expectRenderedPage(page);
}

async function logout(page) {
  if (!page.url().endsWith('/dashboard')) {
    await page.goto(route('/dashboard'));
  }
  const form = page.locator('form[action$="/auth/logout"]');
  await expect(form).toBeVisible();
  await form.getByRole('button', { name: '로그아웃' }).click();
  await expect(page).toHaveURL(/\/demo\/auth\/login$/);
  await expect(page.getByRole('heading', { name: '역할 통합 로그인' })).toBeVisible();
}

test('로그인 화면은 네 체험계정과 역할별 원클릭 진입을 모두 제공한다', async ({ page }) => {
  const runtimeIssues = collectRuntimeIssues(page);
  await openDemoLogin(page);

  for (const loginName of [
    'demo-student',
    'demo-teacher',
    'demo-main-admin',
    'demo-assistant-admin',
  ]) {
    await expect(page.getByText(loginName, { exact: true })).toBeVisible();
  }

  for (const roleLabel of Object.keys(roleHeadings)) {
    await expect(page.getByRole('button', {
      name: `${roleLabel} 기능 체험 시작`,
      exact: true,
    })).toBeVisible();
    await startRole(page, roleLabel);
    await logout(page);
  }

  await page.screenshot({
    path: `${screenshotDir}/phase20-four-role-login.png`,
    fullPage: true,
  });
  expect(runtimeIssues).toEqual([]);
});

test('학생은 seed 성적을 수정·재조회하고 2025·2026 공개 자료 대학 선택까지 간다', async ({ page }) => {
  const runtimeIssues = collectRuntimeIssues(page);
  const suffix = Date.now().toString(36);
  const updatedSubject = `체험 저장 재조회 ${suffix}`;

  await startRole(page, '학생');
  await page.getByRole('link', { name: '내 성적·상담 자료' }).click();
  await expect(page.getByRole('heading', { name: '저장 성적 관리' })).toBeVisible();
  await expect(page.locator('.account-records-table tbody tr')).not.toHaveCount(0);
  await expect(page.getByText('빅데이터 프로그래밍', { exact: true })).toBeVisible();

  const seniorRecord = page.locator('.account-records-table tbody tr', {
    hasText: '빅데이터 프로그래밍',
  }).first();
  await seniorRecord.getByText('성적 수정', { exact: true }).click();
  const seedSubject = seniorRecord.locator(
    'input[name$="-subject_name"][value="빅데이터 프로그래밍"]',
  );
  await expect(seedSubject).toBeVisible();
  await seedSubject.fill(updatedSubject);
  await seniorRecord.getByRole('button', { name: '수정 저장' }).click();
  await expect(page.getByText(updatedSubject, { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText(updatedSubject, { exact: true })).toBeVisible();

  await page.getByRole('link', { name: '내 업무공간' }).click();
  await page.getByRole('link', { name: '공개 성적 계산' }).click();
  await page.getByRole('link', { name: '합성 예시 불러오기' }).click();
  await expect(page.getByText('합성 예시 성적을 불러왔습니다.')).toBeVisible();
  await page.getByRole('button', { name: '입력값 확인하고 대학 선택으로' }).click();
  await expect(page.getByRole('heading', { name: '학생 성적 입력 검수' })).toBeVisible();
  await page.getByRole('button', { name: '확인 완료하고 대학 선택' }).click();

  await expect(page.getByRole('heading', {
    name: '비교할 대학과 학과를 선택하세요',
  })).toBeVisible();
  const resultYear = page.locator('select[name="admission_result_year"]');
  await expect(resultYear.locator('option[value="2025"]')).toHaveCount(1);
  await expect(resultYear.locator('option[value="2026"]')).toHaveCount(1);
  await resultYear.selectOption('2025');
  await expect(resultYear).toHaveValue('2025');
  await resultYear.selectOption('2026');
  await expect(resultYear).toHaveValue('2026');
  await expect(page.locator('[data-institution-filter] option')).toHaveCount(44);
  expect(await page.locator('[data-program-option]').count()).toBeGreaterThanOrEqual(1048);
  await page.locator('[data-institution-filter]').selectOption({
    label: '경기과학기술대학교',
  });
  await expect(page.locator(
    '[data-program-group][data-institution="경기과학기술대학교"]',
  )).toBeVisible();
  await page.screenshot({
    path: `${screenshotDir}/phase20-student-public-targets.png`,
    fullPage: true,
  });
  expect(runtimeIssues).toEqual([]);
});

test('교사가 학급·학생·과목을 저장하고 별도 학생 세션이 연결 코드를 사용한다', async ({ page, browser }) => {
  const teacherIssues = collectRuntimeIssues(page);
  const suffix = Date.now().toString(36).replace(/[^a-z0-9]/gu, '');
  const department = `합성연결학과${suffix}`;
  const className = `E2E-${suffix}`;
  const anonymousCode = `SYN-${suffix}`.slice(0, 40);
  const subjectName = `연결 저장 과목 ${suffix}`;

  await startRole(page, '교사');
  await page.getByRole('link', { name: '학과·학급 학생 관리' }).click();
  await expect(page.getByRole('heading', { name: '학과·학급과 학생 성적' })).toBeVisible();

  const classroomForm = page.locator('form.classroom-create-form');
  await classroomForm.locator('input[name="academic_year"]').fill('2027');
  await classroomForm.locator('input[name="department_name"]').fill(department);
  await classroomForm.locator('input[name="class_name"]').fill(className);
  await classroomForm.getByRole('button', { name: '학급 만들기' }).click();
  await expect(page.getByRole('status').filter({
    hasText: '학급을 만들었습니다.',
  })).toBeVisible();

  const classCard = page.locator('.classroom-card', {
    hasText: `${department} · ${className}`,
  });
  await expect(classCard).toBeVisible();
  await classCard.locator('input[name="anonymous_code"]').fill(anonymousCode);
  await classCard.getByRole('button', { name: '학생 추가·연결코드 발급' }).click();
  await expect(page.getByRole('heading', { name: '학생 연결 코드' })).toBeVisible();
  const connectionCode = (await page.locator('[data-connection-code]').innerText()).trim();
  expect(connectionCode).toMatch(/^[A-Za-z0-9_-]{20,64}$/u);

  const courseForm = page.locator('form[action*="/students/"][action$="/courses"]');
  await expect(courseForm.getByText('성적 출처는 학년별로 자동 적용됩니다.')).toBeVisible();
  await expect(courseForm.locator('[name="record_source"]')).toHaveCount(0);
  await expect(courseForm.locator('[name="is_vocational_training_semester"]')).toHaveCount(0);
  await courseForm.locator('input[name="academic_year"]').fill('2027');
  await courseForm.locator('select[name="grade"]').selectOption('3');
  await courseForm.locator('select[name="semester"]').selectOption('1');
  await courseForm.locator('input[name="subject_group"]').fill('체험교과');
  await courseForm.locator('input[name="subject_name"]').fill(subjectName);
  await courseForm.locator('input[name="credits"]').fill('3');
  await courseForm.locator('input[name="rank_grade"]').fill('2');
  await courseForm.getByRole('button', { name: '검수 완료 과목으로 추가' }).click();
  await expect(page.getByRole('status').filter({
    hasText: '학생 성적 과목을 추가했습니다.',
  })).toBeVisible();
  await expect(page.getByText(subjectName, { exact: true })).toBeVisible();

  const studentContext = await browser.newContext({
    ignoreHTTPSErrors: process.env.E2E_IGNORE_HTTPS_ERRORS === 'true',
  });
  const studentPage = await studentContext.newPage();
  const studentIssues = collectRuntimeIssues(studentPage);
  await startRole(studentPage, '학생');
  await studentPage.getByRole('link', { name: '내 성적·상담 자료' }).click();
  await studentPage.getByLabel('연결 코드').fill(connectionCode);
  await studentPage.getByLabel('위 공유 범위와 연결 해제 효과를 확인했습니다.').check();
  await studentPage.getByRole('button', { name: '학급 연결' }).click();
  await expect(studentPage.getByRole('status').filter({
    hasText: '교사 학급 연결이 완료되었습니다.',
  })).toBeVisible();
  await expect(studentPage.getByText(`${department} · ${className}`)).toBeVisible();
  const linkedCourseRow = studentPage.locator('tbody tr', { hasText: subjectName });
  await expect(linkedCourseRow).toContainText('연결 학생 성적');
  await expect(linkedCourseRow).toContainText('읽기 전용 공유');
  await studentPage.screenshot({
    path: `${screenshotDir}/phase20-student-teacher-link.png`,
    fullPage: true,
  });
  expect(studentIssues).toEqual([]);
  await studentContext.close();

  await page.reload();
  const refreshedCard = page.locator('.classroom-card', {
    hasText: `${department} · ${className}`,
  });
  await expect(refreshedCard).toContainText('학생 계정 연결됨');
  await expect(page.getByText(subjectName, { exact: true })).toBeVisible();
  expect(teacherIssues).toEqual([]);
});

test('보조 관리자는 체험 가입자 승인만 수행하고 교사·주 관리자 기능은 403을 받는다', async ({ page }) => {
  const runtimeIssues = collectRuntimeIssues(page);
  const suffix = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
  const email = `phase20-${suffix}@example.invalid`;
  const displayName = `합성 승인 학생 ${suffix}`;
  const password = `phase20-registration-${suffix}`;

  await page.goto(route('/auth/register?account_type=student'));
  await page.getByLabel('표시 이름').fill(displayName);
  await page.getByLabel('로그인 이메일').fill(email);
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByLabel('비밀번호 확인').fill(password);
  await page.getByRole('button', { name: '가입 승인 요청' }).click();
  await expect(page.getByRole('heading', { name: '가입 신청 접수' })).toBeVisible();

  await page.getByRole('link', { name: '체험 인증 메일 확인' }).click();
  await expect(page.getByRole('heading', { name: '체험 인증 메일함' })).toBeVisible();
  const outboxRow = page.locator('tbody tr', { hasText: email }).first();
  await expect(outboxRow).toBeVisible();
  const verificationHref = await outboxRow.getByRole('link', {
    name: '인증 계속하기',
  }).getAttribute('href');
  expect(verificationHref).toBeTruthy();
  await page.goto(sameOriginDemoUrl(verificationHref || ''));
  await expect(page.getByRole('heading', { name: '이메일 주소 확인' })).toBeVisible();
  await page.getByRole('button', { name: '이메일 인증 완료' }).click();
  await expect(page.getByRole('status').filter({
    hasText: '이메일 인증을 완료했습니다.',
  })).toBeVisible();

  await startRole(page, '보조 관리자');
  await page.getByRole('link', { name: '계정 승인 요청' }).click();
  const memberRow = page.locator('tr', { hasText: email });
  await expect(memberRow).toContainText('PENDING_APPROVAL');
  await memberRow.getByRole('button', { name: /회원 승인/u }).click();
  await expect(page.getByRole('status').filter({
    hasText: '회원 승인이 완료되었습니다.',
  })).toBeVisible();
  await expect(page.locator('tr', { hasText: email })).toHaveCount(0);

  for (const forbiddenPath of [
    '/teacher/classrooms',
    '/teacher/outcomes',
    '/account/records',
    '/admin/consultations/new',
    '/admin/ai/settings',
    '/admin/catalog',
  ]) {
    const forbidden = await page.context().request.get(route(forbiddenPath));
    expect(forbidden.status()).toBe(403);
    expect(await forbidden.text()).toContain('Forbidden');
  }
  await page.goto(route('/dashboard'));
  await expect(page.getByRole('heading', {
    name: '보조 관리자 승인 업무',
  })).toBeVisible();
  await expect(page.getByRole('link', { name: '학과·학급 학생 관리' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: '학생 상담자료 만들기' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /BYOK/u })).toHaveCount(0);
  await expect(page.getByRole('link', { name: '대학·학과·전형 기준정보' })).toHaveCount(0);
  expect(runtimeIssues).toEqual([]);
});

test('주 관리자는 관리 화면·CSV import·fixture 크롤링 미리보기를 실행한다', async ({ page }) => {
  test.slow();
  const runtimeIssues = collectRuntimeIssues(page);
  const suffix = Date.now().toString(36);

  await startRole(page, '주 관리자');
  const adminPages = [
    ['/admin/members', '회원 승인 및 권한 관리'],
    ['/admin/catalog', '대학·전형 기준정보'],
    ['/admin/admission-results', '연도별 입시결과 가져오기'],
    ['/admin/sources', '출처 문서와 검증 결정'],
    ['/admin/rules', '규칙 검수 대기열'],
  ];
  for (const [pathname, heading] of adminPages) {
    const response = await page.goto(route(pathname));
    expect(response?.status()).toBe(200);
    await expect(page.getByRole('heading', { name: heading })).toBeVisible();
    await expectRenderedPage(page);
  }

  await page.goto(route('/admin/catalog'));
  await expect(page.getByRole('heading', { name: '대학 목록' })).toBeVisible();
  await expect(page.getByText('경기과학기술대학교', { exact: true }).first()).toBeVisible();
  await page.goto(route('/admin/sources'));
  await expect(page.locator('form[action$="/admin/sources/upload"]')).toBeVisible();
  await page.goto(route('/admin/admission-results'));

  const importCsv = [
    '결과학년도,지역,대학명,캠퍼스명,모집시기,전공명,주야,전형구분1,전형구분2,모집인원,지원자수,합격자수,경쟁률,합격자최고,합격자평균,합격자최저,점수기준,점수방향,source_reference',
    `2026,경기,경기과학기술대학교,경기 지역,정시모집,경영학과,주간,일반전형,일반전형,3,,,37.33,,65.06,56,POINT_SCORE,HIGHER_IS_BETTER,synthetic-phase20-${suffix}`,
  ].join('\n');
  const importForm = page.locator('form', {
    has: page.locator('input[name="result_file"]'),
  });
  await importForm.locator('input[name="result_file"]').setInputFiles({
    name: `phase20-${suffix}.csv`,
    mimeType: 'text/csv',
    buffer: Buffer.from(importCsv, 'utf8'),
  });
  await importForm.locator('input[name="source_code"]').fill(`PHASE20-${suffix}`);
  await importForm.locator('input[name="source_dataset_version"]').fill(`2026-${suffix}`);
  await importForm.locator('input[name="result_academic_year"]').fill('2026');
  await importForm.locator('input[name="target_academic_year"]').fill('2027');
  await importForm.locator('input[name="source_reference"]').fill(
    `synthetic-phase20-${suffix}`,
  );
  await importForm.getByRole('button', { name: '미리보기 만들기' }).click();
  await expect(page.getByRole('heading', { name: '자동 열 mapping 확인' })).toBeVisible();
  await expect(page.locator('body')).toContainText('자동 preview 행');

  await page.goto(route('/admin/admission-results'));
  const crawlerForm = page.locator(
    'form[action$="/admin/admission-results/collect/procollege"]',
  );
  await expect(crawlerForm).toBeVisible();
  await crawlerForm.locator('input[name="result_academic_year"]').fill('2026');
  await crawlerForm.locator('input[name="target_academic_year"]').fill('2027');
  await crawlerForm.locator('input[name="page_count"]').fill(
    String(1 + (Date.now() % 400)),
  );
  await crawlerForm.getByRole('button', { name: 'raw 수집 후 검수 미리보기' }).click();
  await expect(page.getByRole('heading', { name: '자동 열 mapping 확인' })).toBeVisible();
  await expect(page.locator('body')).toContainText('자동 preview 행');
  await expect(page.locator('body')).toContainText('institution_name');
  await page.screenshot({
    path: `${screenshotDir}/phase20-main-admin-crawler-preview.png`,
    fullPage: true,
  });
  expect(runtimeIssues).toEqual([]);
});

test('계정 보안·로컬 Google 동의와 BYOK 저장·마스킹·삭제가 끝까지 동작한다', async ({ page }) => {
  const runtimeIssues = collectRuntimeIssues(page);
  const publicPassword = await demoPublicPassword(page);
  const suffix = Date.now().toString(36);
  const newPassword = `phase20-new-password-${suffix}`;
  const apiKey = `phase20-browser-key-${suffix}-9XQ7`;

  await page.getByRole('button', { name: '학생 기능 체험 시작', exact: true }).click();
  await expect(page.getByRole('heading', { name: '학생 업무공간' })).toBeVisible();
  await page.getByRole('link', { name: '계정 보안' }).click();
  await expect(page.getByRole('heading', { name: '회원정보·로그인 보안' })).toBeVisible();

  const passwordSection = page.locator('section', {
    has: page.getByRole('heading', { name: '비밀번호 변경' }),
  });
  await passwordSection.getByLabel('현재 비밀번호').fill(publicPassword);
  await passwordSection.getByLabel('새 비밀번호', { exact: true }).fill(newPassword);
  await passwordSection.getByLabel('새 비밀번호 확인').fill(newPassword);
  await passwordSection.getByRole('button', { name: '비밀번호 변경' }).click();
  await expect(page.getByRole('status').filter({
    hasText: '비밀번호를 변경했습니다.',
  })).toBeVisible();

  const googleSection = page.locator('section', {
    has: page.getByRole('heading', { name: 'Google 계정 연결' }),
  });
  await googleSection.getByLabel('현재 비밀번호').fill(newPassword);
  await googleSection.getByRole('button', { name: 'Google 계정 연결' }).click();
  await expect(page.getByRole('heading', { name: 'Google 계정 연결 체험' })).toBeVisible();
  await expect(page.getByText('실제 Google 계정은 사용하지 않습니다.')).toBeVisible();
  await expect(page.getByLabel('Google 체험 이메일')).toHaveAttribute('readonly', '');
  await page.getByRole('button', { name: '체험 승인 계속하기' }).click();
  await expect(page.getByRole('status').filter({
    hasText: 'Google 계정을 이 계정에 연결했습니다.',
  })).toBeVisible();

  await page.goto(route('/admin/ai/settings'));
  await expect(page.getByText('세션별 BYOK 전체 흐름 체험')).toBeVisible();
  await page.locator('#ai-provider').selectOption('OPENAI');
  await page.locator('#ai-api-key').fill(apiKey);
  await page.getByRole('button', { name: '암호화 저장 또는 교체' }).click();
  await expect(page.getByText('••••9XQ7', { exact: true })).toBeVisible();
  await expect(page.getByText(apiKey, { exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByText('••••9XQ7', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '키 삭제' }).click();
  await expect(page.getByText(/저장된 공급자 키가 없습니다/u)).toBeVisible();
  await page.screenshot({
    path: `${screenshotDir}/phase20-security-google-byok.png`,
    fullPage: true,
  });
  expect(runtimeIssues).toEqual([]);
});
