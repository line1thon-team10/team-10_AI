
from datetime import date
import re


TYPE_MAP = {
    "multiple_choice": "choice",
    "short_answer": "short",
    "essay": "essay",
    "choice": "choice",
    "short": "short",
    "객관식": "choice",
    "단답형": "short",
    "서술형": "essay",
}

DIFFICULTY_MAP = {
    "easy": "low",
    "medium": "mid",
    "hard": "high",
    "low": "low",
    "mid": "mid",
    "high": "high",
    "하": "low",
    "중": "mid",
    "상": "high",
}

LEGACY_TYPE_MAP = {
    "choice": "객관식",
    "short": "단답형",
    "essay": "서술형",
    "multiple_choice": "객관식",
    "short_answer": "단답형",
    "객관식": "객관식",
    "단답형": "단답형",
    "서술형": "서술형",
    "ox": "OX",
    "OX": "OX",
}

LEGACY_DIFFICULTY_MAP = {
    "low": "하",
    "mid": "중",
    "high": "상",
    "easy": "하",
    "medium": "중",
    "hard": "상",
    "하": "하",
    "중": "중",
    "상": "상",
}

CHOICE_IDS = ("A", "B", "C", "D")


def _as_dict(value):
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    raise TypeError("데이터는 객체여야 합니다.")


def _unit_id(value):
    value = str(value).strip()
    match = re.fullmatch(r"unit_0*(\d+)", value)
    if match:
        return f"AI{int(match.group(1))}"
    return value


def _concept_id(value, unit_id):
    value = str(value).strip()
    match = re.fullmatch(r"unit_0*(\d+)-(\d+)", value)
    if match:
        return f"AI{int(match.group(1))}-{match.group(2)}"
    if re.fullmatch(r"\d+", value):
        return f"{unit_id}-{value}"
    return value


def _question_id(value, unit_id):
    value = str(value).strip()
    match = re.fullmatch(r"(.+)-Q(\d+)", value)
    if match:
        return f"{_unit_id(match.group(1))}-Q{int(match.group(2)):02d}"
    match = re.fullmatch(r"(.+)-(\d+)", value)
    if match:
        return f"{_unit_id(match.group(1))}-Q{int(match.group(2)):02d}"
    if value.isdigit():
        return f"{unit_id}-Q{int(value):02d}"
    raise ValueError(f"문제 ID를 변환할 수 없습니다: {value}")


def _choices(question, question_type):
    if question_type != "choice":
        return [], str(question["answer"])

    raw = question.get("choices", question.get("options", []))

    if not isinstance(raw, list) or len(raw) != 4:
        raise ValueError("객관식 선택지는 4개여야 합니다.")

    if all(isinstance(item, dict) for item in raw):
        choices = [
            {"id": item["id"], "text": item["text"]}
            for item in raw
        ]
    elif all(isinstance(item, str) for item in raw):
        choices = [
            {"id": choice_id, "text": text}
            for choice_id, text in zip(CHOICE_IDS, raw)
        ]
    else:
        raise ValueError("객관식 선택지 형식이 올바르지 않습니다.")

    ids = [item["id"] for item in choices]
    texts = [item["text"] for item in choices]

    if ids != list(CHOICE_IDS):
        raise ValueError("보기 ID는 A, B, C, D여야 합니다.")

    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ValueError("빈 선택지가 존재합니다.")

    if len(set(texts)) != 4:
        raise ValueError("객관식 선택지가 중복되었습니다.")

    answer = str(question["answer"])

    if answer in ids:
        return choices, answer

    matches = [
        item["id"]
        for item in choices
        if item["text"] == answer
    ]

    if len(matches) != 1:
        raise ValueError("정답이 선택지와 일치하지 않습니다.")

    return choices, matches[0]


