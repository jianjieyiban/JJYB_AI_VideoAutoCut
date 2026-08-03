"""
AI模型配置管理
支持多种大模型API配置
"""

import json
import os
import logging
import tempfile
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, fields

logger = logging.getLogger('JJYB_AI智剪')


class AIServiceError(Exception):
    """可安全展示给用户的 AI 服务错误。"""

    code = "AI_SERVICE_ERROR"
    user_message = "AI 服务暂时不可用，请检查配置后重试。"

    def __init__(self, message: Optional[str] = None):
        super().__init__(message or self.user_message)


class AIConfigurationError(AIServiceError):
    code = "AI_CONFIGURATION_ERROR"
    user_message = "AI 服务尚未完成配置，请配置所选模型后重试。"


class AIRequestError(AIServiceError):
    code = "AI_REQUEST_FAILED"
    user_message = "AI 服务请求失败，请稍后重试。"


class AIResponseError(AIServiceError):
    code = "AI_RESPONSE_INVALID"
    user_message = "AI 服务返回结果无效，请稍后重试。"


@dataclass
class LLMConfig:
    """大语言模型渠道配置。模型 ID 以各服务账户权限和 API 测试结果为准。
    默认推荐 custom_openai：用户在设置页填好任意 OpenAI 兼容服务即可即时驱动三大核心功能。"""
    # OpenAI
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5"

    # 自定义 OpenAI 兼容 API（默认推荐：设置页测试成功后即时生效，驱动三大核心功能）
    custom_openai_name: str = ""
    custom_openai_api_key: str = ""
    custom_openai_base_url: str = ""
    custom_openai_model: str = ""
    custom_openai_vision_model: str = ""

    # Anthropic Claude
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str = "claude-sonnet-5"

    # Google Gemini
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = "gemini-2.5-flash"

    # 月之暗面 Kimi
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_model: str = "kimi-k2.6"

    # 讯飞星火（模型 ID 由账户控制台配置）
    spark_appid: str = ""
    spark_api_key: str = ""
    spark_api_secret: str = ""
    spark_model: str = "spark-v4"

    # 阿里通义千问（DashScope OpenAI 兼容模式）
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen3-max"

    # 百度文心一言
    ernie_api_key: str = ""
    ernie_secret_key: str = ""
    ernie_model: str = ""

    # 智谱ChatGLM
    chatglm_api_key: str = ""
    chatglm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    chatglm_model: str = "glm-4.6"

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    # OpenRouter（聚合多模型，可作为中转站）
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "qwen/qwen3-235b-a22b-instruct"

    # SiliconFlow（硅基流动，可作为中转站）
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_model: str = "Qwen/Qwen3-235B-A22B-Instruct"

    # 火山豆包（字节跳动）
    doubao_api_key: str = ""
    doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    doubao_model: str = "doubao-seed-1-6-250615"

    # 兼容旧配置
    tongyi_api_key: str = ""  # 通义千问（旧）
    tongyi_secret_key: str = ""
    wenxin_api_key: str = ""  # 文心一言（旧）
    wenxin_secret_key: str = ""
    claude_api_key: str = ""  # Claude（旧）

    # 默认使用的模型：custom_openai 为推荐默认，设置页配置并测试成功后即时驱动三大核心功能
    default_model: str = "custom_openai"  # openai/custom_openai/anthropic/gemini/kimi/spark/qwen/ernie/chatglm/deepseek/openrouter/siliconflow/doubao


@dataclass
class VisionConfig:
    """视觉模型渠道配置。模型 ID 以各服务账户权限和 API 测试结果为准。
    自定义 OpenAI 兼容服务（如 GPT-4o 兼容网关）作为默认视觉源，设置页测试成功后即时生效。"""
    # GPT-4V (OpenAI Vision)
    gpt4v_api_key: str = ""
    gpt4v_model: str = "gpt-4o"

    # Claude Vision
    claude_vision_api_key: str = ""
    claude_vision_model: str = "claude-sonnet-5"

    # Google Gemini Vision
    gemini_vision_api_key: str = ""
    gemini_vision_model: str = "gemini-2.5-flash"

    # 通义千问VL
    qwen_vl_api_key: str = ""
    qwen_vl_model: str = "qwen3-vl-plus"

    # 百度视觉
    baidu_vision_api_key: str = ""
    baidu_vision_secret_key: str = ""
    baidu_vision_model: str = ""

    # 腾讯云视觉
    tencent_vision_secret_id: str = ""
    tencent_vision_secret_key: str = ""
    tencent_vision_model: str = ""

    # 讯飞星火视觉
    spark_vision_api_key: str = ""
    spark_vision_model: str = ""

    # 自定义视觉网关（OpenAI 兼容 Vision / VLM，独立于 LLM 和图像生成）
    # 如 GPT-4o 兼容网关、自建 OneAPI/NewAPI 视觉通道、Qwen-VL 代理等
    custom_openai_api_key: str = ""
    custom_openai_base_url: str = ""
    custom_openai_vision_model: str = ""

    # 兼容旧配置
    tongyi_vl_api_key: str = ""  # 通义千问VL（旧）
    openai_vision_api_key: str = ""  # OpenAI Vision（旧）

    # 默认使用的模型：custom_vision → 使用上面的自定义视觉网关配置
    default_model: str = "custom_vision"  # custom_vision/gpt4v/claude_vision/gemini/qwen_vl/baidu/tencent/spark_vision

    # 本地模型选项
    use_local_yolo: bool = True
    use_local_clip: bool = False


