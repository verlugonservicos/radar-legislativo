"""Custos de IA (SPEC V3 10.2): registro em `ops.custos_ia` e teto por execução."""

from __future__ import annotations

import logging

from sqlalchemy import Engine, text

from radar.config import Settings, get_settings

log = logging.getLogger("radar.ai.custo")


class BudgetExceeded(Exception):
    """A próxima etapa passaria do teto `IA_ORCAMENTO_MAX_USD` desta execução."""


def estimate_tokens(texto: str) -> int:
    """Aproximação conservadora para português (~3,5 caracteres por token)."""
    return int(len(texto) / 3.5) + 1


class CostTracker:
    def __init__(
        self,
        engine: Engine | None,
        run_id: int | None,
        budget_usd: float,
        settings: Settings | None = None,
    ) -> None:
        self.engine, self.run_id, self.budget_usd = engine, run_id, budget_usd
        self.s = settings or get_settings()
        self.total_usd = 0.0
        self.por_operacao: dict[str, dict] = {}

    def preco(self, operacao: str) -> tuple[str, float, float]:
        """(modelo, US$/1M entrada, US$/1M saída) da operação."""
        if operacao.startswith("embedding"):
            return self.s.embedding_model, self.s.preco_embedding_usd_1m, 0.0
        return self.s.llm_model, self.s.preco_llm_entrada_usd_1m, self.s.preco_llm_saida_usd_1m

    def custo(self, operacao: str, tokens_in: int, tokens_out: int = 0) -> float:
        _, p_in, p_out = self.preco(operacao)
        return tokens_in / 1e6 * p_in + tokens_out / 1e6 * p_out

    def add(self, operacao: str, itens: int, tokens_in: int, tokens_out: int = 0) -> float:
        modelo = self.preco(operacao)[0]
        usd = self.custo(operacao, tokens_in, tokens_out)
        self.total_usd += usd
        acc = self.por_operacao.setdefault(
            operacao, {"itens": 0, "tokens_in": 0, "tokens_out": 0, "usd": 0.0}
        )
        acc["itens"] += itens
        acc["tokens_in"] += tokens_in
        acc["tokens_out"] += tokens_out
        acc["usd"] += usd
        if self.engine is not None:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO ops.custos_ia (id_execucao, operacao, modelo, itens, tokens_entrada, "
                        "tokens_saida, custo_usd) VALUES (:r, :op, :m, :i, :ti, :to, :c)"
                    ),
                    {"r": self.run_id, "op": operacao, "m": modelo, "i": itens, "ti": tokens_in,
                     "to": tokens_out, "c": round(usd, 6)},
                )  # fmt: skip
        return usd

    def check_projection(self, custo_previsto_usd: float) -> None:
        """Interrompe antes da chamada se o gasto previsto estourar o teto."""
        if self.total_usd + custo_previsto_usd > self.budget_usd:
            raise BudgetExceeded(
                f"teto de US$ {self.budget_usd:.2f} atingido: gasto US$ {self.total_usd:.4f}, "
                f"próximo lote ~US$ {custo_previsto_usd:.4f}"
            )
