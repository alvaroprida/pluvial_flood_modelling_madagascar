"""Shared I/O: HTTP session, cached downloads, remote ZIP access and raster helpers.

Everything that writes to the shared cache goes through ``file_lock`` and a ``.part`` file, so
several basins processed in parallel can ask for the same file without corrupting it: the first
worker downloads, the others wait on the lock and then find the file in place.
"""

from __future__ import annotations

import fcntl
import hashlib
import io
import logging
import math
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Sequence, Tuple

import numpy as np
import rasterio
import requests
from rasterio.enums import Resampling
from rasterio.windows import Window, from_bounds
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

Bounds = Tuple[float, float, float, float]          # (west, south, east, north)

_SESSION: Optional[requests.Session] = None
_TIMEOUT = 180


# ------------------------------------------------------------------------- HTTP
def configure_http(user_agent: str = "mdg-pluvial/0.1", timeout_s: int = 180,
                   max_retries: int = 5) -> requests.Session:
    """Create the process-wide session: one user agent, retries with exponential backoff."""
    global _SESSION, _TIMEOUT
    retry = Retry(total=max_retries, backoff_factor=2,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET", "HEAD"), raise_on_status=False)
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    _SESSION, _TIMEOUT = session, timeout_s
    return session


def session() -> requests.Session:
    return _SESSION or configure_http()


def timeout() -> int:
    return _TIMEOUT


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Exclusive inter-process lock tied to *path* (POSIX only: macOS, Linux)."""
    lock_path = Path(path).with_name(Path(path).name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def http_download(url: str, dest: Path, *, overwrite: bool = False, chunk_mb: int = 8) -> Path:
    """Stream *url* to *dest* via a ``.part`` file, under a lock. Skips if *dest* exists."""
    dest = Path(dest)
    with file_lock(dest):
        if dest.exists() and not overwrite:
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")
        log.info("downloading %s", dest.name)
        with session().get(url, stream=True, timeout=timeout()) as resp:
            resp.raise_for_status()
            with open(part, "wb") as fh:
                for block in resp.iter_content(chunk_size=chunk_mb << 20):
                    fh.write(block)
        part.replace(dest)
        log.info("downloaded %s (%s)", dest.name, human(dest.stat().st_size))
    return dest


class HTTPRangeFile(io.RawIOBase):
    """Seekable read-only file over HTTP byte ranges.

    Wrap in ``io.BufferedReader`` and hand to ``zipfile.ZipFile`` to list and extract
    individual members of a remote archive without downloading the whole thing.
    """

    def __init__(self, url: str):
        self.session = session()
        head = self.session.head(url, allow_redirects=True, timeout=timeout())
        head.raise_for_status()
        self.url = head.url                       # follow redirects once, then reuse
        self.size = int(head.headers["Content-Length"])
        if head.headers.get("Accept-Ranges") != "bytes":
            raise RuntimeError(f"server does not advertise byte ranges: {url}")
        self._pos = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        self._pos = {io.SEEK_SET: offset,
                     io.SEEK_CUR: self._pos + offset,
                     io.SEEK_END: self.size + offset}[whence]
        return self._pos

    def readinto(self, buf) -> int:
        data = self.read(len(buf))
        buf[: len(data)] = data
        return len(data)

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self._pos
        if n == 0 or self._pos >= self.size:
            return b""
        end = min(self._pos + n, self.size) - 1
        resp = self.session.get(self.url, headers={"Range": f"bytes={self._pos}-{end}"},
                                timeout=timeout())
        resp.raise_for_status()
        data = resp.content
        self._pos += len(data)
        return data


def remote_zip(url: str, buffer_mb: int = 4) -> zipfile.ZipFile:
    """Open a remote ZIP for member-level access (central directory + ranged member reads)."""
    return zipfile.ZipFile(io.BufferedReader(HTTPRangeFile(url), buffer_size=buffer_mb << 20))


# ---------------------------------------------------------------------- utility
def sha256(path: Path, chunk: int = 8 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def human(n_bytes: float) -> str:
    """Decimal file size (1 MB = 1e6 B), to match how the data portals quote sizes."""
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if abs(n_bytes) < 1000 or unit == "TB":
            return f"{n_bytes:,.1f} {unit}"
        n_bytes /= 1000


# ---------------------------------------------------------------------- rasters
COG_PROFILE = dict(driver="GTiff", tiled=True, blockxsize=256, blockysize=256,
                   compress="deflate", predictor=2, BIGTIFF="IF_SAFER")


def write_raster(path: Path, array: np.ndarray, transform, *, crs="EPSG:4326",
                 nodata=None, dtype=None, descriptions: Optional[Sequence[str]] = None) -> Path:
    """Write a 2-D or 3-D array as a tiled, deflate-compressed GeoTIFF with overviews."""
    array = np.asarray(array)
    if array.ndim == 2:
        array = array[None, :, :]
    dtype = dtype or array.dtype
    if np.dtype(dtype) == np.float64:                 # float32 is plenty for every layer here
        dtype = "float32"
    profile = dict(COG_PROFILE, height=array.shape[1], width=array.shape[2],
                   count=array.shape[0], dtype=dtype, crs=crs, transform=transform)
    if min(array.shape[1:]) < 256:                    # GeoTIFF tiles must fit the raster
        profile.pop("tiled"), profile.pop("blockxsize"), profile.pop("blockysize")
    if nodata is not None:
        profile["nodata"] = nodata
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array.astype(dtype))
        if descriptions:
            for i, name in enumerate(descriptions, start=1):
                dst.set_band_description(i, name)
        factors = [f for f in (2, 4, 8, 16, 32) if min(array.shape[1:]) // f >= 64]
        if factors:
            dst.build_overviews(factors, Resampling.nearest)
            dst.update_tags(ns="rio_overview", resampling="nearest")
    return path


def clip_raster(src_uri: str, bounds: Bounds, band: int = 1) -> Tuple[np.ndarray, object, dict]:
    """Windowed read of *src_uri* (local path, URL or /vsicurl/...) over *bounds*.

    Returns (array, transform, source metadata). The window is snapped outwards to whole
    source pixels, so no resampling happens - the output stays on the source grid.
    The floor/ceil arithmetic is done by hand rather than with ``Window.round_*``, whose
    rounding mode has changed across rasterio versions.
    """
    with rasterio.open(src_uri) as src:
        w = from_bounds(*bounds, transform=src.transform)
        col_off, row_off = math.floor(w.col_off), math.floor(w.row_off)
        window = Window(col_off, row_off,
                        math.ceil(w.width + (w.col_off - col_off)),
                        math.ceil(w.height + (w.row_off - row_off)))
        window = window.intersection(Window(0, 0, src.width, src.height))
        array = src.read(band, window=window)
        transform = src.window_transform(window)
        meta = dict(crs=src.crs, nodata=src.nodata, dtype=src.dtypes[band - 1], res=src.res)
    return array, transform, meta
