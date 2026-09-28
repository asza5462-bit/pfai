"""PHASE 13.1 — Provider-agnostic Web / Information fabric.

Never fabricates search results. Missing providers report WEB_PROVIDER_UNAVAILABLE /
WEB_FABRIC_STATUS=NOT_CONFIGURED. Includes SSRF protections, registry, and executor.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Any, Callable


class ClaimKind:
    FACT = "FACT"
    SOURCE_DERIVED_CLAIM = "SOURCE-DERIVED CLAIM"
    MODEL_INFERENCE = "MODEL INFERENCE"
    USER_PROVIDED_INFORMATION = "USER-PROVIDED INFORMATION"
    UNCERTAIN_RESULT = "UNCERTAIN RESULT"


WEB_PROVIDER_UNAVAILABLE = "WEB_PROVIDER_UNAVAILABLE"

ALLOWED_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/json",
    "application/xhtml+xml",
    "text/xml",
    "application/xml",
)

_SECRET_REDACT_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret|authorization)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
)


@dataclass
class CitationRecord:
    citation_id: str
    url: str = ""
    title: str = ""
    snippet: str = ""
    retrieved_at: float = 0.0
    freshness: str = "unknown"
    confidence: float = 0.0
    provider: str = ""
    content_hash: str = ""
    claim_kind: str = ClaimKind.SOURCE_DERIVED_CLAIM
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchResult:
    ok: bool
    status: str
    query: str = ""
    citations: list[CitationRecord] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    duplicates_removed: int = 0
    provider: str = ""
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "query": self.query,
            "citations": [c.to_dict() for c in self.citations],
            "claims": list(self.claims),
            "summary": self.summary,
            "duplicates_removed": self.duplicates_removed,
            "provider": self.provider,
            "error": self.error,
            "meta": dict(self.meta),
        }


def redact_secrets(text: str) -> str:
    out = text or ""
    for pat in _SECRET_REDACT_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def validate_url_for_fetch(url: str, *, allow_private: bool = False) -> dict[str, Any]:
    """URL validation + SSRF protections (scheme, host, private/local blocking)."""
    raw = (url or "").strip()
    if not raw:
        return {"ok": False, "error": "empty_url"}
    try:
        parsed = urllib.parse.urlparse(raw)
    except Exception:
        return {"ok": False, "error": "invalid_url"}
    if parsed.scheme not in ("http", "https"):
        return {"ok": False, "error": "scheme_not_allowed"}
    if not parsed.hostname:
        return {"ok": False, "error": "missing_hostname"}
    host = parsed.hostname.lower()
    # Block obvious local/metadata names
    blocked_hosts = {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata",
        "0.0.0.0",
    }
    if host in blocked_hosts or host.endswith(".local") or host.endswith(".internal"):
        return {"ok": False, "error": "ssrf_blocked_host", "host": host}
    # Resolve and check private ranges
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror:
        return {"ok": False, "error": "dns_resolution_failed", "host": host}
    addrs: list[str] = []
    for info in infos:
        sockaddr = info[4]
        ip = sockaddr[0]
        addrs.append(ip)
        try:
            ip_obj = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if not allow_private and (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
            or ip_obj.is_unspecified
        ):
            return {"ok": False, "error": "ssrf_blocked_private_ip", "host": host, "ip": ip}
    return {"ok": True, "url": raw, "host": host, "resolved": sorted(set(addrs))[:8]}


class WebSearchProvider(ABC):
    provider_id: str = "abstract"

    @abstractmethod
    def search(self, query: str, *, limit: int = 5) -> dict[str, Any]:
        ...

    def readiness(self) -> dict[str, Any]:
        return {"ok": False, "provider": self.provider_id, "production_ready": False}


class WebFetchProvider(ABC):
    provider_id: str = "abstract"

    @abstractmethod
    def fetch(self, url: str, *, max_bytes: int = 200_000) -> dict[str, Any]:
        ...

    def readiness(self) -> dict[str, Any]:
        return {"ok": False, "provider": self.provider_id, "production_ready": False}


class UnavailableWebSearchProvider(WebSearchProvider):
    provider_id = "unavailable"

    def search(self, query: str, *, limit: int = 5) -> dict[str, Any]:
        return {
            "ok": False,
            "error": WEB_PROVIDER_UNAVAILABLE,
            "query": query,
            "results": [],
            "provider": self.provider_id,
        }

    def readiness(self) -> dict[str, Any]:
        return {
            "ok": False,
            "provider": self.provider_id,
            "production_ready": False,
            "error": WEB_PROVIDER_UNAVAILABLE,
        }


class UnavailableWebFetchProvider(WebFetchProvider):
    provider_id = "unavailable"

    def fetch(self, url: str, *, max_bytes: int = 200_000) -> dict[str, Any]:
        return {
            "ok": False,
            "error": WEB_PROVIDER_UNAVAILABLE,
            "url": url,
            "provider": self.provider_id,
        }

    def readiness(self) -> dict[str, Any]:
        return {
            "ok": False,
            "provider": self.provider_id,
            "production_ready": False,
            "error": WEB_PROVIDER_UNAVAILABLE,
        }


class MockWebSearchProvider(WebSearchProvider):
    """Deterministic test-only search provider — never production-ready."""

    provider_id = "mock"

    def __init__(self, results: list[dict[str, Any]] | None = None) -> None:
        self._results = list(results or [])
        self.calls: list[dict[str, Any]] = []

    def readiness(self) -> dict[str, Any]:
        return {
            "ok": True,
            "provider": self.provider_id,
            "production_ready": False,
            "note": "test_only",
        }

    def search(self, query: str, *, limit: int = 5) -> dict[str, Any]:
        self.calls.append({"query": query, "limit": limit})
        rows = [
            {
                "url": r.get("url") or f"https://example.test/mock/{i}",
                "title": r.get("title") or f"Mock result {i}",
                "snippet": r.get("snippet") or f"Mock snippet for {query}",
            }
            for i, r in enumerate(self._results[: int(limit)] or [{"title": f"Mock:{query}"}])
        ]
        return {
            "ok": True,
            "query": query,
            "results": rows[: int(limit)],
            "provider": self.provider_id,
            "retrieved_at": time.time(),
            "test_only": True,
        }


class MockWebFetchProvider(WebFetchProvider):
    """Deterministic test-only fetch provider — never production-ready."""

    provider_id = "mock"

    def __init__(self, pages: dict[str, str] | None = None) -> None:
        self.pages = dict(pages or {})
        self.calls: list[str] = []

    def readiness(self) -> dict[str, Any]:
        return {
            "ok": True,
            "provider": self.provider_id,
            "production_ready": False,
            "note": "test_only",
        }

    def fetch(self, url: str, *, max_bytes: int = 200_000) -> dict[str, Any]:
        self.calls.append(url)
        check = validate_url_for_fetch(url, allow_private=True)
        # Mock may allow example.test fixtures without DNS; still reject private SSRF patterns in URL string
        if "localhost" in (url or "").lower() or "127.0.0.1" in (url or ""):
            return {"ok": False, "error": "ssrf_blocked_host", "url": url, "provider": self.provider_id}
        body = self.pages.get(url) or f"<html><title>Mock</title><body>Mock body for {url}</body></html>"
        raw = body.encode("utf-8")[: int(max_bytes)]
        return {
            "ok": True,
            "url": url,
            "final_url": url,
            "status": 200,
            "content_type": "text/html",
            "text": redact_secrets(raw.decode("utf-8", errors="replace")),
            "truncated": False,
            "retrieved_at": time.time(),
            "provider": self.provider_id,
            "content_hash": hashlib.sha256(raw).hexdigest(),
            "test_only": True,
            "url_check": check,
        }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Validate redirect targets before following (SSRF-safe)."""

    def __init__(self, *, allow_private: bool = False, max_redirects: int = 3) -> None:
        self.allow_private = allow_private
        self.max_redirects = max_redirects
        self.redirect_count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        self.redirect_count += 1
        if self.redirect_count > self.max_redirects:
            raise urllib.error.URLError("too_many_redirects")
        check = validate_url_for_fetch(newurl, allow_private=self.allow_private)
        if not check.get("ok"):
            raise urllib.error.URLError(f"ssrf_redirect_blocked:{check.get('error')}")
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


