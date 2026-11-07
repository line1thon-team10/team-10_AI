
from pydantic import BaseModel, ConfigDict

from dotenv import load_dotenv

from services.pdf_parser import extract_pdf_text
from services.groq_client import GroqService
from services.document_structure import (
    extract_metadata,
    build_document_structure
)
from services.unit_analyzer import (
    StudyUnit,
    analyze_unit
)
from services.analysis_validator import (
    validate_structure,
    validate_analysis
)


load_dotenv()


class PDFAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_title: str
    total_pages: int
    units: list[StudyUnit]


def analyze_pdf(file_path):
    print("PDF 파싱 중...")

    total_pages, pages = extract_pdf_text(file_path)

    if not any(page["text"] for page in pages):
        raise ValueError(
            "PDF에서 텍스트를 추출하지 못했습니다."
        )

    groq = GroqService()

    print("문서 제목과 목차 분석 중...")

    metadata = extract_metadata(
        groq,
        pages
    )

    print("전체 학습 단원 구조 분석 중...")

    structure = build_document_structure(
        groq,
        pages,
        metadata
    )

    structure = validate_structure(
        structure,
        total_pages
    )

    print(
        f"총 {len(structure.units)}개 학습 단원 발견"
    )

    analyzed_units = []

    for index, unit in enumerate(
        structure.units,
        start=1
    ):
        print(
            f"[{index}/{len(structure.units)}] "
            f"{unit.title} 분석 중..."
        )

        analyzed_unit = analyze_unit(
            groq,
            pages,
            unit,
            index
        )

        analyzed_units.append(analyzed_unit)

    validate_analysis(
        analyzed_units,
        total_pages
    )

    return PDFAnalysis(
        document_title=metadata.document_title,
        total_pages=total_pages,
        units=analyzed_units
    )
