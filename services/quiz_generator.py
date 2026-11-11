
import logging
import re
from collections import Counter
from datetime import date

from services.groq_client import GroqService
from services.pdf_parser import extract_pdf_text
from services.quiz_validator import validate_quiz
from services.quiz_quality_checker import check_quiz_quality


logger = logging.getLogger(__name__)


QUESTION_PROPERTIES = {
    "id": {"type": "integer"},
    "type": {
        "type": "string",
        "enum": [
            "multiple_choice",
            "short_answer",
            "essay"
        ]
    },
    "difficulty": {
        "type": "string",
        "enum": ["easy", "medium", "hard"]
    },
    "question": {"type": "string"},
    "options": {
        "type": "array",
        "items": {"type": "string"}
    },
    "answer": {"type": "string"},
    "explanation": {"type": "string"},
    "evidence_id": {"type": "integer"},
    "keywords": {
        "type": "array",
        "items": {"type": "string"}
    }
}


BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": QUESTION_PROPERTIES,
                "required": list(
                    QUESTION_PROPERTIES.keys()
                ),
                "additionalProperties": False
            }
        }
    },
    "required": ["questions"],
    "additionalProperties": False
}


QUESTION_PLAN = [
    (1, "multiple_choice"),
    (2, "multiple_choice"),
    (3, "multiple_choice"),
    (4, "multiple_choice"),
    (5, "multiple_choice"),
    (6, "multiple_choice"),
    (7, "short_answer"),
    (8, "short_answer"),
    (9, "essay"),
    (10, "essay")
]


def get_daily_tasks(study_plan, study_date):
    for day in study_plan["schedule"]:
        if day["date"] == study_date:
            return day["tasks"]

    return []


def get_study_pages(tasks):
    page_numbers = set()

    for task in tasks:
        start = task["start_page"]
        end = task["end_page"]

        if start > end:
            raise ValueError(
                "학습 페이지 범위가 잘못되었습니다."
            )

        page_numbers.update(
            range(start, end + 1)
        )

    return sorted(page_numbers)


def split_text(text, max_length=450):
    text = text.strip()

    if not text:
        return []

    parts = re.split(
        r"(?<=[.!?。])\s+|\n+",
        text
    )

    chunks = []
    current = ""

    for part in parts:
        part = part.strip()

        if not part:
            continue

        if len(part) > max_length:
            if current:
                chunks.append(current)
                current = ""

            for start in range(
                0,
                len(part),
                max_length
            ):
                chunks.append(
                    part[start:start + max_length]
                )

            continue

        candidate = f"{current} {part}".strip()

        if current and len(candidate) > max_length:
            chunks.append(current)
            current = part
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks


def build_evidence(pdf_pages, page_numbers):
    evidence = []
    evidence_id = 1

    for page in pdf_pages:
        if page["page"] not in page_numbers:
            continue

        for chunk in split_text(page["text"]):
            evidence.append({
                "id": evidence_id,
                "page": page["page"],
                "text": chunk
            })

            evidence_id += 1

    return evidence


def format_evidence(evidence):
    return "\n\n".join(
        f"[근거 ID: {item['id']} | "
        f"PDF {item['page']}페이지]\n"
        f"{item['text']}"
        for item in evidence
    )


def get_question_plan_text(plan):
    return "\n".join(
        f"{question_id}번: {question_type}"
        for question_id, question_type in plan
    )


def validate_batch(
    questions,
    plan,
    evidence_lookup
):
    errors = []

    if len(questions) != len(plan):
        errors.append(
            f"문제 수 오류: {len(questions)}개 생성, "
            f"{len(plan)}개 필요"
        )

    for index, question in enumerate(questions):
        if index >= len(plan):
            errors.append(
                "요청하지 않은 추가 문제가 존재합니다."
            )
            break

        expected_id, expected_type = plan[index]

        if question["id"] != expected_id:
            errors.append(
                f"{expected_id}번: 문제 ID 오류"
            )

        if question["type"] != expected_type:
            errors.append(
                f"{expected_id}번: 문제 유형 오류"
            )

        if question["difficulty"] not in {
            "easy",
            "medium",
            "hard"
        }:
            errors.append(
                f"{expected_id}번: 난이도 오류"
            )

        if not question["question"].strip():
            errors.append(
                f"{expected_id}번: 질문 내용 없음"
            )

        if not question["answer"].strip():
            errors.append(
                f"{expected_id}번: 정답 없음"
            )

        if not question["explanation"].strip():
            errors.append(
                f"{expected_id}번: 해설 없음"
            )

        if question["evidence_id"] not in evidence_lookup:
            errors.append(
                f"{expected_id}번: 존재하지 않는 근거 ID"
            )

        options = question["options"]

        if expected_type == "multiple_choice":
            if len(options) != 4:
                errors.append(
                    f"{expected_id}번: 선택지 개수 오류"
                )
            elif len(set(options)) != 4:
                errors.append(
                    f"{expected_id}번: 선택지 중복"
                )

            if question["answer"] not in options:
                errors.append(
                    f"{expected_id}번: 정답이 선택지에 없음"
                )

        elif options:
            errors.append(
                f"{expected_id}번: 주관식 선택지 존재"
            )

    return errors


