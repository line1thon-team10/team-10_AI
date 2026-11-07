
import os
import json
import hashlib
from pathlib import Path

import fitz
import requests


def extract_pdf_text(file_path):
    path = Path(file_path)

    if not path.is_file():
        raise FileNotFoundError(file_path)

    cache_dir = Path("cache")
    cache_dir.mkdir(exist_ok=True)

    file_hash = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()

    cache_path = cache_dir / f"{file_hash}.json"

    if cache_path.exists():
        cached = json.loads(
            cache_path.read_text(encoding="utf-8")
        )

        return cached["total_pages"], cached["pages"]

    api_key = os.getenv("UPSTAGE_API_KEY")

    if not api_key:
        raise ValueError("UPSTAGE_API_KEY가 없습니다.")

    with fitz.open(path) as document:
        total_pages = len(document)

    with path.open("rb") as pdf:
        response = requests.post(
            "https://api.upstage.ai/v1/document-digitization",
            headers={
                "Authorization": f"Bearer {api_key}"
            },
            data={
                "model": "document-parse",
                "output_formats": '["markdown"]'
            },
            files={
                "document": (
                    path.name,
                    pdf,
                    "application/pdf"
                )
            },
            timeout=180
        )

    response.raise_for_status()
    result = response.json()

    page_contents = {}

    for element in result.get("elements", []):
        page_number = element.get("page")

        if page_number is None:
            continue

        page_number = int(page_number)
        content = element.get("content", {})

        if isinstance(content, dict):
            text = content.get("markdown", "")
        else:
            text = str(content)

        if text:
            page_contents.setdefault(
                page_number, []
            ).append(text)

    if not page_contents:
        raise ValueError("PDF 파싱 결과가 비어 있습니다.")

    pages = [
        {
            "page": number,
            "text": "\n".join(
                page_contents.get(number, [])
            )
        }
        for number in range(1, total_pages + 1)
    ]

    cache_path.write_text(
        json.dumps(
            {
                "total_pages": total_pages,
                "pages": pages
            },
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    return total_pages, pages
