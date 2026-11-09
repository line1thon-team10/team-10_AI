
import copy
from datetime import date


def _pages(task):
    start = task.get("start_page")
    end = task.get("end_page")

    if (
        type(start) is int
        and type(end) is int
        and 1 <= start <= end
    ):
        return list(range(start, end + 1))

    return []


def _minutes(task):
    value = task.get("estimated_minutes", 0)

    if type(value) is not int or value < 0:
        raise ValueError(
            "estimated_minutes는 0 이상의 정수여야 합니다."
        )

    return value


def _slice(task, pages):
    original = _pages(task)

    if not pages or not set(pages).issubset(original):
        raise ValueError(
            "과제 페이지 범위가 올바르지 않습니다."
        )

    result = copy.deepcopy(task)

    result["start_page"] = min(pages)
    result["end_page"] = max(pages)

    minutes = _minutes(task)
    quotient, remainder = divmod(minutes, len(original))

    result["estimated_minutes"] = sum(
        quotient + (i < remainder)
        for i, page in enumerate(original)
        if page in pages
    )

    if len(pages) != len(original):
        result["task_id"] = (
            f"{task.get('task_id', 'task')}"
            f"_p{min(pages)}_{max(pages)}"
        )

    return result


def _runs(pages):
    groups = []

    for page in sorted(pages):
        if not groups or page != groups[-1][-1] + 1:
            groups.append([page])
        else:
            groups[-1].append(page)

    return groups


def _total(day):
    return sum(
        _minutes(task)
        for task in day["tasks"]
    )


