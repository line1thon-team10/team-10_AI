
from datetime import date

TYPE_MAP = {
    "multiple_choice": "객관식",
    "short_answer": "단답형",
    "essay": "서술형",
    "ox": "OX",
    "객관식": "객관식",
    "단답형": "단답형",
    "서술형": "서술형",
    "OX": "OX",
}

DIFFICULTY_MAP = {
    "easy": "하",
    "medium": "중",
    "hard": "상",
    "하": "하",
    "중": "중",
    "상": "상",
}


def convert_question(question, source="daily"):
    question_type = TYPE_MAP.get(
        question.get("type")
    )
    difficulty = DIFFICULTY_MAP.get(
        question.get("difficulty")
    )

    if question_type is None:
        raise ValueError(
            "지원하지 않는 문제 유형입니다."
        )

    if difficulty is None:
        raise ValueError(
            "지원하지 않는 난이도입니다."
        )

    source = question.get("source", source)

    if source not in {"daily", "pick"}:
        raise ValueError(
            "source는 daily 또는 pick이어야 합니다."
        )

    required = [
        "id",
        "concept",
        "unit",
        "question",
        "answer",
        "explanation"
    ]

    for key in required:
        if key not in question:
            raise ValueError(
                f"필수 필드 누락: {key}"
            )

    page = question.get(
        "page",
        question.get("source_page")
    )

    if page is None:
        raise ValueError(
            "문제의 근거 페이지가 없습니다."
        )

    choices = question.get("choices")

    if question_type == "객관식":
        if (
            not isinstance(choices, list)
            or len(choices) != 4
        ):
            raise ValueError(
                "객관식 선택지는 4개여야 합니다."
            )

        if question["answer"] not in choices:
            raise ValueError(
                "정답이 선택지에 없습니다."
            )

    elif question_type == "OX":
        if choices is None:
            choices = ["O", "X"]

        if choices != ["O", "X"]:
            raise ValueError(
                "OX 선택지는 ['O', 'X']여야 합니다."
            )

        if question["answer"] not in choices:
            raise ValueError(
                "OX 정답이 올바르지 않습니다."
            )

    else:
        choices = None

    return {
        "id": question["id"],
        "concept": question["concept"],
        "unit": question["unit"],
        "page": page,
        "type": question_type,
        "difficulty": difficulty,
        "question": question["question"],
        "choices": choices,
        "answer": question["answer"],
        "explanation": question["explanation"],
        "source": source
    }


def convert_question_bank(bank, source="daily"):
    if bank.get("status") != "success":
        raise ValueError(
            "정상적인 문제은행이 아닙니다."
        )

    questions = []
    seen_ids = set()

    for unit in bank.get("units", []):
        if unit.get("status") != "success":
            continue

        for question in unit.get("questions", []):
            converted = convert_question(
                question, source
            )

            if converted["id"] in seen_ids:
                raise ValueError(
                    "중복 문제 ID가 있습니다."
                )

            seen_ids.add(converted["id"])
            questions.append(converted)

    return {
        "subject": bank.get("subject"),
        "document_title": bank.get(
            "document_title"
        ),
        "questions": questions,
        "total_questions": len(questions)
    }


def convert_analysis(analysis):
    subject = analysis["subject"]
    units = []
    concepts = []

    for unit in analysis["units"]:
        difficulty = DIFFICULTY_MAP.get(
            unit.get("difficulty")
        )

        if difficulty is None:
            raise ValueError(
                f"단원 난이도가 올바르지 않습니다: {unit['id']}"
            )

        units.append({
            "id": unit["id"],
            "subject": subject,
            "name": unit["name"],
            "page_start": unit["page_start"],
            "page_end": unit["page_end"],
            "difficulty": difficulty
        })

        for concept in unit.get("concepts", []):
            concepts.append({
                "id": concept["id"],
                "unit": unit["id"],
                "name": concept["name"],
                "page_start": concept["page_start"],
                "page_end": concept["page_end"]
            })

    return {
        "units": units,
        "concepts": concepts
    }


def convert_grading_to_attempts(
    grading,
    confidences=None,
    attempt_date=None
):
    if grading.get("status") != "success":
        raise ValueError(
            "정상적인 채점 결과가 아닙니다."
        )

    if attempt_date is None:
        attempt_date = (
            grading.get("date")
            or date.today().isoformat()
        )

    if confidences is None:
        confidences = {}

    if not isinstance(confidences, dict):
        raise ValueError(
            "confidences는 문제 ID별 확신도 객체여야 합니다."
        )

    attempts = []

    for result in grading.get("results", []):
        question_id = result["question_id"]

        confidence = confidences.get(
            question_id,
            result.get("confidence")
        )

        if confidence not in {"확실", "애매"}:
            raise ValueError(
                f"{question_id}의 확신도가 없거나 올바르지 않습니다."
            )

        if type(result.get("is_correct")) is not bool:
            raise ValueError(
                f"{question_id}의 정오답 값이 올바르지 않습니다."
            )

        attempt = {
            "date": attempt_date,
            "question": question_id,
            "confidence": confidence,
            "correct": result["is_correct"]
        }

        question_type = TYPE_MAP.get(
            result.get("type")
        )

        if question_type == "서술형":
            score = result.get("score_100")

            if (
                not isinstance(score, (int, float))
                or isinstance(score, bool)
                or not 0 <= score <= 100
            ):
                raise ValueError(
                    f"{question_id}의 서술형 점수가 올바르지 않습니다."
                )

            attempt["essay_score"] = score

        attempts.append(attempt)

    return attempts