class HttpWebFetchProvider(WebFetchProvider):
    """Real HTTP fetch — only when explicitly configured/allowed. SSRF-hardened."""

    provider_id = "http_fetch"

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        user_agent: str = "PFAI-WebFabric/13.1",
        allow_private: bool = False,
        max_redirects: int = 3,
        rate_limit_per_minute: int = 30,
    ) -> None:
        self.timeout = float(timeout)
        self.user_agent = user_agent
        self.allow_private = bool(allow_private)
        self.max_redirects = int(max_redirects)
        self.rate_limit_per_minute = int(rate_limit_per_minute)
        self._lock = threading.RLock()
        self._timestamps: list[float] = []
        self._audit: list[dict[str, Any]] = []

    def readiness(self) -> dict[str, Any]:
        return {
            "ok": True,
            "provider": self.provider_id,
            "production_ready": True,
            "note": "HTTP fetch enabled; network egress + SSRF checks required",
            "ssrf_protection": True,
        }

    def _rate_ok(self) -> bool:
        now = time.time()
        with self._lock:
            self._timestamps = [t for t in self._timestamps if now - t < 60]
            if len(self._timestamps) >= self.rate_limit_per_minute:
                return False
            self._timestamps.append(now)
            return True

    def fetch(self, url: str, *, max_bytes: int = 200_000) -> dict[str, Any]:
        check = validate_url_for_fetch(url, allow_private=self.allow_private)
        if not check.get("ok"):
            self._audit.append({"event": "fetch_denied", "error": check.get("error"), "url": url})
            return {"ok": False, "error": check.get("error"), "url": url, "provider": self.provider_id}
        if not self._rate_ok():
            return {"ok": False, "error": "rate_limited", "url": url, "provider": self.provider_id}
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/json,text/plain,application/xhtml+xml",
            },
            method="GET",
        )
        opener = urllib.request.build_opener(
            _NoRedirect(allow_private=self.allow_private, max_redirects=self.max_redirects)
        )
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if content_type and not any(content_type.startswith(a) for a in ALLOWED_CONTENT_TYPES):
                    self._audit.append({"event": "content_type_denied", "content_type": content_type, "url": url})
                    return {
                        "ok": False,
                        "error": "content_type_not_allowed",
                        "content_type": content_type,
                        "url": url,
                        "provider": self.provider_id,
                    }
                final_url = getattr(resp, "geturl", lambda: url)()
                if final_url != url:
                    recheck = validate_url_for_fetch(final_url, allow_private=self.allow_private)
                    if not recheck.get("ok"):
                        return {
                            "ok": False,
                            "error": f"ssrf_final_url:{recheck.get('error')}",
                            "url": url,
                            "provider": self.provider_id,
                        }
                raw = resp.read(int(max_bytes) + 1)
                truncated = len(raw) > int(max_bytes)
                body = raw[: int(max_bytes)]
                text = redact_secrets(body.decode("utf-8", errors="replace"))
                out = {
                    "ok": True,
                    "url": url,
                    "final_url": final_url,
                    "status": getattr(resp, "status", 200),
                    "content_type": content_type,
                    "text": text,
                    "truncated": truncated,
                    "retrieved_at": time.time(),
                    "provider": self.provider_id,
                    "content_hash": hashlib.sha256(body).hexdigest(),
                }
                self._audit.append({"event": "fetch_ok", "url": url, "bytes": len(body)})
                return out
        except urllib.error.HTTPError as exc:
            return {"ok": False, "error": f"http_{exc.code}", "url": url, "provider": self.provider_id}
        except urllib.error.URLError as exc:
            return {"ok": False, "error": str(getattr(exc, "reason", exc)), "url": url, "provider": self.provider_id}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "url": url, "provider": self.provider_id}

    def audit(self) -> list[dict[str, Any]]:
        return list(self._audit)


