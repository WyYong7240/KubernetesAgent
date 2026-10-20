from __future__ import annotations

import hashlib
import hmac

from fastapi import Header, HTTPException, Request, status

from app.core.config import Settings


async def verify_dagger_signature(
    request: Request,
    x_dagger_signature: str | None = Header(default=None),
) -> None:
    """Verify an optional development or mandatory production DAGGER HMAC signature."""
    settings: Settings = request.app.state.settings
    secret = settings.dagger_webhook_secret
    if not secret:
        if settings.requires_dagger_signature:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DAGGER_WEBHOOK_SECRET must be configured in production.",
            )
        return

    if x_dagger_signature is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-Dagger-Signature.")

    signature = x_dagger_signature.removeprefix("sha256=")
    expected = hmac.new(secret.encode("utf-8"), await request.body(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid DAGGER signature.")
