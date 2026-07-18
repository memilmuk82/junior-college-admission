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

## Phase 13 학과 선택과 결과

- 학과 체크박스는 HTML 이름 `program_ids`를 반복 제출하며 JavaScript 없이도 복수 선택·제출된다.
- 대학 전체 선택, 대학명·학과명 검색, 검색 결과 전체 선택, 선택 개수는 `consultation_programs.js`의 점진적 향상이다.
- 결과는 사용자 학과 선택 순서 안에서 전형 코드의 결정적 순서를 사용하며 평균등급으로 대학을 정렬하지 않는다.
- 학생용 A4는 전체 요약, 교사용 A4는 각 전형의 자격·성적 범위·과목/이수단위·가중치·반올림·근거 trace를 추가한다.
