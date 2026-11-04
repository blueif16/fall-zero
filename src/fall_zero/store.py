"""Where uploads, their reports and saved chats are kept. Locally: files under out/. Deployed on Vercel, whose
disk is read-only and not shared between instances: a private Vercel Blob store, with /tmp as this instance's
working copy. The store is in use once Vercel has connected one to the project (it sets BLOB_STORE_ID or
BLOB_READ_WRITE_TOKEN). Names are paths like "web/<run>/report.json" and "threads/<id>.json"."""

import os
from pathlib import Path

from vercel.blob import sync as blob

ROOT = Path(__file__).resolve().parents[2]
REMOTE = bool(os.environ.get("BLOB_STORE_ID") or os.environ.get("BLOB_READ_WRITE_TOKEN"))
LOCAL = Path("/tmp/fall-zero") if REMOTE else ROOT / "out"  # the pipeline writes here; locally it is the store


def keep(*names: str) -> None:
    """Copy files the pipeline wrote under LOCAL into the store (locally they're in it already)."""
    for name in names if REMOTE else ():
        blob.put_blob(name, (LOCAL / name).read_bytes(), access="private", allow_overwrite=True)


def local(name: str) -> Path | None:
    """A file written once (an upload, its still, its report) on this machine, fetched from the store if this
    instance hasn't got it yet; None if there's no such file."""
    path = LOCAL / name
    if REMOTE and not path.exists():
        try:
            body = blob.get_blob(name, access="private").body
        except blob.BlobNotFoundError:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return path if path.exists() else None


def read(name: str) -> bytes | None:
    """A file that changes (a saved chat): always the store's copy, never one this instance kept."""
    if not REMOTE:
        path = LOCAL / name
        return path.read_bytes() if path.exists() else None
    try:
        return blob.get_blob(name, access="private").body
    except blob.BlobNotFoundError:
        return None


def write(name: str, body: bytes) -> None:
    if REMOTE:  # a saved chat changes with every tap: cached copies go stale within a minute
        blob.put_blob(name, body, access="private", allow_overwrite=True, cache_control_max_age=60)
        return
    path = LOCAL / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def names(folder: str) -> list[str]:
    """The files directly in `folder` (a name ending in /)."""
    if REMOTE:
        return [b.pathname for b in blob.query_blobs(prefix=folder) if "/" not in b.pathname[len(folder) :]]
    path = LOCAL / folder
    return [folder + f.name for f in path.iterdir() if f.is_file()] if path.is_dir() else []


def delete(name: str) -> None:
    if REMOTE:
        blob.delete_blob(name)
    else:
        (LOCAL / name).unlink(missing_ok=True)
