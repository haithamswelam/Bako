"""Safety net for the password spans: the spans must not change what the functions do."""
from app.security import hash_password, verify_password


def test_hash_then_verify_works():
    h = hash_password("correct horse")
    assert h != "correct horse"
    assert verify_password("correct horse", h) is True


def test_wrong_password_is_refused():
    h = hash_password("correct horse")
    assert verify_password("wrong horse", h) is False
