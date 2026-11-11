
import json
import re
from services.groq_client import GroqService

ESSAY_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "missing_points": {"type": "array", "items": {"type": "string"}},
        "feedback": {"type": "string"}
    },
    "required": ["score", "strengths", "missing_points", "feedback"],
    "additionalProperties": False
}


def _rubric(question):
    rubric = question.get("rubric")
    if rubric is None:
        return []
    if not isinstance(rubric, list) or not rubric:
        raise ValueError("rubric은 비어 있지 않은 배열이어야 합니다.")
    result = []
    for item in rubric:
        if not isinstance(item, dict) or not isinstance(item.get("criterion"), str) or not item["criterion"].strip():
            raise ValueError("rubric.criterion이 올바르지 않습니다.")
        points = item.get("points")
        if type(points) is not int or points < 1:
            raise ValueError("rubric.points는 양의 정수여야 합니다.")
        result.append({"criterion": item["criterion"], "points": points})
    if sum(item["points"] for item in result) != 100:
        raise ValueError("rubric 배점 합계는 100이어야 합니다.")
    return result


def grade_essay(question, user_answer, groq_service=None):
    if not isinstance(question, dict) or not isinstance(user_answer, str):
        raise ValueError("문항은 객체, 답안은 문자열이어야 합니다.")
    for key in ("question", "answer"):
        if not isinstance(question.get(key), str) or not question[key].strip():
            raise ValueError(f"{key}가 비어 있습니다.")
    rubric = _rubric(question)
    page = question.get("source_page", question.get("page"))
    if type(page) is not int or page < 1:
        raise ValueError("근거 페이지가 필요합니다.")
    source_text = question.get("source_text", "")
    if not isinstance(source_text, str):
        raise ValueError("source_text는 문자열이어야 합니다.")
    question_id = question.get("id")
    if not user_answer.strip():
        return {
            "question_id": question_id, "score": 0, "is_correct": False,
            "strengths": [], "missing_points": ["답안이 제출되지 않았습니다."],
            "feedback": "답안을 입력하지 않았습니다.", "correct_answer": question["answer"],
            "source_page": page, "source_text": source_text
        }
    system = (
        "너는 학습자료 기반 서술형 채점자다. 정수 0~100점으로 채점하고 85점 이상은 정답이다. "
        "문제와 모범 답안, 제공된 근거 텍스트만 사용한다. 의미가 같은 표현은 인정한다. "
        "답안에 없는 절차를 수행했다고 가정하지 않는다. 정확한 내용과 빠진 내용을 분리한다. "
        "루브릭이 주어지면 각 기준의 충족 정도를 반영해 배점을 적용한다. "
        "루브릭이 없으면 핵심 개념의 정확성 50점, 요구된 절차·조건의 충족 40점, 설명 명료성 10점을 기준으로 채점한다. "
        "근거 없는 요구 조건을 만들어 감점하지 않는다. 모든 피드백은 한국어로 작성한다. "
        "BST에서 자식이 둘인 노드 삭제 문제라면 후속자 선택과 후속자의 원래 위치 삭제는 서로 다른 단계다. "
        "후속자 선택·대체만 설명하고 원래 위치의 후속자 제거를 누락한 답안은, 두 단계만 요구되는 경우 약 70점으로 평가한다."
    )
    payload = {
        "question": question["question"], "correct_answer": question["answer"],
        "user_answer": user_answer, "rubric": rubric,
        "source_page": page, "source_text": source_text[:9000]
    }
    client = groq_service if groq_service is not None else GroqService()
    result = client.generate(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        schema=ESSAY_SCHEMA, name="essay_grading_100", max_tokens=1200
    )
    score = result.get("score")
    if type(score) is not int or not 0 <= score <= 100:
        raise ValueError("AI 서술형 점수는 0~100 정수여야 합니다.")
    for key in ("strengths", "missing_points"):
        if not isinstance(result.get(key), list) or any(not isinstance(x, str) for x in result[key]):
            raise ValueError(f"{key}는 문자열 배열이어야 합니다.")
    if not isinstance(result.get("feedback"), str) or not result["feedback"].strip():
        raise ValueError("서술형 피드백이 비어 있습니다.")
    return {
        "question_id": question_id, "score": score, "is_correct": score >= 85,
        "strengths": result["strengths"], "missing_points": result["missing_points"],
        "feedback": result["feedback"].strip(), "correct_answer": question["answer"],
        "source_page": page, "source_text": source_text
    }
