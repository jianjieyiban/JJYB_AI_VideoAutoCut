# -*- coding: utf-8 -*-
"""
ASR Engine
语音识别引擎 - 完整版
支持多种ASR引擎：Whisper、FunASR等
"""

import logging
from pathlib import Path
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


class ASREngine:
    """ASR引擎 - 完整版"""

    def __init__(self, default_engine: str = 'whisper', model_size: str = 'base'):
        """
        初始化ASR引擎

        Args:
            default_engine: 默认引擎（whisper/funasr）
            model_size: 模型大小（tiny/base/small/medium/large）
        """
        self.default_engine = default_engine
        self.model_size = model_size
        self.whisper_model = None
        self.available_engines = self._check_available_engines() or []
        logger.info(f'✅ ASR引擎初始化完成，可用引擎: {self.available_engines if self.available_engines else "无（需要安装whisper或funasr）"}')

    def _check_available_engines(self) -> List[str]:
        """检查可用的ASR引擎"""
        engines = []

        # 检查Whisper
        try:
            import whisper
            engines.append('whisper')
        except (ImportError, TypeError, Exception) as e:
            logger.warning(f'Whisper不可用: {type(e).__name__}')

        # 检查FunASR
        try:
            import funasr
            engines.append('funasr')
        except (ImportError, Exception) as e:
            logger.warning(f'FunASR不可用: {type(e).__name__}')

        return engines

    def _load_whisper_model(self):
        """加载Whisper模型"""
        if self.whisper_model is None:
            try:
                import whisper
                logger.info(f'正在加载Whisper模型: {self.model_size}')
                self.whisper_model = whisper.load_model(self.model_size)
                logger.info('✅ Whisper模型加载成功')
            except Exception as e:
                logger.error(f'❗ Whisper模型加载失败: {e}')
                raise

    @staticmethod
    def _locale_to_whisper_language(language: str) -> str:
        value = str(language or '').strip().lower()
        if not value or value in ('auto', 'automatic'):
            return 'auto'
        return value.split('-', 1)[0].split('_', 1)[0]

    def _resolve_language(self, language: Optional[str] = None) -> str:
        """Resolve a task language, falling back to the saved global ASR language."""
        if language:
            return self._locale_to_whisper_language(language)

        try:
            from backend.core.global_state import get_global_state
            state = get_global_state()
            if hasattr(state, 'get_user_setting'):
                configured = state.get_user_setting('language', 'asr', None)
            else:
                configured = (getattr(state, 'user_settings', {}).get('language', {}) or {}).get('asr')
        except Exception:
            configured = None

        return self._locale_to_whisper_language(configured or 'en-US')

    def recognize_whisper(self, audio_path: str,
                         language: Optional[str] = None,
                         task: str = 'transcribe') -> Dict:
        """
        使用Whisper进行语音识别

        Args:
            audio_path: 音频文件路径
            language: 语言代码
            task: 任务类型（transcribe/translate）

        Returns:
            识别结果字典
        """
        try:
            self._load_whisper_model()
            language = self._resolve_language(language)

            logger.info(f'开始Whisper识别: {audio_path}')

            result = self.whisper_model.transcribe(
                audio_path,
                language=None if language == 'auto' else language,
                task=task,
                verbose=False
            )

            # 提取文本和时间戳
            segments = []
            for segment in result.get('segments', []):
                segments.append({
                    'start': segment['start'],
                    'end': segment['end'],
                    'text': segment['text'].strip()
                })

            output = {
                'text': result.get('text', '').strip(),
                'language': result.get('language', language),
                'segments': segments,
                'duration': segments[-1]['end'] if segments else 0
            }

            logger.info(f'✅ Whisper识别成功，文本长度: {len(output["text"])}')
            return output

        except Exception as e:
            logger.error(f'❗ Whisper识别失败: {e}', exc_info=True)
            return {'text': '', 'segments': [], 'error': str(e)}

    def recognize_funasr(self, audio_path: str,
                        model_name: str = 'paraformer-zh') -> Dict:
        """
        使用FunASR进行语音识别

        Args:
            audio_path: 音频文件路径
            model_name: 模型名称

        Returns:
            识别结果字典
        """
        try:
            from funasr import AutoModel

            logger.info(f'开始FunASR识别: {audio_path}')

            model = AutoModel(model=model_name)
            result = model.generate(input=audio_path)

            if result and len(result) > 0:
                text = result[0]['text']

                output = {
                    'text': text,
                    'segments': [{'start': 0, 'end': 0, 'text': text}],
                    'duration': 0
                }

                logger.info(f'✅ FunASR识别成功，文本长度: {len(text)}')
                return output
            else:
                return {'text': '', 'segments': []}

        except Exception as e:
            logger.error(f'❗ FunASR识别失败: {e}', exc_info=True)
            return {'text': '', 'segments': [], 'error': str(e)}

    def recognize(self, audio_path: str,
                 engine: Optional[str] = None,
                 language: Optional[str] = None,
                 **kwargs) -> Dict:
        """
        统一的语音识别接口

        Args:
            audio_path: 音频文件路径
            engine: 指定引擎（不指定则使用默认）
            language: 语言代码
            **kwargs: 其他参数

        Returns:
            识别结果字典
        """
        engine = engine or self.default_engine

        if engine not in self.available_engines:
            logger.error(f'引擎 {engine} 不可用')
            return {'text': '', 'segments': [], 'error': f'引擎不可用: {engine}'}

        try:
            if engine == 'whisper':
                return self.recognize_whisper(audio_path, language, **kwargs)

            elif engine == 'funasr':
                return self.recognize_funasr(audio_path, **kwargs)

            else:
                logger.error(f'未知引擎: {engine}')
                return {'text': '', 'segments': [], 'error': f'未知引擎: {engine}'}

        except Exception as e:
            logger.error(f'语音识别失败: {e}', exc_info=True)
            return {'text': '', 'segments': [], 'error': str(e)}

    def generate_srt(self, segments: List[Dict], output_path: str) -> bool:
        """
        生成SRT字幕文件

        Args:
            segments: 时间戳分段列表
            output_path: 输出SRT文件路径

        Returns:
            是否成功
        """
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, 'w', encoding='utf-8') as f:
                for i, segment in enumerate(segments, 1):
                    start = self._format_timestamp(segment['start'])
                    end = self._format_timestamp(segment['end'])
                    text = segment['text']

                    f.write(f"{i}\n")
                    f.write(f"{start} --> {end}\n")
                    f.write(f"{text}\n\n")

            logger.info(f'✅ SRT字幕生成成功: {output_path}')
            return True

        except Exception as e:
            logger.error(f'❗ SRT字幕生成失败: {e}', exc_info=True)
            return False

    def _format_timestamp(self, seconds: float) -> str:
        """
        格式化时间戳为SRT格式

        Args:
            seconds: 秒数

        Returns:
            格式化的时间戳（HH:MM:SS,mmm）
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)

        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def batch_recognize(self, audio_paths: List[str],
                       engine: Optional[str] = None) -> List[Dict]:
        """
        批量识别音频

        Args:
            audio_paths: 音频文件路径列表
            engine: 指定引擎

        Returns:
            识别结果列表
        """
        results = []

        for audio_path in audio_paths:
            result = self.recognize(audio_path, engine=engine)
            results.append({
                'file': audio_path,
                'result': result
            })

        logger.info(f'✅ 批量识别完成: {len(results)}个文件')
        return results
