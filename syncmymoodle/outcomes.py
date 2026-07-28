"""Typed download outcomes and statistics for one sync run."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

import requests


@dataclass(frozen=True, order=True)
class RemovedContent:
    """One remotely absent item whose local copy is intentionally retained."""

    course: str
    old_path: str
    remote_identity: str


class AuthenticationFailure(RuntimeError):
    """An expected authentication failure that may affect one resource."""


class FailureCode(StrEnum):
    """Stable diagnostic codes for failures that count toward the exit status."""

    NETWORK_PROVIDER = "SMM-NETWORK-PROVIDER"
    AUTHENTICATION = "SMM-AUTHENTICATION"
    LOCAL_STORAGE = "SMM-LOCAL-STORAGE"
    INTERNAL = "SMM-INTERNAL"


POLICY_SKIP_CODE = "SMM-POLICY-SKIP"
_FAILURE_PRIORITY = {
    FailureCode.NETWORK_PROVIDER: 0,
    FailureCode.AUTHENTICATION: 1,
    FailureCode.LOCAL_STORAGE: 2,
    FailureCode.INTERNAL: 3,
}


def classify_exception(error: Exception) -> FailureCode:
    """Classify a caught resource exception without hiding programming errors."""
    if isinstance(error, AuthenticationFailure):
        return FailureCode.AUTHENTICATION
    if isinstance(error, requests.RequestException):
        return FailureCode.NETWORK_PROVIDER
    if isinstance(error, OSError):
        return FailureCode.LOCAL_STORAGE
    return FailureCode.INTERNAL


@dataclass(frozen=True)
class DownloadOutcome:
    """The complete user-visible result of processing one download node."""

    failure_code: FailureCode | None = None
    downloaded: int = 0
    updated: int = 0
    unchanged: int = 0
    planned: int = 0
    policy_skipped: int = 0
    transferred_bytes: int = 0
    cache_verified: bool = True

    @property
    def is_handled(self) -> bool:
        return self.failure_code is None

    def __bool__(self) -> bool:
        raise TypeError("Use DownloadOutcome.is_handled instead of truth testing")

    def merge(self, other: DownloadOutcome) -> DownloadOutcome:
        """Combine artifact outcomes belonging to the same download node."""
        failure_code = max(
            (
                code
                for code in (self.failure_code, other.failure_code)
                if code is not None
            ),
            key=_FAILURE_PRIORITY.__getitem__,
            default=None,
        )
        return DownloadOutcome(
            failure_code=failure_code,
            downloaded=self.downloaded + other.downloaded,
            updated=self.updated + other.updated,
            unchanged=self.unchanged + other.unchanged,
            planned=self.planned + other.planned,
            policy_skipped=self.policy_skipped + other.policy_skipped,
            transferred_bytes=self.transferred_bytes + other.transferred_bytes,
            cache_verified=self.cache_verified and other.cache_verified,
        )


HANDLED_DOWNLOAD = DownloadOutcome()
SKIPPED_DOWNLOAD = DownloadOutcome(cache_verified=False)
POLICY_SKIPPED_DOWNLOAD = DownloadOutcome(
    unchanged=1,
    policy_skipped=1,
    cache_verified=False,
)
UNCHANGED_DOWNLOAD = DownloadOutcome(unchanged=1)
PLANNED_DOWNLOAD = DownloadOutcome(planned=1, cache_verified=False)


def failed_download(code: FailureCode) -> DownloadOutcome:
    return DownloadOutcome(failure_code=code, cache_verified=False)


FAILED_DOWNLOAD = failed_download(FailureCode.NETWORK_PROVIDER)


def completed_download(*, existed: bool, transferred_bytes: int = 0) -> DownloadOutcome:
    """Build the outcome of installing one requested artifact."""
    return DownloadOutcome(
        downloaded=int(not existed),
        updated=int(existed),
        transferred_bytes=max(0, transferred_bytes),
    )


@dataclass
class RunStatistics:
    """User-relevant outcomes accumulated during one sync run."""

    courses: int = 0
    downloaded: int = 0
    updated: int = 0
    unchanged: int = 0
    planned: int = 0
    policy_skipped: int = 0
    transferred_bytes: int = 0
    failure_counts: dict[FailureCode, int] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic, repr=False)

    @property
    def failed(self) -> int:
        return sum(self.failure_counts.values())

    def record_failure(self, code: FailureCode) -> None:
        self.failure_counts[code] = self.failure_counts.get(code, 0) + 1

    def record_download(self, outcome: DownloadOutcome) -> None:
        self.downloaded += outcome.downloaded
        self.updated += outcome.updated
        self.unchanged += outcome.unchanged
        self.planned += outcome.planned
        self.policy_skipped += outcome.policy_skipped
        self.transferred_bytes += outcome.transferred_bytes
        if outcome.failure_code is not None:
            self.record_failure(outcome.failure_code)

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)
