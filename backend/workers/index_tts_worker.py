# -*- coding: utf-8 -*-
"""由外部 Python 3.10 执行的 IndexTTS worker。"""

import argparse
import importlib
import json
import sys
from pathlib import Path


def emit(payload, exit_code=0):
    print(json.dumps(payload, ensure_ascii=False), flush=True)
    raise SystemExit(exit_code)


def get_device():
    """NVIDIA CUDA 可用时使用 GPU；AMD Windows 与无 CUDA 环境使用 CPU。"""
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def inference_options(device):
    return {
        "is_fp16": device == "cuda",
        "use_cuda_kernel": device == "cuda",
    }


def load_index_tts(model_dir, device):
    source_dir = Path(model_dir)
    if not (source_dir / "indextts").is_dir():
        raise RuntimeError("未找到 models/index-tts 官方源码")
    sys.path.insert(0, str(source_dir))

    module = None
    index_tts_class = None
    for module_name, class_name in (
        ("indextts.infer_v2", "IndexTTS2"),
        ("indextts.infer", "IndexTTS"),
    ):
        try:
            candidate = importlib.import_module(module_name)
            candidate_class = getattr(candidate, class_name, None)
            if candidate_class is not None:
                module = candidate
                index_tts_class = candidate_class
                break
        except ModuleNotFoundError:
            continue
    if index_tts_class is None:
        raise RuntimeError("官方源码中未找到 IndexTTS 推理类")

    config_path = source_dir / "checkpoints" / "config.yaml"
    if not config_path.is_file():
        config_path = source_dir / "config.yaml"
    if not config_path.is_file():
        raise RuntimeError("未找到 IndexTTS 模型配置；请按官方说明放置 checkpoints")

    checkpoint_dir = str(source_dir / "checkpoints")
    fp16 = device == "cuda"
    if index_tts_class.__name__ == "IndexTTS2":
        return index_tts_class(
            cfg_path=str(config_path),
            model_dir=checkpoint_dir,
            device=device,
            use_fp16=fp16,
            use_cuda_kernel=fp16,
            use_deepspeed=False,
        )

    options = inference_options(device)
    try:
        return index_tts_class(
            cfg_path=str(config_path),
            model_dir=checkpoint_dir,
            device=device,
            **options,
        )
    except TypeError:
        return index_tts_class(
            str(config_path),
            checkpoint_dir,
            device=device,
        )


def run(request_path):
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    text = request["text"]
    reference_audio = request["reference_audio"]
    output_path = Path(request["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)

    device = get_device()
    model = load_index_tts(request["model_dir"], device)
    inference = getattr(model, "infer", None) or getattr(model, "inference", None)
    if inference is None:
        raise RuntimeError("当前官方 IndexTTS 源码未提供 infer/inference 接口")

    try:
        inference(reference_audio, text, output_path=str(output_path))
    except TypeError:
        inference(spk_audio_prompt=reference_audio, text=text, output_path=str(output_path))

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("IndexTTS 未输出有效音频")
    return {
        "ok": True,
        "device_used": device,
        "directml_supported": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    try:
        emit(run(args.request))
    except Exception:
        emit({"ok": False, "error": "IndexTTS worker 执行失败"}, 1)


if __name__ == "__main__":
    main()
