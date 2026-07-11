# 도메인 용어집

## 지원자격 상태

- `ELIGIBLE`: 현재 확인된 사실과 게시 규칙으로 지원 가능
- `CONDITIONALLY_ELIGIBLE`: 게시 규칙이 명시한 후속 조건을 전제로 지원 가능
- `INELIGIBLE`: 현재 확인된 사실과 게시 규칙으로 지원 불가
- `NEEDS_REVIEW`: 규칙이 사람 검토를 명시하거나 제한형 DSL로 확정할 수 없음
- `INSUFFICIENT_DATA`: 판정에 필요한 학생 사실이 누락된 내부 상태

`NEEDS_REVIEW`와 `INSUFFICIENT_DATA`는 확정 결과로 표시하지 않는다. 성적 계산 진입은 `ELIGIBLE`과 `CONDITIONALLY_ELIGIBLE`만 허용한다.

## 학생 사실

학생 사실은 원적교·최종 고교 유형, 졸업 상태, 직업위탁 참여·이수 상태와 기간, 전학, 검정고시 및 공식 전형이 실제 요구하는 제한된 추가 조건이다. 학생에게 일반고·특성화고 전형 중 하나를 배정하는 분류값이 아니다.

학교 유형 코드는 `GENERAL`, `VOCATIONAL`, `MEISTER`, `COMPREHENSIVE_VOCATIONAL`, `LIFELONG_EDUCATION`, `FOREIGN`을 사용한다. 값이 확인되지 않았으면 별도 추정 코드가 아니라 `None`으로 유지한다.

현재 정의는 엔진 실행 계약이며 실제 대학별 의미는 검수 완료된 공식 규칙과 출처 인용이 연결된 뒤에만 공개한다.

## 복수지원과 결격

복수지원 상태는 `ALLOWED`, `BLOCKED`, `NEEDS_REVIEW`다. 이는 한 전형 자체의 지원자격과 독립적이며 지원 이력 조합만 설명한다.

결격 상태는 `CLEAR`, `DISQUALIFIED`, `NEEDS_REVIEW`, `INSUFFICIENT_DATA`다. 민감 결격 사실은 학생 사실 모델이나 영구 DB 행에 합치지 않고 판정 요청의 세션 전용 입력으로만 사용한다. 결격과 점수 감점은 서로 다른 규칙 유형이다.
