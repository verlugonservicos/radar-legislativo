from pathlib import Path

import pytest

from radar.config import RAIZ_PROJETO, ConfiguracaoAusente, Settings


def test_defaults_sem_env(sem_env):
    s = Settings()
    assert s.database_url is None
    assert s.camara_itens_por_pagina == 100
    assert s.tipos_relevantes == ["PL", "PLP", "PEC", "MPV", "PDL"]
    assert s.id_legislatura == 57


def test_lista_separada_por_virgula(sem_env):
    sem_env.setenv("TIPOS_RELEVANTES", "pl, pec ,MPV,")
    assert Settings().tipos_relevantes == ["PL", "PEC", "MPV"]


def test_bronze_cai_para_database_url(sem_env):
    sem_env.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h/db")
    sem_env.setenv("BRONZE_DATABASE_URL", "")
    s = Settings()
    assert s.bronze_database_url.get_secret_value() == "postgresql+psycopg://u:p@h/db"


def test_bronze_separada(sem_env):
    sem_env.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h/db")
    sem_env.setenv("BRONZE_DATABASE_URL", "postgresql+psycopg://u:p@outro/db")
    assert "outro" in Settings().bronze_database_url.get_secret_value()


def test_segredo_nao_aparece_no_repr(sem_env):
    sem_env.setenv("OPENAI_API_KEY", "valor-segredo-ficticio")
    s = Settings()
    assert "segredo" not in repr(s)
    assert "segredo" not in str(s.openai_api_key)


@pytest.mark.parametrize(
    "valor",
    [None, "", "postgresql+psycopg://postgres.<ref>:<senha>@host:6543/postgres"],
)
def test_exigir_recusa_vazio_ou_placeholder(sem_env, valor):
    if valor is not None:
        sem_env.setenv("DATABASE_URL", valor)
    with pytest.raises(ConfiguracaoAusente, match="DATABASE_URL"):
        Settings().exigir("database_url")


def test_caminhos_relativos_viram_absolutos(sem_env):
    sem_env.setenv("LANDING_DIR", "data/landing")
    assert Settings().landing_dir == RAIZ_PROJETO / "data" / "landing"
    sem_env.setenv("LANDING_DIR", "/tmp/x")
    assert Settings().landing_dir == Path("/tmp/x")


def test_env_example_cobre_todos_os_campos():
    """Toda variável de Settings precisa estar documentada no .env.example (e vice-versa)."""
    texto = (RAIZ_PROJETO / ".env.example").read_text(encoding="utf-8")
    no_example = {
        linha.split("=", 1)[0].strip()
        for linha in texto.splitlines()
        if linha.strip() and not linha.lstrip().startswith("#") and "=" in linha
    }
    campos = {(info.alias or nome).upper() for nome, info in Settings.model_fields.items()}
    assert campos == no_example