def _sources(question):
    if "sources" in question:
        sources = question["sources"]

        if not isinstance(sources, list):
            raise ValueError("sources는 배열이어야 합니다.")

        result = []

        for source in sources:
            start = source.get("start_page")
            end = source.get("end_page")
            quote = source.get("quote", "")

            if (
                type(start) is not int
                or type(end) is not int
                or start < 1
                or end < start
                or not isinstance(quote, str)
                or not quote.strip()
            ):
                raise ValueError("근거 자료 형식이 올바르지 않습니다.")

            result.append({
                "start_page": start,
                "end_page": end,
                "quote": quote
            })

        return result

    page = question.get(
        "page",
        question.get("source_page")
    )

    quote = question.get(
        "source_text",
        question.get("quote", "")
    )

    if type(page) is not int or page < 1:
        raise ValueError("근거 페이지가 올바르지 않습니다.")

    if not isinstance(quote, str) or not quote.strip():
        raise ValueError("근거 문장이 없습니다.")

    return [{
        "start_page": page,
        "end_page": page,
        "quote": quote
    }]


def convert_question(question, source="daily"):
    question = _as_dict(question)

    question_type = TYPE_MAP.get(question.get("type"))
    difficulty = DIFFICULTY_MAP.get(question.get("difficulty"))

    if question_type is None:
        raise ValueError("지원하지 않는 문제 유형입니다.")

    if difficulty is None:
        raise ValueError("지원하지 않는 난이도입니다.")

    unit = question.get("unit_id", question.get("unit"))

    if not unit:
        raise ValueError("unit_id가 필요합니다.")

    unit_id = _unit_id(unit)

    concept = question.get(
        "concept_id",
        question.get("concept")
    )

    if not concept:
        raise ValueError("concept_id가 필요합니다.")

    concept_id = _concept_id(concept, unit_id)

    if not concept_id.startswith(unit_id + "-"):
        raise ValueError("개념 ID와 단원 ID가 일치하지 않습니다.")

    raw_id = question.get(
        "question_id",
        question.get("id")
    )

    if raw_id is None:
        raise ValueError("문제 ID가 없습니다.")

    question_id = _question_id(raw_id, unit_id)

    prompt = question.get(
        "prompt",
        question.get("question")
    )

    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("문제 본문이 없습니다.")

    if not isinstance(question.get("answer"), str):
        raise ValueError("정답이 올바르지 않습니다.")

    explanation = question.get("explanation")

    if not isinstance(explanation, str) or not explanation.strip():
        raise ValueError("해설이 없습니다.")

    choices, answer = _choices(question, question_type)

    return {
        "question_id": question_id,
        "unit_id": unit_id,
        "concept_id": concept_id,
        "type": question_type,
        "difficulty": difficulty,
        "prompt": prompt,
        "choices": choices,
        "answer": answer,
        "explanation": explanation,
        "sources": _sources(question)
    }


def get_public_question(question):
    converted = (
        convert_question(question)
        if "question_id" not in question
        or "prompt" not in question
        else dict(question)
    )

    return {
        key: value
        for key, value in converted.items()
        if key not in {"answer", "explanation", "sources"}
    }


def convert_question_bank(bank, source="daily"):
    if bank.get("status") != "success":
        raise ValueError("정상적인 문제은행이 아닙니다.")

    questions = []
    seen_ids = set()
    units = []

    for unit in bank.get("units", []):
        unit_id = _unit_id(unit.get("unit_id", ""))

        if unit.get("status") != "success":
            units.append({
                "unit_id": unit_id,
                "status": unit.get("status"),
                "questions": []
            })
            continue

        converted_questions = []

        for question in unit.get("questions", []):
            converted = convert_question(question, source)
            question_id = converted["question_id"]

            if question_id in seen_ids:
                raise ValueError(f"중복 문제 ID: {question_id}")

            seen_ids.add(question_id)
            converted_questions.append(converted)
            questions.append(converted)

        units.append({
            "unit_id": unit_id,
            "status": "success",
            "questions": converted_questions
        })

    return {
        "status": "success",
        "subject": bank.get("subject"),
        "document_title": bank.get("document_title"),
        "total_questions": len(questions),
        "units": units,
        "questions": questions
    }


