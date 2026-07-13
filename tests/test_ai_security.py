from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.services.ai_credentials import ByokCredentialCipher, ByokCredentialError


def test_byok_cipher_encrypts_and_authenticates_provider_key() -> None:
    cipher = ByokCredentialCipher(Fernet.generate_key().decode("ascii"))
    ciphertext = cipher.encrypt("synthetic-provider-key-1234")

    assert "synthetic-provider-key" not in ciphertext
    assert cipher.decrypt(ciphertext) == "synthetic-provider-key-1234"

    tampered = bytearray(ciphertext.encode("ascii"))
    midpoint = len(tampered) // 2
    tampered[midpoint] = ord("A") if tampered[midpoint] != ord("A") else ord("B")
    with pytest.raises(InvalidToken):
        cipher.decrypt(tampered.decode("ascii"))


def test_byok_cipher_rejects_wrong_or_invalid_master_key() -> None:
    cipher = ByokCredentialCipher(Fernet.generate_key().decode("ascii"))
    ciphertext = cipher.encrypt("synthetic-provider-key-1234")

    wrong = ByokCredentialCipher(Fernet.generate_key().decode("ascii"))
    with pytest.raises(InvalidToken):
        wrong.decrypt(ciphertext)
    with pytest.raises(ByokCredentialError):
        ByokCredentialCipher("not-a-fernet-key")