def get_generation_system_prompt():
    return """
너는 AI 학습 서비스 피뢰침의 퀴즈 출제 전문가다.

제공된 PDF 학습 자료만 사용한다.

문제 생성 규칙:
1. 요청된 문제 수를 정확히 지킨다.
2. 지정된 문제 ID와 유형을 지킨다.
3. 객관식 선택지는 정확히 4개다.
4. 객관식 정답은 반드시 하나만 존재한다.
5. 객관식 answer는 options 중 하나와 정확히 일치한다.
6. 단답형과 서술형 options는 빈 배열이다.
7. 모든 정답과 해설은 PDF 내용으로 뒷받침되어야 한다.
8. PDF에 없는 개념이나 사실을 임의로 추가하지 않는다.
9. evidence_id는 제공된 근거 ID 중 하나를 선택한다.
10. 선택한 근거는 정답을 직접 뒷받침해야 한다.
11. 문제의 핵심 개념이 불필요하게 중복되지 않도록 한다.
12. 모든 문제에 정답과 해설 및 채점 키워드를 포함한다.
13. 객관식 선택지 중 두 개 이상 정답이 되는 문제는 만들지 않는다.
14. 모든 문제와 해설은 한국어로 작성한다.
15. 문제를 어렵게 만들기 위해 외부 지식을 추가하지 않는다.
16. 자료에서 직접 확인할 수 없는 세부 동작을 단정하지 않는다.
17. 서술형은 자료에 있는 개념을 비교하거나 연결하도록 구성한다.
18. 자료가 짧으면 무리하게 복잡한 문제를 만들지 않는다.
19. 실제 PDF에 근거가 있는 내용만 정답에 포함한다.
20. 근거에 없는 추측을 해설에 포함하지 않는다.

난이도 규칙:
- easy: 기본 개념의 이해와 기억
- medium: 개념 비교와 간단한 적용
- hard: 여러 개념을 연결하는 분석과 추론

난이도 비율은 고정하지 않는다.
각 문제의 실제 수준에 맞춰 난이도를 지정한다.
hard 문제를 반드시 생성할 필요는 없다.
PDF 내용이 기초적이면 easy와 medium 중심으로 구성한다.
난이도보다 정답의 정확성과 PDF 근거 충실도를 우선한다.

반드시 JSON Schema를 준수한다.
"""


