# -*- coding: utf-8 -*-
"""
Voiceover Service
AI配音服务 - 完整实现
多种AI音色、文字转语音生成、语速语调调整
"""

import logging
import json
import uuid
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from backend.config.paths import PROJECT_ROOT
from backend.engine.audio_processor import AudioProcessor

logger = logging.getLogger(__name__)


class SynthesisPath(str):
    """兼容字符串路径的合成结果，并携带实际引擎元数据。"""

    def __new__(cls, path: str, metadata: Dict):
        instance = super().__new__(cls, path)
        instance.metadata = metadata
        return instance


class VoiceoverService:
    """AI配音服务 - 完整实现"""

    def __init__(self, db_manager, socketio, tts_engine=None):
        """初始化 AI 配音服务，统一使用全局 TTS 引擎。"""
        self.db_manager = db_manager
        self.socketio = socketio
        self._legacy_tts_engine = tts_engine
        self.audio_processor = AudioProcessor()

        # 可用的AI音色列表
        self.available_voices = self._init_voices()

        logger.info(f'✅ AI配音服务初始化完成，可用音色: {len(self.available_voices)}个')

    @property
    def tts_engine(self):
        """始终从全局状态读取当前 TTS 实例，确保设置保存后立即生效。"""
        try:
            from backend.core.global_state import get_global_state
            engine = get_global_state().get_tts_engine()
            if engine is not None:
                return engine
        except Exception as exc:
            logger.warning('获取全局 TTS 引擎失败，使用兼容实例: %s', exc)
        return self._legacy_tts_engine

    def _init_voices(self) -> List[Dict]:
        """初始化可用音色列表"""
        return [
            {
                'id': 'zh-CN-XiaoxiaoNeural',
                'name': '晓晓',
                'gender': 'female',
                'language': 'zh-CN',
                'description': '温柔女声，适合解说',
                'style': ['gentle', 'friendly']
            },
            {
                'id': 'zh-CN-YunxiNeural',
                'name': '云希',
                'gender': 'male',
                'language': 'zh-CN',
                'description': '成熟男声，适合纪录片',
                'style': ['serious', 'calm']
            },
            {
                'id': 'zh-CN-YunyangNeural',
                'name': '云扬',
                'gender': 'male',
                'language': 'zh-CN',
                'description': '年轻男声，适合活力内容',
                'style': ['energetic', 'cheerful']
            },
            {
                'id': 'zh-CN-XiaoyiNeural',
                'name': '晓伊',
                'gender': 'female',
                'language': 'zh-CN',
                'description': '甜美女声，适合轻松内容',
                'style': ['sweet', 'cute']
            },
            {
                'id': 'zh-CN-YunjianNeural',
                'name': '云健',
                'gender': 'male',
                'language': 'zh-CN',
                'description': '浑厚男声，适合严肃内容',
                'style': ['deep', 'authoritative']
            }
        ]

    def _normalize_voice_id(self, voice_id: str) -> str:
        vid = (voice_id or 'zh-CN-XiaoxiaoNeural').strip()
        lower = vid.lower()
        if 'neural' in lower and '-' in lower:
            return vid
        alias = {
            'zh': 'zh-CN-XiaoxiaoNeural',
            'zh-cn': 'zh-CN-XiaoxiaoNeural',
            'en-us': 'en-US-JennyNeural',
            'en-default': 'en-US-JennyNeural',
            'en-newest': 'en-US-JennyNeural',
            'en-au': 'en-AU-NatashaNeural',
            'en-br': 'en-GB-LibbyNeural',
            'en-gb': 'en-GB-LibbyNeural',
            'en-india': 'en-IN-NeerjaNeural',
            'es': 'es-ES-ElviraNeural',
            'fr': 'fr-FR-DeniseNeural',
            'jp': 'ja-JP-NanamiNeural',
            'ja': 'ja-JP-NanamiNeural',
            'kr': 'ko-KR-SunHiNeural',
            'ko': 'ko-KR-SunHiNeural',
        }
        return alias.get(lower, vid)

    @staticmethod
    def _normalize_engine(engine: Optional[str]) -> str:
        aliases = {
            'edge': 'edge-tts',
            'edgetts': 'edge-tts',
            'azure-tts': 'azure',
            'google': 'gtts',
            'google-tts': 'gtts',
            'local': 'pyttsx3',
            'offline': 'pyttsx3',
        }
        normalized = (engine or '').strip().lower()
        return aliases.get(normalized, normalized)

    def _synthesize_with_fallback(self, text: str, output_path: Path, voice_id: str,
                                  requested_engine: Optional[str], rate: str = '+0%',
                                  volume: str = '+0%', pitch=0,
                                  advanced_config: Optional[Dict] = None) -> SynthesisPath:
        engine_requested = self._normalize_engine(requested_engine)

        # 火山引擎语音克隆单独处理（不走 tts_engine）
        if engine_requested == 'volcano':
            try:
                if output_path.exists():
                    output_path.unlink()
                output_path_str = self._synthesize_volcano(
                    text=text,
                    reference_audio='',
                    voice_config={'voice_type': voice_id},
                    output_path=str(output_path),
                )
                if output_path.exists() and output_path.stat().st_size > 0:
                    metadata = {
                        'engine_requested': 'volcano',
                        'engine_used': 'volcano',
                        'fallback_used': False,
                        'fallback_reason': None,
                    }
                    logger.info(f'✅ 火山引擎语音克隆合成成功')
                    return SynthesisPath(str(output_path), metadata)
                raise RuntimeError('火山引擎语音克隆未生成有效音频')
            except Exception as exc:
                logger.error(f'❗ 火山引擎语音克隆合成失败: {exc}', exc_info=True)
                raise RuntimeError(f'火山引擎语音克隆合成失败: {exc}')

        # IndexTTS2 克隆语音也单独处理
        if engine_requested == 'indextts2':
            try:
                reference_audio = (advanced_config or {}).get('reference_audio', '')
                if not reference_audio:
                    raise RuntimeError('请先上传参考音频后再试听 IndexTTS2 克隆语音')
                if output_path.exists():
                    output_path.unlink()
                result = self.generate_clone_voiceover(
                    text=text,
                    reference_audio=reference_audio,
                    engine='indextts2',
                    voice_config=advanced_config or {},
                    output_dir=str(output_path.parent),
                )
                # 复制或移动到目标路径
                result_path = result.get('output_path') or result.get('audio_path')
                if result_path and Path(result_path).exists():
                    import shutil
                    shutil.copy2(str(result_path), str(output_path))
                if output_path.exists() and output_path.stat().st_size > 0:
                    metadata = {
                        'engine_requested': 'indextts2',
                        'engine_used': 'indextts2',
                        'fallback_used': False,
                        'fallback_reason': None,
                    }
                    logger.info(f'✅ IndexTTS2 克隆语音合成成功')
                    return SynthesisPath(str(output_path), metadata)
                raise RuntimeError('IndexTTS2 克隆语音未生成有效音频')
            except Exception as exc:
                logger.error(f'❗ IndexTTS2 克隆语音合成失败: {exc}', exc_info=True)
                raise RuntimeError(f'IndexTTS2 克隆语音合成失败: {exc}')

        # 普通 TTS 引擎走原有逻辑
        available = list(getattr(self.tts_engine, 'available_engines', []) or [])
        default_engine = self._normalize_engine(getattr(self.tts_engine, 'default_engine', ''))
        preferred_engine = engine_requested or default_engine or 'edge-tts'
        candidates = [preferred_engine]
        # 仅在调用方未显式指定引擎时，才允许离线 pyttsx3 兜底。
        if not engine_requested and preferred_engine != 'pyttsx3':
            candidates.append('pyttsx3')

        failure_reasons = []
        for engine in candidates:
            if engine not in available:
                failure_reasons.append(f'{engine}不可用')
                continue

            try:
                if output_path.exists():
                    output_path.unlink()
                kwargs = {
                    'text': text,
                    'output_path': str(output_path),
                    'engine': engine,
                    'voice': voice_id,
                    'advanced_config': advanced_config,
                }
                if engine == 'gtts':
                    from backend.config.ai_config import get_config_manager
                    configured_lang = getattr(
                        get_config_manager().tts_model_config,
                        'gtts_lang',
                        'zh-CN',
                    )
                    kwargs.update(lang=configured_lang or 'zh-CN', slow=False)
                else:
                    kwargs.update(rate=rate, volume=volume, pitch=pitch)
                ok = self.tts_engine.synthesize(**kwargs)
            except Exception as exc:
                logger.error(f'❗ 使用引擎 {engine} 合成失败: {exc}', exc_info=True)
                ok = False
                failure_reasons.append(f'{engine}合成异常: {exc}')

            if ok and output_path.exists() and output_path.stat().st_size > 0:
                fallback_used = engine != preferred_engine
                metadata = {
                    'engine_requested': engine_requested or None,
                    'engine_used': engine,
                    'fallback_used': fallback_used,
                    'fallback_reason': '; '.join(failure_reasons) if fallback_used else None,
                }
                logger.info(f'✅ TTS 合成成功: engine_requested={metadata["engine_requested"]}, engine_used={engine}')
                return SynthesisPath(str(output_path), metadata)

            if not ok:
                failure_reasons.append(f'{engine}合成失败')
            else:
                failure_reasons.append(f'{engine}未生成有效音频文件')

        raise RuntimeError(f'TTS引擎生成失败: {"; ".join(failure_reasons)}')

    def _probe_audio_duration(self, path: Path) -> float:
        """使用 ffprobe 读取音频时长，失败时返回 0。"""
        try:
            cmd = [
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                str(path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                dur = (result.stdout or '').strip()
                if dur:
                    return float(dur)
        except Exception:
            pass
        return 0.0

    def _register_audio_to_project(self, project_id: str, audio_path: Path,
                                    metadata: Optional[Dict] = None) -> None:
        """将生成的音频登记为项目素材，并追加到项目统一 tracks 的音频轨道。"""
        if not audio_path or not audio_path.exists():
            return

        duration = self._probe_audio_duration(audio_path)
        size = audio_path.stat().st_size

        # 1) 登记素材
        self.db_manager.create_material(
            project_id=project_id,
            material_type='audio',
            name=audio_path.name,
            path=str(audio_path),
            size=size,
            duration=duration,
            metadata={
                'source': 'voiceover',
                'engine_used': (metadata or {}).get('engine_used'),
                'engine_requested': (metadata or {}).get('engine_requested'),
                'fallback_used': (metadata or {}).get('fallback_used'),
            }
        )

        # 2) 追加到项目 config.tracks 的音频轨道
        project = self.db_manager.get_project(project_id) or {}
        raw_config = project.get('config')
        if isinstance(raw_config, str):
            try:
                project_config = json.loads(raw_config) if raw_config else {}
            except Exception:
                project_config = {}
        elif isinstance(raw_config, dict):
            project_config = raw_config
        else:
            project_config = {}

        tracks = list(project_config.get('tracks') or [])
        target = None
        for item in tracks:
            if item.get('id') == 'audio-track-1' and item.get('type') == 'audio':
                target = item
                break
        if target is None:
            target = {'id': 'audio-track-1', 'type': 'audio', 'clips': []}
            tracks.append(target)

        clips = list(target.get('clips') or [])
        start_time = float(sum(float(c.get('duration') or 0) for c in clips))
        clips.append({
            'id': f"clip-{uuid.uuid4().hex[:8]}",
            'name': audio_path.name,
            'path': str(audio_path),
            'start': start_time,
            'duration': duration,
        })
        target['clips'] = clips
        project_config['tracks'] = tracks

        # 3) 更新项目结果状态
        raw_result = project.get('result')
        if isinstance(raw_result, str):
            try:
                result_obj = json.loads(raw_result) if raw_result else {}
            except Exception:
                result_obj = {}
        elif isinstance(raw_result, dict):
            result_obj = raw_result
        else:
            result_obj = {}
        result_obj.setdefault('audio_path', str(audio_path))
        result_obj.setdefault('audio_duration', duration)

        self.db_manager.update_project(project_id, {
            'config': project_config,
            'result': result_obj,
        })

    def get_available_voices(self, language: str = None, gender: str = None) -> List[Dict]:
        """
        获取可用音色列表

        Args:
            language: 语言筛选
            gender: 性别筛选

        Returns:
            音色列表
        """
        try:
            voices = self.available_voices

            if language:
                voices = [v for v in voices if v['language'] == language]

            if gender:
                voices = [v for v in voices if v['gender'] == gender]

            logger.info(f'✅ 获取音色列表: {len(voices)}个')

            return voices

        except Exception as e:
            logger.error(f'❗ 获取音色列表失败: {e}', exc_info=True)
            return []

    def create_voiceover_project(self, data: Dict) -> Dict:
        """
        创建AI配音项目

        Args:
            data: 项目数据
                - name: 项目名称
                - text: 配音文本
                - voice_id: 音色ID
                - rate: 语速
                - pitch: 音调

        Returns:
            项目信息
        """
        try:
            logger.info('🎙️ 创建AI配音项目...')

            # 创建项目
            project = self.db_manager.create_project(
                name=data.get('name', 'AI配音项目'),
                project_type='voiceover',
                description='AI配音项目',
                template='voiceover'
            )

            project_id = project['id']

            # 保存配置
            config = {
                'text': data.get('text', ''),
                'voice_id': data.get('voice_id', 'zh-CN-XiaoxiaoNeural'),
                'rate': data.get('rate', '+0%'),  # -50% to +100%
                'pitch': data.get('pitch', '+0Hz'),  # -50Hz to +50Hz
                'volume': data.get('volume', '+0%'),  # -100% to +100%
                'style': data.get('style', 'general')
            }

            self.db_manager.update_project(project_id, {'config': config})

            logger.info(f'✅ AI配音项目创建成功: {project_id}')

            return {
                'project_id': project_id,
                'project': project,
                'config': config
            }

        except Exception as e:
            logger.error(f'❗ 创建AI配音项目失败: {e}', exc_info=True)
            raise

    def generate_voiceover(self, text: str, voice_config: Dict, project_id: Optional[str] = None) -> str:
        """
        生成AI配音

        Args:
            text: 配音文本
            voice_config: 配音配置
                - voice_id: 音色ID
                - rate: 语速
                - pitch: 音调
                - volume: 音量
            project_id: 可选项目ID；提供时会将生成的音频登记为素材并写入项目 tracks

        Returns:
            音频文件路径（SynthesisPath 携带引擎元数据）
        """
        try:
            logger.info(f'🎙️ 生成AI配音: {len(text)}字')

            # 读取基本配置
            voice_id_raw = voice_config.get('voice_id', 'zh-CN-XiaoxiaoNeural')
            voice_id = self._normalize_voice_id(voice_id_raw)
            rate = voice_config.get('rate', '+0%')
            volume = voice_config.get('volume', '+0%')
            pitch = voice_config.get('pitch', 0)

            # 前端传入的引擎类型；未指定时沿用 TTS 引擎默认值。
            raw_engine = voice_config.get('engine')
            requested_engine = self._normalize_engine(raw_engine)

            # 读取高级配置参数（情感TTS、说话人嵌入、音频特征等）
            advanced_config = {
                # 情感TTS配置
                'emotion_type': voice_config.get('emotion_type', 'neutral'),
                'emotion_intensity': voice_config.get('emotion_intensity', 'moderate'),
                'emotion_modeling': voice_config.get('emotion_modeling', 'embedding'),
                'emotion_transfer': voice_config.get('emotion_transfer', 'moderate'),

                # 说话人嵌入配置
                'speaker_embedding_model': voice_config.get('speaker_embedding_model', 'ecapa-tdnn'),
                'embedding_dim': voice_config.get('embedding_dim', 256),
                'similarity_metric': voice_config.get('similarity_metric', 'cosine'),
                'embedding_fusion': voice_config.get('embedding_fusion', 'concat'),

                # 音频特征提取配置
                'audio_feature_type': voice_config.get('audio_feature_type', 'mel-spectrogram'),
                'mel_bins': voice_config.get('mel_bins', 80),
                'fft_size': voice_config.get('fft_size', 1024),
                'hop_length': voice_config.get('hop_length', 256),

                # 数据增强配置
                'time_stretch': voice_config.get('time_stretch', 'moderate'),
                'pitch_shift': voice_config.get('pitch_shift', 'semitone-2'),
                'noise_level': voice_config.get('noise_level', 'light'),
                'volume_variation': voice_config.get('volume_variation', 'small'),

                # 技术性能优化
                'inference_mode': voice_config.get('inference_mode', 'balanced'),
                'compute_device': voice_config.get('compute_device', 'auto'),
                'batch_size': voice_config.get('batch_size', 8),
                'cache_strategy': voice_config.get('cache_strategy', 'smart')
            }

            logger.info(
                '📋 配音配置: engine_requested=%s, voice=%s, rate=%s, volume=%s, emotion=%s',
                requested_engine or 'default',
                voice_id,
                rate,
                volume,
                advanced_config['emotion_type'],
            )

            # 生成输出路径（统一到 PROJECT_ROOT/output/audios）
            output_dir = PROJECT_ROOT / 'output' / 'audios'
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"voiceover_{datetime.now().strftime('%Y%m%d%H%M%S')}.mp3"

            result = self._synthesize_with_fallback(
                text=text,
                output_path=output_path,
                voice_id=voice_id,
                requested_engine=raw_engine,
                rate=rate,
                volume=volume,
                pitch=pitch,
                advanced_config=advanced_config,
            )
            logger.info(f'✅ AI配音生成成功: {result}')

            # 若提供了项目ID，将生成的音频登记为素材并写入项目统一 tracks
            if project_id:
                try:
                    self._register_audio_to_project(project_id, output_path, result.metadata)
                except Exception as perr:
                    logger.warning(f'⚠️ 配音写入项目素材/tracks 失败（不影响生成结果）: {perr}')

            return result

        except Exception as e:
            logger.error(f'❗ 生成AI配音失败: {e}', exc_info=True)
            raise

    def batch_generate_voiceovers(self, texts: List[str], voice_config: Dict) -> List[str]:
        """
        批量生成AI配音

        Args:
            texts: 文本列表
            voice_config: 配音配置

        Returns:
            音频文件路径列表
        """
        try:
            logger.info(f'🎙️ 批量生成AI配音: {len(texts)}段')

            output_paths = []

            for i, text in enumerate(texts):
                try:
                    output_path = self.generate_voiceover(text, voice_config)
                    output_paths.append(output_path)

                    # 发送进度更新
                    progress = (i + 1) / len(texts) * 100
                    self.socketio.emit('voiceover_progress', {
                        'progress': progress,
                        'current': i + 1,
                        'total': len(texts)
                    })

                except Exception as e:
                    logger.error(f'❗ 生成第{i+1}段配音失败: {e}')
                    output_paths.append(None)

            success_count = len([p for p in output_paths if p])
            logger.info(f'✅ 批量配音完成: {success_count}/{len(texts)}')

            return output_paths

        except Exception as e:
            logger.error(f'❗ 批量生成配音失败: {e}', exc_info=True)
            raise

    def adjust_voice_parameters(self, audio_path: str, adjustments: Dict) -> str:
        """
        调整语音参数

        Args:
            audio_path: 原始音频路径
            adjustments: 调整参数
                - speed: 速度调整（0.5-2.0）
                - pitch: 音调调整（-12 to +12 半音）
                - volume: 音量调整（0.0-2.0）

        Returns:
            调整后的音频路径
        """
        try:
            logger.info(f'🔧 调整语音参数: {audio_path}')

            if not audio_path:
                raise ValueError('audio_path 不能为空')

            # 提取调整参数并限制范围
            try:
                speed = float(adjustments.get('speed', 1.0) or 1.0)
            except Exception:
                speed = 1.0
            speed = max(0.5, min(2.0, speed))

            try:
                pitch = float(adjustments.get('pitch', 0.0) or 0.0)
            except Exception:
                pitch = 0.0
            pitch = max(-12.0, min(12.0, pitch))  # 以半音为单位

            try:
                volume = float(adjustments.get('volume', 1.0) or 1.0)
            except Exception:
                volume = 1.0
            volume = max(0.0, min(2.0, volume))

            # 如果没有任何变化，直接返回原路径
            if abs(speed - 1.0) < 1e-3 and abs(pitch) < 1e-3 and abs(volume - 1.0) < 1e-3:
                logger.info('ℹ️ 未检测到参数变化，返回原始音频')
                return audio_path

            input_path = Path(audio_path)
            if not input_path.is_absolute():
                input_path = PROJECT_ROOT / audio_path
            if not input_path.exists():
                raise FileNotFoundError(f'音频文件不存在: {input_path}')

            output_dir = PROJECT_ROOT / 'output' / 'audios'
            output_dir.mkdir(parents=True, exist_ok=True)
            ext = input_path.suffix or '.mp3'
            output_path = output_dir / f"{input_path.stem}_adjusted_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"

            # 构建音频滤镜：优先考虑音量和语速，音高通过 asetrate 粗略调整
            filters = []

            if abs(pitch) > 1e-3:
                # 简单基于半音的移调：每个半音倍率为 2^(n/12)
                semitone_ratio = 2 ** (pitch / 12.0)
                # 固定采样率为 44100Hz，先改变采样率再重采样回 44100
                filters.append(f'asetrate=44100*{semitone_ratio:.5f}')
                filters.append('aresample=44100')

            if abs(speed - 1.0) > 1e-3:
                # atempo 只支持 0.5-2.0，前面已经做过裁剪
                filters.append(f'atempo={speed:.3f}')

            # 音量调整
            filters.append(f'volume={volume:.3f}')

            filter_str = ','.join(filters)

            cmd = [
                'ffmpeg',
                '-y',
                '-i', str(input_path),
                '-filter:a', filter_str,
                str(output_path)
            ]

            logger.info(f'🎛️ FFmpeg 音频参数调整命令: {" ".join(cmd)}')
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                logger.error(f'❗ 音频参数调整失败: {result.stderr}')
                raise RuntimeError(f'音频参数调整失败: {result.stderr[:200]}')

            logger.info(f'✅ 参数调整完成: {output_path}')

            return str(output_path)

        except Exception as e:
            logger.error(f'❗ 调整参数失败: {e}', exc_info=True)
            raise

    def merge_voiceovers(self, audio_paths: List[str], output_path: str = None) -> str:
        """
        合并多段配音

        Args:
            audio_paths: 音频文件路径列表
            output_path: 输出路径

        Returns:
            合并后的音频路径
        """
        try:
            logger.info(f'🔗 合并配音: {len(audio_paths)}段')

            if not audio_paths:
                raise ValueError('audio_paths 不能为空')

            # 过滤无效路径
            valid_paths = [str(p) for p in audio_paths if p]
            if not valid_paths:
                raise ValueError('没有可用的音频路径用于合并')

            if not output_path:
                output_dir = PROJECT_ROOT / 'output' / 'audios'
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = str(output_dir / f"merged_{datetime.now().strftime('%Y%m%d%H%M%S')}.mp3")

            # 使用 AudioProcessor 进行实际合并
            ok = self.audio_processor.merge_audios(valid_paths, output_path)
            if not ok:
                raise RuntimeError('音频合并失败')

            logger.info(f'✅ 配音合并完成: {output_path}')

            return output_path

        except Exception as e:
            logger.error(f'❗ 合并配音失败: {e}', exc_info=True)
            raise

    def preview_voice(self, voice_id: str, sample_text: str = None, engine: Optional[str] = None,
                      advanced_config: Optional[Dict] = None) -> str:
        """预览音色

        Args:
            voice_id: 音色ID
            sample_text: 示例文本
            engine: 前端可选指定的TTS引擎标识（edge-tts / azure / gtts / pyttsx3 等）
            advanced_config: 额外配置（如克隆语音的参考音频等）

        Returns:
            预览音频路径
        """
        try:
            logger.info(f'👂 预览音色: {voice_id}, engine={engine}')
            # 自动清理过期的预览缓存，避免长时间占用磁盘
            try:
                self.cleanup_preview_cache(max_age_hours=24)
            except Exception as cleanup_err:
                logger.warning(f'预览缓存清理失败（忽略，不影响本次生成）: {cleanup_err}')

            if not sample_text:
                sample_text = "大家好，这是音色预览示例。"

            output_dir = PROJECT_ROOT / 'output' / 'previews'
            output_dir.mkdir(parents=True, exist_ok=True)
            # 克隆语音的预览文件名加上引擎前缀，避免冲突
            safe_engine = (engine or 'default').replace('/', '_').replace('\\', '_')
            output_path = output_dir / f"preview_{safe_engine}_{voice_id[:50]}.mp3"

            result = self._synthesize_with_fallback(
                text=sample_text,
                output_path=output_path,
                voice_id=self._normalize_voice_id(voice_id),
                requested_engine=engine,
                advanced_config=advanced_config,
            )
            logger.info(f'✅ 音色预览生成: {result}, engine={result.metadata["engine_used"]}')
            return result

        except Exception as e:
            logger.error(f'❗ 预览音色失败: {e}', exc_info=True)
            raise

    def cleanup_preview_cache(self, max_age_hours: int = 24) -> int:
        """清理过期的预览音频缓存文件

        Args:
            max_age_hours: 保留的最长小时数，早于该时间的预览文件会被删除

        Returns:
            实际删除的文件个数
        """
        try:
            preview_dir = PROJECT_ROOT / 'output' / 'previews'
            if not preview_dir.exists():
                return 0

            cutoff_ts = datetime.now().timestamp() - max_age_hours * 3600
            deleted = 0

            for f in preview_dir.glob('preview_*.mp3'):
                try:
                    stat = f.stat()
                    if stat.st_mtime < cutoff_ts:
                        f.unlink()
                        deleted += 1
                except Exception as fe:
                    logger.warning(f'❗ 删除预览缓存文件失败: {f}: {fe}')

            if deleted:
                logger.info(f'🧹 预览缓存清理完成，删除 {deleted} 个过期文件')
            return deleted
        except Exception as e:
            logger.error(f'❗ 预览缓存清理过程异常: {e}', exc_info=True)
            return 0

    # ================================================================== #
    # 升级能力 1：克隆语音生成（以克隆语音为主，全面配置市面热门方案）
    # ================================================================== #
    def list_clone_engines(self) -> List[Dict]:
        """列出已实现的克隆语音引擎及其真实就绪状态。

        包含本地 IndexTTS2，以及 Fish Audio、MiniMax、火山引擎和
        Azure Custom Voice 云端服务；未实现的本地引擎不会对外声明。
        """
        engines: List[Dict] = []

        # 1) IndexTTS2 本地
        try:
            from backend.services.local_voice_clone_service import local_voice_clone_service
            status = local_voice_clone_service.status()
            engines.append({
                'id': 'indextts2',
                'name': 'IndexTTS2',
                'type': 'local',
                'ready': status.get('ready', False),
                'reason': status.get('reason'),
                'needs_reference_audio': True,
                'needs_consent': True,
                'description': '本地零样本声音复刻，需 Python 3.10 + 完整模型权重',
            })
        except Exception as e:
            logger.warning(f'⚠️ IndexTTS2 状态检测失败: {e}')
            engines.append({
                'id': 'indextts2', 'name': 'IndexTTS2', 'type': 'local',
                'ready': False, 'reason': f'检测异常: {e}',
                'needs_reference_audio': True, 'needs_consent': True,
            })

        # 2) Fish Audio 云端 API
        try:
            from backend.config.ai_config import get_config_manager
            cfg = get_config_manager()
            fish_key = getattr(cfg.tts_model_config, 'fish_audio_api_key', '') or ''
            engines.append({
                'id': 'fish-audio', 'name': 'Fish Audio', 'type': 'cloud',
                'ready': bool(fish_key),
                'reason': None if fish_key else '未配置 fish_audio_api_key',
                'needs_reference_audio': True,
                'needs_consent': True,
                'description': 'Fish Audio 云端语音克隆，支持文本转语音与音色克隆',
            })
        except Exception as e:
            engines.append({
                'id': 'fish-audio', 'name': 'Fish Audio', 'type': 'cloud',
                'ready': False, 'reason': f'检测异常: {e}',
                'needs_reference_audio': True, 'needs_consent': True,
            })

        # 4) MiniMax T2A 云端 API
        try:
            from backend.config.ai_config import get_config_manager
            cfg = get_config_manager()
            mm_key = getattr(cfg.tts_model_config, 'minimax_api_key', '') or ''
            engines.append({
                'id': 'minimax', 'name': 'MiniMax T2A', 'type': 'cloud',
                'ready': bool(mm_key),
                'reason': None if mm_key else '未配置 minimax_api_key',
                'needs_reference_audio': True,
                'needs_consent': True,
                'description': 'MiniMax 语音大模型，支持声音复刻与情感配音',
            })
        except Exception as e:
            engines.append({
                'id': 'minimax', 'name': 'MiniMax T2A', 'type': 'cloud',
                'ready': False, 'reason': f'检测异常: {e}',
                'needs_reference_audio': True, 'needs_consent': True,
            })

        # 5) 火山引擎语音克隆
        try:
            from backend.config.ai_config import get_config_manager
            cfg = get_config_manager()
            vol_key = getattr(cfg.tts_model_config, 'volcano_api_key', '') or ''
            engines.append({
                'id': 'volcano', 'name': '火山引擎语音克隆', 'type': 'cloud',
                'ready': bool(vol_key),
                'reason': None if vol_key else '未配置 volcano_api_key',
                'needs_reference_audio': True,
                'needs_consent': True,
                'description': '字节火山引擎声音复刻，需已开通声音复刻服务',
            })
        except Exception as e:
            engines.append({
                'id': 'volcano', 'name': '火山引擎语音克隆', 'type': 'cloud',
                'ready': False, 'reason': f'检测异常: {e}',
                'needs_reference_audio': True, 'needs_consent': True,
            })

        # 6) Azure Custom Voice
        try:
            from backend.config.ai_config import get_config_manager
            cfg = get_config_manager()
            az_key = getattr(cfg.tts_model_config, 'azure_tts_key', '') or ''
            engines.append({
                'id': 'azure-custom', 'name': 'Azure Custom Voice', 'type': 'cloud',
                'ready': bool(az_key),
                'reason': None if az_key else '未配置 azure_tts_key',
                'needs_reference_audio': True,
                'needs_consent': True,
                'description': 'Azure 自定义神经语音，需在 Azure 门户训练声音模型',
            })
        except Exception as e:
            engines.append({
                'id': 'azure-custom', 'name': 'Azure Custom Voice', 'type': 'cloud',
                'ready': False, 'reason': f'检测异常: {e}',
                'needs_reference_audio': True, 'needs_consent': True,
            })

        return engines

    def generate_clone_voiceover(self,
                                  text: str,
                                  reference_audio: str,
                                  engine: str = 'indextts2',
                                  voice_config: Optional[Dict] = None,
                                  project_id: Optional[str] = None,
                                  output_dir: Optional[str] = None) -> Dict:
        """生成克隆语音

        Args:
            text: 要合成的文本
            reference_audio: 参考音频路径（必须位于项目 uploads 目录内）
            engine: 克隆引擎 id（indextts2/fish-audio/minimax/volcano/azure-custom）
            voice_config: 可选额外配置（speed/pitch/volume/emotion 等）
            project_id: 项目ID（可选，提供则登记为素材）
            output_dir: 指定输出目录（可选，绝对路径，需有写权限）

        Returns:
            dict: 包含 output_path / output_url / engine_used / fallback_used 等
        """
        try:
            logger.info(f'🎙️ 克隆语音生成: engine={engine}, text_len={len(text)}')

            if not text or not text.strip():
                raise ValueError('text 不能为空')
            if not reference_audio:
                raise ValueError('reference_audio 不能为空')

            voice_config = voice_config or {}
            engine = (engine or 'indextts2').strip().lower()
            output_path_str = ''

            # ---------- 1) IndexTTS2 本地克隆 ----------
            if engine in ('indextts2', 'index-tts', 'index_tts'):
                from backend.services.local_voice_clone_service import (
                    local_voice_clone_service, LocalVoiceCloneError,
                )
                ref_audio = local_voice_clone_service.resolve_upload_audio(reference_audio)
                result = local_voice_clone_service.generate(text, ref_audio)
                output_path_str = str(PROJECT_ROOT / result['output_path'])
                metadata = {
                    'engine_requested': 'indextts2',
                    'engine_used': 'IndexTTS2',
                    'fallback_used': False,
                    'fallback_reason': None,
                    'device_used': result.get('device_used', 'cpu'),
                }

            # ---------- 2) Fish Audio 云端 API ----------
            elif engine in ('fish-audio', 'fish_audio', 'fish'):
                output_path_str = self._synthesize_fish_audio(
                    text=text,
                    reference_audio=reference_audio,
                    voice_config=voice_config,
                    output_dir=output_dir,
                )
                metadata = {
                    'engine_requested': 'fish-audio',
                    'engine_used': 'fish-audio',
                    'fallback_used': False,
                    'fallback_reason': None,
                }

            # ---------- 4) MiniMax T2A 云端 API ----------
            elif engine in ('minimax', 'minimax-t2a'):
                output_path_str = self._synthesize_minimax(
                    text=text,
                    reference_audio=reference_audio,
                    voice_config=voice_config,
                    output_dir=output_dir,
                )
                metadata = {
                    'engine_requested': 'minimax',
                    'engine_used': 'minimax',
                    'fallback_used': False,
                    'fallback_reason': None,
                }

            # ---------- 5) 火山引擎语音克隆 ----------
            elif engine in ('volcano', 'volcano-voice-clone'):
                output_path_str = self._synthesize_volcano(
                    text=text,
                    reference_audio=reference_audio,
                    voice_config=voice_config,
                    output_dir=output_dir,
                )
                metadata = {
                    'engine_requested': 'volcano',
                    'engine_used': 'volcano',
                    'fallback_used': False,
                    'fallback_reason': None,
                }

            # ---------- 6) Azure Custom Voice ----------
            elif engine in ('azure-custom', 'azure_custom'):
                output_path_str = self._synthesize_azure_custom(
                    text=text,
                    reference_audio=reference_audio,
                    voice_config=voice_config,
                    output_dir=output_dir,
                )
                metadata = {
                    'engine_requested': 'azure-custom',
                    'engine_used': 'azure-custom',
                    'fallback_used': False,
                    'fallback_reason': None,
                }

            else:
                raise ValueError(f'不支持的克隆引擎: {engine}')

            # ---------- 输出路径处理 / 复制到指定目录 ----------
            out_path = Path(output_path_str).resolve()
            if output_dir and engine == 'indextts2':
                # IndexTTS2 输出固定在 temp/outputs/local_voice_clone，需复制
                target_dir = Path(output_dir)
                if not target_dir.is_absolute():
                    target_dir = PROJECT_ROOT / target_dir
                target_dir.mkdir(parents=True, exist_ok=True)
                target_file = target_dir / f"clone_{datetime.now().strftime('%Y%m%d%H%M%S')}.wav"
                import shutil as _shutil
                _shutil.copy2(str(out_path), str(target_file))
                out_path = target_file

            # 计算 URL（仅当文件位于项目内时）
            try:
                rel = out_path.relative_to(PROJECT_ROOT)
                rel_str = str(rel).replace('\\', '/')
                audio_url = '/' + rel_str.lstrip('/')
            except Exception:
                rel_str = str(out_path)
                audio_url = None

            # ---------- 登记到项目素材 ----------
            if project_id:
                try:
                    self._register_audio_to_project(project_id, out_path, metadata)
                except Exception as perr:
                    logger.warning(f'⚠️ 克隆配音写入项目素材失败（不影响生成结果）: {perr}')

            logger.info(f'✅ 克隆语音生成成功: engine={metadata["engine_used"]}, output={out_path}')
            return {
                'audio_path': rel_str,
                'audio_url': audio_url,
                'absolute_path': str(out_path),
                'project_id': project_id,
                **metadata,
            }
        except Exception as e:
            logger.error(f'❗ 克隆语音生成失败: {e}', exc_info=True)
            raise

    # ---------- 云端克隆 API 实现 ----------
    def _ensure_clone_output_path(self, output_dir: Optional[str], suffix: str = '.mp3') -> Path:
        """生成克隆输出文件路径。优先使用调用方指定的目录。"""
        if output_dir:
            base = Path(output_dir)
            if not base.is_absolute():
                base = PROJECT_ROOT / base
        else:
            base = PROJECT_ROOT / 'output' / 'audios'
        base.mkdir(parents=True, exist_ok=True)
        return base / f"clone_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}{suffix}"

    def _read_audio_bytes(self, audio_path: str) -> bytes:
        """读取参考音频字节（用于云端 API 上传）"""
        p = Path(audio_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / audio_path
        if not p.exists():
            raise FileNotFoundError(f'参考音频不存在: {p}')
        return p.read_bytes()

    def _synthesize_fish_audio(self, text: str, reference_audio: str,
                                voice_config: Dict, output_dir: Optional[str]) -> str:
        """调用 Fish Audio 云端 API 进行声音克隆"""
        import requests
        from backend.config.ai_config import get_config_manager
        cfg = get_config_manager()
        api_key = getattr(cfg.tts_model_config, 'fish_audio_api_key', '') or ''
        if not api_key:
            raise RuntimeError('未配置 fish_audio_api_key，无法使用 Fish Audio 克隆')
        base_url = getattr(cfg.tts_model_config, 'fish_audio_base_url', '') or 'https://api.fish.audio/v1'

        out_path = self._ensure_clone_output_path(output_dir, '.mp3')
        ref_bytes = self._read_audio_bytes(reference_audio)

        # Fish Audio /v1/tts 接口：通过 reference_audio 字段上传参考音频
        files = {
            'text': (None, text),
            'reference_audio': ('ref.wav', ref_bytes, 'audio/wav'),
        }
        # 可选参数
        speed = voice_config.get('speed', 1.0)
        try:
            speed = float(speed)
        except Exception:
            speed = 1.0
        files['speed'] = (None, str(speed))

        headers = {
            'Authorization': f'Bearer {api_key}',
        }
        url = base_url.rstrip('/') + '/tts'
        logger.info(f'🐟 调用 Fish Audio: {url}')
        resp = requests.post(url, headers=headers, files=files, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(f'Fish Audio 返回 {resp.status_code}: {resp.text[:300]}')
        out_path.write_bytes(resp.content)
        if out_path.stat().st_size < 1024:
            raise RuntimeError('Fish Audio 返回内容过小，可能未生成有效音频')
        return str(out_path)

    def _synthesize_minimax(self, text: str, reference_audio: str,
                             voice_config: Dict, output_dir: Optional[str]) -> str:
        """调用 MiniMax T2A 云端 API 进行声音克隆（语音复刻 v2）"""
        import requests
        from backend.config.ai_config import get_config_manager
        cfg = get_config_manager()
        api_key = getattr(cfg.tts_model_config, 'minimax_api_key', '') or ''
        group_id = getattr(cfg.tts_model_config, 'minimax_group_id', '') or ''
        if not api_key or not group_id:
            raise RuntimeError('未配置 minimax_api_key 或 minimax_group_id，无法使用 MiniMax 克隆')
        base_url = getattr(cfg.tts_model_config, 'minimax_base_url', '') or 'https://api.minimax.chat/v1'

        out_path = self._ensure_clone_output_path(output_dir, '.mp3')

        # 第一步：上传参考音频到 MiniMax 文件接口，获取 fileId
        ref_bytes = self._read_audio_bytes(reference_audio)
        upload_url = base_url.rstrip('/') + '/files/upload'
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'multipart/form-data',
        }
        files = {
            'file': ('ref.wav', ref_bytes, 'audio/wav'),
        }
        logger.info(f'🎙️ 上传参考音频到 MiniMax: {upload_url}')
        up_resp = requests.post(upload_url, headers=headers, files=files, timeout=60)
        if up_resp.status_code != 200:
            raise RuntimeError(f'MiniMax 文件上传失败 {up_resp.status_code}: {up_resp.text[:300]}')
        up_data = up_resp.json()
        file_id = (up_data.get('file') or {}).get('file_id') or up_data.get('file_id')
        if not file_id:
            raise RuntimeError(f'MiniMax 文件上传返回无 file_id: {up_data}')

        # 第二步：调用声音复刻接口 T2A_v2
        t2a_url = base_url.rstrip('/') + f'/t2a_v2?GroupId={group_id}'
        payload = {
            'model': 'speech-02-hd',
            'text': text,
            'voice_setting': {
                'voice_id': 'voice_clone',
                'speed': float(voice_config.get('speed', 1.0)),
                'vol': float(voice_config.get('volume', 1.0)),
                'pitch': int(voice_config.get('pitch', 0)),
            },
            'audio_setting': {
                'sample_rate': 24000,
                'format': 'mp3',
            },
            'pronunciation_dict': {'tone': []},
            'timber_weights': [
                {
                    'voice_id': 'voice_clone',
                    'weight': 1,
                    'voice_file_id': file_id,
                }
            ],
        }
        headers2 = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        logger.info(f'🎙️ 调用 MiniMax T2A: {t2a_url}')
        resp = requests.post(t2a_url, headers=headers2, json=payload, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(f'MiniMax T2A 返回 {resp.status_code}: {resp.text[:300]}')
        data = resp.json()
        # MiniMax 返回 hex 格式音频
        audio_hex = (data.get('data') or {}).get('audio') or data.get('audio')
        if not audio_hex:
            raise RuntimeError(f'MiniMax T2A 未返回音频: {data}')
        import binascii
        out_path.write_bytes(binascii.unhexlify(audio_hex))
        if out_path.stat().st_size < 1024:
            raise RuntimeError('MiniMax T2A 返回音频过小')
        return str(out_path)

    def _synthesize_volcano(self, text: str, reference_audio: str,
                             voice_config: Dict, output_dir: Optional[str]) -> str:
        """调用火山引擎语音克隆服务（声音复刻 2.0 接口）

        注意：完整的火山引擎声音复刻流程包含「上传参考音频 → 训练 → 调用」，
        此处实现的是已训练后调用的简版流程。如需训练新音色，请前往火山控制台。
        """
        import requests
        from backend.config.ai_config import get_config_manager
        cfg = get_config_manager()
        api_key = getattr(cfg.tts_model_config, 'volcano_api_key', '') or ''
        app_id = getattr(cfg.tts_model_config, 'volcano_app_id', '') or ''
        voice_type = voice_config.get('voice_type') or getattr(cfg.tts_model_config, 'volcano_voice_type', '') or ''
        if not api_key or not app_id:
            raise RuntimeError('未配置 volcano_api_key 或 volcano_app_id')
        if not voice_type:
            raise RuntimeError('未指定 voice_type（已训练的火山声音复刻音色 ID）')

        out_path = self._ensure_clone_output_path(output_dir, '.mp3')
        url = 'https://openspeech.bytedance.com/api/v1/tts'
        payload = {
            'app': {
                'appid': app_id,
                'token': api_key,
                'cluster': 'volcano_tts',
            },
            'user': {'uid': 'jjyb_ai'},
            'audio': {
                'voice_type': voice_type,
                'encoding': 'mp3',
                'speed_ratio': float(voice_config.get('speed', 1.0)),
                'volume_ratio': float(voice_config.get('volume', 1.0)),
                'pitch_ratio': float(voice_config.get('pitch', 1.0)),
            },
            'request': {
                'reqid': uuid.uuid4().hex,
                'text': text,
                'text_type': 'plain',
                'operation': 'query',
            },
        }
        headers = {'Content-Type': 'application/json'}
        logger.info(f'🌋 调用火山引擎 TTS: voice_type={voice_type}')
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f'火山 TTS 返回 {resp.status_code}: {resp.text[:300]}')
        data = resp.json()
        if data.get('code') != 3000:
            raise RuntimeError(f'火山 TTS 业务错误: code={data.get("code")}, message={data.get("message")}')
        import binascii
        audio_data = data.get('data')
        if not audio_data:
            raise RuntimeError('火山 TTS 未返回音频数据')
        out_path.write_bytes(binascii.unhexlify(audio_data))
        if out_path.stat().st_size < 1024:
            raise RuntimeError('火山 TTS 返回音频过小')
        return str(out_path)

    def _synthesize_azure_custom(self, text: str, reference_audio: str,
                                  voice_config: Dict, output_dir: Optional[str]) -> str:
        """调用 Azure Custom Voice（已部署的自定义音色）

        Azure 自定义神经语音需要先在 Azure 门户训练并部署模型，
        部署后会得到一个 endpointId，调用时将其作为 voice 名称传入。
        """
        from backend.config.ai_config import get_config_manager
        cfg = get_config_manager()
        api_key = getattr(cfg.tts_model_config, 'azure_tts_key', '') or ''
        region = getattr(cfg.tts_model_config, 'azure_tts_region', '') or 'eastasia'
        endpoint_id = voice_config.get('endpoint_id') or getattr(cfg.tts_model_config, 'azure_custom_endpoint_id', '') or ''
        if not api_key:
            raise RuntimeError('未配置 azure_tts_key')
        if not endpoint_id:
            raise RuntimeError('未指定 endpoint_id（Azure Custom Voice 部署后的 endpoint ID）')

        out_path = self._ensure_clone_output_path(output_dir, '.mp3')
        # Azure TTS REST 接口
        url = f'https://{region}.tts.speech.microsoft.com/cognitiveservices/v1'
        ssml = f"""
<speak version='1.0' xml:lang='zh-CN'>
  <voice name='{endpoint_id}'>
    {text}
  </voice>
</speak>
""".strip()
        headers = {
            'Ocp-Apim-Subscription-Key': api_key,
            'Content-Type': 'application/ssml+xml',
            'X-Microsoft-OutputFormat': 'audio-16khz-32kbitrate-mono-mp3',
            'User-Agent': 'JJYB_AI_TTS',
        }
        import requests as _req
        logger.info(f'☁️ 调用 Azure Custom Voice: endpoint={endpoint_id}')
        resp = _req.post(url, headers=headers, data=ssml.encode('utf-8'), timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f'Azure Custom Voice 返回 {resp.status_code}: {resp.text[:300]}')
        out_path.write_bytes(resp.content)
        if out_path.stat().st_size < 1024:
            raise RuntimeError('Azure Custom Voice 返回内容过小')
        return str(out_path)

    # ================================================================== #
    # 升级能力 2：下载到指定文件夹
    # ================================================================== #
    def download_audio_to_folder(self, audio_path: str, target_dir: str,
                                  filename: Optional[str] = None) -> Dict:
        """将已生成的音频文件复制到用户指定的文件夹

        Args:
            audio_path: 源音频路径（项目内相对路径或绝对路径）
            target_dir: 目标文件夹绝对路径（不存在则创建）
            filename: 可选目标文件名（不指定则使用源文件名+时间戳）

        Returns:
            dict: 包含 saved_path / file_size 等
        """
        try:
            if not audio_path:
                raise ValueError('audio_path 不能为空')
            if not target_dir:
                raise ValueError('target_dir 不能为空')

            src = Path(audio_path)
            if not src.is_absolute():
                src = PROJECT_ROOT / audio_path
            if not src.exists():
                raise FileNotFoundError(f'源音频不存在: {src}')

            target = Path(target_dir)
            if not target.is_absolute():
                target = PROJECT_ROOT / target
            target.mkdir(parents=True, exist_ok=True)

            # 写权限检测
            test_file = target / f'.jjyb_write_test_{uuid.uuid4().hex[:6]}'
            try:
                test_file.write_text('ok', encoding='utf-8')
                test_file.unlink()
            except Exception as we:
                raise RuntimeError(f'目标文件夹无写权限: {target} ({we})')

            if not filename:
                stem = src.stem
                ext = src.suffix or '.mp3'
                filename = f"{stem}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
            else:
                # 防止路径穿越
                filename = Path(filename).name

            target_file = target / filename
            import shutil as _shutil
            _shutil.copy2(str(src), str(target_file))

            logger.info(f'✅ 音频已保存到指定文件夹: {target_file}')
            return {
                'saved_path': str(target_file),
                'saved_dir': str(target),
                'filename': filename,
                'file_size': target_file.stat().st_size,
            }
        except Exception as e:
            logger.error(f'❗ 下载到指定文件夹失败: {e}', exc_info=True)
            raise

    def generate_and_download(self, text: str, voice_config: Dict,
                              target_dir: str, project_id: Optional[str] = None) -> Dict:
        """一步生成配音并下载到指定文件夹（普通 TTS）"""
        try:
            # 1. 生成配音
            result = self.generate_voiceover(text, voice_config, project_id=project_id)
            audio_path = str(result)  # SynthesisPath is a str subclass

            # 2. 复制到指定文件夹
            saved = self.download_audio_to_folder(audio_path, target_dir)

            return {
                'audio_path': audio_path,
                'engine_used': result.metadata.get('engine_used'),
                'engine_requested': result.metadata.get('engine_requested'),
                'fallback_used': result.metadata.get('fallback_used'),
                'fallback_reason': result.metadata.get('fallback_reason'),
                'saved_path': saved['saved_path'],
                'saved_dir': saved['saved_dir'],
                'filename': saved['filename'],
                'file_size': saved['file_size'],
            }
        except Exception as e:
            logger.error(f'❗ 生成并下载失败: {e}', exc_info=True)
            raise
