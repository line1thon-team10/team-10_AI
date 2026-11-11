
import re
from typing import Any

from dotenv import load_dotenv
from services.groq_client import GroqService

load_dotenv()

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "pages": {
            "type": "array",
            "items": {"type": "integer"}
        }
    },
    "required": ["answer", "pages"],
    "additionalProperties": False
}


def _normalize_pages(pages: list[dict]) -> list[dict]:
    result = []

    for item in pages:
        if not isinstance(item, dict):
            continue

        number = item.get("page")
        content = item.get("text")

        if (
            isinstance(number, int)
            and number > 0
            and isinstance(content, str)
            and content.strip()
        ):
            result.append({
                "page": number,
                "text": content.strip()
            })

    return result


def _validate_history(history: list[dict]) -> list[dict]:
    if not isinstance(history, list):
        raise ValueError("history는 배열이어야 합니다.")

    validated = []

    for item in history:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("question"), str)
            or not isinstance(item.get("answer"), str)
        ):
            raise ValueError(
                "history 항목에는 question과 answer 문자열이 필요합니다."
            )

        pages = item.get("pages", [])

        if (
            not isinstance(pages, list)
            or any(type(p) is not int or p < 1 for p in pages)
        ):
            raise ValueError(
                "history.pages는 양의 정수 배열이어야 합니다."
            )

        validated.append({
            "question": item["question"],
            "answer": item["answer"],
            "pages": pages
        })

    return validated


def _generate(
    groq,
    instruction: str,
    question: str,
    source_pages: list[dict],
    history: list[dict],
    allowed_pages: list[int]
) -> dict:
    import json

    source = [
        {
            "page": p["page"],
            "text": p["text"][:9000]
        }
        for p in source_pages
    ]

    messages = [
        {
            "role": "system",
            "content": (
                instruction
                + "\n반드시 제공된 학습자료에만 근거해 답하세요."
                + " 근거가 없다면 모른다고 답하고 pages를 빈 배열로 반환하세요."
                + " 페이지 번호는 제공된 번호만 사용하세요."
                + " 답변은 한국어로 작성하세요."
            )
        },
        {
            "role": "user",
            "content": json.dumps({
                "question": question,
                "history": history[-8:],
                "source_pages": source
            }, ensure_ascii=False)
        }
    ]

    result = groq.generate(
        messages,
        ANSWER_SCHEMA,
        "ai_tutor_answer",
        max_tokens=1200
    )

    answer = result.get("answer")

    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("AI 튜터 답변이 비어 있습니다.")

    cited = result.get("pages", [])

    if not isinstance(cited, list):
        raise ValueError(
            "AI 튜터 근거 페이지 형식이 올바르지 않습니다."
        )

    cited = list(dict.fromkeys(
        p for p in cited
        if type(p) is int and p in allowed_pages
    ))

    return {
        "answer": answer.strip(),
        "pages": cited
    }


def answer_tutor(
    question: str,
    history: list[dict],
    document_pages: list[dict],
    groq: Any = None
) -> dict:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question은 비어 있을 수 없습니다.")

    validated_history = _validate_history(history)
    pages = _normalize_pages(document_pages)

    if not pages:
        return {
            "answer": "학습자료에서 읽을 수 있는 내용을 찾지 못했습니다.",
            "pages": []
        }

    terms = set(
        re.findall(r"[가-힣A-Za-z0-9]{2,}", question.lower())
    )

    ranked = sorted(
        pages,
        key=lambda p: sum(
            p["text"].lower().count(term)
            for term in terms
        ),
        reverse=True
    )

    selected = ranked[:8]
    client = groq if groq is not None else GroqService()

    return _generate(
        client,
        (
            "당신은 학습자료를 설명하는 AI 튜터입니다."
            " 질문 하나에 명확하고 간결하게 답하고,"
            " 답변에 실제 사용한 근거 페이지를 pages에 기록하세요."
            " 이전 대화는 맥락 파악용이며 현재 자료보다 우선하지 않습니다."
        ),
        question,
        selected,
        validated_history,
        [p["page"] for p in selected]
    )


def simplify_tutor(
    question: str,
    answer: str,
    pages: list[int],
    document_pages: list[dict],
    groq: Any = None
) -> dict:
    if (
        not isinstance(question, str)
        or not question.strip()
        or not isinstance(answer, str)
        or not answer.strip()
    ):
        raise ValueError("직전 질문과 답변이 필요합니다.")

    if (
        not isinstance(pages, list)
        or any(type(p) is not int or p < 1 for p in pages)
    ):
        raise ValueError(
            "pages는 양의 정수 배열이어야 합니다."
        )

    original_pages = list(dict.fromkeys(pages))
    available = _normalize_pages(document_pages)

    evidence = [
        p for p in available
        if p["page"] in original_pages
    ]

    if original_pages and len(evidence) != len(original_pages):
        raise ValueError(
            "원래 답변의 근거 페이지를 학습자료에서 찾을 수 없습니다."
        )

    if not original_pages:
        return {
            "answer": "원래 답변에 확인된 근거가 없어 쉬운 설명을 생성할 수 없습니다.",
            "pages": []
        }

    client = groq if groq is not None else GroqService()

    result = _generate(
        client,
        (
            "다음은 이미 답변한 질문입니다."
            " 새로운 질문에 답하지 말고 기존 답변을 쉬운 말로 다시 설명하세요."
            " 원래 답변의 의미를 유지하고 자료에 없는 사실을 추가하지 마세요."
            " pages는 원래 근거를 유지해야 합니다."
        ),
        question,
        evidence,
        [{
            "question": question,
            "answer": answer,
            "pages": original_pages
        }],
        original_pages
    )

    return {
        "answer": result["answer"],
        "pages": original_pages
    }
