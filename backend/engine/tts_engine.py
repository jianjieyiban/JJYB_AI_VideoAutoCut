# -*- coding: utf-8 -*-
"""
TTS Engine
文本转语音引擎 - 完整版
支持多种TTS引擎：Edge TTS、gTTS、Coqui TTS等
"""

import logging
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Dict, List

import requests

logger = logging.getLogger(__name__)


class TTSEngine:
    """TTS引擎 - 完整版"""
    
    def __init__(self, default_engine: str = 'pyttsx3'):
        """
        初始化TTS引擎
        
        Args:
            default_engine: 默认引擎（edge-tts/gtts/coqui）
        """
        self.default_engine = default_engine
        self.available_engines = self._check_available_engines()
        logger.info(f'✅ TTS引擎初始化完成，可用引擎: {self.available_engines}')
    
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
            import gtts
            engines.append('gtts')
        except ImportError:
            logger.warning('gTTS未安装')
        
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

            # 检查 Voice-Pro 外部引擎配置（允许脚本为相对 voice_pro_root 的路径）
            try:
                vp_enabled = getattr(cfg.tts_model_config, 'voice_pro_enabled', False)
                vp_root = getattr(cfg.tts_model_config, 'voice_pro_root', '')
                vp_python = getattr(cfg.tts_model_config, 'voice_pro_python_exe', '')
                vp_script = getattr(cfg.tts_model_config, 'voice_pro_tts_script', '')
                if vp_enabled and vp_root and vp_python:
                    root_path = Path(vp_root)
                    root_ok = root_path.exists()
                    py_ok = Path(vp_python).exists()

                    # 与 synthesize_voice_pro 中逻辑保持一致：脚本既可以是绝对路径，也可以是相对 root 的路径
                    script_ok = True
                    if vp_script:
                        script_path = Path(vp_script)
                        if not script_path.is_absolute():
                            script_path = root_path / vp_script
                        script_ok = script_path.exists()

                    if root_ok and py_ok and script_ok:
                        engines.append('voice-pro')
                    else:
                        logger.warning('Voice-Pro 配置不完整或路径不存在，已忽略作为可用TTS引擎')
            except Exception as ve:
                logger.warning(f'检查 Voice-Pro 配置失败: {ve}')
        except Exception as e:
            logger.warning(f'检查Azure TTS配置失败: {e}')
        
        return engines
    
    async def synthesize_edge_tts(self, text: str, output_path: str,
                                  voice: str = 'zh-CN-XiaoxiaoNeural',
                                  rate: str = '+0%', volume: str = '+0%',
                                  pitch: Optional[int] = None) -> bool:
        """
        使用Edge TTS合成语音
        
        Args:
            text: 要合成的文本
            output_path: 输出音频路径
            voice: 语音名称
            rate: 语速调整
            volume: 音量调整
            pitch: 音调调整（半音，-12到+12，转换为Hz）
            
        Returns:
            是否成功
        """
        try:
            import edge_tts
            
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            
            # 将半音转换为Hz（粗略映射：每个半音约等于6-8Hz）
            pitch_str = '+0Hz'
            if pitch is not None and pitch != 0:
                pitch_hz = int(pitch * 7)  # 每半音约7Hz
                pitch_str = f'{pitch_hz:+d}Hz' if pitch_hz != 0 else '+0Hz'
            
            logger.info(f'🎵 Edge TTS参数: voice={voice}, rate={rate}, volume={volume}, pitch={pitch_str}')
            
            communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch_str)
            await communicate.save(output_path)
            
            # 验证文件是否有效（至少1KB，避免损坏的文件）
            out_file = Path(output_path)
            if not out_file.exists():
                logger.error(f'❗ Edge TTS 未生成文件: {output_path}')
                return False
            
            file_size = out_file.stat().st_size
            if file_size < 1024:  # 至少1KB
                logger.error(f'❗ Edge TTS 生成文件过小({file_size} bytes)，可能损坏: {output_path}')
                return False
            
            logger.info(f'✅ Edge TTS合成成功: {output_path} ({file_size} bytes)')
            return True
            
        except Exception as e:
            logger.error(f'❗ Edge TTS合成失败: {e}', exc_info=True)
            return False
    
    def synthesize_pyttsx3(self, text: str, output_path: str,
                           voice: Optional[str] = None,
                           rate: Optional[str] = None,
                           volume: Optional[str] = None) -> bool:
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
                proc = subprocess.run(cmd, capture_output=True)
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
                       voice: Optional[str] = None) -> bool:
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
                        model_name: str = 'tts_models/zh-CN/baker/tacotron2-DDC-GST') -> bool:
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
                             pitch: Optional[int] = None) -> bool:
        """使用 Azure TTS 合成语音（通过 REST API）"""
        try:
            from backend.config.ai_config import get_config_manager
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
            
            # 音调转换：半音转换为百分比或Hz（Azure支持两种格式）
            pitch_str = '+0Hz'
            if pitch is not None and pitch != 0:
                pitch_hz = int(pitch * 7)  # 每半音约7Hz
                pitch_str = f'{pitch_hz:+d}Hz' if pitch_hz != 0 else '+0Hz'
            
            logger.info(f'🎵 Azure TTS参数: voice={voice}, rate={prosody_rate}, pitch={pitch_str}')

            ssml = f"""
<speak version='1.0' xml:lang='zh-CN'>
  <voice name='{voice}'>
    <prosody rate='{prosody_rate}' pitch='{pitch_str}'>
      {text}
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

    def synthesize_voice_pro(self, text: str, output_path: str,
                             voice: str = 'zh-CN-XiaoxiaoNeural',
                             pitch: Optional[int] = None,
                             advanced_config: Optional[Dict] = None,
                             **kwargs) -> bool:
        """使用 Voice-Pro 外部引擎合成语音

        通过 AIConfig 中的 voice_pro_* 配置，调用独立的 Python 3.10 环境与脚本。
        要求外部脚本能够从文本文件读取内容并在给定路径生成音频文件。
        """
        try:
            from backend.config.ai_config import get_config_manager
            cfg = get_config_manager()

            enabled = getattr(cfg.tts_model_config, 'voice_pro_enabled', False)
            root = Path(getattr(cfg.tts_model_config, 'voice_pro_root', '') or '')
            python_exe = Path(getattr(cfg.tts_model_config, 'voice_pro_python_exe', '') or '')
            tts_script = getattr(cfg.tts_model_config, 'voice_pro_tts_script', '') or ''

            if not enabled:
                logger.error('Voice-Pro 外部引擎未启用（voice_pro_enabled=False）')
                return False

            if not root.exists() or not python_exe.exists():
                logger.error(f'Voice-Pro 根目录或 Python 路径不存在: root={root}, python={python_exe}')
                return False

            # 允许脚本路径为相对路径（相对于 root）或绝对路径
            script_path = Path(tts_script)
            if tts_script and not script_path.is_absolute():
                script_path = root / tts_script

            if tts_script and not script_path.exists():
                logger.error(f'Voice-Pro TTS 脚本不存在: {script_path}')
                return False

            out_path = Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)

            # 将文本写入临时文件，避免命令行长度问题和编码问题
            tmp_dir = out_path.parent / 'voice_pro_tmp'
            tmp_dir.mkdir(parents=True, exist_ok=True)
            text_file = tmp_dir / (out_path.stem + '_input.txt')
            text_file.write_text(text, encoding='utf-8')

            # 使用绝对路径传给外部脚本，避免 cwd 在 Voice-Pro 根目录时导致相对路径找不到文件
            out_path_abs = out_path.resolve()
            text_file_abs = text_file.resolve()

            # 简单参数约定：python tts_script --text_file xxx --output_file yyy --voice xxxx
            cmd = [
                str(python_exe),
            ]
            if tts_script:
                cmd.append(str(script_path))
            else:
                logger.error('Voice-Pro 未配置 tts_script，无法构造外部命令')
                return False

            # 将 Edge 风格的 rate（例如 +20%）粗略映射为 CosyVoice2 的 speed（0.5~2.0）
            speed = 1.0
            rate = kwargs.get('rate') or kwargs.get('speed')
            try:
                if isinstance(rate, str) and rate.endswith('%'):
                    pct = int(rate[:-1])
                    speed = 1.0 + pct / 100.0
            except Exception:
                speed = 1.0
            speed = max(0.5, min(2.0, float(speed)))

            # 改进的音色映射：保留原始voice ID，提供更细致的映射
            # Voice-Pro/CosyVoice2 可能支持：中文女声、中文男声、云扬等
            spk_hint = voice or 'zh-CN-XiaoxiaoNeural'
            
            # 尝试精确匹配音色名称
            v_low = str(voice).lower() if voice else ''
            
            # 云扬（Yunyang）- 年轻男声
            if 'yunyang' in v_low or '云扬' in voice:
                spk_hint = '云扬'
                logger.info(f'✅ 匹配到音色: 云扬 (Yunyang - 年轻男声)')
            # 云希（Yunxi）- 成熟男声
            elif 'yunxi' in v_low or '云希' in voice:
                spk_hint = '云希'
                logger.info(f'✅ 匹配到音色: 云希 (Yunxi - 成熟男声)')
            # 云健（Yunjian）- 浑厚男声
            elif 'yunjian' in v_low or '云健' in voice:
                spk_hint = '云健'
                logger.info(f'✅ 匹配到音色: 云健 (Yunjian - 浑厚男声)')
            # 晓晓（Xiaoxiao）- 温柔女声
            elif 'xiaoxiao' in v_low or '晓晓' in voice:
                spk_hint = '晓晓'
                logger.info(f'✅ 匹配到音色: 晓晓 (Xiaoxiao - 温柔女声)')
            # 晓伊（Xiaoyi）- 甜美女声
            elif 'xiaoyi' in v_low or '晓伊' in voice:
                spk_hint = '晓伊'
                logger.info(f'✅ 匹配到音色: 晓伊 (Xiaoyi - 甜美女声)')
            # 泛化匹配：男/女声
            elif any(k in v_low for k in ('male', '男')):
                spk_hint = '中文男'
                logger.info(f'🎙️ 泛化匹配: 中文男声')
            elif any(k in v_low for k in ('female', '女')):
                spk_hint = '中文女'
                logger.info(f'🎙️ 泛化匹配: 中文女声')
            else:
                # 保持原始voice参数，让外部脚本自行处理
                logger.info(f'📋 使用原始音色参数: {spk_hint}')
            
            # 处理情感配置（如果Voice-Pro支持）
            emotion = 'neutral'
            emotion_intensity = 1.0
            if advanced_config:
                emotion = advanced_config.get('emotion_type', 'neutral')
                intensity_map = {'subtle': 0.3, 'moderate': 1.0, 'strong': 1.5, 'extreme': 2.0}
                emotion_intensity = intensity_map.get(advanced_config.get('emotion_intensity', 'moderate'), 1.0)
                logger.info(f'🎭 情感配置: emotion={emotion}, intensity={emotion_intensity}')

            cmd.extend([
                '--text_file', str(text_file_abs),
                '--output_file', str(out_path_abs),
                '--voice', str(spk_hint),
                '--speed', str(speed),
            ])
            
            # 如果支持情感参数，添加到命令行
            if advanced_config and advanced_config.get('emotion_type') != 'neutral':
                cmd.extend(['--emotion', emotion, '--emotion_intensity', str(emotion_intensity)])
            
            # 如果支持音调参数，添加到命令行
            if pitch is not None and pitch != 0:
                cmd.extend(['--pitch', str(pitch)])

            logger.info(f'🎧 调用 Voice-Pro 外部引擎: {" ".join(cmd)}')
            result = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=600
            )

            if result.returncode != 0:
                stderr_preview = (result.stderr or '')[:400]
                logger.error(f'❗ Voice-Pro 外部引擎执行失败，返回码 {result.returncode}，stderr: {stderr_preview}')
                return False

            if not out_path.exists():
                logger.error(f'❗ Voice-Pro 外部引擎未生成目标文件: {out_path}')
                return False

            logger.info(f'✅ Voice-Pro 外部引擎合成成功: {out_path}')
            return True

        except subprocess.TimeoutExpired:
            logger.error('❗ Voice-Pro 外部引擎执行超时')
            return False
        except Exception as e:
            logger.error(f'❗ Voice-Pro 外部引擎调用异常: {e}', exc_info=True)
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
        engine = engine or self.default_engine
        
        if engine not in self.available_engines:
            logger.error(f'引擎 {engine} 不可用')
            return False
        
        # 提取并记录高级配置
        if advanced_config:
            emotion_type = advanced_config.get('emotion_type', 'neutral')
            emotion_intensity = advanced_config.get('emotion_intensity', 'moderate')
            inference_mode = advanced_config.get('inference_mode', 'balanced')
            logger.info(f'🎭 高级配置: emotion={emotion_type}, intensity={emotion_intensity}, inference={inference_mode}')
        
        try:
            if engine == 'edge-tts':
                # Edge TTS需要异步运行
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    self.synthesize_edge_tts(text, output_path, voice, pitch=pitch, **kwargs)
                )
                loop.close()
                return result
            
            elif engine == 'gtts':
                return self.synthesize_gtts(text, output_path, voice=voice, **kwargs)
            
            elif engine == 'coqui':
                return self.synthesize_coqui(text, output_path, **kwargs)
            
            elif engine == 'azure':
                return self.synthesize_azure_tts(text, output_path, voice=voice, pitch=pitch, **kwargs)
            
            elif engine == 'pyttsx3':
                return self.synthesize_pyttsx3(text, output_path, voice=voice, **kwargs)

            elif engine == 'voice-pro':
                return self.synthesize_voice_pro(text, output_path, voice=voice, pitch=pitch, advanced_config=advanced_config, **kwargs)

            else:
                logger.error(f'未知引擎: {engine}')
                return False
                
        except Exception as e:
            logger.error(f'语音合成失败: {e}', exc_info=True)
            return False
    
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
