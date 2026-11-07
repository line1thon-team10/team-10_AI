
import json
import os
import re
from datetime import date, timedelta

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

MODEL = "openai/gpt-oss-20b"

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM_PROMPT = """
너는 AI 학습 플래너 '피뢰침'의 학습 목표 설정 도우미다.

사용자 메시지를 분석해 학습 조건을 업데이트한다.

규칙:
1. 오늘 날짜를 기준으로 상대적인 날짜를 YYYY-MM-DD로 변환한다.
2. 이전 조건을 유지하고 사용자가 변경한 항목만 수정한다.
3. PDF 전체 단원을 기본 학습 범위로 설정한다.
4. 제외 단원과 집중 학습 단원은 제공된 unit_id만 사용한다.
5. 하루 학습 시간은 분 단위 정수로 변환한다.
6. 요일은 월요일=0, 일요일=6으로 변환한다.
7. 명시되지 않은 시험 날짜나 학습 시간을 추측하지 않는다.
8. 사용자의 최신 수정 요청이 이전 조건보다 우선한다.
9. 계획 생성 동의 여부를 confirmed로 반환한다.
10. 단순한 긍정 표현은 기존 조건이 완성된 경우에만 동의로 처리한다.
11. 사용자가 조건을 변경하면서 동의도 명시했다면 두 요청을 모두 반영한다.
12. 반드시 JSON 객체 하나만 반환한다.

출력 구조:
{
  "conditions": {
    "target_date": null,
    "daily_minutes": null,
    "excluded_unit_ids": [],
    "priority_unit_ids": [],
    "unavailable_weekdays": [],
    "unavailable_dates": [],
    "goal": "전체 범위 학습",
    "notes": ""
  },
  "confirmed": false
}
"""


def initial_conditions():
    return {
        "target_date": None,
        "daily_minutes": None,
        "excluded_unit_ids": [],
        "priority_unit_ids": [],
        "unavailable_weekdays": [],
        "unavailable_dates": [],
        "goal": "전체 범위 학습",
        "notes": "",
    }


def normalize_conditions(data, document):
    result = initial_conditions()

    if not isinstance(data, dict):
        data = {}

    for key in result:
        if key in data:
            result[key] = data[key]

    unit_ids = {
        unit["unit_id"]
        for unit in document["units"]
    }

    for key in ["excluded_unit_ids", "priority_unit_ids"]:
        values = result[key]

        if not isinstance(values, list):
            values = []

        result[key] = list(dict.fromkeys(
            value
            for value in values
            if isinstance(value, str) and value in unit_ids
        ))

    result["priority_unit_ids"] = [
        unit_id
        for unit_id in result["priority_unit_ids"]
        if unit_id not in result["excluded_unit_ids"]
    ]

    weekdays = result["unavailable_weekdays"]

    if not isinstance(weekdays, list):
        weekdays = []

    result["unavailable_weekdays"] = sorted(set(
        value
        for value in weekdays
        if isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 6
    ))

    dates = result["unavailable_dates"]

    if not isinstance(dates, list):
        dates = []

    valid_dates = []

    for value in dates:
        try:
            date.fromisoformat(value)
            valid_dates.append(value)
        except (TypeError, ValueError):
            pass

    result["unavailable_dates"] = sorted(set(valid_dates))

    minutes = result["daily_minutes"]

    if (
        not isinstance(minutes, int)
        or isinstance(minutes, bool)
        or minutes <= 0
        or minutes > 1440
    ):
        result["daily_minutes"] = None

    try:
        if result["target_date"] is not None:
            date.fromisoformat(result["target_date"])
    except (TypeError, ValueError):
        result["target_date"] = None

    if not isinstance(result["goal"], str):
        result["goal"] = "전체 범위 학습"

    if not isinstance(result["notes"], str):
        result["notes"] = ""

    return result


def get_available_days(conditions, today):
    if not conditions["target_date"]:
        return []

    target = date.fromisoformat(conditions["target_date"])

    if target <= today:
        return []

    days = []

    current = today

    while current < target:
        if (
            current.weekday() not in conditions["unavailable_weekdays"]
            and current.isoformat() not in conditions["unavailable_dates"]
        ):
            days.append(current)

        current += timedelta(days=1)

    return days


def get_missing_fields(conditions, document, today):
    missing = []

    if not conditions["target_date"]:
        missing.append("target_date")
    elif date.fromisoformat(conditions["target_date"]) <= today:
        missing.append("target_date")

    if conditions["daily_minutes"] is None:
        missing.append("daily_minutes")

    selected_units = [
        unit
        for unit in document["units"]
        if unit["unit_id"] not in conditions["excluded_unit_ids"]
    ]

    if not selected_units:
        missing.append("study_scope")

    if "target_date" not in missing:
        if not get_available_days(conditions, today):
            missing.append("available_days")

    return missing


def build_question(missing):
    if "target_date" in missing:
        return "언제까지 공부를 마쳐야 하나요? 시험 날짜나 목표 완료일을 알려주세요."

    if "daily_minutes" in missing:
        return "하루에 몇 분 또는 몇 시간 정도 공부할 수 있나요? 쉬는 요일이나 날짜도 함께 알려주세요."

    if "study_scope" in missing:
        return "모든 단원이 제외되었어요. 최소 한 개 이상의 학습 단원을 포함해 주세요."

    if "available_days" in missing:
        return "목표일까지 공부할 수 있는 날이 없어요. 목표 날짜나 쉬는 날을 조정해 주세요."

    return "학습 조건이 준비됐어요. 이 조건으로 일일 학습 계획을 생성할까요?"


def update_goal_conversation(document, state, user_message, today=None):
    if today is None:
        today = date.today()

    if isinstance(today, str):
        today = date.fromisoformat(today)

    if not document.get("units"):
        raise ValueError("PDF 분석 결과에 학습 단원이 없습니다.")

    if not user_message.strip():
        raise ValueError("사용자 메시지가 비어 있습니다.")

    previous = normalize_conditions(
        state if state is not None else initial_conditions(),
        document,
    )

    units = [
        {
            "unit_id": unit["unit_id"],
            "title": unit["title"],
            "start_page": unit["start_page"],
            "end_page": unit["end_page"],
        }
        for unit in document["units"]
    ]

    payload = {
        "today": today.isoformat(),
        "document_title": document.get("document_title"),
        "units": units,
        "previous_conditions": previous,
        "user_message": user_message,
    }

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False),
            },
        ],
        temperature=0,
        max_completion_tokens=2000,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content

    if not content:
        raise ValueError("Groq에서 빈 응답을 반환했습니다.")

    parsed = json.loads(content)

    if not isinstance(parsed, dict):
        raise ValueError("Groq 응답이 JSON 객체가 아닙니다.")

    conditions = normalize_conditions(
        parsed.get("conditions", {}),
        document,
    )

    missing = get_missing_fields(conditions, document, today)

    confirmed = parsed.get("confirmed") is True and not missing

    selected_units = [
        unit
        for unit in document["units"]
        if unit["unit_id"] not in conditions["excluded_unit_ids"]
    ]

    if confirmed:
        status = "confirmed"
        assistant_message = "학습 조건이 확정됐어요. 일일 학습 계획을 생성할게요."
    elif missing:
        status = "collecting"
        assistant_message = build_question(missing)
    else:
        status = "ready"
        assistant_message = build_question([])

    return {
        "status": status,
        "assistant_message": assistant_message,
        "conditions": conditions,
        "missing_fields": missing,
        "selected_units": selected_units,
    }
