
import re
from collections import Counter


EXPECTED_TYPES = (
    ["multiple_choice"] * 6
    + ["short_answer"] * 2
    + ["essay"] * 2
)

VALID_DIFFICULTIES = {"easy", "medium", "hard"}


def normalize_text(text):
    return re.sub(r"\s+", "", str(text)).strip()


def normalize_quiz_difficulty(quiz):
    return quiz


def validate_quiz(quiz, pdf_pages, allowed_pages):
    questions = quiz.get("questions", [])
    errors = []

    if len(questions) != 10:
        errors.append(
            f"문제 수 오류: {len(questions)}개"
        )

    page_lookup = {
        page["page"]: normalize_text(page["text"])
        for page in pdf_pages
    }

    seen_questions = set()
    seen_ids = set()

    for index, question in enumerate(questions):
        number = index + 1
        question_id = question.get("id")

        if question_id != number:
            errors.append(
                f"{number}번: 문제 ID 오류"
            )

        if question_id in seen_ids:
            errors.append(
                f"{number}번: 문제 ID 중복"
            )

        seen_ids.add(question_id)

        question_type = question.get("type")

        if (
            index < len(EXPECTED_TYPES)
            and question_type != EXPECTED_TYPES[index]
        ):
            errors.append(
                f"{number}번: 문제 유형 오류"
            )

        if question.get("difficulty") not in VALID_DIFFICULTIES:
            errors.append(
                f"{number}번: 난이도 값 오류"
            )

        question_text = normalize_text(
            question.get("question", "")
        )

        if not question_text:
            errors.append(
                f"{number}번: 문제 내용 없음"
            )

        if question_text in seen_questions:
            errors.append(
                f"{number}번: 동일한 문제 중복"
            )

        seen_questions.add(question_text)

        if not str(question.get("answer", "")).strip():
            errors.append(
                f"{number}번: 정답 없음"
            )

        if not str(question.get("explanation", "")).strip():
            errors.append(
                f"{number}번: 해설 없음"
            )

        source_page = question.get("source_page")

        if source_page not in allowed_pages:
            errors.append(
                f"{number}번: 허용되지 않은 근거 페이지"
            )
        else:
            original_text = page_lookup.get(
                source_page, ""
            )

            source_text = normalize_text(
                question.get("source_text", "")
            )

            if not source_text:
                errors.append(
                    f"{number}번: 근거 문장 없음"
                )
            elif source_text not in original_text:
                errors.append(
                    f"{number}번: PDF 원문과 근거 불일치"
                )

        options = question.get("options", [])

        if not isinstance(options, list):
            errors.append(
                f"{number}번: 선택지 형식 오류"
            )
            continue

        if question_type == "multiple_choice":
            if len(options) != 4:
                errors.append(
                    f"{number}번: 선택지 개수 오류"
                )
            elif len(set(options)) != 4:
                errors.append(
                    f"{number}번: 선택지 중복"
                )

            if question.get("answer") not in options:
                errors.append(
                    f"{number}번: 정답이 선택지에 없음"
                )

        elif options:
            errors.append(
                f"{number}번: 주관식 선택지 존재"
            )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "difficulty_distribution": dict(
            Counter(
                question.get("difficulty")
                for question in questions
            )
        )
    }
