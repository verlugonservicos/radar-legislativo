"""Cliente OpenAI mínimo (SPEC V3 10.1): embeddings e chat com saída JSON estrita.

`ClienteIA` é injetável: os testes usam um cliente falso com a mesma interface.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from radar.config import Settings, get_settings

log = logging.getLogger("radar.ai")

_REPETIR = retry(
    retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIConnectionError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)


class SemChaveOpenAI(RuntimeError):
    """OPENAI_API_KEY não configurada: a etapa de IA é pulada."""


class Cliente(Protocol):
    def embed(self, texts: list[str]) -> tuple[list[list[float]], int]: ...
    def chat_json(self, system: str, user: str, schema: dict) -> tuple[dict, int, int]: ...


class ClienteIA:
    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()
        if self.s.openai_api_key is None:
            raise SemChaveOpenAI("OPENAI_API_KEY não configurada no .env")
        self._api = OpenAI(api_key=self.s.openai_api_key.get_secret_value(), timeout=60)

    @_REPETIR
    def embed(self, texts: list[str]) -> tuple[list[list[float]], int]:
        """Vetores (na ordem de `texts`) e tokens cobrados."""
        r = self._api.embeddings.create(model=self.s.embedding_model, input=texts)
        return [d.embedding for d in sorted(r.data, key=lambda d: d.index)], r.usage.prompt_tokens

    @_REPETIR
    def chat_json(self, system: str, user: str, schema: dict) -> tuple[dict, int, int]:
        """Objeto JSON validado pelo schema estrito, tokens de entrada e de saída."""
        r = self._api.chat.completions.create(
            model=self.s.llm_model,
            temperature=self.s.llm_temperature,
            max_tokens=self.s.llm_max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "resumo", "schema": schema, "strict": True},
            },
        )
        conteudo = r.choices[0].message.content
        if r.choices[0].finish_reason != "stop" or not conteudo:
            raise ValueError(f"resposta incompleta do modelo ({r.choices[0].finish_reason})")
        return json.loads(conteudo), r.usage.prompt_tokens, r.usage.completion_tokens
