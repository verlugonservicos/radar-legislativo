"""Cliente HTTP da API de Dados Abertos da Câmara (SPEC V3 seção 5.1)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from radar.config import Settings, get_settings

log = logging.getLogger("radar.extract.client")


class CamaraAPIError(Exception):
    """Falha definitiva numa chamada (depois de esgotados os retries)."""

    def __init__(self, mensagem: str, url: str, status: int | None = None) -> None:
        super().__init__(f"{mensagem} [{status or '-'}] {url}")
        self.url = url
        self.status = status


@dataclass
class PageResult:
    page_number: int
    payload: dict
    url: str
    status: int


class _Throttle:
    """Intervalo mínimo entre requisições, somado entre todas as threads."""

    def __init__(self, intervalo: float) -> None:
        self.intervalo = intervalo
        self._lock = threading.Lock()
        self._proxima = 0.0

    def aguardar(self) -> None:
        with self._lock:
            agora = time.monotonic()
            espera = self._proxima - agora
            self._proxima = max(agora, self._proxima) + self.intervalo
        if espera > 0:
            time.sleep(espera)


class CamaraClient:
    """Sessão HTTP com retry/backoff, throttle global e paginação por `links.next`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = s = settings or get_settings()
        self.base = s.camara_base_url.rstrip("/")
        self.timeout = (s.camara_timeout_connect, s.camara_timeout_read)
        self.throttle = _Throttle(s.camara_throttle_segundos)
        retry = Retry(
            total=s.camara_max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adaptador = HTTPAdapter(max_retries=retry, pool_maxsize=s.extracao_workers * 2)
        self.sessao = requests.Session()
        self.sessao.mount("https://", adaptador)
        self.sessao.mount("http://", adaptador)
        self.sessao.headers.update(
            {"Accept": "application/json", "User-Agent": s.camara_user_agent}
        )
        self.chamadas = 0
        self._lock_contador = threading.Lock()

    def _url(self, path: str) -> str:
        return path if path.startswith("http") else f"{self.base}{path}"

    def _requisitar(self, url: str, params: dict | None) -> tuple[int, dict | None, str]:
        self.throttle.aguardar()
        with self._lock_contador:
            self.chamadas += 1
        try:
            resposta = self.sessao.get(url, params=params, timeout=self.timeout)
        except (requests.Timeout, requests.ConnectionError) as erro:
            raise CamaraAPIError(f"{type(erro).__name__}", url) from erro
        if resposta.status_code == 404:
            return 404, None, resposta.url
        if resposta.status_code >= 400:
            detalhe = resposta.text[:200].replace("\n", " ")
            raise CamaraAPIError(
                f"HTTP {resposta.status_code}: {detalhe}", resposta.url, resposta.status_code
            )
        try:
            return resposta.status_code, resposta.json(), resposta.url
        except ValueError as erro:
            raise CamaraAPIError("JSON inválido", resposta.url, resposta.status_code) from erro

    def get(self, path: str, params: dict | None = None) -> dict | None:
        """Uma chamada. Devolve `None` em 404."""
        _, corpo, _ = self._requisitar(self._url(path), params)
        return corpo

    def iter_pages(
        self, path: str, params: dict | None = None, paginado: bool = True
    ) -> Iterator[PageResult]:
        """Laço `while` seguindo `links[rel=next]`. Não paginado = uma única página."""
        url = self._url(path)
        parametros: dict | None = dict(params or {})
        if paginado:
            parametros.setdefault("pagina", 1)
            parametros.setdefault("itens", self.settings.camara_itens_por_pagina)
        pagina = 1
        vistas: set[str] = set()
        while url:
            status, corpo, url_final = self._requisitar(url, parametros)
            if corpo is None:  # 404: recurso inexistente (ex.: ID removido)
                log.debug("404 em %s", url_final)
                return
            yield PageResult(pagina, corpo, url_final, status)
            if not paginado:
                return
            proxima = next(
                (lk.get("href") for lk in corpo.get("links") or [] if lk.get("rel") == "next"), None
            )
            if not proxima:
                return
            if proxima in vistas or proxima == url_final:
                log.warning("link next repetido, encerrando paginação: %s", proxima)
                return
            vistas.add(proxima)
            url, parametros, pagina = proxima, None, pagina + 1  # o href já traz os parâmetros
