"""
routes/calendar_proxy.py
-------------------------
Reverse-proxies the bundled Radicale calendar server (docker-compose.yml's
`caldav` service) through this app's own port, so a browser only ever needs
one port/login (the dashboard's) to reach the calendar UI — Radicale itself
is not published to the host by default (see docker-compose.yml's `caldav`
service comments).

Auth model: gated by the same require_session_or_token dependency as every
other dashboard-facing route; this proxy then injects Radicale's own
htpasswd Basic Auth itself (from CALDAV_USERNAME/CALDAV_PASSWORD) so the
browser never has to separately log into Radicale.

X-Script-Name is Radicale's own documented mechanism for running correctly
behind a reverse proxy mounted under a URL sub-path — it tells Radicale to
render its internal web UI's self-referential links prefixed with
/calendar instead of assuming it's served at /.

Only proxies the *bundled* Radicale service (always at the compose-network
address below, regardless of what CALDAV_URL is set to) — if you've pointed
CALDAV_URL at an external CalDAV server instead, this route isn't useful;
manage that calendar through its own UI directly.
"""
import base64
import os
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response

import auth

router = APIRouter()

_CALDAV_ROOT = "http://caldav:5232"
_MOUNT_PREFIX = "/calendar"

_METHODS = [
    "GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD",
    "PROPFIND", "PROPPATCH", "REPORT", "MKCALENDAR", "MKCOL",
    "COPY", "MOVE", "LOCK", "UNLOCK",
]

# Headers that must not be forwarded verbatim between hops (RFC 7230 §6.1),
# ones httpx/Starlette recompute themselves, and this app's own auth
# material (session cookie / API_TOKEN header) which Radicale has no use
# for and shouldn't see.
_STRIP_REQUEST_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "content-length", "host", "authorization", "cookie", "auth",
}
_STRIP_RESPONSE_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "content-length",
    # httpx transparently decompresses gzip/deflate/br when reading
    # `.content` below — forwarding the original Content-Encoding value
    # alongside the now-decompressed body makes the browser try to
    # decompress plain content a second time (Firefox: "Content Encoding
    # Error", Chrome: ERR_CONTENT_DECODING_FAILED).
    "content-encoding",
}

_client = httpx.AsyncClient(timeout=30.0)


def _radicale_auth_header() -> str:
    username = os.getenv("CALDAV_USERNAME", "")
    password = os.getenv("CALDAV_PASSWORD", "")
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"


@router.get("/calendar")
async def calendar_redirect(_: Annotated[None, Depends(auth.require_session_or_token)]):
    return RedirectResponse(url=f"{_MOUNT_PREFIX}/")


@router.api_route("/calendar/{path:path}", methods=_METHODS)
async def proxy_calendar(
    path: str,
    request: Request,
    _: Annotated[None, Depends(auth.require_session_or_token)],
):
    body = await request.body()

    forward_headers = {
        k: v for k, v in request.headers.items() if k.lower() not in _STRIP_REQUEST_HEADERS
    }
    forward_headers["Authorization"] = _radicale_auth_header()
    forward_headers["X-Script-Name"] = _MOUNT_PREFIX

    upstream_url = f"{_CALDAV_ROOT}/{path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    upstream_response = await _client.request(
        request.method,
        upstream_url,
        content=body,
        headers=forward_headers,
    )

    response_headers = {
        k: v for k, v in upstream_response.headers.items()
        if k.lower() not in _STRIP_RESPONSE_HEADERS
    }

    location = response_headers.get("location")
    if location and location.startswith("/") and not location.startswith(_MOUNT_PREFIX):
        response_headers["location"] = f"{_MOUNT_PREFIX}{location}"

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
    )