def convert_analysis(analysis):
    analysis = _as_dict(analysis)
    subject = analysis["subject"]
    units = []
    concepts = []

    for unit in analysis["units"]:
        unit = _as_dict(unit)

        unit_id = _unit_id(
            unit.get("id", unit.get("unit_id"))
        )

        difficulty = LEGACY_DIFFICULTY_MAP.get(
            unit.get("difficulty", "중")
        )

        if difficulty is None:
            raise ValueError("단원 난이도가 올바르지 않습니다.")

        start = unit.get("page_start", unit.get("start_page"))
        end = unit.get("page_end", unit.get("end_page"))

        units.append({
            "id": unit_id,
            "subject": subject,
            "name": unit.get("name", unit.get("title")),
            "page_start": start,
            "page_end": end,
            "difficulty": difficulty
        })

        for concept in unit.get("concepts", []):
            concept = _as_dict(concept)

            concepts.append({
                "id": _concept_id(concept["id"], unit_id),
                "unit": unit_id,
                "name": concept["name"],
                "page_start": concept["page_start"],
                "page_end": concept["page_end"]
            })

    return {
        "units": units,
        "concepts": concepts
    }


def convert_grading_response(grading, question_lookup=None):
    if grading.get("status") != "success":
        raise ValueError("정상적인 채점 결과가 아닙니다.")

    question_lookup = question_lookup or {}
    results = []

    for item in grading.get("results", []):
        raw_id = item["question_id"]
        original = question_lookup.get(raw_id, {})

        unit = item.get(
            "unit_id",
            original.get("unit_id", original.get("unit"))
        )

        if unit:
            question_id = _question_id(raw_id, _unit_id(unit))
        else:
            question_id = str(raw_id)

        question_type = TYPE_MAP.get(
            item.get("type", original.get("type"))
        )

        result = {
            "question_id": question_id,
            "is_correct": bool(item["is_correct"]),
            "correct_answer": item["correct_answer"],
            "explanation": item.get("explanation", ""),
            "got_points": item.get(
                "got_points",
                item.get("strengths", [])
            ),
            "missing_points": item.get("missing_points", [])
        }

        if question_type == "essay":
            result["essay_score"] = item.get(
                "essay_score",
                item.get("score_100")
            )
            result["feedback"] = item.get("feedback", "")

            if (
                type(result["essay_score"]) is not int
                or not 0 <= result["essay_score"] <= 100
            ):
                raise ValueError("서술형 점수가 올바르지 않습니다.")

            result["is_correct"] = result["essay_score"] >= 85

        results.append(result)

    return {
        "total_questions": len(results),
        "results": results
    }


def convert_grading_to_attempts(
    grading,
    confidences=None,
    attempt_date=None
):
    if grading.get("status") != "success":
        raise ValueError("정상적인 채점 결과가 아닙니다.")

    if attempt_date is None:
        attempt_date = (
            grading.get("date")
            or date.today().isoformat()
        )

    confidences = confidences or {}

    if not isinstance(confidences, dict):
        raise ValueError("confidences는 객체여야 합니다.")

    attempts = []

    for result in grading.get("results", []):
        question_id = result["question_id"]

        confidence = confidences.get(
            question_id,
            result.get("confidence")
        )

        if confidence not in {"확실", "애매"}:
            raise ValueError(
                f"{question_id}의 확신도가 올바르지 않습니다."
            )

        if type(result.get("is_correct")) is not bool:
            raise ValueError("정오답 값이 올바르지 않습니다.")

        attempt = {
            "date": attempt_date,
            "question": question_id,
            "confidence": confidence,
            "correct": result["is_correct"]
        }

        question_type = LEGACY_TYPE_MAP.get(
            result.get("type")
        )

        if question_type == "서술형":
            score = result.get(
                "essay_score",
                result.get("score_100")
            )

            if (
                not isinstance(score, (int, float))
                or isinstance(score, bool)
                or not 0 <= score <= 100
            ):
                raise ValueError("서술형 점수가 올바르지 않습니다.")

            attempt["essay_score"] = score

        attempts.append(attempt)

    return attempts
