"""Runner HTTP do pipeline (SPEC V3 seção 13, com a execução assíncrona do ADR-031).

O n8n chama este serviço pela rede interna do Swarm (`http://radar_runner:8000`); a porta nunca é
publicada. Uma execução por vez (trava global): pedidos concorrentes recebem 409.

- `GET  /health`              sem token: vivo + se há execução em andamento
- `POST /run`                 inicia a carga em segundo plano → 202 {"job": id}
- `GET  /jobs/{id}`           acompanha a carga (o n8n consulta até `concluido=true`)
- `POST /dashboard/build`     gera o site (síncrono, segundos)
- `POST /dashboard/publish`   envia o site ao branch gh-pages (síncrono, segundos)

Assíncrono porque a carga leva de 30 min a mais de 2 h: uma chamada HTTP aberta por todo esse tempo
caía por timeout no n8n (SPEC 15 previa 1 h).
"""

from __future__ import annotations

import logging
import secrets
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from radar.config import get_settings

log = logging.getLogger("radar.runner")


@asynccontextmanager
async def _ciclo(_: FastAPI):
    from radar.logging_setup import setup_logging

    setup_logging()  # mesmos arquivos de log da CLI (data/logs), visíveis fora do contêiner
    yield


app = FastAPI(title="Radar Legislativo — runner", version="1.0", docs_url=None, redoc_url=None,
              lifespan=_ciclo)  # fmt: skip

_trava = threading.Lock()
_jobs: dict[str, dict] = {}
MAX_JOBS = 50  # histórico curto em memória; o histórico completo fica em ops.execucoes


class PedidoRun(BaseModel):
    mode: Literal["incremental", "backfill"] = "incremental"
    start: date | None = None
    end: date | None = None
    endpoints: list[str] | None = None
    skip_ai: bool = False
    orcamento: float | None = Field(default=None, ge=0, le=5)  # teto de IA em US$ desta execução


def exigir_token(x_runner_token: str | None = Header(default=None)) -> None:
    """Token comparado em tempo constante; sem token configurado o runner recusa tudo."""
    esperado = get_settings().runner_token
    valor = esperado.get_secret_value() if esperado else ""
    if not valor or valor.startswith("troque"):
        raise HTTPException(503, "RUNNER_TOKEN não configurado")
    if not x_runner_token or not secrets.compare_digest(x_runner_token, valor):
        raise HTTPException(401, "token inválido")


def _registrar(tipo: str, parametros: dict) -> dict:
    job = {"job": uuid.uuid4().hex[:12], "tipo": tipo, "parametros": parametros, "status": "running",
           "concluido": False, "inicio": datetime.now().isoformat(timespec="seconds"),
           "fim": None, "resultado": None, "erro": None}  # fmt: skip
    _jobs[job["job"]] = job
    for antigo in list(_jobs)[:-MAX_JOBS]:
        _jobs.pop(antigo, None)
    return job


def _concluir(
    job: dict, status: str, resultado: dict | None = None, erro: str | None = None
) -> None:
    job.update(status=status, concluido=True, resultado=resultado, erro=erro,
               fim=datetime.now().isoformat(timespec="seconds"))  # fmt: skip


def _executar_carga(job: dict, pedido: PedidoRun) -> None:
    from radar.pipeline import ETAPAS_M5, run_pipeline

    try:
        steps = ETAPAS_M5 - {"ai"} if pedido.skip_ai else ETAPAS_M5
        r = run_pipeline(pedido.mode, pedido.start, pedido.end, steps=steps,
                         endpoints=set(pedido.endpoints) if pedido.endpoints else None,
                         origem="runner", ai_orcamento_usd=pedido.orcamento)  # fmt: skip
        r = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in r.items()}
        _concluir(job, r["status"], resultado=r, erro=", ".join(r.get("falhas") or []) or None)
    except Exception as erro:  # o job sempre termina com um status, nunca fica "running"
        log.exception("runner: carga falhou")
        _concluir(job, "failed", erro=str(erro)[:500])
    finally:
        _trava.release()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "ocupado": _trava.locked()}


@app.post("/run", status_code=202, dependencies=[Depends(exigir_token)])
def iniciar_run(pedido: PedidoRun | None = None) -> dict:
    pedido = pedido or PedidoRun()
    if not _trava.acquire(blocking=False):
        raise HTTPException(409, "já existe uma execução em andamento")
    job = _registrar("run", pedido.model_dump(mode="json"))
    threading.Thread(target=_executar_carga, args=(job, pedido), daemon=True).start()
    return {"job": job["job"], "status": job["status"]}


@app.get("/jobs/{job_id}", dependencies=[Depends(exigir_token)])
def consultar(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:  # runner reiniciado no meio: o n8n trata como falha
        raise HTTPException(404, "job desconhecido (o runner pode ter reiniciado)")
    return job


def _sincrono(tipo: str, fazer) -> dict:
    if not _trava.acquire(blocking=False):
        raise HTTPException(409, "já existe uma execução em andamento")
    job = _registrar(tipo, {})
    try:
        _concluir(job, "success", resultado=fazer())
    except Exception as erro:
        log.exception("runner: %s falhou", tipo)
        _concluir(job, "failed", erro=str(erro)[:500])
    finally:
        _trava.release()
    if job["status"] == "failed":
        raise HTTPException(500, job["erro"])
    return job


@app.post("/dashboard/build", dependencies=[Depends(exigir_token)])
def dashboard_build() -> dict:
    from radar.dashboard.build import build

    return _sincrono("dashboard_build", lambda: build(get_settings().dashboard_out_dir))


@app.post("/dashboard/publish", dependencies=[Depends(exigir_token)])
def dashboard_publish() -> dict:
    from radar.dashboard.publish import publish

    return _sincrono("dashboard_publish", lambda: publish(get_settings().dashboard_out_dir))
