
import json
from pathlib import Path

from dotenv import load_dotenv

from services.quiz_generator import (
    generate_daily_quiz,
    get_public_quiz
)

load_dotenv()

PDF_PATH = "data/demo/operating_system.pdf"
PLAN_PATH = "study_plan_result.json"

# 실제 학습 계획에 존재하는 날짜
TEST_DATE = "2026-11-12"


def main():
    study_plan = json.loads(
        Path(PLAN_PATH).read_text(encoding="utf-8")
    )

    print("=== 일일 퀴즈 생성 시작 ===")

    result = generate_daily_quiz(
        pdf_path=PDF_PATH,
        study_plan=study_plan,
        study_date=TEST_DATE
    )

    if result["status"] != "success":
        print(result["message"])
        return

    # 전체 정답 데이터 저장 (로컬 테스트 전용)
    Path("quiz_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 정답을 제거한 프론트엔드용 데이터
    public_quiz = get_public_quiz(result)

    Path("quiz_public.json").write_text(
        json.dumps(public_quiz, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("\n=== 생성 완료 ===")
    print(f"학습 날짜: {result['date']}")
    print(f"문제 수: {result['total_questions']}")
    print(f"출제 페이지: {result['source_pages']}")

    for question in result["questions"]:
        print(
            f"\n[{question['id']}번] "
            f"{question['type']} / {question['difficulty']}"
        )
        print(question["question"])
        print(f"정답: {question['answer']}")
        print(f"근거: PDF {question['source_page']}페이지")

    print("\nquiz_result.json 저장 완료")
    print("quiz_public.json 저장 완료")


if __name__ == "__main__":
    main()
