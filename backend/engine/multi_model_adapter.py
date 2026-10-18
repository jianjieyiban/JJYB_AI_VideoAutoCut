"""
多模型适配器
支持通义千问、文心一言、ChatGLM、DeepSeek、OpenAI、Claude、Gemini等
"""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod

from backend.config.ai_config import AIConfigurationError, AIRequestError

logger = logging.getLogger('JJYB_AI智剪')


class BaseModelAdapter(ABC):
    """模型适配器基类"""

    def __init__(self, api_key: str, **kwargs):
        self.api_key = api_key
        self.kwargs = kwargs
        self.logger = logger

    @abstractmethod
    def generate_text(self, prompt: str, **kwargs) -> str:
        """生成文本"""
        pass

    @abstractmethod
    def analyze_image(self, image_path: str, prompt: str, **kwargs) -> str:
        """分析图像"""
        pass


class TongyiAdapter(BaseModelAdapter):
    """通义千问适配器"""

    def __init__(self, api_key: str, **kwargs):
        super().__init__(api_key, **kwargs)
        self.client = None
        self._init_client()

    def _init_client(self):
        """初始化客户端"""
        try:
            import dashscope
            dashscope.api_key = self.api_key
            self.client = dashscope
            self.logger.info("✅ 通义千问客户端初始化成功")
        except Exception as e:
            self.logger.error(f"❌ 通义千问客户端初始化失败: {e}")

    def generate_text(self, prompt: str, **kwargs) -> str:
        """生成文本"""
        if not self.client:
            raise Exception("通义千问客户端未初始化")

        try:
            from dashscope import Generation

            response = Generation.call(
                model=self.kwargs.get('model', 'qwen-plus'),
                prompt=prompt,
                **kwargs
            )

            if response.status_code == 200:
                return response.output.text
            else:
                raise Exception(f"API调用失败: {response.message}")

        except Exception as e:
            self.logger.error(f"❌ 通义千问文本生成失败: {e}")
            raise

    def analyze_image(self, image_path: str, prompt: str, **kwargs) -> str:
        """分析图像"""
        if not self.client:
            raise Exception("通义千问客户端未初始化")

        try:
            from dashscope import MultiModalConversation

            # 构造本地文件的 file:// URI。
            # 注意：dashscope SDK 内部会简单地把前缀 "file://" 去掉再按本地路径读取；
            # 在 Windows 上，如果传入 pathlib.as_uri() 得到 "file:///F:/..."，
            # 它去掉前缀后会变成 "/F:/..."，导致找不到文件。
            # 因此这里对 Windows 做专门处理，保证最终传给 SDK 的实际文件路径是 "F:/..."。
            try:
                p = Path(image_path).resolve()
                if os.name == 'nt':
                    # Windows: 生成类似 file://F:/path/to/img.jpg 的形式
                    path_str = p.as_posix()
                    img_uri = f'file://{path_str}'
                else:
                    # POSIX: 直接使用合法的 file:///path 形式
                    img_uri = p.as_uri()
            except Exception:
                # 兜底：保持与旧版本一致的简单拼接（使用原始路径字符串）
                img_uri = f'file://{image_path}'

            messages = [{
                'role': 'user',
                'content': [
                    {'image': img_uri},
                    {'text': prompt}
                ]
            }]

            response = MultiModalConversation.call(
                model=self.kwargs.get('vision_model', 'qwen3-vl-plus'),
                messages=messages,
                **kwargs
            )

            if response.status_code == 200:
                return response.output.choices[0].message.content
            else:
                raise Exception(f"API调用失败: {response.message}")

        except Exception as e:
            self.logger.error(f"❌ 通义千问图像分析失败: {e}")
            raise


