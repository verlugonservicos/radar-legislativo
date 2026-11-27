"""Runner HTTP (SPEC 13 + ADR-031): token, assíncrono, consulta do job e 409 em concorrência."""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from radar.config import get_settings
from radar.runner import app as runner

TOKEN = "token-de-teste-123"
CAB = {"X-Runner-Token": TOKEN}


@pytest.fixture()
def cliente(monkeypatch):
    monkeypatch.setenv("RUNNER_TOKEN", TOKEN)
    get_settings.cache_clear()
    runner._jobs.clear()
    yield TestClient(runner.app)
    get_settings.cache_clear()
    if runner._trava.locked():
        runner._trava.release()


def _esperar(cliente, job, limite=5.0):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        r = cliente.get(f"/jobs/{job}", headers=CAB).json()
        if r["concluido"]:
            return r
        time.sleep(0.02)
    raise AssertionError("job não terminou")


def test_health_sem_token(cliente):
    assert cliente.get("/health").json() == {"ok": True, "ocupado": False}


def test_sem_token_ou_token_errado_da_401(cliente):
    assert cliente.post("/run").status_code == 401
    assert cliente.post("/run", headers={"X-Runner-Token": "errado"}).status_code == 401
    assert cliente.get("/jobs/x", headers={"X-Runner-Token": "errado"}).status_code == 401


def test_sem_token_configurado_recusa(cliente, monkeypatch):
    monkeypatch.setenv("RUNNER_TOKEN", "troque-por-um-token-aleatorio")
    get_settings.cache_clear()
    assert cliente.post("/run", headers=CAB).status_code == 503


def test_run_assincrono_e_consulta(cliente, monkeypatch):
    chamadas = {}

    def falso(modo, start, end, **kw):
        chamadas.update(modo=modo, **kw)
        return {
            "id_execucao": 99,
            "status": "success",
            "falhas": [],
            "duracao_s": 0.1,
            "start": None,
            "end": None,
        }

    monkeypatch.setattr("radar.pipeline.run_pipeline", falso)
    r = cliente.post("/run", headers=CAB, json={"mode": "incremental", "orcamento": 0.15})
    assert r.status_code == 202
    fim = _esperar(cliente, r.json()["job"])
    assert fim["status"] == "success" and fim["resultado"]["id_execucao"] == 99
    assert chamadas["modo"] == "incremental" and chamadas["ai_orcamento_usd"] == 0.15
    assert "ai" in chamadas["steps"] and chamadas["origem"] == "runner"


def test_falha_da_carga_vira_status_failed(cliente, monkeypatch):
    def quebra(*a, **k):
        raise RuntimeError("banco fora do ar")

    monkeypatch.setattr("radar.pipeline.run_pipeline", quebra)
    fim = _esperar(cliente, cliente.post("/run", headers=CAB).json()["job"])
    assert fim["status"] == "failed" and "banco fora do ar" in fim["erro"]
    assert not runner._trava.locked()


def test_409_em_concorrencia(cliente, monkeypatch):
    libera = threading.Event()

    def lenta(*a, **k):
        libera.wait(5)
        return {
            "id_execucao": 1,
            "status": "success",
            "falhas": [],
            "duracao_s": 0,
            "start": None,
            "end": None,
        }

    monkeypatch.setattr("radar.pipeline.run_pipeline", lenta)
    job = cliente.post("/run", headers=CAB).json()["job"]
    assert cliente.post("/run", headers=CAB).status_code == 409
    assert cliente.post("/dashboard/build", headers=CAB).status_code == 409
    assert cliente.get("/health").json()["ocupado"] is True
    libera.set()
    assert _esperar(cliente, job)["status"] == "success"


def test_job_desconhecido_404(cliente):
    assert cliente.get("/jobs/naoexiste", headers=CAB).status_code == 404


def test_dashboard_build_e_publish(cliente, monkeypatch):
    monkeypatch.setattr("radar.dashboard.build.build", lambda out: {"paginas": 9})
    monkeypatch.setattr("radar.dashboard.publish.publish", lambda out: {"commit": "abc"})
    assert cliente.post("/dashboard/build", headers=CAB).json()["resultado"] == {"paginas": 9}
    assert cliente.post("/dashboard/publish", headers=CAB).json()["resultado"] == {"commit": "abc"}


def test_dashboard_falha_devolve_500(cliente, monkeypatch):
    def quebra(out):
        raise RuntimeError("site incompleto")

    monkeypatch.setattr("radar.dashboard.publish.publish", quebra)
    r = cliente.post("/dashboard/publish", headers=CAB)
    assert r.status_code == 500 and "site incompleto" in r.json()["detail"]
