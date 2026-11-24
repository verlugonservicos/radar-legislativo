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
                   (999001, '2026-03-01 10:00-03', 57, 'Teste', 'BBB', 'SP', 'Exercício'),
                   -- mesmo instante em outra legislatura (caso real da API): não pode gerar versão duplicada
                   (999001, '2026-03-01 10:00-03', 56, 'Teste', 'CCC', 'SP', 'Exercício')
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


def test_deputados_orfaos_da_silver(engine):
    """SPEC 9.5: IDs citados em votos/autorias/presenças sem cadastro em silver.deputados."""
    from radar.extract.orfaos import deputados_orfaos

    run_silver(engine, None)
    antes = set(deputados_orfaos(engine))
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO silver.votos (id_votacao, id_deputado) VALUES ('orfao-1', 987654321)")
        )
        cadastrado = conn.execute(
            text("SELECT id_deputado FROM silver.deputados LIMIT 1")
        ).scalar_one()
        conn.execute(text("INSERT INTO silver.votos (id_votacao, id_deputado) VALUES ('orfao-2', :d)"),
                     {"d": cadastrado})  # fmt: skip
    try:
        orfaos = deputados_orfaos(engine)
        assert "987654321" in orfaos and str(cadastrado) not in orfaos
        assert set(orfaos) - antes == {"987654321"}
        assert deputados_orfaos(engine, limite=1) == [
            "987654321"
        ]  # mais recentes (maior id) primeiro
    finally:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM silver.votos WHERE id_votacao IN ('orfao-1', 'orfao-2')")
            )


# ------------------------------------------------------------------ IA (M4) com cliente falso
PROPS_IA = [
    (9000001, "PL", "Dispõe sobre a distribuição gratuita de medicamentos e vacinas nos hospitais do SUS.", ["Saúde"]),
    (9000002, "PEC", "Altera o sistema tributário para criar imposto sobre bens e reduzir isenções fiscais.", ["Economia"]),
    (9000003, "PL", "Institui o Dia Nacional do Bordado.", ["Homenagens e Datas Comemorativas"]),
    (9000004, "REQ", "Requer informações ao Ministro.", None),  # tipo não relevante: fica de fora
]  # fmt: skip


@pytest.fixture
def props_ia(engine, monkeypatch):
    from radar.config import get_settings

    # os embeddings falsos (saco de palavras) têm similaridades menores que os reais
    monkeypatch.setenv("TEMA_LIMIAR_MINIMO", "0.05")
    get_settings.cache_clear()
    build(engine)
    with engine.begin() as conn:
        for id_, tipo, ementa, temas in PROPS_IA:
            conn.execute(text(
                "INSERT INTO gold.fato_proposicao (id_proposicao, sigla_tipo, numero, ano, ementa, "
                "temas_oficiais, data_apresentacao, regime) VALUES (:i, :t, 1, 2026, :e, :o, '2026-11-20', "
                ":r) ON CONFLICT (id_proposicao) DO NOTHING"),
                {"i": id_, "t": tipo, "e": ementa, "o": temas,
                 "r": "Urgência (Art. 155, RICD)" if tipo == "PEC" else None})  # fmt: skip
        conn.execute(text("DELETE FROM ops.custos_ia"))
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM gold.fato_proposicao WHERE id_proposicao >= 9000000"))
        conn.execute(text("UPDATE gold.dim_tema SET embedding = NULL, texto_hash = NULL"))
    get_settings.cache_clear()


def _ia(engine, i, col):
    return _um(engine, f"SELECT {col} FROM gold.fato_proposicao WHERE id_proposicao = :i", i=i)


def test_ia_classifica_resume_pontua_e_e_idempotente(props_ia):
    from ai_fake import ClienteFalso

    from radar.ai.runner import run_ai

    cli = ClienteFalso()
    r = run_ai(props_ia, None, orcamento_usd=1.0, cliente=cli)
    assert (
        r["temas"] == 12 and r["embeddings"] == 3 and r["resumos"] == 3 and not r["teto_atingido"]
    )
    assert _ia(props_ia, 9000001, "tema_ia") == "Saúde"
    assert _ia(props_ia, 9000002, "tema_ia") == "Tributário e Fiscal"
    assert _ia(props_ia, 9000004, "tema_ia") is None  # REQ fora dos tipos relevantes
    assert len(_ia(props_ia, 9000001, "resumo_executivo")) == 400  # truncado
    assert _ia(props_ia, 9000001, "setores_afetados") == [
        "Serviços",
        "Setor Público",
    ]  # sem repetição
    assert _ia(props_ia, 9000001, "ia_prompt_versao") == "resumo-v3"
    assert float(_ia(props_ia, 9000002, "relevancia_score")) > float(
        _ia(props_ia, 9000003, "relevancia_score")
    )
    assert _um(props_ia, "SELECT count(*) FROM ops.custos_ia") >= 3 and r["custo_usd"] > 0
    assert (
        len(__import__("radar.ai.classifier", fromlist=["x"]).similares(props_ia, 9000001, k=2))
        == 2
    )

    # segunda execução: nada mudou → nenhuma chamada paga
    antes = (cli.chamadas_embed, cli.chamadas_chat)
    r2 = run_ai(props_ia, None, orcamento_usd=1.0, cliente=cli)
    assert (
        (cli.chamadas_embed, cli.chamadas_chat) == antes
        and r2["custo_usd"] == 0
        and r2["pendentes"] == 0
    )

    # novo despacho não refaz o resumo; ementa nova refaz embedding e resumo
    with props_ia.begin() as conn:
        conn.execute(
            text(
                "UPDATE gold.fato_proposicao SET ultimo_despacho = 'Às comissões' WHERE id_proposicao = 9000001"
            )
        )
        conn.execute(text("UPDATE gold.fato_proposicao SET ementa = ementa || ' Inclui farmácias.' WHERE id_proposicao = 9000001"))  # fmt: skip
    r3 = run_ai(props_ia, None, orcamento_usd=1.0, cliente=cli)
    assert r3["embeddings"] == 1 and r3["resumos"] == 1

    # a carga da Gold não apaga as colunas de IA
    build(props_ia)
    assert _ia(props_ia, 9000002, "tema_ia") == "Tributário e Fiscal"


