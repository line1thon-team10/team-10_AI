
import json
import re

from services.groq_client import GroqService
from services.essay_grader import grade_essay

TYPE_MAP = {
    "multiple_choice": "multiple_choice",
    "short_answer": "short_answer",
    "essay": "essay",
    "ox": "ox",
    "객관식": "multiple_choice",
    "단답형": "short_answer",
    "서술형": "essay",
    "OX": "ox",
}

POINTS = {
    "multiple_choice": 5,
    "ox": 5,
    "short_answer": 10,
    "essay": 25,
}

SHORT_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "feedback": {"type": "string"},
        "missing_points": {
            "type": "array",
            "items": {"type": "string"}
        }
    },
    "required": ["score", "feedback", "missing_points"],
    "additionalProperties": False
}


def normalize_answer(answer):
    return re.sub(r"[.,!?。\s]", "", str(answer).strip().lower())


def get_question_type(question):
    question_type = TYPE_MAP.get(question.get("type"))
    if question_type is None:
        raise ValueError(
            f"지원하지 않는 문제 유형: {question.get('type')}"
        )
    return question_type


def validate_submission(quiz, submission):
    if quiz.get("status") != "success":
        raise ValueError("정상적으로 생성된 퀴즈가 아닙니다.")

    questions = quiz.get("questions", [])
    answers = submission.get("answers")

    if not isinstance(answers, list) or len(answers) != len(questions):
        raise ValueError("모든 문제의 답안을 배열로 제출해야 합니다.")

    ids = [q["id"] for q in questions]
    submitted = []

    for item in answers:
        if (
            not isinstance(item, dict)
            or "question_id" not in item
            or not isinstance(item.get("answer"), str)
        ):
            raise ValueError(
                "답안에는 question_id와 answer 문자열이 필요합니다."
            )

        submitted.append(item["question_id"])

        if "confidence" in item:
            if item["confidence"] not in {"확실", "애매"}:
                raise ValueError(
                    "확신도는 확실 또는 애매여야 합니다."
                )

    if (
        len(set(ids)) != len(ids)
        or len(set(submitted)) != len(submitted)
        or set(ids) != set(submitted)
    ):
        raise ValueError(
            "제출된 문제 ID가 퀴즈와 일치하지 않습니다."
        )

    if (
        submission.get("date") is not None
        and submission["date"] != quiz.get("date")
    ):
        raise ValueError("학습 날짜가 일치하지 않습니다.")

    for question in questions:
        get_question_type(question)


def _base(question, user_answer, confidence=None):
    result = {
        "question_id": question["id"],
        "type": question["type"],
        "difficulty": question.get("difficulty", "easy"),
        "question": question["question"],
        "user_answer": user_answer,
        "correct_answer": question["answer"],
        "explanation": question.get("explanation", ""),
        "source_page": question.get(
            "source_page", question.get("page")
        ),
        "source_text": question.get("source_text", "")
    }

    if confidence is not None:
        result["confidence"] = confidence

    return result


def grade_multiple_choice(
    question,
    user_answer,
    confidence=None
):
    correct = (
        normalize_answer(user_answer)
        == normalize_answer(question["answer"])
    )

    max_score = POINTS[get_question_type(question)]

    return {
        **_base(question, user_answer, confidence),
        "score": max_score if correct else 0,
        "max_score": max_score,
        "score_100": 100 if correct else 0,
        "is_correct": correct,
        "feedback": (
            "정답입니다."
            if correct
            else "정답과 일치하지 않습니다."
        ),
        "strengths": [],
        "missing_points": []
    }


