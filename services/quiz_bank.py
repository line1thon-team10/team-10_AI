
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from services.groq_client import GroqService
from services.pdf_parser import extract_pdf_text
from services.quiz_generator import BATCH_SCHEMA, build_evidence, attach_evidence


QUESTION_TYPES = ["multiple_choice"] * 6 + ["short_answer"] * 3 + ["essay"]

BANK_SCHEMA = json.loads(json.dumps(BATCH_SCHEMA))
BANK_SCHEMA["properties"]["questions"]["items"]["properties"]["concept_id"] = {"type": "string"}
BANK_SCHEMA["properties"]["questions"]["items"]["required"].append("concept_id")


def _as_dict(value):
    return value.model_dump() if hasattr(value, "model_dump") else value


def _normalized(value):
    return re.sub(r"\s+", "", str(value)).casefold()


def _save_json(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def _check_unit(unit, total_pages):
    start = int(unit.get("page_start", unit.get("start_page", 0)))
    end = int(unit.get("page_end", unit.get("end_page", 0)))
    if not 1 <= start <= end <= total_pages:
        raise ValueError(f"단원 페이지 범위 오류: {unit.get('id', unit.get('unit_id'))}")
    return start, end


def _get_concepts(unit, start, end):
    concepts = []
    for raw in unit.get("concepts", []):
        item = _as_dict(raw)
        concept_id = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()
        first = int(item.get("page_start", start))
        last = int(item.get("page_end", end))
        if not concept_id or not name or not start <= first <= last <= end:
            raise ValueError(f"잘못된 개념 정보: {item}")
        concepts.append({"id": concept_id, "name": name, "page_start": first, "page_end": last})
    if not concepts:
        raise ValueError(f"개념이 없는 단원입니다: {unit.get('id', unit.get('unit_id'))}")
    if len({item["id"] for item in concepts}) != len(concepts):
        raise ValueError("중복된 개념 ID가 있습니다.")
    return concepts


def _validate_question(question, number, kind, evidence_lookup, concept_lookup, seen):
    if question.get("id") != number or question.get("type") != kind:
        raise ValueError(f"{number}번 문제 ID 또는 유형 오류")
    if question.get("difficulty") != "easy":
        raise ValueError(f"{number}번 문제 난이도 오류")
    if not str(question.get("question", "")).strip():
        raise ValueError(f"{number}번 질문이 비어 있습니다.")
    key = _normalized(question["question"])
    if key in seen:
        raise ValueError(f"{number}번 중복 문항")
    if not str(question.get("answer", "")).strip() or not str(question.get("explanation", "")).strip():
        raise ValueError(f"{number}번 정답 또는 해설 누락")
    evidence = evidence_lookup.get(question.get("evidence_id"))
    if evidence is None:
        raise ValueError(f"{number}번 근거 ID 오류")
    concept = concept_lookup.get(question.get("concept_id"))
    if concept is None:
        raise ValueError(f"{number}번 개념 ID 오류")
    if not concept["page_start"] <= evidence["page"] <= concept["page_end"]:
        raise ValueError(f"{number}번 개념과 근거 페이지가 일치하지 않습니다.")
    options = question.get("options", [])
    if kind == "multiple_choice":
        if len(options) != 4 or len(set(options)) != 4 or question["answer"] not in options:
            raise ValueError(f"{number}번 객관식 선택지 오류")
    elif options:
        raise ValueError(f"{number}번 주관식 선택지 오류")
    seen.add(key)


def _make_batch(service, plan, evidence, concepts, previous, title):
    evidence_lookup = {item["id"]: item for item in evidence}
    concept_lookup = {item["id"]: item for item in concepts}
    system = (
        "너는 피뢰침 학습자료 퀴즈 출제자다. 반드시 제공된 JSON Schema를 지켜라. "
        "각 문제는 제공된 concepts의 concept_id를 반드시 하나 선택한다. "
        "그 개념의 page_start~page_end 범위 안에 있는 evidence_id만 선택한다. "
        "선택한 근거 텍스트가 정답을 직접 뒷받침하는 문제만 작성한다. "
        "개념과 근거의 의미가 실제로 맞아야 하며 페이지 번호만 맞는 문제를 만들지 않는다. "
        "요청된 문제 번호와 유형을 지키고 difficulty는 모두 easy로 한다. "
        "객관식 선택지는 서로 다른 4개이며 정답은 반드시 선택지 중 하나다. "
        "단답형과 서술형 options는 빈 배열이다. "
        "모든 문제에 정답, 해설, evidence_id, concept_id, keywords를 포함한다. "
        "이전 문항과 중복하지 않고 모든 질문과 해설을 한국어로 작성한다. "
        "PDF에 없는 사실을 만들지 않는다."
    )
    payload = {
        "unit": title,
        "plan": [{"id": number, "type": kind, "difficulty": "easy"} for number, kind in plan],
        "concepts": concepts,
        "evidence": evidence,
        "previous_questions": previous
    }
    errors = []
    for attempt in range(3):
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
        ]
        if errors:
            messages.append({"role": "user", "content": "이전 오류를 수정해 전체 묶음을 다시 생성하세요: " + "; ".join(errors)})
        result = service.generate(messages, BANK_SCHEMA, "unit_quiz_bank_concept", max_tokens=5000)
        questions = result.get("questions", [])
        errors = []
        if len(questions) != len(plan):
            errors.append("요청한 문항 수와 다릅니다.")
        seen = {_normalized(item["question"]) for item in previous}
        for (number, kind), question in zip(plan, questions):
            try:
                _validate_question(question, number, kind, evidence_lookup, concept_lookup, seen)
            except (ValueError, TypeError, KeyError) as error:
                errors.append(str(error))
        if not errors:
            return questions
    raise ValueError("개념 기반 문제 생성 검증 실패: " + "; ".join(errors))


