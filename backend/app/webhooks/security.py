import hashlib
import hmac


def verify_hmac_sha256(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Verify a `sha256=<hex>` style signature (GitHub / Jira HMAC webhooks)."""
    if not secret:
        return True  # no secret configured -> verification disabled (dev only)
    if not signature_header:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)