@dataclass
class TTSModelConfig:
    """TTS语音模型配置 - 支持主流TTS服务"""
    DEFAULT_TTS_ENGINES = {'edge-tts', 'gtts', 'azure', 'pyttsx3', 'coqui'}
    DEFAULT_TTS_ALIASES = {
        'edge': 'edge-tts',
        'edgetts': 'edge-tts',
        'azure-tts': 'azure',
        'local': 'pyttsx3',
        'offline': 'pyttsx3',
    }
    # Microsoft Azure TTS
    azure_tts_key: str = ""
    azure_tts_region: str = "eastasia"
    # Azure Custom Voice（已训练部署的自定义神经语音）
    azure_custom_endpoint_id: str = ""

    # Edge TTS（免费）
    enable_edge_tts: bool = True
    edge_tts_voice: str = "zh-CN-XiaoxiaoNeural"

    # gTTS（免费）
    enable_gtts: bool = False
    gtts_lang: str = "zh-CN"

    # Fish Audio 云端语音克隆（https://fish.audio）
    fish_audio_api_key: str = ""
    fish_audio_base_url: str = "https://api.fish.audio/v1"

    # MiniMax T2A 云端语音克隆（语音复刻 v2）
    minimax_api_key: str = ""
    minimax_group_id: str = ""
    minimax_base_url: str = "https://api.minimax.chat/v1"

    # 火山引擎语音克隆（字节跳动，声音复刻 2.0）
    volcano_api_key: str = ""
    volcano_app_id: str = ""
    volcano_voice_type: str = ""  # 已训练的火山声音复刻音色 ID

    # 默认使用的常规 TTS：edge-tts/gtts/azure/pyttsx3/coqui
    default_tts: str = "edge-tts"


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

    # 剪映专业版原生草稿根目录；为空时由系统自动检测。
    # 该字段必须在配置模型中声明，才能在重启后保持用户手动确认的目录。
    jianying_draft_path: str = ""

    # 原创解说生产路径只接受真实云端 AI 结果
    strict_ai_results: bool = True


@dataclass
class LocalModelConfig:
    """本地模型设置"""
    # 强制CPU
    force_cpu: bool = False  # 非特殊情况不要打开，打开后，重启生效

    # ASR精度
    asr_precision: str = "float32"  # float32/float16/int8

    # 分辨率限制
    enable_resolution_limit: bool = False  # 开启后，将只能建1080P以上分辨率的视频，但速度会更快，但速度会更快，不建议开启


