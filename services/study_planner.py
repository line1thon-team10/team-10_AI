
from datetime import date, timedelta
from math import ceil


def get_study_days(conditions, today):
    target = date.fromisoformat(conditions["target_date"])
    unavailable_weekdays = set(conditions["unavailable_weekdays"])
    unavailable_dates = set(conditions["unavailable_dates"])

    days = []
    current = today

    while current < target:
        if (
            current.weekday() not in unavailable_weekdays
            and current.isoformat() not in unavailable_dates
        ):
            days.append(current)

        current += timedelta(days=1)

    return days


def get_selected_units(document, conditions):
    excluded_ids = set(conditions["excluded_unit_ids"])

    return [
        unit
        for unit in document["units"]
        if unit["unit_id"] not in excluded_ids
    ]


def get_concepts(unit):
    concepts = unit.get("key_concepts", [])

    if not isinstance(concepts, list):
        return []

    return [
        concept.strip()
        for concept in concepts
        if isinstance(concept, str) and concept.strip()
    ]


def get_description(unit, task_type, concept_index=0):
    concepts = get_concepts(unit)

    if task_type == "study":
        if concepts:
            return f"{unit['title']} 학습: {concepts[0]}"
        return f"{unit['title']}의 핵심 개념 학습"

    if task_type == "deep_study":
        if concepts:
            index = concept_index % len(concepts)
            return f"집중 학습: {concepts[index]}"
        return f"{unit['title']} 집중 학습"

    if task_type == "review":
        if concepts:
            index = concept_index % len(concepts)
            return f"복습: {concepts[index]}"
        return f"{unit['title']} 핵심 내용 복습"

    if task_type == "quiz":
        if concepts:
            index = concept_index % len(concepts)
            return f"개념 확인 퀴즈: {concepts[index]}"
        return f"{unit['title']} 개념 확인 퀴즈"

    return unit["title"]


def make_task(
    unit,
    task_type,
    minutes,
    description,
    start_page=None,
    end_page=None,
):
    return {
        "task_type": task_type,
        "unit_id": unit["unit_id"],
        "unit_title": unit["title"],
        "start_page": (
            unit["start_page"]
            if start_page is None
            else start_page
        ),
        "end_page": (
            unit["end_page"]
            if end_page is None
            else end_page
        ),
        "estimated_minutes": minutes,
        "description": description,
    }


