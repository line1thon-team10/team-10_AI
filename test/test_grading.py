
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from services.quiz_grader import grade_quiz


def main():
    print("=== 일일 퀴즈 자동 채점 시작 ===")

    quiz_path = Path("quiz_result.json")

    if not quiz_path.exists():
        raise FileNotFoundError(
            "quiz_result.json 파일이 없습니다. "
            "먼저 python test_quiz.py를 실행하세요."
        )

    with quiz_path.open(
        "r",
        encoding="utf-8"
    ) as file:
        quiz = json.load(file)

    test_answers = {
        1: "준비 상태",
        2: "실행 상태",
        3: "휴면 상태",
        4: "네트워크 패킷 내용",
        5: "프로세스의 레지스터와 프로그램 카운터 값을 복원하기 위해",
        6: "실행 → 대기 → 준비",
        7: "생성",
        8: "대기 상태",
        9: "스케줄링 정보는 운영체제가 프로세스를 관리하고 CPU를 할당하는 데 사용하는 정보입니다.",
        10: "준비 상태는 CPU를 기다리고 대기 상태는 입출력을 기다리는 상태입니다."
    }

    submission = {
        "date": quiz["date"],
        "answers": [
            {
                "question_id": question["id"],
                "answer": test_answers.get(
                    question["id"],
                    ""
                )
            }
            for question in quiz["questions"]
        ]
    }

    print("\n=== 테스트 답안 ===")

    for item in submission["answers"]:
        print(
            f"{item['question_id']}번: "
            f"{item['answer']}"
        )

    print("\n=== 채점 진행 ===")

    result = grade_quiz(
        quiz=quiz,
        submission=submission
    )

    print("\n=== 채점 완료 ===")
    print(
        f"총점: {result['total_score']}"
        f"/{result['max_score']}"
    )
    print(
        f"성취도: {result['percentage']}%"
    )
    print(
        f"정답: {result['correct_count']}개"
    )
    print(
        f"부분 정답: {result['partial_count']}개"
    )
    print(
        f"오답: {result['incorrect_count']}개"
    )
    print(
        f"책 색상: {result['achievement']}"
    )

    print("\n=== 문제별 채점 결과 ===")

    for item in result["results"]:
        print(
            f"\n[{item['question_id']}번] "
            f"{item['type']}"
        )
        print(
            f"문제: {item['question']}"
        )
        print(
            f"제출 답안: {item['user_answer']}"
        )
        print(
            f"모범 답안: {item['correct_answer']}"
        )
        print(
            f"점수: {item['score']}"
            f"/{item['max_score']}"
        )
        print(
            f"피드백: {item['feedback']}"
        )
        print(
            f"해설: {item['explanation']}"
        )
        print(
            f"근거: PDF {item['source_page']}페이지"
        )

    output_path = Path("grading_result.json")

    with output_path.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2
        )

    print(
        "\ngrading_result.json 저장 완료"
    )


if __name__ == "__main__":
    main()