@dataclass
class ImageGenConfig:
    """AI封面 / 图像生成模型配置。
    支持多种文生图服务：OpenAI DALL-E、阿里云通义万相、百度文心一格、
    腾讯混元生图、智谱CogView、字节豆包生图、
    以及通用自定义 OpenAI 兼容图像生成网关（如 Stability AI、Midjourney API 代理、本地 SD WebUI 等）。"""
    # OpenAI DALL-E 3
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "dall-e-3"

    # 阿里云通义万相（DashScope Image Generation）
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    qwen_model: str = "wanx-v1"

    # 百度文心一格 / 智能绘画
    baidu_api_key: str = ""
    baidu_secret_key: str = ""
    baidu_model: str = "wanxiang-v1"

    # 腾讯混元生图
    tencent_secret_id: str = ""
    tencent_secret_key: str = ""
    tencent_model: str = "hunyuan-image"

    # 智谱 CogView / 智谱生图
    chatglm_api_key: str = ""
    chatglm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    chatglm_model: str = "cogview-4-plus"

    # 字节豆包生图（火山方舟）
    doubao_api_key: str = ""
    doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    doubao_model: str = "seedream-4"

    # MiniMax 日月（M2VGen 图像）
    minimax_api_key: str = ""
    minimax_group_id: str = ""
    minimax_base_url: str = "https://api.minimax.chat/v1"
    minimax_model: str = "speech-2.0"

    # SiliconFlow 聚合图像生成（推荐：SD3 / Flux / 多款模型）
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_model: str = "black-forest-labs/FLUX.1-schnell"

    # OpenRouter 聚合图像生成
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/dall-e-3"

    # 自定义 OpenAI 兼容图像生成网关（如本地 SD WebUI 的 /v1 兼容插件、OneAPI、NewAPI、自建代理）
    custom_openai_name: str = ""
    custom_openai_api_key: str = ""
    custom_openai_base_url: str = ""
    custom_openai_model: str = ""

    # 默认使用的图像生成厂商：推荐 custom_openai，配置好任意兼容网关即可使用
    default_model: str = "custom_openai"

    # 全局默认参数
    default_size: str = "1024x1024"       # 默认尺寸 1024x1024
    default_quality: str = "standard"     # standard / hd
    default_style: str = "vivid"          # vivid / natural
    default_n: int = 1                    # 默认生成数量
    save_dir: str = ""                    # 自定义保存目录（留空则走 output/covers/）


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
        self.image_config = ImageGenConfig()

        self.load_config()
        self.load_censor_words()

    @staticmethod
    def _load_dataclass(config_class, data: Dict[str, Any]):
        allowed_fields = {field.name for field in fields(config_class)}
        return config_class(**{key: value for key, value in data.items() if key in allowed_fields})

    def load_config(self):
        """加载配置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # 加载各个配置
                if 'llm' in data:
                    self.llm_config = self._load_dataclass(LLMConfig, data['llm'])
                if 'vision' in data:
                    self.vision_config = self._load_dataclass(VisionConfig, data['vision'])
                if 'tts_model' in data:
                    self.tts_model_config = self._load_dataclass(TTSModelConfig, data['tts_model'])
                if 'proxy' in data:
                    self.proxy_config = self._load_dataclass(ProxyConfig, data['proxy'])
                if 'tts' in data:
                    self.tts_config = self._load_dataclass(TTSConfig, data['tts'])
                if 'censor' in data:
                    self.censor_config = self._load_dataclass(CensorConfig, data['censor'])
                if 'global' in data:
                    self.global_config = self._load_dataclass(GlobalConfig, data['global'])
                if 'local_model' in data:
                    self.local_model_config = self._load_dataclass(LocalModelConfig, data['local_model'])
                if 'image' in data:
                    self.image_config = self._load_dataclass(ImageGenConfig, data['image'])

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
                'local_model': asdict(self.local_model_config),
                'image': asdict(self.image_config)
            }

            config_dir = os.path.dirname(os.path.abspath(self.config_file))
            fd, temporary_file = tempfile.mkstemp(prefix='ai_config_', suffix='.tmp', dir=config_dir, text=True)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temporary_file, self.config_file)
            finally:
                if os.path.exists(temporary_file):
                    os.unlink(temporary_file)

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

    def normalize_llm_provider(self, provider: Optional[str] = None) -> str:
        """将前端和旧版配置中的 LLM 标识统一为规范 provider。

        支持三类输入，最终都映射到 fields_by_provider 可识别的服务名：
        1) 前端 brand-based：alibaba / google / baidu / zhipu / iflytek / minimax / bytedance / custom-llm ...
        2) 旧版 model_id（qwen-max、gpt-4o 等）由 commentary_routes_enhanced 在入口归一化
        3) 已规范化的服务名：custom_openai / qwen / gemini / ernie / chatglm / spark / kimi / doubao ...
        """
        value = (provider or self.llm_config.default_model or '').strip().lower().replace('-', '_')
        aliases = {
            # ---------- 服务名（自映射，确保不变） ----------
            'openai': 'openai',
            'custom_openai': 'custom_openai', 'openai_compatible': 'custom_openai',
            'anthropic': 'anthropic', 'claude': 'anthropic',
            'gemini': 'gemini', 'google': 'gemini',
            'kimi': 'kimi', 'moonshot': 'kimi', 'minimax': 'kimi',
            'qwen': 'qwen', 'tongyi': 'qwen', 'qianwen': 'qwen', 'alibaba': 'qwen',
            'chatglm': 'chatglm', 'glm': 'chatglm', 'zhipu': 'chatglm',
            'deepseek': 'deepseek',
            'openrouter': 'openrouter', 'open_router': 'openrouter',
            'siliconflow': 'siliconflow', 'silicon_flow': 'siliconflow',
            'doubao': 'doubao', 'bytedance': 'doubao', 'volcano': 'doubao', 'huoshan': 'doubao',
            'spark': 'spark', 'iflytek': 'spark', 'xinghuo': 'spark',
            'ernie': 'ernie', 'wenxin': 'ernie', 'baidu': 'ernie',
            'tencent': 'tencent', 'hunyuan': 'tencent',
            # ---------- 前端 custom-llm（normalize 后变 custom_llm） ----------
            'custom': 'custom_openai', 'custom_llm': 'custom_openai',
        }
        # 先精确匹配，再前缀兜底（兜底 qwen-max-2025、gpt-4o-2024 等）
        if value in aliases:
            return aliases[value]
        prefix_fallbacks = [
            ('gpt', 'openai'), ('claude', 'anthropic'), ('gemini', 'gemini'),
            ('qwen', 'qwen'), ('ernie', 'ernie'), ('wenxin', 'ernie'), ('baidu', 'ernie'),
            ('glm', 'chatglm'), ('chatglm', 'chatglm'), ('zhipu', 'chatglm'),
            ('deepseek', 'deepseek'), ('kimi', 'kimi'), ('moonshot', 'kimi'),
            ('spark', 'spark'), ('xinghuo', 'spark'), ('iflytek', 'spark'),
            ('doubao', 'doubao'), ('hunyuan', 'tencent'),
            ('openrouter', 'openrouter'), ('siliconflow', 'siliconflow'),
            ('alibaba', 'qwen'), ('bytedance', 'doubao'), ('volcano', 'doubao'),
            ('custom', 'custom_openai'),
        ]
        for prefix, svc in prefix_fallbacks:
            if value.startswith(prefix):
                return svc
        return value

    def get_llm_connection(self, provider: Optional[str] = None) -> Dict[str, Optional[str]]:
        """获取规范 provider 的密钥、模型和基础地址。
        base_url 统一使用 normalize_base_url 规范化（去尾斜杠、自动补 /v1，避免 /v1/v1）。"""
        normalized = self.normalize_llm_provider(provider)
        config = self.llm_config
        fields_by_provider = {
            'openai': ('openai_api_key', 'openai_model', 'openai_base_url'),
            'custom_openai': ('custom_openai_api_key', 'custom_openai_model', 'custom_openai_base_url'),
            'anthropic': ('anthropic_api_key', 'anthropic_model', 'anthropic_base_url'),
            'gemini': ('gemini_api_key', 'gemini_model', 'gemini_base_url'),
            'kimi': ('kimi_api_key', 'kimi_model', 'kimi_base_url'),
            'qwen': ('qwen_api_key', 'qwen_model', 'qwen_base_url'),
            'chatglm': ('chatglm_api_key', 'chatglm_model', 'chatglm_base_url'),
            'deepseek': ('deepseek_api_key', 'deepseek_model', 'deepseek_base_url'),
            'openrouter': ('openrouter_api_key', 'openrouter_model', 'openrouter_base_url'),
            'siliconflow': ('siliconflow_api_key', 'siliconflow_model', 'siliconflow_base_url'),
            'doubao': ('doubao_api_key', 'doubao_model', 'doubao_base_url'),
            'spark': ('spark_api_key', 'spark_model', None),
            'ernie': ('ernie_api_key', 'ernie_model', None),
        }
        key_field, model_field, base_field = fields_by_provider.get(normalized, (None, None, None))
        key = getattr(config, key_field, '') if key_field else ''
        if normalized == 'qwen':
            key = key or config.tongyi_api_key
        elif normalized == 'ernie':
            key = key or config.wenxin_api_key
        elif normalized == 'anthropic':
            key = key or config.claude_api_key
        raw_base = getattr(config, base_field, None) if base_field else None
        base_url = self.normalize_base_url(raw_base) if raw_base else None
        return {
            'provider': normalized,
            'api_key': key,
            'model': getattr(config, model_field, '') if model_field else '',
            'base_url': base_url,
        }

    def get_llm_api_key(self, model: Optional[str] = None) -> Optional[str]:
        """获取规范化后的 LLM API 密钥。"""
        return self.get_llm_connection(model)['api_key']

    def normalize_vision_provider(self, provider: Optional[str] = None) -> str:
        """统一视觉模型的连字符、下划线和旧版别名。

        支持三类输入，最终映射到可识别的视觉服务名：
        1) 前端 brand-based：alibaba / google / baidu / zhipu / anthropic / custom-vision ...
        2) 旧版 model_id（qwen-vl-max、gpt-4v 等）由 commentary_routes_enhanced 在入口归一化
        3) 已规范化服务名：gpt4v / qwen_vl / gemini_vision / claude_vision / baidu_vision / custom_vision ...

        注意：custom_openai 不自动映射到 custom_vision —— 这样 LLM / Vision / Image
        三类 custom_openai 调用路径完全独立，避免封面生成和视觉分析共用同一网关配置。
        """
        value = (provider or self.vision_config.default_model or '').strip().lower().replace('-', '_')
        aliases = {
            # ---------- 服务名（自映射） ----------
            'gpt4v': 'gpt4v', 'openai_vision': 'gpt4v', 'openai': 'gpt4v',
            'claude_vision': 'claude_vision', 'anthropic_vision': 'claude_vision',
            'anthropic': 'claude_vision', 'claude': 'claude_vision',
            'gemini_vision': 'gemini_vision', 'gemini': 'gemini_vision', 'google': 'gemini_vision',
            'chatglm': 'chatglm', 'chatglm_vision': 'chatglm', 'zhipu_vision': 'chatglm',
            'baidu_vision': 'baidu_vision', 'baidu': 'baidu_vision',
            'wenxin': 'baidu_vision', 'wenxin_vision': 'baidu_vision', 'ernie_vision': 'baidu_vision',
            'tencent_vision': 'tencent_vision', 'tencent': 'tencent_vision', 'hunyuan_vision': 'tencent_vision',
            'spark_vision': 'spark_vision', 'spark': 'spark_vision', 'iflytek_vision': 'spark_vision',
            'doubao_vision': 'doubao_vision', 'bytedance_vision': 'doubao_vision',
            'bytedance': 'doubao_vision', 'volcano_vision': 'doubao_vision', 'huoshan_vision': 'doubao_vision',
            'qwen_vl': 'qwen_vl', 'tongyi_vl': 'qwen_vl', 'qianwen_vl': 'qwen_vl', 'alibaba': 'qwen_vl',
            # ---------- 自定义视觉：独立配置，不复用 LLM 的 custom_openai ----------
            'custom_vision': 'custom_vision', 'custom_openai_vision': 'custom_vision',
            'custom': 'custom_vision',
        }
        if value in aliases:
            return aliases[value]
        # 前缀兜底
        if value.startswith('qwen_vl'):
            return 'qwen_vl'
        if value.startswith('gemini_vision') or value.startswith('gemini'):
            return 'gemini_vision'
        if value.startswith('claude_vision') or value.startswith('claude'):
            return 'claude_vision'
        if value.startswith(('glm_', 'chatglm_', 'zhipu_')):
            return 'chatglm'
        if value.startswith('gpt4v') or value.startswith('gpt'):
            return 'gpt4v'
        if value.startswith(('baidu', 'wenxin', 'ernie')):
            return 'baidu_vision'
        if value.startswith(('tencent', 'hunyuan')):
            return 'tencent_vision'
        if value.startswith(('spark', 'iflytek', 'xinghuo')):
            return 'spark_vision'
        if value.startswith(('doubao', 'bytedance', 'volcano', 'huoshan')):
            return 'doubao_vision'
        if value.startswith('custom'):
            return 'custom_vision'
        return value

    def get_vision_api_key(self, model: Optional[str] = None) -> Optional[str]:
        """获取规范化后的视觉模型 API 密钥。优先读视觉专属配置，缺失才回退 LLM 同名厂商的 Key 做兼容。"""
        normalized = self.normalize_vision_provider(model)
        config = self.vision_config
        llm_config = self.llm_config
        key_map = {
            'gpt4v': (
                config.gpt4v_api_key or config.openai_vision_api_key
                or llm_config.openai_api_key
            ),
            'claude_vision': (
                config.claude_vision_api_key or llm_config.anthropic_api_key
                or llm_config.claude_api_key
            ),
            'gemini_vision': config.gemini_vision_api_key or llm_config.gemini_api_key,
            'qwen_vl': (
                config.qwen_vl_api_key or config.tongyi_vl_api_key
                or llm_config.qwen_api_key or llm_config.tongyi_api_key
            ),
            'chatglm': llm_config.chatglm_api_key,
            'baidu_vision': config.baidu_vision_api_key or llm_config.ernie_api_key or llm_config.wenxin_api_key,
            'tencent_vision': (
                config.tencent_vision_secret_id
                or getattr(llm_config, 'tencent_api_key', '')
            ),
            'spark_vision': config.spark_vision_api_key or llm_config.spark_api_key,
            'doubao_vision': (
                llm_config.doubao_api_key
                or getattr(llm_config, 'bytedance_api_key', '')
            ),
            # 自定义视觉：使用 VISION 专属 custom_openai_api_key（不再复用 LLM 的，避免三类配置混淆）
            'custom_vision': (
                config.custom_openai_api_key
                or llm_config.custom_openai_api_key  # 向后兼容：旧用户可能只配了 LLM 自定义
            ),
        }
        return key_map.get(normalized)

    def get_vision_base_url(self, model: Optional[str] = None) -> Optional[str]:
        """获取视觉模型对应的基础地址。custom_vision 使用视觉专属 custom_openai_base_url。"""
        normalized = self.normalize_vision_provider(model)
        config = self.vision_config
        llm_config = self.llm_config
        url_map = {
            'gpt4v': llm_config.openai_base_url,
            'claude_vision': llm_config.anthropic_base_url,
            'gemini_vision': llm_config.gemini_base_url,
            'qwen_vl': llm_config.qwen_base_url,
            'chatglm': llm_config.chatglm_base_url,
            'baidu_vision': (
                getattr(llm_config, 'ernie_base_url', '')
                or getattr(llm_config, 'wenxin_base_url', '')
            ),
            'tencent_vision': getattr(llm_config, 'tencent_base_url', ''),
            'spark_vision': getattr(llm_config, 'spark_base_url', ''),
            'doubao_vision': (
                llm_config.doubao_base_url
                or getattr(llm_config, 'bytedance_base_url', '')
            ),
            # 自定义视觉：使用 VISION 专属 custom_openai_base_url，不再复用 LLM 自定义
            'custom_vision': (
                config.custom_openai_base_url
                or llm_config.custom_openai_base_url  # 向后兼容：旧用户可能只配了 LLM
            ),
        }
        return url_map.get(normalized)

    def get_vision_model(self, model: Optional[str] = None) -> str:
        """获取视觉模型名。custom_vision 使用视觉专属 custom_openai_vision_model。"""
        normalized = self.normalize_vision_provider(model)
        config = self.vision_config
        llm_config = self.llm_config
        model_map = {
            'gpt4v': config.gpt4v_model,
            'claude_vision': config.claude_vision_model,
            'gemini_vision': config.gemini_vision_model,
            'qwen_vl': config.qwen_vl_model,
            'baidu_vision': config.baidu_vision_model or llm_config.ernie_model,
            'tencent_vision': config.tencent_vision_model or getattr(llm_config, 'tencent_model', ''),
            'spark_vision': config.spark_vision_model or llm_config.spark_model,
            'chatglm': llm_config.chatglm_model,
            'doubao_vision': (
                llm_config.doubao_model
                or getattr(llm_config, 'bytedance_model', '')
            ),
            # 视觉专属自定义模型（默认 gpt-4o 级别的视觉模型）
            'custom_vision': (
                config.custom_openai_vision_model
                or llm_config.custom_openai_model
                or config.gpt4v_model
            ),
        }
        return model_map.get(normalized, '')

    def get_vision_connection(self, provider: Optional[str] = None) -> Dict[str, Any]:
        """统一获取视觉模型连接信息（结构化：api_key / model / base_url / provider）。

        三类模型调用路径严格区分：
        - LLM 文案（文本）    → get_llm_connection   → 走 LLMConfig.custom_openai_*
        - Vision 画面分析（视觉）→ get_vision_connection → 走 VisionConfig.custom_openai_*
        - Image 封面生成（图像）→ get_image_connection  → 走 ImageGenConfig.custom_openai_*
        """
        from copy import deepcopy
        normalized = self.normalize_vision_provider(provider)
        config = self.vision_config
        conn: Dict[str, Any] = {
            'provider': normalized,
            'api_key': self.get_vision_api_key(provider),
            'base_url': self.normalize_base_url(self.get_vision_base_url(provider)) if self.get_vision_base_url(provider) else None,
            'model': self.get_vision_model(provider),
        }
        if normalized == 'baidu_vision':
            conn['secret_key'] = config.baidu_vision_secret_key
        elif normalized == 'tencent_vision':
            conn['secret_id'] = config.tencent_vision_secret_id
            conn['secret_key'] = config.tencent_vision_secret_key
        return conn

    # -----------------------------
    # 公共辅助：Base URL 规范化（去尾斜杠 + 自动补 /v1，避免 /v1/v1 重复）
    # -----------------------------
    @staticmethod
    def normalize_base_url(raw_url: Optional[str]) -> str:
        """Base URL 规范化：
        1) 去掉首尾空白；
        2) 去掉所有末尾斜杠；
        3) 如果路径不包含 /v1 且不以 /v1 结尾，则自动补 /v1（OneAPI/NewAPI/OpenAI 兼容的默认约定）；
        4) 返回规范化结果。

        不会出现 /v1/v1 重复：只有原始 URL 里完全不包含 /v1 才补。
        """
        if not raw_url:
            return ''
        s = str(raw_url).strip()
        if not s:
            return ''
        # 1. 末尾斜杠全部去掉
        while s.endswith('/'):
            s = s[:-1]
        if not s:
            return ''
        # 2. 协议和 host 部分可能没有 /v1，也不需要补（裸 host 如 https://api.example.com）
        #    只有 host 后面为空（=无 path，即 s 只含 2 个斜杠）时，补 /v1
        #    或 path 中不含 /v1 时补 /v1
        try:
            from urllib.parse import urlparse
            u = urlparse(s)
            path = (u.path or '').rstrip('/')
            # 如果 path 里没有 /v1 或不是裸路径，则补 /v1
            has_v1 = ('/v1' in path) or path.endswith('/v1')
            if not has_v1:
                s = s.rstrip('/') + '/v1'
        except Exception:
            # urlparse 失败则走简单兜底：看字符串有没有 /v1
            if '/v1' not in s:
                s = s.rstrip('/') + '/v1'
        return s

    # ===================== 封面图像生成配置辅助方法 =====================

    def normalize_image_provider(self, provider: Optional[str] = None) -> str:
        """统一封面生成厂商标识：别名、大小写、连字符归一化。"""
        value = (provider or self.image_config.default_model or '').strip().lower().replace('-', '_')
        aliases = {
            'dall_e': 'openai', 'dalle': 'openai', 'openai': 'openai',
            'wanx': 'qwen', 'tongyi_wanxiang': 'qwen', 'qwen': 'qwen', 'aliyun': 'qwen',
            'wenxin': 'baidu', 'yige': 'baidu', 'baidu': 'baidu', 'ernie_image': 'baidu',
            'hunyuan': 'tencent', 'tencent': 'tencent',
            'cogview': 'chatglm', 'zhipu': 'chatglm', 'chatglm': 'chatglm',
            'seedream': 'doubao', 'huoshan': 'doubao', 'volcano': 'doubao', 'doubao': 'doubao', 'bytedance': 'doubao',
            'minimax': 'minimax', 'moonshot_image': 'minimax',
            'siliconflow': 'siliconflow', 'sf': 'siliconflow',
            'openrouter': 'openrouter',
            'custom': 'custom_openai', 'custom_openai': 'custom_openai', 'self_host': 'custom_openai',
            'sd': 'custom_openai', 'stable_diffusion': 'custom_openai', 'sd_webui': 'custom_openai',
        }
        normalized = aliases.get(value, value)
        # 前缀兜底
        for prefix in ('dall', 'gpt_image', 'openai'):
            if normalized.startswith(prefix):
                return 'openai'
        if normalized.startswith(('wanx', 'tongyi', 'qwen', 'aliyun')):
            return 'qwen'
        if normalized.startswith(('wenxin', 'yige', 'baidu', 'ernie')):
            return 'baidu'
        if normalized.startswith(('hunyuan', 'tencent')):
            return 'tencent'
        if normalized.startswith(('cogview', 'zhipu', 'chatglm', 'glm')):
            return 'chatglm'
        if normalized.startswith(('seedream', 'doubao', 'huoshan', 'volcano', 'bytedance')):
            return 'doubao'
        if normalized.startswith('minimax'):
            return 'minimax'
        if normalized.startswith('silicon'):
            return 'siliconflow'
        if normalized.startswith('openrouter'):
            return 'openrouter'
        return normalized

    def get_image_connection(self, provider: Optional[str] = None) -> Dict[str, Any]:
        """获取封面生成厂商的连接信息：api_key / model / base_url / group_id 等。"""
        normalized = self.normalize_image_provider(provider)
        cfg = self.image_config
        # 按厂商返回连接配置；字段与 ImageGenConfig 保持一致
        conn_map = {
            'openai': {
                'provider': 'openai',
                'api_key': cfg.openai_api_key,
                'model': cfg.openai_model,
                'base_url': cfg.openai_base_url,
            },
            'qwen': {
                'provider': 'qwen',
                'api_key': cfg.qwen_api_key,
                'model': cfg.qwen_model,
                'base_url': cfg.qwen_base_url,
            },
            'baidu': {
                'provider': 'baidu',
                'api_key': cfg.baidu_api_key,
                'secret_key': cfg.baidu_secret_key,
                'model': cfg.baidu_model,
                'base_url': None,  # 百度走 AK/SK 获取 token，不需要 base_url
            },
            'tencent': {
                'provider': 'tencent',
                'secret_id': cfg.tencent_secret_id,
                'secret_key': cfg.tencent_secret_key,
                'model': cfg.tencent_model,
            },
            'chatglm': {
                'provider': 'chatglm',
                'api_key': cfg.chatglm_api_key,
                'model': cfg.chatglm_model,
                'base_url': cfg.chatglm_base_url,
            },
            'doubao': {
                'provider': 'doubao',
                'api_key': cfg.doubao_api_key,
                'model': cfg.doubao_model,
                'base_url': cfg.doubao_base_url,
            },
            'minimax': {
                'provider': 'minimax',
                'api_key': cfg.minimax_api_key,
                'group_id': cfg.minimax_group_id,
                'model': cfg.minimax_model,
                'base_url': cfg.minimax_base_url,
            },
            'siliconflow': {
                'provider': 'siliconflow',
                'api_key': cfg.siliconflow_api_key,
                'model': cfg.siliconflow_model,
                'base_url': cfg.siliconflow_base_url,
            },
            'openrouter': {
                'provider': 'openrouter',
                'api_key': cfg.openrouter_api_key,
                'model': cfg.openrouter_model,
                'base_url': cfg.openrouter_base_url,
            },
            'custom_openai': {
                'provider': 'custom_openai',
                'display_name': cfg.custom_openai_name,
                'api_key': cfg.custom_openai_api_key,
                'model': cfg.custom_openai_model,
                'base_url': cfg.custom_openai_base_url,
            },
        }
        conn = conn_map.get(normalized)
        if not conn:
            # 未识别厂商，默认走 custom_openai
            conn = dict(conn_map['custom_openai'])
            conn['provider'] = normalized
        # Base URL 统一规范化：去尾斜杠、缺 /v1 自动补，防止 /v1/v1 重复
        if conn.get('base_url'):
            conn['base_url'] = self.normalize_base_url(conn['base_url'])
        # 注入全局默认参数
        conn.setdefault('default_size', cfg.default_size)
        conn.setdefault('default_quality', cfg.default_quality)
        conn.setdefault('default_style', cfg.default_style)
        conn.setdefault('default_n', cfg.default_n)
        conn.setdefault('save_dir', cfg.save_dir)
        return conn

    def get_image_api_key(self, provider: Optional[str] = None) -> Optional[str]:
        """快速获取封面图像生成的 API Key（用于设置页连通性测试）。"""
        conn = self.get_image_connection(provider)
        key = conn.get('api_key') or conn.get('secret_id') or conn.get('appid')
        return key

    def get_tts_config(self, tts_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取TTS配置 - 支持所有TTS服务"""
        tts_type = tts_type or self.tts_model_config.default_tts

        config_map = {
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
                'local_model': asdict(self.local_model_config),
                'image': asdict(self.image_config)
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
                self.llm_config = self._load_dataclass(LLMConfig, data['llm'])
            if 'vision' in data:
                self.vision_config = self._load_dataclass(VisionConfig, data['vision'])
            if 'tts_model' in data:
                self.tts_model_config = self._load_dataclass(TTSModelConfig, data['tts_model'])
            if 'proxy' in data:
                self.proxy_config = self._load_dataclass(ProxyConfig, data['proxy'])
            if 'tts' in data:
                self.tts_config = self._load_dataclass(TTSConfig, data['tts'])
            if 'censor' in data:
                self.censor_config = self._load_dataclass(CensorConfig, data['censor'])
            if 'global' in data:
                self.global_config = self._load_dataclass(GlobalConfig, data['global'])
            if 'local_model' in data:
                self.local_model_config = self._load_dataclass(LocalModelConfig, data['local_model'])
            if 'image' in data:
                self.image_config = self._load_dataclass(ImageGenConfig, data['image'])

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
