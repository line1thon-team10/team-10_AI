
import json

from pydantic import BaseModel, ConfigDict


MAX_TEXT_CHARS = 2000


class UnitContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_concepts: list[str]
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


def split_unit_pages(pages):
    chunks = []
    current = []
    current_length = 0

    for page in pages:
        text = page["text"]

        if len(text) > MAX_TEXT_CHARS:
            parts = [
                text[i:i + MAX_TEXT_CHARS]
                for i in range(0, len(text), MAX_TEXT_CHARS)
            ]

            for part in parts:
                if current:
                    chunks.append(current)
                    current = []
                    current_length = 0

                chunks.append([
                    {
                        "page": page["page"],
                        "text": part
                    }
                ])

            continue

        if current and current_length + len(text) > MAX_TEXT_CHARS:
            chunks.append(current)
            current = []
            current_length = 0

        current.append(page)
        current_length += len(text)

    if current:
        chunks.append(current)

    return chunks


def analyze_unit_chunk(groq, chunk, unit):
    prompt = f"""
다음 학습 단원의 PDF 내용을 분석하세요.

학습 단원:
{unit.title}

상위 목차:
{unit.parent_section}

학습 범위:
{unit.start_page}~{unit.end_page}페이지

현재 분석 내용:
{json.dumps(chunk, ensure_ascii=False)}

규칙:
1. 실제 제공된 PDF 내용만 사용하세요.
2. 핵심 개념은 최대 6개 추출하세요.
3. 요약은 한국어 2~3문장으로 작성하세요.
4. 현재 내용에 없는 개념을 만들어내지 마세요.
5. 단원 이름이나 페이지 범위를 새로 생성하지 마세요.
6. 같은 개념을 중복 작성하지 마세요.
"""

    result = groq.generate(
        messages=[
            {
                "role": "system",
                "content": "학습자료 핵심 개념 및 요약 분석 전문가입니다."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        schema=UnitContent.model_json_schema(),
        name="unit_content",
        max_tokens=900
    )

    return UnitContent.model_validate(result)


def analyze_unit(groq, pages, unit, index):
    target_pages = [
        page
        for page in pages
        if unit.start_page <= page["page"] <= unit.end_page
    ]

    if not target_pages:
        raise ValueError(
            f"학습 단원 페이지가 없습니다: {unit.title}"
        )

    chunks = split_unit_pages(target_pages)

    concepts = []
    summaries = []

    for chunk in chunks:
        content = analyze_unit_chunk(
            groq,
            chunk,
            unit
        )

        concepts.extend(content.key_concepts)
        summaries.append(content.summary)

    concepts = list(dict.fromkeys(concepts))

    return StudyUnit(
        unit_id=f"unit_{index:02d}",
        parent_section=unit.parent_section,
        title=unit.title,
        start_page=unit.start_page,
        end_page=unit.end_page,
        key_concepts=concepts,
        summary=" ".join(summaries)
    )
