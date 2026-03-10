import base64
from cryptography.fernet import Fernet
from src.config import settings


def _get_fernet() -> Fernet:
    # Convert 32-byte hex key to Fernet-compatible 32-byte key
    key_bytes = bytes.fromhex(settings.encryption_key)
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
