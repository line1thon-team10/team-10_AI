
import json
from pathlib import Path

from services.study_replanner import replan_study


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )


def main():
    path = Path("study_plan_result.json")

    if not path.exists():
        raise FileNotFoundError(
            "study_plan_result.json 파일이 없습니다."
        )

    with path.open("r", encoding="utf-8") as file:
        study_plan = json.load(file)

    schedule = study_plan["schedule"]

    study_day = next(
        (
            day for day in schedule
            if any(
                isinstance(task.get("start_page"), int)
                and isinstance(task.get("end_page"), int)
                for task in day["tasks"]
            )
            and day["date"] < study_plan["target_date"]
        ),
        None
    )

    if study_day is None:
        raise ValueError(
            "테스트할 학습 날짜를 찾지 못했습니다."
        )

    study_date = study_day["date"]

    planned_pages = sorted({
        page
        for task in study_day["tasks"]
        if isinstance(task.get("start_page"), int)
        and isinstance(task.get("end_page"), int)
        for page in range(
            task["start_page"],
            task["end_page"] + 1
        )
    })

    print("=== 학습 일정 재조정 테스트 ===")
    print(f"학습 날짜: {study_date}")
    print(f"오늘 학습 페이지: {planned_pages}")

    completed_result = replan_study(
        study_plan=study_plan,
        study_date=study_date,
        completed=True
    )

    print("\n=== 전체 완료 테스트 ===")
    print(f"상태: {completed_result['status']}")
    print(f"재조정: {completed_result['replanned']}")
    print(f"사유: {completed_result['reason']}")

    assert completed_result["replanned"] is False
    assert completed_result["study_plan"] == study_plan

    save_json(
        "replanner_completed_result.json",
        completed_result
    )

    completed_pages = planned_pages[:len(planned_pages) // 2]

    incomplete_result = replan_study(
        study_plan=study_plan,
        study_date=study_date,
        completed=False,
        completed_pages=completed_pages
    )

    print("\n=== 미완료 테스트 ===")
    print(f"상태: {incomplete_result['status']}")
    print(f"재조정: {incomplete_result['replanned']}")
    print(f"완료 페이지: {incomplete_result['completed_pages']}")
    print(f"미완료 페이지: {incomplete_result['remaining_pages']}")
    print(f"사유: {incomplete_result['reason']}")

    save_json(
        "replanner_incomplete_result.json",
        incomplete_result
    )

    if incomplete_result["status"] == "success":
        print("\n=== 변경된 미래 일정 ===")

        for day in incomplete_result["study_plan"]["schedule"]:
            if day["date"] <= study_date:
                continue

            print(
                f"\n{day['date']} "
                f"({day['total_minutes']}분)"
            )

            for task in day["tasks"]:
                print(
                    f"  {task.get('unit_title', '학습')}: "
                    f"{task.get('start_page', '-')}~"
                    f"{task.get('end_page', '-')}페이지 "
                    f"({task.get('estimated_minutes', 0)}분)"
                )

    print("\n=== 테스트 완료 ===")
    print("replanner_completed_result.json 저장 완료")
    print("replanner_incomplete_result.json 저장 완료")


if __name__ == "__main__":
    main()
