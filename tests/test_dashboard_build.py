"""Build dos dashboards com marts simulados (SPEC V3 seção 18): sem banco, roda no CI."""

import json
import re
from datetime import UTC

import pytest

from radar.dashboard import build as b
from radar.dashboard import queries

PAGINAS = [p["slug"] for p in b.carregar_config()["paginas"]]


def _fixtures():
    meta = {"atualizado_em": "2026-11-23T12:00:00+00:00", "periodo": {"inicio": "2026-08-22", "fim": "2026-11-19"},
            "versao": "0.5.0", "cobertura": "78/78", "execucao": {"id": 9, "modo": "incremental", "status": "success"},
            "temas": [{"nome": "Saúde", "cor": "#0F766E", "critico": False}],
            "ia": {"acuracia": 0.859, "acuracia_sem_vazamento": 0.81, "custo_total_usd": 0.83}}  # fmt: skip
    dados = {nome: [] for nome in queries.DATASETS}
    dados["kpis_diarios"] = [{"data": "2026-11-19", "proposicoes": 3, "proposicoes_relevantes": 1, "votacoes": 2,
                              "votacoes_aprovadas": 2, "eventos": 1, "discursos": 0, "valor_despesas": 10.5,
                              "alertas_enviados": 0}]  # fmt: skip
    dados["deputados"] = [
        {"id_deputado": 1, "nome": "Fulana", "sigla_partido": "XX", "sigla_uf": "SP"}
    ]
    dados.update(similares={}, meta=meta)
    return dados


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    r = b.build(out, fixtures=_fixtures())
    return out, r


def test_gera_as_8_paginas_com_titulo_idioma_e_navegacao(site):
    out, r = site
    assert r["paginas"] == 8 and len(PAGINAS) == 8
    for slug in PAGINAS:
        html = (out / f"{slug}.html").read_text(encoding="utf-8")
        assert '<html lang="pt-BR">' in html and re.search(r"<title>[^<]+</title>", html)
        assert '<meta name="viewport"' in html and '<meta name="description"' in html
        assert len(re.findall(r'<nav class="nav">.*?</nav>', html, re.S)) == 1
        assert all(f'href="{p}.html"' in html for p in PAGINAS)  # navegação com os 8 links
        assert html.count('aria-current="page"') == 1
        assert re.search(
            rf'src="static/js/pages/{slug}\.[0-9a-f]{{10}}\.js"', html
        )  # módulo da página (com hash)
        assert 'integrity="sha384-' in html  # ECharts da CDN com SRI


def test_datasets_no_formato_meta_dados_e_dentro_do_limite(site):
    out, _ = site
    for arq in (out / "data").glob("*.json"):
        assert arq.stat().st_size <= 1_000_000
        corpo = json.loads(arq.read_text(encoding="utf-8"))
        assert set(corpo) == {"meta", "dados"} and corpo["meta"]["dataset"] == arq.stem
    meta = json.loads((out / "data" / "meta.json").read_text(encoding="utf-8"))["dados"]
    assert meta["cobertura"] == "78/78"
    assert set(queries.DATASETS) | {"similares", "meta"} == {
        p.stem for p in (out / "data").glob("*.json")
    }


def test_paginas_referenciam_datasets_existentes(site):
    out, _ = site
    usados = set()
    for js in (out / "static" / "js" / "pages").glob("*.js"):
        usados |= set(re.findall(r"dados\('([a-z_]+)'\)", js.read_text(encoding="utf-8")))
    assert usados and usados <= set(queries.DATASETS) | {"similares", "meta"}


def test_cache_busting_reescreve_imports_dos_modulos(site):
    out, _ = site
    js = (out / "static" / "js" / "pages").glob("index.*.js").__next__().read_text(encoding="utf-8")
    imports = re.findall(r"from '([^']+)'", js)
    assert imports and all(re.search(r"\.[0-9a-f]{10}\.js$", i) for i in imports)
    for i in imports:  # cada import aponta para um arquivo que existe
        assert (out / "static" / "js" / "pages" / i).resolve().exists()


def test_json_grande_e_cortado_com_aviso(tmp_path):
    linhas = [{"i": n, "texto": "x" * 100} for n in range(2000)]
    tamanho = b.gravar_json(tmp_path / "x.json", "x", linhas, limite=50_000)
    corpo = json.loads((tmp_path / "x.json").read_text())
    assert tamanho <= 50_000 and corpo["meta"]["cortado"] and corpo["meta"]["linhas_total"] == 2000


def test_valores_numericos_e_datas_em_iso():
    from datetime import date, datetime
    from decimal import Decimal

    assert b._valor(Decimal("10")) == 10 and b._valor(Decimal("1.5")) == 1.5
    assert b._valor(date(2026, 11, 19)) == "2026-11-19"
    assert b._valor(datetime(2026, 11, 19, 12, tzinfo=UTC)).startswith("2026-11-19T12:00")


def test_publicacao_recusa_site_incompleto(tmp_path):
    from radar.dashboard.publish import validar_site

    with pytest.raises(RuntimeError):
        validar_site(tmp_path)
