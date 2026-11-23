"""Silver e Gold contra PostgreSQL real: reconciliação, idempotência, SCD2 e fidelidade."""

import json
import os

import pytest
from sqlalchemy import text

from radar import db
from radar.bronze import loader
from radar.catalog.amostras import FIXTURES
from radar.catalog.loader import load_catalog
from radar.gold.builder import build
from radar.silver.runner import run_silver

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL não definida"),
]


@pytest.fixture(scope="module")
def engine():
    eng = db.criar_engine(os.environ["DATABASE_URL"])
    db.db_init(eng)
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM ops.controle_ingestao WHERE camada = 'silver'"))
        for s in load_catalog():
            conn.execute(text(f"TRUNCATE bronze.{s.nome}"))
        conn.execute(text("TRUNCATE " + ", ".join(
            f"silver.{t}" for t in conn.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'silver'")).scalars())))  # fmt: skip
        conn.execute(
            text("TRUNCATE gold.fato_voto, gold.fato_despesa, gold.fato_proposicao CASCADE")
        )
        conn.execute(text("TRUNCATE gold.dim_deputado CASCADE"))
    for s in load_catalog():
        fx = json.loads((FIXTURES / f"{s.nome}.json").read_text(encoding="utf-8"))
        meta = fx.pop("_meta")
        env = {"_meta": {"url": meta["url"], "params": None, "pagina": 1, "id_execucao": 1,
                         "id_pai": None if meta["id_pai"] is None else str(meta["id_pai"]),
                         "extraido_em": "2026-11-22T10:00:00+00:00"}, "resposta": fx}  # fmt: skip
        loader.load_endpoint(s, eng, [(FIXTURES / f"{s.nome}.json", env)], 1)
    yield eng
    eng.dispose()


def _um(engine, sql, **p):
    with engine.connect() as conn:
        return conn.execute(text(sql), p).scalar_one()


def test_silver_reconcilia_todas_as_entidades_e_e_incremental(engine):
    r1 = run_silver(engine)
    assert not [n for n, c in r1.items() if "falha" in c]
    assert all(c["reconciliado"] for c in r1.values())
    assert _um(engine, "SELECT count(*) FROM silver.deputados") > 0
    r2 = run_silver(engine)  # nada novo na Bronze: só as referências (sempre completas) são relidas
    assert sum(c["lidos"] for n, c in r2.items() if n not in ("referencias", "ufs")) == 0


def test_gold_sem_falhas_idempotente_e_preserva_ia(engine):
    run_silver(engine, completa=True)
    g1 = build(engine)
    assert not [a for a, c in g1["arquivos"].items() if "falha" in c]
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE gold.fato_proposicao SET tema_ia = 'Saúde', relevancia_score = 0.9")
        )
    g2 = build(engine)
    assert g1["contagens"] == g2["contagens"]  # reexecução não duplica
    assert (
        _um(
            engine,
            "SELECT count(*) FROM gold.fato_proposicao WHERE tema_ia IS DISTINCT FROM 'Saúde'",
        )
        == 0
    )
    assert g2["integridade"]["deputado_com_mais_de_uma_versao_atual"] == 0
    assert _um(engine, "SELECT count(*) FROM gold.dim_tema") == 13


def test_scd2_e_fidelidade_partidaria(engine):
    """Troca de partido gera 2 versões; o voto liga à versão da data; 'Liberado' fica fora."""
    with engine.begin() as conn:
        conn.execute(
            text("""
            INSERT INTO silver.deputados (id_deputado, nome, sigla_partido, sigla_uf) VALUES (999001, 'Teste', 'BBB', 'SP')
            ON CONFLICT (id_deputado) DO NOTHING;
            INSERT INTO silver.deputados_historico (id_deputado, data_hora, id_legislatura, nome, sigla_partido, sigla_uf, situacao)
            VALUES (999001, '2025-01-01 10:00-03', 57, 'Teste', 'AAA', 'SP', 'Exercício'),
                   (999001, '2025-06-01 10:00-03', 57, 'Teste', 'AAA', 'SP', 'Exercício'),
                   (999001, '2026-03-01 10:00-03', 57, 'Teste', 'BBB', 'SP', 'Exercício')
            ON CONFLICT DO NOTHING;
            INSERT INTO silver.votacoes (id_votacao, data, data_hora_registro) VALUES
                ('T-1', '2025-08-01', '2025-08-01 15:00-03'), ('T-2', '2026-09-01', '2026-09-01 15:00-03')
            ON CONFLICT DO NOTHING;
            INSERT INTO silver.votos (id_votacao, id_deputado, tipo_voto, data_registro_voto, sigla_partido, sigla_uf) VALUES
                ('T-1', 999001, 'Sim', '2025-08-01 15:00-03', 'AAA', 'SP'),
                ('T-2', 999001, 'Não', '2026-09-01 15:00-03', 'BBB', 'SP')
            ON CONFLICT DO NOTHING;
            INSERT INTO silver.votacoes_orientacoes (id_votacao, sigla_partido_bloco, orientacao_voto) VALUES
                ('T-1', 'AAA', 'Sim'), ('T-1', 'Governo', 'Não'), ('T-2', 'BBB', 'Liberado')
            ON CONFLICT DO NOTHING;
        """)
        )
    build(engine)
    with engine.connect() as conn:
        versoes = conn.execute(text(
            "SELECT sigla_partido, atual FROM gold.dim_deputado WHERE id_deputado = 999001 ORDER BY valido_de")).all()  # fmt: skip
        votos = conn.execute(text(
            "SELECT v.id_votacao, d.sigla_partido, v.seguiu_partido, v.seguiu_governo FROM gold.fato_voto v "
            "JOIN gold.dim_deputado d USING (sk_deputado) WHERE v.id_deputado = 999001 ORDER BY 1")).all()  # fmt: skip
        nominal = conn.execute(
            text("SELECT votos_sim, nominal FROM gold.fato_votacao WHERE id_votacao = 'T-1'")
        ).one()
    assert [tuple(v) for v in versoes] == [("AAA", False), ("BBB", True)]  # 3 linhas → 2 versões
    assert [tuple(v) for v in votos] == [("T-1", "AAA", True, False), ("T-2", "BBB", None, None)]
    assert tuple(nominal) == (1, True)
