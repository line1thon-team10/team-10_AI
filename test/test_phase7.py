
import json
from pathlib import Path

from services.quiz_grader import grade_quiz
from services.backend_adapter import (
    convert_question,
    convert_grading_to_attempts
)
from services.learning_metrics import (
    calculate_learning_metrics
)

SEED_PATH = Path("seed_quiz.json")
OUTPUT_DIR = Path("result/phase7")


def save_json(filename, data):
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    path = OUTPUT_DIR / filename

    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(f"저장 완료: {path}")


def main():
    data = json.loads(
        SEED_PATH.read_text(encoding="utf-8")
    )

    questions = [
        question
        for question in data["questions"]
        if question["type"] in {"객관식", "OX"}
    ][:5]

    assert len(questions) == 5

    converted_questions = [
        convert_question(question)
        for question in questions
    ]

    quiz = {
        "status": "success",
        "date": "2026-11-09",
        "document_title": "7차 통합 테스트",
        "questions": converted_questions
    }

    answers = []

    for index, question in enumerate(questions):
        if index == 0:
            answer = question["answer"]
            confidence = "확실"
        elif index == 1:
            answer = question["answer"]
            confidence = "애매"
        else:
            answer = (
                "X" if question["type"] == "OX"
                and question["answer"] == "O"
                else (
                    "O" if question["type"] == "OX"
                    else "__wrong_answer__"
                )
            )
            confidence = "확실"

        answers.append({
            "question_id": question["id"],
            "answer": answer,
            "confidence": confidence
        })

    submission = {
        "date": "2026-11-09",
        "answers": answers
    }

    print("[1/3] 퀴즈 채점")

    grading = grade_quiz(
        quiz,
        submission
    )

    assert grading["total_questions"] == 5

    save_json(
        "grading.json",
        grading
    )

    print("[2/3] 풀이 기록 변환")

    attempts = convert_grading_to_attempts(
        grading
    )

    assert len(attempts) == 5
    assert all(
        item["confidence"] in {"확실", "애매"}
        for item in attempts
    )

    save_json(
        "attempts.json",
        attempts
    )

    print("[3/3] 학습 상태 계산")

    updated_data = dict(data)
    updated_data["attempts"] = (
        data["attempts"] + attempts
    )

    metrics = calculate_learning_metrics(
        updated_data,
        {
            "DS": 88,
            "OS": 67,
            "NW": 36
        }
    )

    assert metrics["units"]
    assert metrics["readiness"]

    save_json(
        "learning_metrics.json",
        metrics
    )

    summary = {
        "status": "success",
        "graded_questions": grading[
            "total_questions"
        ],
        "attempts_created": len(attempts),
        "unit_count": len(metrics["units"]),
        "weak_concept_count": len(
            metrics["weak_concepts"]
        )
    }

    save_json(
        "summary.json",
        summary
    )

    print("\n7차 2단계 통합 테스트 통과")
    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2
        )
    )


if __name__ == "__main__":
    main()
