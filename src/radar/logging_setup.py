"""Logging padronizado: console (INFO) e arquivo rotativo (DEBUG), com contexto e sem segredos."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMATO = (
    "%(asctime)s | %(levelname)s | %(name)s | run=%(run)s | camada=%(camada)s "
    "| endpoint=%(endpoint)s | %(message)s"
)

_contexto: ContextVar[dict[str, str] | None] = ContextVar("radar_log_contexto", default=None)

# senha em URLs de conexão (postgresql://usuario:SENHA@host) e chaves comuns
_PADROES_SEGREDO = [
    (re.compile(r"(://[^:/@\s]+:)[^@\s]+(@)"), r"\1***\2"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"(\b\d{6,}:)[A-Za-z0-9_\-]{20,}"), r"\1***"),  # token de bot do Telegram
]


def mascarar(texto: str) -> str:
    """Remove senhas e chaves de um texto antes de registrá-lo."""
    for padrao, troca in _PADROES_SEGREDO:
        texto = padrao.sub(troca, texto)
    return texto


class _FormatterSeguro(logging.Formatter):
    """Mascara segredos na linha final, inclusive em tracebacks de exceções."""

    def format(self, record: logging.LogRecord) -> str:
        return mascarar(super().format(record))


class _ContextoFilter(logging.Filter):
    """Injeta run/camada/endpoint no registro e mascara segredos na mensagem."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _contexto.get() or {}
        for chave in ("run", "camada", "endpoint"):
            if not hasattr(record, chave):
                setattr(record, chave, ctx.get(chave, "-"))
        record.msg = mascarar(record.getMessage())
        record.args = None
        return True


@contextmanager
def log_contexto(**valores: object) -> Iterator[None]:
    """Define run/camada/endpoint para todos os logs dentro do bloco."""
    novo = {**(_contexto.get() or {}), **{k: str(v) for k, v in valores.items()}}
    token = _contexto.set(novo)
    try:
        yield
    finally:
        _contexto.reset(token)


def setup_logging(log_dir: Path | None = None, nivel_console: str = "INFO") -> None:
    """Configura o logger raiz `radar`. Pode ser chamado mais de uma vez."""
    logger = logging.getLogger("radar")
    logger.setLevel(logging.DEBUG)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = _FormatterSeguro(FORMATO)
    filtro = _ContextoFilter()

    console = logging.StreamHandler()
    console.setLevel(nivel_console.upper())
    console.setFormatter(formatter)
    console.addFilter(filtro)
    logger.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        arquivo = RotatingFileHandler(
            log_dir / "radar.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
        arquivo.setLevel(logging.DEBUG)
        arquivo.setFormatter(formatter)
        arquivo.addFilter(filtro)
        logger.addHandler(arquivo)

    logger.propagate = False
