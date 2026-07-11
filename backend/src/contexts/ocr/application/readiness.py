from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from src.shared.internal_status_codes import InternalStatusCode


ReadinessProbe = Callable[[], Awaitable[None]]


@dataclass(slots=True, frozen=True)
class DependencyReadinessCheck:
    name: str
    internal_code: InternalStatusCode
    probe: ReadinessProbe


@dataclass(slots=True, frozen=True)
class ReadinessReport:
    checks: dict[str, str]
    internal_code: InternalStatusCode | None = None
    error_reason: str | None = None

    @property
    def ready(self) -> bool:
        return self.internal_code is None


class ReadinessService:
    """Runs dependency probes without exposing exception or connection details."""

    def __init__(
        self,
        checks: Sequence[DependencyReadinessCheck] = (),
        *,
        timeout_seconds: float = 2.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("readiness timeout must be positive")
        self._checks = tuple(checks)
        self._timeout_seconds = timeout_seconds

    async def check(self) -> ReadinessReport:
        results = await asyncio.gather(
            *(self._run_probe(check) for check in self._checks)
        )
        checks = {"application": "ok"}
        first_failure: DependencyReadinessCheck | None = None
        for check, succeeded in zip(self._checks, results, strict=True):
            checks[check.name] = "ok" if succeeded else "unavailable"
            if not succeeded and first_failure is None:
                first_failure = check
        if first_failure is None:
            return ReadinessReport(checks=checks)
        return ReadinessReport(
            checks=checks,
            internal_code=first_failure.internal_code,
            error_reason=f"readiness_{first_failure.name}_unavailable",
        )

    async def _run_probe(self, check: DependencyReadinessCheck) -> bool:
        try:
            await asyncio.wait_for(check.probe(), timeout=self._timeout_seconds)
        except Exception:
            return False
        return True


__all__ = [
    "DependencyReadinessCheck",
    "ReadinessReport",
    "ReadinessService",
]
