"""Brotli precompression helpers.

Kept deliberately import-light (only the stdlib + the optional ``brotli``
module) so it can run at Docker *build* time — before the database, static
directory, or the heavier ``builder`` import chain exist — as well as at
runtime from ``builder._write_json``.

Every helper is best-effort: if ``brotli`` isn't installed the functions become
no-ops, so the app still works (responses just fall back to gzip-on-the-fly).
"""
from pathlib import Path

# Text-ish assets worth precompressing. Already-compressed formats (png, jpg,
# woff2, gz, br) gain nothing from a second pass and are skipped.
_BR_EXTS = {
    ".js", ".mjs", ".css", ".html", ".json", ".svg", ".map",
    ".txt", ".xml", ".ico", ".webmanifest",
}
# Below this size the Brotli framing overhead and the extra request bookkeeping
# outweigh the savings; serve such files uncompressed.
_BR_MIN_BYTES = 1024
_BR_QUALITY = 11  # max ratio; we compress offline so the CPU cost is one-time


def write_br(path: Path, payload: bytes) -> None:
    """Atomically write ``<path>.br`` next to ``path``.

    Atomic (tmp + replace) so a concurrent reader never sees a partial ``.br``.
    No-op when ``brotli`` is unavailable.
    """
    try:
        import brotli
    except ImportError:
        return
    br = path.with_name(path.name + ".br")
    tmp = br.with_name(br.name + ".tmp")
    tmp.write_bytes(brotli.compress(payload, quality=_BR_QUALITY))
    tmp.replace(br)


def precompress_dir(root) -> int:
    """Walk ``root`` and write a ``.br`` sibling for each compressible file.

    Used at image-build time for the immutable SPA bundle. Returns the number of
    files compressed (0 when ``brotli`` is unavailable).
    """
    try:
        import brotli  # noqa: F401  (presence check; write_br re-imports)
    except ImportError:
        return 0
    root = Path(root)
    count = 0
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix == ".br":
            continue
        if p.suffix.lower() not in _BR_EXTS:
            continue
        data = p.read_bytes()
        if len(data) < _BR_MIN_BYTES:
            continue
        write_br(p, data)
        count += 1
    return count
