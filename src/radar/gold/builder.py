"""Construção da Gold (SPEC V3 seção 9): DDL → dimensões → fatos → pontes → integridade.

Os marts (`100_marts.sql`) entram no M5, depois da IA.
"""

from __future__ import annotations

import logging
import time

import yaml
from sqlalchemy import Engine, text

from radar.config import RAIZ_PROJETO
from radar.db import SQL_DIR, executar_script
from radar.logging_setup import log_contexto

log = logging.getLogger("radar.gold")

DDL = ("gold/001_dimensoes.sql", "gold/002_fatos.sql", "gold/003_pontes.sql", "gold/004_ia.sql")
CARGAS = ("gold/010_load_dimensoes.sql", "gold/020_load_fatos.sql", "gold/030_load_pontes.sql")
TEMAS = RAIZ_PROJETO / "config" / "temas.yaml"

# Verificações de órfãos (SPEC 9.5): (nome, consulta que conta registros sem par)
INTEGRIDADE = {
    "voto_sem_deputado": "SELECT count(*) FROM gold.fato_voto v WHERE v.sk_deputado IS NULL",
    "voto_sem_votacao": "SELECT count(*) FROM gold.fato_voto v LEFT JOIN gold.fato_votacao f USING (id_votacao) WHERE f.id_votacao IS NULL",
    "despesa_sem_deputado": "SELECT count(*) FROM gold.fato_despesa WHERE sk_deputado IS NULL",
    "pauta_sem_proposicao": "SELECT count(*) FROM gold.fato_pauta_item p LEFT JOIN gold.fato_proposicao f USING (id_proposicao) WHERE p.id_proposicao > 0 AND f.id_proposicao IS NULL",
    "presenca_sem_deputado": "SELECT count(*) FROM gold.fato_presenca_evento p WHERE NOT EXISTS (SELECT 1 FROM gold.dim_deputado d WHERE d.id_deputado = p.id_deputado)",
    "autor_deputado_sem_dimensao": "SELECT count(*) FROM gold.ponte_proposicao_autor a WHERE a.id_deputado IS NOT NULL AND NOT EXISTS (SELECT 1 FROM gold.dim_deputado d WHERE d.id_deputado = a.id_deputado)",
    "deputado_com_mais_de_uma_versao_atual": "SELECT count(*) FROM (SELECT id_deputado FROM gold.dim_deputado WHERE atual GROUP BY 1 HAVING count(*) > 1) x",
}

TABELAS = (
    "dim_tempo", "dim_partido", "dim_deputado", "dim_orgao", "dim_tema", "dim_tipo_proposicao",
    "dim_frente", "dim_bloco", "fato_proposicao", "fato_tramitacao", "fato_votacao", "fato_voto",
    "fato_orientacao", "fato_despesa", "fato_evento", "fato_pauta_item", "fato_presenca_evento",
    "fato_discurso", "ponte_proposicao_autor", "ponte_frente_membro", "ponte_orgao_membro",
    "ponte_bloco_partido",
)  # fmt: skip


def criar_tabelas(engine: Engine) -> None:
    for arquivo in DDL:
        executar_script(engine, SQL_DIR / arquivo)


def carregar_temas(engine: Engine) -> int:
    """`config/temas.yaml` → gold.dim_tema (+ o tema de fallback)."""
    cfg = yaml.safe_load(TEMAS.read_text(encoding="utf-8"))
    temas = [*cfg["temas"], {"nome": cfg["tema_fallback"], "critico": False, "cor": cfg.get("cor_fallback"),
                             "descricao": "Proposições sem tema predominante."}]  # fmt: skip
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO gold.dim_tema (nome, descricao, critico, cor_hex) VALUES (:nome, :descricao, :critico, :cor) "
                "ON CONFLICT (nome) DO UPDATE SET descricao = EXCLUDED.descricao, critico = EXCLUDED.critico, "
                "cor_hex = EXCLUDED.cor_hex, atualizado_em = now()"
            ),
            temas,
        )
    return len(temas)


MARTS = "gold/100_marts.sql"


def refresh_marts(engine: Engine, id_execucao: int | None = None) -> dict:
    """Recria os marts (SPEC 9.6) numa transação, depois da IA. Devolve linhas por mart."""
    t0 = time.monotonic()
    with log_contexto(run=id_execucao or "-", camada="gold", endpoint="marts"):
        executar_script(engine, SQL_DIR / MARTS)
        with engine.connect() as conn:
            nomes = conn.execute(text(
                "SELECT matviewname FROM pg_matviews WHERE schemaname = 'gold' AND matviewname LIKE 'mart_%' ORDER BY 1"
            )).scalars().all()  # fmt: skip
            linhas = {
                n: conn.execute(text(f"SELECT count(*) FROM gold.{n}")).scalar_one() for n in nomes
            }
        duracao = round(time.monotonic() - t0, 1)
        log.info("marts: %d recriados em %.1f s · %s", len(linhas), duracao,
                 ", ".join(f"{n.removeprefix('mart_')}={q}" for n, q in linhas.items()))  # fmt: skip
    return {"marts": linhas, "duracao_s": duracao}


def check_integrity(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {nome: conn.execute(text(sql)).scalar_one() for nome, sql in INTEGRIDADE.items()}


def contar(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            t: conn.execute(text(f"SELECT count(*) FROM gold.{t}")).scalar_one() for t in TABELAS
        }


def build(engine: Engine, id_execucao: int | None = None) -> dict:
    """Executa a Gold em ordem; cada arquivo numa transação. Falha num arquivo é registrada."""
    resultado: dict = {"arquivos": {}}
    with log_contexto(run=id_execucao or "-", camada="gold", endpoint="-"):
        criar_tabelas(engine)
        resultado["temas"] = carregar_temas(engine)
        for arquivo in CARGAS:
            t0 = time.monotonic()
            try:
                executar_script(engine, SQL_DIR / arquivo)
                resultado["arquivos"][arquivo] = {"duracao_s": round(time.monotonic() - t0, 1)}
                log.info("%s: ok (%.1f s)", arquivo, time.monotonic() - t0)
            except Exception as erro:
                resultado["arquivos"][arquivo] = {"falha": str(erro)[:300]}
                log.exception("%s: falha", arquivo)
        resultado["integridade"] = check_integrity(engine)
        resultado["contagens"] = contar(engine)
        log.info("integridade: %s", resultado["integridade"])
    return resultado
