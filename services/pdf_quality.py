
import re
from statistics import median


class PDFQualityError(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__(report["message"])


def evaluate_pdf_quality(
    pages,
    total_pages=None,
    min_chars=40,
    min_readable_ratio=0.35
):
    if not isinstance(pages, list):
        raise ValueError("pages는 배열이어야 합니다.")

    if total_pages is None:
        total_pages = len(pages)

    if type(total_pages) is not int or total_pages < 1:
        raise ValueError("total_pages는 양의 정수여야 합니다.")

    if not 0 <= min_readable_ratio <= 1 or min_chars < 1:
        raise ValueError("품질 검사 기준이 올바르지 않습니다.")

    by_page = {}

    for item in pages:
        if not isinstance(item, dict) or type(item.get("page")) is not int:
            raise ValueError("각 페이지에는 정수 page가 필요합니다.")

        number = item["page"]

        if not 1 <= number <= total_pages or number in by_page:
            raise ValueError("페이지 번호가 중복되거나 범위를 벗어났습니다.")

        content = item.get("text", "")

        if not isinstance(content, str):
            raise ValueError("페이지 text는 문자열이어야 합니다.")

        by_page[number] = content

    details = []

    for number in range(1, total_pages + 1):
        content = by_page.get(number, "")
        normalized = re.sub(r"\s+", "", content)
        meaningful = re.findall(r"[가-힣A-Za-z0-9]", normalized)
        replacement_count = content.count("\ufffd")
        noise_ratio = replacement_count / max(1, len(normalized))

        readable = (
            len(meaningful) >= min_chars
            and noise_ratio < 0.05
        )

        details.append({
            "page": number,
            "character_count": len(meaningful),
            "readable": readable,
            "replacement_ratio": round(noise_ratio, 4)
        })

    readable_count = sum(item["readable"] for item in details)
    readable_ratio = readable_count / total_pages
    total_characters = sum(item["character_count"] for item in details)

    status = (
        "pass"
        if readable_count > 0 and readable_ratio >= min_readable_ratio
        else "no_quiz"
    )

    message = (
        "텍스트 추출 품질 검사를 통과했습니다."
        if status == "pass"
        else "읽을 수 있는 페이지가 부족합니다. 선명한 PDF로 다시 업로드하거나 목차를 직접 입력해 주세요."
    )

    return {
        "status": status,
        "quiz_allowed": status == "pass",
        "reason": (
            None
            if status == "pass"
            else "insufficient_extractable_text"
        ),
        "message": message,
        "total_pages": total_pages,
        "readable_pages": readable_count,
        "readable_ratio": round(readable_ratio, 4),
        "total_characters": total_characters,
        "median_characters_per_page": median(
            item["character_count"] for item in details
        ),
        "pages": details,
        "assessment_method": "text_heuristic_not_ocr_confidence"
    }


def require_pdf_quality(pages, total_pages=None, **kwargs):
    report = evaluate_pdf_quality(
        pages,
        total_pages,
        **kwargs
    )

    if not report["quiz_allowed"]:
        raise PDFQualityError(report)

    return report
