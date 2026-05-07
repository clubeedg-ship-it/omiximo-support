"""Tests for the Fernet encryption/decryption service."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.core.exceptions import EncryptionError
from app.services.encryption import decrypt, encrypt


class TestEncryptDecryptRoundtrip:
    """Verify that encrypt/decrypt are inverse operations."""

    def test_roundtrip_basic(self):
        original = "my-secret-api-key"
        token = encrypt(original)
        assert decrypt(token) == original

    def test_roundtrip_unicode(self):
        original = "api-key-with-unicode-€£¥"
        assert decrypt(encrypt(original)) == original

    def test_roundtrip_long_string(self):
        original = "x" * 2048
        assert decrypt(encrypt(original)) == original

    def test_roundtrip_empty_string(self):
        original = ""
        assert decrypt(encrypt(original)) == original

    def test_encrypt_returns_string(self):
        token = encrypt("some-key")
        assert isinstance(token, str)

    def test_encrypt_differs_each_call(self):
        """Fernet tokens are non-deterministic (contain a timestamp + nonce)."""
        key = "same-api-key"
        token1 = encrypt(key)
        token2 = encrypt(key)
        # Tokens will differ even for the same plaintext
        assert token1 != token2
        # But both must decrypt to the same value
        assert decrypt(token1) == decrypt(token2) == key

    def test_encrypt_output_is_not_plaintext(self):
        original = "super-secret-api-key"
        token = encrypt(original)
        assert original not in token

    def test_decrypt_tampered_token_raises(self):
        token = encrypt("valid-key")
        # Flip a character in the middle of the token
        tampered = token[:-5] + ("X" * 5)
        with pytest.raises(EncryptionError, match="Decryption failed"):
            decrypt(tampered)

    def test_decrypt_garbage_raises(self):
        with pytest.raises(EncryptionError):
            decrypt("this-is-not-a-valid-fernet-token!!!")

    def test_decrypt_empty_string_raises(self):
        with pytest.raises(EncryptionError):
            decrypt("")


class TestEncryptionEdgeCases:
    """Edge cases and error paths."""

    def test_mirakl_api_key_pattern(self):
        """Simulate a realistic Mirakl API key format."""
        api_key = "a7f3b1c9-d2e4-4f6a-8b0c-1234567890ab"  # gitleaks:allow
        assert decrypt(encrypt(api_key)) == api_key

    def test_multiple_accounts_isolated(self):
        """Different accounts' keys decrypt independently."""
        key1 = "account-1-key"
        key2 = "account-2-key"
        token1 = encrypt(key1)
        token2 = encrypt(key2)
        assert decrypt(token1) == key1
        assert decrypt(token2) == key2

    def test_known_fernet_key_roundtrip(self, monkeypatch):
        """Test with a freshly generated valid Fernet key."""
        new_key = Fernet.generate_key().decode()
        monkeypatch.setattr("app.services.encryption.settings.FERNET_KEY", new_key)
        original = "test-value"
        assert decrypt(encrypt(original)) == original
