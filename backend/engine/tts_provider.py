#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : tts_provider.py
@Desc   : TTS Provider插件化架构 - 融入JJYB-ZJ的Provider接口设计
          统一TTS引擎接口，支持热插拔、自动注册、配置驱动
          所有TTS引擎遵循同一接口，便于扩展新引擎
"""

import os
import logging
import importlib
from typing import Dict, List, Optional, Any, Type, Callable
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger('JJYB_AI智剪')


@dataclass
class TTSRequest:
    """TTS合成请求（统一参数）"""
    text: str
    output_path: str
    voice: str = ''             # 音色ID/名称
    language: str = 'zh-CN'     # 语言
    rate: str = '+0%'           # 语速（百分比字符串）
    volume: str = '+0%'         # 音量
    pitch: Optional[int] = None  # 音调（半音）
    # 高级配置
    emotion: str = 'neutral'    # 情感
    emotion_intensity: float = 1.0  # 情感强度
    style: str = ''             # 风格
    # 声音复刻相关
    reference_audio_path: str = ''  # 参考音频路径
    clone_voice_id: str = ''    # 克隆音色ID
    # 音频参数
    sample_rate: int = 24000
    audio_format: str = 'mp3'
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TTSResult:
    """TTS合成结果"""
    success: bool
    output_path: str = ''
    duration: float = 0.0       # 音频时长（秒）
    sample_rate: int = 24000
    audio_format: str = 'mp3'
    file_size: int = 0
    error: str = ''
    engine_name: str = ''
    voice_used: str = ''
    metadata: Dict[str, Any] = field(default_factory=dict)


class TTSProviderBase(ABC):
    """TTS Provider 抽象基类 - 所有TTS引擎必须继承"""

    # 子类必须覆盖以下属性
    name: str = ''              # 引擎唯一标识（如 'edge-tts'）
    display_name: str = ''      # 显示名称
    description: str = ''       # 引擎描述
    supports_streaming: bool = False  # 是否支持流式合成
    supports_clone: bool = False     # 是否支持声音复刻
    supports_emotion: bool = False   # 是否支持情感
    supports_ssml: bool = False      # 是否支持SSML
    supported_voices: List[str] = []  # 支持的音色列表
    supported_languages: List[str] = []  # 支持的语言列表

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.initialized = False
        self._init_engine()

    def _init_engine(self):
        """子类可覆盖的初始化逻辑"""
        try:
            self.initialize()
            self.initialized = True
            logger.info(f'TTS Provider [{self.name}] 初始化成功')
        except Exception as e:
            logger.error(f'TTS Provider [{self.name}] 初始化失败: {e}')
            self.initialized = False

    @abstractmethod
    def initialize(self) -> None:
        """初始化引擎（子类必须实现）"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查引擎是否可用（如依赖包是否安装、配置是否完整）"""
        pass

    @abstractmethod
    def synthesize(self, request: TTSRequest) -> TTSResult:
        """合成语音（子类必须实现）"""
        pass

    def synthesize_stream(self, request: TTSRequest) -> Any:
        """流式合成（如支持）。子类可覆盖。"""
        raise NotImplementedError(f'[{self.name}] 不支持流式合成')

    def clone_voice(self, reference_audio_path: str, voice_name: str = '') -> Dict:
        """声音复刻（如支持）。子类可覆盖。"""
        raise NotImplementedError(f'[{self.name}] 不支持声音复刻')

    def list_voices(self) -> List[Dict]:
        """列出可用音色。子类可覆盖。"""
        return [{'id': v, 'name': v} for v in self.supported_voices]

    def get_info(self) -> Dict:
        """获取引擎信息"""
        return {
            'name': self.name,
            'display_name': self.display_name,
            'description': self.description,
            'available': self.is_available(),
            'initialized': self.initialized,
            'supports_streaming': self.supports_streaming,
            'supports_clone': self.supports_clone,
            'supports_emotion': self.supports_emotion,
            'supports_ssml': self.supports_ssml,
            'voices_count': len(self.supported_voices),
            'languages_count': len(self.supported_languages),
        }


