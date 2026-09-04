"""User records and address validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")


@dataclass
class Address:
    street: str
    city: str
    state: str
    zip_code: str

    def validate(self) -> list[str]:
        problems = []
        if not self.street.strip():
            problems.append("street is required")
        if not self.city.strip():
            problems.append("city is required")
        if len(self.state) != 2 or not self.state.isalpha():
            problems.append("state must be a two-letter code")
        if not _ZIP_RE.match(self.zip_code):
            problems.append("zip code must be 5 digits (optionally +4)")
        return problems


@dataclass
class User:
    email: str
    name: str
    addresses: list[Address] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not _EMAIL_RE.match(self.email):
            raise ValueError(f"invalid email: {self.email!r}")

    def default_address(self) -> Address:
        if not self.addresses:
            raise LookupError(f"{self.email} has no saved address")
        return self.addresses[0]
