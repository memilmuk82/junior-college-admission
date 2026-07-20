from __future__ import annotations

from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine import Connection

PHASE16_HEAD = "8e31b7c4d2a6"
PHASE17_HEAD = "b6f1e8a42c73"
LEGACY_RESULT_COUNT = 482
LEGACY_PROGRAM_COUNT = 128


def _legacy_result_snapshot(
    connection: Connection, *, dataset_id: str
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        tuple(row)
        for row in connection.execute(
            text(
                """
                SELECT id, dataset_id, source_row_number,
                       result_academic_year, target_academic_year,
                       institution_code, campus_code, program_code,
                       admission_round_code, admission_track_code,
                       capacity, applicant_count, admitted_count,
                       competition_rate, best_score, average_score, cutoff_score,
                       score_basis, score_direction, source_reference,
                       validation_status, publication_status
                FROM admission_result_import_rows
                WHERE dataset_id = :dataset_id
                ORDER BY source_row_number
                """
            ),
            {"dataset_id": dataset_id},
        )
    )


def _delete_synthetic_legacy_data(
    connection: Connection,
    *,
    dataset_id: str,
    institution_ids: tuple[str, ...],
) -> None:
    connection.execute(
        text("DELETE FROM admission_result_import_rows WHERE dataset_id = :dataset_id"),
        {"dataset_id": dataset_id},
    )
    connection.execute(
        text("DELETE FROM admission_result_import_datasets WHERE id = :dataset_id"),
        {"dataset_id": dataset_id},
    )
    connection.execute(
        text("DELETE FROM institutions WHERE id = ANY(:institution_ids)"),
        {"institution_ids": list(institution_ids)},
    )


