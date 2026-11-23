"""Extrator genérico: executa qualquer endpoint do catálogo e grava a Landing (SPEC V3 seção 5.5)."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from radar.catalog.models import EndpointSpec
from radar.extract import landing
from radar.extract.client import CamaraAPIError, CamaraClient
from radar.extract.ids import resolve_ids
from radar.extract.windows import recortes, render_params
from radar.logging_setup import log_contexto
from radar.run_context import RunContext

log = logging.getLogger("radar.extract")


@dataclass
class ExtractResult:
    endpoint: str
    chamadas: int = 0
    paginas: int = 0
    registros: int = 0
    ids: int = 0
    erros: list[dict] = field(default_factory=list)
    arquivos: set = field(default_factory=set, repr=False)  # páginas gravadas nesta execução

    @property
    def vazio(self) -> bool:
        return self.registros == 0 and not self.erros


def _conta(dados: object) -> int:
    if isinstance(dados, list):
        return len(dados)
    return 1 if dados else 0


class GenericExtractor:
    def __init__(self, client: CamaraClient) -> None:
        self.client = client
        self._lock = threading.Lock()

    def _baixar(
        self,
        spec: EndpointSpec,
        ctx: RunContext,
        ref,
        path: str,
        params: dict,
        resultado: ExtractResult,
        id_pai: str | None = None,
        passe: int = 0,
    ) -> None:
        """Todas as páginas de uma chamada lógica → arquivos na Landing."""
        requisicoes = 0
        try:
            for pagina in self.client.iter_pages(path, params, paginado=spec.paginado):
                requisicoes += 1
                arquivo = landing.write_page(
                    spec.nome, ref, pagina.payload, pagina.page_number,
                    url=pagina.url, params=params if pagina.page_number == 1 else None,
                    id_execucao=ctx.id_execucao, status_http=pagina.status,
                    id_pai=id_pai, passe=passe,
                )  # fmt: skip
                with self._lock:
                    resultado.arquivos.add(arquivo)
                    resultado.paginas += 1
                    resultado.registros += _conta(pagina.payload.get("dados"))
        except CamaraAPIError as erro:
            with self._lock:
                resultado.erros.append({"id_pai": id_pai, "passe": passe, "url": erro.url,
                                        "status": erro.status, "erro": str(erro)[:300]})  # fmt: skip
            log.warning("falha em %s (id_pai=%s): %s", spec.nome, id_pai, erro)
        finally:
            with self._lock:  # 404 ou erro também contam como uma chamada
                resultado.chamadas += max(requisicoes, 1)

    @staticmethod
    def _limpar_sobras(spec, ctx: RunContext, ref, resultado: ExtractResult, erros: int) -> None:
        """Limpeza segura da partição: só depois do download e só se não houve erro."""
        if erros:
            log.warning("%s: %d erro(s) — arquivos anteriores da partição dt=%s preservados",
                        spec.nome, erros, ref)  # fmt: skip
            return
        if spec.nome in ctx.apenas_orfaos:  # extração parcial: não mexe no que já existia
            return
        removidos = landing.prune_partition(spec.nome, ref, resultado.arquivos)
        if removidos:
            log.info("%s: %d arquivo(s) antigos removidos de dt=%s", spec.nome, removidos, ref)

    def run(self, spec: EndpointSpec, ctx: RunContext) -> ExtractResult:
        resultado = ExtractResult(spec.nome)
        passes = spec.janela.passes or [{}]
        fixos = ctx.placeholders()
        ids = resolve_ids(spec, ctx) if "{id}" in spec.path else [None]
        resultado.ids = len(ids) if "{id}" in spec.path else 0
        if "{id}" in spec.path and not ids:
            log.warning("%s: nenhum ID de origem (%s)", spec.nome, spec.ids.de if spec.ids else "")

        with log_contexto(run=ctx.id_execucao, camada="landing", endpoint=spec.nome):
            for ref, janela_ctx in recortes(spec, ctx.start, ctx.end, ctx.hoje):
                valores = {**fixos, **janela_ctx}
                base = render_params(spec.params, valores) | render_params(
                    spec.janela.params, valores
                )
                antes = (
                    resultado.chamadas,
                    resultado.paginas,
                    resultado.registros,
                    len(resultado.erros),
                )
                tarefas = [
                    (id_pai, num, base | render_params(passe, valores))
                    for id_pai in ids
                    for num, passe in enumerate(passes)
                ]
                if len(tarefas) == 1 or ctx.settings.extracao_workers == 1:
                    for id_pai, num, params in tarefas:
                        path = spec.path.replace("{id}", id_pai) if id_pai else spec.path
                        self._baixar(spec, ctx, ref, path, params, resultado, id_pai, num)
                else:
                    with ThreadPoolExecutor(ctx.settings.extracao_workers) as pool:
                        futuros = [
                            pool.submit(
                                self._baixar,
                                spec,
                                ctx,
                                ref,
                                spec.path.replace("{id}", id_pai) if id_pai else spec.path,
                                params,
                                resultado,
                                id_pai,
                                num,
                            )  # fmt: skip
                            for id_pai, num, params in tarefas
                        ]
                        for futuro in as_completed(futuros):
                            futuro.result()
                self._limpar_sobras(spec, ctx, ref, resultado, len(resultado.erros) - antes[3])
                landing.write_manifest(spec.nome, ref, {
                    "endpoint": spec.nome, "path": spec.path, "id_execucao": ctx.id_execucao,
                    "params": base, "passes": len(passes), "ids": resultado.ids,
                    "chamadas": resultado.chamadas - antes[0], "paginas": resultado.paginas - antes[1],
                    "registros": resultado.registros - antes[2],
                    "erros": resultado.erros[antes[3]:],
                })  # fmt: skip
            log.info(
                "%s: %d chamadas, %d páginas, %d registros, %d erros",
                spec.nome, resultado.chamadas, resultado.paginas, resultado.registros, len(resultado.erros),
            )  # fmt: skip
        return resultado
