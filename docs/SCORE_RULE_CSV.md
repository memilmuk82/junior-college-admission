# 성적 규칙 표준 CSV 계약

## 운영 원칙과 단계 경계

학교별 성적 규칙은 관리자가 관리자 메뉴에서 직접 수정하는 방식을 기본으로 한다. 표준 CSV는 여러 대학·전형의 동일 스키마 규칙을 일괄 등록·갱신하기 위한 보조 수단이다. 서식·병합 셀 해석 부담이 큰 XLSX는 필수 운영 입력 형식이 아니며 참고자료로만 사용한다.

관리자 직접 편집과 CSV는 모두 `ManagedScoreRule`과 `score_rule_to_payload()`의 canonical 스키마를 사용한다. CSV는 기존 게시 규칙을 수정하거나 게시하지 않는다. Phase 7에서 다음 흐름을 구현한다.

```text
CSV 업로드 → 형식·허용값 검증 → 대상 규칙 식별
→ 신규·변경·충돌·오류 분류 → 변경 전후 미리보기
→ 관리자 확인 → 선택한 유효 행만 DRAFT 새 버전 생성
→ 검수·사람 승인 → 게시
```

Phase 4는 고정 schema, import/export codec과 검증 결과만 제공한다. DB 쓰기, 변경 비교, 승인 화면은 제공하지 않는다.

## 기본 업무키

한 행은 `admission_year + university_code + campus_code + admission_round + admission_track_code`로 식별한다. 파일 안에서 이 키가 중복되면 해당 키의 모든 행을 오류로 처리한다.

## score_rules.csv 헤더

헤더 이름과 순서를 모두 고정한다. 별도 Z점수 표 연결을 위해 요구 목록에 `z_score_table_code`를 추가했다.

```text
schema_version
admission_year
university_code
university_name
campus_code
admission_round
admission_track_code
admission_track_name
rule_version
home_grade_1_included
home_grade_2_included
home_grade_3_semester_1_included
home_grade_3_semester_2_included
vocational_grade_included
vocational_semester_1_included
vocational_semester_2_included
semester_selection_method
best_semester_count
subject_selection_method
best_subject_count
subject_scope
credit_weighted
grade_weight_1
grade_weight_2
grade_weight_3
semester_weight_1_1
semester_weight_1_2
semester_weight_2_1
semester_weight_2_2
semester_weight_3_1
semester_weight_3_2
achievement_handling
career_subject_included
z_score_policy
z_score_source
z_score_table_code
attendance_included
interview_ratio
practical_ratio
rounding_mode
rounding_scale
maximum_score
evidence_document_id
evidence_page
evidence_location
source_status
change_reason
administrator_note
```

## 허용 코드

- boolean: `TRUE`, `FALSE`만 허용한다. 빈 값은 `None`이며 `FALSE`와 다르다.
- `semester_selection_method`: `ALL`, `FIRST_N`, `RECENT_N`, `BEST_N`, `MANUAL_REVIEW`
- `subject_selection_method`: `ALL`, `BEST_N`, `SCOPE`, `MANUAL_REVIEW`
- `subject_scope`: `ALL`, `GENERAL_SUBJECTS`, `CAREER_SUBJECTS`, `SPECIFIED`, `MANUAL_REVIEW`
- `achievement_handling`: `EXCLUDE`, `GRADE_TABLE`, `DISTRIBUTION`, `MANUAL_REVIEW`
- `z_score_policy`: `NOT_USED`, `INTERNAL_CALCULATION`, `TABLE_LOOKUP`, `MANUAL_REVIEW`
- `z_score_source`: `UNIVERSITY_OFFICIAL`, `VERIFIED_REFERENCE`, `INTERNAL_CALCULATION`, `MANUAL_REVIEW`
- `rounding_mode`: `ROUND_HALF_UP`, `ROUND_HALF_EVEN`, `ROUND_DOWN`, `ROUND_UP`, `TRUNCATE`, `MANUAL_REVIEW`
- `source_status`: `AMENDED_FINAL_GUIDE`, `FINAL_GUIDE`, `AMENDED_IMPLEMENTATION_PLAN`, `IMPLEMENTATION_PLAN`, `COMMON_STANDARD`, `VERIFIED_REFERENCE`, `REFERENCE_ONLY`, `AI_EXTRACTED_DRAFT`, `MANUAL_REVIEW`

공식 근거가 부족하면 `source_status=MANUAL_REVIEW`로 두며 게시 대상으로 취급하지 않는다.

## 값 검증

- UTF-8과 UTF-8 BOM을 지원한다.
- 파일은 5 MiB, 데이터는 10,000행, 셀은 10,000자를 넘을 수 없다.
- 지정 헤더 외 열, 헤더 순서 변경, 행별 열 개수 오류를 명시적으로 거부한다.
- 비율과 점수는 `Decimal`로 읽고 NaN·Infinity를 거부한다.
- 학년 가중치와 학기 가중치는 동시에 사용할 수 없다. 선택한 방식의 가중치는 빠짐없이 입력하고 합계가 정확히 1이어야 한다.
- 학기 가중치는 선택된 정확한 학년·학기에 적용한다. 선택되지 않은 학기의 양수 가중치와 선택된 학기의 빈 가중치는 오류다.
- 공식 가중치가 일부만 있으면 동일 비율로 추정하지 않는다. 빈 값은 미확정, `0`은 명시적 미반영으로 구분한다.
- 비율은 0 이상 1 이하이고 면접·실기 합계는 1을 넘을 수 없다.
- `FIRST_N`, `RECENT_N`, `BEST_N` 학기 선택과 `BEST_N` 과목 선택에는 양의 count가 필요하다.
- 빈 값은 `None`, 문자열 `0`은 `Decimal("0")`으로 보존한다.
- 자유 수식 열, 추가 payload 필드, 수식형 셀은 허용하지 않는다.
- 면접·실기는 `non_predictive_components`에 안내 메타데이터로만 보존하고 예상점수에 합산하지 않는다.
- 검정고시 변환표는 기본 CSV와 Phase 4 계산 범위에서 제외한다.

일부 행이 잘못되어도 오류 행과 유효 행을 분리해 반환한다. 자동 저장이나 부분 게시는 하지 않으며 Phase 7에서 관리자가 선택한 유효 행만 DRAFT로 저장한다.

## z_score_tables.csv

복잡한 변환표를 기본 CSV의 JSON 문자열로 넣지 않는다. `z_score_table_code`로 다음 고정 CSV와 연결한다.

```text
schema_version
table_code
z_min_exclusive
z_max_inclusive
converted_value
evidence_document_id
evidence_page
evidence_location
source_status
change_reason
```

Z 구간은 `(z_min_exclusive, z_max_inclusive]`로 해석한다. 빈 하한·상한은 열린 끝을 뜻하며 같은 `table_code` 안에서 겹치는 구간은 표 전체 오류다. 표의 출처와 페이지는 필수다.