def split_unit_study(unit, daily_minutes):
    start_page = unit["start_page"]
    end_page = unit["end_page"]
    total_pages = end_page - start_page + 1

    if total_pages <= 0:
        raise ValueError(f"잘못된 단원 페이지 범위: {unit['unit_id']}")

    minutes_per_page = 15
    pages_per_task = max(1, daily_minutes // minutes_per_page)

    tasks = []
    current_page = start_page

    while current_page <= end_page:
        task_end = min(
            end_page,
            current_page + pages_per_task - 1,
        )

        page_count = task_end - current_page + 1
        minutes = page_count * minutes_per_page

        tasks.append(
            make_task(
                unit=unit,
                task_type="study",
                minutes=minutes,
                description=get_description(unit, "study"),
                start_page=current_page,
                end_page=task_end,
            )
        )

        current_page = task_end + 1

    return tasks


def build_unit_tasks(unit, conditions):
    daily_minutes = conditions["daily_minutes"]
    priority_ids = set(conditions["priority_unit_ids"])
    is_priority = unit["unit_id"] in priority_ids

    tasks = split_unit_study(unit, daily_minutes)

    concepts = get_concepts(unit)

    if is_priority:
        tasks.append(
            make_task(
                unit,
                "deep_study",
                min(30, daily_minutes),
                get_description(unit, "deep_study", 1),
            )
        )

    tasks.append(
        make_task(
            unit,
            "review",
            min(20 if not is_priority else 30, daily_minutes),
            get_description(unit, "review", 2),
        )
    )

    tasks.append(
        make_task(
            unit,
            "quiz",
            min(20 if not is_priority else 30, daily_minutes),
            get_description(unit, "quiz", 3),
        )
    )

    return tasks


def distribute_tasks(tasks, days, daily_minutes):
    schedule = [
        {
            "date": day.isoformat(),
            "day_of_week": day.weekday(),
            "total_minutes": 0,
            "tasks": [],
        }
        for day in days
    ]

    if not schedule:
        return None

    if not tasks:
        return schedule

    day_count = len(schedule)
    task_count = len(tasks)

    for index, task in enumerate(tasks):
        preferred_day = min(
            day_count - 1,
            (index * day_count) // task_count,
        )

        assigned = False

        for day_index in range(preferred_day, day_count):
            day = schedule[day_index]

            if (
                day["total_minutes"] + task["estimated_minutes"]
                <= daily_minutes
            ):
                day["tasks"].append(task.copy())
                day["total_minutes"] += task["estimated_minutes"]
                assigned = True
                break

        if not assigned:
            return None

    return schedule


def fill_review_days(schedule, units, conditions):
    daily_minutes = conditions["daily_minutes"]
    priority_ids = set(conditions["priority_unit_ids"])

    if not units:
        return schedule

    review_index = 0

    for day in schedule:
        if day["tasks"]:
            continue

        priority_units = [
            unit
            for unit in units
            if unit["unit_id"] in priority_ids
        ]

        review_units = priority_units or units

        unit = review_units[review_index % len(review_units)]
        review_index += 1

        task_type = "quiz" if review_index % 2 == 0 else "review"
        minutes = min(30, daily_minutes)

        task = make_task(
            unit,
            task_type,
            minutes,
            get_description(
                unit,
                task_type,
                review_index,
            ),
        )

        day["tasks"].append(task)
        day["total_minutes"] = minutes

    return schedule


def add_task_ids(schedule):
    counter = 1

    for day in schedule:
        for task in day["tasks"]:
            task["task_id"] = f"task_{counter:04d}"
            counter += 1

    return schedule


def create_study_plan(document, conditions, today=None):
    if today is None:
        today = date.today()

    if isinstance(today, str):
        today = date.fromisoformat(today)

    daily_minutes = conditions["daily_minutes"]

    if not isinstance(daily_minutes, int) or daily_minutes <= 0:
        raise ValueError("하루 학습 시간이 올바르지 않습니다.")

    selected_units = get_selected_units(document, conditions)

    if not selected_units:
        raise ValueError("학습할 단원이 없습니다.")

    days = get_study_days(conditions, today)

    if not days:
        raise ValueError("학습 가능한 날짜가 없습니다.")

    tasks = []

    for unit in selected_units:
        tasks.extend(build_unit_tasks(unit, conditions))

    required_minutes = sum(
        task["estimated_minutes"]
        for task in tasks
    )

    available_minutes = len(days) * daily_minutes

    if required_minutes > available_minutes:
        return {
            "status": "insufficient_time",
            "message": "목표일까지 학습과 복습을 완료하기에 시간이 부족합니다.",
            "required_minutes": required_minutes,
            "available_minutes": available_minutes,
            "shortage_minutes": required_minutes - available_minutes,
            "suggestion": "하루 학습 시간을 늘리거나 목표 날짜를 연장해 주세요.",
        }

    schedule = distribute_tasks(
        tasks,
        days,
        daily_minutes,
    )

    if schedule is None:
        return {
            "status": "insufficient_time",
            "message": "일정에 학습 작업을 배정할 수 없습니다.",
            "suggestion": "하루 학습 시간을 늘리거나 목표 날짜를 연장해 주세요.",
        }

    schedule = fill_review_days(
        schedule,
        selected_units,
        conditions,
    )

    schedule = add_task_ids(schedule)

    return {
        "status": "success",
        "document_title": document.get("document_title"),
        "start_date": today.isoformat(),
        "target_date": conditions["target_date"],
        "daily_minutes": daily_minutes,
        "total_study_days": len(days),
        "selected_unit_ids": [
            unit["unit_id"]
            for unit in selected_units
        ],
        "priority_unit_ids": [
            unit_id
            for unit_id in conditions["priority_unit_ids"]
            if unit_id in {
                unit["unit_id"]
                for unit in selected_units
            }
        ],
        "schedule": schedule,
    }
