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

복수지원 상태는 `ALLOWED`, `BLOCKED`, `NEEDS_REVIEW`다. 상담에서 복수지원 규칙을 실행하지 않은 경우에는 `NOT_EVALUATED`로 명시한다. 이는 한 전형 자체의 지원자격과 독립적이며 지원 이력 조합만 설명한다.

결격 상태는 `CLEAR`, `DISQUALIFIED`, `NEEDS_REVIEW`, `INSUFFICIENT_DATA`다. 민감 결격 사실은 학생 사실 모델이나 영구 DB 행에 합치지 않고 판정 요청의 세션 전용 입력으로만 사용한다. 결격과 점수 감점은 서로 다른 규칙 유형이다.

## 성적 입력 상태

- `READY`: 게시 범위 규칙으로 검증된 계산 후보가 한 개 이상 선택됨
- `NEEDS_REVIEW`: 전형 의존 또는 수동 검토 범위로 자동 선택할 수 없음
- `INSUFFICIENT_DATA`: 규칙은 확정됐지만 선택 가능한 검증 성적이 없음

성적 입력 상태는 점수가 아니며 자격 상태를 변경하지 않는다. trace의 출처·학기·과목은 이후 계산 엔진이 사용할 후보의 근거다.

## 성적 계산 모드

- `GLOBAL`·`PER_GRADE`: 우수 학기를 전체 후보에서 고르는지 학년마다 고르는지 구분한다.
- `EQUAL`: 선택 학기를 동일 가중한다.
- `GRADE_ONLY`: 학기 집계 후 학년 가중치만 적용한다.
- `GLOBAL_SEMESTER`: 선택된 전체 학기의 가중치 합을 1로 적용한다.
- `GRADE_WITHIN_SEMESTER`: 학년 가중치와 해당 학년 내부 학기 가중치를 곱한다.
- `LOWER_IS_BETTER`·`HIGHER_IS_BETTER`: 등급과 점수처럼 우수 방향이 다른 값을 명시한다.

Z점수의 `UNIVERSITY_OFFICIAL`, `VERIFIED_REFERENCE`, `INTERNAL_CALCULATION`, `MANUAL_REVIEW`는 계산식 자체가 아니라 근거 수준을 나타낸다. 계산 trace는 공식 버전, 반올림 전후 값, 절단값, 변환표 코드·버전과 근거 위치를 보존한다.

## 반영 평균등급

`ReflectedGradeResult`는 배점 환산 결과와 분리된 등급 척도 결과다. 반올림 전 평균, 표시 평균, 등급 척도, 선택 학기·과목·이수단위, 학년·학기 가중치, 중간·표시 반올림, 규칙 ID·버전을 보존한다. 점수 변환용 `score_base`·`score_multiplier`·`maximum_score`는 평균등급 자체를 바꾸지 않는다.

`계산 기준 준비 중`은 학과·전형 기준정보는 있으나 실행 가능한 게시 자격·성적 범위·성적 규칙이 완성되지 않은 항목 상태다. 지원 불가와 같은 의미로 해석하지 않는다.

공개 입시결과의 `INCOMPATIBLE_SCALE`은 `score_basis`가 학생 반영 평균등급 척도와 다른 상태다. 배점 등 다른 척도의 평균 숫자는 결과 화면·출력·AI payload에서 숨기고 직접 비교 불가 사유만 표시한다.
