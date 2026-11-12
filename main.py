
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from services.ai_tutor import answer_tutor, simplify_tutor
from services.analysis_contract import convert_analysis_for_backend
from services.pdf_analyzer import analyze_pdf
from services.pdf_quality import PDFQualityError
from services.quiz_bank import (
    generate_unit_question_bank,
    select_unit_questions,
)
from services.quiz_grader import grade_quiz
from services.learning_metrics import calculate_learning_metrics
from services.backend_adapter import (
    convert_question,
    get_public_question,
    convert_grading_response,
    convert_grading_to_attempts,
)


app = FastAPI(
    title="피뢰침 AI API",
    version="1.0.0"
)


class GenerateRequest(BaseModel):
    pdf_path: str
    analysis: dict[str, Any]
    subject: str


class SelectRequest(BaseModel):
    bank: dict[str, Any]
    unit_id: str
    count: int = Field(default=5, ge=1, le=10)
    excluded_ids: list[str] = Field(default_factory=list)
    allowed_pages: list[int] | None = None


class GradeRequest(BaseModel):
    quiz: dict[str, Any]
    submission: dict[str, Any]


class GradeAndMetricsRequest(BaseModel):
    quiz: dict[str, Any]
    submission: dict[str, Any]
    learning_data: dict[str, Any]
    done_pages: dict[str, int] | None = None


class MetricsRequest(BaseModel):
    data: dict[str, Any]
    done_pages: dict[str, int] | None = None


class TutorAskRequest(BaseModel):
    question: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    document_pages: list[dict[str, Any]]


class TutorSimplifyRequest(BaseModel):
    question: str
    answer: str
    pages: list[int]
    document_pages: list[dict[str, Any]]


def _fail(error: Exception):
    if isinstance(error, PDFQualityError):
        raise HTTPException(
            status_code=422,
            detail=error.report
        ) from error

    if isinstance(error, (ValueError, KeyError, TypeError)):
        raise HTTPException(
            status_code=422,
            detail=str(error)
        ) from error

    raise error


def _safe_pdf_path(value: str) -> str:
    path = Path(value).resolve()
    root = Path(
        os.getenv("AI_PDF_ROOT", "data")
    ).resolve()

    if (
        root not in path.parents
        or not path.is_file()
        or path.suffix.lower() != ".pdf"
    ):
        raise ValueError(
            "pdf_path는 AI_PDF_ROOT 내부에 존재하는 PDF 파일이어야 합니다."
        )

    return str(path)


def _normalized_unit_id(value):
    value = str(value).strip()
    match = re.fullmatch(r"unit_0*(\d+)", value)

    if match:
        return f"AI{int(match.group(1))}"

    return value


def _internal_question_id(question):
    return question.get("id", question.get("question_id"))


def _convert_bank_question(question):
    if "question_id" in question and "prompt" in question:
        return dict(question)

    return convert_question(question)


def _select_questions(bank, unit_id, count, excluded_ids, allowed_pages):
    normalized_unit = _normalized_unit_id(unit_id)

    unit = next(
        (
            item
            for item in bank.get("units", [])
            if _normalized_unit_id(item.get("unit_id", "")) == normalized_unit
        ),
        None
    )

    if unit is None:
        raise ValueError(f"단원을 찾을 수 없습니다: {unit_id}")

    if unit.get("status") != "success":
        return []

    excluded = set(str(value) for value in excluded_ids)
    allowed = set(allowed_pages) if allowed_pages is not None else None

    selected = []

    for question in unit.get("questions", []):
        converted = _convert_bank_question(question)

        old_id = str(_internal_question_id(question))
        new_id = converted["question_id"]

        if old_id in excluded or new_id in excluded:
            continue

        if allowed is not None:
            sources = converted.get("sources", [])
            source_pages = {
                page
                for source in sources
                for page in range(
                    source["start_page"],
                    source["end_page"] + 1
                )
            }

            if not source_pages.intersection(allowed):
                continue

        selected.append(question)

        if len(selected) >= count:
            break

    return selected


