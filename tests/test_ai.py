"""IA (M4) sem rede e sem banco: textos, custo, classificação, relevância e avaliação."""

import numpy as np
import pandas as pd
import pytest
import yaml
from ai_fake import vetor

from radar.ai import evaluation
from radar.ai.classifier import cosine_matrix, escolher
from radar.ai.cost import BudgetExceeded, CostTracker, estimate_tokens
from radar.ai.prompts import PROMPT_VERSAO, SCHEMA_RESUMO, SETORES, texto_proposicao
from radar.ai.relevance import compute_relevance
from radar.ai.summarizer import hash_resumo, montar_prompt
from radar.config import RAIZ_PROJETO, Settings

TEMAS = yaml.safe_load((RAIZ_PROJETO / "config" / "temas.yaml").read_text(encoding="utf-8"))
NOMES_TEMAS = {t["nome"] for t in TEMAS["temas"]} | {TEMAS["tema_fallback"]}


def test_texto_da_proposicao_omite_partes_nulas():
    assert texto_proposicao("PL", "Altera a lei X.", None, None) == "PL. Altera a lei X"
    t = texto_proposicao("PEC", "Cria o imposto", "tributo", ["Economia", "Saúde"])
    assert t == "PEC. Cria o imposto. Palavras-chave: tributo. Temas oficiais: Economia, Saúde"


def test_hash_do_resumo_ignora_o_despacho():
    """ADR-026: novos despachos não disparam novo resumo; mudança de ementa dispara."""
    assert hash_resumo("Ementa", "det") == hash_resumo("Ementa", "det")
    assert hash_resumo("Ementa", "det") != hash_resumo("Ementa nova", "det")
    p = {"sigla_tipo": "PL", "numero": 1, "ano": 2026, "tema_ia": "Saúde", "ementa": "E",
         "ementa_detalhada": None, "keywords": "k", "orgao_situacao": None, "regime": None,
         "ultimo_despacho": "Às comissões"}  # fmt: skip
    assert "Último despacho: Às comissões" in montar_prompt(
        p
    ) and "palavras-chave: k" in montar_prompt(p)


def test_schema_do_resumo_estrito_e_setores_fechados():
    assert PROMPT_VERSAO == "resumo-v4"
    assert SCHEMA_RESUMO["additionalProperties"] is False
    assert SCHEMA_RESUMO["properties"]["setores_afetados"]["items"]["enum"] == SETORES
    assert all(1 <= len(s.split()) <= 3 for s in SETORES)


def test_custo_e_teto():
    s = Settings(
        preco_embedding_usd_1m=0.02, preco_llm_entrada_usd_1m=0.15, preco_llm_saida_usd_1m=0.60
    )
    t = CostTracker(None, None, budget_usd=0.001, settings=s)
    assert t.custo("resumo", 1_000_000, 1_000_000) == pytest.approx(0.75)
    assert t.custo("embedding", 1_000_000) == pytest.approx(0.02)
    t.add("resumo", 1, 600, 90)
    assert t.total_usd == pytest.approx(600 * 0.15e-6 + 90 * 0.60e-6)
    with pytest.raises(BudgetExceeded):
        t.check_projection(0.001)
    assert estimate_tokens("a" * 35) == 11


def test_cosseno_e_escolha_com_limiar_e_segundo_tema():
    A = cosine_matrix(np.array([[1.0, 0.0], [0.0, 2.0]]), np.array([[2.0, 0.0], [1.0, 1.0]]))
    assert A[0, 0] == pytest.approx(1.0) and A[1, 1] == pytest.approx(0.7071, abs=1e-4)
    sim = pd.DataFrame({"id_proposicao": [1, 1, 2, 2], "tema": ["Saúde", "Educação", "Saúde", "Educação"],
                        "sim": [0.6, 0.3, 0.25, 0.2]})  # fmt: skip
    e = escolher(sim, limiar=0.4).set_index("id_proposicao")
    assert e.loc[1, "tema_ia"] == "Saúde" and e.loc[1, "tema_ia_segundo"] == "Educação"
    assert e.loc[2, "tema_ia"] == "Outros" and e.loc[2, "tema_ia_score"] == 0.25


def test_embeddings_falsos_aproximam_textos_parecidos():
    saude = vetor("Tema: Saúde. hospitais medicamentos vacinas")
    a = vetor("PL. Distribuição gratuita de medicamentos nos hospitais")
    b = vetor("PL. Concessão de rodovias federais")
    assert np.dot(a, saude) > np.dot(b, saude)


def test_relevancia_segue_a_formula_da_spec():
    df = pd.DataFrame([
        {"peso_tipo": 1.0, "tema_ia": "Tributário e Fiscal", "nivel_impacto": "alto",
         "regime": "Urgência (Art. 155, RICD)", "em_pauta_proximos_7d": True},
        {"peso_tipo": None, "tema_ia": "Saúde", "nivel_impacto": None, "regime": None,
         "em_pauta_proximos_7d": None},
    ])  # fmt: skip
    r = compute_relevance(df, {"Tributário e Fiscal"})
    assert r.tolist() == [1.0, pytest.approx(0.30 * 0.2 + 0.20 * 0.4)]


def test_mapa_de_temas_oficiais_cobre_todos_e_aponta_para_temas_validos():
    mapa = yaml.safe_load(evaluation.MAPA.read_text(encoding="utf-8"))
    assert len(mapa) == 32
    destinos = {d for v in mapa.values() for d in (v if isinstance(v, list) else [v])}
    assert destinos <= NOMES_TEMAS
    m = evaluation.carregar_mapa()
    assert evaluation.esperado(["Saúde", "Turismo"], m) == {
        "Saúde",
        "Economia e Sistema Financeiro",
    }
    assert evaluation.esperado(["Direito Constitucional"], m) == set()  # → Outros: não avaliável


def test_curva_acuracia_por_cobertura():
    df = pd.DataFrame({"score": [0.6, 0.5, 0.3, 0.25], "acerto": [True, True, False, True]})
    c = {p["limiar"]: p for p in evaluation.curva(df, [0.2, 0.4])}
    assert c[0.2] == {
        "limiar": 0.2,
        "cobertura": 1.0,
        "acuracia": 0.75,
        "acuracia_classificadas": 0.75,
    }
    assert (
        c[0.4]["cobertura"] == 0.5
        and c[0.4]["acuracia"] == 0.5
        and c[0.4]["acuracia_classificadas"] == 1.0
    )
