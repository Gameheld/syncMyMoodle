"""Stable identities and complete local state for downloaded artifacts."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from syncmymoodle import links, pathing
from syncmymoodle.http_utils import canonical_remote_url
from syncmymoodle.node import DownloadArtifact, DownloadKind, Node

if TYPE_CHECKING:
    from syncmymoodle.context import SyncContext


def remote_content_identity(node: Node) -> tuple[str, str] | None:
    """Return a stable comparison key and a safe user-visible identity."""
    if not node.url:
        return None
    youtube_id = links.youtube_video_id_from_node(node)
    if youtube_id is not None:
        identity = f"youtube:{youtube_id}"
        return identity, identity
    identity_url, display_url = canonical_remote_url(node.url)
    if node.download_kind is DownloadKind.OPENCAST:
        identity = f"opencast:{node.id}:{identity_url.partition('?')[0]}"
        return identity, identity
    if node.download_kind in {DownloadKind.EMEDIA, DownloadKind.QUIZ} and node.id:
        identity = f"{node.download_kind}:{node.id}"
        return identity, identity
    return f"{node.download_kind}:{identity_url}", display_url


def _without_windows_extended_prefix(path: Path) -> Path:
    value = os.fspath(path)
    if value.startswith("\\\\?\\UNC\\"):
        return Path("\\\\" + value[8:])
    if value.startswith("\\\\?\\"):
        return Path(value[4:])
    return path


def relative_artifact_path(ctx: SyncContext, path: Path) -> str:
    """Encode an artifact path portably beneath the configured sync root."""
    root = ctx.internal_path_root.root
    candidate = pathing.absolute_path(_without_windows_extended_prefix(path)).resolve(
        strict=False
    )
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(
            f"artifact path is outside the sync directory: {path}"
        ) from error
    if not relative.parts:
        raise ValueError("artifact path cannot be the sync directory")
    return PurePosixPath(*relative.parts).as_posix()


def resolve_artifact_path(
    ctx: SyncContext,
    artifact: DownloadArtifact,
) -> Path | None:
    """Resolve a cached portable path without allowing it to escape the root."""
    relative = PurePosixPath(artifact.path)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    candidate = ctx.internal_path_root.root.joinpath(*relative.parts)
    try:
        if not candidate.resolve(strict=False).is_relative_to(
            ctx.internal_path_root.root
        ):
            return None
    except OSError:
        return None
    return pathing.with_windows_extended_length_prefix(candidate)


def download_artifact(
    ctx: SyncContext,
    node: Node,
    path: Path,
    content_hash: str,
    size: int,
) -> DownloadArtifact:
    identity = remote_content_identity(node)
    if identity is None:
        raise ValueError("downloaded artifact requires a remote identity")
    return DownloadArtifact(
        relative_artifact_path(ctx, path),
        content_hash,
        size,
        identity[0],
    )
