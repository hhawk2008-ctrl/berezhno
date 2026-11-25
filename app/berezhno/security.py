"""Коды входа, токены сеансов и подписанные значения для кук."""
import base64
import hashlib
import hmac
import secrets
import time


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(secret: str, email: str, code: str) -> str:
    return hmac.new(secret.encode(), f"login:{email}:{code}".encode(), hashlib.sha256).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _sig(secret: str, payload: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:40]


def sign(secret: str, value: str) -> str:
    payload = base64.urlsafe_b64encode(f"{int(time.time())}|{value}".encode()).decode().rstrip("=")
    return f"{payload}.{_sig(secret, payload)}"


def unsign(secret: str, signed: str | None, max_age: int) -> str | None:
    """Значение из sign(), если подпись верна и не старше max_age секунд, иначе None."""
    if not signed or "." not in signed:
        return None
    payload, sig = signed.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sig(secret, payload)):
        return None
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
        ts, value = raw.split("|", 1)
    except ValueError:
        return None
    if time.time() - int(ts) > max_age:
        return None
    return value
