from urllib.parse import urlparse


class Policy:
    """Central deny-by-default network/tool policy.

    Network access requires BOTH an explicit network opt-in and a non-empty
    exact-host allowlist. An empty allowlist never means "allow all".
    """
    def __init__(self, cfg):
        self.network = bool(cfg.get("allow_network", False))
        self.domains = {str(d).strip().lower().rstrip(".") for d in cfg.get("allowed_domains", []) if str(d).strip()}
        self.max_chars = int(cfg.get("max_response_chars", 20000))

    def allow_url(self, url):
        if not self.network or not self.domains:
            return False
        try:
            parsed = urlparse(url)
        except ValueError:
            return False
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            return False
        return parsed.hostname.lower().rstrip(".") in self.domains