def test_ia_para_no_teto_e_guarda_o_que_fez(props_ia):
    from ai_fake import ClienteFalso

    from radar.ai.runner import run_ai

    with props_ia.begin() as conn:
        conn.execute(
            text("UPDATE gold.fato_proposicao SET resumo_executivo = NULL, ia_texto_hash = NULL")
        )
    r = run_ai(props_ia, None, orcamento_usd=0.0002, cliente=ClienteFalso())
    assert r["teto_atingido"] and r["resumos"] == 0 and r["pendentes"] == 3
    assert r["classificadas"] == 3  # embeddings já feitos são classificados mesmo com o teto


def test_falha_num_resumo_nao_derruba_os_demais(props_ia):
    from ai_fake import ClienteFalso

    from radar.ai.runner import run_ai

    r = run_ai(props_ia, None, orcamento_usd=1.0, cliente=ClienteFalso(falhar_em={"Bordado"}))
    assert r["resumos"] == 2 and r["falhas_resumo"] == 1 and r["pendentes"] == 1


def test_avaliacao_grava_acuracia(props_ia):
    from ai_fake import ClienteFalso

    from radar.ai.cost import CostTracker
    from radar.ai.evaluation import avaliar
    from radar.ai.runner import run_ai

    run_ai(props_ia, None, orcamento_usd=1.0, cliente=ClienteFalso())
    r = avaliar(
        props_ia,
        ClienteFalso(),
        CostTracker(props_ia, None, 1.0),
        limiar=0.0,
        amostra_sem_vazamento=10,
    )
    assert r["avaliadas"] == 3 and 0 <= r["acuracia"] <= 1 and r["sem_vazamento"]["n"] == 3
    assert _um(props_ia, "SELECT count(*) FROM ops.avaliacao_ia") >= 1


# ------------------------------------------------------------------ marts e dashboards (M5)
def test_marts_com_indice_unico_e_site_gerado_do_banco(engine, tmp_path):
    from radar.dashboard.build import build as build_site
    from radar.gold.builder import refresh_marts

    run_silver(engine, None)
    build(engine)
    r = refresh_marts(engine)
    assert len(r["marts"]) == 24
    with engine.connect() as conn:
        sem_indice = conn.execute(text(
            "SELECT m.matviewname FROM pg_matviews m WHERE m.schemaname = 'gold' AND NOT EXISTS ("
            " SELECT 1 FROM pg_indexes i JOIN pg_class c ON c.relname = i.indexname JOIN pg_index x ON x.indexrelid = c.oid"
            " WHERE i.schemaname = 'gold' AND i.tablename = m.matviewname AND x.indisunique)")).scalars().all()  # fmt: skip
    assert sem_indice == []
    assert refresh_marts(engine)["marts"] == r["marts"]  # idempotente
    site = build_site(tmp_path / "site", engine=engine)
    assert site["paginas"] == 9 and (tmp_path / "site" / "data" / "meta.json").exists()


def test_titulo_padroniza_maiusculas_de_tipos_e_fornecedores(engine):
    casos = {
        "LOCAÇÃO OU FRETAMENTO DE VEÍCULOS AUTOMOTORES": "Locação ou Fretamento de Veículos Automotores",
        "HOSPEDAGEM ,EXCETO DO PARLAMENTAR NO DISTRITO FEDERAL.": "Hospedagem, Exceto do Parlamentar no Distrito Federal.",
        "PASSAGEM AÉREA - SIGEPA": "Passagem Aérea - SIGEPA",
        "TAM LINHAS AEREAS S/A.": "TAM Linhas Aereas S/A.",
        "AUTO POSTO 104 NORTE LTDA": "Auto Posto 104 Norte Ltda",
        "E SERVIÇOS DE TÁXI": "E Serviços de Táxi",  # conectivo no início continua com inicial maiúscula
    }
    for entrada, esperado in casos.items():
        assert _um(engine, "SELECT gold.titulo(:t)", t=entrada) == esperado
    assert _um(engine, "SELECT gold.titulo(NULL)") is None
