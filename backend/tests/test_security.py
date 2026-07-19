from app.core.security import hash_device_token, verify_device_token


def test_device_token_hash_is_salted_and_verifiable() -> None:
    token = "explicit-test-token"
    first_hash = hash_device_token(token, iterations=1_000)
    second_hash = hash_device_token(token, iterations=1_000)

    assert first_hash != second_hash
    assert token not in first_hash
    assert verify_device_token(token, first_hash) is True
    assert verify_device_token("wrong-token", first_hash) is False


def test_malformed_device_token_hash_is_rejected() -> None:
    assert verify_device_token("test-token", "not-a-valid-hash") is False
