"""Extração (M2) sem rede: cliente, janelas, Landing e extrator genérico."""

import json
import threading
import time
from datetime import date

import pytest
import responses

from radar.catalog.models import EndpointSpec
from radar.config import Settings
from radar.extract import landing, windows
from radar.extract.client import CamaraAPIError, CamaraClient, _Throttle
from radar.extract.generic import GenericExtractor
from radar.extract.ids import extrair_campo, resolve_ids
from radar.run_context import RunContext

BASE = "https://dadosabertos.camara.leg.br/api/v2"


@pytest.fixture
def ambiente(sem_env, tmp_path):
    """Landing em pasta temporária e throttle zerado."""
    sem_env.setenv("LANDING_DIR", str(tmp_path / "landing"))
    sem_env.setenv("CAMARA_THROTTLE_SEGUNDOS", "0")
    sem_env.setenv("EXTRACAO_WORKERS", "2")
    return tmp_path


def _ctx(id_execucao=1, start=date(2026, 11, 1), end=date(2026, 11, 7)):
    return RunContext(
        id_execucao, "backfill", start, end, date(2026, 11, 22), engine=None, settings=Settings()
    )


# ------------------------------------------------------------------ cliente
@responses.activate
def test_paginacao_segue_links_next(ambiente):
    responses.get(f"{BASE}/deputados", json={"dados": [{"id": 1}], "links": [
        {"rel": "next", "href": f"{BASE}/deputados?pagina=2&itens=1"}]})  # fmt: skip
    responses.get(f"{BASE}/deputados?pagina=2&itens=1", json={"dados": [{"id": 2}], "links": []})
    paginas = list(CamaraClient().iter_pages("/deputados", {"idLegislatura": 57}))
    assert [p.page_number for p in paginas] == [1, 2]
    assert "pagina=1" in paginas[0].url and "itens=100" in paginas[0].url


@responses.activate
def test_next_repetido_encerra(ambiente):
    proxima = f"{BASE}/x?pagina=2"
    responses.get(f"{BASE}/x", json={"dados": [], "links": [{"rel": "next", "href": proxima}]})
    responses.get(proxima, json={"dados": [], "links": [{"rel": "next", "href": proxima}]})
    assert len(list(CamaraClient().iter_pages("/x"))) == 2


@responses.activate
def test_nao_paginado_uma_pagina_sem_parametros_de_pagina(ambiente):
    responses.get(f"{BASE}/votacoes/1/votos", json={"dados": [{"a": 1}] * 3, "links": []})
    paginas = list(CamaraClient().iter_pages("/votacoes/1/votos", paginado=False))
    assert len(paginas) == 1 and "pagina" not in paginas[0].url


@responses.activate
def test_404_devolve_none_e_400_levanta(ambiente):
    responses.get(f"{BASE}/deputados/999", status=404)
    responses.get(f"{BASE}/votacoes", status=400, body='{"detail":"A diferença entre as datas"}')
    cliente = CamaraClient()
    assert cliente.get("/deputados/999") is None
    with pytest.raises(CamaraAPIError, match="HTTP 400"):
        cliente.get("/votacoes", {"dataInicio": "2026-01-01", "dataFim": "2026-11-21"})


