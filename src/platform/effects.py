"""Small value objects shared by independent Platform effect adapters."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlatformRunResult:
    receipts_emitted: int
