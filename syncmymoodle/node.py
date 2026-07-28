from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

NAME_CLASH_ID_UNSET = object()


class RemoteMarkerKind(StrEnum):
    CONTENT_HASH = "content_hash"
    OPAQUE = "opaque"


class DownloadStatus(StrEnum):
    PENDING = "pending"
    HANDLED = "handled"
    SKIPPED = "skipped"


class DownloadKind(StrEnum):
    """Download behavior recorded separately from the display-only node type."""

    DIRECT = "direct"
    YOUTUBE = "youtube"
    EMEDIA = "emedia"
    QUIZ = "quiz"
    OPENCAST = "opencast"


class NodeKind(StrEnum):
    """Structural roles in the synchronized Moodle tree."""

    ROOT = "Root"
    SEMESTER = "Semester"
    COURSE = "Course"
    SECTION = "Section"


@dataclass(frozen=True)
class DownloadArtifact:
    """Complete local state for one downloaded remote artifact."""

    path: str
    content_hash: str
    size: int
    remote_identity: str

    def __post_init__(self) -> None:
        portable_path = PurePosixPath(self.path) if isinstance(self.path, str) else None
        if (
            portable_path is None
            or not self.path
            or "\\" in self.path
            or portable_path.is_absolute()
            or ".." in portable_path.parts
            or portable_path.as_posix() != self.path
            or not isinstance(self.content_hash, str)
            or len(self.content_hash) != 64
            or any(
                character not in "0123456789abcdef" for character in self.content_hash
            )
            or not isinstance(self.size, int)
            or isinstance(self.size, bool)
            or self.size < 0
            or not isinstance(self.remote_identity, str)
            or not self.remote_identity
        ):
            raise ValueError("invalid downloaded artifact metadata")

    @classmethod
    def from_value(cls, value: Any) -> DownloadArtifact | None:
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict) or set(value) != {
            "path",
            "content_hash",
            "size",
            "remote_identity",
        }:
            return None
        try:
            return cls(
                value["path"],
                value["content_hash"],
                value["size"],
                value["remote_identity"],
            )
        except (TypeError, ValueError):
            return None

    def to_cache_data(self) -> dict[str, str | int]:
        return {
            "path": self.path,
            "content_hash": self.content_hash,
            "size": self.size,
            "remote_identity": self.remote_identity,
        }


def _remote_marker_kind(
    value: RemoteMarkerKind | str | None,
) -> RemoteMarkerKind | None:
    if value is None:
        return None
    try:
        return RemoteMarkerKind(value)
    except ValueError:
        return None


def _download_status(value: DownloadStatus | str | None) -> DownloadStatus | None:
    if value is None:
        return None
    try:
        return DownloadStatus(value)
    except ValueError:
        return None


def _download_kind(value: DownloadKind | str | None) -> DownloadKind:
    try:
        return DownloadKind(value or DownloadKind.DIRECT)
    except ValueError:
        return DownloadKind.DIRECT


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _artifact_hashes(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        key: digest
        for key, digest in value.items()
        if isinstance(key, str)
        and key.isalnum()
        and isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    }