class DuckDuckGoHtmlSearchProvider(WebSearchProvider):
    """Optional HTML search adapter — only when PFAI_WEB_SEARCH_PROVIDER=ddg."""

    provider_id = "ddg_html"

    def __init__(self, *, timeout: float = 15.0, fetch: WebFetchProvider | None = None) -> None:
        self.timeout = float(timeout)
        self._fetch = fetch or HttpWebFetchProvider(timeout=timeout)

    def readiness(self) -> dict[str, Any]:
        return {
            "ok": True,
            "provider": self.provider_id,
            "production_ready": True,
            "note": "DuckDuckGo HTML scrape adapter; results may be sparse; vendor-agnostic optional adapter",
        }

    def search(self, query: str, *, limit: int = 5) -> dict[str, Any]:
        q = (query or "").strip()
        if not q:
            return {"ok": False, "error": "empty_query", "results": [], "provider": self.provider_id}
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": q})
        fetched = self._fetch.fetch(url, max_bytes=400_000)
        if not fetched.get("ok"):
            return {
                "ok": False,
                "error": fetched.get("error") or WEB_PROVIDER_UNAVAILABLE,
                "results": [],
                "provider": self.provider_id,
            }
        results = _parse_ddg_results(fetched.get("text") or "", limit=int(limit))
        return {
            "ok": True,
            "query": q,
            "results": results,
            "provider": self.provider_id,
            "retrieved_at": time.time(),
        }


