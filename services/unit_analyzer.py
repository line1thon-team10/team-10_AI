
import json
import re

from pydantic import BaseModel, ConfigDict, Field


MAX_TEXT_CHARS = 2000


class ExtractedConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    pages: list[int]


class UnitContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_concepts: list[ExtractedConcept]
    summary: str


class StudyUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_id: str
    parent_section: str
    title: str
    start_page: int
    end_page: int
    key_concepts: list[str]
    summary: str
    difficulty: str = "중"
    estimated_minutes: float = 0
    concepts: list[dict] = Field(default_factory=list)


def _normalized(value):
    return re.sub(r"\s+", "", str(value)).casefold()


def split_unit_pages(pages):
    chunks = []
    current = []
    current_length = 0

    for page in pages:
        text = str(page.get("text", ""))
        page_number = int(page["page"])

        if not text.strip():
            continue

        if len(text) > MAX_TEXT_CHARS:
            if current:
                chunks.append(current)
                current = []
                current_length = 0

            for start in range(0, len(text), MAX_TEXT_CHARS):
                part = text[start:start + MAX_TEXT_CHARS]

                chunks.append([
                    {
                        "page": page_number,
                        "text": part
                    }
                ])

            continue

        if current and current_length + len(text) > MAX_TEXT_CHARS:
            chunks.append(current)
            current = []
            current_length = 0

        current.append({
            "page": page_number,
            "text": text
        })

        current_length += len(text)

    if current:
        chunks.append(current)

    return chunks


def analyze_unit_chunk(groq, chunk, unit):
    available_pages = sorted({
        int(page["page"])
        for page in chunk
    })

    prompt = f"""
다음 학습 단원의 PDF 내용을 분석하세요.

학습 단원:
{unit.title}

상위 목차:
{unit.parent_section}

학습 범위:
{unit.start_page}~{unit.end_page}페이지

현재 제공된 페이지:
{json.dumps(available_pages, ensure_ascii=False)}

현재 분석 내용:
{json.dumps(chunk, ensure_ascii=False)}

규칙:
1. 실제 제공된 PDF 내용만 사용하세요.
2. 핵심 개념은 최대 6개 추출하세요.
3. 각 핵심 개념은 name과 pages를 포함해야 합니다.
4. name에는 해당 개념을 구체적으로 식별할 수 있는 이름을 작성하세요.
5. pages에는 해당 개념을 설명하는 실제 PDF 페이지 번호를 넣으세요.
6. pages에는 현재 제공된 페이지 번호만 사용할 수 있습니다.
7. 개념이 실제로 설명되지 않은 페이지를 근거로 지정하지 마세요.
8. PDF에 등장하는 중요한 알고리즘, 용어, 원리, 정의를 우선 추출하세요.
9. 같은 개념을 중복 추출하지 마세요.
10. 현재 내용에 없는 개념을 만들어내지 마세요.
11. 단원 이름이나 페이지 범위를 새로 생성하지 마세요.
12. 요약은 한국어 2~3문장으로 작성하세요.
13. 근거가 불분명한 개념은 추출하지 마세요.
"""

    result = groq.generate(
        messages=[
            {
                "role": "system",
                "content": (
                    "학습자료 핵심 개념 및 근거 페이지 분석 전문가입니다. "
                    "PDF에 명시된 내용과 실제 페이지 번호를 기준으로 분석합니다."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        schema=UnitContent.model_json_schema(),
        name="unit_content",
        max_tokens=1600
    )

    content = UnitContent.model_validate(result)

    if len(content.key_concepts) > 6:
        raise ValueError(
            "한 청크에서 핵심 개념이 6개를 초과했습니다."
        )

    available = set(available_pages)

    for concept in content.key_concepts:
        if not concept.name.strip():
            raise ValueError(
                "이름이 없는 개념이 추출되었습니다."
            )

        if not concept.pages:
            raise ValueError(
                f"근거 페이지가 없는 개념입니다: {concept.name}"
            )

        if not set(concept.pages).issubset(available):
            raise ValueError(
                f"개념 근거 페이지가 분석 범위를 벗어났습니다: "
                f"{concept.name}, {concept.pages}"
            )

    return content


def analyze_unit(groq, pages, unit, index):
    target_pages = [
        page
        for page in pages
        if (
            unit.start_page
            <= int(page["page"])
            <= unit.end_page
        )
    ]

    if not target_pages:
        raise ValueError(
            f"학습 단원 페이지가 없습니다: {unit.title}"
        )

    chunks = split_unit_pages(target_pages)

    if not chunks:
        raise ValueError(
            f"학습 단원에서 텍스트를 추출하지 못했습니다: {unit.title}"
        )

    concept_map = {}
    summaries = []

    for chunk in chunks:
        content = analyze_unit_chunk(
            groq,
            chunk,
            unit
        )

        if content.summary.strip():
            summaries.append(content.summary.strip())

        for concept in content.key_concepts:
            name = concept.name.strip()
            key = _normalized(name)

            if not key:
                continue

            valid_pages = {
                int(page)
                for page in concept.pages
                if (
                    unit.start_page
                    <= int(page)
                    <= unit.end_page
                )
            }

            if not valid_pages:
                continue

            if key not in concept_map:
                concept_map[key] = {
                    "name": name,
                    "pages": set()
                }

            concept_map[key]["pages"].update(
                valid_pages
            )

    concept_entries = []

    for concept_index, item in enumerate(
        concept_map.values(),
        start=1
    ):
        matched_pages = sorted(item["pages"])

        concept_entries.append({
            "id": f"unit_{index:02d}-{concept_index}",
            "name": item["name"],
            "page_start": matched_pages[0],
            "page_end": matched_pages[-1]
        })

    minutes = round(
        (unit.end_page - unit.start_page + 1)
        * 2.5
        * 1.2,
        1
    )

    return StudyUnit(
        difficulty="중",
        estimated_minutes=minutes,
        concepts=concept_entries,
        unit_id=f"unit_{index:02d}",
        parent_section=unit.parent_section,
        title=unit.title,
        start_page=unit.start_page,
        end_page=unit.end_page,
        key_concepts=[
            item["name"]
            for item in concept_map.values()
        ],
        summary=" ".join(summaries)
    )
