from __future__ import annotations

import re
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, delete, func, select, update
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app import create_app
from app.models import (
    AdmissionResultImportDataset,
    AdmissionResultImportRow,
    AdmissionRound,
    AdmissionTrack,
    Campus,
    Institution,
    Program,
)
from app.services.admission_result_file_imports import parse_admission_result_upload
from app.services.admission_result_imports import (
    DatabaseCatalogResolver,
    list_published_imported_results_for_program,
    list_published_result_years,
    load_published_imported_result,
    persist_admission_result_preview,
    publish_admission_result_dataset,
)
from app.services.phase14_public_seed import load_phase14_public_seed
from app.services.temporary_uploads import TemporaryUploadStore


def _csv(institution_name: str, average: str) -> bytes:
    return (
        "대학명,캠퍼스명,모집시기,전공명,전형구분1,전형구분2,모집인원,"
        "합격자평균,합격자최저\n"
        f"{institution_name},본교,수시1차,합성학과,특별전형,일반고,0,{average},5.4\n"
    ).encode()


def test_versioned_import_publishes_exact_target_year_and_supersedes(
    postgres_engine: Engine,
) -> None:
    prefix = uuid4().hex[:10].upper()
    institution_code = f"P14-{prefix}"
    institution_name = f"합성전문대학-{prefix}"
    source_code = f"P14-SOURCE-{prefix}"
    with Session(postgres_engine) as session:
        institution = Institution(
            code=institution_code,
            name=institution_name,
            institution_type="JUNIOR_COLLEGE",
        )
        session.add(institution)
        session.flush()
        campus = Campus(institution_id=institution.id, code="MAIN", name="본교")
        session.add(campus)
        session.flush()
        program = Program(campus_id=campus.id, code="SYNTHETIC-P", name="합성학과")
        session.add(program)
        admission_round = AdmissionRound(
            institution_id=institution.id,
            academic_year=2028,
            code="SUSI-1",
            name="수시1차",
        )
        session.add_all([program, admission_round])
        session.flush()
        track = AdmissionTrack(
            admission_round_id=admission_round.id,
            program_id=program.id,
            code="SPECIAL-GENERAL-HS",
            name="특별전형 / 일반고",
        )
        session.add(track)
        session.commit()
        first = parse_admission_result_upload(
            _csv(institution_name, "4.3"),
            filename="result.csv",
            result_academic_year=2027,
            target_academic_year=2028,
            catalog=DatabaseCatalogResolver(session),
        )
        assert (first.valid_row_count, first.review_row_count, first.error_row_count) == (1, 0, 0)
        first_dataset = persist_admission_result_preview(
            session,
            first,
            source_code=source_code,
            source_dataset_version="V1",
            source_reference="synthetic-public-reference",
            collected_at=datetime.now(UTC),
        )
        session.flush()
        publish_admission_result_dataset(
            session,
            first_dataset.id,
            published_by="synthetic-admin",
            published_at=datetime.now(UTC),
            allow_partial=False,
        )
        session.commit()

        loaded = load_published_imported_result(
            session,
            target_academic_year=2028,
            result_academic_year=2027,
            institution_code=institution_code,
            campus_code="MAIN",
            program_code="SYNTHETIC-P",
            admission_round_code="SUSI-1",
            admission_track_code="SPECIAL-GENERAL-HS",
        )
        assert loaded is not None
        assert loaded.publication_version == "V1"
        assert loaded.capacity == 0
        assert str(loaded.average_score) == "4.3000"
        assert list_published_result_years(session, 2028) == (2027,)

        second = parse_admission_result_upload(
            _csv(institution_name, "4.1"),
            filename="result.csv",
            result_academic_year=2027,
            target_academic_year=2028,
            catalog=DatabaseCatalogResolver(session),
        )
        second_dataset = persist_admission_result_preview(
            session,
            second,
            source_code=source_code,
            source_dataset_version="V2",
            source_reference="synthetic-public-reference-v2",
            collected_at=datetime.now(UTC),
        )
        session.flush()
        publish_admission_result_dataset(
            session,
            second_dataset.id,
            published_by="synthetic-admin",
            published_at=datetime.now(UTC),
            allow_partial=False,
        )
        session.commit()

        session.refresh(first_dataset)
        session.refresh(second_dataset)
        assert first_dataset.lifecycle_status == "SUPERSEDED"
        assert second_dataset.supersedes_id == first_dataset.id
        loaded_v2 = load_published_imported_result(
            session,
            target_academic_year=2028,
            result_academic_year=2027,
            institution_code=institution_code,
            campus_code="MAIN",
            program_code="SYNTHETIC-P",
            admission_round_code="SUSI-1",
            admission_track_code="SPECIAL-GENERAL-HS",
        )
        assert loaded_v2 is not None
        assert loaded_v2.publication_version == "V2"
        assert str(loaded_v2.average_score) == "4.1000"

        dataset_ids = tuple(
            session.scalars(
                select(AdmissionResultImportDataset.id).where(
                    AdmissionResultImportDataset.source_code == source_code
                )
            )
        )
        session.execute(
            delete(AdmissionResultImportRow).where(
                AdmissionResultImportRow.dataset_id.in_(dataset_ids)
            )
        )
        session.execute(
            update(AdmissionResultImportDataset)
            .where(AdmissionResultImportDataset.id.in_(dataset_ids))
            .values(supersedes_id=None)
        )
        session.execute(
            delete(AdmissionResultImportDataset).where(
                AdmissionResultImportDataset.id.in_(dataset_ids)
            )
        )
        session.execute(delete(Institution).where(Institution.code == institution_code))
        session.commit()


