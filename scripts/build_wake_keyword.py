#!/usr/bin/env python3
"""Generate and verify sherpa-onnx KWS keyword tokens with the official tokenizer."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

_METADATA_PREFIXES = (":", "#", "@")


def keyword_tokens(line: str) -> list[str]:
    """Return model tokens only, excluding KWS metadata fields."""
    return [
        token
        for token in line.strip().split()
        if token and not token.startswith(_METADATA_PREFIXES)
    ]


def _find_cli(explicit: str | None) -> str:
    if explicit:
        return explicit
    for name in ("sherpa-onnx-cli", "sherpa_onnx_cli"):
        path = shutil.which(name)
        if path:
            return path
    raise SystemExit(
        "sherpa-onnx text2token CLI not found; install the CLI or pass --cli PATH"
    )


def generate_keyword_line(
    tokens_path: Path,
    phrase: str,
    tokens_type: str,
    cli: str | None = None,
    bpe_model: Path | None = None,
) -> str:
    """Tokenize one wake phrase using sherpa-onnx's official text2token command."""
    executable = _find_cli(cli)
    with tempfile.TemporaryDirectory(prefix="voice-kws-token-") as tmp:
        input_path = Path(tmp) / "keywords_raw.txt"
        output_path = Path(tmp) / "keywords_tokenized.txt"
        input_path.write_text(f"{phrase} @{phrase}\n", encoding="utf-8")
        cmd = [
            executable,
            "text2token",
            str(input_path),
            str(output_path),
            "--tokens",
            str(tokens_path),
            "--tokens-type",
            tokens_type,
        ]
        if bpe_model is not None:
            cmd += ["--bpe-model", str(bpe_model)]
        try:
            subprocess.run(cmd, check=True, text=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise SystemExit(f"text2token failed: {detail}") from exc
        lines = [line.strip() for line in output_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(lines) != 1:
            raise SystemExit(f"expected one tokenized keyword line, got {len(lines)}")
        return lines[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate/verify a wake keyword with sherpa-onnx text2token."
    )
    parser.add_argument("tokens", help="Path to the KWS model tokens.txt")
    parser.add_argument("--phrase", default="小西小西")
    parser.add_argument(
        "--tokens-type",
        default="cjkchar",
        choices=("cjkchar", "bpe", "cjkchar+bpe", "fpinyin", "ppinyin", "phone+ppinyin"),
    )
    parser.add_argument("--bpe-model", help="Required for bpe/cjkchar+bpe models")
    parser.add_argument("--keywords", help="Existing keywords.txt to compare against")
    parser.add_argument("--write", help="Write the generated keyword line to this file")
    parser.add_argument("--cli", help="Path to sherpa-onnx-cli")
    args = parser.parse_args()

    tokens_path = Path(args.tokens)
    if not tokens_path.is_file():
        raise SystemExit(f"tokens file not found: {tokens_path}")
    bpe_model = Path(args.bpe_model) if args.bpe_model else None
    if bpe_model is not None and not bpe_model.is_file():
        raise SystemExit(f"BPE model not found: {bpe_model}")

    generated = generate_keyword_line(
        tokens_path=tokens_path,
        phrase=args.phrase,
        tokens_type=args.tokens_type,
        cli=args.cli,
        bpe_model=bpe_model,
    )
    print(f"generated: {generated}")

    if args.keywords:
        keywords_path = Path(args.keywords)
        if not keywords_path.is_file():
            raise SystemExit(f"keywords file not found: {keywords_path}")
        existing_lines = [
            line.strip()
            for line in keywords_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("# ")
        ]
        if not existing_lines:
            raise SystemExit(f"keywords file is empty: {keywords_path}")
        generated_tokens = keyword_tokens(generated)
        matches = [line for line in existing_lines if keyword_tokens(line) == generated_tokens]
        if not matches:
            print("existing keyword tokenization does NOT match official text2token output")
            print("existing lines:")
            for line in existing_lines:
                print(f"  {line}")
            raise SystemExit(2)
        print(f"verified: token sequence matches {keywords_path}")

    if args.write:
        output = Path(args.write)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(generated + "\n", encoding="utf-8")
        print(f"written: {output}")


if __name__ == "__main__":
    main()