class WenxinAdapter(BaseModelAdapter):
    """文心一言适配器"""

    def __init__(self, api_key: str, secret_key: str, **kwargs):
        super().__init__(api_key, **kwargs)
        self.secret_key = secret_key
        self.access_token = None
        self._get_access_token()

    def _get_access_token(self):
        """获取access token"""
        try:
            import requests

            url = f"https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={self.api_key}&client_secret={self.secret_key}"
            response = requests.post(url)

            if response.status_code == 200:
                self.access_token = response.json().get('access_token')
                self.logger.info("✅ 文心一言access token获取成功")
            else:
                raise Exception(f"获取access token失败: {response.text}")

        except Exception as e:
            self.logger.error(f"❌ 文心一言access token获取失败: {e}")

    def generate_text(self, prompt: str, **kwargs) -> str:
        """生成文本"""
        if not self.access_token:
            raise Exception("文心一言access token未获取")

        try:
            import requests

            url = f"https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions?access_token={self.access_token}"

            payload = {
                "messages": [{"role": "user", "content": prompt}],
                **kwargs
            }

            response = requests.post(url, json=payload)

            if response.status_code == 200:
                return response.json().get('result', '')
            else:
                raise Exception(f"API调用失败: {response.text}")

        except Exception as e:
            self.logger.error(f"❌ 文心一言文本生成失败: {e}")
            raise

    def analyze_image(self, image_path: str, prompt: str, **kwargs) -> str:
        """分析图像"""
        # 文心一言的图像分析功能
        raise NotImplementedError("文心一言图像分析功能待实现")


class ChatGLMAdapter(BaseModelAdapter):
    """ChatGLM适配器"""

    def __init__(self, api_key: str, base_url: str = "", **kwargs):
        super().__init__(api_key, **kwargs)
        self.base_url = base_url
        self.client = None
        self._init_client()

    def _init_client(self):
        """初始化客户端"""
        try:
            from zhipuai import ZhipuAI
            client_kwargs = {'api_key': self.api_key}
            if self.base_url:
                client_kwargs['base_url'] = self.base_url
            self.client = ZhipuAI(**client_kwargs)
            self.logger.info("✅ ChatGLM客户端初始化成功")
        except Exception as e:
            self.logger.error(f"❌ ChatGLM客户端初始化失败: {e}")

    def generate_text(self, prompt: str, **kwargs) -> str:
        """生成文本"""
        if not self.client:
            raise Exception("ChatGLM客户端未初始化")

        try:
            response = self.client.chat.completions.create(
                model=self.kwargs.get('model', 'glm-4-flash'),
                messages=[{"role": "user", "content": prompt}],
                **kwargs
            )

            return response.choices[0].message.content

        except Exception as e:
            self.logger.error(f"❌ ChatGLM文本生成失败: {e}")
            raise

    def analyze_image(self, image_path: str, prompt: str, **kwargs) -> str:
        """使用智谱原生客户端发起视觉请求。"""
        if not self.client:
            raise AIConfigurationError()

        try:
            import base64

            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            model = kwargs.pop('model', self.kwargs.get('vision_model') or self.kwargs.get('model'))
            response = self.client.chat.completions.create(
                model=model,
                messages=[{
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': prompt},
                        {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{image_data}'}},
                    ],
                }],
                **kwargs,
            )
            return response.choices[0].message.content
        except Exception as exc:
            self.logger.error('❌ ChatGLM 图像分析失败: %s', exc)
            raise AIRequestError() from exc


class OpenAICompatibleAdapter(BaseModelAdapter):
    """通用 OpenAI-compatible 适配器。"""

    def __init__(self, api_key: str, base_url: str, model: str, **kwargs):
        super().__init__(api_key, **kwargs)
        self.base_url = base_url
        self.model = model
        self.client = None
        self._init_client()

    def _init_client(self):
        """初始化客户端"""
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            self.logger.info("✅ OpenAI-compatible客户端初始化成功")
        except Exception:
            self.logger.error("OpenAI-compatible 客户端初始化失败")

    def generate_text(self, prompt: str, **kwargs) -> str:
        """生成文本"""
        if not self.client:
            raise AIConfigurationError()

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                **kwargs
            )
            return response.choices[0].message.content
        except Exception as exc:
            self.logger.error("OpenAI-compatible 文本请求失败")
            raise AIRequestError() from exc

    def analyze_image(self, image_path: str, prompt: str, **kwargs) -> str:
        """分析图像：OpenAI 兼容网关通常同时支持 Chat 与 Vision（如 GPT-4o 兼容服务）。
        复用同一 base_url / api_key / model；若服务方不支持视觉，将由上层捕获异常。"""
        if not self.client:
            raise AIConfigurationError()

        try:
            import base64
            import mimetypes

            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            mime = mimetypes.guess_type(image_path)[0] or 'image/jpeg'

            model = kwargs.pop('model', self.model)
            response = self.client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_data}"}}
                    ]
                }],
                **kwargs
            )
            return response.choices[0].message.content
        except Exception as exc:
            self.logger.error("OpenAI-compatible 图像分析失败: %s", exc, exc_info=True)
            raise AIRequestError() from exc