class GenericHttpSearchProvider(WebSearchProvider):
    """Generic configurable HTTP search adapter (JSON). Provider-agnostic."""

    provider_id = "http_search"

    def __init__(
        self,
        *,
        endpoint: str,
        timeout: float = 15.0,
        api_key: str = "",
        query_param: str = "q",
    ) -> None:
        self.endpoint = (endpoint or "").strip()
        self.timeout = float(timeout)
        self.api_key = api_key
        self.query_param = query_param or "q"

    def readiness(self) -> dict[str, Any]:
        configured = bool(self.endpoint)
        return {
            "ok": configured,
            "provider": self.provider_id,
            "production_ready": configured,
            "endpoint_configured": configured,
            "note": "Generic HTTP search JSON adapter",
        }

    def search(self, query: str, *, limit: int = 5) -> dict[str, Any]:
        if not self.endpoint:
            return {"ok": False, "error": WEB_PROVIDER_UNAVAILABLE, "results": [], "provider": self.provider_id}
        check = validate_url_for_fetch(self.endpoint)
        if not check.get("ok"):
            return {"ok": False, "error": check.get("error"), "results": [], "provider": self.provider_id}
        url = self.endpoint + ("&" if "?" in self.endpoint else "?") + urllib.parse.urlencode(
            {self.query_param: query, "limit": int(limit)}
        )
        headers = {"Accept": "application/json", "User-Agent": "PFAI-WebFabric/13.1"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read(500_000)
                data = json.loads(raw.decode("utf-8", errors="replace"))
            rows = data if isinstance(data, list) else data.get("results") or data.get("items") or []
            results = []
            for row in rows[: int(limit)]:
                if not isinstance(row, dict):
                    continue
                results.append(
                    {
                        "url": str(row.get("url") or row.get("link") or ""),
                        "title": str(row.get("title") or ""),
                        "snippet": str(row.get("snippet") or row.get("description") or "")[:400],
                    }
                )
            return {
                "ok": True,
                "query": query,
                "results": results,
                "provider": self.provider_id,
                "retrieved_at": time.time(),
            }
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "results": [], "provider": self.provider_id}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip and data and data.strip():
            self.parts.append(data.strip())


class SourceParser:
    def parse(self, fetched: dict[str, Any]) -> dict[str, Any]:
        if not fetched.get("ok"):
            return {"ok": False, "error": fetched.get("error") or "fetch_failed", "text": "", "title": ""}
        text = redact_secrets(str(fetched.get("text") or ""))
        content_type = str(fetched.get("content_type") or "")
        title = ""
        if "html" in content_type.lower() or "<html" in text[:500].lower():
            m = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.I | re.S)
            title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
            extractor = _TextExtractor()
            try:
                extractor.feed(text)
                plain = " ".join(extractor.parts)
            except Exception:
                plain = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", plain).strip()
        return {
            "ok": True,
            "title": title,
            "text": text[:50_000],
            "url": fetched.get("url") or "",
            "content_hash": fetched.get("content_hash") or "",
            "retrieved_at": fetched.get("retrieved_at") or time.time(),
            "provider": fetched.get("provider") or "",
        }

    def extract_claims(self, text: str, *, source_url: str = "") -> list[dict[str, Any]]:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]
        claims = []
        for i, s in enumerate(sentences[:20]):
            kind = ClaimKind.SOURCE_DERIVED_CLAIM
            conf = 0.55
            low = s.lower()
            if any(w in low for w in ("maybe", "might", "uncertain", "possibly", "unclear")):
                kind = ClaimKind.UNCERTAIN_RESULT
                conf = 0.35
            claims.append(
                {
                    "claim_id": f"c{i+1}",
                    "statement": s[:500],
                    "claim_kind": kind,
                    "confidence": conf,
                    "source": source_url,
                    "provenance": {"parser": "SourceParser", "index": i},
                }
            )
        return claims


class SourceVerifier:
    def verify(self, citations: list[CitationRecord]) -> dict[str, Any]:
        seen_hashes: set[str] = set()
        seen_urls: set[str] = set()
        unique: list[CitationRecord] = []
        dupes = 0
        for c in citations:
            key_h = c.content_hash or ""
            key_u = (c.url or "").rstrip("/").lower()
            if (key_h and key_h in seen_hashes) or (key_u and key_u in seen_urls):
                dupes += 1
                continue
            if key_h:
                seen_hashes.add(key_h)
            if key_u:
                seen_urls.add(key_u)
            age = time.time() - (c.retrieved_at or time.time())
            if age < 3600:
                c.freshness = "fresh"
            elif age < 86400 * 7:
                c.freshness = "recent"
            else:
                c.freshness = "stale_or_unknown"
            unique.append(c)
        return {"ok": True, "citations": unique, "duplicates_removed": dupes}


