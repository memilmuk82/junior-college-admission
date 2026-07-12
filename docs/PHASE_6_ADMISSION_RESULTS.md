# Phase 6 입시결과 수집·분석 계약

## 운영 목적

과거 입시결과는 경쟁률, 지원·합격 인원, 최고·평균·최저 성적을 전형·학과별로 비교하는 결과 분석 자료다. 과거 결과를 현재 모집학년도의 성적 산식이나 공식 합격선으로 바꾸지 않는다.

분석 업무키는 다음 여섯 값을 모두 사용한다.

- 모집학년도
- 대학 코드
- 캠퍼스 코드
- 모집시기
- 전형 코드
- 학과 코드

빈 키, 중복 키, 수집 단위와 다른 학년도는 batch 전체를 차단한다.

## 수집 단계

```text
source request
→ bounded transport
→ immutable raw collection
→ canonical normalization
→ staging validation
→ administrator confirmation
→ published result
→ result analysis input
```

`CollectionPolicy`는 timeout, 최대 재시도, 재시도 간격, 호출 간격, 최대 응답 크기, 최대 페이지 수, 최대 행 수를 고정한다. adapter는 요청 생성, 응답 행 추출, canonical 정규화를 각각 별도 메서드로 제공한다. Phase 6 테스트는 합성 transport만 사용하며 실제 사이트를 호출하지 않는다.

raw collection은 요청 fingerprint, 응답 SHA-256, collection SHA-256과 원시 행을 보존한다. staging은 raw를 수정하지 않고 새 행으로 정규화한다. raw 객체를 게시 함수에 전달하면 명시적으로 거부한다.

## 품질 차단

다음 중 하나라도 발생하면 staging 상태는 `BLOCKED`다.

- 이전 수집 대비 행 수 급감
- 이전 수집 대비 페이지 수 급감
- 빈 업무키
- 같은 batch의 업무키 중복
- 수집 단위와 다른 모집학년도
- 정규화 실패
- 음수·비유한 결과 지표
- 결과 지표 전체 누락
- 빈 수집 결과

오류 행을 제외한 부분 게시를 허용하지 않는다. 관리자가 확인한 행 수가 staging 전체 행 수와 정확히 같아야 게시 객체를 만들 수 있다.

## PostgreSQL 단계 분리

- `admission_result_raw_batches`, `admission_result_raw_pages`: 수집 요청·응답의 근거 단위
- `admission_result_staging_batches`, `admission_result_staging_rows`: 정규화·오류 분류 단위
- `admission_result_published_batches`: 관리자와 승인시각·확인 행 수
- `admission_results_published`: 분석에 사용할 버전 고정 결과

staging `READY`는 오류 행 0건과 전체 유효 행을 DB 제약으로 요구한다. published 결과는 동일 업무키에서 활성 `PUBLISHED` 한 건만 허용하고 이전 버전은 `SUPERSEDED`로 보존한다.

결과 지표의 `NULL`과 숫자 `0`은 다르다. 지원자 0명, 경쟁률 0은 그대로 보존하며 누락값으로 바꾸지 않는다.

## 과거 규칙 버전과 결과 분석

과거 결과에 성적 규칙을 연결할 때 다음 세 값을 함께 저장한다.

- `score_rule_id`
- `score_rule_version`
- `score_rule_academic_year`

규칙 모집학년도는 결과 모집학년도와 같아야 한다. 연결할 과거 규칙이 확인되지 않았다면 세 값 모두 `NULL`로 남기며 현재 게시 규칙을 대신 연결하지 않는다.

`load_published_admission_result_for_analysis()`는 정확한 업무키의 활성 `PUBLISHED` 결과만 읽는다. raw·staging·`SUPERSEDED` 행은 결과 분석 입력으로 반환하지 않는다.

## 참고자료 적용

- 폴리텍 서울정수 PDF 33~34쪽 결과: 서울정수·2026 업무키
- 폴리텍 서울강서 PDF 67~69쪽 결과: 서울강서·2026 업무키
- 제공 CSV의 2016~2026 행: 각 행 내부 모집학년도를 유지

위 자료는 자동 seed나 자동 게시 대상으로 사용하지 않는다. source adapter 정규화와 staging 검증, 관리자 승인을 거친 경우에만 운영 분석 자료가 된다.
