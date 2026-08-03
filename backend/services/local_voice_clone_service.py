# -*- coding: utf-8 -*-
"""IndexTTS2 本地声音复刻子进程服务。"""

import json
import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from backend.config.paths import PROJECT_ROOT
from backend.services.hardware_capability_service import hardware_capability_service

logger = logging.getLogger(__name__)


class LocalVoiceCloneError(RuntimeError):
    """本地声音复刻不可执行时抛出。"""


class LocalVoiceCloneService:
    ENGINE_NAME = "IndexTTS2"
    AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg"}

    def __init__(self):
        self.project_root = PROJECT_ROOT.resolve()
        self.uploads_dir = (self.project_root / "uploads").resolve()
        self.model_dir = (self.project_root / "models" / "index-tts").resolve()
        self.worker_path = (self.project_root / "backend" / "workers" / "index_tts_worker.py").resolve()
        self.processing_dir = self.project_root / "temp" / "processing" / "index_tts"
        self.output_dir = self.project_root / "temp" / "outputs" / "local_voice_clone"

    def _python_command(self):
        configured = os.environ.get("INDEXTTS_PYTHON", "").strip()
        candidates = []
        if configured:
            candidate = Path(configured)
            if not candidate.is_file():
                return None, "INDEXTTS_PYTHON 不存在或不是解释器文件"
            candidates.append(([str(candidate)], str(candidate)))
        else:
            candidates.extend([
                (["py", "-3.10"], "py -3.10"),
                (["python3.10"], "python3.10"),
            ])

        for command, label in candidates:
            try:
                result = subprocess.run(
                    command + ["-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if result.returncode == 0 and result.stdout.strip() == "3.10":
                    return command, label
            except (OSError, subprocess.TimeoutExpired):
                continue
        return None, "未找到可用的外部 Python 3.10；可通过 INDEXTTS_PYTHON 指定"

    @staticmethod
    def _ffmpeg_available():
        return shutil.which("ffmpeg") is not None

    @staticmethod
    def _runtime_available(python_command):
        if not python_command:
            return False
        try:
            result = subprocess.run(
                python_command + [
                    "-c",
                    "import torch, torchaudio, transformers, modelscope, omegaconf, "
                    "einops, librosa, safetensors, sentencepiece",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _model_checks(self):
        checkpoint_dir = self.model_dir / "checkpoints"
        required = (
            "config.yaml",
            "gpt.pth",
            "s2mel.pth",
            "bpe.model",
            "feat1.pt",
            "feat2.pt",
            "wav2vec2bert_stats.pt",
            "qwen0.6bemo4-merge",
        )
        auxiliary_files = (
            "w2v-bert-2.0/config.json",
            "w2v-bert-2.0/model.safetensors",
            "semantic_codec_model.safetensors",
            "campplus_cn_common.bin",
            "bigvgan/config.json",
            "bigvgan/bigvgan_generator.pt",
        )
        cache_dir = checkpoint_dir / "hf_cache"
        return {
            "directory": checkpoint_dir.is_dir(),
            "required_files": all((checkpoint_dir / name).exists() for name in required),
            "auxiliary_cache": all((cache_dir / name).is_file() for name in auxiliary_files),
        }

    def status(self):
        python_command, python_detail = self._python_command()
        source_ready = (self.model_dir / "indextts").is_dir()
        model_checks = self._model_checks()
        model_weights_ready = model_checks["directory"] and model_checks["required_files"]
        runtime_ready = self._runtime_available(python_command)
        ready = bool(
            python_command
            and source_ready
            and model_weights_ready
            and model_checks["auxiliary_cache"]
            and runtime_ready
            and self.worker_path.is_file()
            and self._ffmpeg_available()
        )
        result = {
            "engine_requested": self.ENGINE_NAME,
            "engine_used": self.ENGINE_NAME if ready else None,
            "fallback": False,
            "ready": ready,
            "device_policy": hardware_capability_service.capabilities()["index_tts"],
            "checks": {
                "python_3_10": bool(python_command),
                "index_tts_source": source_ready,
                "index_tts_runtime": runtime_ready,
                "model_weights": model_weights_ready,
                "auxiliary_models": model_checks["auxiliary_cache"],
                "worker": self.worker_path.is_file(),
                "ffmpeg": self._ffmpeg_available(),
                "models_directory": self.model_dir.is_dir(),
            },
        }
        if not python_command:
            result["reason"] = python_detail
        elif not runtime_ready:
            result["reason"] = "外部 Python 3.10 缺少或无法加载 IndexTTS2 运行依赖"
        elif not source_ready:
            result["reason"] = "未检测到 models/index-tts 官方源码"
        elif not model_weights_ready:
            result["reason"] = "未检测到完整的 models/index-tts/checkpoints 模型文件"
        elif not model_checks["auxiliary_cache"]:
            result["reason"] = "IndexTTS2 辅助模型尚未准备完成"
        elif not result["checks"]["ffmpeg"]:
            result["reason"] = "未检测到 ffmpeg"
        return result

    def resolve_upload_audio(self, provided_path):
        if not isinstance(provided_path, str) or not provided_path.strip():
            raise LocalVoiceCloneError("参考音频无效")
        raw_path = Path(provided_path.strip())
        candidate = raw_path if raw_path.is_absolute() else self.project_root / raw_path
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.uploads_dir)
        except (OSError, ValueError):
            raise LocalVoiceCloneError("参考音频必须位于项目 uploads 目录内")
        if not resolved.is_file() or resolved.suffix.lower() not in self.AUDIO_SUFFIXES:
            raise LocalVoiceCloneError("参考音频格式无效")
        return resolved

    def normalize_reference(self, reference_audio, job_id):
        if not self._ffmpeg_available():
            raise LocalVoiceCloneError("未检测到 ffmpeg，无法规范化参考音频")
        self.processing_dir.mkdir(parents=True, exist_ok=True)
        normalized = self.processing_dir / f"{job_id}_reference.wav"
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(reference_audio),
            "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(normalized),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
        except subprocess.TimeoutExpired:
            raise LocalVoiceCloneError("参考音频规范化超时")
        except OSError:
            raise LocalVoiceCloneError("无法启动 ffmpeg")
        if result.returncode != 0 or not normalized.is_file() or normalized.stat().st_size == 0:
            normalized.unlink(missing_ok=True)
            raise LocalVoiceCloneError("参考音频规范化失败")
        return normalized

    @staticmethod
    def _worker_result(stdout):
        for line in reversed(stdout.splitlines()):
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                continue
        return None

    def generate(self, text, reference_audio):
        if not isinstance(text, str) or not text.strip():
            raise LocalVoiceCloneError("文本不能为空")
        if len(text) > 2000:
            raise LocalVoiceCloneError("文本超过 2000 字符限制")

        status = self.status()
        if not status["ready"]:
            raise LocalVoiceCloneError(status.get("reason") or "IndexTTS2 环境未就绪")

        python_command, _ = self._python_command()
        job_id = uuid.uuid4().hex
        normalized = self.normalize_reference(reference_audio, job_id)
        self.processing_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        request_path = self.processing_dir / f"{job_id}.json"
        output_path = self.output_dir / f"{job_id}.wav"
        request_path.write_text(json.dumps({
            "text": text.strip(),
            "reference_audio": str(normalized),
            "output_path": str(output_path),
            "model_dir": str(self.model_dir),
        }, ensure_ascii=False), encoding="utf-8")

        try:
            result = subprocess.run(
                python_command + [str(self.worker_path), "--request", str(request_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
                cwd=str(self.project_root),
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise LocalVoiceCloneError("IndexTTS2 生成超时")
        except OSError:
            raise LocalVoiceCloneError("无法启动外部 Python 3.10 worker")
        finally:
            request_path.unlink(missing_ok=True)
            normalized.unlink(missing_ok=True)

        worker_data = self._worker_result(result.stdout)
        if result.returncode != 0 or not worker_data or not worker_data.get("ok"):
            output_path.unlink(missing_ok=True)
            raise LocalVoiceCloneError((worker_data or {}).get("error") or "IndexTTS2 生成失败")
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise LocalVoiceCloneError("IndexTTS2 未生成有效音频文件")

        return {
            "engine_requested": self.ENGINE_NAME,
            "engine_used": self.ENGINE_NAME,
            "fallback": False,
            "device_used": worker_data.get("device_used", "cpu"),
            "directml_supported": False,
            "output_path": str(output_path.relative_to(self.project_root)).replace("\\", "/"),
            "output_url": f"/temp/outputs/local_voice_clone/{output_path.name}",
        }


local_voice_clone_service = LocalVoiceCloneService()
