"""Fernet encryption/decryption for Mirakl API keys.

Architecture decision D3 mandates that API keys are never stored in plaintext.
This module wraps the cryptography.fernet.Fernet primitive and exposes two
simple functions used by the service layer.

The Fernet key is loaded from settings.FERNET_KEY.  The key must be a valid
32-byte URL-safe base64-encoded string (generate with Fernet.generate_key()).
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.core.exceptions import EncryptionError


def _get_fernet() -> Fernet:
    """Instantiate a Fernet cipher from the configured key.

    This is intentionally kept as a function rather than a module-level
    singleton so that the key can be swapped in tests without patching a
    global object.
    """
    try:
        return Fernet(settings.FERNET_KEY.encode())
    except (ValueError, TypeError) as exc:
        raise EncryptionError(
            "Invalid FERNET_KEY: must be a 32-byte URL-safe base64-encoded string",
            detail=str(exc),
        ) from exc


def encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* and return the Fernet token as a UTF-8 string.

    Args:
        plaintext: The value to encrypt (e.g. a raw Mirakl API key).

    Returns:
        URL-safe base64-encoded Fernet token string.

    Raises:
        EncryptionError: If the key is invalid or encryption fails.
    """
    fernet = _get_fernet()
    try:
        token: bytes = fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")
    except Exception as exc:
        raise EncryptionError("Encryption failed", detail=str(exc)) from exc


def decrypt(token: str) -> str:
    """Decrypt a Fernet *token* and return the original plaintext.

    Args:
        token: A Fernet token string as returned by :func:`encrypt`.

    Returns:
        The decrypted plaintext string.

    Raises:
        EncryptionError: If the token is invalid, expired, or the key is wrong.
    """
    fernet = _get_fernet()
    try:
        plaintext: bytes = fernet.decrypt(token.encode("utf-8"))
        return plaintext.decode("utf-8")
    except InvalidToken as exc:
        raise EncryptionError(
            "Decryption failed: invalid or tampered token",
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise EncryptionError("Decryption failed", detail=str(exc)) from exc
