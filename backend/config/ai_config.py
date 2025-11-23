"""
AI模型配置管理
支持多种大模型API配置
"""

import json
import os
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger('JJYB_AI智剪')


@dataclass
class LLMConfig:
    """大语言模型配置 - 支持12个主流模型"""
    # OpenAI GPT-4
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-3.5-turbo"
    
    # Anthropic Claude
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-sonnet-20240229"
    
    # Google Gemini
    gemini_api_key: str = ""
    
    # 月之暗面 Kimi
    kimi_api_key: str = ""
    
    # 讯飞星火
    spark_api_key: str = ""
    spark_api_secret: str = ""
    
    # 阿里通义千问
    qwen_api_key: str = ""
    
    # 百度文心一言
    ernie_api_key: str = ""
    ernie_secret_key: str = ""
    
    # 智谱ChatGLM
    chatglm_api_key: str = ""
    
    # DeepSeek
    deepseek_api_key: str = ""
    
    # 兼容旧配置
    tongyi_api_key: str = ""  # 通义千问（旧）
    tongyi_secret_key: str = ""
    wenxin_api_key: str = ""  # 文心一言（旧）
    wenxin_secret_key: str = ""
    claude_api_key: str = ""  # Claude（旧）
    
    # 默认使用的模型
    default_model: str = "openai"  # openai/anthropic/gemini/kimi/spark/qwen/ernie/chatglm/deepseek


@dataclass
class VisionConfig:
    """视觉分析模型配置 - 支持主流视觉模型"""
    # GPT-4V (OpenAI Vision)
    gpt4v_api_key: str = ""
    gpt4v_model: str = "gpt-4-vision-preview"
    
    # Claude Vision
    claude_vision_api_key: str = ""
    
    # Google Gemini Vision
    gemini_vision_api_key: str = ""
    
    # 通义千问VL
    qwen_vl_api_key: str = ""
    
    # 百度视觉
    baidu_vision_api_key: str = ""
    baidu_vision_secret_key: str = ""
    
    # 腾讯云视觉
    tencent_vision_secret_id: str = ""
    tencent_vision_secret_key: str = ""
    
    # 兼容旧配置
    tongyi_vl_api_key: str = ""  # 通义千问VL（旧）
    openai_vision_api_key: str = ""  # OpenAI Vision（旧）
    
    # 默认使用的模型
    default_model: str = "gpt4v"  # gpt4v/claude_vision/gemini/qwen_vl/baidu/tencent
    
    # 本地模型选项
    use_local_yolo: bool = True
    use_local_clip: bool = False


@dataclass
class TTSModelConfig:
    """TTS语音模型配置 - 支持主流TTS服务"""
    # Microsoft Azure TTS
    azure_tts_key: str = ""
    azure_tts_region: str = "eastasia"
    
    # Edge TTS（免费）
    enable_edge_tts: bool = True
    edge_tts_voice: str = "zh-CN-XiaoxiaoNeural"
    
    # gTTS（免费）
    enable_gtts: bool = False
    gtts_lang: str = "zh-CN"
    
    # 声音克隆
    enable_voice_clone: bool = False
    voice_clone_model_path: str = ""
    voice_clone_executable_path: str = ""
    
    # Voice-Pro 外部 TTS 引擎
    voice_pro_enabled: bool = False
    voice_pro_root: str = ""
    voice_pro_python_exe: str = ""
    voice_pro_tts_script: str = ""

    # 默认使用的TTS（当前版本默认使用本地 pyttsx3 离线引擎）
    default_tts: str = "pyttsx3"  # pyttsx3/edge/gtts/azure/voice_clone


@dataclass
class ProxyConfig:
    """聚合接口配置"""
    use_proxy: bool = False  # 是否使用聚合接口
    proxy_type: str = "海外线路"  # 聚合海外线路/聚合国内线路
    proxy_url: str = ""  # 聚合海外线路URL
    proxy_domestic_url: str = ""  # 聚合国内线路URL
    
    # 海外线路说明
    # 1号线：适合国内用户，自己微软官网中转
    # 2号线：适合国内用户，无需开启微软中转，速度重快，但可能会有一定的网络动荡
    # 3号线：海外直连，国内部分地区可能会有网络问题
    # 4号线：海外直连，国内部分地区可能会有网络问题


