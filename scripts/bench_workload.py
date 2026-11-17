"""Reproducible single-thread workload for measuring player impact."""
from __future__ import annotations

import argparse
import hashlib
import json
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=20.0)
    args = parser.parse_args()

    buffer = bytes(range(256)) * 4096  # 1 MiB
    digest = hashlib.sha256()
    iterations = 0
    checksum = 0
    started = time.perf_counter()
    deadline = started + max(1.0, args.seconds)
    while time.perf_counter() < deadline:
        digest.update(buffer)
        block = digest.digest()
        value = 0
        for byte in block:
            value = (value * 31 + byte) & 0xFFFFFFFF
        checksum ^= value
        iterations += 1
    elapsed = time.perf_counter() - started
    print(json.dumps({
        "seconds": round(elapsed, 3),
        "iterations": iterations,
        "iterations_per_second": round(iterations / elapsed, 1),
        "checksum": checksum,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