class OpenAIAdapter(BaseModelAdapter):
    """OpenAI适配器"""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", **kwargs):
        super().__init__(api_key, **kwargs)
        self.base_url = base_url
        self.client = None
        self._init_client()

    def _init_client(self):
        """初始化客户端"""
        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
            self.logger.info("✅ OpenAI客户端初始化成功")
        except Exception as e:
            self.logger.error(f"❌ OpenAI客户端初始化失败: {e}")

    def generate_text(self, prompt: str, model: str = "gpt-4.1-mini", **kwargs) -> str:
        """生成文本"""
        if not self.client:
            raise Exception("OpenAI客户端未初始化")

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                **kwargs
            )

            return response.choices[0].message.content

        except Exception as e:
            self.logger.error(f"❌ OpenAI文本生成失败: {e}")
            raise

    def analyze_image(self, image_path: str, prompt: str, model: str = "gpt-4o-mini", **kwargs) -> str:
        """分析图像"""
        if not self.client:
            raise Exception("OpenAI客户端未初始化")

        try:
            import base64

            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            response = self.client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
                    ]
                }],
                **kwargs
            )

            return response.choices[0].message.content

        except Exception as e:
            self.logger.error(f"❌ OpenAI图像分析失败: {e}")
            raise


class ClaudeAdapter(BaseModelAdapter):
    """Claude适配器"""

    def __init__(self, api_key: str, base_url: str = "", **kwargs):
        super().__init__(api_key, **kwargs)
        self.base_url = base_url
        self.client = None
        self._init_client()

    def _init_client(self):
        """初始化客户端"""
        try:
            import anthropic
            client_kwargs = {'api_key': self.api_key}
            if self.base_url:
                client_kwargs['base_url'] = self.base_url
            self.client = anthropic.Anthropic(**client_kwargs)
            self.logger.info("✅ Claude客户端初始化成功")
        except Exception as e:
            self.logger.error(f"❌ Claude客户端初始化失败: {e}")

    def generate_text(self, prompt: str, model: str = "claude-sonnet-4-6", **kwargs) -> str:
        """生成文本"""
        if not self.client:
            raise Exception("Claude客户端未初始化")

        try:
            message = self.client.messages.create(
                model=model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
                **kwargs
            )

            return message.content[0].text

        except Exception as e:
            self.logger.error(f"❌ Claude文本生成失败: {e}")
            raise

    def analyze_image(self, image_path: str, prompt: str, model: str = "claude-sonnet-4-6", **kwargs) -> str:
        """分析图像"""
        if not self.client:
            raise Exception("Claude客户端未初始化")

        try:
            import base64

            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')

            message = self.client.messages.create(
                model=model,
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
                        {"type": "text", "text": prompt}
                    ]
                }],
                **kwargs
            )

            return message.content[0].text

        except Exception as e:
            self.logger.error(f"❌ Claude图像分析失败: {e}")
            raise


class GeminiAdapter(BaseModelAdapter):
    """Gemini适配器"""

    def __init__(self, api_key: str, base_url: str = "", **kwargs):
        super().__init__(api_key, **kwargs)
        self.base_url = base_url
        self.client = None
        self._init_client()

    def _init_client(self):
        """初始化客户端"""
        try:
            import google.generativeai as genai
            configure_kwargs = {'api_key': self.api_key}
            if self.base_url:
                configure_kwargs['client_options'] = {'api_endpoint': self.base_url}
            genai.configure(**configure_kwargs)
            self.client = genai
            self.logger.info("✅ Gemini客户端初始化成功")
        except Exception as e:
            self.logger.error(f"❌ Gemini客户端初始化失败: {e}")

    def generate_text(self, prompt: str, model: str = "gemini-2.0-flash", **kwargs) -> str:
        """生成文本"""
        if not self.client:
            raise Exception("Gemini客户端未初始化")

        try:
            model_instance = self.client.GenerativeModel(model)
            response = model_instance.generate_content(prompt, **kwargs)
            return response.text

        except Exception as e:
            self.logger.error(f"❌ Gemini文本生成失败: {e}")
            raise

    def analyze_image(self, image_path: str, prompt: str, model: str = "gemini-2.0-flash", **kwargs) -> str:
        """分析图像"""
        if not self.client:
            raise Exception("Gemini客户端未初始化")

        try:
            from PIL import Image

            img = Image.open(image_path)
            model_instance = self.client.GenerativeModel(model)
            response = model_instance.generate_content([prompt, img], **kwargs)
            return response.text

        except Exception as e:
            self.logger.error(f"❌ Gemini图像分析失败: {e}")
            raise


