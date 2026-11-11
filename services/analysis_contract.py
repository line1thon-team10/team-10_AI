
import re
from typing import Any


DIFFICULTY_MULTIPLIERS = {"하": 1.0, "중": 1.2, "상": 1.5}


def _as_dict(value: Any) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    raise TypeError("분석 결과는 dict 또는 Pydantic 모델이어야 합니다.")


def convert_analysis_for_backend(analysis: Any, subject: str) -> dict:
    document = _as_dict(analysis)

    if not isinstance(subject, str) or not re.fullmatch(
        r"[A-Z][A-Z0-9]{1,9}", subject
    ):
        raise ValueError(
            "subject는 DS, OS, NW 같은 대문자 과목 코드여야 합니다."
        )

    units = []

    for index, raw in enumerate(document.get("units", []), start=1):
        unit = _as_dict(raw)
        start = int(unit["start_page"])
        end = int(unit["end_page"])

        if start < 1 or end < start or end > int(document["total_pages"]):
            raise ValueError("단원 페이지 범위가 올바르지 않습니다.")

        unit_id = f"{subject}{index}"
        concepts = []

        for number, concept in enumerate(
            unit.get("concepts") or unit.get("key_concepts", []),
            start=1
        ):
            if isinstance(concept, str):
                name = concept
                page_start = start
                page_end = end
            else:
                name = concept["name"]
                page_start = int(concept.get("page_start", start))
                page_end = int(concept.get("page_end", end))

            if not start <= page_start <= page_end <= end:
                raise ValueError(
                    "개념 페이지 범위가 단원 범위를 벗어났습니다."
                )

            concepts.append({
                "id": f"{unit_id}-{number}",
                "name": name,
                "page_start": page_start,
                "page_end": page_end
            })

        difficulty = unit.get("difficulty", "중")

        if difficulty not in DIFFICULTY_MULTIPLIERS:
            difficulty = "중"

        minutes = round(
            (end - start + 1)
            * 2.5
            * DIFFICULTY_MULTIPLIERS[difficulty],
            1
        )

        units.append({
            "id": unit_id,
            "name": unit["title"],
            "page_start": start,
            "page_end": end,
            "difficulty": difficulty,
            "estimated_minutes": minutes,
            "concepts": concepts
        })

    return {
        "subject": subject,
        "document_title": document["document_title"],
        "total_pages": document["total_pages"],
        "units": units
    }
