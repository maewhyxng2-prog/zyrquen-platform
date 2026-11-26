import bcrypt

from apps.api.security import hash_password, verify_password


def test_hash_password_verifies_long_passwords():
    password = "a" * 128

    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password(password[:-1], hashed)


def test_verify_password_accepts_existing_bcrypt_hashes():
    password = "LegacyPassword123"
    legacy_hash = bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("ascii")

    assert verify_password(password, legacy_hash)


def test_verify_password_rejects_malformed_hash():
    assert not verify_password("password", "not-a-password-hash")