class ResearchPlanner:
    def plan(self, query: str) -> dict[str, Any]:
        q = (query or "").strip()
        steps = [
            {"step": "search", "query": q},
            {"step": "fetch_top", "limit": 3},
            {"step": "parse_extract"},
            {"step": "verify_dedupe"},
            {"step": "summarize_with_provenance"},
        ]
        return {
            "ok": True,
            "query": q,
            "steps": steps,
            "capabilities": ["search", "fetch", "parse", "extract", "compare", "summarize", "provenance"],
        }


def _parse_ddg_results(html: str, *, limit: int = 5) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for m in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        html or "",
        flags=re.I | re.S,
    ):
        href = urllib.parse.unquote(m.group(1))
        if "uddg=" in href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            href = (qs.get("uddg") or [href])[0]
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        results.append({"url": href, "title": title, "snippet": ""})
        if len(results) >= limit:
            break
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)', html or "", flags=re.I | re.S)
    for i, sn in enumerate(snippets[: len(results)]):
        results[i]["snippet"] = re.sub(r"<[^>]+>", "", sn).strip()[:400]
    return results


class WebProviderRegistry:
    """Catalog of search/fetch providers — configuration selects which is active."""

    def __init__(self) -> None:
        self._search: dict[str, Callable[[], WebSearchProvider]] = {}
        self._fetch: dict[str, Callable[[], WebFetchProvider]] = {}
        self.bootstrap_defaults()

    def bootstrap_defaults(self) -> None:
        self._search.setdefault("unavailable", UnavailableWebSearchProvider)
        self._search.setdefault("mock", MockWebSearchProvider)
        self._search.setdefault("ddg", lambda: DuckDuckGoHtmlSearchProvider())
        self._search.setdefault("ddg_html", lambda: DuckDuckGoHtmlSearchProvider())
        self._search.setdefault(
            "http_search",
            lambda: GenericHttpSearchProvider(endpoint=os.environ.get("PFAI_WEB_SEARCH_ENDPOINT", "")),
        )
        self._fetch.setdefault("unavailable", UnavailableWebFetchProvider)
        self._fetch.setdefault("mock", MockWebFetchProvider)
        self._fetch.setdefault("http", lambda: HttpWebFetchProvider())
        self._fetch.setdefault("http_fetch", lambda: HttpWebFetchProvider())

    def register_search(self, provider_id: str, factory: Callable[[], WebSearchProvider]) -> None:
        self._search[provider_id] = factory

    def register_fetch(self, provider_id: str, factory: Callable[[], WebFetchProvider]) -> None:
        self._fetch[provider_id] = factory

    def list_search(self) -> list[str]:
        return sorted(self._search)

    def list_fetch(self) -> list[str]:
        return sorted(self._fetch)

    def create_search(self, provider_id: str) -> WebSearchProvider:
        factory = self._search.get(provider_id)
        if not factory:
            return UnavailableWebSearchProvider()
        return factory()

    def create_fetch(self, provider_id: str) -> WebFetchProvider:
        factory = self._fetch.get(provider_id)
        if not factory:
            return UnavailableWebFetchProvider()
        return factory()


