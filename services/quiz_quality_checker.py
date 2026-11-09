
import json

from services.groq_client import GroqService


QUALITY_SCHEMA = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_id": {"type": "integer"},
                    "category": {
                        "type": "string",
                        "enum": [
                            "duplicate",
                            "multiple_answers",
                            "incorrect_answer",
                            "unsupported_content",
                            "unclear_question"
                        ]
                    },
                    "reason": {"type": "string"},
                    "suggestion": {"type": "string"}
                },
                "required": [
                    "question_id",
                    "category",
                    "reason",
                    "suggestion"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": ["passed", "issues"],
    "additionalProperties": False
}


def check_quiz_quality(
    quiz,
    pdf_pages,
    allowed_pages,
    groq_service=None
):
    service = groq_service or GroqService()

    selected_pages = [
        page
        for page in pdf_pages
        if page["page"] in allowed_pages
    ]

    source_text = "\n\n".join(
        f"[PDF {page['page']}페이지]\n{page['text']}"
        for page in selected_pages
    )

    system_prompt = """
너는 AI 학습 서비스 피뢰침의 퀴즈 품질 검증 AI다.

제공된 PDF 학습 자료를 기준으로 퀴즈를 검증한다.

필수 검증 항목:
1. 객관식 정답이 실제로 올바른가?
2. 객관식 선택지에 정답이 두 개 이상 존재하는가?
3. 정답과 해설이 PDF 내용에 의해 뒷받침되는가?
4. PDF에 없는 사실을 단정하고 있는가?
5. 동일한 내용을 반복해서 묻는 문제가 있는가?
6. 질문이 명확하고 답변 가능한가?
7. 단답형과 서술형 모범 답안이 정확한가?
8. 문제에 지정된 근거 페이지가 적절한가?

검증 원칙:
- 난이도 비율은 검증하지 않는다.
- 난이도가 쉽거나 어렵다는 이유만으로 실패시키지 않는다.
- PDF 내용이 기초적이어도 문제를 실패시키지 않는다.
- 문제에 외부 지식이 반드시 필요한 경우 근거 부족으로 처리한다.
- PDF에 직접 적혀 있지 않더라도 명시된 내용에서 논리적으로 도출할 수 있는 설명은 허용한다.
- 일반적인 예시가 새로운 사실을 단정하지 않고 원래 개념을 정확하게 설명한다면 허용한다.
- 근거가 불충분한 내용을 추측으로 정당화하지 않는다.
- source_text가 PDF 원문과 일치하는지는 Python에서 별도로 검사한다.
- source_text가 존재한다는 이유만으로 정답이 정확하다고 판단하지 않는다.
- 문제의 정답이 PDF 근거로 뒷받침되는지 확인한다.
- 다른 문제와 일부 용어가 겹친다는 이유만으로 중복 처리하지 않는다.
- 같은 사실을 사실상 동일하게 묻는 경우에만 중복으로 판단한다.
- 명확한 오류만 issues에 포함한다.
- 문제가 없다면 passed는 true, issues는 빈 배열이다.
- 문제가 있다면 passed는 false다.
- 모든 reason과 suggestion은 한국어로 작성한다.

category:
duplicate: 실질적으로 동일한 문제
multiple_answers: 객관식 복수 정답
incorrect_answer: 정답 오류
unsupported_content: PDF 근거 부족
unclear_question: 모호한 질문

반드시 JSON Schema를 준수한다.
"""

    user_prompt = f"""
[PDF 학습 자료]
{source_text}

[검증할 퀴즈]
{json.dumps(quiz, ensure_ascii=False)}

정답의 정확성, 근거 충실도, 문제 중복 여부를 검증해라.

난이도 분포나 난이도 적절성은 실패 사유로 사용하지 마라.
"""

    result = service.generate(
        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        schema=QUALITY_SCHEMA,
        name="quiz_quality_check",
        max_tokens=3500
    )

    valid_ids = {
        question["id"]
        for question in quiz["questions"]
    }

    result["issues"] = [
        issue
        for issue in result["issues"]
        if issue["question_id"] in valid_ids
    ]

    result["passed"] = (
        result["passed"]
        and len(result["issues"]) == 0
    )

    return result
