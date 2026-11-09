import pytest

from sme_financial_dashboard.security.passwords import (
    PasswordError,
    hash_password,
    needs_rehash,
    validate_password,
    verify_password,
)


def test_argon2id_hash_and_verify():
    password = "Correct-Horse-Battery-19"
    encoded = hash_password(password)
    assert encoded.startswith("$argon2id$")
    assert verify_password(encoded, password)
    assert not verify_password(encoded, "wrong-password")


@pytest.mark.parametrize("password", ["short", " " * 12, "x" * 129, "contains\x00null!"])
def test_password_policy_rejects_invalid_password(password):
    with pytest.raises(PasswordError):
        validate_password(password)


def test_malformed_hash_is_not_accepted():
    assert not verify_password("not-a-hash", "some-password")