def replan_study(
    study_plan,
    study_date,
    completed,
    completed_pages=None
):
    plan = copy.deepcopy(study_plan)
    days = plan.get("schedule")

    if not isinstance(days, list) or not days:
        raise ValueError(
            "schedule이 비어 있거나 올바르지 않습니다."
        )

    if type(completed) is not bool:
        raise ValueError(
            "completed는 bool이어야 합니다."
        )

    if (
        type(plan.get("daily_minutes")) is not int
        or plan["daily_minutes"] <= 0
    ):
        raise ValueError(
            "daily_minutes가 올바르지 않습니다."
        )

    date.fromisoformat(study_date)

    target = date.fromisoformat(
        plan["target_date"]
    )

    if date.fromisoformat(study_date) > target:
        raise ValueError(
            "마감일 이후에는 재조정할 수 없습니다."
        )

    dates = [
        day["date"]
        for day in days
    ]

    if (
        len(set(dates)) != len(dates)
        or dates != sorted(dates)
    ):
        raise ValueError(
            "schedule 날짜가 중복되거나 정렬되지 않았습니다."
        )

    today = next(
        (
            day for day in days
            if day["date"] == study_date
        ),
        None
    )

    if today is None:
        raise ValueError(
            "해당 날짜의 일정이 없습니다."
        )

    for day in days:
        if not isinstance(day.get("tasks"), list):
            raise ValueError(
                "tasks는 배열이어야 합니다."
            )

        for task in day["tasks"]:
            _minutes(task)

    study_tasks = [
        task
        for task in today["tasks"]
        if task.get("task_type") in (
            "study",
            "deep_study"
        )
        and _pages(task)
    ]

    planned = sorted({
        page
        for task in study_tasks
        for page in _pages(task)
    })

    if completed:
        return {
            "status": "success",
            "replanned": False,
            "reason": (
                "오늘 학습 목표를 완료하여 "
                "기존 일정을 유지합니다."
            ),
            "study_date": study_date,
            "planned_pages": planned,
            "completed_pages": planned,
            "remaining_pages": [],
            "study_plan": plan
        }

    if completed_pages is None:
        completed_pages = []

    if (
        not isinstance(completed_pages, list)
        or any(
            type(page) is not int
            for page in completed_pages
        )
        or len(set(completed_pages)) != len(
            completed_pages
        )
    ):
        raise ValueError(
            "completed_pages는 중복 없는 "
            "정수 배열이어야 합니다."
        )

    done = set(completed_pages)

    if not done.issubset(planned):
        raise ValueError(
            "완료 페이지가 오늘 학습 범위를 "
            "벗어났습니다."
        )

    remaining = sorted(
        set(planned) - done
    )

    if not remaining:
        raise ValueError(
            "모두 완료했다면 completed=True를 사용하세요."
        )

    if not study_tasks:
        raise ValueError(
            "오늘 일정에 페이지 기반 "
            "학습 과제가 없습니다."
        )

    pending = []
    revised_today = []

    for task in today["tasks"]:
        if task not in study_tasks:
            revised_today.append(task)
            continue

        pages = _pages(task)

        for run in _runs([
            page for page in pages
            if page in done
        ]):
            revised_today.append(
                _slice(task, run)
            )

        for run in _runs([
            page for page in pages
            if page not in done
        ]):
            pending.append(
                _slice(task, run)
            )

    today["tasks"] = revised_today
    today["total_minutes"] = _total(today)

    future = [
        day for day in days
        if study_date < day["date"]
        <= plan["target_date"]
    ]

    if not future:
        return {
            "status": "adjustment_required",
            "replanned": False,
            "reason": "남은 학습일이 없습니다.",
            "study_date": study_date,
            "planned_pages": planned,
            "completed_pages": sorted(done),
            "remaining_pages": remaining,
            "study_plan": copy.deepcopy(study_plan)
        }

    completion = {}

    for day in days:
        if day["date"] >= study_date:
            break

        for task in day["tasks"]:
            if task.get("task_type") in (
                "study",
                "deep_study"
            ):
                for page in _pages(task):
                    completion[
                        (task.get("unit_id"), page)
                    ] = day["date"]

    for task in study_tasks:
        for page in _pages(task):
            if page in done:
                completion[
                    (task.get("unit_id"), page)
                ] = study_date

    deferred = []

    for day in future:
        incoming = deferred + day["tasks"]
        deferred = []

        day["tasks"] = []

        incoming = pending + incoming
        pending = []

        for task in incoming:
            task_pages = _pages(task)
            task_type = task.get("task_type")

            is_dependency = task_type in (
                "review",
                "quiz"
            )

            dependency_ready = (
                not is_dependency
                or all(
                    (
                        (task.get("unit_id"), page)
                        in completion
                        and completion[
                            (task.get("unit_id"), page)
                        ] < day["date"]
                    )
                    for page in task_pages
                )
            )

            if not dependency_ready:
                deferred.append(task)
                continue

            available = (
                plan["daily_minutes"] - _total(day)
            )

            if _minutes(task) <= available:
                day["tasks"].append(task)

                if task_type in (
                    "study",
                    "deep_study"
                ):
                    for page in task_pages:
                        completion[
                            (task.get("unit_id"), page)
                        ] = day["date"]
            else:
                deferred.append(task)

        day["total_minutes"] = _total(day)

    if deferred:
        return {
            "status": "adjustment_required",
            "replanned": False,
            "reason": (
                "남은 학습일 또는 하루 학습 시간이 "
                "부족하여 일부 과제를 "
                "배정하지 못했습니다."
            ),
            "study_date": study_date,
            "planned_pages": planned,
            "completed_pages": sorted(done),
            "remaining_pages": remaining,
            "unallocated_tasks": deferred,
            "study_plan": copy.deepcopy(study_plan)
        }

    return {
        "status": "success",
        "replanned": True,
        "reason": (
            "미완료 학습을 우선 배정하고 "
            "복습·퀴즈 선후관계를 고려해 "
            "일정을 조정했습니다."
        ),
        "study_date": study_date,
        "planned_pages": planned,
        "completed_pages": sorted(done),
        "remaining_pages": remaining,
        "study_plan": plan
    }
