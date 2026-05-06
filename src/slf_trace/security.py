import hashlib
import hmac
import secrets


def generate_station_token() -> str:
    return secrets.token_urlsafe(32)


def hash_station_token(token: str) -> str:
    return "sha256$" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_station_token(token: str, token_hash: str | None) -> bool:
    if not token_hash:
        return False
    algorithm, _, digest = token_hash.partition("$")
    if algorithm != "sha256" or not digest:
        return False
    candidate = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate, digest)