class AnnaHostSamplingAdapter(BaseModelAdapter):
    """Anna 平台宿主 LLM 适配器（MCP sampling 反向 RPC）。

    全新安装、用户未配置任何模型密钥时，AI 能力（文案生成 + 画面理解）
    由 Anna 平台内置大模型驱动，开箱即用；反向 RPC 通道由 Executa 插件
    在 initialize 协商后注入 backend.engine.anna_host_llm。
    用户配置了自己的密钥时，工厂优先使用用户配置。
    """

    def __init__(self, **kwargs):
        super().__init__(api_key='anna-host-llm', **kwargs)

    @staticmethod
    def available() -> bool:
        try:
            from backend.engine import anna_host_llm
            return anna_host_llm.is_host_llm_available()
        except Exception:
            return False

    def generate_text(self, prompt: str, **kwargs) -> str:
        from backend.engine.anna_host_llm import sample_text
        max_tokens = int(kwargs.get('max_tokens') or 4000)
        system = str(kwargs.get('system') or '')
        self.logger.info("🤖 使用 Anna 平台宿主 LLM 生成文本（无用户密钥，开箱即用）")
        return sample_text(prompt, max_tokens=max_tokens, system=system)

    def analyze_image(self, image_path: str, prompt: str, **kwargs) -> str:
        from backend.engine.anna_host_llm import sample_vision
        max_tokens = int(kwargs.get('max_tokens') or 2000)
        return sample_vision(image_path, prompt, max_tokens=max_tokens)


