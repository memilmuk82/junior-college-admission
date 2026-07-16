// @ts-check
import { test, expect } from '@playwright/test';

const appUrl = process.env.APP_URL || process.env.ADMIN_URL;
const approverUsername = process.env.ASSISTANT_ADMIN_USERNAME || process.env.ADMIN_USERNAME;
const approverPassword = process.env.ASSISTANT_ADMIN_PASSWORD || process.env.ADMIN_PASSWORD;
const assistantUsername = process.env.ASSISTANT_ADMIN_USERNAME;
const assistantPassword = process.env.ASSISTANT_ADMIN_PASSWORD;

function requireApprovalEnvironment() {
  if (!appUrl || !approverUsername || !approverPassword) {
    test.skip(
      true,
      'APP_URL (or ADMIN_URL) and synthetic approver credentials are required'
    );
  }
}

async function login(page, loginName, password) {
  await page.goto(`${appUrl}/auth/login`);
  await page.getByLabel('아이디', { exact: false }).fill(loginName);
  await page.getByLabel('비밀번호', { exact: true }).fill(password);
  await page.getByRole('button', { name: /^로그인/ }).click();
}

async function logout(page) {
  await page.getByRole('button', { name: '로그아웃' }).click();
  await expect(page.getByRole('heading', { name: '교직원 로그인' })).toBeVisible();
}

test.describe('approved internal staff membership without JavaScript', () => {
  test.use({ javaScriptEnabled: false });

  test('registration stays pending until an approver activates the member', async ({ page }) => {
    requireApprovalEnvironment();
    const suffix = `${Date.now()}-${process.pid}`;
    const loginName = `synthetic.teacher-${suffix}`;
    const email = `${loginName}@example.invalid`;
    const password = 'synthetic-member-password-2026';
    const browserErrors = [];
    page.on('console', (message) => {
      if (message.type() === 'error') browserErrors.push(message.text());
    });
    page.on('pageerror', (error) => browserErrors.push(error.message));

    await page.goto(`${appUrl}/auth/register`);
    await expect(page.getByRole('heading', { name: '교직원 회원가입' })).toBeVisible();
    await expect(page.getByText(/학생 공개 회원가입이 아닙니다/)).toBeVisible();
    await page.getByLabel('표시 이름').fill('합성 승인 테스트 교사');
    await page.getByLabel('아이디', { exact: true }).fill(loginName);
    await page.getByLabel('업무용 이메일').fill(email);
    await page.getByLabel('비밀번호', { exact: true }).fill(password);
    await page.getByLabel('비밀번호 확인').fill(password);
    await page.getByRole('button', { name: '가입 승인 요청' }).click();

    await expect(page.getByRole('heading', { name: '가입 신청 접수' })).toBeVisible();

    await login(page, loginName, password);
    await expect(page.getByRole('heading', { name: '관리자 승인 대기' })).toBeVisible();
    await expect(page.getByText('PENDING_APPROVAL', { exact: true })).toBeVisible();

    await page.goto(`${appUrl}/admin/consultations/new`);
    await expect(page.getByRole('heading', { name: '관리자 승인 대기' })).toBeVisible();
    await logout(page);

    await login(page, approverUsername, approverPassword);
    await page.goto(`${appUrl}/admin/members`);
    await expect(page.getByRole('heading', { name: '회원 승인 및 권한 관리' })).toBeVisible();
    const memberRow = page.locator('tbody tr').filter({ hasText: loginName });
    await expect(memberRow).toContainText('PENDING_APPROVAL');
    await memberRow.getByRole('button', { name: `${loginName} 회원 승인` }).click();
    await expect(page.getByRole('status')).toContainText('회원 승인이 완료되었습니다.');
    const approvedMemberRow = page.locator('tbody tr').filter({ hasText: loginName });
    if (await approvedMemberRow.count()) {
      await expect(approvedMemberRow).toContainText('ACTIVE');
    }
    await logout(page);

    await login(page, loginName, password);
    await expect(page.getByRole('heading', { name: '단계형 상담 시작' })).toBeVisible();
    await expect(page.locator('body')).not.toContainText('관리자 승인 대기');
    expect(browserErrors).toEqual([]);
  });

  test('assistant admin has approval UI but cannot enter rule settings', async ({ page }) => {
    if (!appUrl || !assistantUsername || !assistantPassword) {
      test.skip(true, 'synthetic ASSISTANT_ADMIN credentials are required');
    }

    await login(page, assistantUsername, assistantPassword);
    await page.goto(`${appUrl}/admin/members`);
    await expect(page.getByText(/승인 대기 일반 회원만 승인/)).toBeVisible();
    await expect(page.getByRole('button', { name: '역할 저장' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '상태 저장' })).toHaveCount(0);

    const response = await page.goto(`${appUrl}/admin/rules`);
    expect(response).not.toBeNull();
    expect(response.status()).toBe(403);
  });
});
