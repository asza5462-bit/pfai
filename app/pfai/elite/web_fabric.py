"""PHASE 13 — Provider-agnostic Web / Information fabric.

Never fabricates search results. Missing providers report WEB_PROVIDER_UNAVAILABLE.
Every external result preserves provenance and claim classification.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any
from html.parser import HTMLParser


class ClaimKind:
    FACT = "FACT"
    SOURCE_DERIVED_CLAIM = "SOURCE-DERIVED CLAIM"
    MODEL_INFERENCE = "MODEL INFERENCE"
    USER_PROVIDED_INFORMATION = "USER-PROVIDED INFORMATION"
    UNCERTAIN_RESULT = "UNCERTAIN RESULT"


WEB_PROVIDER_UNAVAILABLE = "WEB_PROVIDER_UNAVAILABLE"


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


class HttpWebFetchProvider(WebFetchProvider):
    """Real HTTP fetch — only used when explicitly configured/allowed."""

    provider_id = "http_fetch"

    def __init__(self, *, timeout: float = 15.0, user_agent: str = "PFAI-WebFabric/13") -> None:
        self.timeout = float(timeout)
        self.user_agent = user_agent

    def readiness(self) -> dict[str, Any]:
        return {
            "ok": True,
            "provider": self.provider_id,
            "production_ready": True,
            "note": "HTTP fetch enabled; network egress required",
        }

    def fetch(self, url: str, *, max_bytes: int = 200_000) -> dict[str, Any]:
        if not url or not str(url).startswith(("http://", "https://")):
            return {"ok": False, "error": "invalid_url", "provider": self.provider_id}
        req = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept": "text/html,application/json,text/plain"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read(int(max_bytes) + 1)
                truncated = len(raw) > int(max_bytes)
                body = raw[: int(max_bytes)]
                content_type = resp.headers.get("Content-Type", "")
                text = body.decode("utf-8", errors="replace")
                return {
                    "ok": True,
                    "url": url,
                    "final_url": getattr(resp, "geturl", lambda: url)(),
                    "status": getattr(resp, "status", 200),
                    "content_type": content_type,
                    "text": text,
                    "truncated": truncated,
                    "retrieved_at": time.time(),
                    "provider": self.provider_id,
                    "content_hash": hashlib.sha256(body).hexdigest(),
                }
        except urllib.error.HTTPError as exc:
            return {"ok": False, "error": f"http_{exc.code}", "url": url, "provider": self.provider_id}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "url": url, "provider": self.provider_id}


class DuckDuckGoHtmlSearchProvider(WebSearchProvider):
    """Optional HTML search adapter — only when PFAI_WEB_SEARCH_PROVIDER=ddg."""

    provider_id = "ddg_html"

    def __init__(self, *, timeout: float = 15.0) -> None:
        self.timeout = float(timeout)
        self._fetch = HttpWebFetchProvider(timeout=timeout)

    def readiness(self) -> dict[str, Any]:
        return {
            "ok": True,
            "provider": self.provider_id,
            "production_ready": True,
            "note": "DuckDuckGo HTML scrape adapter; results may be sparse",
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
        text = str(fetched.get("text") or "")
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
            # Freshness heuristic
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
    # DuckDuckGo HTML result anchors
    for m in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        html or "",
        flags=re.I | re.S,
    ):
        href = urllib.parse.unquote(m.group(1))
        # DDG sometimes wraps uddg=
        if "uddg=" in href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            href = (qs.get("uddg") or [href])[0]
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        results.append({"url": href, "title": title, "snippet": ""})
        if len(results) >= limit:
            break
    # Snippets
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)', html or "", flags=re.I | re.S)
    for i, sn in enumerate(snippets[: len(results)]):
        results[i]["snippet"] = re.sub(r"<[^>]+>", "", sn).strip()[:400]
    return results


def web_providers_from_env() -> tuple[WebSearchProvider, WebFetchProvider]:
    search_kind = (os.environ.get("PFAI_WEB_SEARCH_PROVIDER") or "").strip().lower()
    fetch_kind = (os.environ.get("PFAI_WEB_FETCH_PROVIDER") or "").strip().lower()
    allow_network = (os.environ.get("PFAI_WEB_ALLOW_NETWORK") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    search: WebSearchProvider
    if search_kind in ("ddg", "ddg_html", "duckduckgo") and allow_network:
        search = DuckDuckGoHtmlSearchProvider(
            timeout=float(os.environ.get("PFAI_WEB_TIMEOUT", "15") or 15)
        )
    else:
        search = UnavailableWebSearchProvider()

    fetch: WebFetchProvider
    if fetch_kind in ("http", "http_fetch") and allow_network:
        fetch = HttpWebFetchProvider(timeout=float(os.environ.get("PFAI_WEB_TIMEOUT", "15") or 15))
    elif search_kind in ("ddg", "ddg_html", "duckduckgo") and allow_network:
        # Search implies fetch capability for result bodies when allowed
        fetch = HttpWebFetchProvider(timeout=float(os.environ.get("PFAI_WEB_TIMEOUT", "15") or 15))
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
    available = bool(sr.get("ok")) or bool(fr.get("ok"))
    return {
        "WEB_SEARCH_PROVIDER": getattr(s, "provider_id", "unknown"),
        "WEB_FETCH_PROVIDER": getattr(f, "provider_id", "unknown"),
        "WEB_PROVIDER_AVAILABLE": available,
        "WEB_STATUS": "READY" if available else WEB_PROVIDER_UNAVAILABLE,
        "search_production_ready": bool(sr.get("production_ready")),
        "fetch_production_ready": bool(fr.get("production_ready")),
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
    ) -> None:
        if search is None or fetch is None:
            s, f = web_providers_from_env()
            search = search or s
            fetch = fetch or f
        self.search_provider = search
        self.fetch_provider = fetch
        self.parser = parser or SourceParser()
        self.verifier = verifier or SourceVerifier()
        self.planner = planner or ResearchPlanner()

    def status(self) -> dict[str, Any]:
        return web_config_report(self.search_provider, self.fetch_provider)

    def research(self, query: str, *, limit: int = 5, fetch_top: int = 2) -> ResearchResult:
        plan = self.planner.plan(query)
        search_out = self.search_provider.search(query, limit=limit)
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
            snippet = str(row.get("snippet") or "")
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

        # Optional deeper fetch
        for row in results[: max(0, int(fetch_top))]:
            url = str(row.get("url") or "")
            if not url:
                continue
            fetched = self.fetch_provider.fetch(url)
            if not fetched.get("ok"):
                # Do not invent content; note failure on citation meta
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
        # Distinguish model inference: we only summarize source titles — mark as SOURCE-DERIVED
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