def _prepare_grading(quiz, submission):
    questions = quiz.get("questions")

    if not isinstance(questions, list) or not questions:
        raise ValueError("채점할 문제가 없습니다.")

    answers = submission.get("answers")

    if not isinstance(answers, list):
        raise ValueError("답안은 배열이어야 합니다.")

    internal_questions = []
    question_lookup = {}
    id_lookup = {}
    converted_lookup = {}

    for question in questions:
        old_id = _internal_question_id(question)

        if old_id is None:
            raise ValueError("문제 ID가 없습니다.")

        if "question_id" in question and "prompt" in question:
            if "answer" not in question:
                raise ValueError(
                    "채점에는 정답이 포함된 내부 문제 데이터가 필요합니다."
                )

            converted = dict(question)
            question_type = converted.get("type")
            raw_choices = converted.get("choices", [])

            if question_type == "choice":
                choices = [
                    item["text"]
                    for item in raw_choices
                ]

                answer_id = converted["answer"]
                answer_text = next(
                    (
                        item["text"]
                        for item in raw_choices
                        if item["id"] == answer_id
                    ),
                    None
                )

                if answer_text is None:
                    raise ValueError("객관식 정답 ID가 올바르지 않습니다.")

                internal_type = "multiple_choice"
            elif question_type == "short":
                choices = []
                answer_text = converted["answer"]
                internal_type = "short_answer"
            elif question_type == "essay":
                choices = []
                answer_text = converted["answer"]
                internal_type = "essay"
            else:
                raise ValueError("지원하지 않는 문제 유형입니다.")

            difficulty_map = {
                "low": "easy",
                "mid": "medium",
                "high": "hard"
            }

            sources = converted.get("sources", [])

            if not sources:
                raise ValueError("채점에 필요한 근거 자료가 없습니다.")

            internal = {
                "id": old_id,
                "type": internal_type,
                "difficulty": difficulty_map.get(
                    converted.get("difficulty"),
                    "easy"
                ),
                "question": converted["prompt"],
                "options": choices,
                "answer": answer_text,
                "explanation": converted.get("explanation", ""),
                "source_page": sources[0]["start_page"],
                "source_text": sources[0]["quote"],
                "keywords": converted.get("keywords", [])
            }

            if "rubric" in question:
                internal["rubric"] = question["rubric"]
        else:
            internal = dict(question)
            converted = convert_question(question)

        new_id = converted["question_id"]

        if new_id in id_lookup:
            raise ValueError(f"중복 문제 ID: {new_id}")

        id_lookup[new_id] = old_id
        id_lookup[str(old_id)] = old_id

        question_lookup[old_id] = question
        converted_lookup[old_id] = converted
        internal_questions.append(internal)

    internal_answers = []
    submitted_ids = set()

    for item in answers:
        if not isinstance(item, dict):
            raise ValueError("답안 형식이 올바르지 않습니다.")

        submitted_id = str(item.get("question_id", ""))
        answer = item.get("answer")

        if submitted_id not in id_lookup:
            raise ValueError(
                f"존재하지 않는 문제 ID: {submitted_id}"
            )

        if not isinstance(answer, str):
            raise ValueError("답안은 문자열이어야 합니다.")

        old_id = id_lookup[submitted_id]

        if old_id in submitted_ids:
            raise ValueError("중복 제출된 답안이 있습니다.")

        submitted_ids.add(old_id)

        question = next(
            q for q in internal_questions
            if q["id"] == old_id
        )

        converted = converted_lookup[old_id]

        if converted["type"] == "choice":
            choice_lookup = {
                item["id"]: item["text"]
                for item in converted["choices"]
            }

            if answer in choice_lookup:
                answer = choice_lookup[answer]

        internal_item = {
            "question_id": old_id,
            "answer": answer
        }

        if "confidence" in item:
            internal_item["confidence"] = item["confidence"]

        internal_answers.append(internal_item)

    internal_quiz = {
        **quiz,
        "status": "success",
        "questions": internal_questions
    }

    internal_submission = {
        **submission,
        "answers": internal_answers
    }

    return (
        internal_quiz,
        internal_submission,
        question_lookup,
        converted_lookup
    )


def _convert_grading(grading, question_lookup, converted_lookup):
    response = convert_grading_response(
        grading,
        question_lookup
    )

    for index, result in enumerate(grading["results"]):
        old_id = result["question_id"]
        converted = converted_lookup[old_id]
        output = response["results"][index]

        output["question_id"] = converted["question_id"]

        if converted["type"] == "choice":
            correct_text = result["correct_answer"]

            matching = [
                choice["id"]
                for choice in converted["choices"]
                if choice["text"] == correct_text
            ]

            if len(matching) != 1:
                raise ValueError(
                    "객관식 정답 ID를 확인할 수 없습니다."
                )

            output["correct_answer"] = matching[0]

        if converted["type"] == "essay":
            output["essay_score"] = result["score_100"]
            output["is_correct"] = result["score_100"] >= 85
            output["feedback"] = result.get("feedback", "")
            output["got_points"] = result.get("strengths", [])
            output["missing_points"] = result.get(
                "missing_points",
                []
            )

    return response


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


