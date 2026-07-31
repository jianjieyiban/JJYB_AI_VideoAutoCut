# -*- coding: utf-8 -*-
"""本机 GPU 与 FFmpeg 硬件能力检测。"""

import shutil
import subprocess
import sys


class HardwareCapabilityService:
    """只报告可实际检测到的硬件和编码器能力。"""

    @staticmethod
    def _run(command, timeout=8):
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            return result.stdout if result.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def _display_adapters(self):
        if sys.platform != "win32":
            return []
        output = self._run([
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
        ])
        return [line.strip() for line in output.splitlines() if line.strip()]

    @staticmethod
    def _test_encoder(encoder):
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.1",
                    "-c:v", encoder, "-f", "null", "-",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _ffmpeg_capabilities(self):
        available = shutil.which("ffmpeg") is not None
        encoders = self._run(["ffmpeg", "-hide_banner", "-encoders"]).lower() if available else ""
        hwaccels = self._run(["ffmpeg", "-hide_banner", "-hwaccels"]).lower() if available else ""
        advertised = {
            "nvenc": "h264_nvenc" in encoders,
            "qsv": "h264_qsv" in encoders,
            "amf": "h264_amf" in encoders,
        }
        usable = {
            name: self._test_encoder(f"h264_{name}") if present else False
            for name, present in advertised.items()
        }
        return {
            "available": available,
            "nvenc": usable["nvenc"],
            "qsv": usable["qsv"],
            "amf": usable["amf"],
            "advertised_encoders": advertised,
            "hardware_accelerations": [
                line.strip() for line in hwaccels.splitlines()
                if line.strip() and "hardware acceleration methods" not in line
            ],
        }

    def capabilities(self):
        adapters = self._display_adapters()
        normalized = [adapter.lower() for adapter in adapters]
        nvidia = any("nvidia" in adapter for adapter in normalized)
        amd = any("amd" in adapter or "radeon" in adapter for adapter in normalized)
        intel = any("intel" in adapter for adapter in normalized)
        cuda_devices = []
        if nvidia:
            cuda_devices = [line.strip() for line in self._run(["nvidia-smi", "-L"], timeout=5).splitlines() if line.strip()]

        ffmpeg = self._ffmpeg_capabilities()
        return {
            "platform": sys.platform,
            "display_adapters": adapters,
            "gpu": {
                "nvidia_detected": nvidia,
                "nvidia_cuda_available": bool(cuda_devices),
                "nvidia_devices": cuda_devices,
                "amd_detected": amd,
                "intel_detected": intel,
            },
            "ffmpeg": ffmpeg,
            "encoding": {
                "nvenc_available": ffmpeg["nvenc"],
                "qsv_available": ffmpeg["qsv"],
                "amf_available": ffmpeg["amf"],
                "amd_note": "AMD 显卡可在 FFmpeg 检测到 AMF 时用于 AMF 编码。" if amd else "未检测到 AMD 显卡。",
            },
            "index_tts": {
                "engine": "IndexTTS2",
                "windows_amd_device": "cpu" if sys.platform == "win32" and amd else None,
                "directml_supported": False,
                "note": "Windows 上 IndexTTS2 当前不使用 DirectML；AMD 环境走 CPU 推理。" if sys.platform == "win32" and amd else "IndexTTS2 推理设备由其运行时决定。",
            },
        }


hardware_capability_service = HardwareCapabilityService()
