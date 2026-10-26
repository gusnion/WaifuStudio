#!/usr/bin/env python3
"""
Fast multi-part Wan 2.2 model downloader using Python standard library.
Downloads models from manifest using parallel HTTP Range requests.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

NUM_THREADS = 12
CHUNK_SIZE = 8 * 1024 * 1024  # ~8 MB per chunk
BUFFER_SIZE = 64 * 1024
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WaifuDownloader/1.0"
SOCKET_TIMEOUT = int(os.environ.get("WAN_DOWNLOAD_TIMEOUT", "45"))
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds


def compute_sha256(filepath: str, expected_size: int | None = None) -> str:
    """Computes SHA256 in 1MB chunks."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().lower()


def clean_temp_files(part_pattern: str, part_file: str) -> None:
    """Cleans up .part and .partN temporary files."""
    for p in glob.glob(part_pattern):
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass
    if os.path.exists(part_file):
        try:
            os.remove(part_file)
        except OSError:
            pass


class ProgressTracker:
    def __init__(self, model_id: str, total_bytes: int):
        self.model_id = model_id
        self.total_bytes = total_bytes
        self.downloaded_bytes = 0
        self.lock = Lock()
        self.last_print_time = 0.0

    def add_bytes(self, n: int) -> None:
        with self.lock:
            self.downloaded_bytes += n
            now = time.time()
            if now - self.last_print_time >= 0.5 or self.downloaded_bytes >= self.total_bytes:
                self.last_print_time = now
                self._print_progress()

    def set_initial_bytes(self, n: int) -> None:
        with self.lock:
            self.downloaded_bytes = n

    def _print_progress(self) -> None:
        curr_mb = self.downloaded_bytes / (1024 * 1024)
        total_mb = self.total_bytes / (1024 * 1024)
        pct = (self.downloaded_bytes / self.total_bytes * 100) if self.total_bytes > 0 else 100.0
        sys.stdout.write(f"\r[{self.model_id}] {curr_mb:8.1f} / {total_mb:8.1f} MB ({pct:5.1f}%)")
        sys.stdout.flush()

    def finish(self) -> None:
        self._print_progress()
        sys.stdout.write("\n")
        sys.stdout.flush()


def download_chunk(
    url: str,
    start_byte: int,
    end_byte: int,
    chunk_path: str,
    tracker: ProgressTracker,
) -> None:
    expected_chunk_size = end_byte - start_byte + 1
    last_err: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        existing_size = os.path.getsize(chunk_path) if os.path.exists(chunk_path) else 0

        if existing_size > expected_chunk_size:
            try:
                os.remove(chunk_path)
            except OSError:
                pass
            existing_size = 0
        elif existing_size == expected_chunk_size:
            return

        req_start = start_byte + existing_size
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Range": f"bytes={req_start}-{end_byte}",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=SOCKET_TIMEOUT) as resp:
                status = getattr(resp, "status", 200)
                if status == 206:
                    mode = "ab" if existing_size > 0 else "wb"
                    with open(chunk_path, mode) as f:
                        while True:
                            buf = resp.read(BUFFER_SIZE)
                            if not buf:
                                break
                            f.write(buf)
                            tracker.add_bytes(len(buf))
                    return
                elif status == 200:
                    # Server ignored Range; overwrite from beginning
                    if existing_size > 0:
                        tracker.add_bytes(-existing_size)
                    with open(chunk_path, "wb") as f:
                        while True:
                            buf = resp.read(BUFFER_SIZE)
                            if not buf:
                                break
                            f.write(buf)
                            tracker.add_bytes(len(buf))
                    return
                else:
                    raise RuntimeError(f"Unexpected HTTP status {status} downloading chunk {chunk_path}")
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                backoff_time = INITIAL_BACKOFF * (2 ** (attempt - 1))
                time.sleep(backoff_time)
            else:
                raise RuntimeError(
                    f"Failed chunk {start_byte}-{end_byte} after {MAX_RETRIES} attempts: {last_err}"
                ) from last_err