def _cache_key(pdf_path, document, subject):
    digest = hashlib.sha256()
    with Path(pdf_path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    payload = json.dumps({"version": "concept_guided_v3", "pdf_hash": digest.hexdigest(), "analysis": document, "subject": subject}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_unit_question_bank(pdf_path, analysis, subject=None, output_path=None, groq_service=None):
    document = _as_dict(analysis)
    subject = subject or document.get("subject")
    if not subject:
        raise ValueError("과목 코드 subject가 필요합니다.")
    if document.get("subject") and document["subject"] != subject:
        raise ValueError("요청 subject와 분석 결과의 subject가 다릅니다.")
    total_pages, pdf_pages = extract_pdf_text(pdf_path)
    service = groq_service or GroqService()
    cache_dir = Path("cache") / "quiz_bank" / _cache_key(pdf_path, document, subject)
    cache_dir.mkdir(parents=True, exist_ok=True)
    units = []
    for index, raw in enumerate(document.get("units", []), start=1):
        unit = _as_dict(raw)
        start, end = _check_unit(unit, total_pages)
        unit_id = unit.get("id", f"{subject}{index}")
        title = unit.get("name", unit.get("title", unit_id))
        cache_file = cache_dir / f"unit_{index}.json"
        if cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("unit_id") == unit_id and cached.get("status") in {"success", "no_quiz"}:
                units.append(cached)
                continue
        concepts = _get_concepts(unit, start, end)
        covered_pages = {page for concept in concepts for page in range(concept["page_start"], concept["page_end"] + 1)}
        evidence = build_evidence(pdf_pages, covered_pages)
        if not evidence:
            unit_result = {"unit_id": unit_id, "status": "no_quiz", "reason": "no_extractable_text_for_concepts", "questions": []}
            _save_json(cache_file, unit_result)
            units.append(unit_result)
            continue
        if len(evidence) > 24:
            step = max(1, (len(evidence) + 23) // 24)
            evidence = evidence[::step][:24]
        usable_pages = {item["page"] for item in evidence}
        concepts = [item for item in concepts if any(item["page_start"] <= page <= item["page_end"] for page in usable_pages)]
        plans = [list(enumerate(QUESTION_TYPES[:5], start=1)), list(enumerate(QUESTION_TYPES[5:], start=6))]
        batch_cache = cache_dir / f"unit_{index}_batches.json"
        previous = []
        if batch_cache.exists():
            previous = json.loads(batch_cache.read_text(encoding="utf-8"))
            if len(previous) not in {5, 10} or any("concept_id" not in item for item in previous):
                previous = []
        for plan in plans:
            if len(previous) >= plan[-1][0]:
                continue
            previous.extend(_make_batch(service, plan, evidence, concepts, previous, title))
            _save_json(batch_cache, previous)
        attached = attach_evidence(previous, evidence)
        concept_lookup = {item["id"]: item for item in concepts}
        questions = []
        for index_question, (raw_question, question) in enumerate(zip(previous, attached), start=1):
            concept = concept_lookup[raw_question["concept_id"]]
            if not concept["page_start"] <= question["source_page"] <= concept["page_end"]:
                raise ValueError(f"{unit_id} {index_question}번 문제 개념-근거 불일치")
            questions.append({
                "id": f"{unit_id}-{index_question:02d}",
                "concept": concept["id"],
                "concept_name": concept["name"],
                "unit": unit_id,
                "page": question["source_page"],
                "type": question["type"],
                "difficulty": "easy",
                "question": question["question"],
                "choices": question["options"],
                "answer": question["answer"],
                "explanation": question["explanation"],
                "source_text": question["source_text"],
                "keywords": question["keywords"]
            })
        unit_result = {"unit_id": unit_id, "status": "success", "questions": questions}
        _save_json(cache_file, unit_result)
        units.append(unit_result)
    result = {
        "status": "success",
        "subject": subject,
        "document_title": document.get("document_title", Path(pdf_path).stem),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "units": units
    }
    if output_path:
        _save_json(output_path, result)
    return result


def select_unit_questions(bank, unit_id, count=5, excluded_ids=None, allowed_pages=None):
    if count < 1:
        raise ValueError("count는 1 이상이어야 합니다.")
    excluded = set(excluded_ids or [])
    allowed = set(allowed_pages) if allowed_pages is not None else None
    unit = next((item for item in bank.get("units", []) if item.get("unit_id") == unit_id), None)
    if unit is None:
        raise ValueError(f"단원을 찾을 수 없습니다: {unit_id}")
    if unit.get("status") != "success":
        return []
    selected = [question for question in unit["questions"] if question["id"] not in excluded and (allowed is None or question["page"] in allowed)]
    return selected[:count]


def get_public_bank_questions(questions):
    return [{
        "id": question["id"],
        "concept": question["concept"],
        "unit": question["unit"],
        "page": question["page"],
        "type": question["type"],
        "difficulty": question["difficulty"],
        "question": question["question"],
        "choices": question["choices"]
    } for question in questions]


def load_question_bank(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
