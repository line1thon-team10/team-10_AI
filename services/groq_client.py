
import os
import json
import time
import logging

from groq import Groq, APIStatusError


logger = logging.getLogger(__name__)

MODEL = "openai/gpt-oss-120b"
MIN_REQUEST_INTERVAL = 25
MAX_RETRIES = 6


class RequestTooLargeError(Exception):
    pass


class GroqService:
    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY")

        if not api_key:
            raise ValueError("GROQ_API_KEY가 없습니다.")

        self.client = Groq(api_key=api_key)
        self.last_request = 0

    def wait_for_slot(self):
        elapsed = time.monotonic() - self.last_request
        remaining = MIN_REQUEST_INTERVAL - elapsed

        if remaining > 0:
            time.sleep(remaining)

    def generate(self, messages, schema, name, max_tokens=1200):
        for attempt in range(MAX_RETRIES):
            self.wait_for_slot()
            self.last_request = time.monotonic()

            try:
                response = self.client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    temperature=0.1,
                    max_completion_tokens=max_tokens,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": name,
                            "strict": True,
                            "schema": schema
                        }
                    }
                )

                content = response.choices[0].message.content

                if not content:
                    raise RuntimeError("Groq 응답이 비어 있습니다.")

                return json.loads(content)

            except APIStatusError as error:
                message = str(error).lower()

                if error.status_code == 413:
                    raise RequestTooLargeError(
                        "Groq 요청이 TPM 제한을 초과했습니다."
                    ) from error

                if error.status_code == 400 and (
                    "max completion tokens" in message
                    or "json_validate_failed" in message
                ):
                    raise RequestTooLargeError(
                        "Groq 출력 토큰이 부족합니다."
                    ) from error

                if error.status_code not in (
                    429, 500, 502, 503, 504
                ):
                    raise

                if attempt == MAX_RETRIES - 1:
                    raise

                retry_after = None

                if error.response is not None:
                    retry_after = error.response.headers.get(
                        "retry-after"
                    )

                try:
                    wait_time = float(retry_after)
                except (TypeError, ValueError):
                    wait_time = min(
                        90,
                        20 * (attempt + 1)
                    )

                logger.warning(
                    f"Groq 요청 대기: {wait_time:.0f}초"
                )

                time.sleep(max(1, wait_time))

        raise RuntimeError("Groq 요청 실패")
