from __future__ import annotations

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AiProviderCredential
from app.services.ai_providers import PROVIDER_CODES

FERNET_ENCRYPTION_VERSION = "FERNET_V1"


class ByokCredentialError(ValueError):
    pass


class ByokCredentialCipher:
    def __init__(self, master_key: str) -> None:
        if not master_key or master_key != master_key.strip():
            raise ByokCredentialError("BYOK master key 설정이 유효하지 않습니다.")
        try:
            self._fernet = Fernet(master_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as error:
            raise ByokCredentialError("BYOK master key 형식이 유효하지 않습니다.") from error

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")


def save_provider_credential(
    session: Session,
    *,
    actor_ref: str,
    provider: str,
    api_key: str,
    cipher: ByokCredentialCipher,
) -> AiProviderCredential:
    _validate_identity(actor_ref, provider)
    if (
        api_key != api_key.strip()
        or any(character.isspace() for character in api_key)
        or not 8 <= len(api_key) <= 4096
    ):
        raise ByokCredentialError("API 키는 공백 없이 8자 이상 4096자 이하여야 합니다.")
    record = session.scalar(
        select(AiProviderCredential).where(
            AiProviderCredential.actor_ref == actor_ref,
            AiProviderCredential.provider == provider,
        )
    )
    encrypted = cipher.encrypt(api_key)
    if record is None:
        record = AiProviderCredential(
            actor_ref=actor_ref,
            provider=provider,
            encrypted_api_key=encrypted,
            masked_hint=_masked_hint(api_key),
            encryption_version=FERNET_ENCRYPTION_VERSION,
        )
        session.add(record)
    else:
        record.encrypted_api_key = encrypted
        record.masked_hint = _masked_hint(api_key)
        record.encryption_version = FERNET_ENCRYPTION_VERSION
    return record


def decrypt_provider_credential(
    record: AiProviderCredential,
    cipher: ByokCredentialCipher,
) -> str:
    if record.encryption_version != FERNET_ENCRYPTION_VERSION:
        raise ByokCredentialError("지원하지 않는 BYOK 키 암호화 버전입니다.")
    return cipher.decrypt(record.encrypted_api_key)


def delete_provider_credential(session: Session, *, actor_ref: str, provider: str) -> bool:
    _validate_identity(actor_ref, provider)
    record = session.scalar(
        select(AiProviderCredential).where(
            AiProviderCredential.actor_ref == actor_ref,
            AiProviderCredential.provider == provider,
        )
    )
    if record is None:
        return False
    session.delete(record)
    return True


def _validate_identity(actor_ref: str, provider: str) -> None:
    if not actor_ref or actor_ref != actor_ref.strip() or len(actor_ref) > 120:
        raise ByokCredentialError("관리자 식별자가 유효하지 않습니다.")
    if provider not in PROVIDER_CODES:
        raise ByokCredentialError("지원하지 않는 BYOK 공급자입니다.")


def _masked_hint(api_key: str) -> str:
    return f"••••{api_key[-4:]}"


__all__ = [
    "ByokCredentialCipher",
    "ByokCredentialError",
    "FERNET_ENCRYPTION_VERSION",
    "decrypt_provider_credential",
    "delete_provider_credential",
    "save_provider_credential",
]