def web_providers_from_env(
    registry: WebProviderRegistry | None = None,
) -> tuple[WebSearchProvider, WebFetchProvider]:
    reg = registry or WebProviderRegistry()
    search_kind = (os.environ.get("PFAI_WEB_SEARCH_PROVIDER") or "").strip().lower()
    fetch_kind = (os.environ.get("PFAI_WEB_FETCH_PROVIDER") or "").strip().lower()
    allow_network = (os.environ.get("PFAI_WEB_ALLOW_NETWORK") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    timeout = float(os.environ.get("PFAI_WEB_TIMEOUT", "15") or 15)

    # Explicit mock for tests
    if search_kind == "mock":
        search: WebSearchProvider = MockWebSearchProvider()
    elif search_kind in ("ddg", "ddg_html", "duckduckgo") and allow_network:
        search = DuckDuckGoHtmlSearchProvider(timeout=timeout)
    elif search_kind in ("http", "http_search") and allow_network:
        search = GenericHttpSearchProvider(
            endpoint=os.environ.get("PFAI_WEB_SEARCH_ENDPOINT", ""),
            timeout=timeout,
            api_key=os.environ.get("PFAI_WEB_SEARCH_API_KEY", ""),
            query_param=os.environ.get("PFAI_WEB_SEARCH_QUERY_PARAM", "q"),
        )
    elif search_kind and search_kind not in ("", "unavailable", "none") and allow_network:
        search = reg.create_search(search_kind)
    else:
        search = UnavailableWebSearchProvider()

    if fetch_kind == "mock":
        fetch: WebFetchProvider = MockWebFetchProvider()
    elif fetch_kind in ("http", "http_fetch") and allow_network:
        fetch = HttpWebFetchProvider(
            timeout=timeout,
            allow_private=(os.environ.get("PFAI_WEB_ALLOW_PRIVATE") or "").lower() in ("1", "true"),
        )
    elif search_kind in ("ddg", "ddg_html", "duckduckgo") and allow_network and not fetch_kind:
        fetch = HttpWebFetchProvider(timeout=timeout)
    elif fetch_kind and fetch_kind not in ("", "unavailable", "none") and allow_network:
        fetch = reg.create_fetch(fetch_kind)
    else:
        fetch = UnavailableWebFetchProvider()

    return search, fetch


def web_config_report(
    search: WebSearchProvider | None = None,
    fetch: WebFetchProvider | None = None,
) -> dict[str, Any]:
    s, f = search, fetch
    if s is None or f is None:
        s2, f2 = web_providers_from_env()
        s = s or s2
        f = f or f2
    sr = s.readiness()
    fr = f.readiness()
    sid = getattr(s, "provider_id", "unknown")
    fid = getattr(f, "provider_id", "unknown")
    if sid == "mock" or fid == "mock":
        status = "TEST_ONLY"
    elif bool(sr.get("production_ready")) or bool(fr.get("production_ready")):
        status = "READY"
    else:
        status = "NOT_CONFIGURED"
    return {
        "WEB_SEARCH_PROVIDER": sid,
        "WEB_FETCH_PROVIDER": fid,
        "WEB_PROVIDER_AVAILABLE": status == "READY",
        "WEB_STATUS": WEB_PROVIDER_UNAVAILABLE if status == "NOT_CONFIGURED" else status,
        "WEB_FABRIC_STATUS": status,
        "search_production_ready": bool(sr.get("production_ready")),
        "fetch_production_ready": bool(fr.get("production_ready")),
        "ssrf_protection": True,
        "note": sr.get("note") or fr.get("note") or sr.get("error") or fr.get("error") or "",
    }


class WebInformationFabric:
    """Orchestrates search → fetch → parse → verify → summarize with provenance."""

    def __init__(
        self,
        *,
        search: WebSearchProvider | None = None,
        fetch: WebFetchProvider | None = None,
        parser: SourceParser | None = None,
        verifier: SourceVerifier | None = None,
        planner: ResearchPlanner | None = None,
        registry: WebProviderRegistry | None = None,
    ) -> None:
        self.registry = registry or WebProviderRegistry()
        if search is None or fetch is None:
            s, f = web_providers_from_env(self.registry)
            search = search or s
            fetch = fetch or f
        self.search_provider = search
        self.fetch_provider = fetch
        self.parser = parser or SourceParser()
        self.verifier = verifier or SourceVerifier()
        self.planner = planner or ResearchPlanner()
        self._audit: list[dict[str, Any]] = []

    def status(self) -> dict[str, Any]:
        return web_config_report(self.search_provider, self.fetch_provider)

    def research(self, query: str, *, limit: int = 5, fetch_top: int = 2) -> ResearchResult:
        plan = self.planner.plan(query)
        search_out = self.search_provider.search(query, limit=limit)
        self._audit.append({"event": "search", "ok": search_out.get("ok"), "provider": search_out.get("provider")})
        if not search_out.get("ok"):
            return ResearchResult(
                ok=False,
                status=WEB_PROVIDER_UNAVAILABLE,
                query=query,
                error=str(search_out.get("error") or WEB_PROVIDER_UNAVAILABLE),
                provider=getattr(self.search_provider, "provider_id", ""),
                meta={"plan": plan},
            )

        citations: list[CitationRecord] = []
        claims: list[dict[str, Any]] = []
        results = list(search_out.get("results") or [])
        for i, row in enumerate(results):
            url = str(row.get("url") or "")
            title = str(row.get("title") or "")
            snippet = redact_secrets(str(row.get("snippet") or ""))
            cid = f"cite-{hashlib.sha256(f'{url}:{i}'.encode()).hexdigest()[:12]}"
            content_hash = hashlib.sha256((snippet or title or url).encode()).hexdigest()
            citations.append(
                CitationRecord(
                    citation_id=cid,
                    url=url,
                    title=title,
                    snippet=snippet,
                    retrieved_at=float(search_out.get("retrieved_at") or time.time()),
                    confidence=0.5,
                    provider=str(search_out.get("provider") or ""),
                    content_hash=content_hash,
                    claim_kind=ClaimKind.SOURCE_DERIVED_CLAIM,
                    provenance={"stage": "search", "rank": i},
                )
            )
            if snippet:
                claims.append(
                    {
                        "statement": snippet[:500],
                        "claim_kind": ClaimKind.SOURCE_DERIVED_CLAIM,
                        "confidence": 0.5,
                        "source": url,
                        "citation_id": cid,
                    }
                )

        for row in results[: max(0, int(fetch_top))]:
            url = str(row.get("url") or "")
            if not url:
                continue
            fetched = self.fetch_provider.fetch(url)
            self._audit.append({"event": "fetch", "ok": fetched.get("ok"), "url": url})
            if not fetched.get("ok"):
                continue
            parsed = self.parser.parse(fetched)
            if not parsed.get("ok"):
                continue
            extracted = self.parser.extract_claims(parsed.get("text") or "", source_url=url)
            claims.extend(extracted)
            citations.append(
                CitationRecord(
                    citation_id=f"cite-{hashlib.sha256(url.encode()).hexdigest()[:12]}",
                    url=url,
                    title=str(parsed.get("title") or row.get("title") or ""),
                    snippet=(parsed.get("text") or "")[:400],
                    retrieved_at=float(parsed.get("retrieved_at") or time.time()),
                    confidence=0.65,
                    provider=str(fetched.get("provider") or ""),
                    content_hash=str(parsed.get("content_hash") or ""),
                    claim_kind=ClaimKind.SOURCE_DERIVED_CLAIM,
                    provenance={"stage": "fetch_parse"},
                )
            )

        verified = self.verifier.verify(citations)
        unique_cites: list[CitationRecord] = verified["citations"]
        summary_bits = [c.title or c.url for c in unique_cites[:5] if (c.title or c.url)]
        summary = (
            f"Research for {query!r}: {len(unique_cites)} sources. "
            + ("; ".join(summary_bits) if summary_bits else "No titles.")
        )
        claims.append(
            {
                "statement": summary,
                "claim_kind": ClaimKind.SOURCE_DERIVED_CLAIM,
                "confidence": 0.6,
                "source": "web_fabric_summary",
                "provenance": {"note": "summary_of_source_titles_only"},
            }
        )
        return ResearchResult(
            ok=True,
            status="SUCCESS",
            query=query,
            citations=unique_cites,
            claims=claims,
            summary=summary,
            duplicates_removed=int(verified.get("duplicates_removed") or 0),
            provider=str(search_out.get("provider") or ""),
            meta={"plan": plan, "search_count": len(results)},
        )

    def audit(self) -> list[dict[str, Any]]:
        return list(self._audit)


class WebResearchExecutor:
    """Thin executor over WebInformationFabric for skill/tool orchestration."""

    def __init__(self, fabric: WebInformationFabric | None = None) -> None:
        self.fabric = fabric or WebInformationFabric()

    def execute(self, query: str, *, limit: int = 5, fetch_top: int = 1) -> dict[str, Any]:
        result = self.fabric.research(query, limit=limit, fetch_top=fetch_top)
        out = result.to_dict()
        out["WEB_FABRIC_STATUS"] = self.fabric.status().get("WEB_FABRIC_STATUS")
        out["audit"] = self.fabric.audit()[-10:]
        return out

    def status(self) -> dict[str, Any]:
        return self.fabric.status()


# PHASE 15 documentation aliases — same provider abstractions, no parallel stack.
WebProvider = WebInformationFabric
SearchProvider = WebSearchProvider
FetchProvider = WebFetchProvider

# PHASE 22 explicit interface aliases / policy wrappers (provider-independent).
WebPageParser = SourceParser
WebContentExtractor = SourceParser
WebCitationProvider = SourceVerifier


class WebPolicyGate:
    """Authorize web operations — SSRF, schemes, budgets, domain policy. Never secrets in URLs."""

    VERSION = "22.0.0"

    def __init__(
        self,
        *,
        allowed_domains: list[str] | None = None,
        denied_domains: list[str] | None = None,
        max_requests: int = 20,
        allow_private: bool = False,
    ) -> None:
        self.allowed_domains = {d.lower() for d in (allowed_domains or [])}
        self.denied_domains = {d.lower() for d in (denied_domains or [])}
        self.max_requests = int(max_requests)
        self.allow_private = bool(allow_private)
        self._count = 0
        self._audit: list[dict[str, Any]] = []

    def authorize_url(self, url: str, *, approved: bool = False, actor: str = "") -> dict[str, Any]:
        self._count += 1
        if self._count > self.max_requests:
            row = {"ok": False, "error": "request_budget_exceeded", "url": url}
            self._audit.append(row)
            return row
        # Credentials must never appear in URLs
        if "@" in (urllib.parse.urlparse(url).netloc or "") and ":" in (urllib.parse.urlparse(url).netloc or ""):
            # user:pass@host pattern
            if urllib.parse.urlparse(url).username or urllib.parse.urlparse(url).password:
                row = {"ok": False, "error": "credentials_in_url_forbidden", "url": "[REDACTED]"}
                self._audit.append(row)
                return row
        check = validate_url_for_fetch(url, allow_private=self.allow_private)
        if not check.get("ok"):
            self._audit.append({"ok": False, "error": check.get("error"), "actor": actor})
            return {"ok": False, "error": check.get("error"), "ssrf_blocked": True}
        host = str(check.get("host") or "").lower()
        if self.denied_domains and any(host == d or host.endswith("." + d) for d in self.denied_domains):
            return {"ok": False, "error": "domain_denied", "host": host}
        if self.allowed_domains and not any(host == d or host.endswith("." + d) for d in self.allowed_domains):
            return {"ok": False, "error": "domain_not_allowlisted", "host": host}
        # External network still requires provider configuration + optional approval for high-risk
        return {
            "ok": True,
            "url": check.get("url"),
            "host": host,
            "approved": bool(approved),
            "actor": actor,
            "version": self.VERSION,
        }

    def audit(self) -> list[dict[str, Any]]:
        return list(self._audit)


class WebResearchSession:
    """Session-scoped research with budgets, provenance, and honest NOT_CONFIGURED behavior."""

    VERSION = "22.0.0"

    def __init__(
        self,
        fabric: WebInformationFabric | None = None,
        *,
        policy: WebPolicyGate | None = None,
        session_id: str = "",
    ) -> None:
        self.fabric = fabric or WebInformationFabric()
        self.policy = policy or WebPolicyGate()
        self.session_id = session_id or hashlib.sha256(str(time.time()).encode()).hexdigest()[:16]
        self.history: list[dict[str, Any]] = []

    def status(self) -> dict[str, Any]:
        st = self.fabric.status()
        return {**st, "session_id": self.session_id, "version": self.VERSION}

    def research(self, query: str, *, limit: int = 5, fetch_top: int = 1, approved: bool = False, actor: str = "") -> dict[str, Any]:
        status = self.fabric.status()
        if status.get("WEB_FABRIC_STATUS") != "READY":
            out = {
                "ok": False,
                "WEB_FABRIC_STATUS": status.get("WEB_FABRIC_STATUS") or "NOT_CONFIGURED",
                "fabricated_citations": False,
                "fabricated_urls": False,
                "citations": [],
                "answer": f"Web research unavailable: WEB_FABRIC_STATUS={status.get('WEB_FABRIC_STATUS')}",
                "session_id": self.session_id,
            }
            self.history.append({"query": query, "ok": False, "status": out["WEB_FABRIC_STATUS"]})
            return out
        result = self.fabric.research(query, limit=limit, fetch_top=fetch_top)
        # Policy-check citation URLs (no auto-fetch of denied domains)
        safe_cites = []
        for c in result.citations:
            auth = self.policy.authorize_url(c.url, approved=approved, actor=actor) if c.url else {"ok": True}
            if auth.get("ok"):
                safe_cites.append(c.to_dict())
        out = result.to_dict()
        out["citations"] = safe_cites
        out["WEB_FABRIC_STATUS"] = status.get("WEB_FABRIC_STATUS")
        out["session_id"] = self.session_id
        out["fabricated_citations"] = False
        out["policy_audit"] = self.policy.audit()[-5:]
        self.history.append({"query": query, "ok": out.get("ok"), "citations": len(safe_cites)})
        return out

MockWebProvider = MockWebSearchProvider