def download_single_stream(url: str, total_bytes: int, target_path: str, tracker: ProgressTracker) -> None:
    """Fallback if range requests fail entirely or for whole-file download."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=SOCKET_TIMEOUT) as resp:
        with open(target_path, "wb") as f:
            while True:
                buf = resp.read(BUFFER_SIZE)
                if not buf:
                    break
                f.write(buf)
                tracker.add_bytes(len(buf))


def process_model(model: dict, repo_root: str) -> None:
    model_id = model.get("id", "unknown")
    filename = model["filename"]
    subdir = model.get("subdir", "")
    expected_bytes = int(model["bytes"])
    expected_sha256 = model["sha256"].strip().lower()
    url = model["url"]

    dest_dir = os.path.join(repo_root, "ComfyUI", "models", subdir)
    os.makedirs(dest_dir, exist_ok=True)

    final_path = os.path.join(dest_dir, filename)
    part_file = os.path.join(dest_dir, f"{filename}.part")
    part_pattern = os.path.join(dest_dir, f"{filename}.part*")

    # 1. Skip if final file already exists with identical size and sha256
    if os.path.isfile(final_path):
        if os.path.getsize(final_path) == expected_bytes:
            print(f"[{model_id}] Checking existing file SHA256...")
            if compute_sha256(final_path) == expected_sha256:
                print(f"[{model_id}] OK - Already complete and verified ({final_path}). Skipping.")
                return
            else:
                print(f"[{model_id}] Existing file corrupt/mismatched. Redownloading.")
                try:
                    os.remove(final_path)
                except OSError:
                    pass

    # 2. Divide into ~8 MB chunks
    chunks: list[tuple[int, int, int, str]] = []  # (index, start, end, chunk_path)
    offset = 0
    idx = 0
    while offset < expected_bytes:
        chunk_end = min(offset + CHUNK_SIZE - 1, expected_bytes - 1)
        chunk_path = os.path.join(dest_dir, f"{filename}.part{idx}")
        chunks.append((idx, offset, chunk_end, chunk_path))
        offset = chunk_end + 1
        idx += 1

    tracker = ProgressTracker(model_id, expected_bytes)

    # Calculate already existing bytes in valid .partN files
    initial_downloaded = 0
    for _, start_b, end_b, cp in chunks:
        expected_len = end_b - start_b + 1
        if os.path.isfile(cp):
            size = os.path.getsize(cp)
            if size <= expected_len:
                initial_downloaded += size
            else:
                try:
                    os.remove(cp)
                except OSError:
                    pass
    tracker.set_initial_bytes(initial_downloaded)

    print(f"[{model_id}] Starting download: {filename} ({expected_bytes / (1024*1024):.1f} MB) in {len(chunks)} chunks using {NUM_THREADS} threads")

    # 3. Parallel download with ThreadPoolExecutor
    try:
        with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            futures = {
                executor.submit(download_chunk, url, start, end, c_path, tracker): (start, end, c_path)
                for _, start, end, c_path in chunks
            }
            for fut in as_completed(futures):
                fut.result()
        tracker.finish()
    except Exception as e:
        tracker.finish()
        print(f"[{model_id}] ERROR during chunk downloads (preserving .partN for resume): {e}", file=sys.stderr)
        raise

    # 4. Concatenate chunks in order to <filename>.part
    print(f"[{model_id}] Assembling parts into {filename}.part...")
    try:
        with open(part_file, "wb") as outfile:
            for _, _, _, c_path in chunks:
                if not os.path.isfile(c_path):
                    raise RuntimeError(f"Missing chunk file: {c_path}")
                with open(c_path, "rb") as infile:
                    while True:
                        buf = infile.read(1024 * 1024)
                        if not buf:
                            break
                        outfile.write(buf)
    except Exception as e:
        print(f"[{model_id}] ERROR assembling chunks: {e}", file=sys.stderr)
        clean_temp_files(part_pattern, part_file)
        raise

    # 5. Verify assembled file size and SHA256
    assembled_size = os.path.getsize(part_file)
    if assembled_size != expected_bytes:
        clean_temp_files(part_pattern, part_file)
        raise RuntimeError(
            f"Size mismatch for {filename}: expected {expected_bytes} bytes, got {assembled_size} bytes"
        )

    print(f"[{model_id}] Verifying SHA256 checksum...")
    assembled_hash = compute_sha256(part_file)
    if assembled_hash != expected_sha256:
        clean_temp_files(part_pattern, part_file)
        raise RuntimeError(
            f"SHA256 mismatch for {filename}: expected {expected_sha256}, got {assembled_hash}"
        )

    # 6. Atomic replace to final filename and cleanup chunk parts
    if os.path.exists(final_path):
        try:
            os.remove(final_path)
        except OSError:
            pass
    os.replace(part_file, final_path)

    # Remove .partN chunk files now that final file is verified and placed
    for _, _, _, c_path in chunks:
        try:
            if os.path.exists(c_path):
                os.remove(c_path)
        except OSError:
            pass

    print(f"[{model_id}] OK - Successfully downloaded and verified: {final_path}")


def main() -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, ".."))
    manifest_path = os.path.join(repo_root, "install", "manifest", "manifest.wan.json")

    if not os.path.isfile(manifest_path):
        print(f"ERROR: Manifest file not found at {manifest_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"ERROR: Failed to read manifest JSON: {e}", file=sys.stderr)
        sys.exit(1)

    models = data.get("models", [])
    if not models:
        print("WARNING: No models found in manifest.")
        return

    print(f"Found {len(models)} models in {os.path.relpath(manifest_path, repo_root)}")
    failed_models: list[str] = []

    for model in models:
        model_id = model.get("id", "unknown")
        try:
            process_model(model, repo_root)
        except Exception as e:
            print(f"[{model_id}] FAILED model download: {e}. Skipping to next model.", file=sys.stderr)
            failed_models.append(model_id)

    if failed_models:
        print(
            f"\nERROR: The following {len(failed_models)} model(s) failed or remained incomplete: {', '.join(failed_models)}",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\nAll manifest models downloaded and verified successfully.")


if __name__ == "__main__":
    main()