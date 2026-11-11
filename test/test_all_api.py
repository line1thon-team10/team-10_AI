
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from services.backend_adapter import convert_question

BASE_URL = os.getenv("AI_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
OUTPUT_DIR = Path("result/phase7")
PDF_PATH = Path("data/demo/artificial_intelligence.pdf")
ANALYSIS_PATH = OUTPUT_DIR / "api_analysis.json"
BANK_PATH = OUTPUT_DIR / "api_question_bank.json"
SEED_PATH = Path("seed_quiz.json")

RESULTS = []


def request_json(method, path, payload=None, timeout=120):
    headers = {}

    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    else:
        body = None

    request = urllib.request.Request(
        BASE_URL + path,
        data=body,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)

    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")

        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = {"detail": raw}

        return error.code, detail


def check(name, callback):
    print(f"\n[검증] {name}")

    try:
        detail = callback()
        RESULTS.append({
            "name": name,
            "status": "PASS",
            "detail": detail
        })
        print("결과: PASS")
        print("상세:", detail)

    except Exception as error:
        RESULTS.append({
            "name": name,
            "status": "FAIL",
            "detail": str(error)
        })
        print("결과: FAIL")
        print("오류:", error)


def assert_status(status, expected=200):
    assert status == expected, f"HTTP {status}, 예상 {expected}"


def load_json(path):
    if not path.exists():
        raise FileNotFoundError(f"파일이 없습니다: {path}")

    return json.loads(path.read_text(encoding="utf-8"))


def save_json(name, data):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return path


def get_analysis():
    analysis = load_json(ANALYSIS_PATH)
    return analysis.get("analysis", analysis)


def get_bank():
    return load_json(BANK_PATH)


def build_grading_data():
    seed = load_json(SEED_PATH)

    questions = [
        question
        for question in seed["questions"]
        if question["type"] in {"객관식", "OX"}
    ][:5]

    assert len(questions) == 5

    quiz = {
        "status": "success",
        "date": "2026-11-09",
        "document_title": "전체 API 재검증",
        "questions": [
            convert_question(question)
            for question in questions
        ]
    }

    answers = []

    for index, question in enumerate(questions):
        if index < 2:
            answer = question["answer"]
        elif question["type"] == "OX":
            answer = "X" if question["answer"] == "O" else "O"
        else:
            answer = "__wrong_answer__"

        answers.append({
            "question_id": question["id"],
            "answer": answer,
            "confidence": "확실" if index != 1 else "애매"
        })

    submission = {
        "date": "2026-11-09",
        "answers": answers
    }

    return quiz, submission, seed


def test_health():
    status, data = request_json("GET", "/health")
    assert_status(status)
    assert data.get("status") == "ok"
    return data


def test_analyze_contract():
    status, data = request_json(
        "POST",
        "/ai/analyze",
        {
            "subject": "AI"
        }
    )

    assert_status(status, 422)
    assert isinstance(data.get("detail"), list)
    return "필수 PDF 파일 누락 시 HTTP 422 확인"


def test_generate_contract():
    status, data = request_json(
        "POST",
        "/ai/quiz/generate",
        {
            "pdf_path": "../invalid.pdf",
            "analysis": {},
            "subject": "AI"
        }
    )

    assert_status(status, 422)
    return "허용되지 않은 PDF 경로 HTTP 422 확인"


def test_generate_result():
    bank = get_bank()

    assert bank.get("status") == "success"
    units = bank.get("units", [])
    assert units

    total = 0

    for unit in units:
        assert unit.get("status") == "success"
        questions = unit.get("questions", [])
        assert len(questions) == 10
        total += len(questions)

    return f"기존 HTTP 생성 결과 검증: {len(units)}개 단원, {total}문제"


def test_select():
    bank = get_bank()
    units = bank["units"]
    unit_id = units[0]["unit_id"]

    status, data = request_json(
        "POST",
        "/ai/quiz/select",
        {
            "bank": bank,
            "unit_id": unit_id,
            "count": 5,
            "excluded_ids": []
        }
    )

    assert_status(status)
    assert data.get("status") == "success"
    assert data.get("total_questions") == 5

    questions = data.get("questions", [])
    assert len(questions) == 5

    forbidden = {
        "answer",
        "correct_answer",
        "correct_answers",
        "answer_key",
        "is_correct",
        "reference_answer",
        "model_answer"
    }

    for question in questions:
        assert isinstance(question, dict)
        assert question.get("id")
        assert not forbidden.intersection(question.keys()), (
            f"정답 관련 필드 노출: {question.get('id')}"
        )

    save_json("api_selected_questions.json", data)
    return f"{unit_id}: 5문제 선택, 정답 필드 비노출"


def test_grade():
    quiz, submission, _ = build_grading_data()

    status, data = request_json(
        "POST",
        "/ai/quiz/grade",
        {
            "quiz": quiz,
            "submission": submission
        },
        timeout=1200
    )

    assert_status(status)
    assert data.get("total_questions") == 5

    save_json("api_grading.json", data)
    return "5문제 HTTP 채점 완료"


def test_grade_and_metrics():
    quiz, submission, seed = build_grading_data()

    status, data = request_json(
        "POST",
        "/ai/quiz/grade-and-metrics",
        {
            "quiz": quiz,
            "submission": submission,
            "learning_data": seed,
            "done_pages": {
                "DS": 88,
                "OS": 67,
                "NW": 36
            }
        },
        timeout=1200
    )

    assert_status(status)
    assert data.get("status") == "success"
    assert data.get("grading", {}).get("total_questions") == 5
    assert len(data.get("attempts", [])) == 5
    assert data.get("metrics", {}).get("units")

    save_json("api_grade_and_metrics.json", data)
    return "채점 5문제, 풀이 기록 5개, 학습 지표 생성"


def test_metrics():
    seed = load_json(SEED_PATH)

    status, data = request_json(
        "POST",
        "/ai/learning/metrics",
        {
            "data": seed,
            "done_pages": {
                "DS": 88,
                "OS": 67,
                "NW": 36
            }
        }
    )

    assert_status(status)
    assert data.get("units")
    assert data.get("readiness")

    save_json("api_learning_metrics.json", data)
    return f"학습 단원 {len(data['units'])}개"


def test_tutor_ask():
    status, data = request_json(
        "POST",
        "/ai/tutor/ask",
        {
            "question": "지도학습과 비지도학습의 차이를 설명해줘.",
            "history": [],
            "document_pages": [
                {
                    "page": 1,
                    "text": "지도학습은 입력 데이터와 정답 레이블을 이용해 학습한다. 비지도학습은 정답 레이블 없이 데이터의 패턴을 학습한다."
                }
            ]
        },
        timeout=1200
    )

    assert_status(status)
    assert isinstance(data, dict)
    assert data

    save_json("api_tutor_ask.json", data)
    return f"튜터 응답 필드: {list(data.keys())}"


def test_tutor_simplify():
    status, data = request_json(
        "POST",
        "/ai/tutor/simplify",
        {
            "question": "지도학습이란 무엇인가?",
            "answer": "지도학습은 정답 레이블이 포함된 데이터로 입력과 출력의 관계를 학습하는 머신러닝 방식입니다.",
            "pages": [1],
            "document_pages": [
                {
                    "page": 1,
                    "text": "지도학습은 정답 레이블이 있는 데이터를 사용해 모델을 학습시키는 방법이다."
                }
            ]
        },
        timeout=1200
    )

    assert_status(status)
    assert isinstance(data, dict)
    assert data

    save_json("api_tutor_simplify.json", data)
    return f"쉬운 설명 응답 필드: {list(data.keys())}"


def main():
    print("=" * 55)
    print("피뢰침 AI 전체 API 재검증")
    print("서버:", BASE_URL)
    print("=" * 55)

    check("1. 서버 상태 /health", test_health)
    check("2. PDF 분석 입력 검증 /ai/analyze", test_analyze_contract)
    check("3. 문제은행 생성 입력 검증", test_generate_contract)
    check("4. 기존 문제은행 생성 결과 검증", test_generate_result)
    check("5. 문제 선택 /ai/quiz/select", test_select)
    check("6. 퀴즈 채점 /ai/quiz/grade", test_grade)
    check("7. 채점 및 학습 지표 /ai/quiz/grade-and-metrics", test_grade_and_metrics)
    check("8. 학습 지표 /ai/learning/metrics", test_metrics)
    check("9. AI 튜터 질문 /ai/tutor/ask", test_tutor_ask)
    check("10. AI 튜터 쉬운 설명 /ai/tutor/simplify", test_tutor_simplify)

    passed = sum(item["status"] == "PASS" for item in RESULTS)
    failed = len(RESULTS) - passed

    summary = {
        "status": "success" if failed == 0 else "failed",
        "total_tests": len(RESULTS),
        "passed": passed,
        "failed": failed,
        "results": RESULTS
    }

    path = save_json("api_full_test_summary.json", summary)

    print("\n" + "=" * 55)
    print("전체 API 재검증 결과")
    print(f"PASS: {passed}/{len(RESULTS)}")
    print(f"FAIL: {failed}/{len(RESULTS)}")
    print("결과 저장:", path)
    print("=" * 55)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
