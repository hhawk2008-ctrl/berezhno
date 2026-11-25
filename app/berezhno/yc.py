"""IAM-токен сервисного аккаунта виртуальной машины (без постоянных ключей на сервере)."""
import time

import httpx

METADATA_TOKEN_URL = "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token"

_token: str | None = None
_token_expires: float = 0.0


async def iam_token(client: httpx.AsyncClient) -> str:
    global _token, _token_expires
    if _token and time.monotonic() < _token_expires - 300:
        return _token
    resp = await client.get(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    _token = data["access_token"]
    _token_expires = time.monotonic() + int(data.get("expires_in", 3600))
    return _token