@app.post("/ai/analyze")
async def analyze(
    file: UploadFile = File(...),
    subject: str = Form(...)
):
    if (
        not file.filename
        or Path(file.filename).suffix.lower() != ".pdf"
    ):
        raise HTTPException(
            status_code=422,
            detail="PDF 파일만 업로드할 수 있습니다."
        )

    max_size = (
        int(os.getenv("AI_MAX_UPLOAD_MB", "25"))
        * 1024
        * 1024
    )

    tmp = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".pdf",
            delete=False
        ) as target:
            tmp = target.name
            size = 0

            while chunk := await file.read(1024 * 1024):
                size += len(chunk)

                if size > max_size:
                    raise HTTPException(
                        status_code=413,
                        detail="PDF 업로드 크기 제한을 초과했습니다."
                    )

                target.write(chunk)

        analysis = analyze_pdf(tmp)

        backend = convert_analysis_for_backend(
            analysis,
            subject
        )

        return {
            "status": "success",
            "analysis": backend
        }

    except HTTPException:
        raise

    except Exception as error:
        _fail(error)

    finally:
        await file.close()

        if tmp:
            Path(tmp).unlink(missing_ok=True)


@app.post("/ai/quiz/generate")
def generate(request: GenerateRequest):
    try:
        path = _safe_pdf_path(
            request.pdf_path
        )

        bank = generate_unit_question_bank(
            path,
            request.analysis,
            subject=request.subject
        )

        return bank

    except Exception as error:
        _fail(error)


@app.post("/ai/quiz/select")
def select(request: SelectRequest):
    try:
        questions = _select_questions(
            request.bank,
            request.unit_id,
            request.count,
            request.excluded_ids,
            request.allowed_pages
        )

        converted = [
            get_public_question(
                _convert_bank_question(question)
            )
            for question in questions
        ]

        return {
            "status": "success",
            "questions": converted,
            "total_questions": len(converted)
        }

    except Exception as error:
        _fail(error)


@app.post("/ai/quiz/grade")
def grade(request: GradeRequest):
    try:
        (
            internal_quiz,
            internal_submission,
            question_lookup,
            converted_lookup
        ) = _prepare_grading(
            request.quiz,
            request.submission
        )

        grading = grade_quiz(
            internal_quiz,
            internal_submission
        )

        return _convert_grading(
            grading,
            question_lookup,
            converted_lookup
        )

    except Exception as error:
        _fail(error)


@app.post("/ai/quiz/grade-and-metrics")
def grade_and_metrics(
    request: GradeAndMetricsRequest
):
    try:
        (
            internal_quiz,
            internal_submission,
            question_lookup,
            converted_lookup
        ) = _prepare_grading(
            request.quiz,
            request.submission
        )

        grading = grade_quiz(
            internal_quiz,
            internal_submission
        )

        attempts = convert_grading_to_attempts(
            grading
        )

        known_ids = {
            question["id"]
            for question in request.learning_data["questions"]
        }

        unknown = [
            attempt["question"]
            for attempt in attempts
            if attempt["question"] not in known_ids
        ]

        if unknown:
            raise ValueError(
                f"학습 데이터에 없는 문제 ID: {unknown}"
            )

        data = dict(request.learning_data)

        data["attempts"] = (
            list(data.get("attempts", []))
            + attempts
        )

        metrics = calculate_learning_metrics(
            data,
            request.done_pages
        )

        return {
            "status": "success",
            "grading": _convert_grading(
                grading,
                question_lookup,
                converted_lookup
            ),
            "attempts": attempts,
            "metrics": metrics
        }

    except Exception as error:
        _fail(error)


@app.post("/ai/learning/metrics")
def metrics(request: MetricsRequest):
    try:
        return calculate_learning_metrics(
            request.data,
            request.done_pages
        )

    except Exception as error:
        _fail(error)


@app.post("/ai/tutor/ask")
def tutor_ask(request: TutorAskRequest):
    try:
        return answer_tutor(
            request.question,
            request.history,
            request.document_pages
        )

    except Exception as error:
        _fail(error)


@app.post("/ai/tutor/simplify")
def tutor_simplify(
    request: TutorSimplifyRequest
):
    try:
        return simplify_tutor(
            request.question,
            request.answer,
            request.pages,
            request.document_pages
        )

    except Exception as error:
        _fail(error)
