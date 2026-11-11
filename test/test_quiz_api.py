
import json
import urllib.request
import urllib.error
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"
PDF_PATH = "data/demo/artificial_intelligence.pdf"
SUBJECT = "AI"

OUTPUT_DIR = Path("result/phase7")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def post_json(path, payload):
    body = json.dumps(
        payload,
        ensure_ascii=False
    ).encode("utf-8")

    request = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=1200
        ) as response:
            result = json.load(response)

            print("HTTP 상태:", response.status)

            return result

    except urllib.error.HTTPError as error:
        raw = error.read().decode(
            "utf-8",
            errors="replace"
        )

        print("HTTP 오류:", error.code)
        print("서버 응답:")

        try:
            detail = json.loads(raw)

            print(
                json.dumps(
                    detail,
                    ensure_ascii=False,
                    indent=2
                )
            )

        except json.JSONDecodeError:
            print(raw)

        raise SystemExit(1)

    except urllib.error.URLError as error:
        print("서버 연결 오류:", error.reason)
        raise SystemExit(1)


def main():
    analysis_path = (
        OUTPUT_DIR / "api_analysis.json"
    )

    if not analysis_path.exists():
        raise FileNotFoundError(
            f"분석 결과 파일이 없습니다: {analysis_path}"
        )

    analysis = json.loads(
        analysis_path.read_text(
            encoding="utf-8"
        )
    )

    if "analysis" in analysis:
        analysis = analysis["analysis"]

    print("PDF 경로:", PDF_PATH)
    print("과목 코드:", SUBJECT)
    print("분석 단원 수:", len(analysis.get("units", [])))

    for unit in analysis.get("units", []):
        print(
            "단원:",
            unit.get("id"),
            unit.get("name"),
            "페이지:",
            unit.get("page_start"),
            "~",
            unit.get("page_end"),
            "개념 수:",
            len(unit.get("concepts", []))
        )

    print("[1/2] 문제은행 생성")

    bank = post_json(
        "/ai/quiz/generate",
        {
            "pdf_path": PDF_PATH,
            "analysis": analysis,
            "subject": SUBJECT
        }
    )

    bank_path = (
        OUTPUT_DIR / "api_question_bank.json"
    )

    bank_path.write_text(
        json.dumps(
            bank,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("저장 완료:", bank_path)

    print("[2/2] 문제은행 결과 확인")

    for unit in bank.get("units", []):
        print(
            unit.get("unit_id"),
            unit.get("status"),
            len(unit.get("questions", []))
        )

    print("문제은행 생성 테스트 완료")


if __name__ == "__main__":
    main()
