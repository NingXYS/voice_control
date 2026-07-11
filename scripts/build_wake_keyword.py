#!/usr/bin/env python3
"""Validate that a wake phrase can be represented by a KWS tokens file."""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("tokens")
    parser.add_argument("--phrase", default="小西小西")
    args = parser.parse_args()
    tokens = set()
    for line in Path(args.tokens).read_text(encoding="utf-8").splitlines():
        if line.strip():
            tokens.add(line.split()[0])
    units = list(args.phrase.replace(" ", ""))
    missing = [unit for unit in units if unit not in tokens]
    if missing:
        raise SystemExit("tokens missing: " + " ".join(sorted(set(missing))))
    print(" ".join(units))


if __name__ == "__main__":
    main()
