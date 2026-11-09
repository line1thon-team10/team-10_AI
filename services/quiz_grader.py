
import json
import re

from services.groq_client import GroqService


POINTS = {
    "multiple_choice": 5,
    "short_answer": 10,
    "essay": 25
}


GRADING_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_id": {
                        "type": "integer"
                    },
                    "score": {
                        "type": "integer"
                    },
                    "feedback": {
                        "type": "string"
                    }
                },
                "required": [
                    "question_id",
                    "score",
                    "feedback"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": ["results"],
    "additionalProperties": False
}


def normalize_answer(answer):
    text = str(answer).strip().lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[.,!?。]", "", text)
    return text


def validate_submission(quiz, submission):
    if quiz.get("status") != "success":
        raise ValueError(
            "정상적으로 생성된 퀴즈가 아닙니다."
        )

    questions = quiz.get("questions", [])
    answers = submission.get("answers")

    if not isinstance(answers, list):
        raise ValueError(
            "answers는 배열이어야 합니다."
        )

    if len(answers) != len(questions):
        raise ValueError(
            "모든 문제의 답안을 제출해야 합니다."
        )

    question_ids = {
        question["id"]
        for question in questions
    }

    submitted_ids = []

    for item in answers:
        if not isinstance(item, dict):
            raise ValueError(
                "답안 형식이 올바르지 않습니다."
            )

        if "question_id" not in item:
            raise ValueError(
                "question_id가 없습니다."
            )

        if "answer" not in item:
            raise ValueError(
                "answer가 없습니다."
            )

        if not isinstance(item["answer"], str):
            raise ValueError(
                "answer는 문자열이어야 합니다."
            )

        submitted_ids.append(
            item["question_id"]
        )

    if len(set(submitted_ids)) != len(submitted_ids):
        raise ValueError(
            "중복 제출된 문제 ID가 있습니다."
        )

    if set(submitted_ids) != question_ids:
        raise ValueError(
            "제출된 문제 ID가 퀴즈와 일치하지 않습니다."
        )

    if (
        submission.get("date") is not None
        and submission["date"] != quiz.get("date")
    ):
        raise ValueError(
            "학습 날짜가 일치하지 않습니다."
        )


def grade_multiple_choice(question, user_answer):
    correct = (
        normalize_answer(user_answer)
        == normalize_answer(question["answer"])
    )

    max_score = POINTS["multiple_choice"]

    return {
        "question_id": question["id"],
        "type": question["type"],
        "difficulty": question["difficulty"],
        "question": question["question"],
        "user_answer": user_answer,
        "correct_answer": question["answer"],
        "score": max_score if correct else 0,
        "max_score": max_score,
        "is_correct": correct,
        "feedback": (
            "정답입니다."
            if correct
            else "정답과 일치하지 않습니다."
        ),
        "explanation": question["explanation"],
        "source_page": question["source_page"],
        "source_text": question["source_text"]
    }