@dataclass
class TTSConfig:
    """TTS配音参数"""
    # 元默认配置
    enable_silence_split: bool = True  # 开启后TTS配音后会自动去掉长的音频沉默
    silence_threshold: int = 50  # 推荐50，越大越严格，默认50
    
    # voxCPM配音参数
    vox_speed: float = 3.0  # 语气模仿，默认3.0（值越大语气生硬，值越小语气极自白，音量极小）
    vox_steps: int = 10  # 推理步数，默认10（音质小步成速度慢，音质差但速度快，音质差但速度快，但超过20效果提升不明显）


@dataclass
class CensorConfig:
    """违禁词配置"""
    enable_censor: bool = True  # 是否启用违禁词检测
    censor_tool: str = "国内版剪映"  # 国内版剪映/自定义
    custom_words: List[str] = None  # 自定义违禁词列表
    
    def __post_init__(self):
        if self.custom_words is None:
            self.custom_words = []


@dataclass
class GlobalConfig:
    """全局知识设置"""
    # 画面推理模型
    vision_model_type: str = "2.5推理模型"  # 2.5推理模型/其他
    
    # 视频中转
    enable_video_transfer: bool = False  # 关闭中转（超过限额且自己有网络中转，建议关闭）
    
    # 语言设置
    language: str = "简体中文"  # 简体中文/English
    
    # 自动转模型
    auto_convert_model: bool = True  # 必须开启
    
    # AI连禁词
    enable_ai_censor: bool = False  # 开启后，将在传入AI前过滤掉违禁词
    
    # 提示音
    enable_sound: bool = True  # 完成任务会有提示


@dataclass
class LocalModelConfig:
    """本地模型设置"""
    # 强制CPU
    force_cpu: bool = False  # 非特殊情况不要打开，打开后，重启生效
    
    # ASR精度
    asr_precision: str = "float32"  # float32/float16/int8
    
    # 分辨率限制
    enable_resolution_limit: bool = False  # 开启后，将只能建1080P以上分辨率的视频，但速度会更快，但速度会更快，不建议开启


