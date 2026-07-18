# Phase 14 연도별 공개 입시결과 import

## 연도 계약

- `result_academic_year`: 공개 결과가 실제로 발표된 모집학년도
- `target_academic_year`: 해당 결과를 참고자료로 노출할 상담 대상 학년도
- 업로드 기본 제안은 `target = result + 1`이며 관리자가 화면에서 확인·수정한다.
- 결과 연도와 현재 규칙 연도는 서로 대체하지 않는다. 과거 규칙 ID·버전·연도가 모두
  확인된 행만 직접 비교 계약을 가질 수 있다.

## 관리자 흐름

`/admin/admission-results`에서 다음 순서로 처리한다.

```text
CSV/XLSX 메모리 읽기
→ 결과 시트·머리글 자동 탐지
→ 자동 canonical/source 열 mapping 표시
→ 관리자가 열별 override를 선택·확정
→ 같은 TTL 임시 원본으로 canonical preview 재계산
→ canonical 정규화
→ DB 기준정보 exact mapping
→ VALID / REVIEW / ERROR 미리보기
→ 부분 게시 정책 명시 확인
→ PUBLISHED 데이터셋
→ 같은 출처·결과연도·상담연도의 이전 버전 SUPERSEDED
```

원본 바이트와 원본 파일명은 DB·로그·Git에 저장하지 않는다. 같은 파일은 SHA-256으로
기존 데이터셋을 식별한다. 수식형 셀은 실행하지 않으며 CSV formula injection 후보는
`FORMULA_NOT_ALLOWED` 오류다. 숫자 `0`과 `NULL`은 별도로 보존한다.
mapping 확인 중인 원본은 권한이 제한된 TTL 임시 세션에만 두고, dataset 저장 직후
삭제한다. dataset에는 자동 확정 mapping과 관리자가 고른 override JSON만 보존한다.
열 동의어는 코드가 아니라
`data/seed/phase14_admission_result_column_aliases.json`의 schema/version allowlist로
관리한다. 정규화 후 서로 다른 canonical 필드가 같은 동의어를 주장하면 설정 전체를
fail-closed로 거부한다. 파일의 `모집학년도`가 관리자가 선택한 결과 학년도와 다르면 해당
행은 `RESULT_YEAR_MISMATCH` ERROR다.

상담 서비스는
`app.services.admission_result_imports.load_published_imported_result()`에 상담 대상연도,
결과연도, 대학·캠퍼스·학과·모집시기·전형 코드와 `score_basis`를 모두 넘겨 정확한 한 행을
조회한다. `list_published_result_years()`는 새 데이터 게시 뒤 재배포 없이 상담연도에서
선택 가능한 결과연도를 반환한다. 규칙 상태와 무관하게 학과의 과거 결과를 먼저 보여줄
때는 `list_published_imported_results_for_program()`으로 모집시기·전형별 게시 행을
조회한다.

## 기준 XLSX 대조

- 기준 size: 394,539 bytes
- 기준 SHA-256: `bde8fe5d513ce2737c08815b0d7e1df366dc8844e6ff7f243eccb63c3bd40606`
- `2025 수시(1차) 결과`: 1,818행
- `2025 수시(2차) 결과`: 1,652행
- 합계: 3,470행
- catalog 없는 최초 preview: VALID 0, REVIEW 3,463, ERROR 7
- ERROR 7건은 공개 결과 지표가 모두 비어 있어 자동 게시하지 않는 행이다.
- `성적 입력`과 `대학별 등급` 시트, `나의 등급` 이후 계산 보조열은 importer와 seed
  allowlist 밖이며 읽기 결과·DB·Git에 포함하지 않는다.

## 공개 파일럿 seed

`data/seed/phase14_public_admission_catalog.csv`와
`data/seed/phase14_public_admission_results_2025.csv`는 동양미래대학교·명지전문대학·
인하공업전문대학·연성대학교 4곳 482행의 명시 매핑만 포함한다. seed는 위 기준 XLSX의
두 공개 결과 시트에서 직접 파생되며 각 행 `source_reference`가 XLSX SHA-256·시트·원본
행 번호를 가리킨다. `성적 입력`과 `대학별 등급` 시트는 generator가 접근하지 않는다.
다음 명령은 digest와 482행을 재검사한 뒤 2025 결과→2027 상담 데이터셋을 게시한다.

```bash
flask --app wsgi seed-phase14-public-results --actor-ref '<관리자 actor ref>'
```

고정 대학 코드는 `DONGYANG-MIRAE`, `MYONGJI-COLLEGE`,
`INHA-TECHNICAL-COLLEGE`, `YEONSUNG`이며 캠퍼스 코드는 `MAIN`, 모집시기는
`SUSI-1`·`SUSI-2`다. 전형구분은 다음처럼 별도 canonical 필드로 보존한다.

| 원본 전형구분1 | 원본 전형구분2 | 전형 코드 |
| --- | --- | --- |
| 특별전형 | 일반고 | `SPECIAL-GENERAL-HS` |
| 특별전형 | 특성화고 | `SPECIAL-VOCATIONAL-HS` |
| 일반전형 | 일반전형 | `GENERAL` |
| 특별전형 | 대학자체 | `COLLEGE-SPECIFIC` |

`동양미래대학교(특)`은 별도 대학을 만들지 않고 `DONGYANG-MIRAE`의
`SPECIAL-VOCATIONAL-HS`로 연결한다. seed 482행은 모두 VALID/PUBLISHED다.
동양미래대학교 호텔관광학과 수시1차 특별전형/일반고 대표 행은 XLSX 기준 평균 5.7,
최저 6.3, 모집인원 47이다. XLSX에 없는 경쟁률은 all-years CSV를 대학·학과·모집시기·
전형 canonical 코드가 정확히 한 건 일치할 때만 보조 결합해 8.4를 표시한다. 482행의
`source_reference`는 XLSX primary 시트·행과 `supplemental.competition_rate` CSV hash·행을
함께 기록한다. fuzzy·추정·복수 매치는 보강하지 않는다.

all-years CSV는 2025 동일 범위 484행과 경쟁률·모집인원 존재 여부를 교차검증하고,
exact unique 482개 업무키의 경쟁률에만 field-level supplemental lineage로 사용한다.
이 4개 대학 mapping을 적용한
기준 XLSX 3,470행 preview는 VALID 482, REVIEW 2,981, ERROR 7이다. 나머지 2,981행은 기준정보를 추가 검수하기 전까지
자동 코드를 생성하거나 게시하지 않는다.
