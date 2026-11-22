import re

from radar.db import SQL_DIR, SQL_INIT


def test_arquivos_do_init_existem():
    for nome in SQL_INIT:
        assert (SQL_DIR / nome).is_file(), nome


def test_schemas_das_quatro_camadas():
    sql = (SQL_DIR / "000_schemas.sql").read_text(encoding="utf-8")
    for camada in ("bronze", "silver", "gold", "ops"):
        assert f"CREATE SCHEMA IF NOT EXISTS {camada};" in sql


def test_ddl_idempotente():
    """Todo CREATE TABLE/INDEX/SCHEMA usa IF NOT EXISTS; views usam OR REPLACE."""
    for caminho in SQL_DIR.rglob("*.sql"):
        sql = re.sub(r"--[^\n]*", "", caminho.read_text(encoding="utf-8"))
        for comando in re.findall(r"CREATE\s+(?:UNIQUE\s+)?(TABLE|INDEX|SCHEMA)\s+(\S+)", sql):
            assert comando[1].upper() == "IF", (
                f"{caminho.name}: CREATE {comando[0]} sem IF NOT EXISTS"
            )
        assert not re.search(r"CREATE\s+VIEW", sql), f"{caminho.name}: use CREATE OR REPLACE VIEW"


def test_nenhuma_senha_em_sql():
    for caminho in SQL_DIR.rglob("*.sql"):
        sql = re.sub(r"--[^\n]*", "", caminho.read_text(encoding="utf-8"))
        assert "PASSWORD" not in sql.upper(), caminho.name


def test_permissoes_usam_papel_da_v3():
    sql = (SQL_DIR / "ops" / "003_roles.sql").read_text(encoding="utf-8")
    assert "radar_leitura" in sql
    assert "dashboard_leitura" not in sql


def test_views_de_tamanho():
    sql = (SQL_DIR / "ops" / "002_views_ops.sql").read_text(encoding="utf-8")
    assert "ops.vw_tamanho_schemas" in sql and "ops.vw_tamanho_banco" in sql
