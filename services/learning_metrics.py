
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

WEIGHT = {"하": 1.0, "중": 1.5, "상": 2.0}


def rnd(value):
    return int(
        Decimal(str(value)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP
        )
    )


def item_point(attempt):
    if not attempt["correct"]:
        return 0.0
    return 1.0 if attempt["confidence"] == "확실" else 0.5


def unit_score(items):
    if not items:
        raise ValueError(
            "단원 이해도 계산에 풀이 기록이 필요합니다."
        )

    def rate(values):
        return sum(
            point * weight for point, weight in values
        ) / sum(weight for _, weight in values)

    recent = items[-20:]
    alpha = (
        0.5 if len(recent) < 10
        else (0.4 if len(recent) < 20 else 0.3)
    )

    return 100 * (
        alpha * rate(items)
        + (1 - alpha) * rate(recent)
    )


def grade(score):
    return (
        "붕괴 위기" if score < 50
        else ("흔들림" if score < 80 else "안정")
    )


def calculate_learning_metrics(data, done_pages=None):
    questions = {
        q["id"]: q for q in data["questions"]
    }
    units = {
        u["id"]: u for u in data["units"]
    }
    concepts = {
        c["id"]: c for c in data["concepts"]
    }

    by_day = defaultdict(list)

    for attempt in data["attempts"]:
        if attempt["question"] not in questions:
            raise ValueError(
                f"존재하지 않는 문제 ID: {attempt['question']}"
            )

        if attempt["confidence"] not in ("확실", "애매"):
            raise ValueError(
                "확신도는 확실 또는 애매여야 합니다."
            )

        by_day[attempt["date"]].append(attempt)

    items = defaultdict(list)
    shown = {}
    recovery = set()
    history = []

    for day in sorted(by_day):
        touched = []

        for attempt in by_day[day]:
            question = questions[attempt["question"]]
            unit_id = question["unit"]

            if unit_id not in units:
                raise ValueError(
                    f"존재하지 않는 단원 ID: {unit_id}"
                )

            items[unit_id].append((
                item_point(attempt),
                WEIGHT[question["difficulty"]]
            ))

            if unit_id not in touched:
                touched.append(unit_id)

        for unit_id in touched:
            raw = min(unit_score(items[unit_id]), 99)
            previous = shown.get(unit_id)
            current = raw

            if (
                unit_id in recovery
                and previous is not None
                and raw > previous + 5
            ):
                current = previous + 5

            shown[unit_id] = current
            score = rnd(current)

            if score < 80:
                recovery.add(unit_id)

            history.append({
                "date": day,
                "unit": unit_id,
                "unit_name": units[unit_id]["name"],
                "previous_score": (
                    None if previous is None
                    else rnd(previous)
                ),
                "score": score,
                "grade": grade(score),
            })

    unit_results = [
        {
            "unit": unit_id,
            "unit_name": units[unit_id]["name"],
            "score": rnd(score),
            "grade": grade(rnd(score)),
            "recovery_mode": unit_id in recovery,
        }
        for unit_id, score in shown.items()
    ]

    readiness = []

    if done_pages is not None:
        for subject in data["subjects"]:
            subject_units = [
                u for u in data["units"]
                if u["subject"] == subject["id"]
                and u["id"] in shown
            ]

            if not subject_units:
                continue

            lengths = {
                u["id"]: (
                    u["page_end"] - u["page_start"] + 1
                )
                for u in subject_units
            }

            mastery = (
                sum(
                    rnd(shown[uid]) * pages
                    for uid, pages in lengths.items()
                )
                / sum(lengths.values())
                / 100
            )

            completed = done_pages.get(subject["id"])

            if completed is None:
                continue

            progress = completed / subject["pages"]
            ready = rnd(progress * mastery * 100)

            readiness.append({
                "subject": subject["id"],
                "subject_name": subject["name"],
                "progress_percent": round(
                    progress * 100, 2
                ),
                "mastery_percent": round(
                    mastery * 100, 2
                ),
                "readiness_percent": ready,
                "target_percent": subject["target"],
                "gap_percent": subject["target"] - ready,
            })

    wrong = defaultdict(int)

    for attempt in data["attempts"]:
        if not attempt["correct"]:
            concept_id = questions[
                attempt["question"]
            ]["concept"]
            wrong[concept_id] += 1

    weak_concepts = [
        {
            "concept": concept_id,
            "concept_name": concepts[concept_id]["name"],
            "wrong_count": count,
            "is_weak": count >= 2,
        }
        for concept_id, count in sorted(wrong.items())
    ]

    return {
        "unit_history": history,
        "units": unit_results,
        "readiness": readiness,
        "concept_errors": weak_concepts,
        "weak_concepts": [
            item for item in weak_concepts
            if item["is_weak"]
        ],
    }
