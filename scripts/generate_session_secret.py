"""Print a cryptographically random secret for local .env configuration."""

from __future__ import annotations

import secrets

if __name__ == "__main__":
    print(secrets.token_urlsafe(48))
