from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DemoScoreRow:
    academic_year: int
    grade: int
    semester: int
    subject_group: str
    subject_name: str
    credits: str
    rank_grade: str
    raw_score: str = ""
    course_mean: str = ""
    standard_deviation: str = ""


# 사용자가 제공한 합성 성적표. 3학년 1학기는 원점수·과목평균·표준편차로
# Z점수 미리보기도 확인할 수 있고, 표에 기재된 석차등급을 계산 입력에 쓴다.
DEMO_SCORE_ROWS = (
    DemoScoreRow(2025, 1, 1, "국어", "국어", "4", "4"),
    DemoScoreRow(2025, 1, 1, "수학", "수학", "4", "6"),
    DemoScoreRow(2025, 1, 1, "영어", "영어", "4", "5"),
    DemoScoreRow(2025, 1, 1, "사회", "한국사", "3", "6"),
    DemoScoreRow(2025, 1, 1, "사회", "통합사회", "3", "5"),
    DemoScoreRow(2025, 1, 1, "과학", "통합과학", "3", "3"),
    DemoScoreRow(2025, 1, 1, "정보", "정보", "2", "3"),
    DemoScoreRow(2025, 1, 2, "국어", "국어", "4", "5"),
    DemoScoreRow(2025, 1, 2, "수학", "수학", "4", "6"),
    DemoScoreRow(2025, 1, 2, "영어", "영어", "4", "6"),
    DemoScoreRow(2025, 1, 2, "사회", "한국사", "3", "6"),
    DemoScoreRow(2025, 1, 2, "사회", "통합사회", "3", "7"),
    DemoScoreRow(2025, 1, 2, "과학", "통합과학", "4", "5"),
    DemoScoreRow(2025, 1, 2, "정보", "정보", "3", "5"),
    DemoScoreRow(2026, 2, 1, "국어", "문학", "4", "6"),
    DemoScoreRow(2026, 2, 1, "수학", "수학Ⅰ", "4", "6"),
    DemoScoreRow(2026, 2, 1, "영어", "영어Ⅰ", "4", "6"),
    DemoScoreRow(2026, 2, 1, "사회", "경제", "2", "5"),
    DemoScoreRow(2026, 2, 1, "과학", "화학Ⅰ", "2", "8"),
    DemoScoreRow(2026, 2, 1, "과학", "생명과학Ⅰ", "2", "7"),
    DemoScoreRow(2026, 2, 1, "제2외국어", "일본어Ⅰ", "2", "4"),
    DemoScoreRow(2026, 2, 2, "국어", "독서", "4", "6"),
    DemoScoreRow(2026, 2, 2, "수학", "수학Ⅱ", "4", "6"),
    DemoScoreRow(2026, 2, 2, "영어", "영어Ⅱ", "4", "6"),
    DemoScoreRow(2026, 2, 2, "사회", "경제", "2", "4"),
    DemoScoreRow(2026, 2, 2, "과학", "화학Ⅰ", "2", "7"),
    DemoScoreRow(2026, 2, 2, "과학", "생명과학Ⅰ", "2", "6"),
    DemoScoreRow(2026, 2, 2, "제2외국어", "일본어Ⅰ", "2", "5"),
    DemoScoreRow(
        2027,
        3,
        1,
        "전문교과",
        "빅데이터 프로그래밍",
        "6",
        "3",
        "91.35",
        "63.50",
        "27.50",
    ),
    DemoScoreRow(
        2027,
        3,
        1,
        "전문교과",
        "웹 프로그래밍 실무",
        "6",
        "2",
        "93.50",
        "56.90",
        "23.40",
    ),
    DemoScoreRow(
        2027,
        3,
        1,
        "전문교과",
        "응용 프로그래밍 개발",
        "14",
        "3",
        "93.00",
        "76.10",
        "21.80",
    ),
)


__all__ = ["DEMO_SCORE_ROWS", "DemoScoreRow"]