class AIConfigManager:
    """AI配置管理器"""
    
    def __init__(self, config_dir: str = "config"):
        """
        初始化配置管理器
        
        Args:
            config_dir: 配置文件目录
        """
        self.config_dir = config_dir
        self.config_file = os.path.join(config_dir, "ai_config.json")
        self.censor_file = os.path.join(config_dir, "censor_words.json")
        
        # 确保配置目录存在
        os.makedirs(config_dir, exist_ok=True)
        
        # 加载配置
        self.llm_config = LLMConfig()
        self.vision_config = VisionConfig()
        self.tts_model_config = TTSModelConfig()
        self.proxy_config = ProxyConfig()
        self.tts_config = TTSConfig()
        self.censor_config = CensorConfig()
        self.global_config = GlobalConfig()
        self.local_model_config = LocalModelConfig()
        
        self.load_config()
        self.load_censor_words()
    
    def load_config(self):
        """加载配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 加载各个配置
                if 'llm' in data:
                    self.llm_config = LLMConfig(**data['llm'])
                if 'vision' in data:
                    self.vision_config = VisionConfig(**data['vision'])
                if 'tts_model' in data:
                    self.tts_model_config = TTSModelConfig(**data['tts_model'])
                if 'proxy' in data:
                    self.proxy_config = ProxyConfig(**data['proxy'])
                if 'tts' in data:
                    self.tts_config = TTSConfig(**data['tts'])
                if 'censor' in data:
                    self.censor_config = CensorConfig(**data['censor'])
                if 'global' in data:
                    self.global_config = GlobalConfig(**data['global'])
                if 'local_model' in data:
                    self.local_model_config = LocalModelConfig(**data['local_model'])
                
                logger.info("✅ AI配置加载成功")
            else:
                logger.info("📝 使用默认AI配置")
                self.save_config()
        
        except Exception as e:
            logger.error(f"❌ 加载AI配置失败: {e}")
    
    def save_config(self):
        """保存配置"""
        try:
            data = {
                'llm': asdict(self.llm_config),
                'vision': asdict(self.vision_config),
                'tts_model': asdict(self.tts_model_config),
                'proxy': asdict(self.proxy_config),
                'tts': asdict(self.tts_config),
                'censor': asdict(self.censor_config),
                'global': asdict(self.global_config),
                'local_model': asdict(self.local_model_config)
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info("✅ AI配置保存成功")
            return True
        
        except Exception as e:
            logger.error(f"❌ 保存AI配置失败: {e}")
            return False
    
    def load_censor_words(self):
        """加载违禁词"""
        try:
            if os.path.exists(self.censor_file):
                with open(self.censor_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.censor_config.custom_words = data.get('words', [])
                logger.info(f"✅ 加载了{len(self.censor_config.custom_words)}个违禁词")
            else:
                # 创建默认违禁词文件
                self.save_censor_words()
        
        except Exception as e:
            logger.error(f"❌ 加载违禁词失败: {e}")
    
    def save_censor_words(self):
        """保存违禁词"""
        try:
            data = {
                'words': self.censor_config.custom_words,
                'categories': self._get_default_censor_categories()
            }
            
            with open(self.censor_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info("✅ 违禁词保存成功")
            return True
        
        except Exception as e:
            logger.error(f"❌ 保存违禁词失败: {e}")
            return False
    
    def _get_default_censor_categories(self) -> Dict[str, List[str]]:
        """获取默认违禁词分类"""
        return {
            "政治敏感": [],
            "暴力血腥": [],
            "色情低俗": [],
            "违法犯罪": [],
            "虚假信息": [],
            "侵权内容": [],
            "其他": []
        }
    
    def add_censor_word(self, word: str, category: str = "其他") -> bool:
        """添加违禁词"""
        if word and word not in self.censor_config.custom_words:
            self.censor_config.custom_words.append(word)
            self.save_censor_words()
            logger.info(f"✅ 添加违禁词: {word}")
            return True
        return False
    
    def remove_censor_word(self, word: str) -> bool:
        """删除违禁词"""
        if word in self.censor_config.custom_words:
            self.censor_config.custom_words.remove(word)
            self.save_censor_words()
            logger.info(f"✅ 删除违禁词: {word}")
            return True
        return False
    
    def check_censor(self, text: str) -> tuple[bool, List[str]]:
        """
        检查文本是否包含违禁词
        
        Args:
            text: 待检查文本
            
        Returns:
            (是否包含违禁词, 违禁词列表)
        """
        if not self.censor_config.enable_censor:
            return False, []
        
        found_words = []
        for word in self.censor_config.custom_words:
            if word in text:
                found_words.append(word)
        
        return len(found_words) > 0, found_words
    
    def filter_censor_words(self, text: str, replace_with: str = "***") -> str:
        """
        过滤文本中的违禁词
        
        Args:
            text: 原文本
            replace_with: 替换字符
            
        Returns:
            过滤后的文本
        """
        if not self.censor_config.enable_censor:
            return text
        
        filtered_text = text
        for word in self.censor_config.custom_words:
            if word in filtered_text:
                filtered_text = filtered_text.replace(word, replace_with)
        
        return filtered_text
    
    def get_llm_api_key(self, model: Optional[str] = None) -> Optional[str]:
        """获取LLM API密钥 - 支持所有12个模型"""
        model = model or self.llm_config.default_model
        
        key_map = {
            # 新配置
            'openai': self.llm_config.openai_api_key,
            'anthropic': self.llm_config.anthropic_api_key,
            'gemini': self.llm_config.gemini_api_key,
            'kimi': self.llm_config.kimi_api_key,
            'spark': self.llm_config.spark_api_key,
            'qwen': self.llm_config.qwen_api_key,
            'ernie': self.llm_config.ernie_api_key,
            'chatglm': self.llm_config.chatglm_api_key,
            'deepseek': self.llm_config.deepseek_api_key,
            # 兼容旧配置
            'tongyi': self.llm_config.tongyi_api_key or self.llm_config.qwen_api_key,
            'wenxin': self.llm_config.wenxin_api_key or self.llm_config.ernie_api_key,
            'claude': self.llm_config.claude_api_key or self.llm_config.anthropic_api_key,
        }
        
        return key_map.get(model)
    
    def get_vision_api_key(self, model: Optional[str] = None) -> Optional[str]:
        """获取视觉模型API密钥 - 支持所有视觉模型"""
        model = model or self.vision_config.default_model
        
        key_map = {
            # 新配置
            'gpt4v': self.vision_config.gpt4v_api_key,
            'claude_vision': self.vision_config.claude_vision_api_key,
            'gemini_vision': self.vision_config.gemini_vision_api_key,
            'qwen_vl': self.vision_config.qwen_vl_api_key,
            'baidu': self.vision_config.baidu_vision_api_key,
            'tencent': self.vision_config.tencent_vision_secret_id,
            # 兼容旧配置
            'qianwen_vl': self.vision_config.tongyi_vl_api_key or self.vision_config.qwen_vl_api_key,
            'openai': self.vision_config.openai_vision_api_key or self.vision_config.gpt4v_api_key,
            'gemini': self.vision_config.gemini_vision_api_key,
            'claude': self.vision_config.claude_vision_api_key,
        }
        
        return key_map.get(model)
    
    def get_tts_config(self, tts_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取TTS配置 - 支持所有TTS服务"""
        tts_type = tts_type or self.tts_model_config.default_tts
        
        config_map = {
            'pyttsx3': {
                'enabled': True
            },
            'azure': {
                'key': self.tts_model_config.azure_tts_key,
                'region': self.tts_model_config.azure_tts_region
            },
            'edge': {
                'enabled': self.tts_model_config.enable_edge_tts,
                'voice': self.tts_model_config.edge_tts_voice
            },
            'gtts': {
                'enabled': self.tts_model_config.enable_gtts,
                'lang': self.tts_model_config.gtts_lang
            },
            'voice_clone': {
                'enabled': self.tts_model_config.enable_voice_clone,
                'model_path': self.tts_model_config.voice_clone_model_path,
                'executable_path': getattr(self.tts_model_config, 'voice_clone_executable_path', '')
            },
            'voice_pro': {
                'enabled': getattr(self.tts_model_config, 'voice_pro_enabled', False),
                'root': getattr(self.tts_model_config, 'voice_pro_root', ''),
                'python_exe': getattr(self.tts_model_config, 'voice_pro_python_exe', ''),
                'tts_script': getattr(self.tts_model_config, 'voice_pro_tts_script', '')
            }
        }
        
        return config_map.get(tts_type)
    
    def export_config(self, filepath: str) -> bool:
        """导出配置"""
        try:
            data = {
                'llm': asdict(self.llm_config),
                'vision': asdict(self.vision_config),
                'tts_model': asdict(self.tts_model_config),
                'proxy': asdict(self.proxy_config),
                'tts': asdict(self.tts_config),
                'censor': asdict(self.censor_config),
                'global': asdict(self.global_config),
                'local_model': asdict(self.local_model_config)
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"✅ 配置导出成功: {filepath}")
            return True
        
        except Exception as e:
            logger.error(f"❌ 配置导出失败: {e}")
            return False
    
    def import_config(self, filepath: str) -> bool:
        """导入配置"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 更新配置
            if 'llm' in data:
                self.llm_config = LLMConfig(**data['llm'])
            if 'vision' in data:
                self.vision_config = VisionConfig(**data['vision'])
            if 'tts_model' in data:
                self.tts_model_config = TTSModelConfig(**data['tts_model'])
            if 'proxy' in data:
                self.proxy_config = ProxyConfig(**data['proxy'])
            if 'tts' in data:
                self.tts_config = TTSConfig(**data['tts'])
            if 'censor' in data:
                self.censor_config = CensorConfig(**data['censor'])
            if 'global' in data:
                self.global_config = GlobalConfig(**data['global'])
            if 'local_model' in data:
                self.local_model_config = LocalModelConfig(**data['local_model'])
            
            # 保存
            self.save_config()
            
            logger.info(f"✅ 配置导入成功: {filepath}")
            return True
        
        except Exception as e:
            logger.error(f"❌ 配置导入失败: {e}")
            return False


# 全局配置管理器实例
_config_manager = None


def get_config_manager() -> AIConfigManager:
    """获取配置管理器单例"""
    global _config_manager
    if _config_manager is None:
        config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config')
        _config_manager = AIConfigManager(config_dir)
    return _config_manager