def test_throttle_global_entre_threads():
    throttle = _Throttle(0.05)
    inicio = time.monotonic()
    threads = [threading.Thread(target=throttle.aguardar) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert time.monotonic() - inicio >= 0.19  # 5 chamadas → pelo menos 4 intervalos


# ------------------------------------------------------------------ janelas
def test_by_year_nunca_cruza_o_ano_nem_passa_de_31_dias():
    janelas = windows.by_year(date(2025, 11, 20), date(2026, 2, 10))
    assert all(i.year == f.year for i, f in janelas)
    assert all((f - i).days < 31 for i, f in janelas)
    assert janelas[0][0] == date(2025, 11, 20) and janelas[-1][1] == date(2026, 2, 10)


def test_monthly_com_reprocessamento():
    assert windows.monthly(date(2026, 2, 5), date(2026, 3, 1), 3) == [
        (2025, 11), (2025, 12), (2026, 1), (2026, 2), (2026, 3)]  # fmt: skip


def test_daily_e_render_params():
    assert len(windows.daily(date(2026, 11, 1), date(2026, 11, 7))) == 7
    assert windows.render_params({"a": "{inicio}", "b": "x"}, {"inicio": "2026-11-01"}) == {
        "a": "2026-11-01", "b": "x"}  # fmt: skip


def test_recortes_por_tipo_de_janela():
    hoje, ini, fim = date(2026, 11, 22), date(2026, 11, 1), date(2026, 11, 7)
    diaria = EndpointSpec(nome="p", path="/p", grupo="p", tipo="lista",
                          janela={"tipo": "periodo", "particao": "diaria"})  # fmt: skip
    inteiro = EndpointSpec(nome="d", path="/d/{id}/x", grupo="d", tipo="subrecurso",
                           ids={"de": "d"}, janela={"tipo": "periodo"})  # fmt: skip
    mensal = EndpointSpec(nome="m", path="/m", grupo="m", tipo="lista",
                          janela={"tipo": "mensal", "reprocessar_meses": 1})  # fmt: skip
    sem = EndpointSpec(nome="s", path="/s", grupo="s", tipo="lista")
    assert len(windows.recortes(diaria, ini, fim, hoje)) == 7
    assert windows.recortes(inteiro, ini, fim, hoje) == [
        (ini, {"inicio": "2026-11-01", "fim": "2026-11-07"})
    ]
    assert [r[0] for r in windows.recortes(mensal, ini, fim, hoje)] == [
        date(2026, 10, 1),
        date(2026, 11, 1),
    ]
    assert windows.recortes(sem, ini, fim, hoje) == [(hoje, {})]


# ------------------------------------------------------------------ landing
def test_landing_envelope_nome_e_filtro_por_execucao(ambiente):
    ref = date(2026, 11, 3)
    arq = landing.write_page("eventos_pauta", ref, {"dados": [1]}, 1, url="u", params={"a": 1},
                             id_execucao=7, id_pai=55, passe=1)  # fmt: skip
    landing.write_page("eventos_pauta", ref, {"dados": [2]}, 1, url="u", params=None, id_execucao=8)
    landing.write_manifest("eventos_pauta", ref, {"ok": True})
    assert arq.name == "pai_55_p1_page_001.json"
    env = json.loads(arq.read_text())
    assert env["_meta"]["id_pai"] == "55" and env["resposta"] == {"dados": [1]}
    assert len(list(landing.iter_files("eventos_pauta", ref, ref))) == 2  # manifesto fica de fora
    assert len(list(landing.iter_files("eventos_pauta", ref, ref, id_execucao=7))) == 1
    (landing.partition_dir("eventos_pauta", ref) / "x_page_001.json.tmp").write_text("{}")
    assert landing.prune_partition("eventos_pauta", ref, {arq}) == 2  # a outra página e o .tmp
    assert [a for a, _ in landing.iter_files("eventos_pauta", ref, ref)] == [arq]
    assert (landing.partition_dir("eventos_pauta", ref) / "_manifest.json").exists()


# ------------------------------------------------------------------ ids e extrator
def test_extrair_campo():
    r = {"id": 1, "orgaos": [{"id": 3}, {"id": None}], "a": {"b": "x"}}
    assert extrair_campo(r, "orgaos[].id") == [3]
    assert extrair_campo(r, "a.b") == ["x"]
    assert extrair_campo("texto", "id") == []


@responses.activate
def test_extrator_lista_e_subrecurso_com_ids_da_landing(ambiente):
    lista = EndpointSpec(nome="eventos", path="/eventos", grupo="eventos", tipo="lista", paginado=True,
                         janela={"tipo": "periodo", "params": {"dataInicio": "{inicio}", "dataFim": "{fim}"}})  # fmt: skip
    sub = EndpointSpec(nome="eventos_pauta", path="/eventos/{id}/pauta", grupo="eventos",
                       tipo="subrecurso", ids={"de": "eventos", "filtro": "janela"})  # fmt: skip
    responses.get(
        f"{BASE}/eventos", json={"dados": [{"id": 10}, {"id": 11}, {"id": 10}], "links": []}
    )
    responses.get(f"{BASE}/eventos/10/pauta", json={"dados": [{"ordem": 1}], "links": []})
    responses.get(f"{BASE}/eventos/11/pauta", status=503)
    ctx = _ctx()
    extrator = GenericExtractor(CamaraClient())

    r1 = extrator.run(lista, ctx)
    assert (r1.registros, r1.paginas, r1.erros) == (3, 1, [])
    assert resolve_ids(sub, ctx) == ["10", "11"]  # únicos, na ordem

    r2 = extrator.run(sub, ctx)
    assert r2.registros == 1 and len(r2.erros) == 1 and r2.erros[0]["id_pai"] == "11"
    manifesto = json.loads(
        (landing.partition_dir("eventos_pauta", ctx.hoje) / "_manifest.json").read_text()
    )
    assert manifesto["ids"] == 2 and manifesto["registros"] == 1
    assert "dataInicio=2026-11-01" in responses.calls[0].request.url


# ------------------------------------------------------------------ limpeza segura e órfãos
def _sub():
    return EndpointSpec(nome="eventos_pauta", path="/eventos/{id}/pauta", grupo="eventos",
                        tipo="subrecurso", ids={"de": "eventos", "filtro": "janela"})  # fmt: skip


def _lista_eventos(ctx, ids):
    landing.write_page("eventos", ctx.hoje, {"dados": [{"id": i} for i in ids]}, 1, url="u",
                       params=None, id_execucao=ctx.id_execucao)  # fmt: skip


@responses.activate
def test_falha_na_api_preserva_arquivos_da_execucao_anterior(ambiente):
    """A partição não é apagada antes do download: com erro, o que já existia fica."""
    ctx1, ctx2 = _ctx(1), _ctx(2)
    _lista_eventos(ctx1, [10, 11])
    responses.get(f"{BASE}/eventos/10/pauta", json={"dados": [{"ordem": 1}], "links": []})
    responses.get(f"{BASE}/eventos/11/pauta", json={"dados": [{"ordem": 2}], "links": []})
    GenericExtractor(CamaraClient()).run(_sub(), ctx1)

    responses.replace(responses.GET, f"{BASE}/eventos/10/pauta", status=503)
    responses.replace(responses.GET, f"{BASE}/eventos/11/pauta", status=503)
    _lista_eventos(ctx2, [10, 11])
    r = GenericExtractor(CamaraClient()).run(_sub(), ctx2)
    assert len(r.erros) == 2
    arquivos = list(landing.iter_files("eventos_pauta", ctx1.hoje, ctx1.hoje, id_execucao=1))
    assert len(arquivos) == 2  # nada se perdeu


@responses.activate
def test_sucesso_remove_so_as_sobras_da_execucao_anterior(ambiente):
    ctx1, ctx2 = _ctx(1), _ctx(2)
    _lista_eventos(ctx1, [10, 11])
    responses.get(f"{BASE}/eventos/10/pauta", json={"dados": [{"ordem": 1}], "links": []})
    responses.get(f"{BASE}/eventos/11/pauta", json={"dados": [{"ordem": 2}], "links": []})
    GenericExtractor(CamaraClient()).run(_sub(), ctx1)

    _lista_eventos(ctx2, [10])  # o evento 11 saiu da origem
    GenericExtractor(CamaraClient()).run(_sub(), ctx2)
    nomes = sorted(a.name for a, _ in landing.iter_files("eventos_pauta", ctx2.hoje, ctx2.hoje))
    assert nomes == ["pai_10_page_001.json"]  # regravado; o do 11 (sobra) foi removido


def _detalhe_deputado():
    return EndpointSpec(nome="deputados_detalhe", path="/deputados/{id}", grupo="deputados",
                        tipo="detalhe", ids={"de": "deputados", "incluir_orfaos": True})  # fmt: skip


def test_orfaos_somados_aos_ids_da_origem(ambiente):
    ctx = _ctx()
    landing.write_page("deputados", ctx.hoje, {"dados": [{"id": 1}, {"id": 2}]}, 1, url="u",
                       params=None, id_execucao=1)  # fmt: skip
    ctx.orfaos = ["2", "99"]
    assert resolve_ids(_detalhe_deputado(), ctx) == ["1", "2", "99"]


def test_endpoint_forcado_pelos_orfaos_busca_so_os_orfaos(ambiente):
    ctx = _ctx()
    ctx.orfaos, ctx.apenas_orfaos = ["99", "98"], {"deputados_detalhe"}
    assert resolve_ids(_detalhe_deputado(), ctx) == ["99", "98"]


def test_pipeline_forca_detalhe_do_deputado_quando_ha_orfaos(ambiente, monkeypatch):
    from radar import pipeline

    detalhe, lista = _detalhe_deputado(), _sub()
    monkeypatch.setattr(pipeline, "deputados_orfaos", lambda engine: ["99"])
    ctx = _ctx()
    specs = pipeline._incluir_orfaos(ctx, [lista, detalhe], [lista], None)
    assert [s.nome for s in specs] == ["eventos_pauta", "deputados_detalhe"]
    assert ctx.apenas_orfaos == {"deputados_detalhe"} and ctx.etapas["orfaos"] == {"deputados": 1}
    # já selecionado pela frequência → não é "só órfãos" (soma aos IDs normais)
    ctx2 = _ctx()
    pipeline._incluir_orfaos(ctx2, [detalhe], [detalhe], None)
    assert ctx2.apenas_orfaos == set()
    # filtro --endpoints respeitado
    ctx3 = _ctx()
    assert pipeline._incluir_orfaos(ctx3, [lista, detalhe], [lista], {"eventos_pauta"}) == [lista]
