# 프론트엔드 구조

## 렌더링 원칙

- Flask Jinja2 서버 렌더링을 기본으로 한다.
- React, Vue, Svelte, Next.js 등 SPA 프레임워크와 TypeScript를 도입하지 않는다.
- 링크 이동, 조회, 입력, 수정, 저장의 핵심 흐름은 HTML 폼 제출과 서버 응답만으로 동작해야 한다.
- 부분 갱신이나 파일 미리보기처럼 필요한 상호작용만 Vanilla JavaScript와 `fetch` API로 보강한다.
- JavaScript가 비활성화되어도 핵심 상담 흐름을 완료할 수 있어야 한다.

## 인쇄

- 학생 상담 결과와 교사용 관리·근거 화면은 별도 Jinja 템플릿으로 구성한다.
- 공통 A4 규칙은 `app/static/css/print.css`에 둔다.
- 학생용 `.student-print`와 교사용 `.teacher-print` 레이아웃은 Phase 8에서 실제 데이터와 함께 완성하고 Playwright 인쇄 미리보기로 검증한다.
- 인쇄 화면에는 웹 탐색 요소와 동작 버튼을 포함하지 않는다.
