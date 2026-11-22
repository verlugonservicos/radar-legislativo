"""Testes contra um PostgreSQL real. Rodam com: pytest -m integration (requer DATABASE_URL)."""

import os

import pytest
from sqlalchemy import text

from radar import db

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL não definida"),
]

TABELAS_OPS = {
    "pipeline_execucoes",
    "controle_ingestao",
    "catalogo_endpoints",
    "cobertura_endpoints",
    "qualidade_rejeicoes",
    "custos_ia",
    "alertas_enviados",
}


@pytest.fixture
def engine():
    eng = db.criar_engine(os.environ["DATABASE_URL"])
    yield eng
    eng.dispose()


def test_db_init_idempotente(engine):
    db.db_init(engine)
    db.db_init(engine)
    info = db.verificar_conexao(engine)
    assert all(info["camadas"].values())


def test_tabelas_e_views_ops(engine):
    db.db_init(engine)
    with engine.connect() as conn:
        tabelas = set(
            conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema='ops'")
            ).scalars()
        )
        camadas = set(conn.execute(text("SELECT schema FROM ops.vw_tamanho_schemas")).scalars())
    assert tabelas >= TABELAS_OPS
    assert "vw_tamanho_schemas" in tabelas
    assert camadas == {"bronze", "silver", "gold", "ops"}


def test_status_invalido_rejeitado(engine):
    db.db_init(engine)
    with pytest.raises(Exception, match="ck_execucoes_status"), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ops.pipeline_execucoes (modo, origem, status) VALUES ('x','cli','ok')"
            )
        )


def test_avisos_do_servidor_sao_capturados(engine, tmp_path):
    script = tmp_path / "aviso.sql"
    script.write_text("DO $$ BEGIN RAISE NOTICE 'teste 100%% ok'; END $$;", encoding="utf-8")
    assert db.executar_script(engine, script) == ["teste 100% ok"]