def generate_batch(
    service,
    plan,
    evidence,
    task_descriptions,
    previous_questions=None
):
    evidence_lookup = {
        item["id"]: item
        for item in evidence
    }

    user_prompt = f"""
[오늘의 학습 작업]
{task_descriptions}

[생성할 문제]
{get_question_plan_text(plan)}

[PDF 학습 자료]
{format_evidence(evidence)}

지정된 문제를 정확히 생성해라.
문제 난이도는 실제 내용에 맞게 자유롭게 결정한다.
근거가 없는 내용을 추가하지 않는다.
"""

    if previous_questions:
        previous_text = "\n".join(
            f"- {question['question']}"
            for question in previous_questions
        )

        user_prompt += f"""

[이미 생성된 문제]
{previous_text}

이미 생성된 문제와 불필요하게 중복되지 않도록 한다.
"""

    last_errors = []

    for attempt in range(3):
        messages = [
            {
                "role": "system",
                "content": get_generation_system_prompt()
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ]

        if last_errors:
            messages.append({
                "role": "user",
                "content": (
                    "이전 생성 결과의 오류를 수정해라.\n"
                    + "\n".join(last_errors)
                )
            })

        result = service.generate(
            messages=messages,
            schema=BATCH_SCHEMA,
            name="daily_quiz_batch",
            max_tokens=5000
        )

        questions = result["questions"]

        errors = validate_batch(
            questions,
            plan,
            evidence_lookup
        )

        if not errors:
            return questions

        last_errors = errors

        logger.info(
            f"문제 묶음 검증 실패 "
            f"({attempt + 1}/3)"
        )

        for error in errors:
            logger.info(f"- {error}")

    raise ValueError(
        "문제 묶음 생성 실패:\n"
        + "\n".join(last_errors)
    )


def attach_evidence(questions, evidence):
    evidence_lookup = {
        item["id"]: item
        for item in evidence
    }

    result = []

    for question in questions:
        evidence_item = evidence_lookup[
            question["evidence_id"]
        ]

        result.append({
            "id": question["id"],
            "type": question["type"],
            "difficulty": question["difficulty"],
            "question": question["question"],
            "options": question["options"],
            "answer": question["answer"],
            "explanation": question["explanation"],
            "source_page": evidence_item["page"],
            "source_text": evidence_item["text"],
            "keywords": question["keywords"]
        })

    return result


def repair_questions(
    service,
    questions,
    issues,
    evidence,
    task_descriptions
):
    issue_lookup = {}

    for issue in issues:
        question_id = issue["question_id"]

        issue_lookup.setdefault(
            question_id, []
        ).append(issue)

    if not issue_lookup:
        raise ValueError(
            "수정할 문제를 확인할 수 없습니다."
        )

    plan_lookup = {
        item[0]: item
        for item in QUESTION_PLAN
    }

    evidence_lookup = {
        item["id"]: item
        for item in evidence
    }

    updated_questions = list(questions)

    for question_id in sorted(issue_lookup):
        if question_id not in plan_lookup:
            raise ValueError(
                f"존재하지 않는 문제 ID: {question_id}"
            )

        current_question = next(
            question
            for question in updated_questions
            if question["id"] == question_id
        )

        other_questions = [
            question
            for question in updated_questions
            if question["id"] != question_id
        ]

        issue_text = "\n".join(
            f"- [{issue['category']}] "
            f"{issue['reason']}\n"
            f"개선 방향: {issue['suggestion']}"
            for issue in issue_lookup[question_id]
        )

        other_questions_text = "\n".join(
            f"- {question['id']}번: {question['question']}"
            for question in other_questions
        )

        plan = [plan_lookup[question_id]]

        user_prompt = f"""
[오늘의 학습 작업]
{task_descriptions}

[수정할 문제]
{get_question_plan_text(plan)}

[기존 문제]
{current_question}

[발견된 오류]
{issue_text}

[다른 문제]
{other_questions_text}

[PDF 학습 자료]
{format_evidence(evidence)}

오류가 발견된 문제 하나만 다시 생성해라.

조건:
1. 문제 ID와 유형은 유지한다.
2. 난이도는 실제 문제 수준에 맞게 자유롭게 변경할 수 있다.
3. 기존 오류를 해결한다.
4. PDF 근거가 명확한 내용만 사용한다.
5. 다른 문제와 불필요하게 중복되지 않도록 한다.
6. 객관식은 정답이 정확히 하나여야 한다.
7. 근거 없는 외부 지식을 추가하지 않는다.
8. questions 배열에 수정된 문제 하나만 포함한다.
"""

        last_errors = []
        replacement = None

        for attempt in range(3):
            messages = [
                {
                    "role": "system",
                    "content": get_generation_system_prompt()
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ]

            if last_errors:
                messages.append({
                    "role": "user",
                    "content": (
                        "이전 수정 결과의 오류를 해결해라.\n"
                        + "\n".join(last_errors)
                    )
                })

            response = service.generate(
                messages=messages,
                schema=BATCH_SCHEMA,
                name="quiz_question_repair",
                max_tokens=2000
            )

            candidates = response["questions"]

            errors = validate_batch(
                candidates,
                plan,
                evidence_lookup
            )

            if not errors:
                replacement = candidates[0]
                break

            last_errors = errors

            logger.info(
                f"{question_id}번 수정 구조 검증 실패 "
                f"({attempt + 1}/3)"
            )

            for error in errors:
                logger.info(f"- {error}")

        if replacement is None:
            raise ValueError(
                f"{question_id}번 문제 수정 실패:\n"
                + "\n".join(last_errors)
            )

        updated_questions = [
            replacement
            if question["id"] == question_id
            else question
            for question in updated_questions
        ]

        logger.info(
            f"{question_id}번 문제 수정 완료"
        )

    return updated_questions


def generate_daily_quiz(
    pdf_path,
    study_plan,
    study_date=None,
    groq_service=None
):
    if study_date is None:
        study_date = date.today().isoformat()

    tasks = get_daily_tasks(
        study_plan,
        study_date
    )

    if not tasks:
        return {
            "status": "no_schedule",
            "date": study_date,
            "message": "해당 날짜에 학습 일정이 없습니다."
        }

    page_numbers = get_study_pages(tasks)

    total_pages, pdf_pages = extract_pdf_text(
        pdf_path
    )

    if any(
        page < 1 or page > total_pages
        for page in page_numbers
    ):
        raise ValueError(
            "학습 범위가 PDF 페이지 수를 벗어났습니다."
        )

    evidence = build_evidence(
        pdf_pages,
        page_numbers
    )

    if not evidence:
        raise ValueError(
            "퀴즈 생성에 사용할 PDF 내용이 없습니다."
        )

    task_descriptions = "\n".join(
        f"- {task['unit_title']}: {task['description']}"
        for task in tasks
    )

    service = groq_service or GroqService()

    logger.info("\n객관식 6문제 생성 중")

    multiple_choice_questions = generate_batch(
        service=service,
        plan=QUESTION_PLAN[:6],
        evidence=evidence,
        task_descriptions=task_descriptions
    )

    logger.info("단답형 및 서술형 4문제 생성 중")

    subjective_questions = generate_batch(
        service=service,
        plan=QUESTION_PLAN[6:],
        evidence=evidence,
        task_descriptions=task_descriptions,
        previous_questions=multiple_choice_questions
    )

    raw_questions = (
        multiple_choice_questions
        + subjective_questions
    )

    max_quality_attempts = 3
    last_errors = []

    for attempt in range(max_quality_attempts):
        logger.info(
            f"\n전체 퀴즈 검증 "
            f"({attempt + 1}/{max_quality_attempts})"
        )

        questions = attach_evidence(
            raw_questions,
            evidence
        )

        quiz = {
            "questions": questions
        }

        validation = validate_quiz(
            quiz,
            pdf_pages,
            set(page_numbers)
        )

        if not validation["valid"]:
            raise ValueError(
                "전체 퀴즈 구조 검증 실패:\n"
                + "\n".join(validation["errors"])
            )

        logger.info("구조 검증 통과")

        quality = check_quiz_quality(
            quiz=quiz,
            pdf_pages=pdf_pages,
            allowed_pages=set(page_numbers),
            groq_service=service
        )

        if quality["passed"]:
            distribution = dict(
                Counter(
                    question["difficulty"]
                    for question in questions
                )
            )

            logger.info("AI 품질 검증 통과")
            logger.info(
                f"난이도 분포: {distribution}"
            )

            return {
                "status": "success",
                "date": study_date,
                "document_title": study_plan["document_title"],
                "total_questions": len(questions),
                "source_pages": page_numbers,
                "questions": questions
            }

        issues = quality["issues"]

        last_errors = [
            (
                f"{issue['question_id']}번 "
                f"[{issue['category']}]: "
                f"{issue['reason']} "
                f"개선: {issue['suggestion']}"
            )
            for issue in issues
        ]

        if not last_errors:
            last_errors = [
                "AI 품질 검증에서 통과하지 못했습니다."
            ]

        logger.info("AI 품질 검증 실패")

        for error in last_errors:
            logger.info(f"- {error}")

        if attempt == max_quality_attempts - 1:
            break

        if not issues:
            break

        logger.info(
            "\n문제가 발견된 문항만 수정합니다."
        )

        raw_questions = repair_questions(
            service=service,
            questions=raw_questions,
            issues=issues,
            evidence=evidence,
            task_descriptions=task_descriptions
        )

    raise ValueError(
        "퀴즈 생성 및 품질 검증 실패:\n"
        + "\n".join(last_errors)
    )


def get_public_quiz(quiz):
    if quiz["status"] != "success":
        return quiz

    return {
        "status": "success",
        "date": quiz["date"],
        "total_questions": quiz["total_questions"],
        "questions": [
            {
                "id": question["id"],
                "type": question["type"],
                "difficulty": question["difficulty"],
                "question": question["question"],
                "options": question["options"]
            }
            for question in quiz["questions"]
        ]
    }
