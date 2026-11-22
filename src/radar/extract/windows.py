"""Janelas de datas e renderização de parâmetros (SPEC V3 seção 5.3)."""

from __future__ import annotations

from datetime import date, timedelta

from radar.catalog.models import EndpointSpec

# A API recusa intervalos maiores que 3 meses em /votacoes (confirmado no M1); 31 dias é seguro.
MAX_DIAS_POR_JANELA = 31


def daily(start: date, end: date) -> list[tuple[date, date]]:
    """Um intervalo por dia: (d, d)."""
    return [(start + timedelta(days=i),) * 2 for i in range((end - start).days + 1)]


def by_year(start: date, end: date, max_dias: int = MAX_DIAS_POR_JANELA) -> list[tuple[date, date]]:
    """Intervalos de até `max_dias` que nunca cruzam 31/12."""
    janelas = []
    inicio = start
    while inicio <= end:
        fim = min(end, inicio + timedelta(days=max_dias - 1), date(inicio.year, 12, 31))
        janelas.append((inicio, fim))
        inicio = fim + timedelta(days=1)
    return janelas


def monthly(start: date, end: date, reprocessar_meses: int = 0) -> list[tuple[int, int]]:
    """(ano, mês) do período, recuando `reprocessar_meses` antes do início."""
    ano, mes = start.year, start.month - reprocessar_meses
    while mes < 1:
        ano, mes = ano - 1, mes + 12
    meses = []
    while (ano, mes) <= (end.year, end.month):
        meses.append((ano, mes))
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return meses


def render_params(template: dict[str, str], ctx: dict[str, object]) -> dict[str, str]:
    """Substitui `{placeholder}` pelos valores do contexto."""
    return {k: str(v).format(**{c: str(x) for c, x in ctx.items()}) for k, v in template.items()}


def recortes(spec: EndpointSpec, start: date, end: date, hoje: date) -> list[tuple[date, dict]]:
    """Partições da execução: [(data da partição dt, contexto de placeholders)]."""
    janela = spec.janela
    if janela.tipo == "periodo":
        if janela.particao == "diaria":
            intervalos = daily(start, end)
        elif janela.particao == "ano":
            intervalos = by_year(start, end)
        else:  # período inteiro numa chamada (sub-recursos por ID: evita N chamadas por dia)
            intervalos = by_year(start, end, max_dias=(end - start).days + 1)
        return [(i, {"inicio": i.isoformat(), "fim": f.isoformat()}) for i, f in intervalos]
    if janela.tipo == "mensal":
        return [
            (date(a, m, 1), {"ano": a, "mes": m})
            for a, m in monthly(start, end, janela.reprocessar_meses)
        ]
    return [(hoje, {})]  # sem janela ou desde o início da legislatura: partição = data da execução
