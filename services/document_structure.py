
import json
import re

from pydantic import BaseModel, ConfigDict

from services.groq_client import RequestTooLargeError


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_title: str
    section_titles: list[str]


class UnitBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    parent_section: str
    start_page: int
    end_page: int


class DocumentStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    units: list[UnitBoundary]
    excluded_pages: list[int]


def get_page_outline(page):
    lines = [
        line.strip()
        for line in page["text"].splitlines()
        if line.strip()
    ]

    headings = []

    for line in lines:
        clean = re.sub(
            r"^[#*\-\s]+",
            "",
            line
        ).strip()

        if not clean or len(clean) > 70:
            continue

        if line.startswith("#") or re.match(
            r"^\d+(\.\d+)*[.)]?\s+",
            clean
        ):
            headings.append(clean[:55])

    return {
        "page": page["page"],
        "headings": headings[:2],
        "preview": " ".join(lines)[:70]
    }


def extract_metadata(groq, pages):
    selected = pages[:3]

    prompt = f"""
PDF 문서의 제목과 원본 목차를 추출하세요.

{json.dumps(selected, ensure_ascii=False)}

규칙:
1. 문서 제목을 장 번호 하나로 작성하지 마세요.
2. 실제 문서 제목을 사용하세요.
3. 원본 목차의 대단원 제목을 추출하세요.
4. 존재하지 않는 목차를 만들지 마세요.
"""

    result = groq.generate(
        messages=[
            {
                "role": "system",
                "content": "PDF 제목과 목차 분석 전문가입니다."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        schema=DocumentMetadata.model_json_schema(),
        name="document_metadata",
        max_tokens=800
    )

    return DocumentMetadata.model_validate(result)


def analyze_outline_chunk(groq, outlines, metadata):
    prompt = f"""
다음 PDF 페이지들의 학습 단원 구조를 분석하세요.

문서 제목:
{metadata.document_title}

원본 목차:
{json.dumps(metadata.section_titles, ensure_ascii=False)}

페이지 정보:
{json.dumps(outlines, ensure_ascii=False)}

규칙:
1. 원본 목차를 우선하세요.
2. 실제 페이지 내용을 기준으로 학습 단원을 구분하세요.
3. 단원 제목은 한국어로 작성하세요.
4. 임의의 장 번호를 만들지 마세요.
5. 동일한 주제는 가능한 하나의 단원으로 묶으세요.
6. 모든 페이지를 단원 또는 제외 페이지로 분류하세요.
7. 단원 페이지가 겹치면 안 됩니다.
8. 단원은 페이지 순서대로 반환하세요.
9. 표지와 목차 페이지는 제외할 수 있습니다.
10. parent_section은 원본 대단원 제목을 사용하세요.
"""

    result = groq.generate(
        messages=[
            {
                "role": "system",
                "content": "학습 단원 구조 분석 전문가입니다."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        schema=DocumentStructure.model_json_schema(),
        name="outline_chunk",
        max_tokens=1400
    )

    return DocumentStructure.model_validate(result)


def split_outlines(outlines, size):
    return [
        outlines[i:i + size]
        for i in range(0, len(outlines), size)
    ]


def analyze_with_fallback(groq, outlines, metadata):
    try:
        return analyze_outline_chunk(
            groq,
            outlines,
            metadata
        )

    except RequestTooLargeError:
        if len(outlines) <= 3:
            raise

        middle = len(outlines) // 2

        print(
            f"{outlines[0]['page']}~"
            f"{outlines[-1]['page']}페이지 재분할"
        )

        left = analyze_with_fallback(
            groq,
            outlines[:middle],
            metadata
        )

        right = analyze_with_fallback(
            groq,
            outlines[middle:],
            metadata
        )

        return DocumentStructure(
            units=left.units + right.units,
            excluded_pages=(
                left.excluded_pages
                + right.excluded_pages
            )
        )


def merge_boundaries(units):
    units = sorted(
        units,
        key=lambda unit: unit.start_page
    )

    merged = []

    for unit in units:
        if not merged:
            merged.append(unit)
            continue

        previous = merged[-1]

        if (
            previous.title == unit.title
            and previous.parent_section == unit.parent_section
            and previous.end_page + 1 == unit.start_page
        ):
            previous.end_page = unit.end_page
        else:
            merged.append(unit)

    return merged


def build_document_structure(groq, pages, metadata):
    outlines = [
        get_page_outline(page)
        for page in pages
    ]

    chunks = split_outlines(outlines, 20)

    print(
        f"문서 구조를 {len(chunks)}개 구간으로 분석합니다."
    )

    all_units = []
    all_excluded = []

    for index, chunk in enumerate(chunks, start=1):
        print(
            f"[구조 {index}/{len(chunks)}] "
            f"{chunk[0]['page']}~"
            f"{chunk[-1]['page']}페이지"
        )

        result = analyze_with_fallback(
            groq,
            chunk,
            metadata
        )

        all_units.extend(result.units)
        all_excluded.extend(result.excluded_pages)

    return DocumentStructure(
        units=merge_boundaries(all_units),
        excluded_pages=sorted(set(all_excluded))
    )