def grade_subjective_questions(
    questions,
    answer_lookup,
    service
):
    grading_items = []

    for question in questions:
        grading_items.append({
            "question_id": question["id"],
            "type": question["type"],
            "question": question["question"],
            "max_score": POINTS[question["type"]],
            "correct_answer": question["answer"],
            "keywords": question.get("keywords", []),
            "source_text": question["source_text"],
            "user_answer": answer_lookup[
                question["id"]
            ]
        })

    system_prompt = """
너는 AI 학습 서비스 피뢰침의 주관식 채점 전문가다.

제공된 문제, 모범 답안, PDF 원문을 기준으로 채점한다.

채점 원칙:
1. 답안의 의미와 개념적 정확성을 평가한다.
2. 모범 답안과 표현이 달라도 의미가 같으면 인정한다.
3. 띄어쓰기와 사소한 오탈자만으로 감점하지 않는다.
4. 핵심 개념이 정확하다면 부분 점수를 부여한다.
5. PDF에서 확인할 수 없는 내용을 정답의 필수 조건으로 요구하지 않는다.
6. 모범 답안에 근거 없는 내용이 있더라도 이를 필수 채점 기준으로 사용하지 않는다.
7. keywords는 참고 자료이며 모든 키워드가 필수는 아니다.
8. 문제에서 요구하는 조건이 충족되었는지 평가한다.
9. 문제에서 예시를 요구했다면 예시의 적절성도 평가한다.
10. 질문에 답하지 않거나 관련 없는 내용은 0점이다.
11. 빈 답안은 0점이다.
12. 점수는 0점 이상 최대 배점 이하의 정수다.
13. 모범 답안의 문장을 그대로 사용하지 않아도 정답으로 인정한다.
14. feedback에는 잘한 점과 부족한 점을 구체적으로 작성한다.
15. 답안에 없는 내용을 사용자가 작성했다고 판단하지 않는다.
16. 답안에 모순이나 잘못된 개념이 있으면 감점한다.
17. 단답형은 핵심 개념의 정확성을 중심으로 채점한다.
18. 서술형은 정확성, 설명의 충실성, 요구 조건 충족 여부를 평가한다.
19. 모든 feedback은 한국어로 작성한다.
20. 반드시 모든 문제를 정확히 한 번씩 채점한다.

단답형은 10점 만점이다.
서술형은 25점 만점이다.

반드시 지정된 JSON Schema를 준수한다.
"""

    user_prompt = (
        "다음 주관식 답안을 채점해라.\n\n"
        + json.dumps(
            grading_items,
            ensure_ascii=False,
            indent=2
        )
    )

    response = service.generate(
        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        schema=GRADING_SCHEMA,
        name="quiz_subjective_grading",
        max_tokens=3500
    )

    ai_results = response["results"]

    expected_ids = {
        question["id"]
        for question in questions
    }

    result_ids = [
        item["question_id"]
        for item in ai_results
    ]

    if (
        len(result_ids) != len(expected_ids)
        or len(set(result_ids)) != len(result_ids)
        or set(result_ids) != expected_ids
    ):
        raise ValueError(
            "AI 채점 결과의 문제 ID가 일치하지 않습니다."
        )

    ai_lookup = {
        item["question_id"]: item
        for item in ai_results
    }

    results = []

    for question in questions:
        question_id = question["id"]
        user_answer = answer_lookup[question_id]
        max_score = POINTS[question["type"]]
        ai_result = ai_lookup[question_id]

        score = ai_result["score"]

        if (
            isinstance(score, bool)
            or not isinstance(score, int)
            or score < 0
            or score > max_score
        ):
            raise ValueError(
                f"{question_id}번 AI 채점 점수가 올바르지 않습니다."
            )

        feedback = ai_result["feedback"].strip()

        if not feedback:
            raise ValueError(
                f"{question_id}번 채점 피드백이 없습니다."
            )

        if not user_answer.strip():
            score = 0
            feedback = "답안을 입력하지 않았습니다."

        results.append({
            "question_id": question_id,
            "type": question["type"],
            "difficulty": question["difficulty"],
            "question": question["question"],
            "user_answer": user_answer,
            "correct_answer": question["answer"],
            "score": score,
            "max_score": max_score,
            "is_correct": score == max_score,
            "feedback": feedback,
            "explanation": question["explanation"],
            "source_page": question["source_page"],
            "source_text": question["source_text"]
        })

    return results


def grade_quiz(
    quiz,
    submission,
    groq_service=None
):
    validate_submission(
        quiz,
        submission
    )

    answer_lookup = {
        item["question_id"]: item["answer"]
        for item in submission["answers"]
    }

    multiple_choice_results = []
    subjective_questions = []

    for question in quiz["questions"]:
        if question["type"] == "multiple_choice":
            result = grade_multiple_choice(
                question,
                answer_lookup[question["id"]]
            )

            multiple_choice_results.append(result)

        elif question["type"] in {
            "short_answer",
            "essay"
        }:
            subjective_questions.append(question)

        else:
            raise ValueError(
                f"지원하지 않는 문제 유형: {question['type']}"
            )

    subjective_results = []

    if subjective_questions:
        print("단답형 및 서술형 AI 채점 중")

        service = groq_service or GroqService()

        subjective_results = grade_subjective_questions(
            questions=subjective_questions,
            answer_lookup=answer_lookup,
            service=service
        )

    results = sorted(
        multiple_choice_results + subjective_results,
        key=lambda item: item["question_id"]
    )

    total_score = sum(
        item["score"]
        for item in results
    )

    max_score = sum(
        item["max_score"]
        for item in results
    )

    correct_count = sum(
        1
        for item in results
        if item["is_correct"]
    )

    partial_count = sum(
        1
        for item in results
        if 0 < item["score"] < item["max_score"]
    )

    incorrect_count = sum(
        1
        for item in results
        if item["score"] == 0
    )

    percentage = (
        round(total_score / max_score * 100, 1)
        if max_score
        else 0
    )

    if percentage >= 80:
        achievement = "green"
    elif percentage >= 50:
        achievement = "yellow"
    else:
        achievement = "red"

    return {
        "status": "success",
        "date": quiz["date"],
        "document_title": quiz["document_title"],
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
