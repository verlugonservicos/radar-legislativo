"""Pipeline M2 ponta a ponta: API simulada → Landing → Bronze → ops."""

import os
from datetime import date

import pytest
import responses
from sqlalchemy import text

from radar import db, pipeline
from radar.catalog.models import EndpointSpec

BASE = "https://dadosabertos.camara.leg.br/api/v2"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL não definida"),
]

SPECS = [
    EndpointSpec(nome="partidos", path="/partidos", grupo="partidos", tipo="lista", paginado=True,
                 params={"idLegislatura": "{id_legislatura}"}, chave=["id"]),
    EndpointSpec(nome="partidos_detalhe", path="/partidos/{id}", grupo="partidos", tipo="detalhe",
                 ids={"de": "partidos"}, chave=["id"], frequencia="semanal"),
]  # fmt: skip


@pytest.fixture
def ambiente(monkeypatch, tmp_path):
    monkeypatch.setenv("LANDING_DIR", str(tmp_path / "landing"))
    monkeypatch.setenv("CAMARA_THROTTLE_SEGUNDOS", "0")
    monkeypatch.setattr(pipeline, "load_catalog", lambda: SPECS)
    eng = db.get_engine()
    db.db_init(eng)
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE bronze.partidos, bronze.partidos_detalhe"))
        conn.execute(text("DELETE FROM ops.controle_ingestao WHERE endpoint LIKE 'partidos%'"))
    return eng


@responses.activate
def test_backfill_duas_vezes(ambiente):
    responses.get(
        f"{BASE}/partidos",
        json={"dados": [{"id": 1, "sigla": "A"}, {"id": 2, "sigla": "B"}], "links": []},
    )
    responses.get(f"{BASE}/partidos/1", json={"dados": {"id": 1, "nome": "Partido A"}, "links": []})
    responses.get(f"{BASE}/partidos/2", json={"dados": {"id": 2, "nome": "Partido B"}, "links": []})

    r1 = pipeline.run_pipeline("backfill", date(2026, 11, 1), date(2026, 11, 7), force=True)
    r2 = pipeline.run_pipeline("backfill", date(2026, 11, 1), date(2026, 11, 7), force=True)

    assert r1["status"] == r2["status"] == "success" and r1["endpoints"] == 2
    with ambiente.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM bronze.partidos")).scalar_one() == 2
        assert conn.execute(text("SELECT count(*) FROM bronze.partidos_detalhe")).scalar_one() == 2
        cob = dict(conn.execute(text(
            "SELECT endpoint, inseridos FROM ops.cobertura_endpoints WHERE id_execucao = :id"), {"id": r2["id_execucao"]}).all())  # fmt: skip
        status = conn.execute(text(
            "SELECT status FROM ops.pipeline_execucoes WHERE id_execucao = :id"), {"id": r1["id_execucao"]}).scalar_one()  # fmt: skip
        wm = conn.execute(text(
            "SELECT ultima_data_ref FROM ops.controle_ingestao WHERE endpoint='partidos_detalhe' AND camada='bronze'")).scalar_one()  # fmt: skip
    assert cob == {"partidos": 0, "partidos_detalhe": 0}  # 2ª execução: nada novo
    assert status == "success" and wm == date(2026, 11, 7)
    assert "idLegislatura=57" in responses.calls[0].request.url


@responses.activate
def test_falha_num_endpoint_vira_partial(ambiente):
    responses.get(f"{BASE}/partidos", json={"dados": [{"id": 1}], "links": []})
    responses.get(f"{BASE}/partidos/1", status=500)
    r = pipeline.run_pipeline("backfill", date(2026, 11, 1), date(2026, 11, 7), force=True)
    assert r["status"] == "partial" and r["falhas"] == ["partidos_detalhe"]
