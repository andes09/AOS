import base64
import logging

from cryptography.fernet import Fernet, InvalidToken
from src.config import settings

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    # Convert 32-byte hex key to Fernet-compatible 32-byte key
    try:
        key_bytes = bytes.fromhex(settings.encryption_key)
        fernet_key = base64.urlsafe_b64encode(key_bytes)
        return Fernet(fernet_key)
    except Exception:
        # A malformed ENCRYPTION_KEY breaks every encrypt/decrypt call site at
        # once. Name the cause here rather than letting a ValueError about hex
        # digits surface from whichever feature happened to touch a key first.
        logger.exception("ENCRYPTION_KEY is malformed — expected a 32-byte hex string")
        raise


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        # Almost always means ENCRYPTION_KEY was rotated/changed while rows
        # encrypted under the previous key are still stored — every BYOK key in
        # the database becomes unreadable at once. The ciphertext is never
        # logged.
        logger.error(
            "Failed to decrypt a stored secret — ENCRYPTION_KEY likely changed "
            "since this value was written"
        )
        raise