def _grade_short(question, answer, service):
    if not answer.strip():
        return {
            "score": 0,
            "feedback": "답안을 입력하지 않았습니다.",
            "missing_points": ["답안 미제출"]
        }

    result = service.generate(
        messages=[
            {
                "role": "system",
                "content": (
                    "학습자료 기반 단답형 채점자다. "
                    "0~100 정수 점수와 한국어 피드백, "
                    "빠진 점을 반환한다. "
                    "표현이 달라도 의미가 같으면 인정하고 "
                    "제공된 근거만 사용한다."
                )
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question["question"],
                        "answer": question["answer"],
                        "user_answer": answer,
                        "source_text": question.get(
                            "source_text", ""
                        )[:9000],
                        "keywords": question.get(
                            "keywords", []
                        )
                    },
                    ensure_ascii=False
                )
            }
        ],
        schema=SHORT_SCHEMA,
        name="short_answer_grading",
        max_tokens=800
    )

    if (
        type(result.get("score")) is not int
        or not 0 <= result["score"] <= 100
    ):
        raise ValueError(
            "단답형 점수가 올바르지 않습니다."
        )

    if (
        not isinstance(result.get("feedback"), str)
        or not result["feedback"].strip()
    ):
        raise ValueError(
            "단답형 피드백이 없습니다."
        )

    if (
        not isinstance(result.get("missing_points"), list)
        or any(
            not isinstance(x, str)
            for x in result["missing_points"]
        )
    ):
        raise ValueError(
            "단답형 부족한 점 형식이 올바르지 않습니다."
        )

    return result


def grade_subjective_questions(
    questions,
    answer_lookup,
    service,
    confidence_lookup=None
):
    results = []
    confidence_lookup = confidence_lookup or {}

    for question in questions:
        answer = answer_lookup[question["id"]]
        question_type = get_question_type(question)

        if question_type == "essay":
            evaluation = grade_essay(
                question, answer, service
            )
        elif question_type == "short_answer":
            evaluation = _grade_short(
                question, answer, service
            )
        else:
            raise ValueError(
                "주관식 유형이 올바르지 않습니다."
            )

        score_100 = evaluation["score"]
        max_score = POINTS[question_type]
        score = round(
            max_score * score_100 / 100, 2
        )
        is_correct = score_100 >= 85

        results.append({
            **_base(
                question,
                answer,
                confidence_lookup.get(question["id"])
            ),
            "score": score,
            "max_score": max_score,
            "score_100": score_100,
            "is_correct": is_correct,
            "feedback": evaluation["feedback"],
            "strengths": evaluation.get(
                "strengths", []
            ),
            "missing_points": evaluation.get(
                "missing_points", []
            )
        })

    return results


def grade_quiz(quiz, submission, groq_service=None):
    validate_submission(quiz, submission)

    answer_lookup = {
        item["question_id"]: item["answer"]
        for item in submission["answers"]
    }

    confidence_lookup = {
        item["question_id"]: item["confidence"]
        for item in submission["answers"]
        if "confidence" in item
    }

    questions = quiz["questions"]

    objective = [
        q for q in questions
        if get_question_type(q)
        in {"multiple_choice", "ox"}
    ]

    subjective = [
        q for q in questions
        if get_question_type(q)
        in {"short_answer", "essay"}
    ]

    results = [
        grade_multiple_choice(
            q,
            answer_lookup[q["id"]],
            confidence_lookup.get(q["id"])
        )
        for q in objective
    ]

    if subjective:
        service = (
            groq_service
            if groq_service is not None
            else GroqService()
        )

        results.extend(
            grade_subjective_questions(
                subjective,
                answer_lookup,
                service,
                confidence_lookup
            )
        )

    order = {
        q["id"]: i
        for i, q in enumerate(questions)
    }

    results.sort(
        key=lambda item: order[item["question_id"]]
    )

    total_score = round(
        sum(item["score"] for item in results), 2
    )
    max_score = sum(
        item["max_score"] for item in results
    )

    percentage = (
        round(total_score / max_score * 100, 1)
        if max_score else 0
    )

    correct_count = sum(
        bool(item["is_correct"])
        for item in results
    )

    partial_count = sum(
        0 < item["score"] < item["max_score"]
        and not item["is_correct"]
        for item in results
    )

    incorrect_count = (
        len(results) - correct_count - partial_count
    )

    achievement = (
        "green" if percentage >= 80
        else "yellow" if percentage >= 50
        else "red"
    )

    return {
        "status": "success",
        "date": quiz.get("date"),
        "document_title": quiz.get(
            "document_title", ""
        ),
        "total_questions": len(results),
        "total_score": total_score,
        "max_score": max_score,
        "percentage": percentage,
        "correct_count": correct_count,
        "partial_count": partial_count,
        "incorrect_count": incorrect_count,
        "achievement": achievement,
        "results": results
    }