class Node:
    def __init__(
        self,
        name: str,
        id: Any,
        type: str,  # noqa: A003 - keep original name for compatibility
        parent: Node | None,
        url: str | None = None,
        download_headers: dict[str, str] | None = None,
        timemodified: Any = None,
        etag: str | None = None,
        etag_kind: RemoteMarkerKind | str | None = None,
        content_hash: str | None = None,
        artifact: DownloadArtifact | dict[str, Any] | None = None,
        artifact_hashes: dict[str, str] | None = None,
        remote_size: Any = None,
        name_clash_id: Any = NAME_CLASH_ID_UNSET,
        download_status: DownloadStatus | str | None = None,
        download_kind: DownloadKind | str | None = None,
    ) -> None:
        self.name = name
        self.id = id
        self.url = url
        self.type = type
        self.parent = parent
        self.children: list[Node] = []
        self.download_headers = dict(download_headers) if download_headers else None
        self.timemodified = timemodified
        self.etag = etag
        self.etag_kind = _remote_marker_kind(etag_kind)
        # A content hash (sha256 hex) we compute from the bytes we downloaded.
        # Unlike etag, which for Sciebo/WebDAV is an opaque revision token, this
        # is a real hash of our copy, used to detect local user modifications.
        self.artifact = DownloadArtifact.from_value(artifact)
        self._legacy_content_hash = (
            content_hash
            if self.artifact is None and isinstance(content_hash, str)
            else None
        )
        self.artifact_hashes = _artifact_hashes(artifact_hashes)
        self.remote_size = _optional_int(remote_size)
        self.name_clash_id = (
            id if name_clash_id is NAME_CLASH_ID_UNSET else name_clash_id
        )
        self.download_status = (
            _download_status(download_status) or DownloadStatus.PENDING
        )
        self.download_kind = _download_kind(download_kind)
        self._conflicting_download_metadata: set[str] = set()

    def __repr__(self) -> str:
        return (
            f"Node(has_url={self.url is not None}, type={self.type}, "
            f"download_kind={self.download_kind})"
        )

    @property
    def is_handled(self) -> bool:
        return self.download_status != DownloadStatus.PENDING

    @property
    def is_verified(self) -> bool:
        return self.download_status == DownloadStatus.HANDLED

    @property
    def content_hash(self) -> str | None:
        if self.artifact is not None:
            return self.artifact.content_hash
        return self._legacy_content_hash

    @content_hash.setter
    def content_hash(self, value: str | None) -> None:
        self.artifact = None
        self._legacy_content_hash = value

    def record_artifact(self, artifact: DownloadArtifact) -> None:
        self.artifact = artifact
        self._legacy_content_hash = None

    @property
    def has_remote_marker_conflict(self) -> bool:
        return "remote_marker" in self._conflicting_download_metadata

    def mark_handled(self) -> None:
        self.download_status = DownloadStatus.HANDLED

    def mark_skipped(self) -> None:
        self.download_status = DownloadStatus.SKIPPED

    def add_child(
        self,
        name: str,
        id: Any,
        type: str,  # noqa: A003 - keep original name for compatibility
        url: str | None = None,
        download_headers: dict[str, str] | None = None,
        timemodified: Any = None,
        etag: str | None = None,
        etag_kind: RemoteMarkerKind | str | None = None,
        remote_size: Any = None,
        name_clash_id: Any = NAME_CLASH_ID_UNSET,
        download_kind: DownloadKind | str | None = None,
    ) -> Node:
        temp = Node(
            name,
            id,
            type,
            self,
            url=url,
            download_headers=download_headers,
            timemodified=timemodified,
            etag=etag,
            etag_kind=etag_kind,
            remote_size=remote_size,
            name_clash_id=name_clash_id,
            download_kind=download_kind,
        )
        self.children.append(temp)
        return temp

    @staticmethod
    def _reconcile_download_metadata(existing: Node, candidate: Node) -> None:
        for attr in ("download_headers", "timemodified", "remote_size"):
            if attr in existing._conflicting_download_metadata:
                continue
            old = getattr(existing, attr)
            new = getattr(candidate, attr)
            if old is None:
                setattr(existing, attr, new)
            elif new is not None and old != new:
                setattr(existing, attr, None)
                existing._conflicting_download_metadata.add(attr)

        if "remote_marker" in existing._conflicting_download_metadata:
            return
        if existing.etag is None and candidate.etag is not None:
            existing.etag = candidate.etag
            existing.etag_kind = candidate.etag_kind
        elif candidate.etag is not None and (
            existing.etag != candidate.etag
            or (
                existing.etag_kind is not None
                and candidate.etag_kind is not None
                and existing.etag_kind != candidate.etag_kind
            )
        ):
            existing.etag = None
            existing.etag_kind = None
            existing._conflicting_download_metadata.add("remote_marker")
        elif candidate.etag is not None and existing.etag_kind is None:
            existing.etag_kind = candidate.etag_kind

    def add_download_child(
        self,
        name: str,
        id: Any,
        type: str,  # noqa: A003 - keep original name for compatibility
        *,
        url: str,
        download_headers: dict[str, str] | None = None,
        timemodified: Any = None,
        etag: str | None = None,
        etag_kind: RemoteMarkerKind | str | None = None,
        remote_size: Any = None,
        name_clash_id: Any = NAME_CLASH_ID_UNSET,
        download_kind: DownloadKind | str | None = None,
    ) -> Node:
        """Add one discovered download, reconciling a compatible URL duplicate.

        Structural insertion remains unconditional in :meth:`add_child`. This
        operation makes provider-level materialization deduplication explicit:
        a repeated name and URL strengthens missing metadata instead of
        creating two downloads for the same target path.
        """
        candidate = Node(
            name,
            id,
            type,
            self,
            url=url,
            download_headers=download_headers,
            timemodified=timemodified,
            etag=etag,
            etag_kind=etag_kind,
            remote_size=remote_size,
            name_clash_id=name_clash_id,
            download_kind=download_kind,
        )
        existing = next(
            (
                child
                for child in self.children
                if child.url == url and child.name == candidate.name
            ),
            None,
        )
        if existing is None:
            self.children.append(candidate)
            return candidate
        if (
            existing.type != candidate.type
            or existing.download_kind is not candidate.download_kind
        ):
            raise ValueError(
                "conflicting download semantics for the same target name and URL"
            )
        self._reconcile_download_metadata(existing, candidate)
        return existing

    def ancestor(self, kind: NodeKind) -> Node | None:
        """Return this node or its nearest ancestor with the structural kind."""
        current: Node | None = self
        while current is not None:
            if current.type == kind:
                return current
            current = current.parent
        return None

    def clone(self, parent: Node | None = None) -> Node:
        clone = Node(
            self.name,
            self.id,
            self.type,
            parent,
            url=self.url,
            download_headers=self.download_headers,
            timemodified=self.timemodified,
            etag=self.etag,
            etag_kind=self.etag_kind,
            content_hash=self._legacy_content_hash,
            artifact=self.artifact,
            artifact_hashes=self.artifact_hashes,
            remote_size=self.remote_size,
            name_clash_id=self.name_clash_id,
            download_status=self.download_status,
            download_kind=self.download_kind,
        )
        clone.children = [child.clone(clone) for child in self.children]
        clone._conflicting_download_metadata = set(self._conflicting_download_metadata)
        return clone

    def get_path(self) -> list[str]:
        ret: list[str] = []
        cur: Node | None = self
        while cur is not None:
            ret.insert(0, cur.name)
            cur = cur.parent
        return ret


def match_equivalent_child(parent: Node | None, child: Node) -> Node | None:
    """Find the structurally equivalent child below ``parent``, if any."""
    if parent is None:
        return None
    candidates = [
        candidate
        for candidate in parent.children
        if candidate.name == child.name and candidate.type == child.type
    ]
    if not candidates:
        return None

    for attr in ("url", "name_clash_id", "id"):
        child_value = getattr(child, attr)
        if child_value is None:
            continue
        for candidate in candidates:
            if getattr(candidate, attr) == child_value:
                return candidate
    return candidates[0]
