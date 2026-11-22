"""Configuração central do Radar Legislativo, lida do ambiente e do arquivo `.env`."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

RAIZ_PROJETO = Path(__file__).resolve().parents[2]
PLACEHOLDER_MARCAS = ("<senha>", "<ref>", "sk-...", "troque-por")


class ConfiguracaoAusente(RuntimeError):
    """Uma variável obrigatória para a operação não foi definida no `.env`."""


def _eh_placeholder(valor: str | None) -> bool:
    return not valor or any(marca in valor for marca in PLACEHOLDER_MARCAS)


class Settings(BaseSettings):
    """Um campo por variável do `.env.example`."""

    model_config = SettingsConfigDict(
        env_file=RAIZ_PROJETO / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Bancos ---
    database_url: SecretStr | None = None
    bronze_database_url_raw: SecretStr | None = Field(default=None, alias="BRONZE_DATABASE_URL")
    database_url_readonly: SecretStr | None = None
    db_limite_mb: int = 500

    # --- API Câmara ---
    camara_base_url: str = "https://dadosabertos.camara.leg.br/api/v2"
    camara_openapi_url: str = "https://dadosabertos.camara.leg.br/api/v2/api-docs"
    camara_itens_por_pagina: int = Field(default=100, ge=1, le=100)
    camara_throttle_segundos: float = Field(default=0.2, ge=0)
    camara_timeout_connect: float = 5
    camara_timeout_read: float = 60
    camara_max_retries: int = Field(default=5, ge=0)
    camara_user_agent: str = "radar-legislativo/2.0 (projeto academico)"
    id_legislatura: int = 57
    inicio_legislatura: date = date(2023, 2, 1)

    # --- Pipeline ---
    landing_dir: Path = Path("data/landing")
    rejected_dir: Path = Path("data/rejected")
    log_dir: Path = Path("data/logs")
    extracao_workers: int = Field(default=4, ge=1)
    janela_incremental_dias: int = Field(default=2, ge=1)
    despesas_meses_reprocessar: int = Field(default=3, ge=0)
    bronze_retencao_versoes_dias: int = Field(default=0, ge=0)
    tipos_relevantes: Annotated[list[str], NoDecode] = ["PL", "PLP", "PEC", "MPV", "PDL"]

    # --- OpenAI ---
    openai_api_key: SecretStr | None = None
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_batch: int = Field(default=100, ge=1)
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 300
    ia_resumo_habilitado: bool = True
    ia_orcamento_max_usd: float = Field(default=1.00, ge=0)
    preco_embedding_usd_1m: float = 0.02
    preco_llm_entrada_usd_1m: float = 0.15
    preco_llm_saida_usd_1m: float = 0.60
    tema_limiar_minimo: float = Field(default=0.20, ge=0, le=1)

    # --- Telegram ---
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    # --- Dashboards ---
    dashboard_out_dir: Path = Path("site")
    dashboard_base_url: str = ""
    dashboard_janela_dias: int = Field(default=90, ge=1)

    # --- Runner / n8n ---
    runner_token: SecretStr | None = None
    n8n_encryption_key: SecretStr | None = None
    generic_timezone: str = "America/Sao_Paulo"

    # --- Logging ---
    log_level: str = "INFO"

    @field_validator("tipos_relevantes", mode="before")
    @classmethod
    def _split_virgula(cls, valor: object) -> object:
        if isinstance(valor, str):
            return [item.strip().upper() for item in valor.split(",") if item.strip()]
        return valor

    @field_validator(
        "database_url",
        "bronze_database_url_raw",
        "database_url_readonly",
        "openai_api_key",
        "telegram_bot_token",
        "runner_token",
        "n8n_encryption_key",
        mode="before",
    )
    @classmethod
    def _vazio_vira_none(cls, valor: object) -> object:
        if isinstance(valor, str) and not valor.strip():
            return None
        return valor

    @field_validator("landing_dir", "rejected_dir", "log_dir", "dashboard_out_dir")
    @classmethod
    def _caminho_absoluto(cls, valor: Path) -> Path:
        return valor if valor.is_absolute() else RAIZ_PROJETO / valor

    # ------------------------------------------------------------ acessores
    @property
    def bronze_database_url(self) -> SecretStr | None:
        """URL da Bronze; cai para `database_url` quando não definida."""
        return self.bronze_database_url_raw or self.database_url

    def exigir(self, campo: str) -> str:
        """Devolve o valor de um campo secreto ou falha com mensagem clara."""
        valor = getattr(self, campo)
        texto = valor.get_secret_value() if isinstance(valor, SecretStr) else valor
        if _eh_placeholder(texto):
            raise ConfiguracaoAusente(
                f"{campo.upper()} não está configurada. Preencha no arquivo .env "
                "(veja .env.example)."
            )
        return texto


@lru_cache
def get_settings() -> Settings:
    """Instância única das configurações."""
    return Settings()