def test_phase17_upgrade_preserves_phase16_public_results_and_catalog(
    postgres_engine: Engine,
) -> None:
    """운영 규모의 Phase 14 결과가 Phase 17 변환 중 유실되지 않아야 한다."""

    config = Config("alembic.ini")
    marker = uuid4().hex
    dataset_id = str(uuid4())
    institution_ids = tuple(str(uuid4()) for _ in range(4))
    campus_ids = tuple(str(uuid4()) for _ in range(4))
    program_ids = tuple(str(uuid4()) for _ in range(LEGACY_PROGRAM_COUNT))

    try:
        command.downgrade(config, PHASE16_HEAD)
        with postgres_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version")) == PHASE16_HEAD
            )
            assert "day_night" not in {
                column["name"] for column in inspect(connection).get_columns("programs")
            }

        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO institutions (
                        id, code, name, institution_type
                    ) VALUES (
                        :id, :code, :name, 'JUNIOR_COLLEGE'
                    )
                    """
                ),
                [
                    {
                        "id": institution_id,
                        "code": f"P17-{marker[:12]}-U{index}",
                        "name": f"Phase17 합성 전문대 {marker[:8]}-{index}",
                    }
                    for index, institution_id in enumerate(institution_ids)
                ],
            )
            connection.execute(
                text(
                    """
                    INSERT INTO campuses (
                        id, institution_id, code, name
                    ) VALUES (
                        :id, :institution_id, :code, :name
                    )
                    """
                ),
                [
                    {
                        "id": campus_ids[index],
                        "institution_id": institution_ids[index],
                        "code": "MAIN",
                        "name": "본교",
                    }
                    for index in range(4)
                ],
            )
            connection.execute(
                text(
                    """
                    INSERT INTO programs (
                        id, campus_id, code, name
                    ) VALUES (
                        :id, :campus_id, :code, :name
                    )
                    """
                ),
                [
                    {
                        "id": program_ids[index],
                        "campus_id": campus_ids[index // 32],
                        "code": f"P{index:03d}",
                        "name": f"합성학과 {index:03d}",
                    }
                    for index in range(LEGACY_PROGRAM_COUNT)
                ],
            )
            connection.execute(
                text(
                    """
                    INSERT INTO admission_result_import_datasets (
                        id, source_code, source_dataset_version, source_hash,
                        source_format, result_academic_year, target_academic_year,
                        lifecycle_status, original_row_count, valid_row_count,
                        review_row_count, error_row_count, published_row_count,
                        detected_sheets, column_mapping, column_mapping_overrides,
                        source_reference, collected_at, published_at, published_by
                    ) VALUES (
                        :id, :source_code, 'phase16-production-shape', :source_hash,
                        'CSV', 2025, 2026,
                        'PUBLISHED', :row_count, :row_count,
                        0, 0, :row_count,
                        '["synthetic"]'::json, '{}'::json, '{}'::json,
                        'synthetic-phase16-public-results', now(), now(),
                        'synthetic-migration-verifier'
                    )
                    """
                ),
                {
                    "id": dataset_id,
                    "source_code": f"P17-MIGRATION-{marker}",
                    "source_hash": marker * 2,
                    "row_count": LEGACY_RESULT_COUNT,
                },
            )

            legacy_rows: list[dict[str, object]] = []
            for row_index in range(LEGACY_RESULT_COUNT):
                program_index = row_index % LEGACY_PROGRAM_COUNT
                institution_index = program_index // 32
                legacy_rows.append(
                    {
                        "id": str(uuid4()),
                        "dataset_id": dataset_id,
                        "source_row_number": row_index + 1,
                        "institution_code": f"P17-{marker[:12]}-U{institution_index}",
                        "institution_name": (
                            f"Phase17 합성 전문대 {marker[:8]}-{institution_index}"
                        ),
                        "program_code": f"P{program_index:03d}",
                        "program_name": f"합성학과 {program_index:03d}",
                        "track_code": f"SYNTHETIC-TRACK-{row_index // LEGACY_PROGRAM_COUNT}",
                        "track_name": f"합성전형 {row_index // LEGACY_PROGRAM_COUNT}",
                        "day_night": None if row_index % 2 == 0 else "주간",
                        "capacity": 10 + row_index % 20,
                        "applicant_count": 30 + row_index,
                        "admitted_count": 8 + row_index % 20,
                        "competition_rate": 3 + (row_index % 10) / 10,
                    }
                )

            connection.execute(
                text(
                    """
                    INSERT INTO admission_result_import_rows (
                        id, dataset_id, source_row_number, source_sheet,
                        result_academic_year, target_academic_year, region,
                        institution_code, institution_name,
                        campus_code, campus_name, program_code, program_name,
                        admission_round_code, admission_round_name, day_night,
                        admission_category, admission_track_code, admission_track_name,
                        capacity, applicant_count, admitted_count, competition_rate,
                        best_score, average_score, cutoff_score,
                        score_basis, score_direction,
                        historical_score_rule_id, historical_score_rule_version,
                        historical_score_rule_year, source_reference,
                        validation_status, validation_issues, publication_status
                    ) VALUES (
                        :id, :dataset_id, :source_row_number, '합성 결과',
                        2025, 2026, '합성지역',
                        :institution_code, :institution_name,
                        'MAIN', '본교', :program_code, :program_name,
                        'SUSI-1', '수시 1차', :day_night,
                        '합성', :track_code, :track_name,
                        :capacity, :applicant_count, :admitted_count, :competition_rate,
                        3.0000, 4.0000, 5.0000,
                        'RANK_GRADE', 'LOWER_IS_BETTER',
                        NULL, NULL, NULL, 'synthetic-phase16-public-results',
                        'VALID', '{}'::json, 'PUBLISHED'
                    )
                    """
                ),
                legacy_rows,
            )
            before_upgrade = _legacy_result_snapshot(connection, dataset_id=dataset_id)
            assert len(before_upgrade) == LEGACY_RESULT_COUNT

        command.upgrade(config, PHASE17_HEAD)

        with postgres_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version")) == PHASE17_HEAD
            )
            assert _legacy_result_snapshot(connection, dataset_id=dataset_id) == before_upgrade

            day_night_counts: dict[str, int] = {}
            for row in connection.execute(
                text(
                    """
                    SELECT day_night, count(*)
                    FROM admission_result_import_rows
                    WHERE dataset_id = :dataset_id
                    GROUP BY day_night
                    """
                ),
                {"dataset_id": dataset_id},
            ):
                day_night_counts[str(row[0])] = int(row[1])
            assert day_night_counts == {"DAY": 241, "UNKNOWN": 241}
            assert (
                connection.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM programs
                        WHERE id = ANY(:program_ids) AND day_night = 'UNKNOWN'
                        """
                    ),
                    {"program_ids": list(program_ids)},
                )
                == LEGACY_PROGRAM_COUNT
            )
            assert (
                connection.scalar(
                    text(
                        """
                        SELECT count(*)
                        FROM campuses
                        WHERE id = ANY(:campus_ids) AND region IS NULL
                        """
                    ),
                    {"campus_ids": list(campus_ids)},
                )
                == 4
            )

            program_columns = {
                column["name"]: column for column in inspect(connection).get_columns("programs")
            }
            result_columns = {
                column["name"]: column
                for column in inspect(connection).get_columns("admission_result_import_rows")
            }
            consultation_columns = {
                column["name"]: column
                for column in inspect(connection).get_columns("saved_consultations")
            }
            assert program_columns["day_night"]["nullable"] is False
            assert "UNKNOWN" in str(program_columns["day_night"]["default"])
            assert result_columns["day_night"]["nullable"] is False
            assert "UNKNOWN" in str(result_columns["day_night"]["default"])
            assert consultation_columns["student_profile"]["nullable"] is False
            assert "VOCATIONAL_CURRENT" in str(consultation_columns["student_profile"]["default"])
    finally:
        with postgres_engine.begin() as connection:
            _delete_synthetic_legacy_data(
                connection,
                dataset_id=dataset_id,
                institution_ids=institution_ids,
            )
        command.upgrade(config, PHASE17_HEAD)