class MultiModelManager:
    """多模型管理器"""

    def __init__(self):
        """初始化多模型管理器"""
        self.logger = logger
        self.adapters: Dict[str, BaseModelAdapter] = {}
        self._load_config()

    def _load_config(self):
        """加载配置"""
        try:
            from backend.config.ai_config import get_config_manager
            self.config_manager = get_config_manager()
            self.logger.info("✅ 多模型管理器配置加载成功")
        except Exception as e:
            self.logger.error(f"❌ 多模型管理器配置加载失败: {e}")
            self.config_manager = None

    def get_adapter(self, model_type: str) -> Optional[BaseModelAdapter]:
        """获取模型适配器"""
        if model_type in self.adapters:
            return self.adapters[model_type]

        if not self.config_manager:
            return None

        try:
            normalized_type = self.config_manager.normalize_llm_provider(model_type)
            if normalized_type in self.adapters:
                return self.adapters[normalized_type]
            model_type = normalized_type

            if model_type in {
                'openai', 'custom_openai', 'deepseek', 'kimi', 'qwen', 'chatglm',
                'openrouter', 'siliconflow', 'doubao',
            }:
                connection = self.config_manager.get_llm_connection(model_type)
                if connection['api_key'] and connection['model'] and connection['base_url']:
                    adapter = OpenAICompatibleAdapter(
                        connection['api_key'], connection['base_url'], connection['model']
                    )
                    self.adapters[model_type] = adapter
                    return adapter

            if model_type == 'anthropic':
                connection = self.config_manager.get_llm_connection(model_type)
                if connection['api_key']:
                    adapter = ClaudeAdapter(
                        connection['api_key'], base_url=connection['base_url'] or '', model=connection['model']
                    )
                    self.adapters[model_type] = adapter
                    return adapter

            if model_type == 'gemini':
                connection = self.config_manager.get_llm_connection(model_type)
                if connection['api_key']:
                    adapter = GeminiAdapter(
                        connection['api_key'], base_url=connection['base_url'] or '', model=connection['model']
                    )
                    self.adapters[model_type] = adapter
                    return adapter

            if model_type == 'ernie':
                api_key = self.config_manager.llm_config.ernie_api_key or self.config_manager.llm_config.wenxin_api_key
                secret_key = self.config_manager.llm_config.ernie_secret_key or self.config_manager.llm_config.wenxin_secret_key
                if api_key and secret_key:
                    adapter = WenxinAdapter(api_key, secret_key, model=self.config_manager.llm_config.ernie_model)
                    self.adapters[model_type] = adapter
                    return adapter

            if model_type == 'spark':
                raise AIConfigurationError('讯飞星火尚未接入本项目的 LLM 请求实现')

        except Exception as e:
            self.logger.error(f"❌ 获取{model_type}适配器失败: {e}")

        return None

    def generate_text(self, prompt: str, model_type: Optional[str] = None, **kwargs) -> str:
        """生成文本（支持 'system-default' 作为占位符，自动解析为配置里的默认 LLM）"""
        # 占位符解析：'system-default' / 空 / 'custom-llm' → 自动用 LLMConfig.default_model
        if (not model_type) or model_type in ('system-default', 'custom-llm'):
            if self.config_manager:
                model_type = self.config_manager.llm_config.default_model
        # 再走一次 normalize（确保 custom_openai 等不会被误解析）
        if self.config_manager and model_type:
            model_type = self.config_manager.normalize_llm_provider(model_type)

        adapter = self.get_adapter(model_type)
        if not adapter and AnnaHostSamplingAdapter.available():
            # 用户未配置密钥且宿主 LLM 已协商：走 Anna 平台内置模型，开箱即用
            adapter = AnnaHostSamplingAdapter()
            self.adapters[model_type or 'system-default'] = adapter
        if not adapter:
            raise Exception(f"无法获取{model_type}模型适配器（建议：设置页→模型统一后台→文本模型，填写 自定义OpenAI / 其他厂商的 API Key、Base URL、默认模型并保存；在 Anna 平台内使用时无需配置，自动使用平台内置 AI）")

        return adapter.generate_text(prompt, **kwargs)

    def chat(self, messages, model_type: Optional[str] = None, **kwargs) -> str:
        """Chat 接口：兼容 OpenAI 风格的 messages=[{role,content}] 调用格式。

        本项目所有底层适配器仅暴露 generate_text(prompt)，此处统一将 messages
        列表拼接为自然语言 prompt 后转发。为 /api/ai-config/test-llm、
        /api/ai-config/test-all 等调用 manager.chat(...) 的接口提供兼容。
        """
        import json as _json
        # messages 支持两种格式：list of dict 或 JSON 字符串
        if isinstance(messages, str):
            try:
                messages = _json.loads(messages)
            except Exception:
                messages = [{'role': 'user', 'content': messages}]
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages 必须是非空数组")

        system_parts = []
        prompt_parts = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            role = str(m.get('role', 'user')).lower()
            content = str(m.get('content', '') or '')
            if not content:
                continue
            if role == 'system':
                system_parts.append(content)
            elif role == 'user':
                prompt_parts.append(f"【用户】{content}")
            elif role == 'assistant':
                prompt_parts.append(f"【助理】{content}")
            else:
                prompt_parts.append(f"【{role}】{content}")

        final_prompt = ''
        if system_parts:
            final_prompt += '系统设定：\n' + '\n'.join(system_parts) + '\n\n'
        if prompt_parts:
            final_prompt += '\n'.join(prompt_parts) + '\n\n【助理】'
        if not final_prompt.strip():
            final_prompt = '你好，请回复：收到'

        return self.generate_text(final_prompt, model_type=model_type, **kwargs)

    def analyze_image(self, image_path: str, prompt: str, model_type: Optional[str] = None, **kwargs) -> str:
        """使用显式配置的云视觉模型分析图像，不执行提供商回退。"""
        if not self.config_manager:
            raise AIConfigurationError()

        vision_config = self.config_manager.vision_config
        selected_model = model_type or vision_config.default_model
        normalized_model = self.config_manager.normalize_vision_provider(selected_model)

        # 调试日志：记录云视觉调用的关键配置，便于定位问题
        api_key = self.config_manager.get_vision_api_key(normalized_model)
        base_url = self.config_manager.get_vision_base_url(normalized_model)
        vision_model_name = self.config_manager.get_vision_model(normalized_model)
        self.logger.info(
            '🔍 云视觉调用: model_type=%s → normalized=%s → adapter_model=%s, '
            'base_url=%s, api_key=%s, image=%s',
            model_type, normalized_model, vision_model_name,
            base_url or '(空)', (api_key[:8] + '***') if api_key else '(空)',
            image_path,
        )

        aliases = {
            'qwen_vl': 'qwen_vl', 'gpt4v': 'openai',
            'gemini_vision': 'gemini', 'claude_vision': 'anthropic',
            'chatglm': 'chatglm',
            # 自定义视觉：复用 custom_openai 配置走 OpenAI 兼容协议
            'custom_vision': 'custom_vision',
        }
        adapter_type = aliases.get(normalized_model)
        if not adapter_type:
            if normalized_model in {'baidu_vision', 'tencent_vision', 'spark_vision'}:
                raise NotImplementedError(f'{normalized_model} 视觉服务尚未接入')
            if AnnaHostSamplingAdapter.available():
                # 未识别的视觉模型且宿主 LLM 已协商：走 Anna 平台内置多模态模型
                host_adapter = AnnaHostSamplingAdapter()
                self.adapters[f'vision:{normalized_model}'] = host_adapter
                return host_adapter.analyze_image(image_path, prompt, **kwargs)
            raise AIConfigurationError()

        api_key = self.config_manager.get_vision_api_key(normalized_model)
        if not api_key and AnnaHostSamplingAdapter.available():
            # 无视觉密钥且宿主 LLM 已协商：走 Anna 平台内置多模态模型
            host_adapter = AnnaHostSamplingAdapter()
            self.adapters[f'vision:{normalized_model}'] = host_adapter
            self.logger.info("🤖 使用 Anna 平台宿主 LLM 分析图像（无用户密钥，开箱即用）")
            return host_adapter.analyze_image(image_path, prompt, **kwargs)
        if not api_key:
            raise AIConfigurationError()

        adapter = self.adapters.get(f'vision:{normalized_model}')
        if adapter is None:
            if adapter_type == 'qwen_vl':
                adapter = TongyiAdapter(api_key, vision_model=vision_config.qwen_vl_model)
            elif adapter_type == 'openai':
                adapter = OpenAIAdapter(
                    api_key, self.config_manager.get_vision_base_url(normalized_model)
                )
            elif adapter_type == 'gemini':
                adapter = GeminiAdapter(
                    api_key, base_url=self.config_manager.get_vision_base_url(normalized_model) or ''
                )
            elif adapter_type == 'anthropic':
                adapter = ClaudeAdapter(
                    api_key, base_url=self.config_manager.get_vision_base_url(normalized_model) or ''
                )
            elif adapter_type == 'chatglm':
                adapter = ChatGLMAdapter(
                    api_key,
                    base_url=self.config_manager.get_vision_base_url(normalized_model) or '',
                    vision_model=self.config_manager.llm_config.chatglm_model,
                )
            elif adapter_type == 'custom_vision':
                # 自定义视觉必须使用视觉专属连接，避免误用文本模型配置。
                base_url = self.config_manager.get_vision_base_url(normalized_model) or ''
                model_id = self.config_manager.get_vision_model(normalized_model) or ''
                if not (api_key and base_url and model_id):
                    raise AIConfigurationError()
                adapter = OpenAICompatibleAdapter(api_key, base_url, model_id)
            else:
                raise AIConfigurationError()
            self.adapters[f'vision:{normalized_model}'] = adapter

        vision_models = {
            'gpt4v': vision_config.gpt4v_model,
            'gemini_vision': vision_config.gemini_vision_model,
            'claude_vision': vision_config.claude_vision_model,
            'qwen_vl': vision_config.qwen_vl_model,
            'chatglm': self.config_manager.llm_config.chatglm_model,
            'custom_vision': self.config_manager.get_vision_model(normalized_model),
        }
        try:
            if adapter_type == 'qwen_vl':
                return adapter.analyze_image(image_path, prompt, **kwargs)
            return adapter.analyze_image(
                image_path, prompt, model=vision_models[normalized_model], **kwargs
            )
        except (AIConfigurationError, AIRequestError):
            raise
        except Exception as exc:
            self.logger.error("云视觉分析请求失败: %s", exc, exc_info=True)
            raise AIRequestError() from exc


# 全局多模型管理器实例
_multi_model_manager = None


def reset_multi_model_manager() -> None:
    """丢弃缓存的模型客户端，使配置切换在下一次请求时生效。"""
    global _multi_model_manager
    _multi_model_manager = None


def get_multi_model_manager() -> MultiModelManager:
    """获取多模型管理器单例"""
    global _multi_model_manager
    if _multi_model_manager is None:
        _multi_model_manager = MultiModelManager()
    return _multi_model_manager