def test_admin_upload_route_previews_unknown_mapping_without_storing_original(
    postgres_engine: Engine, tmp_path: Path
) -> None:
    source_code = f"P14-ROUTE-{uuid4().hex.upper()}"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "ADMIN_USERNAME": "synthetic-admin",
            "ADMIN_PASSWORD_HASH": generate_password_hash("synthetic-password"),
            "ALLOW_LEGACY_ADMIN_LOGIN": True,
            "TEMP_UPLOAD_ROOT": str(tmp_path / "uploads"),
        }
    )
    client = app.test_client()
    assert client.get("/admin/admission-results").status_code == 302
    login_page = client.get("/admin/login")
    csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', login_page.get_data(as_text=True))
    assert csrf_match is not None
    login = client.post(
        "/admin/login",
        data={
            "csrf_token": csrf_match.group(1),
            "username": "synthetic-admin",
            "password": "synthetic-password",
        },
    )
    assert login.status_code == 302
    page = client.get("/admin/admission-results")
    page_csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True))
    assert page_csrf is not None
    csv_rows = [
        "대학명,캠퍼스명,모집시기,전공명,전형구분1,전형구분2,모집인원,합격자평균,관리자확정평균,합격자최저"
    ] + [
        f"미매핑전문대학,본교,수시1차,미매핑학과-{index},특별전형,일반고,0,8.8,4.3,5.4"
        for index in range(101)
    ]
    upload = client.post(
        "/admin/admission-results",
        data={
            "csrf_token": page_csrf.group(1),
            "source_code": source_code,
            "source_dataset_version": "2027-V1",
            "result_academic_year": "2027",
            "target_academic_year": "",
            "source_reference": "synthetic-public-reference",
            "result_file": (BytesIO("\n".join(csv_rows).encode()), "results.csv"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert upload.status_code == 200
    mapping_body = upload.get_data(as_text=True)
    assert "자동 열 mapping 확인" in mapping_body
    assert "average_score" in mapping_body
    assert "합격자평균" in mapping_body
    temporary_session_match = re.search(
        r'name="temporary_session_id" value="([0-9a-f]{32})"', mapping_body
    )
    mapping_csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', mapping_body)
    assert temporary_session_match is not None
    assert mapping_csrf_match is not None
    temporary_session_id = temporary_session_match.group(1)
    confirmed = client.post(
        "/admin/admission-results/preview",
        data={
            "csrf_token": mapping_csrf_match.group(1),
            "temporary_session_id": temporary_session_id,
            "mapping__average_score": "관리자확정평균",
        },
        follow_redirects=True,
    )
    body = confirmed.get_data(as_text=True)
    assert confirmed.status_code == 200
    assert "2027" in body and "2028" in body
    assert "CATALOG_MAPPING_REQUIRED" in body
    assert "101 / 0 / 101 / 0 / 0" in body
    assert "미매핑전문대학" in body
    assert "1 / 2 페이지" in body
    assert "average_score" in body and "관리자확정평균" in body
    next_page = client.get(f"{confirmed.request.path}?status=REVIEW&page=2")
    assert next_page.status_code == 200
    assert "2 / 2 페이지" in next_page.get_data(as_text=True)
    assert "CSV / 102" in next_page.get_data(as_text=True)

    with Session(postgres_engine) as session:
        dataset = session.scalar(
            select(AdmissionResultImportDataset).where(
                AdmissionResultImportDataset.source_code == source_code
            )
        )
        assert dataset is not None
        assert dataset.lifecycle_status == "STAGED"
        assert dataset.column_mapping_overrides == {"average_score": "관리자확정평균"}
        first_row = session.scalar(
            select(AdmissionResultImportRow).where(
                AdmissionResultImportRow.dataset_id == dataset.id,
                AdmissionResultImportRow.source_row_number == 2,
            )
        )
        assert first_row is not None
        assert str(first_row.average_score) == "4.3000"
        session.execute(
            delete(AdmissionResultImportRow).where(
                AdmissionResultImportRow.dataset_id == dataset.id
            )
        )
        session.delete(dataset)
        session.commit()
    assert (
        not TemporaryUploadStore(tmp_path / "uploads").session_path(temporary_session_id).exists()
    )


def test_phase14_public_seed_loads_482_xlsx_rows_for_four_real_institutions(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine) as session:
        dataset_id = load_phase14_public_seed(
            session,
            repository_root=Path("."),
            actor_ref="synthetic-seed-verifier",
            occurred_at=datetime.now(UTC),
        )
        session.flush()
        dataset = session.get(AdmissionResultImportDataset, dataset_id)
        assert dataset is not None
        assert dataset.lifecycle_status == "PUBLISHED"
        assert (
            dataset.result_academic_year,
            dataset.target_academic_year,
            dataset.original_row_count,
            dataset.valid_row_count,
            dataset.review_row_count,
            dataset.error_row_count,
            dataset.published_row_count,
        ) == (2025, 2027, 482, 482, 0, 0, 482)
        assert (
            session.scalar(
                select(func.count())
                .select_from(AdmissionResultImportRow)
                .where(
                    AdmissionResultImportRow.dataset_id == dataset_id,
                    AdmissionResultImportRow.publication_status == "PUBLISHED",
                )
            )
            == 482
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AdmissionResultImportRow)
                .where(AdmissionResultImportRow.dataset_id == dataset_id)
            )
            == 482
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AdmissionResultImportRow)
                .where(
                    AdmissionResultImportRow.dataset_id == dataset_id,
                    AdmissionResultImportRow.competition_rate.is_not(None),
                )
            )
            == 482
        )
        institution_codes = set(
            session.scalars(
                select(Institution.code).where(
                    Institution.code.in_(
                        {
                            "DONGYANG-MIRAE",
                            "MYONGJI-COLLEGE",
                            "INHA-TECHNICAL-COLLEGE",
                            "YEONSUNG",
                        }
                    )
                )
            )
        )
        assert institution_codes == {
            "DONGYANG-MIRAE",
            "MYONGJI-COLLEGE",
            "INHA-TECHNICAL-COLLEGE",
            "YEONSUNG",
        }
        example = session.scalar(
            select(AdmissionResultImportRow).where(
                AdmissionResultImportRow.dataset_id == dataset_id,
                AdmissionResultImportRow.institution_code == "DONGYANG-MIRAE",
                AdmissionResultImportRow.program_name == "호텔관광학과",
                AdmissionResultImportRow.admission_round_code == "SUSI-1",
                AdmissionResultImportRow.admission_track_code == "SPECIAL-GENERAL-HS",
                AdmissionResultImportRow.publication_status == "PUBLISHED",
            )
        )
        assert example is not None
        assert (
            str(example.average_score),
            str(example.cutoff_score),
            str(example.competition_rate),
        ) == ("5.7000", "6.3000", "8.4000")
        loaded = load_published_imported_result(
            session,
            target_academic_year=2027,
            result_academic_year=2025,
            institution_code=str(example.institution_code),
            campus_code=str(example.campus_code),
            program_code=str(example.program_code),
            admission_round_code=str(example.admission_round_code),
            admission_track_code=str(example.admission_track_code),
        )
        assert loaded is not None
        assert loaded.source_reference.startswith(
            "sha256:bde8fe5d513ce2737c08815b0d7e1df366dc8844e6ff7f243eccb63c3bd40606#"
        )
        assert (
            "supplemental.competition_rate="
            "sha256:c35d548abb244168dcffd1a582a38368a58f611f2998604a9b1b70f7e5ae6658#"
            in loaded.source_reference
        )
        program_results = list_published_imported_results_for_program(
            session,
            target_academic_year=2027,
            result_academic_year=2025,
            institution_code=str(example.institution_code),
            campus_code=str(example.campus_code),
            program_code=str(example.program_code),
        )
        assert any(
            result.admission_track_code == "SPECIAL-GENERAL-HS" for result in program_results
        )
        assert list_published_result_years(session, 2027) == (2025,)
        session.rollback()