class EdgeTTSProvider(TTSProviderBase):
    """Edge-TTS Provider - 微软免费在线TTS"""

    name = 'edge-tts'
    display_name = 'Edge TTS'
    description = '微软免费TTS服务，支持多种音色和情感'
    supports_emotion = True
    supports_streaming = True
    supported_voices = [
        'zh-CN-XiaoxiaoNeural', 'zh-CN-YunxiNeural', 'zh-CN-YunyangNeural',
        'zh-CN-XiaoyiNeural', 'zh-CN-YunjianNeural', 'zh-CN-XiaohanNeural',
        'zh-CN-XiaomoNeural', 'zh-CN-XiaoruiNeural', 'zh-CN-YunyeNeural',
        'zh-CN-YunyouNeural',
    ]
    supported_languages = ['zh-CN', 'en-US', 'ja-JP', 'ko-KR']

    EMOTION_TO_STYLE = {
        'happy': 'cheerful', 'sad': 'sad', 'angry': 'angry',
        'excited': 'excited', 'calm': 'calm', 'fearful': 'fearful',
        'love': 'gentle', 'neutral': None,
    }

    def initialize(self) -> None:
        import edge_tts  # noqa: F401
        from backend.config.ai_config import get_config_manager
        try:
            cfg = get_config_manager()
            self.enable = getattr(cfg.tts_model_config, 'enable_edge_tts', True)
        except Exception:
            self.enable = True

    def is_available(self) -> bool:
        return self.initialized and self.enable

    def synthesize(self, request: TTSRequest) -> TTSResult:
        if not self.is_available():
            return TTSResult(success=False, error=f'[{self.name}] 引擎不可用', engine_name=self.name)

        from backend.engine.tts_engine import TTSEngine

        engine = TTSEngine(default_engine='edge-tts')
        ok = engine.synthesize(
            text=request.text,
            output_path=request.output_path,
            engine=self.name,
            voice=request.voice or 'zh-CN-XiaoxiaoNeural',
            rate=request.rate,
            volume=request.volume,
            pitch=request.pitch,
            advanced_config={'emotion_type': request.emotion},
        )
        if not ok:
            return TTSResult(
                success=False,
                error=engine.last_error or 'Edge TTS 未生成有效音频，请检查网络后重试或切换本地/Google 引擎',
                engine_name=self.name,
            )

        out_file = Path(request.output_path)
        duration = self._estimate_duration(out_file)
        return TTSResult(
            success=True,
            output_path=request.output_path,
            duration=duration,
            file_size=out_file.stat().st_size,
            audio_format=request.audio_format,
            engine_name=self.name,
            voice_used=request.voice or 'zh-CN-XiaoxiaoNeural',
            metadata={'style': self.EMOTION_TO_STYLE.get(request.emotion), 'emotion': request.emotion}
        )

    def _estimate_duration(self, audio_path: Path) -> float:
        """估算音频时长"""
        try:
            import mutagen
            audio = mutagen.File(str(audio_path))
            if audio and audio.info:
                return audio.info.length
        except Exception:
            pass
        # 兜底：根据文件大小估算（mp3 128kbps）
        size = audio_path.stat().st_size
        return max(0.1, size / (128 * 1024 / 8))

    async def synthesize_stream(self, request: TTSRequest):
        """流式合成"""
        if not self.is_available():
            raise RuntimeError(f'[{self.name}] 引擎不可用')
        import edge_tts
        voice = request.voice or 'zh-CN-XiaoxiaoNeural'
        communicate = edge_tts.Communicate(
            request.text, voice,
            rate=request.rate, volume=request.volume
        )
        async for chunk in communicate.stream():
            if chunk['type'] == 'audio':
                yield chunk['data']


