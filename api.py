
import os
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
    get_public_bank_questions,
    select_unit_questions,
)
from services.quiz_grader import grade_quiz
from services.learning_metrics import calculate_learning_metrics
from services.backend_adapter import convert_grading_to_attempts


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
        questions = select_unit_questions(
            request.bank,
            request.unit_id,
            request.count,
            request.excluded_ids,
            request.allowed_pages
        )

        return {
            "status": "success",
            "questions": get_public_bank_questions(
                questions
            ),
            "total_questions": len(questions)
        }

    except Exception as error:
        _fail(error)


@app.post("/ai/quiz/grade")
def grade(request: GradeRequest):
    try:
        return grade_quiz(
            request.quiz,
            request.submission
        )

    except Exception as error:
        _fail(error)


@app.post("/ai/quiz/grade-and-metrics")
def grade_and_metrics(
    request: GradeAndMetricsRequest
):
    try:
        grading = grade_quiz(
            request.quiz,
            request.submission
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
            "grading": grading,
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
