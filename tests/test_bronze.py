"""Bronze (M2): chave, hash, linhas e carga idempotente."""

import json
import os
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from radar import db
from radar.bronze import loader
from radar.bronze.ddl import gerar_ddl
from radar.catalog.amostras import FIXTURES
from radar.catalog.loader import load_catalog

SPECS = {s.nome: s for s in load_catalog()}


def _envelope(dados, id_pai=None, id_execucao=1):
    return {
        "_meta": {"endpoint": "x", "url": "https://api/x", "params": {"a": 1}, "id_pai": id_pai,
                  "pagina": 1, "passe": 0, "extraido_em": "2026-11-22T10:00:00+00:00",
                  "id_execucao": id_execucao, "status_http": 200},
        "resposta": {"dados": dados, "links": []},
    }  # fmt: skip


def test_hash_estavel_independe_da_ordem_das_chaves():
    assert loader.payload_hash({"a": 1, "b": [1, 2]}) == loader.payload_hash({"b": [1, 2], "a": 1})
    assert loader.payload_hash({"a": 1}) != loader.payload_hash({"a": 2})


def test_chave_registro_com_pai_aninhados_e_nulos():
    despesas = SPECS["deputados_despesas"]
    reg = {
        "ano": 2026,
        "mes": 10,
        "codDocumento": 7,
        "numDocumento": None,
        "parcela": 0,
        "valorDocumento": 12.5,
    }
    assert loader.chave_registro(despesas, reg, "204528") == "204528|2026|10|7||0|12.5"
    votos = SPECS["votacoes_votos"]
    assert loader.chave_registro(votos, {"deputado_": {"id": 9}}, "123-4") == "123-4|9"
    assert loader.chave_registro(SPECS["referencias_deputados"], {"x": []}, None) == "objeto_unico"
    hist = SPECS["grupos_historico"]
    assert loader.chave_registro(hist, {}, "2") == "2|||"


def test_linhas_lista_objeto_e_vazio():
    spec = SPECS["eventos"]
    raiz = Path("/tmp/landing")
    arq = raiz / "eventos/dt=2026-11-01/page_001.json"
    assert (
        len(list(loader.linhas_do_envelope(spec, _envelope([{"id": 1}, {"id": 2}]), arq, raiz)))
        == 2
    )
    det = SPECS["eventos_detalhe"]
    linhas = list(loader.linhas_do_envelope(det, _envelope({"id": 5}, id_pai="5"), arq, raiz))
    assert (
        len(linhas) == 1
        and linhas[0][1] == "5"
        and linhas[0][8] == "eventos/dt=2026-11-01/page_001.json"
    )
    assert list(loader.linhas_do_envelope(spec, _envelope([]), arq, raiz)) == []


def test_ddl_tem_constraint_de_versao_e_view_atual():
    ddl = gerar_ddl(SPECS["proposicoes_tramitacoes"])
    assert "UNIQUE (chave_registro, payload_hash)" in ddl
    assert "CREATE OR REPLACE VIEW bronze.vw_proposicoes_tramitacoes_atual" in ddl


# ------------------------------------------------------------------ integração
pytestmark_integration = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL não definida"
)


@pytest.fixture
def engine():
    eng = db.criar_engine(os.environ["DATABASE_URL"])
    db.db_init(eng)
    yield eng
    eng.dispose()


def _arquivos_da_fixture(nome: str, id_execucao: int):
    fx = json.loads((FIXTURES / f"{nome}.json").read_text(encoding="utf-8"))
    meta = fx.pop("_meta")
    env = _envelope(fx["dados"], id_pai=None if meta["id_pai"] is None else str(meta["id_pai"]),
                    id_execucao=id_execucao)  # fmt: skip
    env["_meta"]["url"] = meta["url"]
    return [(FIXTURES / f"{nome}.json", env)]


@pytest.mark.integration
@pytestmark_integration
def test_db_init_cria_78_tabelas_e_views(engine):
    with engine.connect() as conn:
        tabelas = conn.execute(text(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'bronze'")).scalar_one()  # fmt: skip
        views = conn.execute(text(
            "SELECT count(*) FROM pg_views WHERE schemaname = 'bronze' AND viewname LIKE 'vw\\_%\\_atual'")).scalar_one()  # fmt: skip
        catalogo = conn.execute(
            text("SELECT count(*) FROM ops.catalogo_endpoints WHERE NOT obsoleto")
        ).scalar_one()
        cobertura = conn.execute(text("SELECT count(*) FROM ops.vw_cobertura_atual")).scalar_one()
    assert (tabelas, views, catalogo, cobertura) == (78, 78, 78, 78)


@pytest.mark.integration
@pytestmark_integration
@pytest.mark.parametrize(
    "nome", ["votacoes_votos", "deputados_detalhe", "referencias_proposicoes", "grupos_membros"]
)
def test_carga_idempotente_e_nova_versao(engine, nome):
    spec = SPECS[nome]
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE bronze.{nome}"))
    r1 = loader.load_endpoint(spec, engine, _arquivos_da_fixture(nome, 1), 1)
    r2 = loader.load_endpoint(spec, engine, _arquivos_da_fixture(nome, 2), 2)
    assert r1.inseridos == r1.lidos > 0
    assert r2.inseridos == 0 and r2.ignorados == r2.lidos  # reexecução não duplica

    arquivos = _arquivos_da_fixture(nome, 3)
    dados = arquivos[0][1]["resposta"]["dados"]
    primeiro = dados[0] if isinstance(dados, list) else dados
    primeiro["_campo_alterado_no_teste"] = True
    r3 = loader.load_endpoint(spec, engine, arquivos, 3)
    assert r3.inseridos == 1  # só o registro alterado vira nova versão

    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT count(*) FROM bronze.{nome}")).scalar_one()
        atuais = conn.execute(text(f"SELECT count(*) FROM bronze.vw_{nome}_atual")).scalar_one()
        payload = conn.execute(text(
            f"SELECT payload FROM bronze.vw_{nome}_atual ORDER BY carregado_em DESC, id DESC LIMIT 1")).scalar_one()  # fmt: skip
    assert total == r1.lidos + 1 and atuais == r1.lidos
    assert payload.get("_campo_alterado_no_teste") is True


@pytest.mark.integration
@pytestmark_integration
def test_payload_identico_a_resposta(engine):
    """Critério de aceite 4: o payload da Bronze é igual, campo a campo, ao registro da API."""
    nome = "proposicoes_detalhe"
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE bronze.{nome}"))
    arquivos = _arquivos_da_fixture(nome, 1)
    loader.load_endpoint(SPECS[nome], engine, arquivos, 1)
    with engine.connect() as conn:
        payload = conn.execute(text(f"SELECT payload FROM bronze.{nome}")).scalar_one()
    assert payload == arquivos[0][1]["resposta"]["dados"]


def test_retencao_desligada_nao_apaga():
    assert loader.aplicar_retencao(None, SPECS["eventos"], 0) == 0
    _ = date  # noqa: F841 (import usado por outros testes do módulo)
