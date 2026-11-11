
import json

from services.goal_conversation import (
    initial_conditions,
    update_goal_conversation,
)
from services.study_planner import create_study_plan
from services.plan_validator import validate_study_plan


TASK_TYPE_NAMES = {
    "study": "신규 학습",
    "deep_study": "집중 학습",
    "review": "복습",
    "quiz": "퀴즈",
}


def print_conditions(conditions):
    print("\n현재 학습 조건:")
    print(json.dumps(
        conditions,
        ensure_ascii=False,
        indent=2,
    ))


def print_study_plan(plan):
    print("\n생성된 일일 학습 계획:")

    for day in plan["schedule"]:
        print(
            f"\n[{day['date']}] "
            f"총 {day['total_minutes']}분"
        )

        for task in day["tasks"]:
            task_type = TASK_TYPE_NAMES.get(
                task["task_type"],
                task["task_type"],
            )

            print(
                f"- [{task['task_id']}] "
                f"{task_type}: {task['unit_title']}"
            )

            print(
                f"  페이지: "
                f"{task['start_page']}~{task['end_page']}p"
            )

            print(
                f"  시간: {task['estimated_minutes']}분"
            )

            print(
                f"  내용: {task['description']}"
            )


def main():
    with open("test_result.json", "r", encoding="utf-8") as file:
        document = json.load(file)

    state = initial_conditions()

    print(f"\n분석 문서: {document['document_title']}")
    print(f"전체 단원: {len(document['units'])}개")

    print("\nAI: PDF 전체를 기본 학습 범위로 설정했어요.")
    print("AI: 언제까지 공부를 마쳐야 하나요?")

    try:
        while True:
            message = input("\n사용자: ").strip()

            if message.lower() in ["exit", "quit", "종료"]:
                break

            if not message:
                continue

            try:
                result = update_goal_conversation(
                    document=document,
                    state=state,
                    user_message=message,
                )

                state = result["conditions"]

                print(f"\nAI: {result['assistant_message']}")
                print(f"상태: {result['status']}")

                if result["status"] in ["ready", "confirmed"]:
                    print_conditions(state)

                if result["status"] != "confirmed":
                    continue

                plan = create_study_plan(
                    document=document,
                    conditions=state,
                )

                if plan["status"] != "success":
                    print("\n학습 계획 생성 실패:")
                    print(json.dumps(
                        plan,
                        ensure_ascii=False,
                        indent=2,
                    ))
                    continue

                validate_study_plan(
                    plan=plan,
                    conditions=state,
                    document=document,
                )

                with open(
                    "study_plan_result.json",
                    "w",
                    encoding="utf-8",
                ) as file:
                    json.dump(
                        plan,
                        file,
                        ensure_ascii=False,
                        indent=2,
                    )

                print_study_plan(plan)

                print(
                    "\n학습 계획이 "
                    "study_plan_result.json에 저장됐습니다."
                )

                break

            except Exception as error:
                print(f"\n오류: {error}")

    except (KeyboardInterrupt, EOFError):
        print("\n프로그램을 종료합니다.")


if __name__ == "__main__":
    main()
