import hashlib
import hmac
import logging

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


def verify_hmac_sha256(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Verify a `sha256=<hex>` style signature (GitHub / Jira HMAC webhooks).

    Fails closed: with no secret there is nothing to verify against, so nothing verifies."""
    if not secret or not signature_header:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def require_valid_signature(
    secret_name: str, secret: str, body: bytes, signature_header: str | None
) -> None:
    """Reject a webhook unless `body` is signed with the secret configured as `secret_name`.

    An unset secret refuses every request (403) instead of accepting unsigned payloads — these
    endpoints are publicly routed, and anyone can read which ones exist."""
    if not secret:
        logger.warning("Rejected a webhook: %s is not set, so it can't be verified", secret_name)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Webhook intake is disabled until {secret_name} is configured",
        )
    if not verify_hmac_sha256(secret, body, signature_header):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad signature")
