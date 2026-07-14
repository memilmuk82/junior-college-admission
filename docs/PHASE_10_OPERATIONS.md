# Phase 10 운영 런북

## 백업 생성

운영 `.env`와 PostgreSQL 컨테이너가 준비된 상태에서만 실행한다.

```bash
BACKUP_DIR=backups ./scripts/backup_postgres.sh
```

스크립트는 `umask 077`을 적용하고 임시 dump를 만든 뒤 파일 크기를 확인해 원자적으로 이동한다. 실패하면 임시파일을 삭제하며, `backups/`는 Git과 Docker build context에서 제외된다.

## 복구 리허설

복구는 운영 volume이 아닌 별도 격리된 PostgreSQL 컨테이너와 합성 데이터에서 수행한다.

1. 백업 파일 SHA-256과 생성 시각을 별도 운영 기록에 남긴다.
2. 격리 DB를 만들고 `pg_restore --list`로 archive 목차를 읽기 전용 검증한다.
3. 별도 DB에 restore하고 `flask db current`, 핵심 healthcheck, migration drift를 확인한다.
4. 합성 smoke·회귀 테스트 후 격리 volume을 폐기한다.
5. 실패 원인과 복구 시간을 기록하고 운영 DB에는 접근하지 않는다.

실제 운영 DB 복구, 데이터 삭제, 외부 배포는 이 런북만으로 자동 수행하지 않는다.

## 운영 게이트

- 규칙 배치는 대학 5곳 단위로 근거·학년도·캠퍼스·전형·버전·골든 테스트를 모두 확인한다.
- 최종 모집요강은 기존 게시 버전을 수정하지 않고 새 DRAFT와 lineage로 교체한다.
- 성능 기준선은 지원자격→성적 계산→입시결과 비교의 결정론적 흐름을 합성 데이터로 측정한다.
- 키 회전·보유기간 삭제·백업 복구는 감사 로그와 실패 복구 결과를 남긴다.
- 현장 파일럿은 실제 학생 자료 없이 합성 계정·합성 상담으로만 진행한다.
