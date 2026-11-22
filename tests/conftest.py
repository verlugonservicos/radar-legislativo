"""Fixtures comuns: isolam os testes do `.env` local e do cache de configurações."""

from __future__ import annotations

import pytest

from radar import config, db


@pytest.fixture(autouse=True)
def _limpa_caches():
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    yield
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()


@pytest.fixture
def sem_env(monkeypatch: pytest.MonkeyPatch):
    """Settings sem `.env` e sem variáveis do sistema que afetem o teste."""
    monkeypatch.setitem(config.Settings.model_config, "env_file", None)
    for nome in ("DATABASE_URL", "BRONZE_DATABASE_URL", "OPENAI_API_KEY", "TIPOS_RELEVANTES"):
        monkeypatch.delenv(nome, raising=False)
    return monkeypatch
