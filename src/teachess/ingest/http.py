"""Shared HTTP client: identifiable User-Agent, sequential requests, 429 back-off."""

import time
from collections.abc import Callable, Mapping

import httpx

from teachess import __version__

USER_AGENT = f"teachess/{__version__} (personal chess coach)"
RATE_LIMIT_WAIT_SECONDS = 60.0  # Lichess asks clients to wait a full minute after a 429


class IngestError(RuntimeError):
    """User-facing download error (message in Spanish)."""


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(30.0, read=120.0),
        follow_redirects=True,
        transport=transport,
    )


def get(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, str | int] | None = None,
    headers: Mapping[str, str] | None = None,
    not_found_message: str = "Recurso no encontrado.",
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """GET with one retry after a rate-limit response; errors become IngestError."""
    try:
        response = client.get(url, params=params, headers=headers)
        if response.status_code == 429:
            sleep(RATE_LIMIT_WAIT_SECONDS)
            response = client.get(url, params=params, headers=headers)
    except httpx.TransportError as exc:
        raise IngestError(f"No se pudo conectar con {httpx.URL(url).host}: {exc}") from exc

    if response.status_code == 404:
        raise IngestError(not_found_message)
    if response.status_code == 429:
        raise IngestError("Límite de peticiones alcanzado; inténtalo de nuevo más tarde.")
    if response.is_error:
        raise IngestError(f"Error HTTP {response.status_code} al descargar {url}.")
    return response
