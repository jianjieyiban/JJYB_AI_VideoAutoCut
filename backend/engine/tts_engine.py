# -*- coding: utf-8 -*-
"""
TTS Engine
文本转语音引擎 - 完整版
支持多种TTS引擎：Edge TTS、gTTS、Coqui TTS等
"""

import logging
import asyncio
import threading
import subprocess
import math
import re
import json
import time
from xml.sax.saxutils import escape
from pathlib import Path
from typing import Optional, Dict, List

import requests

logger = logging.getLogger(__name__)


class TTSEngine:
    """TTS引擎 - 完整版"""

    EDGE_REQUEST_TIMEOUT_SECONDS = 18
    EDGE_TASK_TIMEOUT_SECONDS = 60
    EDGE_LOCK_TIMEOUT_SECONDS = 5
    EDGE_MAX_CONCURRENT_REQUESTS = 1
    PYTTSX3_TASK_TIMEOUT_SECONDS = 20
    GTTS_TASK_TIMEOUT_SECONDS = 12
    _edge_request_semaphore = threading.BoundedSemaphore(EDGE_MAX_CONCURRENT_REQUESTS)
    _edge_workers_lock = threading.Lock()
    _edge_workers = set()

    def __init__(self, default_engine: Optional[str] = None):
        """初始化 TTS 引擎，并以系统 TTS 配置作为默认来源。"""
        self.default_engine = self._resolve_default_engine(default_engine)
        self.available_engines = self._check_available_engines()
        self._last_error = ''
        self._last_error_lock = threading.Lock()
        self._last_error_context = threading.local()
        if self.default_engine not in self.available_engines and self.available_engines:
            logger.warning(
                '配置的默认 TTS 引擎 %s 当前不可用，已回退为 %s',
                self.default_engine,
                self.available_engines[0],
            )
            self.default_engine = self.available_engines[0]
        logger.info(f'✅ TTS引擎初始化完成，默认引擎: {self.default_engine}，可用引擎: {self.available_engines}')

    @staticmethod
    def _normalize_engine_name(engine: Optional[str]) -> str:
        aliases = {
            'edge': 'edge-tts',
            'edgetts': 'edge-tts',
            'azure-tts': 'azure',
            'local': 'pyttsx3',
            'offline': 'pyttsx3',
            'indextts': 'indextts2',
            'index_tts': 'indextts2',
            'index-tts2': 'indextts2',
            'volcano-tts': 'volcano',
        }
        value = str(engine or '').strip().lower()
        return aliases.get(value, value or 'edge-tts')

    def _resolve_default_engine(self, requested_engine: Optional[str]) -> str:
        if requested_engine:
            return self._normalize_engine_name(requested_engine)
        try:
            from backend.config.ai_config import get_config_manager
            configured = getattr(
                get_config_manager().tts_model_config,
                'default_tts',
                'edge',
            )
            return self._normalize_engine_name(configured)
        except Exception as exc:
            logger.warning('读取默认 TTS 配置失败，使用 Edge TTS: %s', exc)
            return 'edge-tts'

    def reload_config(self) -> None:
        """重新读取运行时 TTS 配置并刷新可用引擎列表。"""
        self.default_engine = self._resolve_default_engine(None)
        self.available_engines = self._check_available_engines()
        if self.default_engine not in self.available_engines and self.available_engines:
            self.default_engine = self.available_engines[0]
        logger.info('🔄 TTS 配置已刷新，默认引擎: %s，可用引擎: %s', self.default_engine, self.available_engines)

    def _check_available_engines(self) -> List[str]:
        """检查可用的TTS引擎"""
        engines = []

        # 检查Edge TTS
        try:
            from backend.config.ai_config import get_config_manager
            cfg = get_config_manager()
            enable_edge = getattr(cfg.tts_model_config, 'enable_edge_tts', True)
            if enable_edge:
                import edge_tts
                engines.append('edge-tts')
            else:
                logger.info('Edge TTS 在配置中被关闭(enable_edge_tts=False)，跳过加载')
        except ImportError:
            logger.warning('Edge TTS未安装')
        except Exception as e:
            logger.warning(f'检查 Edge TTS 失败: {e}')

        # 检查gTTS
        try:
            from backend.config.ai_config import get_config_manager
            if not getattr(get_config_manager().tts_model_config, 'enable_gtts', False):
                logger.info('gTTS 在配置中被关闭(enable_gtts=False)，跳过加载')
            else:
                import gtts
                engines.append('gtts')
        except ImportError:
            logger.warning('gTTS未安装')
        except Exception as e:
            logger.warning(f'检查 gTTS 配置失败: {e}')

        # 检查Coqui TTS
        try:
            import TTS
            engines.append('coqui')
        except ImportError:
            logger.warning('Coqui TTS未安装')

        # 检查pyttsx3（离线）
        try:
            import pyttsx3  # noqa: F401
            engines.append('pyttsx3')
        except ImportError:
            logger.warning('pyttsx3未安装')

        # 检查Azure TTS（通过是否配置了Key/Region判断）
        try:
            from backend.config.ai_config import get_config_manager
            cfg = get_config_manager()
            key = getattr(cfg.tts_model_config, 'azure_tts_key', '') or getattr(cfg.tts_model_config, 'azure_subscription_key', '')
            region = getattr(cfg.tts_model_config, 'azure_tts_region', '') or getattr(cfg.tts_model_config, 'azure_region', '')
            if key and region:
                engines.append('azure')
            else:
                logger.warning('Azure TTS未配置密钥或区域，如需使用请在设置中填写 azure_tts_key 和 azure_tts_region')
        except Exception as e:
            logger.warning(f'检查Azure TTS配置失败: {e}')

        return engines

    @staticmethod
    def _normalize_pitch(value, edge_format: bool = False):
        """规范化音调：Hz 字符串原样按 Hz 解析，数字按半音解析。"""
        semitones = 0.0
        if not isinstance(value, bool) and value is not None:
            try:
                if isinstance(value, str):
                    raw = value.strip()
                    if raw.lower().endswith('hz'):
                        # 仅接受单个规范 Hz 值，拒绝历史故障中的 +0Hz+0Hz 拼接值。
                        match = re.fullmatch(r'([+-]?\d+(?:\.\d+)?)\s*hz', raw, re.IGNORECASE)
                        if match:
                            hz = float(match.group(1))
                            if math.isfinite(hz):
                                if edge_format:
                                    rounded = int(round(hz))
                                    return f'{rounded:+d}Hz' if rounded else '+0Hz'
                                return hz / 7.0
                    elif raw:
                        semitones = float(raw)
                elif isinstance(value, (int, float)):
                    semitones = float(value)
            except (TypeError, ValueError):
                semitones = 0.0
        if not math.isfinite(semitones):
            semitones = 0.0
        # 合成端限制在常用的 ±12 半音范围内，避免异常输入。
        semitones = max(-12.0, min(12.0, semitones))
        if edge_format:
            hz = int(round(semitones * 7))
            return f'{hz:+d}Hz' if hz else '+0Hz'
        return semitones

    @classmethod
    def normalize_pitch(cls, value, edge_format: bool = False):
        """公共音调规范化入口，保持调用方兼容。"""
        return cls._normalize_pitch(value, edge_format=edge_format)

    @staticmethod
    def normalize_edge_pitch(value) -> str:
        """将半音或 Hz 输入统一为 Edge TTS 的 ±整数Hz 格式。"""
        if isinstance(value, bool) or value is None:
            return '+0Hz'
        if isinstance(value, str):
            raw = value.strip()
            hz_match = re.search(r'([+-]?\d+(?:\.\d+)?)\s*hz', raw, re.IGNORECASE)
            if hz_match:
                try:
                    hz = float(hz_match.group(1))
                    if math.isfinite(hz):
                        rounded = int(round(hz))
                        return f'{rounded:+d}Hz' if rounded else '+0Hz'
                except (TypeError, ValueError):
                    pass
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return '+0Hz'
        try:
            semitones = float(value)
        except (TypeError, ValueError):
            return '+0Hz'
        if not math.isfinite(semitones):
            return '+0Hz'
        semitones = max(-12.0, min(12.0, semitones))
        hz = int(round(semitones * 7))
        return f'{hz:+d}Hz' if hz else '+0Hz'

    @staticmethod
    def _normalize_edge_percent(value) -> str:
        if isinstance(value, bool) or value is None:
            return '+0%'
        try:
            normalized = str(value).strip()
            if not normalized:
                return '+0%'
            if normalized.endswith('%'):
                normalized = normalized[:-1].strip()
            number = float(normalized)
            if not math.isfinite(number):
                return '+0%'
            text = f'{number:g}'
            return f'{float(text):+g}%'
        except (TypeError, ValueError):
            return '+0%'

    @property
    def last_error(self) -> str:
        """当前调用线程最近一次合成失败的用户可见原因。"""
        local_error = getattr(self._last_error_context, 'message', None)
        if local_error is not None:
            return local_error
        with self._last_error_lock:
            return self._last_error

    def _set_last_error(self, message: str) -> None:
        value = str(message or '')
        self._last_error_context.message = value
        with self._last_error_lock:
            self._last_error = value

    @staticmethod
    def _remove_partial_output(output_path: str) -> None:
        try:
            Path(output_path).unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _is_retryable_edge_error(error: Exception) -> bool:
        try:
            import aiohttp
            aiohttp_errors = (aiohttp.ClientError, asyncio.TimeoutError)
        except ImportError:
            aiohttp_errors = (asyncio.TimeoutError,)
        return isinstance(error, aiohttp_errors + (OSError,)) or error.__class__.__name__ == 'NoAudioReceived'

    async def synthesize_edge_tts(self, text: str, output_path: str,
                                  voice: str = 'zh-CN-XiaoxiaoNeural',
                                  rate: str = '+0%', volume: str = '+0%',
                                  pitch: Optional[int] = None,
                                  advanced_config: Optional[Dict] = None) -> bool:
        """使用 Edge TTS 合成语音；每次请求限时，网络故障最多尝试三次。"""
        self._set_last_error('')
        if not str(text or '').strip():
            self._set_last_error('Edge TTS 文本为空，请填写解说内容后重试')
            logger.warning('Edge TTS 合成被拒绝：文本为空')
            return False

        try:
            import edge_tts
        except Exception:
            self._set_last_error('Edge TTS 引擎不可用，请检查依赖或切换本地/Google 引擎')
            logger.error('Edge TTS 引擎不可用')
            return False

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        pitch_str = self.normalize_edge_pitch(pitch)
        rate = self._normalize_edge_percent(rate)
        volume = self._normalize_edge_percent(volume)
        segment_name = Path(output_path).stem
        logger.info('Edge TTS 开始：段=%s，voice=%s，rate=%s，volume=%s，pitch=%s', segment_name, voice, rate, volume, pitch_str)

        for attempt in range(1, 4):
            self._remove_partial_output(output_path)
            try:
                communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch_str)
                await asyncio.wait_for(
                    communicate.save(output_path), timeout=self.EDGE_REQUEST_TIMEOUT_SECONDS
                )
                out_file = Path(output_path)
                if not out_file.is_file() or out_file.stat().st_size < 1024:
                    raise OSError('Edge TTS 未生成有效音频文件')
                logger.info('Edge TTS 成功：段=%s，尝试=%s/3，%s bytes', segment_name, attempt, out_file.stat().st_size)
                return True
            except asyncio.TimeoutError:
                self._remove_partial_output(output_path)
                failure_kind = 'timeout'
                error = None
            except Exception as caught_error:
                self._remove_partial_output(output_path)
                error = caught_error
                failure_kind = 'NoAudio' if caught_error.__class__.__name__ == 'NoAudioReceived' else 'network'
                if not self._is_retryable_edge_error(caught_error):
                    message = f'Edge TTS 参数或服务请求失败：{caught_error}'
                    self._set_last_error(message)
                    logger.error('Edge TTS 失败：段=%s，尝试=%s/3，类型=%s，原因=%s', segment_name, attempt, failure_kind, caught_error)
                    return False

            if attempt < 3:
                delay = 0.6 * (2 ** (attempt - 1))
                logger.warning('Edge TTS 未完成：段=%s，尝试=%s/3，类型=%s，%.1f 秒后重试%s',
                               segment_name, attempt, failure_kind, delay,
                               f'：{error}' if error else '')
                await asyncio.sleep(delay)
                continue

            if failure_kind == 'timeout':
                message = f'Edge TTS 请求超时（每次最多 {self.EDGE_REQUEST_TIMEOUT_SECONDS} 秒，已重试 3 次），请检查网络后重试'
            elif failure_kind == 'NoAudio':
                message = 'Edge TTS 未返回音频（已重试 3 次），请检查网络后重试'
            else:
                message = 'Edge TTS 网络请求失败（已重试 3 次），请检查网络后重试'
            self._set_last_error(message)
            logger.error('Edge TTS 最终失败：段=%s，尝试=%s/3，类型=%s%s', segment_name, attempt, failure_kind,
                         f'，原因={error}' if error else '')
            return False
        return False

    def _run_edge_synthesis(self, coroutine, timeout: Optional[float] = None,
                            output_path: Optional[str] = None) -> bool:
        """在受限工作线程执行 Edge 协程，调用方始终在明确总时限内返回。"""
        timeout = float(timeout or self.EDGE_TASK_TIMEOUT_SECONDS)
        if not self._edge_request_semaphore.acquire(timeout=self.EDGE_LOCK_TIMEOUT_SECONDS):
            try:
                coroutine.close()
            except Exception:
                pass
            self._set_last_error(f'Edge TTS 请求繁忙，等待超过 {self.EDGE_LOCK_TIMEOUT_SECONDS} 秒，请稍后重试')
            logger.warning('Edge TTS 请求未取得并发槽位，已在 %s 秒后返回', self.EDGE_LOCK_TIMEOUT_SECONDS)
            return False

        outcome = {'result': False, 'error': None, 'last_error': ''}
        completed = threading.Event()

        def run_in_thread():
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                outcome['result'] = loop.run_until_complete(coroutine)
                outcome['last_error'] = self.last_error
            except Exception as error:
                outcome['error'] = error
            finally:
                try:
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                finally:
                    asyncio.set_event_loop(None)
                    loop.close()
                    with self._edge_workers_lock:
                        self._edge_workers.discard(threading.current_thread())
                    self._edge_request_semaphore.release()
                    completed.set()

        worker = threading.Thread(target=run_in_thread, name='edge-tts-worker', daemon=True)
        with self._edge_workers_lock:
            self._edge_workers.add(worker)
        worker.start()
        if not completed.wait(timeout):
            if output_path:
                self._remove_partial_output(output_path)
            self._set_last_error(f'Edge TTS 总任务超时（最多 {int(timeout)} 秒），请求已停止等待，请稍后重试')
            logger.error('Edge TTS 工作线程超时：%s 秒；线程仍在后台清理，未复用其输出路径', timeout)
            return False

        with self._edge_workers_lock:
            self._edge_workers.discard(worker)
        if outcome['error']:
            self._set_last_error('Edge TTS 合成执行失败，请检查网络后重试')
            logger.error('Edge TTS 工作线程执行失败: %s', outcome['error'])
            return False
        self._set_last_error(outcome['last_error'])
        return bool(outcome['result'])

    def has_compatible_pyttsx3_voice(self, requested_voice: Optional[str] = None) -> bool:
        """只在存在对应语言的 Windows SAPI 音色时允许本地回退。"""
        target = 'zh' if 'zh' in str(requested_voice or 'zh-CN').lower() else str(requested_voice or '').split('-')[0].lower()
        com_initialized = False
        engine = None
        try:
            try:
                import pythoncom
                pythoncom.CoInitialize()
                com_initialized = True
            except ImportError:
                pass
            import pyttsx3
            engine = pyttsx3.init()
            for item in engine.getProperty('voices') or []:
                name = str(getattr(item, 'name', '') or '').lower()
                langs = getattr(item, 'languages', []) or []
                language_text = ' '.join(
                    value.decode(errors='ignore') if isinstance(value, bytes) else str(value)
                    for value in langs
                ).lower()
                combined = f'{name} {language_text}'
                if target == 'zh':
                    if any(token in combined for token in ('zh', 'chinese', '中文', '普通话', 'mandarin')):
                        return True
                elif target and target in combined:
                    return True
            return False
        except Exception as exc:
            logger.info('无法确认本地 SAPI 音色，跳过本地回退: %s', exc)
            return False
        finally:
            if engine:
                try:
                    engine.stop()
                except Exception:
                    pass
            if com_initialized:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def _validate_audio_file(self, path: str | Path, min_duration: float = 0.12) -> bool:
        """只接受含音频流、可读取且非静音的真实音频文件。"""
        candidate = Path(path)
        if not candidate.is_file() or candidate.stat().st_size < 1024:
            return False
        try:
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_streams', '-show_entries',
                 'format=duration:stream=codec_type,duration', '-of', 'json', str(candidate)],
                capture_output=True, text=True, timeout=10, check=False,
            )
            data = json.loads(probe.stdout or '{}') if probe.returncode == 0 else {}
            streams = data.get('streams') or []
            if not any(stream.get('codec_type') == 'audio' for stream in streams):
                return False
            duration = float((data.get('format') or {}).get('duration') or 0)
            if duration < min_duration:
                return False
            silence = subprocess.run(
                ['ffmpeg', '-v', 'error', '-i', str(candidate), '-af', 'volumedetect', '-f', 'null', '-'],
                capture_output=True, text=True, timeout=12, check=False,
            )
            match = re.search(r'max_volume:\s*(-?(?:inf|\d+(?:\.\d+)?)?)\s*dB', silence.stderr or '', re.I)
            if match and match.group(1).lower() == '-inf':
                return False
            return silence.returncode == 0
        except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            logger.warning('音频有效性校验失败: %s', exc)
            return False

    def _run_blocking_tts(self, worker_func, timeout: float, label: str) -> bool:
        """将潜在阻塞的本地/网络 TTS 限时运行；超时线程只写独立临时文件。"""
        result = {'ok': False, 'error': None}
        finished = threading.Event()

        def runner():
            try:
                result['ok'] = bool(worker_func())
            except Exception as exc:
                result['error'] = exc
            finally:
                finished.set()

        worker = threading.Thread(target=runner, name=f'{label}-worker', daemon=True)
        worker.start()
        if not finished.wait(timeout):
            self._set_last_error(f'{label} 合成超时（最多 {int(timeout)} 秒），未采用未验证输出')
            logger.warning('%s 工作线程超时，已放弃其临时输出', label)
            return False
        if result['error']:
            self._set_last_error(f'{label} 合成失败：{result["error"]}')
            return False
        return bool(result['ok'])

    def synthesize_pyttsx3(self, text: str, output_path: str,
                           voice: Optional[str] = None, rate: Optional[str] = None,
                           volume: Optional[str] = None,
                           advanced_config: Optional[Dict] = None) -> bool:
        """在独立 COM 线程使用 Windows SAPI，并只发布经 ffprobe/非静音校验的 MP3。"""
        output = Path(output_path)
        temp_output = output.with_name(f'.{output.stem}_{threading.get_ident()}_{time.time_ns()}.mp3')

        def work():
            com_initialized = False
            try:
                try:
                    import pythoncom
                    pythoncom.CoInitialize()
                    com_initialized = True
                except ImportError:
                    pass
                return self._synthesize_pyttsx3_blocking(text, str(temp_output), voice, rate, volume, advanced_config)
            finally:
                if com_initialized:
                    try:
                        pythoncom.CoUninitialize()
                    except Exception:
                        pass

        try:
            ok = self._run_blocking_tts(work, self.PYTTSX3_TASK_TIMEOUT_SECONDS, '本地 Windows SAPI')
            if ok and self._validate_audio_file(temp_output):
                output.parent.mkdir(parents=True, exist_ok=True)
                temp_output.replace(output)
                self._set_last_error('')
                return True
            if ok:
                self._set_last_error('本地 Windows SAPI 未生成有效的非静音音频')
            return False
        finally:
            if temp_output.exists():
                self._remove_partial_output(str(temp_output))

    def _synthesize_pyttsx3_blocking(self, text: str, output_path: str,
                                     voice: Optional[str] = None,
                                     rate: Optional[str] = None,
                                     volume: Optional[str] = None,
                                     advanced_config: Optional[Dict] = None) -> bool:
        """
        使用 pyttsx3（Windows SAPI5 离线）合成语音
        - 先输出为 WAV，再使用 ffmpeg 转为 MP3

        注意：pyttsx3在某些环境下不稳定，建议使用Edge-TTS或gTTS作为替代
        """
        try:
            import pyttsx3
            out_path = Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_wav = out_path.with_suffix('.wav')

            # 初始化引擎，捕获可能的异常
            try:
                engine = pyttsx3.init()
            except Exception as init_err:
                logger.error(f'❗ pyttsx3 初始化失败: {init_err}')
                return False

            # 可选：根据 rate/volume 调整
            try:
                if isinstance(rate, str) and rate.endswith('%'):
                    pct = int(rate[:-1])
                    base = 200
                    new_rate = max(80, min(300, int(base * (1 + pct/100.0))))
                    engine.setProperty('rate', new_rate)
                    logger.debug(f'设置语速: {new_rate}')
            except Exception as e:
                logger.warning(f'设置语速失败: {e}')

            try:
                if isinstance(volume, str) and volume.endswith('%'):
                    pct = int(volume[:-1])
                    v = max(0.0, min(1.0, 1.0 + pct/100.0))
                    engine.setProperty('volume', v)
                    logger.debug(f'设置音量: {v}')
            except Exception as e:
                logger.warning(f'设置音量失败: {e}')

            # 改进的音色匹配逻辑
            try:
                voices = engine.getProperty('voices') or []
                if not voices:
                    logger.warning('⚠️ pyttsx3 未检测到系统音色，将使用默认音色')
                else:
                    logger.info(f'检测到 {len(voices)} 个系统音色')

                v_str = (voice or 'zh-CN-XiaoxiaoNeural').lower()

                # 从Edge-TTS音色ID推断语言和性别
                target_lang = 'zh'
                target_gender = None

                # 语言推断
                if 'en-' in v_str or v_str.startswith('en') or 'english' in v_str:
                    target_lang = 'en'
                elif 'ja' in v_str or 'jp' in v_str or 'japanese' in v_str:
                    target_lang = 'ja'
                elif 'ko' in v_str or 'kr' in v_str or 'korean' in v_str:
                    target_lang = 'ko'
                elif 'fr' in v_str or 'french' in v_str:
                    target_lang = 'fr'
                elif 'es' in v_str or 'spanish' in v_str:
                    target_lang = 'es'

                # 粗略推断目标性别（如果本地语音里带有 gender 信息可以利用）
                target_gender = None
                if any(key in v_str for key in ('xiaoxiao', 'xiaoyi', 'xiaomo', 'xiaoqiu', 'jenny', 'sonia', 'female', 'woman')):
                    target_gender = 'female'
                elif any(key in v_str for key in ('yunxi', 'yunyang', 'yunjian', 'yunhao', 'ryan', 'male', 'man')):
                    target_gender = 'male'

                def _match_voice(lang_key: str = None, gender_key: str = None):
                    for vv in voices:
                        name = (getattr(vv, 'name', '') or '').lower()
                        lang_meta = ''
                        try:
                            lang_meta = ''.join(vv.languages or []) if hasattr(vv, 'languages') else ''
                        except Exception:
                            lang_meta = ''
                        meta = (name + ' ' + lang_meta.lower())

                        if lang_key and lang_key not in meta:
                            continue

                        if gender_key:
                            gender_text = (getattr(vv, 'gender', '') or '').lower()
                            if gender_key not in gender_text and gender_key not in name:
                                continue

                        return vv.id
                    return None

                chosen = None

                # 第一轮：语言 + 性别
                if target_gender:
                    chosen = _match_voice(target_lang, target_gender)

                # 第二轮：只按语言
                if not chosen and target_lang:
                    chosen = _match_voice(target_lang, None)

                # 最后兜底：旧逻辑，优先找中文语音
                if not chosen:
                    for v in voices:
                        name = (getattr(v, 'name', '') or '').lower()
                        lang_meta = ''
                        try:
                            lang_meta = ''.join(v.languages or []) if hasattr(v, 'languages') else ''
                        except Exception:
                            lang_meta = ''
                        if 'zh' in name or 'chi' in name or 'zh' in lang_meta.lower():
                            chosen = v.id
                            break

                if chosen:
                    engine.setProperty('voice', chosen)
                    logger.info(f'✅ 选择音色: {chosen}')
                else:
                    logger.warning(f'⚠️ 未找到匹配音色，使用系统默认音色（语言:{target_lang}, 性别:{target_gender}）')
            except Exception as e:
                logger.warning(f'⚠️ 音色选择失败: {e}')

            # 保存音频并等待
            try:
                engine.save_to_file(text, str(tmp_wav))
                engine.runAndWait()

                # pyttsx3有时需要额外的等待时间让文件完全写入
                import time
                time.sleep(0.5)

            except Exception as e:
                logger.error(f'❗ pyttsx3 语音合成失败: {e}')
                # 尝试清理并返回
                try:
                    engine.stop()
                except:
                    pass
                return False

            # 验证WAV文件是否生成（至少1KB）
            if not tmp_wav.exists():
                logger.error(f'❗ pyttsx3 未生成WAV文件: {tmp_wav}')
                return False

            wav_size = tmp_wav.stat().st_size
            if wav_size < 1024:
                logger.error(f'❗ pyttsx3 生成WAV文件过小({wav_size} bytes)，Windows SAPI5引擎可能不可用: {tmp_wav}')
                logger.warning('⚠️ 建议：1. 检查Windows语音服务 2. 或优先使用Edge-TTS/gTTS在线引擎')
                # 清理损坏的文件
                try:
                    tmp_wav.unlink()
                except:
                    pass
                return False

            # 转换为 MP3
            try:
                cmd = ['ffmpeg', '-y', '-i', str(tmp_wav), '-ar', '22050', '-ac', '1', str(out_path)]
                proc = subprocess.run(cmd, capture_output=True, timeout=15, check=False)
                if proc.returncode != 0:
                    logger.error(f'ffmpeg 转换失败: {proc.stderr[:300].decode("utf-8", errors="ignore") if hasattr(proc.stderr, "decode") else proc.stderr}')
                    return False
            finally:
                try:
                    if tmp_wav.exists():
                        tmp_wav.unlink()
                except Exception:
                    pass

            # 验证MP3文件是否生成（至少1KB）
            if not out_path.exists():
                logger.error(f'❗ ffmpeg 未生成MP3文件: {out_path}')
                return False

            mp3_size = out_path.stat().st_size
            if mp3_size < 1024:
                logger.error(f'❗ ffmpeg 生成MP3文件过小({mp3_size} bytes): {out_path}')
                return False

            logger.info(f'✅ pyttsx3 合成成功: {output_path} ({out_path.stat().st_size} bytes)')
            return True
        except Exception as e:
            logger.error(f'❗ pyttsx3 合成失败: {e}', exc_info=True)
            return False

    def synthesize_gtts(self, text: str, output_path: str,
                       lang: str = 'zh-CN', slow: bool = False,
                       voice: Optional[str] = None,
                       advanced_config: Optional[Dict] = None) -> bool:
        """有限时网络回退；仅发布通过真实音频校验的输出。"""
        output = Path(output_path)
        temp_output = output.with_name(f'.{output.stem}_{threading.get_ident()}_{time.time_ns()}.mp3')
        try:
            ok = self._run_blocking_tts(
                lambda: self._synthesize_gtts_blocking(text, str(temp_output), lang, slow, voice, advanced_config),
                self.GTTS_TASK_TIMEOUT_SECONDS, 'gTTS',
            )
            if ok and self._validate_audio_file(temp_output):
                output.parent.mkdir(parents=True, exist_ok=True)
                temp_output.replace(output)
                self._set_last_error('')
                return True
            if ok:
                self._set_last_error('gTTS 未生成有效的非静音音频')
            return False
        finally:
            if temp_output.exists():
                self._remove_partial_output(str(temp_output))

    def _synthesize_gtts_blocking(self, text: str, output_path: str,
                                  lang: str = 'zh-CN', slow: bool = False,
                                  voice: Optional[str] = None,
                                  advanced_config: Optional[Dict] = None) -> bool:
        """
        使用gTTS合成语音

        Args:
            text: 要合成的文本
            output_path: 输出音频路径
            lang: 语言代码
            slow: 是否慢速
            voice: 音色ID（用于推断语言）

        Returns:
            是否成功
        """
        try:
            from gtts import gTTS

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            # 如果提供了voice参数，从中推断语言
            if voice:
                v_lower = voice.lower()
                if 'zh-cn' in v_lower or 'zh-tw' in v_lower or 'zh-hk' in v_lower:
                    lang = 'zh-CN' if 'zh-cn' in v_lower else ('zh-TW' if 'zh-tw' in v_lower else 'zh-CN')
                elif 'en-' in v_lower or v_lower.startswith('en'):
                    lang = 'en'
                elif 'ja' in v_lower or 'jp' in v_lower:
                    lang = 'ja'
                elif 'ko' in v_lower or 'kr' in v_lower:
                    lang = 'ko'
                elif 'fr' in v_lower:
                    lang = 'fr'
                elif 'es' in v_lower:
                    lang = 'es'
                logger.info(f'从音色 {voice} 推断语言: {lang}')

            tts = gTTS(text=text, lang=lang, slow=slow)
            tts.save(output_path)

            # 验证文件是否有效（至少1KB）
            out_file = Path(output_path)
            if not out_file.exists():
                logger.error(f'❗ gTTS 未生成文件: {output_path}')
                return False

            file_size = out_file.stat().st_size
            if file_size < 1024:
                logger.error(f'❗ gTTS 生成文件过小({file_size} bytes): {output_path}')
                return False

            logger.info(f'✅ gTTS合成成功: {output_path} ({file_size} bytes)')
            return True

        except Exception as e:
            logger.error(f'❗ gTTS合成失败: {e}', exc_info=True)
            return False

    def synthesize_coqui(self, text: str, output_path: str,
                        model_name: str = 'tts_models/zh-CN/baker/tacotron2-DDC-GST',
                        advanced_config: Optional[Dict] = None) -> bool:
        """
        使用Coqui TTS合成语音

        Args:
            text: 要合成的文本
            output_path: 输出音频路径
            model_name: 模型名称

        Returns:
            是否成功
        """
        try:
            from TTS.api import TTS

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            tts = TTS(model_name=model_name)
            tts.tts_to_file(text=text, file_path=output_path)

            logger.info(f'✅ Coqui TTS合成成功: {output_path}')
            return True

        except Exception as e:
            logger.error(f'❗ Coqui TTS合成失败: {e}', exc_info=True)
            return False

    def synthesize_azure_tts(self, text: str, output_path: str,
                             voice: str = 'zh-CN-XiaoxiaoNeural',
                             rate: str = '+0%', volume: str = '+0%',
                             pitch: Optional[int] = None,
                             advanced_config: Optional[Dict] = None) -> bool:
        """使用 Azure TTS 合成语音（通过 REST API），支持情感SSML"""
        try:
            from backend.config.ai_config import get_config_manager
            from xml.sax.saxutils import escape
            cfg = get_config_manager()
            subscription_key = getattr(cfg.tts_model_config, 'azure_tts_key', '') or getattr(cfg.tts_model_config, 'azure_subscription_key', '')
            region = getattr(cfg.tts_model_config, 'azure_tts_region', '') or getattr(cfg.tts_model_config, 'azure_region', '')

            if not subscription_key or not region:
                logger.error('Azure TTS 未配置密钥或区域，无法合成')
                return False

            url = f'https://{region}.tts.speech.microsoft.com/cognitiveservices/v1'

            # 将 Edge 风格的百分比语速转换为 Azure prosody rate（简单映射）
            rate_value = 0
            try:
                if isinstance(rate, str) and rate.endswith('%'):
                    rate_value = int(rate[:-1])
            except Exception:
                rate_value = 0
            prosody_rate = f"{rate_value}%" if rate_value else "0%"

            # Azure 使用与 Edge 一致的规范 Hz 格式，避免字符串参与数值计算。
            pitch_str = self.normalize_pitch(pitch, edge_format=True)

            # Azure prosody volume 接受带正负号的百分比，例如 +20%、-10%。
            volume_value = 0
            try:
                if isinstance(volume, str) and volume.strip().endswith('%'):
                    volume_value = int(volume.strip()[:-1])
                elif isinstance(volume, (int, float)):
                    volume_value = int(volume)
            except (TypeError, ValueError):
                volume_value = 0
            prosody_volume = f'{volume_value:+d}%' if volume_value else '+0%'

            # 处理高级配置：情感TTS
            emotion_style = None
            emotion_role = None
            if advanced_config:
                emotion = advanced_config.get('emotion_type', 'neutral')
                intensity = advanced_config.get('emotion_intensity', 'moderate')
                # Azure 神经语音支持的情感风格（中文）
                emotion_to_style = {
                    'happy': 'cheerful',
                    'sad': 'sad',
                    'angry': 'angry',
                    'excited': 'excited',
                    'calm': 'calm',
                    'fearful': 'fearful',
                    'love': 'gentle',
                    'neutral': None,
                }
                emotion_style = emotion_to_style.get(emotion)
                # 情感强度映射到 degree
                intensity_to_degree = {
                    'subtle': '0.3',
                    'moderate': '0.6',
                    'strong': '0.9',
                    'extreme': '1.0',
                }
                emotion_degree = intensity_to_degree.get(intensity, '0.6')

            logger.info(f'🎵 Azure TTS参数: voice={voice}, rate={prosody_rate}, volume={prosody_volume}, pitch={pitch_str}, emotion={emotion_style}')

            escaped_voice = escape(str(voice), entities={'"': '&quot;', "'": '&apos;'})
            escaped_text = escape(str(text))

            # 构建 SSML
            if emotion_style:
                ssml = f"""
<speak version='1.0' xml:lang='zh-CN' xmlns:mstts='https://www.w3.org/2001/mstts'>
  <voice name='{escaped_voice}'>
    <mstts:express-as style='{emotion_style}' styledegree='{emotion_degree}'>
      <prosody rate='{prosody_rate}' volume='{prosody_volume}' pitch='{pitch_str}'>
        {escaped_text}
      </prosody>
    </mstts:express-as>
  </voice>
</speak>
""".strip()
            else:
                ssml = f"""
<speak version='1.0' xml:lang='zh-CN'>
  <voice name='{escaped_voice}'>
    <prosody rate='{prosody_rate}' volume='{prosody_volume}' pitch='{pitch_str}'>
      {escaped_text}
    </prosody>
  </voice>
</speak>
""".strip()

            headers = {
                'Ocp-Apim-Subscription-Key': subscription_key,
                'Content-Type': 'application/ssml+xml',
                'X-Microsoft-OutputFormat': 'audio-16khz-32kbitrate-mono-mp3',
                'User-Agent': 'JJYB_AI_TTS'
            }

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            resp = requests.post(url, headers=headers, data=ssml.encode('utf-8'), timeout=30)
            if resp.status_code == 200:
                with open(output_path, 'wb') as f:
                    f.write(resp.content)
                logger.info(f'✅ Azure TTS合成成功: {output_path}')
                return True
            else:
                logger.error(f'❗ Azure TTS合成失败: {resp.status_code} {resp.text[:300]}')
        except Exception as e:
            logger.error(f'❗ Azure TTS合成异常: {e}', exc_info=True)
            return False

    def synthesize(self, text: str, output_path: str,
                  engine: Optional[str] = None,
                  voice: str = 'zh-CN-XiaoxiaoNeural',
                  pitch: Optional[int] = None,
                  advanced_config: Optional[Dict] = None,
                  **kwargs) -> bool:
        """
        统一的语音合成接口

        Args:
            text: 要合成的文本
            output_path: 输出音频路径
            engine: 指定引擎（不指定则使用默认）
            voice: 语音名称
            pitch: 音调调整（半音，-12到+12）
            advanced_config: 高级配置（情感TTS、说话人嵌入等）
            **kwargs: 其他参数

        Returns:
            是否成功
        """
        raw_engine = engine or self.default_engine
        engine = self._normalize_engine_name(raw_engine)
        self._set_last_error('')
        edge_rate = kwargs.get('rate', '+0%')
        edge_volume = kwargs.get('volume', '+0%')
        if engine == 'edge-tts':
            pitch = self.normalize_edge_pitch(pitch)
        else:
            pitch = self.normalize_pitch(pitch)
        # --- 对外传入的 engine_key 统一分发 ---
        # IndexTTS2 克隆语音：委托给本地声音复刻服务
        if engine in ('indextts2', 'indextts', 'index-tts2'):
            return self._synthesize_indextts2(text, output_path, voice=voice,
                                              pitch=pitch, advanced_config=advanced_config, **kwargs)

        # 火山引擎 TTS（字节火山）
        if engine in ('volcano', 'volcano-tts', 'huoshan', 'bytedance'):
            return self._synthesize_volcano(text, output_path, voice=voice,
                                            pitch=pitch, advanced_config=advanced_config, **kwargs)

        # Voice-Pro / CosyVoice 外部专业引擎（HTTP）
        if engine in ('voice-pro', 'voicepro', 'voice_pro', 'cosyvoice', 'cosy-voice'):
            return self._synthesize_voicepro(text, output_path, voice=voice,
                                            pitch=pitch, advanced_config=advanced_config, **kwargs)

        # Google TTS（云端 gTTS 兜底）
        if engine in ('gtts', 'google', 'google-tts'):
            engine = 'gtts'  # 进入下面的 available_engines 判断 + 分支

        # Azure TTS
        if engine in ('azure', 'azure-tts', 'microsoft-azure'):
            engine = 'azure'

        # Edge TTS
        if engine in ('edge-tts', 'edge', 'microsoft-edge'):
            engine = 'edge-tts'

        if engine not in self.available_engines and engine != 'edge-tts':
            logger.warning(f'引擎 {engine} 不在 available_engines 中，尝试回退 Edge-TTS')
            # 兜底 Edge-TTS（免费、稳定）
            engine = 'edge-tts'

        # 提取并记录高级配置
        if advanced_config:
            emotion_type = advanced_config.get('emotion_type', 'neutral')
            emotion_intensity = advanced_config.get('emotion_intensity', 'moderate')
            inference_mode = advanced_config.get('inference_mode', 'balanced')
            logger.info(f'🎭 高级配置: emotion={emotion_type}, intensity={emotion_intensity}, inference={inference_mode}')

        try:
            if engine == 'edge-tts':
                # Edge TTS需要异步运行，运行中的调用方事件循环会在独立线程中执行。
                result = self._run_edge_synthesis(
                    self.synthesize_edge_tts(
                        text, output_path, voice=voice, rate=edge_rate, volume=edge_volume,
                        pitch=pitch, advanced_config=advanced_config
                    ),
                    output_path=output_path,
                )
                if not result and not self.last_error:
                    self._set_last_error('Edge TTS 未生成有效音频，请检查网络后重试或切换本地/Google 引擎')

            elif engine == 'gtts':
                result = self.synthesize_gtts(text, output_path, voice=voice, advanced_config=advanced_config, **kwargs)

            elif engine == 'coqui':
                result = self.synthesize_coqui(text, output_path, advanced_config=advanced_config, **kwargs)

            elif engine == 'azure':
                result = self.synthesize_azure_tts(text, output_path, voice=voice, pitch=pitch, advanced_config=advanced_config, **kwargs)

            elif engine == 'pyttsx3':
                result = self.synthesize_pyttsx3(text, output_path, voice=voice, advanced_config=advanced_config, **kwargs)

            else:
                logger.error(f'未知引擎: {engine}')
                return False

            # 合成成功后，应用高级后处理（数据增强、音量变化等）
            if result and advanced_config:
                result = self._apply_post_processing(output_path, advanced_config)

            return result

        except Exception as e:
            logger.error(f'语音合成失败: {e}', exc_info=True)
            return False

    def _synthesize_indextts2(self, text: str, output_path: str,
                              voice: str = '', pitch: Optional[int] = None,
                              advanced_config: Optional[Dict] = None, **kwargs) -> bool:
        """使用 IndexTTS2 本地声音复刻合成语音。

        需要 reference_audio 参数（通过 kwargs 或 advanced_config 提供）。
        输出为 WAV 格式，若 output_path 以 .mp3 结尾则自动改为 .wav。
        """
        try:
            from backend.services.local_voice_clone_service import (
                LocalVoiceCloneError,
                local_voice_clone_service,
            )

            reference_audio = ''
            consent = False
            if isinstance(advanced_config, dict):
                reference_audio = advanced_config.get('reference_audio') or ''
                consent = bool(advanced_config.get('consent', False))
            reference_audio = kwargs.get('reference_audio', reference_audio)
            consent = kwargs.get('consent', consent)

            if not reference_audio:
                logger.error('IndexTTS2 克隆语音必须提供 reference_audio 参考音频路径')
                return False
            if not consent:
                logger.error('使用克隆语音必须明确确认已获得参考音频权利人的授权（consent=true）')
                return False

            status = local_voice_clone_service.status()
            if not status.get('ready'):
                logger.error(f'IndexTTS2 引擎未就绪: {status.get("reason") or "请检查环境和模型文件"}')
                return False

            result = local_voice_clone_service.generate(
                text=text,
                reference_audio=reference_audio,
            )
            rel_path = result.get('output_path', '')
            if not rel_path:
                logger.error('IndexTTS2 未返回输出路径')
                return False

            from pathlib import Path as _Path
            from backend.config.paths import PROJECT_ROOT
            src_path = PROJECT_ROOT / rel_path
            if not src_path.exists():
                logger.error(f'IndexTTS2 输出文件不存在: {src_path}')
                return False

            # 输出路径以 .mp3 结尾时改为 .wav（IndexTTS2 输出为 WAV）
            out_path = _Path(output_path)
            if out_path.suffix.lower() == '.mp3':
                out_path = out_path.with_suffix('.wav')
            out_path.parent.mkdir(parents=True, exist_ok=True)

            # 复制文件到目标位置
            import shutil as _shutil
            _shutil.copy2(str(src_path), str(out_path))
            logger.info(f'✅ IndexTTS2 克隆语音合成成功: {out_path}')
            return True

        except LocalVoiceCloneError as e:
            logger.error(f'IndexTTS2 克隆失败: {e}')
            return False
        except Exception as e:
            logger.error(f'IndexTTS2 合成异常: {e}', exc_info=True)
            return False

    def _synthesize_volcano(self, text: str, output_path: str,
                            voice: str = '', pitch: Optional[int] = None,
                            advanced_config: Optional[Dict] = None, **kwargs) -> bool:
        """使用火山引擎 TTS 合成语音（委托给 voiceover_service）。"""
        try:
            from backend.services.voiceover_service import VoiceoverService
            from pathlib import Path as _Path
            import shutil as _shutil

            voice_id = voice or ''
            reference_audio = ''
            if isinstance(advanced_config, dict):
                reference_audio = advanced_config.get('reference_audio') or ''
                if not voice_id:
                    voice_id = advanced_config.get('voice_id') or ''
            reference_audio = kwargs.get('reference_audio', reference_audio)

            if not voice_id:
                logger.error('火山引擎 TTS 必须提供 voice_id（音色ID）')
                return False

            vs = VoiceoverService(db_manager=None, socketio=None)
            out_path = _Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)

            result = vs.generate_clone_voiceover(
                text=text,
                reference_audio=reference_audio,
                engine='volcano',
                voice_config={
                    'voice_id': voice_id,
                    'pitch': pitch or 0,
                },
                output_dir=str(out_path.parent),
            )

            result_path_str = ''
            if isinstance(result, dict):
                result_path_str = result.get('output_path') or result.get('audio_path') or ''
            if not result_path_str:
                logger.error('火山引擎 TTS 未返回输出路径')
                return False

            result_path = _Path(result_path_str)
            if not result_path.exists():
                logger.error(f'火山引擎 TTS 输出文件不存在: {result_path}')
                return False

            # 移动到目标位置
            if result_path != out_path:
                _shutil.move(str(result_path), str(out_path))
            logger.info(f'✅ 火山引擎 TTS 合成成功: {out_path}')
            return True

        except Exception as e:
            logger.error(f'火山引擎 TTS 合成异常: {e}', exc_info=True)
            return False

    def _synthesize_voicepro(self, text: str, output_path: str,
                             voice: str = '', pitch: Optional[int] = None,
                             advanced_config: Optional[Dict] = None, **kwargs) -> bool:
        """Voice-Pro / CosyVoice 等外部专业 TTS 引擎 HTTP 合成。
        兼容 OpenAI 兼容（/v1/audio/speech）、原生（/tts）、自定义（/v1/tts）三种接口。"""
        try:
            import urllib.request
            import urllib.error
            import json as _json
            from pathlib import Path as _Path
            out_path = _Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)

            # 1. 解析 endpoint & api_key（优先级：kwargs > advanced_config > engine_settings.json > 环境变量）
            endpoint = ''
            api_key = ''
            for source in (kwargs or {}, advanced_config or {}):
                endpoint = endpoint or (source.get('endpoint') or source.get('base_url') or source.get('voicepro_endpoint') or '').strip().rstrip('/')
                api_key = api_key or (source.get('api_key') or source.get('voicepro_api_key') or '').strip()
            if not endpoint:
                try:
                    from backend.config.paths import PROJECT_ROOT as PR
                    cfg_path = PR / 'storage' / 'engine_settings.json'
                    if cfg_path.exists():
                        saved = _json.loads(cfg_path.read_text(encoding='utf-8'))
                        vs = saved.get('voice-pro') or saved.get('voicepro') or {}
                        endpoint = endpoint or (vs.get('endpoint') or '').strip().rstrip('/')
                        api_key = api_key or (vs.get('api_key') or '').strip()
                except Exception:
                    pass
            if not endpoint:
                # 兜底默认（本地 CosyVoice 常见端口）
                endpoint = 'http://127.0.0.1:7861/v1'

            # 2. 准备 headers
            headers = {'Content-Type': 'application/json'}
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'

            # 3. 构造候选请求（顺序：OpenAI 兼容 > 原生 /tts > /v1/tts）
            speed = float((kwargs or {}).get('speed') or (advanced_config or {}).get('rate') or 1.0)
            voice_id = voice or 'default'
            text_clean = (text or '').strip()
            if not text_clean:
                logger.error('Voice-Pro 合成失败：文本为空')
                return False

            candidates = []
            # (a) OpenAI /v1/audio/speech
            body_a = _json.dumps({
                'model': kwargs.get('model') or advanced_config.get('model') if isinstance(advanced_config, dict) else '' or 'voice-pro-1',
                'input': text_clean,
                'voice': voice_id,
                'response_format': 'mp3',
                'speed': speed,
            }, ensure_ascii=False).encode('utf-8')
            candidates.append(('POST', endpoint + '/v1/audio/speech', body_a, headers))
            # (b) /tts（voice-pro 原生）
            body_b = _json.dumps({
                'text': text_clean,
                'voice': voice_id,
                'speaker': voice_id,
                'format': 'mp3',
                'speed': speed,
                'pitch': pitch or 0,
            }, ensure_ascii=False).encode('utf-8')
            candidates.append(('POST', endpoint + '/tts', body_b, headers))
            # (c) /v1/tts
            candidates.append(('POST', endpoint + '/v1/tts', body_b, headers))
            # (d) /cosyvoice（CosyVoice 原生）
            candidates.append(('POST', endpoint.rstrip('/'), body_b, headers))

            audio_bytes = b''
            last_err = ''
            ok = False
            for method, url, body, hdrs in candidates:
                try:
                    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        raw = resp.read()
                        if 200 <= resp.status < 300 and len(raw) > 512:
                            audio_bytes = raw
                            ok = True
                            break
                        last_err = f'{url} HTTP {resp.status} len={len(raw)}'
                except urllib.error.HTTPError as e:
                    last_err = f'{url} HTTP {e.code}'
                except Exception as e_x:
                    last_err = f'{url} {e_x}'
            if not ok:
                logger.warning(f'Voice-Pro 所有 TTS 接口均失败，最后一条：{last_err}。兜底 Edge-TTS。')
                # 兜底 Edge-TTS
                result = self._run_edge_synthesis(
                    self.synthesize_edge_tts(
                        text_clean, output_path, 'zh-CN-XiaoxiaoNeural', pitch=pitch,
                        advanced_config=advanced_config, **kwargs
                    ),
                    output_path=output_path,
                )
                return result

            # 写文件
            with open(str(out_path), 'wb') as f:
                f.write(audio_bytes)
            if out_path.stat().st_size < 512:
                logger.error(f'Voice-Pro 输出文件过小：{out_path.stat().st_size} bytes')
                return False
            logger.info(f'✅ Voice-Pro 外部引擎合成成功（{len(audio_bytes)} bytes）: {out_path}')
            return True

        except Exception as e:
            logger.error(f'Voice-Pro 合成异常: {e}', exc_info=True)
            try:
                # 兜底 Edge-TTS
                text_clean = (text or '').strip()
                if text_clean:
                    return self._run_edge_synthesis(
                        self.synthesize_edge_tts(text_clean, output_path, 'zh-CN-XiaoxiaoNeural', pitch=pitch),
                        output_path=output_path,
                    )
            except Exception:
                pass
            return False

    def _apply_post_processing(self, output_path: str, advanced_config: Dict) -> bool:
        """
        对生成的音频应用后处理（数据增强、音量变化等）

        Args:
            output_path: 音频文件路径（原地修改）
            advanced_config: 高级配置字典

        Returns:
            是否成功
        """
        try:
            import subprocess
            from pathlib import Path

            audio_file = Path(output_path)
            if not audio_file.exists():
                logger.warning('后处理失败：音频文件不存在')
                return True  # 不影响主流程

            filters = []
            need_processing = False

            # 1) 时间拉伸（语速微调，不改变音高）
            time_stretch = advanced_config.get('time_stretch', 'none')
            if time_stretch and time_stretch != 'none':
                stretch_ranges = {
                    'narrow': (0.9, 1.1),
                    'moderate': (0.8, 1.2),
                    'wide': (0.7, 1.3),
                }
                stretch_range = stretch_ranges.get(time_stretch)
                if stretch_range:
                    import random
                    # 随机选择一个拉伸比例（在范围内轻微变化，模拟自然变化）
                    rate = random.uniform(stretch_range[0], stretch_range[1])
                    if abs(rate - 1.0) > 0.01:
                        filters.append(f'atempo={rate:.3f}')
                        need_processing = True
                        logger.info(f'🎚️ 数据增强-时间拉伸: rate={rate:.3f}')

            # 2) 音调偏移（通过 asetrate + aresample 实现）
            pitch_shift = advanced_config.get('pitch_shift', 'none')
            if pitch_shift and pitch_shift != 'none':
                semitone_map = {
                    'semitone-1': 1.0,
                    'semitone-2': 2.0,
                    'semitone-3': 3.0,
                }
                semitones = semitone_map.get(pitch_shift, 0)
                if semitones > 0:
                    import random
                    # 随机正负偏移
                    direction = random.choice([-1, 1])
                    actual_semitones = semitones * direction * random.uniform(0.5, 1.0)
                    semitone_ratio = 2 ** (actual_semitones / 12.0)
                    filters.append(f'asetrate=24000*{semitone_ratio:.5f}')
                    filters.append('aresample=24000')
                    need_processing = True
                    logger.info(f'🎵 数据增强-音调偏移: {actual_semitones:.2f}半音')

            # 3) 音量变化
            volume_variation = advanced_config.get('volume_variation', 'none')
            if volume_variation and volume_variation != 'none':
                volume_ranges = {
                    'small': (0.8, 1.2),
                    'medium': (0.7, 1.3),
                    'large': (0.6, 1.4),
                }
                vol_range = volume_ranges.get(volume_variation)
                if vol_range:
                    import random
                    volume = random.uniform(vol_range[0], vol_range[1])
                    filters.append(f'volume={volume:.3f}')
                    need_processing = True
                    logger.info(f'🔊 数据增强-音量变化: {volume:.3f}')

            # 4) 噪声添加（使用 FFmpeg 的 afftdn 或生成噪声后混合，这里用简单的 addnoise 方式）
            noise_level = advanced_config.get('noise_level', 'none')
            if noise_level and noise_level != 'none':
                noise_snr = {
                    'light': 25,
                    'moderate': 15,
                    'heavy': 7,
                }
                snr = noise_snr.get(noise_level)
                if snr:
                    # 使用 arnndn 或简单的噪声注入（这里用音量混合方式近似）
                    # 实际项目中建议使用专门的噪声模型
                    filters.append(f'arnndn=m=denoise')  # 占位，实际需模型
                    # 暂时跳过噪声添加（需要噪声文件或模型），用轻微音量变化代替
                    need_processing = False  # 标记为不需要，避免错误
                    logger.info(f'📢 数据增强-噪声: SNR={snr}dB（暂未启用，需噪声模型）')

            if not need_processing or not filters:
                return True  # 不需要后处理

            # 应用 FFmpeg 滤镜
            filter_str = ','.join(filters)
            tmp_path = audio_file.with_suffix(f'.processed{audio_file.suffix}')

            cmd = [
                'ffmpeg', '-y',
                '-i', str(audio_file),
                '-filter:a', filter_str,
                '-codec:a', 'libmp3lame', '-q:a', '2',
                str(tmp_path)
            ]

            logger.info(f'🎛️ 应用音频后处理: {" ".join(cmd)}')
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode == 0 and tmp_path.exists():
                # 替换原文件
                import shutil
                shutil.move(str(tmp_path), str(audio_file))
                logger.info('✅ 音频后处理完成')
                return True
            else:
                logger.warning(f'⚠️ 音频后处理失败: {result.stderr[:200]}')
                # 清理临时文件
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                return True  # 后处理失败不影响主流程

        except Exception as e:
            logger.warning(f'⚠️ 音频后处理异常: {e}')
            return True  # 后处理失败不影响主流程

    def get_available_voices(self, engine: Optional[str] = None) -> List[Dict]:
        """
        获取可用的语音列表

        Args:
            engine: 指定引擎

        Returns:
            语音列表
        """
        engine = engine or self.default_engine

        if engine == 'edge-tts':
            try:
                import edge_tts
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                voices = loop.run_until_complete(edge_tts.list_voices())
                loop.close()

                return [
                    {
                        'name': v['ShortName'],
                        'gender': v['Gender'],
                        'locale': v['Locale']
                    }
                    for v in voices
                ]
            except Exception as e:
                logger.error(f'获取Edge TTS语音列表失败: {e}')
                return []

        elif engine == 'gtts':
            # gTTS支持的语言
            return [
                {'name': 'zh-CN', 'language': 'Chinese (Simplified)'},
                {'name': 'zh-TW', 'language': 'Chinese (Traditional)'},
                {'name': 'en', 'language': 'English'},
                {'name': 'ja', 'language': 'Japanese'},
                {'name': 'ko', 'language': 'Korean'}
            ]

        return []

    def batch_synthesize(self, texts: List[str], output_dir: str,
                        engine: Optional[str] = None,
                        prefix: str = 'audio') -> List[str]:
        """
        批量合成语音

        Args:
            texts: 文本列表
            output_dir: 输出目录
            engine: 指定引擎
            prefix: 文件名前缀

        Returns:
            成功生成的文件路径列表
        """
        output_paths = []
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        for i, text in enumerate(texts):
            output_path = output_dir / f'{prefix}_{i+1:03d}.mp3'
            if self.synthesize(text, str(output_path), engine=engine):
                output_paths.append(str(output_path))

        logger.info(f'✅ 批量合成完成: {len(output_paths)}/{len(texts)}')
        return output_paths
