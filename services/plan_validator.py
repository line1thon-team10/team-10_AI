
from datetime import date


VALID_TASK_TYPES = {
    "study",
    "deep_study",
    "review",
    "quiz",
}


def validate_study_plan(plan, conditions, document=None):
    if plan.get("status") != "success":
        return False

    schedule = plan.get("schedule", [])

    if not schedule:
        raise ValueError("생성된 학습 일정이 없습니다.")

    target = date.fromisoformat(conditions["target_date"])
    unavailable_weekdays = set(conditions["unavailable_weekdays"])
    unavailable_dates = set(conditions["unavailable_dates"])
    excluded_ids = set(conditions["excluded_unit_ids"])

    task_ids = set()
    studied_pages = {}
    previous_date = None

    for day in schedule:
        current = date.fromisoformat(day["date"])

        if current >= target:
            raise ValueError("목표 날짜 이후의 일정이 포함되어 있습니다.")

        if current.weekday() in unavailable_weekdays:
            raise ValueError("휴식 요일에 학습 일정이 배정되었습니다.")

        if current.isoformat() in unavailable_dates:
            raise ValueError("휴식 날짜에 학습 일정이 배정되었습니다.")

        if previous_date is not None and current <= previous_date:
            raise ValueError("일정 날짜 순서가 올바르지 않습니다.")

        if day["day_of_week"] != current.weekday():
            raise ValueError("요일 정보가 실제 날짜와 일치하지 않습니다.")

        actual_minutes = 0

        for task in day["tasks"]:
            task_id = task.get("task_id")
            task_type = task.get("task_type")
            unit_id = task.get("unit_id")
            minutes = task.get("estimated_minutes")

            if not task_id or task_id in task_ids:
                raise ValueError("작업 ID가 없거나 중복되었습니다.")

            task_ids.add(task_id)

            if task_type not in VALID_TASK_TYPES:
                raise ValueError(f"지원하지 않는 작업 유형: {task_type}")

            if unit_id in excluded_ids:
                raise ValueError("제외한 단원이 일정에 포함되었습니다.")

            if (
                not isinstance(minutes, int)
                or isinstance(minutes, bool)
                or minutes <= 0
            ):
                raise ValueError("작업 시간이 올바르지 않습니다.")

            if not task.get("description"):
                raise ValueError("작업 설명이 없습니다.")

            if task_type == "study":
                start_page = task["start_page"]
                end_page = task["end_page"]

                if start_page > end_page:
                    raise ValueError("학습 페이지 범위가 올바르지 않습니다.")

                studied_pages.setdefault(unit_id, set()).update(
                    range(start_page, end_page + 1)
                )

            actual_minutes += minutes

        if actual_minutes != day["total_minutes"]:
            raise ValueError("일일 학습 시간 합계가 일치하지 않습니다.")

        if actual_minutes > conditions["daily_minutes"]:
            raise ValueError("하루 학습 가능 시간을 초과했습니다.")

        previous_date = current

    if document is not None:
        for unit in document["units"]:
            unit_id = unit["unit_id"]

            if unit_id in excluded_ids:
                continue

            expected_pages = set(
                range(
                    unit["start_page"],
                    unit["end_page"] + 1,
                )
            )

            actual_pages = studied_pages.get(unit_id, set())

            if expected_pages != actual_pages:
                raise ValueError(
                    f"학습 범위가 누락되거나 초과되었습니다: {unit_id}"
                )

    return True
