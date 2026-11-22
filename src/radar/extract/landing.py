"""Camada Landing: JSON integral da API em disco, antes de qualquer carga (SPEC V3 seção 5.2)."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

from radar.config import get_settings


def _raiz() -> Path:
    return get_settings().landing_dir


def partition_dir(endpoint: str, ref: date) -> Path:
    return _raiz() / endpoint / f"dt={ref.isoformat()}"


def _nome(page: int, id_pai: object | None, passe: int) -> str:
    pai = f"pai_{id_pai}_" if id_pai is not None else ""
    p = f"p{passe}_" if passe else ""
    return f"{pai}{p}page_{page:03d}.json"


def _gravar_atomico(destino: Path, conteudo: dict) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".tmp")
    tmp.write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, destino)
    return destino


def write_page(
    endpoint: str,
    ref: date,
    payload: dict,
    page: int,
    *,
    url: str,
    params: dict | None,
    id_execucao: int,
    status_http: int = 200,
    id_pai: object | None = None,
    passe: int = 0,
) -> Path:
    """Grava uma página: envelope `_meta` + `resposta` integral."""
    envelope = {
        "_meta": {
            "endpoint": endpoint,
            "url": url,
            "params": params,
            "id_pai": None if id_pai is None else str(id_pai),
            "pagina": page,
            "passe": passe,
            "extraido_em": datetime.now(UTC).isoformat(),
            "id_execucao": id_execucao,
            "status_http": status_http,
        },
        "resposta": payload,
    }
    return _gravar_atomico(partition_dir(endpoint, ref) / _nome(page, id_pai, passe), envelope)


def write_manifest(endpoint: str, ref: date, manifest: dict) -> Path:
    return _gravar_atomico(partition_dir(endpoint, ref) / "_manifest.json", manifest)


def clear_partition(endpoint: str, ref: date, id_pai: object | None = None) -> None:
    """Remove a partição inteira (ou só os arquivos de um pai) antes de regravar."""
    pasta = partition_dir(endpoint, ref)
    if not pasta.exists():
        return
    if id_pai is None:
        shutil.rmtree(pasta)
    else:
        for arquivo in pasta.glob(f"pai_{id_pai}_*page_*.json"):
            arquivo.unlink()


def iter_files(
    endpoint: str, start: date, end: date, id_execucao: int | None = None
) -> Iterator[tuple[Path, dict]]:
    """(arquivo, envelope) das partições no período; opcionalmente só de uma execução."""
    base = _raiz() / endpoint
    if not base.exists():
        return
    for pasta in sorted(base.glob("dt=*")):
        try:
            ref = date.fromisoformat(pasta.name[3:])
        except ValueError:
            continue
        if not start <= ref <= end:
            continue
        for arquivo in sorted(pasta.glob("*page_*.json")):
            envelope = json.loads(arquivo.read_text(encoding="utf-8"))
            if id_execucao is not None and envelope["_meta"].get("id_execucao") != id_execucao:
                continue
            yield arquivo, envelope
