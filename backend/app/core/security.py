import base64
import binascii
import hashlib
import hmac
import secrets

TOKEN_SCHEME = "pbkdf2_sha256"


def hash_device_token(token: str, iterations: int = 260_000) -> str:
    if not token:
        raise ValueError("Device token must not be empty")
    if iterations < 1:
        raise ValueError("PBKDF2 iterations must be positive")

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", token.encode(), salt, iterations)
    return "$".join(
        (
            TOKEN_SCHEME,
            str(iterations),
            base64.urlsafe_b64encode(salt).decode(),
            base64.urlsafe_b64encode(digest).decode(),
        )
    )


def verify_device_token(token: str, encoded_hash: str) -> bool:
    try:
        scheme, iterations_text, salt_text, digest_text = encoded_hash.split("$", 3)
        if scheme != TOKEN_SCHEME:
            return False
        iterations = int(iterations_text)
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
    except (binascii.Error, TypeError, ValueError):
        return False

    actual = hashlib.pbkdf2_hmac("sha256", token.encode(), salt, iterations)
    return hmac.compare_digest(actual, expected)


hash_password = hash_device_token
verify_password = verify_device_token


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