class AzureTTSProvider(TTSProviderBase):
    """Azure TTS Provider - 微软Azure云TTS"""

    name = 'azure'
    display_name = 'Azure TTS'
    description = '微软Azure认知服务TTS，支持SSML和丰富情感'
    supports_emotion = True
    supports_ssml = True
    supports_streaming = True
    supported_voices = [
        'zh-CN-XiaoxiaoNeural', 'zh-CN-YunxiNeural', 'zh-CN-XiaoyiNeural',
        'zh-CN-YunyangNeural', 'zh-CN-XiaohanNeural',
    ]
    supported_languages = ['zh-CN', 'en-US', 'ja-JP', 'ko-KR']

    def initialize(self) -> None:
        from backend.config.ai_config import get_config_manager
        cfg = get_config_manager()
        self.api_key = getattr(cfg.tts_model_config, 'azure_tts_key', '') or \
                       getattr(cfg.tts_model_config, 'azure_subscription_key', '')
        self.region = getattr(cfg.tts_model_config, 'azure_tts_region', '') or \
                      getattr(cfg.tts_model_config, 'azure_region', '')

    def is_available(self) -> bool:
        return bool(self.api_key and self.region)

    def synthesize(self, request: TTSRequest) -> TTSResult:
        if not self.is_available():
            return TTSResult(success=False, error='[Azure] 未配置API Key或Region', engine_name=self.name)
        try:
            import azure.cognitiveservices.speech as speechsdk

            Path(request.output_path).parent.mkdir(parents=True, exist_ok=True)
            voice = request.voice or 'zh-CN-XiaoxiaoNeural'

            speech_config = speechsdk.SpeechConfig(
                subscription=self.api_key, region=self.region
            )
            speech_config.speech_synthesis_voice_name = voice
            speech_config.speech_synthesis_output_format = (
                speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
            )

            audio_config = speechsdk.audio.AudioOutputConfig(filename=request.output_path)
            synthesizer = speechsdk.SpeechSynthesizer(
                speech_config=speech_config, audio_config=audio_config
            )

            # 构建SSML（含情感）
            ssml = self._build_ssml(request, voice)
            result = synthesizer.speak_ssml_async(ssml).get()

            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                duration = result.audio_duration.total_seconds() if result.audio_duration else 0
                return TTSResult(
                    success=True,
                    output_path=request.output_path,
                    duration=duration,
                    file_size=Path(request.output_path).stat().st_size,
                    engine_name=self.name,
                    voice_used=voice
                )
            else:
                error = str(result.error_details) if result.error_details else '未知错误'
                return TTSResult(success=False, error=error, engine_name=self.name)
        except Exception as e:
            logger.error(f'Azure TTS 合成失败: {e}', exc_info=True)
            return TTSResult(success=False, error=str(e), engine_name=self.name)

    def _build_ssml(self, request: TTSRequest, voice: str) -> str:
        """构建SSML"""
        from xml.sax.saxutils import escape
        rate = request.rate or '+0%'
        volume = request.volume or '+0%'
        pitch = f'{request.pitch:+d}st' if request.pitch else '+0st'

        style_open = ''
        style_close = ''
        if request.emotion and request.emotion != 'neutral':
            moods = {
                'happy': 'cheerful', 'sad': 'sad', 'angry': 'angry',
                'excited': 'excited', 'calm': 'calm', 'fearful': 'fearful',
            }
            mood = moods.get(request.emotion)
            if mood:
                intensity = max(0.1, min(2.0, request.emotion_intensity))
                style_open = f'<mstts:express-as style="{mood}" styledegree="{intensity}">'
                style_close = '</mstts:express-as>'

        return f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis"
            xmlns:mstts="http://www.w3.org/2001/mstts" xml:lang="{request.language}">
            <voice name="{voice}">
                <prosody rate="{rate}" volume="{volume}" pitch="{pitch}">
                    {style_open}{escape(request.text)}{style_close}
                </prosody>
            </voice>
        </speak>'''.strip()


class VolcanoTTSProvider(TTSProviderBase):
    """火山引擎 TTS Provider"""

    name = 'volcano'
    display_name = '火山引擎TTS'
    description = '字节跳动火山引擎TTS，支持语音克隆'
    supports_emotion = True
    supports_clone = True
    supported_voices = ['zh_female_qingxin', 'zh_male_chunhou', 'zh_female_wanwan']
    supported_languages = ['zh-CN']

    def initialize(self) -> None:
        from backend.config.ai_config import get_config_manager
        cfg = get_config_manager()
        self.api_key = getattr(cfg.tts_model_config, 'volcano_tts_key', '') or \
                       getattr(cfg.tts_model_config, 'volcano_api_key', '')
        self.app_id = getattr(cfg.tts_model_config, 'volcano_tts_app_id', '') or \
                      getattr(cfg.tts_model_config, 'volcano_app_id', '')
        self.clone_voice_id = getattr(cfg.tts_model_config, 'volcano_clone_voice_id', '')

    def is_available(self) -> bool:
        return bool(self.api_key and self.app_id)

    def synthesize(self, request: TTSRequest) -> TTSResult:
        if not self.is_available():
            return TTSResult(success=False, error='[Volcano] 未配置API Key或App ID', engine_name=self.name)
        try:
            import requests
            Path(request.output_path).parent.mkdir(parents=True, exist_ok=True)

            # 优先使用克隆音色
            voice = request.clone_voice_id or self.clone_voice_id or request.voice or 'zh_female_qingxin'

            # 火山引擎TTS API调用
            url = 'https://openspeech.bytedance.com/api/v1/tts'
            headers = {
                'Authorization': f'Bearer; {self.api_key}',
                'Content-Type': 'application/json',
            }
            payload = {
                'app': {
                    'appid': self.app_id,
                    'token': self.api_key,
                    'cluster': 'volcano_tts',
                },
                'user': {'uid': 'jjyb_user'},
                'audio': {
                    'voice_type': voice,
                    'encoding': request.audio_format,
                    'speed_ratio': self._parse_rate(request.rate),
                    'volume_ratio': self._parse_volume(request.volume),
                    'pitch_ratio': self._parse_pitch(request.pitch),
                    'sample_rate': request.sample_rate,
                },
                'request': {
                    'reqid': str(__import__('uuid').uuid4()),
                    'text': request.text,
                    'text_type': 'plain',
                    'operation': 'query',
                },
            }

            if request.emotion and request.emotion != 'neutral':
                payload['audio']['emotion'] = request.emotion
                payload['audio']['emotion_intensity'] = request.emotion_intensity

            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            data = resp.json()

            if data.get('code') != 3000:
                return TTSResult(
                    success=False,
                    error=f"火山TTS失败: {data.get('message', '未知错误')}",
                    engine_name=self.name
                )

            # 解码音频数据
            import base64
            audio_data = base64.b64decode(data['data'])
            with open(request.output_path, 'wb') as f:
                f.write(audio_data)

            duration = float(data.get('duration', 0)) / 1000.0 if data.get('duration') else 0
            return TTSResult(
                success=True,
                output_path=request.output_path,
                duration=duration,
                file_size=len(audio_data),
                engine_name=self.name,
                voice_used=voice
            )
        except Exception as e:
            logger.error(f'火山TTS 合成失败: {e}', exc_info=True)
            return TTSResult(success=False, error=str(e), engine_name=self.name)

    def clone_voice(self, reference_audio_path: str, voice_name: str = '') -> Dict:
        """通过参考音频克隆音色"""
        if not self.is_available():
            return {'success': False, 'error': '火山引擎TTS未配置'}
        try:
            import requests
            import base64

            with open(reference_audio_path, 'rb') as f:
                audio_data = base64.b64encode(f.read()).decode()

            url = 'https://openspeech.bytedance.com/api/v1/mega_tts/audio/upload'
            headers = {
                'Authorization': f'Bearer; {self.api_key}',
                'Content-Type': 'application/json',
                'Resource-Id': 'volc.megatts.voiceclone',
            }
            payload = {
                'appid': self.app_id,
                'user_id': 'jjyb_user',
                'audio_format': 'wav',
                'audio_data': audio_data,
                'source': 2,
                'language': 0,
                'model_type': 1,
            }

            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            data = resp.json()

            if data.get('BaseResp', {}).get('StatusCode', 0) != 0:
                return {'success': False, 'error': data.get('BaseResp', {}).get('StatusMessage', '克隆失败')}

            speaker_id = data.get('speaker_id', '')
            return {
                'success': True,
                'speaker_id': speaker_id,
                'voice_id': speaker_id,
                'voice_name': voice_name or f'clone_{speaker_id[:8]}'
            }
        except Exception as e:
            logger.error(f'火山声音克隆失败: {e}', exc_info=True)
            return {'success': False, 'error': str(e)}

    @staticmethod
    def _parse_rate(rate_str: str) -> float:
        """解析语速百分比字符串为比例"""
        try:
            if isinstance(rate_str, str) and rate_str.endswith('%'):
                pct = int(rate_str[:-1])
                return max(0.5, min(2.0, 1.0 + pct / 100.0))
        except Exception:
            pass
        return 1.0

    @staticmethod
    def _parse_volume(volume_str: str) -> float:
        """解析音量百分比字符串为比例"""
        try:
            if isinstance(volume_str, str) and volume_str.endswith('%'):
                pct = int(volume_str[:-1])
                return max(0.1, min(3.0, 1.0 + pct / 100.0))
        except Exception:
            pass
        return 1.0

    @staticmethod
    def _parse_pitch(pitch: Optional[int]) -> float:
        """解析音调（半音）为比例"""
        if pitch is None:
            return 1.0
        return max(0.5, min(2.0, 1.0 + pitch / 12.0))


class IndexTTS2Provider(TTSProviderBase):
    """IndexTTS2 本地声音克隆 Provider"""

    name = 'indextts2'
    display_name = 'IndexTTS2 本地克隆'
    description = '基于IndexTTS2的本地声音克隆引擎，支持任意音色复刻'
    supports_clone = True
    supports_emotion = True
    supported_voices = []  # 由参考音频决定
    supported_languages = ['zh-CN', 'en-US']

    def initialize(self) -> None:
        from backend.services.local_voice_clone_service import LocalVoiceCloneService
        self.service = LocalVoiceCloneService()

    def is_available(self) -> bool:
        try:
            return self.service is not None
        except Exception:
            return False

    def synthesize(self, request: TTSRequest) -> TTSResult:
        if not self.is_available():
            return TTSResult(success=False, error='[IndexTTS2] 服务不可用', engine_name=self.name)
        if not request.reference_audio_path:
            return TTSResult(success=False, error='[IndexTTS2] 缺少参考音频', engine_name=self.name)
        try:
            # 调用本地声音克隆服务
            output_path = self.service.synthesize(
                text=request.text,
                reference_audio_path=request.reference_audio_path,
                output_path=request.output_path,
                language=request.language,
                speed=self._parse_rate(request.rate)
            )
            if not output_path or not os.path.exists(output_path):
                return TTSResult(success=False, error='克隆合成失败', engine_name=self.name)

            file_size = os.path.getsize(output_path)
            duration = self._estimate_duration(output_path)
            return TTSResult(
                success=True,
                output_path=output_path,
                duration=duration,
                file_size=file_size,
                engine_name=self.name,
                voice_used='cloned',
                metadata={'reference_audio': request.reference_audio_path}
            )
        except Exception as e:
            logger.error(f'IndexTTS2 合成失败: {e}', exc_info=True)
            return TTSResult(success=False, error=str(e), engine_name=self.name)

    def clone_voice(self, reference_audio_path: str, voice_name: str = '') -> Dict:
        """IndexTTS2的克隆是即时复刻，无需训练"""
        if not os.path.exists(reference_audio_path):
            return {'success': False, 'error': '参考音频文件不存在'}
        # IndexTTS2每次合成时使用参考音频，无需预先克隆
        return {
            'success': True,
            'voice_id': reference_audio_path,
            'voice_name': voice_name or f'clone_{Path(reference_audio_path).stem}',
            'note': 'IndexTTS2 采用即时复刻模式，参考音频即音色ID'
        }

    @staticmethod
    def _parse_rate(rate_str: str) -> float:
        try:
            if isinstance(rate_str, str) and rate_str.endswith('%'):
                pct = int(rate_str[:-1])
                return max(0.5, min(2.0, 1.0 + pct / 100.0))
        except Exception:
            pass
        return 1.0

    @staticmethod
    def _estimate_duration(audio_path: str) -> float:
        try:
            import mutagen
            audio = mutagen.File(audio_path)
            if audio and audio.info:
                return audio.info.length
        except Exception:
            pass
        size = os.path.getsize(audio_path)
        return max(0.1, size / (128 * 1024 / 8))


class GTTSProvider(TTSProviderBase):
    """Google TTS Provider"""

    name = 'gtts'
    display_name = 'Google TTS'
    description = 'Google Translate TTS，简单免费但音色单一'
    supported_voices = ['zh-CN', 'en-US', 'ja-JP']
    supported_languages = ['zh-CN', 'en-US', 'ja-JP']

    def initialize(self) -> None:
        from backend.config.ai_config import get_config_manager
        try:
            cfg = get_config_manager()
            self.enable = getattr(cfg.tts_model_config, 'enable_gtts', False)
        except Exception:
            self.enable = False

    def is_available(self) -> bool:
        if not self.enable:
            return False
        try:
            import gtts  # noqa: F401
            return True
        except ImportError:
            return False

    def synthesize(self, request: TTSRequest) -> TTSResult:
        if not self.is_available():
            return TTSResult(success=False, error='[gTTS] 不可用', engine_name=self.name)
        try:
            from gtts import gTTS
            Path(request.output_path).parent.mkdir(parents=True, exist_ok=True)
            lang = request.language.split('-')[0] if request.language else 'zh'
            tts = gTTS(text=request.text, lang=lang, slow=False)
            tts.save(request.output_path)
            file_size = os.path.getsize(request.output_path)
            duration = file_size / (128 * 1024 / 8)
            return TTSResult(
                success=True,
                output_path=request.output_path,
                duration=duration,
                file_size=file_size,
                engine_name=self.name,
                voice_used=lang
            )
        except Exception as e:
            logger.error(f'gTTS 合成失败: {e}', exc_info=True)
            return TTSResult(success=False, error=str(e), engine_name=self.name)


class TTSProviderRegistry:
    """TTS Provider 注册中心 - 管理所有已注册的TTS引擎"""

    def __init__(self):
        self._providers: Dict[str, TTSProviderBase] = {}
        self._provider_classes: Dict[str, Type[TTSProviderBase]] = {}
        self._default_provider: Optional[str] = None

    def register(self, provider_class: Type[TTSProviderBase]) -> Type[TTSProviderBase]:
        """注册Provider类（装饰器风格）"""
        if not issubclass(provider_class, TTSProviderBase):
            raise ValueError(f'{provider_class.__name__} 必须继承 TTSProviderBase')
        if not provider_class.name:
            raise ValueError(f'{provider_class.__name__} 必须定义非空 name 属性')
        self._provider_classes[provider_class.name] = provider_class
        logger.info(f'TTS Provider 类已注册: {provider_class.name} ({provider_class.display_name})')
        return provider_class

    def get_provider(self, name: str, config: Optional[Dict] = None) -> Optional[TTSProviderBase]:
        """获取Provider实例（带缓存）"""
        if name in self._providers:
            return self._providers[name]
        if name not in self._provider_classes:
            logger.error(f'TTS Provider [{name}] 未注册')
            return None
        try:
            provider = self._provider_classes[name](config)
            self._providers[name] = provider
            return provider
        except Exception as e:
            logger.error(f'初始化 TTS Provider [{name}] 失败: {e}')
            return None

    def list_available_providers(self) -> List[Dict]:
        """列出所有可用Provider"""
        result = []
        for name, cls in self._provider_classes.items():
            try:
                provider = self.get_provider(name)
                info = provider.get_info() if provider else {
                    'name': name, 'display_name': cls.display_name,
                    'available': False, 'error': '初始化失败'
                }
                result.append(info)
            except Exception as e:
                result.append({
                    'name': name, 'display_name': cls.display_name,
                    'available': False, 'error': str(e)
                })
        return result

    def get_default_provider_name(self) -> str:
        """获取默认Provider名称"""
        if self._default_provider:
            return self._default_provider
        try:
            from backend.config.ai_config import get_config_manager
            cfg = get_config_manager()
            default = getattr(cfg.tts_model_config, 'default_tts', 'edge')
            # 别名映射
            aliases = {'edge': 'edge-tts', 'edgetts': 'edge-tts', 'azure-tts': 'azure'}
            return aliases.get(default, default)
        except Exception:
            return 'edge-tts'

    def set_default_provider(self, name: str) -> None:
        """设置默认Provider"""
        if name in self._provider_classes:
            self._default_provider = name
        else:
            logger.warning(f'设置默认Provider失败：{name} 未注册')

    def synthesize_with_fallback(self, request: TTSRequest,
                                 preferred_engines: Optional[List[str]] = None) -> TTSResult:
        """带回退的合成：尝试preferred_engines列表，全部失败则尝试所有可用引擎"""
        engines = preferred_engines or [self.get_default_provider_name()]

        # 添加备选引擎
        all_engines = list(self._provider_classes.keys())
        for eng in all_engines:
            if eng not in engines:
                engines.append(eng)

        last_error = ''
        for eng in engines:
            provider = self.get_provider(eng)
            if not provider or not provider.is_available():
                continue
            try:
                result = provider.synthesize(request)
                if result.success:
                    return result
                last_error = result.error
            except Exception as e:
                last_error = str(e)
                continue

        return TTSResult(success=False, error=f'所有TTS引擎均失败，最后错误: {last_error}', engine_name='none')


# 全局注册中心实例
_registry: Optional[TTSProviderRegistry] = None


def get_tts_registry() -> TTSProviderRegistry:
    """获取全局TTS Provider注册中心"""
    global _registry
    if _registry is None:
        _registry = TTSProviderRegistry()
        # 注册内置Provider
        _registry.register(EdgeTTSProvider)
        _registry.register(AzureTTSProvider)
        _registry.register(VolcanoTTSProvider)
        _registry.register(IndexTTS2Provider)
        _registry.register(GTTSProvider)
        logger.info(f'✅ TTS Provider注册中心初始化完成，已注册 {len(_registry._provider_classes)} 个引擎')
    return _registry


def reset_tts_registry() -> None:
    """重置TTS注册中心（配置切换时调用）"""
    global _registry
    _registry = None


# 便捷函数
def synthesize_tts(text: str, output_path: str, engine: str = '',
                   voice: str = '', **kwargs) -> TTSResult:
    """便捷合成函数"""
    registry = get_tts_registry()
    engine_name = engine or registry.get_default_provider_name()
    request = TTSRequest(
        text=text, output_path=output_path,
        voice=voice, **kwargs
    )
    if engine_name:
        provider = registry.get_provider(engine_name)
        if provider and provider.is_available():
            return provider.synthesize(request)
    # 回退
    return registry.synthesize_with_fallback(request, [engine_name] if engine_name else None)
