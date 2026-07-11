from werkzeug.datastructures import MultiDict

from app.services.review_forms import parse_review_submission, preview_values
from app.services.structured_imports import StructuredImportPreview, parse_structured_text


def _preview() -> StructuredImportPreview:
    return parse_structured_text(
        "학년도,학년,학기,과목,원점수\n2026,3,1,합성 과목,91",
        source_format="csv",
    )


def _form() -> MultiDict[str, str]:
    values = preview_values(_preview())[0]
    form = MultiDict((f"rows-0-{field}", value) for field, value in values.items())
    form.add("confirmed_row_indices", "0")
    return form


def test_selected_row_rejects_grade_and_semester_outside_database_contract() -> None:
    form = _form()
    form.setlist("rows-0-grade", ["4"])
    form.setlist("rows-0-semester", ["3"])

    submission = parse_review_submission(form, _preview())

    assert not submission.is_valid
    assert submission.field_errors["rows-0-grade"] == "학년은 1~3만 입력할 수 있습니다."
    assert submission.field_errors["rows-0-semester"] == "학기는 1~2만 입력할 수 있습니다."


def test_unselected_invalid_row_does_not_block_valid_selected_rows() -> None:
    preview = parse_structured_text(
        "학년도,학년,학기,과목,원점수\n2026,3,1,합성 선택 과목,91\n2026,3,1,합성 제외 과목,77",
        source_format="csv",
    )
    values = preview_values(preview)
    form: MultiDict[str, str] = MultiDict()
    for index, row_values in enumerate(values):
        for field, value in row_values.items():
            form.add(f"rows-{index}-{field}", value)
    form.add("confirmed_row_indices", "0")
    form.setlist("rows-1-raw_score", ["확인필요"])

    submission = parse_review_submission(form, preview)

    assert submission.is_valid
    assert submission.field_errors["rows-1-raw_score"] == "숫자를 확인하세요."
