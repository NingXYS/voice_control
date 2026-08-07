#!/usr/bin/env python3
"""Export the official 3D-Speaker ERes2NetV2 checkpoint to ONNX.

Run this in a disposable export environment containing torch, onnx and
onnxruntime.  The online voice environment intentionally does not need torch.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--speakerlab-root", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (args.speakerlab_root / "speakerlab").is_dir():
        raise SystemExit("--speakerlab-root does not contain speakerlab")
    if not args.checkpoint.is_file():
        raise SystemExit("checkpoint does not exist")

    sys.path.insert(0, str(args.speakerlab_root))
    import numpy as np
    import onnx
    import onnxruntime as ort
    import torch
    from speakerlab.models.eres2net.ERes2NetV2 import ERes2NetV2

    model = ERes2NetV2(feat_dim=80, embedding_size=192)
    state = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    model.eval()

    # Match 3D-Speaker's official export shape/names while keeping utterance
    # length dynamic.  A fixed seed makes the parity check reproducible.
    torch.manual_seed(20260806)
    feature = torch.randn(1, 345, 80)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{args.output.name}.", suffix=".tmp", dir=args.output.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        torch.onnx.export(
            model,
            feature,
            temporary,
            export_params=True,
            opset_version=11,
            do_constant_folding=True,
            input_names=["x"],
            output_names=["embedding"],
            dynamo=False,
            dynamic_axes={
                "x": {0: "batch_size", 1: "frame_num"},
                "embedding": {0: "batch_size"},
            },
        )
        artifact = onnx.load(str(temporary))
        metadata = {
            "framework": "3d-speaker",
            "language": "Chinese",
            "url": "https://www.modelscope.cn/models/iic/speech_eres2netv2_sv_zh-cn_16k-common/summary",
            "comment": "Exported from the official iic/speech_eres2netv2_sv_zh-cn_16k-common checkpoint",
            "sample_rate": "16000",
            "output_dim": "192",
            "normalize_samples": "1",
            "feature_normalize_type": "global-mean",
        }
        del artifact.metadata_props[:]
        for key, value in metadata.items():
            item = artifact.metadata_props.add()
            item.key = key
            item.value = value
        onnx.checker.check_model(artifact)
        onnx.save(artifact, str(temporary))

        with torch.inference_mode():
            expected = model(feature).detach().cpu().numpy()
        session = ort.InferenceSession(str(temporary), providers=["CPUExecutionProvider"])
        actual = session.run(None, {"x": feature.numpy()})[0]
        cosine = float(
            np.dot(expected.reshape(-1), actual.reshape(-1))
            / (np.linalg.norm(expected) * np.linalg.norm(actual))
        )
        max_error = float(np.max(np.abs(expected - actual)))
        if cosine < 0.9999:
            raise RuntimeError(f"ONNX parity check failed: cosine={cosine:.8f}")
        os.chmod(temporary, 0o644)
        os.replace(temporary, args.output)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    print(f"exported={args.output}")
    print(f"embedding_dim={actual.shape[-1]}")
    print(f"pytorch_onnx_cosine={cosine:.8f}")
    print(f"max_abs_error={max_error:.8g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
