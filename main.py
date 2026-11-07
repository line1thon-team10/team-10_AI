
import json
from pathlib import Path

from services.pdf_analyzer import analyze_pdf


def main():
    result = analyze_pdf("data/demo/realtime_analysis.pdf")

    output_path = Path("test_result.json")

    output_path.write_text(
        json.dumps(
            result.model_dump(),
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(f"분석 결과 저장 완료: {output_path.resolve()}")


if __name__ == "__main__":
    main()
