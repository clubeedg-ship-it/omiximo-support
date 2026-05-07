"""Domain-specific exception hierarchy for Omiximo Support Automation."""

from __future__ import annotations


class OmiximoBaseError(Exception):
    """Root exception for all application errors."""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r}, detail={self.detail!r})"


# --------------------------------------------------------------------------- #
# External API Errors                                                          #
# --------------------------------------------------------------------------- #


class MiraklAPIError(OmiximoBaseError):
    """Raised when a Mirakl REST API call fails.

    Attributes:
        status_code: The HTTP status code returned by Mirakl (if available).
        account_id:  The marketplace_account.id that triggered the error.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        account_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, detail=detail)
        self.status_code = status_code
        self.account_id = account_id


class ClassificationError(OmiximoBaseError):
    """Raised when the LLM classifier returns an unexpected or unparseable response."""

    def __init__(
        self,
        message: str,
        *,
        raw_response: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, detail=detail)
        self.raw_response = raw_response


# --------------------------------------------------------------------------- #
# Template Errors                                                              #
# --------------------------------------------------------------------------- #


class TemplateNotFoundError(OmiximoBaseError):
    """Raised when no matching response template exists for the given criteria.

    Attributes:
        category:    The message category that was looked up.
        language:    The customer language code (nl/en/fr/de).
        account_id:  The marketplace_account.id scoping the lookup.
    """

    def __init__(
        self,
        message: str,
        *,
        category: str | None = None,
        language: str | None = None,
        account_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, detail=detail)
        self.category = category
        self.language = language
        self.account_id = account_id


class TemplateRenderError(OmiximoBaseError):
    """Raised when Jinja2 rendering of a template body fails."""


# --------------------------------------------------------------------------- #
# Safety Errors                                                                #
# --------------------------------------------------------------------------- #


class SafetyViolationError(OmiximoBaseError):
    """Raised when a drafted response fails one or more hard safety rules.

    Attributes:
        violations: List of human-readable rule descriptions that were violated.
    """

    def __init__(
        self,
        message: str,
        *,
        violations: list[str] | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message, detail=detail)
        self.violations: list[str] = violations or []


# --------------------------------------------------------------------------- #
# Encryption Errors                                                            #
# --------------------------------------------------------------------------- #


class EncryptionError(OmiximoBaseError):
    """Raised when Fernet encryption or decryption fails."""
