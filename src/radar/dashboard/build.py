"""Build dos dashboards (SPEC V3 12.1): marts → `data/*.json` → páginas Jinja2 → `site/`.

O site é estático: as páginas buscam os JSON com `fetch` e desenham com ECharts no navegador.
Para testar localmente, sirva a pasta por HTTP (`python -m http.server -d site`), porque o
navegador bloqueia `fetch` em `file://`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import Engine, text

from radar import __version__
from radar.config import RAIZ_PROJETO
from radar.dashboard import queries

log = logging.getLogger("radar.dashboard")

AQUI = Path(__file__).parent
TEMPLATES = AQUI / "templates"
STATIC = AQUI / "static"
CONFIG = RAIZ_PROJETO / "config" / "dashboard.yaml"
GLOSSARIO = RAIZ_PROJETO / "config" / "glossario.yaml"
ECHARTS = {
    "src": "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js",
    "integrity": "sha384-Mx5lkUEQPM1pOJCwFtUICyX45KNojXbkWdYhkKUKsbv391mavbfoAmONbzkgYPzR",
}


def carregar_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def carregar_glossario() -> dict:
    """Termos do glossário; valida que todo `veja` aponta para um termo existente."""
    g = yaml.safe_load(GLOSSARIO.read_text(encoding="utf-8"))
    ids = {t["id"]: t["termo"] for s in g["secoes"] for t in s["termos"]}
    quebrados = [
        t["veja"]
        for s in g["secoes"]
        for t in s["termos"]
        if t.get("veja") and t["veja"] not in ids
    ]
    if quebrados:
        raise ValueError(f"glossário: 'veja' sem termo correspondente: {quebrados}")
    return {"glossario": g, "termos_por_id": ids}


# ------------------------------------------------------------------ JSON
def _valor(v: Any) -> Any:
    """Números como número, datas ISO, `null` para ausente (SPEC 12.1)."""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() and abs(v) < 2**53 else float(v)
    if isinstance(v, datetime):
        return v.astimezone(UTC).isoformat() if v.tzinfo else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_valor(x) for x in v]
    if isinstance(v, dict):
        return {k: _valor(x) for k, x in v.items()}
    return v


def _linhas(conn, sql: str) -> list[dict]:
    return [{k: _valor(v) for k, v in r.items()} for r in conn.execute(text(sql)).mappings()]


CORTADOS: list[str] = []  # datasets cortados no último build (aparecem no resumo)


def gravar_json(
    caminho: Path, nome: str, dados: Any, limite: int, extra: dict | None = None
) -> int:
    """Grava `{"meta": {...}, "dados": [...]}`; acima do limite corta linhas e avisa no próprio JSON."""
    meta = {"dataset": nome, "gerado_em": datetime.now(UTC).isoformat(), **(extra or {})}
    corpo = json.dumps({"meta": meta, "dados": dados}, ensure_ascii=False, separators=(",", ":"))
    if len(corpo.encode()) > limite and isinstance(dados, list) and dados:
        total = len(dados)
        while len(corpo.encode()) > limite and dados:
            dados = dados[: int(len(dados) * 0.9)]
            meta.update(cortado=True, linhas_total=total, linhas=len(dados))
            corpo = json.dumps(
                {"meta": meta, "dados": dados}, ensure_ascii=False, separators=(",", ":")
            )
        log.warning(
            "%s: JSON acima de %d bytes; cortado de %d para %d linhas — os totais do painel ficam "
            "incompletos: exporte um resumo em vez do detalhe",
            nome,
            limite,
            total,
            len(dados),
        )
        CORTADOS.append(nome)
    caminho.write_text(corpo, encoding="utf-8")
    return len(corpo.encode())


def exportar_dados(engine: Engine, data_dir: Path, limite: int) -> dict[str, int]:
    data_dir.mkdir(parents=True, exist_ok=True)
    tamanhos: dict[str, int] = {}
    with engine.connect() as conn:
        for nome, sql in queries.DATASETS.items():
            tamanhos[nome] = gravar_json(
                data_dir / f"{nome}.json", nome, _linhas(conn, sql), limite
            )
        similares: dict[str, list] = {}
        for r in _linhas(conn, queries.SIMILARES):
            similares.setdefault(str(r.pop("id_proposicao")), []).append(r)
        tamanhos["similares"] = gravar_json(
            data_dir / "similares.json", "similares", similares, limite
        )
        tamanhos["meta"] = gravar_json(data_dir / "meta.json", "meta", montar_meta(conn), limite)
    return tamanhos


def montar_meta(conn) -> dict:
    ultima = conn.execute(text(queries.ULTIMA_EXECUCAO)).mappings().first()
    periodo = conn.execute(text(queries.PERIODO)).mappings().one()
    cob = conn.execute(text(queries.COBERTURA)).mappings().one()
    aval = conn.execute(text(queries.AVALIACAO)).mappings().first()
    custo = conn.execute(text(queries.CUSTO_IA)).mappings().one()
    return _valor({
        "atualizado_em": ultima["finalizado_em"] if ultima else None,
        "execucao": {"id": ultima["id_execucao"], "modo": ultima["modo"], "status": ultima["status"]} if ultima else None,
        "periodo": {"inicio": periodo["inicio"], "fim": periodo["data_ref"]},
        "versao": __version__,
        "cobertura": f"{cob['ok']}/{cob['total']}",
        "temas": [dict(r) for r in conn.execute(text(queries.TEMAS)).mappings()],
        "ia": {
            "acuracia": aval["acuracia"], "acuracia_sem_vazamento": float(aval["acuracia_sem_vazamento"] or 0),
            "cobertura": aval["cobertura"], "limiar": aval["limiar"], "avaliadas": aval["avaliadas"],
            "avaliado_em": aval["criado_em"], "custo_total_usd": custo["total"],
        } if aval else {"custo_total_usd": custo["total"]},
    })  # fmt: skip


# ------------------------------------------------------------------ estáticos e páginas
def copiar_static(out_dir: Path) -> dict[str, str]:
    """Copia `static/` acrescentando hash de conteúdo aos CSS/JS (cache busting). Devolve o mapa."""
    destino = out_dir / "static"
    if destino.exists():
        shutil.rmtree(destino)
    mapa: dict[str, str] = {}
    for origem in sorted(STATIC.rglob("*")):
        if origem.is_dir():
            continue
        rel = origem.relative_to(STATIC).as_posix()
        nome = rel
        if origem.suffix in (".css", ".js"):
            h = hashlib.sha256(origem.read_bytes()).hexdigest()[:10]
            nome = f"{rel[: -len(origem.suffix)]}.{h}{origem.suffix}"
        alvo = destino / nome
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origem, alvo)
        mapa[rel] = f"static/{nome}"
    # módulos ES importam uns aos outros pelo nome original: reescreve os imports com o hash
    for rel, publicado in mapa.items():
        if rel.endswith(".js"):
            arq = out_dir / publicado
            conteudo = arq.read_text(encoding="utf-8")
            for outro, pub_outro in mapa.items():
                if outro.endswith(".js"):
                    base_outro = Path(outro).name
                    conteudo = conteudo.replace(f"/{base_outro}'", f"/{Path(pub_outro).name}'")
                    conteudo = conteudo.replace(f"./{base_outro}'", f"./{Path(pub_outro).name}'")
            arq.write_text(conteudo, encoding="utf-8")
    return mapa


def renderizar(out_dir: Path, cfg: dict, assets: dict[str, str]) -> list[str]:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True, lstrip_blocks=True,
    )  # fmt: skip
    env.globals.update(cfg=cfg, asset=lambda rel: assets[rel], echarts=ECHARTS,
                       ano=datetime.now().year, **carregar_glossario())  # fmt: skip
    geradas = []
    for pagina in cfg["paginas"]:
        tpl = env.get_template(f"pages/{pagina['slug']}.html.j2")
        html = tpl.render(pagina=pagina)
        (out_dir / f"{pagina['slug']}.html").write_text(html, encoding="utf-8")
        geradas.append(pagina["slug"])
    return geradas


def validar(out_dir: Path, cfg: dict) -> None:
    faltando = [p["slug"] for p in cfg["paginas"] if not (out_dir / f"{p['slug']}.html").exists()]
    if faltando or not (out_dir / "data" / "meta.json").exists():
        raise RuntimeError(f"build incompleto: páginas faltando {faltando} ou sem data/meta.json")


def gravar_fixtures(data_dir: Path, dados: dict[str, Any], limite: int) -> dict[str, int]:
    """Marts simulados (testes e CI, sem banco): {dataset: linhas} → data/*.json."""
    data_dir.mkdir(parents=True, exist_ok=True)
    return {
        nome: gravar_json(data_dir / f"{nome}.json", nome, _valor(v), limite)
        for nome, v in dados.items()
    }


def build(out_dir: Path, engine: Engine | None = None, readonly: bool = False,
          fixtures: dict[str, Any] | None = None) -> dict:  # fmt: skip
    """Gera o site completo em `out_dir`. Devolve {paginas, datasets, bytes, duracao_s}.

    Com `fixtures` ({dataset: dados}) não consulta o banco — é como o CI testa o build.
    """
    t0 = time.monotonic()
    CORTADOS.clear()
    cfg = carregar_config()
    out_dir.mkdir(parents=True, exist_ok=True)
    limite = cfg.get("limite_json_bytes", 1_000_000)
    # remove datasets de builds anteriores que não existem mais (ex.: despesas → despesas_mensal)
    data_dir = out_dir / "data"
    if data_dir.exists():
        for antigo in data_dir.glob("*.json"):
            antigo.unlink()
    if fixtures is not None:
        tamanhos = gravar_fixtures(out_dir / "data", fixtures, limite)
    else:
        from radar.db import get_engine

        engine = engine or get_engine("database_url_readonly" if readonly else "database_url")
        tamanhos = exportar_dados(engine, out_dir / "data", limite)
    assets = copiar_static(out_dir)
    paginas = renderizar(out_dir, cfg, assets)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    validar(out_dir, cfg)
    total = sum(p.stat().st_size for p in out_dir.rglob("*") if p.is_file())
    r = {"paginas": len(paginas), "datasets": len(tamanhos), "bytes": total,
         "duracao_s": round(time.monotonic() - t0, 1), "cortados": sorted(set(CORTADOS))}  # fmt: skip
    if r["cortados"]:
        log.warning(
            "ATENÇÃO: datasets cortados por tamanho (painéis incompletos): %s", r["cortados"]
        )
    log.info("dashboard: %d páginas, %d datasets, %.1f MB em %.1f s", r["paginas"], r["datasets"],
             total / 1e6, r["duracao_s"])  # fmt: skip
    return r
