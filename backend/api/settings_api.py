"""
设置管理API路由
提供用户设置、API配置的保存和加载功能
"""
import json
import socket
from dataclasses import asdict, fields
from urllib.parse import urlparse
from flask import request, jsonify
from backend.utils.logger import logger
from pathlib import Path
from backend.core.global_state import get_global_state
from backend.config.paths import PROJECT_ROOT


# 固定 64×64 白色 JPEG；仅用于用户明确发起的视觉能力探测，不读取或写入任何文件。
# 使用 64×64 而非 1×1，避免部分 OpenAI 兼容网关以“图片无效”为由拒绝过小图片，
# 导致无法区分“模型不支持视觉”与“测试图片过小”两种情况。
# 使用 JPEG 而非 PNG，以兼容部分无法正确解码 PNG data URI 的网关。
_VISUAL_PROBE_JPEG_BASE64 = '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCABAAEADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD7LooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA//2Q=='


def _is_masked_secret(value):
    """判断设置页返回的密钥脱敏占位值，避免将其作为真实密钥请求上游。"""
    text = str(value or '').strip()
    return not text or ('*' in text and text.count('*') >= 4)


def _is_valid_config_value(value):
    """仅将非空、非脱敏占位符的值视为可用于兼容迁移的配置。"""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and not _is_masked_secret(value)
    return True


def _mask_api_secrets(config):
    """返回供设置页回显的副本，绝不暴露 API Key / Secret 明文。"""
    masked = dict(config)
    for key, value in list(masked.items()):
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        key_lower = key.lower()
        if ('api_key' not in key_lower and 'secret' not in key_lower
                and key not in ('azure_tts_key', 'azure_subscription_key')):
            continue
        if _is_valid_config_value(value):
            masked[key] = '********' if len(value) <= 8 else value[:4] + '*' * (len(value) - 8) + value[-4:]
    return masked


def _validate_outbound_base_url(base_url):
    """校验用户配置的 AI 服务 Base URL。

    本应用为桌面端单用户工具，用户会显式配置自建的 OpenAI 兼容服务
    （如 vLLM、Ollama、LM Studio、内网中转网关等），这些地址常指向
    127.0.0.1、localhost 或内网 IP。运行时（MultiModelManager）并不限制
    出站地址，因此测试与模型发现路径必须保持一致，允许本机/内网地址，
    仅做基本的格式与可解析性校验，避免拼写错误造成误报。
    """
    parsed = urlparse(base_url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
        return False, 'Base URL 必须是有效的 HTTP(S) 服务地址。'
    try:
        host = parsed.hostname
        # 仅验证主机可解析，不阻止本机/内网地址（与运行时行为一致）
        socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == 'https' else 80))
    except (socket.gaierror, ValueError):
        return False, 'Base URL 主机无法解析。'
    return True, ''


def register_settings_routes(app, db_manager):
    """
    注册设置管理相关的API路由

    Args:
        app: Flask应用实例
        db_manager: 数据库管理器实例
    """

    @app.route('/api/settings', methods=['GET'])
    def get_settings():
        """获取所有设置"""
        try:
            settings = db_manager.get_settings()

            logger.info(f'✅ 获取设置成功')

            return jsonify({
                'code': 0,
                'msg': '获取成功',
                'data': settings
            })

        except Exception as e:
            logger.error(f'❌ 获取设置失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'获取失败: {str(e)}',
                'data': None
            }), 500

    @app.route('/api/settings', methods=['POST'])
    def save_settings():
        """保存设置 - 实时生效并触发全局事件"""
        try:
            data = request.get_json()

            if not data:
                return jsonify({
                    'code': 1,
                    'msg': '设置数据不能为空',
                    'data': None
                }), 400

            # 保存设置到数据库
            result = db_manager.save_settings(data)

            if result:
                logger.info(f'✅ 保存设置成功: {len(data)}项配置')

                # 触发全局状态更新和事件通知
                try:
                    gs = get_global_state()
                    # 让内存中的全局状态立即反映已持久化的设置
                    for category, values in data.items():
                        if isinstance(values, dict):
                            gs.user_settings[category] = values

                    # 触发设置更新事件，通知所有监听模块
                    gs.emit_event('settings_updated', {
                        'keys': list(data.keys()),
                        'settings': data
                    })

                    # 如果包含高级设置，应用代理和日志等配置
                    if 'advanced' in data:
                        advanced = data['advanced']
                        # 应用代理设置
                        if 'proxyEnable' in advanced and 'proxyServer' in advanced:
                            _apply_proxy_settings(advanced)
                        # 应用日志级别
                        if 'logLevel' in advanced:
                            _apply_log_level(advanced['logLevel'])

                    # 如果包含性能设置，更新相关配置
                    if 'performance' in data:
                        gs.emit_event('performance_settings_updated', data['performance'])

                    # 如果包含文件设置，更新路径配置
                    if 'file' in data:
                        gs.emit_event('file_settings_updated', data['file'])

                    # 如果包含通知设置，更新通知配置
                    if 'notification' in data:
                        gs.emit_event('notification_settings_updated', data['notification'])

                    # 如果包含语言设置，更新语言配置
                    if 'language' in data:
                        gs.emit_event('language_settings_updated', data['language'])

                    # 如果包含外观设置，确保全局同步
                    if 'appearance' in data:
                        gs.emit_event('appearance_settings_updated', data['appearance'])

                    logger.info('✅ 设置已实时生效，全局事件已触发')
                except Exception as evt_err:
                    logger.warning(f'⚠️ 设置保存成功但触发全局事件时出错: {evt_err}')

                return jsonify({
                    'code': 0,
                    'msg': '保存成功',
                    'data': {'saved_count': len(data)}
                })
            else:
                return jsonify({
                    'code': 1,
                    'msg': '保存失败',
                    'data': None
                }), 500

        except Exception as e:
            logger.error(f'❌ 保存设置失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'保存失败: {str(e)}',
                'data': None
            }), 500

    @app.route('/api/settings/<setting_key>', methods=['GET'])
    def get_setting(setting_key):
        """获取单个设置项"""
        try:
            value = db_manager.get_setting(setting_key)

            logger.info(f'✅ 获取设置项成功: {setting_key}')

            return jsonify({
                'code': 0,
                'msg': '获取成功',
                'data': {
                    'key': setting_key,
                    'value': value
                }
            })

        except Exception as e:
            logger.error(f'❌ 获取设置项失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'获取失败: {str(e)}',
                'data': None
            }), 500

    @app.route('/api/settings/<setting_key>', methods=['PUT'])
    def update_setting(setting_key):
        """更新单个设置项"""
        try:
            data = request.get_json()
            value = data.get('value')

            result = db_manager.update_setting(setting_key, value)

            if result:
                logger.info(f'✅ 更新设置项成功: {setting_key}')
                try:
                    gs = get_global_state()
                    if isinstance(value, dict):
                        gs.user_settings[setting_key] = value

                    gs.emit_event('settings_updated', {
                        'keys': [setting_key],
                        'settings': {setting_key: value}
                    })
                    category_events = {
                        'performance': 'performance_settings_updated',
                        'file': 'file_settings_updated',
                        'notification': 'notification_settings_updated',
                        'language': 'language_settings_updated',
                        'appearance': 'appearance_settings_updated',
                    }
                    if setting_key == 'advanced' and isinstance(value, dict):
                        _apply_proxy_settings(value)
                        if 'logLevel' in value:
                            _apply_log_level(value['logLevel'])
                    elif setting_key in category_events:
                        gs.emit_event(category_events[setting_key], value)
                except Exception as evt_err:
                    logger.warning(f'⚠️ 设置更新成功但触发全局事件时出错: {evt_err}')
                return jsonify({
                    'code': 0,
                    'msg': '更新成功',
                    'data': {
                        'key': setting_key,
                        'value': value
                    }
                })
            else:
                return jsonify({
                    'code': 1,
                    'msg': '更新失败',
                    'data': None
                }), 500

        except Exception as e:
            logger.error(f'❌ 更新设置项失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'更新失败: {str(e)}',
                'data': None
            }), 500

    @app.route('/api/settings/upstream-models', methods=['POST'])
    def get_upstream_models():
        """仅读取上游模型列表，不会发起 chat/completions 请求。"""
        data = request.get_json(silent=True) or {}
        is_image = bool(data.get('_isImage'))
        api_type = str(data.get('api_type') or '').strip().lower().replace('-', '_')
        api_key = str(data.get('api_key') or '').strip()
        base_url = str(data.get('base_url') or '').strip()
        aliases = {
            'claude': 'anthropic', 'openai_vision': 'gpt4v',
            'gemini_vision': 'gemini_vision', 'qwen_vl': 'qwen_vl',
        }
        api_type = aliases.get(api_type, api_type)
        api_key_is_masked = _is_masked_secret(api_key)
        base_url_is_empty = not base_url
        config_sources = {
            'openai': ((('llm', 'openai_api_key'),), (('llm', 'openai_base_url'),)),
            'gpt4v': ((('vision', 'gpt4v_api_key'),), (('llm', 'openai_base_url'),)),
            'custom_openai': ((('llm', 'custom_openai_api_key'),), (('llm', 'custom_openai_base_url'),)),
            'custom_vision': ((('llm', 'custom_openai_api_key'),), (('llm', 'custom_openai_base_url'),)),
            'anthropic': ((('vision', 'claude_vision_api_key'), ('llm', 'anthropic_api_key')), (('llm', 'anthropic_base_url'),)),
            'claude_vision': ((('vision', 'claude_vision_api_key'), ('llm', 'anthropic_api_key')), (('llm', 'anthropic_base_url'),)),
            'gemini': ((('vision', 'gemini_vision_api_key'), ('llm', 'gemini_api_key')), (('llm', 'gemini_base_url'),)),
            'gemini_vision': ((('vision', 'gemini_vision_api_key'), ('llm', 'gemini_api_key')), (('llm', 'gemini_base_url'),)),
            'kimi': ((('llm', 'kimi_api_key'),), (('llm', 'kimi_base_url'),)),
            'qwen': ((('llm', 'qwen_api_key'),), (('llm', 'qwen_base_url'),)),
            'qwen_vl': ((('vision', 'qwen_vl_api_key'), ('llm', 'qwen_api_key')), (('llm', 'qwen_base_url'),)),
            'deepseek': ((('llm', 'deepseek_api_key'),), (('llm', 'deepseek_base_url'),)),
            'chatglm': ((('llm', 'chatglm_api_key'),), (('llm', 'chatglm_base_url'),)),
            'openrouter': ((('llm', 'openrouter_api_key'),), (('llm', 'openrouter_base_url'),)),
            'siliconflow': ((('llm', 'siliconflow_api_key'),), (('llm', 'siliconflow_base_url'),)),
            'doubao': ((('llm', 'doubao_api_key'),), (('llm', 'doubao_base_url'),)),
        }
        sources = config_sources.get(api_type)
        if is_image:
            image_provider = api_type
            image_sources = (
                (('image', f'{image_provider}_api_key'),),
                (('image', f'{image_provider}_base_url'),),
            )
            sources = image_sources
        if sources and (api_key_is_masked or base_url_is_empty):
            from backend.config.ai_config import get_config_manager
            cfg = get_config_manager()
            configs = {'llm': cfg.llm_config, 'vision': cfg.vision_config, 'image': getattr(cfg, 'image_config', None)}

            def saved_value(candidates):
                for config_name, field_name in candidates:
                    config = configs.get(config_name)
                    value = str(getattr(config, field_name, '') or '').strip() if config is not None else ''
                    if value:
                        return value
                return ''

            if api_key_is_masked:
                api_key = saved_value(sources[0])
            if base_url_is_empty:
                base_url = saved_value(sources[1])

        if is_image and api_key and _is_masked_secret(api_key):
            return jsonify({
                'code': 1,
                'msg': '图片生成 API Key 是掩码污染值，无法恢复，请在图片区重新输入完整 Key 并保存',
                'data': None,
            }), 422

        if not api_type or not api_key or not base_url:
            return jsonify({'code': 1, 'msg': '缺少参数：api_type、api_key 和 base_url 均为必填项', 'data': None}), 400

        unsupported = {'ernie', 'spark', 'azure', 'azure_tts'}
        if api_type in unsupported:
            return jsonify({'code': 1, 'msg': '该服务不支持标准模型发现，请使用“手动添加模型”。', 'data': None}), 400

        compatible = {
            'openai', 'gpt4v', 'custom_openai', 'custom_vision', 'kimi', 'qwen',
            'qwen_vl', 'deepseek', 'chatglm', 'openrouter', 'siliconflow', 'doubao'
        }
        if api_type not in compatible | {'anthropic', 'claude_vision', 'gemini', 'gemini_vision'}:
            return jsonify({'code': 1, 'msg': '不支持的服务类型，请使用“手动添加模型”。', 'data': None}), 400

        valid_base_url, base_url_error = _validate_outbound_base_url(base_url)
        if not valid_base_url:
            return jsonify({'code': 1, 'msg': base_url_error, 'data': None}), 400

        def endpoint(suffix, default_prefix=''):
            base = base_url.rstrip('/')
            if base.endswith('/models'):
                base = base[:-7]
            path = urlparse(base).path.rstrip('/')
            if default_prefix and not path:
                return base + default_prefix + suffix
            return base + suffix

        if api_type in ('anthropic', 'claude_vision'):
            url = endpoint('/models', '/v1') if not base_url.rstrip('/').endswith('/v1') else endpoint('/models')
            headers = {'x-api-key': api_key, 'anthropic-version': '2023-06-01'}
            params = None
        elif api_type in ('gemini', 'gemini_vision'):
            url = endpoint('/models', '/v1beta')
            headers = None
            params = {'key': api_key}
        else:
            url = endpoint('/models')
            headers = {'Authorization': 'Bearer ' + api_key}
            params = None

        try:
            import requests
            response = requests.get(url, headers=headers, params=params, timeout=10, allow_redirects=False)
        except requests.RequestException:
            return jsonify({'code': 1, 'msg': '无法连接上游模型服务，请检查 Base URL、网络和服务状态。', 'data': None}), 502

        if not response.ok:
            if response.status_code in (401, 403):
                message = '上游鉴权失败，请检查 API Key 或账号模型权限。'
            elif response.status_code == 404:
                message = '上游未提供模型列表端点，请使用“手动添加模型”。'
            else:
                message = '上游模型列表请求失败（HTTP %s）。' % response.status_code
            return jsonify({'code': 1, 'msg': message, 'data': None}), 502
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            return jsonify({'code': 1, 'msg': '上游返回的模型列表不是有效 JSON。', 'data': None}), 502

        entries = payload.get('data') if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            entries = payload.get('models') if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            return jsonify({'code': 1, 'msg': '上游返回格式中未找到模型列表。', 'data': None}), 502

        models, seen = [], set()
        for item in entries:
            if isinstance(item, str):
                model_id = item.strip()
                name = model_id
            elif isinstance(item, dict):
                model_id = str(item.get('id') or item.get('name') or item.get('model') or '').strip()
                name = str(item.get('label') or item.get('display_name') or item.get('name') or item.get('owned_by') or model_id).strip()
            else:
                continue
            if api_type in ('gemini', 'gemini_vision') and model_id.startswith('models/'):
                model_id = model_id[7:]
            if model_id and model_id not in seen:
                seen.add(model_id)
                models.append({'id': model_id, 'name': name or model_id})
        return jsonify({'code': 0, 'msg': '模型列表获取成功（实际可用模型由上游账号权限决定）。', 'data': {'models': models, 'count': len(models)}})

    @app.route('/api/settings/api-config', methods=['POST'])
    def save_api_config():
        """保存API配置（专门用于API密钥等敏感配置）"""
        try:
            logger.info('=' * 80)
            logger.info('🔑 [API配置保存] 开始处理请求')

            data = request.get_json()
            logger.info(f'📥 [API配置保存] 接收到的数据键: {list(data.keys()) if data else "空"}')

            if not data:
                logger.warning('⚠️ [API配置保存] 数据为空，拒绝请求')
                return jsonify({
                    'code': 1,
                    'msg': 'API配置数据不能为空',
                    'data': None
                }), 400

            clear_fields = {
                key for key in (data.get('_clear_fields') or [])
                if isinstance(key, str)
            }
            data.pop('_clear_fields', None)

            # 过滤空值和脱敏占位值，保护已保存的真实密钥不被覆盖；
            # _clear_fields 中的键表示用户明确要求清空，需保留空字符串写入两种存储。
            try:
                def _should_keep(k, v):
                    if k in clear_fields:
                        return True
                    if v is None:
                        return False
                    if isinstance(v, str):
                        s = v.strip()
                        if s == '':
                            return False
                        if ('api_key' in k.lower()) or ('secret' in k.lower()):
                            star = s.count('*')
                            if star >= 4 and star >= (len(s) // 2):
                                logger.info(f'🙈 [API配置保存] 跳过脱敏/占位值: {k}')
                                return False
                    return True
                data = {kk: vv for kk, vv in (data or {}).items() if _should_keep(kk, vv)}
            except Exception as _e:
                logger.warning(f'⚠️ [API配置保存] 过滤占位值时出错: {_e}')

            # 1) 先写入配置文件（主路径，可靠）
            logger.info('📝 [API配置保存] 步骤1: 写入配置文件 config/ai_config.json')
            try:
                from backend.config.ai_config import TTSModelConfig, get_config_manager
                cfg = get_config_manager()
                if 'default_tts' in data:
                    requested_default_tts = str(data['default_tts'] or '').strip().lower()
                    canonical_default_tts = TTSModelConfig.DEFAULT_TTS_ALIASES.get(
                        requested_default_tts, requested_default_tts
                    )
                    if canonical_default_tts not in TTSModelConfig.DEFAULT_TTS_ENGINES:
                        return jsonify({
                            'code': 1,
                            'msg': 'default_tts 仅支持 edge-tts、gtts、azure、pyttsx3、coqui',
                            'data': None,
                        }), 400
                    data['default_tts'] = canonical_default_tts
                logger.info(f'✅ [API配置保存] 配置管理器加载成功')
                updated_keys = []

                def _apply_dataclass(config):
                    allowed = {field.name for field in fields(config)}
                    for key, value in data.items():
                        if key not in allowed or value is None:
                            continue
                        if isinstance(value, str):
                            value = value.strip()
                            if key not in clear_fields and (
                                not value or (('api_key' in key.lower() or 'secret' in key.lower()) and set(value) == {'*'})
                            ):
                                continue
                        if isinstance(getattr(config, key), bool) and isinstance(value, str):
                            value = value.lower() in {'1', 'true', 'yes', 'on'}
                        if getattr(config, key) != value:
                            setattr(config, key, value)
                            updated_keys.append(key)

                _apply_dataclass(cfg.llm_config)
                _apply_dataclass(cfg.vision_config)
                _apply_dataclass(cfg.tts_model_config)

                image_field_map = {
                    'default_image_model': 'default_model',
                    'default_image_size': 'default_size',
                    'default_image_quality': 'default_quality',
                    'default_image_style': 'default_style',
                    'default_image_n': 'default_n',
                    'image_save_dir': 'save_dir',
                }
                image_suffixes = {'api_key', 'base_url', 'model', 'secret_id', 'secret_key', 'group_id', 'name'}
                for source_key, value in data.items():
                    target_key = image_field_map.get(source_key)
                    if target_key is None and '_image_' in source_key:
                        provider, suffix = source_key.split('_image_', 1)
                        if provider and suffix in image_suffixes:
                            target_key = f'{provider}_{suffix}'
                    if target_key is None or not hasattr(cfg.image_config, target_key) or value is None:
                        continue
                    if isinstance(value, str):
                        value = value.strip()
                        if source_key not in clear_fields and (
                            not value or (('api_key' in target_key.lower() or 'secret' in target_key.lower()) and _is_masked_secret(value))
                        ):
                            continue
                    if isinstance(getattr(cfg.image_config, target_key), bool) and isinstance(value, str):
                        value = value.lower() in {'1', 'true', 'yes', 'on'}
                    if getattr(cfg.image_config, target_key) != value:
                        setattr(cfg.image_config, target_key, value)
                        updated_keys.append(source_key)

                if 'default_model' in data:
                    cfg.llm_config.default_model = cfg.normalize_llm_provider(data['default_model'])
                    updated_keys.append('default_model')
                if 'default_vision_model' in data:
                    cfg.vision_config.default_model = cfg.normalize_vision_provider(data['default_vision_model'])
                    updated_keys.append('default_vision_model')

                logger.info(f'📝 [API配置保存] 更新了 {len(updated_keys)} 个配置项')
                logger.info(f'💾 [API配置保存] 准备保存配置文件...')
                if not cfg.save_config():
                    raise RuntimeError('配置文件保存失败')
                # 后端保存完成后立即刷新共享组件；不依赖前端额外请求。
                if not get_global_state().reload_config():
                    raise RuntimeError('运行时配置重载失败')
                logger.info(f'✅ [API配置保存] 配置文件保存并已应用！')
            except Exception as ie:
                logger.error(f'❌ [API配置保存] 写入配置文件失败: {ie}', exc_info=True)
                return jsonify({
                    'code': 1,
                    'msg': f'配置保存失败: {str(ie)}',
                    'data': None,
                }), 500

            # 2) 同步旧版数据库备份；文件已经成功持久化，数据库失败不得伪装为失败。
            db_sync_warning = None
            try:
                if db_manager.save_api_config(data) is not True:
                    db_sync_warning = '旧版数据库备份未完成，不影响本机配置文件中的已保存配置。'
                    logger.warning('API 配置文件已保存，但旧版数据库备份未完成')
            except Exception as de:
                db_sync_warning = '旧版数据库备份失败，不影响本机配置文件中的已保存配置。'
                logger.warning('API 配置文件已保存，但旧版数据库备份失败: %s', de)

            return jsonify({
                'code': 0,
                'msg': 'API配置已保存到本机配置，重启后仍保留',
                'data': {
                    'saved_keys': list(data.keys()),
                    'config_persisted': True,
                    'db_sync_warning': db_sync_warning,
                }
            })

        except Exception as e:
            logger.error(f'❌ [API配置保存] 发生异常: {e}', exc_info=True)
            logger.info('=' * 80)
            return jsonify({
                'code': 1,
                'msg': f'保存失败: {str(e)}',
                'data': None
            }), 500

    @app.route('/api/settings/api-config', methods=['GET'])
    def get_api_config():
        """获取 API 配置；config/ai_config.json 为唯一权威，SQLite 仅兼容补全。"""
        try:
            from backend.config.ai_config import get_config_manager
            cfg = get_config_manager()

            # 按优先级合并：LLM 优先；Vision/TTS/Image 仅补齐前面没有的有效字段。
            # 这避免 Vision 中同名空 custom_openai_* 字段覆盖 LLM 配置。
            file_conf = {}
            for config in (cfg.llm_config, cfg.vision_config, cfg.tts_model_config, cfg.image_config):
                for key, value in asdict(config).items():
                    if key not in file_conf or not _is_valid_config_value(file_conf[key]):
                        file_conf[key] = value
            file_conf['default_vision_model'] = cfg.vision_config.default_model
            file_conf['default_image_model'] = cfg.image_config.default_model
            file_conf['default_image_size'] = cfg.image_config.default_size
            file_conf['default_image_quality'] = cfg.image_config.default_quality
            file_conf['default_image_style'] = cfg.image_config.default_style
            file_conf['default_image_n'] = cfg.image_config.default_n
            file_conf['image_save_dir'] = cfg.image_config.save_dir

            # 历史 SQLite 数据只能补齐文件中的空字段，绝不可覆盖有效文件值。
            try:
                db_conf = db_manager.get_api_config() or {}
            except Exception as db_error:
                logger.warning('读取旧版 API 配置备份失败，将只使用配置文件: %s', db_error)
                db_conf = {}
            for key, value in db_conf.items():
                if not _is_valid_config_value(file_conf.get(key)) and _is_valid_config_value(value):
                    file_conf[key] = value

            return jsonify({
                'code': 0,
                'msg': '获取成功',
                'data': _mask_api_secrets(file_conf),
            })
        except Exception as e:
            logger.error(f'❌ 获取API配置失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'获取失败: {str(e)}',
                'data': None
            }), 500

    @app.route('/api/settings/azure-tts-preview', methods=['POST'])
    def azure_tts_preview():
        """生成 Azure TTS 试听音频"""
        try:
            data = request.get_json() or {}
            voice_id = (data.get('voice_id') or '').strip()
            if not voice_id:
                from backend.services.voiceover_service import VoiceoverService
                voice_id = VoiceoverService._default_voice_id()
            text = (data.get('text') or '').strip() or '这是 Azure TTS 试听示例，您好！'

            gs = get_global_state()
            tts_engine = gs.get_tts_engine() if gs else None
            if not tts_engine or 'azure' not in (tts_engine.available_engines or []):
                return jsonify({
                    'code': 1,
                    'msg': 'Azure TTS 未正确配置，请先在设置中填写密钥和区域并保存。',
                    'data': None
                }), 400

            preview_dir = PROJECT_ROOT / 'output' / 'previews'
            preview_dir.mkdir(parents=True, exist_ok=True)
            safe_voice = voice_id.replace('/', '_').replace('\\', '_')
            output_path = preview_dir / f'azure_preview_{safe_voice}.mp3'

            ok = tts_engine.synthesize(
                text=text,
                output_path=str(output_path),
                engine='azure',
                voice=voice_id
            )
            if not ok:
                return jsonify({
                    'code': 1,
                    'msg': 'Azure TTS 试听生成失败，请检查密钥、区域或网络。',
                    'data': None
                }), 500

            p = Path(str(output_path)).resolve()
            try:
                rel = p.relative_to(PROJECT_ROOT)
                rel_str = str(rel).replace('\\', '/')
            except Exception:
                rel_str = f"output/previews/{p.name}"
            audio_url = '/' + rel_str.lstrip('/')

            return jsonify({
                'code': 0,
                'msg': '试听生成成功',
                'data': {
                    'audio_path': rel_str,
                    'audio_url': audio_url
                }
            })
        except Exception as e:
            logger.error(f'❌ Azure TTS 试听生成失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'试听失败: {str(e)}',
                'data': None
            }), 500

    @app.route('/api/settings/volcano-voice-clone-test', methods=['POST'])
    def volcano_voice_clone_test():
        """测试火山引擎语音克隆连接"""
        try:
            data = request.get_json() or {}
            api_key = data.get('api_key') or ''
            app_id = data.get('app_id') or ''
            voice_type = data.get('voice_type') or ''

            if _is_masked_secret(api_key):
                api_key = ''
            if _is_masked_secret(app_id):
                app_id = ''

            cfg = get_config_manager()
            if not api_key:
                api_key = getattr(cfg.tts_model_config, 'volcano_api_key', '') or ''
            if not app_id:
                app_id = getattr(cfg.tts_model_config, 'volcano_app_id', '') or ''
            if not voice_type:
                voice_type = getattr(cfg.tts_model_config, 'volcano_voice_type', '') or ''

            if not api_key or not app_id:
                return jsonify({
                    'code': 1,
                    'msg': '请先填写 API Key 和 App ID',
                    'data': None
                }), 400
            if not voice_type:
                return jsonify({
                    'code': 1,
                    'msg': '请先填写音色 ID (Voice Type)，需在火山引擎控制台完成声音复刻训练后获得',
                    'data': None
                }), 400

            import requests
            import uuid
            url = 'https://openspeech.bytedance.com/api/v1/tts'
            payload = {
                'app': {
                    'appid': app_id,
                    'token': api_key,
                    'cluster': 'volcano_tts',
                },
                'user': {'uid': 'jjyb_ai_test'},
                'audio': {
                    'voice_type': voice_type,
                    'encoding': 'mp3',
                    'speed_ratio': 1.0,
                    'volume_ratio': 1.0,
                    'pitch_ratio': 1.0,
                },
                'request': {
                    'reqid': uuid.uuid4().hex,
                    'text': '测',
                    'text_type': 'plain',
                    'operation': 'query',
                },
            }
            headers = {'Content-Type': 'application/json'}
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code != 200:
                return jsonify({
                    'code': 1,
                    'msg': f'连接失败: HTTP {resp.status_code} - {resp.text[:200]}',
                    'data': None
                }), 500
            resp_data = resp.json()
            code = resp_data.get('code')
            if code == 3000:
                return jsonify({
                    'code': 0,
                    'msg': '✅ 火山引擎语音克隆连接测试成功',
                    'data': {'status': 'ok'}
                })
            else:
                return jsonify({
                    'code': 1,
                    'msg': f'连接失败: code={code}, message={resp_data.get("message", "未知错误")}',
                    'data': None
                }), 500
        except Exception as e:
            logger.error(f'❌ 火山引擎语音克隆连接测试失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'测试失败: {str(e)}',
                'data': None
            }), 500

    @app.route('/api/settings/volcano-voice-clone-preview', methods=['POST'])
    def volcano_voice_clone_preview():
        """生成火山引擎语音克隆试听音频"""
        try:
            data = request.get_json() or {}
            text = (data.get('text') or '').strip() or '这是火山引擎语音克隆试听示例，您好！'
            api_key = data.get('api_key') or ''
            app_id = data.get('app_id') or ''
            voice_type = data.get('voice_type') or ''

            if _is_masked_secret(api_key):
                api_key = ''
            if _is_masked_secret(app_id):
                app_id = ''

            cfg = get_config_manager()
            if not api_key:
                api_key = getattr(cfg.tts_model_config, 'volcano_api_key', '') or ''
            if not app_id:
                app_id = getattr(cfg.tts_model_config, 'volcano_app_id', '') or ''
            if not voice_type:
                voice_type = getattr(cfg.tts_model_config, 'volcano_voice_type', '') or ''

            if not api_key or not app_id:
                return jsonify({
                    'code': 1,
                    'msg': '请先在设置中填写火山引擎 API Key 和 App ID 并保存',
                    'data': None
                }), 400
            if not voice_type:
                return jsonify({
                    'code': 1,
                    'msg': '请先填写音色 ID (Voice Type)',
                    'data': None
                }), 400

            preview_dir = PROJECT_ROOT / 'output' / 'previews'
            preview_dir.mkdir(parents=True, exist_ok=True)
            safe_voice = voice_type.replace('/', '_').replace('\\', '_')
            output_path = preview_dir / f'volcano_clone_preview_{safe_voice}.mp3'

            import requests
            import uuid
            import binascii
            url = 'https://openspeech.bytedance.com/api/v1/tts'
            payload = {
                'app': {
                    'appid': app_id,
                    'token': api_key,
                    'cluster': 'volcano_tts',
                },
                'user': {'uid': 'jjyb_ai_preview'},
                'audio': {
                    'voice_type': voice_type,
                    'encoding': 'mp3',
                    'speed_ratio': 1.0,
                    'volume_ratio': 1.0,
                    'pitch_ratio': 1.0,
                },
                'request': {
                    'reqid': uuid.uuid4().hex,
                    'text': text,
                    'text_type': 'plain',
                    'operation': 'query',
                },
            }
            headers = {'Content-Type': 'application/json'}
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code != 200:
                return jsonify({
                    'code': 1,
                    'msg': f'试听失败: HTTP {resp.status_code}',
                    'data': None
                }), 500
            resp_data = resp.json()
            if resp_data.get('code') != 3000:
                return jsonify({
                    'code': 1,
                    'msg': f'试听失败: code={resp_data.get("code")}, message={resp_data.get("message", "未知错误")}',
                    'data': None
                }), 500
            audio_data = resp_data.get('data')
            if not audio_data:
                return jsonify({
                    'code': 1,
                    'msg': '未返回音频数据',
                    'data': None
                }), 500
            output_path.write_bytes(binascii.unhexlify(audio_data))
            if output_path.stat().st_size < 1024:
                return jsonify({
                    'code': 1,
                    'msg': '返回音频过小',
                    'data': None
                }), 500

            p = Path(str(output_path)).resolve()
            try:
                rel = p.relative_to(PROJECT_ROOT)
                rel_str = str(rel).replace('\\', '/')
            except Exception:
                rel_str = f"output/previews/{p.name}"
            audio_url = '/' + rel_str.lstrip('/')

            return jsonify({
                'code': 0,
                'msg': '试听生成成功',
                'data': {
                    'audio_path': rel_str,
                    'audio_url': audio_url
                }
            })
        except Exception as e:
            logger.error(f'❌ 火山引擎语音克隆试听生成失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'试听失败: {str(e)}',
                'data': None
            }), 500

    @app.route('/api/settings/test-api', methods=['POST'])
    def test_api_connection():
        """测试API连接 - 真实HTTP连通校验（尽量无副作用）"""
        try:
            import time as _time
            import requests
            data = request.get_json() or {}
            api_type = str(data.get('api_type') or '').strip().lower()
            api_type = {
                'claude': 'anthropic', 'anthropic': 'anthropic', 'claude-vision': 'claude_vision', 'claude_vision': 'claude_vision',
                'gemini-vision': 'gemini_vision', 'gemini_vision': 'gemini_vision',
                'qwen-vl': 'qwen_vl', 'qwen_vl': 'qwen_vl', 'tongyi': 'qwen',
                'openai-vision': 'gpt4v', 'openai_vision': 'gpt4v',
                'glm-4v': 'chatglm', 'glm_4v': 'chatglm', 'xfyun': 'spark',
            }.get(api_type, api_type)
            api_key = data.get('api_key') or ''
            base_url = data.get('base_url') or ''
            # 设置页读取配置时会脱敏显示密钥；测试请求必须回填后端保存的真实值。
            api_key_is_masked = _is_masked_secret(api_key)
            if api_key_is_masked:
                api_key = ''
            extra = dict(data.get('extra') or {})
            # 同时兼容旧版扁平请求体，避免参数在前后端升级期间丢失。
            for key in ('model', 'name', 'region', 'appid', 'api_secret', 'secret_key', 'timeout'):
                if key in data and key not in extra:
                    extra[key] = data.get(key)

            # 若未显式传入 api_key / base_url，则从配置文件兜底读取
            if not api_key or not base_url:
                try:
                    from backend.config.ai_config import get_config_manager
                    cfg = get_config_manager()
                    m = api_type
                    if m == 'openai':
                        if not api_key:
                            api_key = getattr(cfg.llm_config, 'openai_api_key', '')
                        if not base_url:
                            base_url = getattr(cfg.llm_config, 'openai_base_url', '')
                    elif m in ('gpt4v', 'openai_vision'):
                        if not api_key:
                            api_key = getattr(cfg.vision_config, 'gpt4v_api_key', '') or getattr(cfg.llm_config, 'openai_api_key', '')
                        if not base_url:
                            base_url = getattr(cfg.llm_config, 'openai_base_url', '')
                    elif m == 'custom_openai':
                        if not api_key:
                            api_key = getattr(cfg.llm_config, 'custom_openai_api_key', '')
                        if not base_url:
                            base_url = getattr(cfg.llm_config, 'custom_openai_base_url', '')
                    elif m in ('claude', 'claude-vision', 'claude_vision', 'anthropic'):
                        if not api_key:
                            api_key = getattr(cfg.vision_config, 'claude_vision_api_key', '') if m in ('claude-vision', 'claude_vision') else getattr(cfg.llm_config, 'anthropic_api_key', '')
                            api_key = api_key or getattr(cfg.llm_config, 'anthropic_api_key', '') or getattr(cfg.llm_config, 'claude_api_key', '')
                        if not base_url:
                            base_url = getattr(cfg.llm_config, 'anthropic_base_url', '')
                    elif m in ('gemini', 'gemini-vision', 'gemini_vision'):
                        if not api_key:
                            api_key = getattr(cfg.vision_config, 'gemini_vision_api_key', '') if m in ('gemini-vision', 'gemini_vision') else getattr(cfg.llm_config, 'gemini_api_key', '')
                            api_key = api_key or getattr(cfg.llm_config, 'gemini_api_key', '')
                        if not base_url:
                            base_url = getattr(cfg.llm_config, 'gemini_base_url', '')
                    elif m == 'kimi':
                        if not api_key:
                            api_key = getattr(cfg.llm_config, 'kimi_api_key', '')
                        if not base_url:
                            base_url = getattr(cfg.llm_config, 'kimi_base_url', '')
                    elif m in ('qwen', 'qwen_vl'):
                        if not api_key:
                            api_key = (
                                getattr(cfg.vision_config, 'qwen_vl_api_key', '')
                                or getattr(cfg.vision_config, 'tongyi_vl_api_key', '')
                            ) if m == 'qwen_vl' else ''
                            api_key = api_key or getattr(cfg.llm_config, 'qwen_api_key', '') or getattr(cfg.llm_config, 'tongyi_api_key', '')
                        if not base_url:
                            base_url = getattr(cfg.llm_config, 'qwen_base_url', '')
                    elif m in ('ernie','wenxin'):
                        ak = getattr(cfg.llm_config, 'ernie_api_key', '')
                        sk = getattr(cfg.llm_config, 'ernie_secret_key', '')
                        if ak and sk and not api_key:
                            api_key = f'{ak}:{sk}'
                    elif m in ('chatglm','zhipu'):
                        if not api_key:
                            api_key = getattr(cfg.llm_config, 'chatglm_api_key', '')
                        if not base_url:
                            base_url = getattr(cfg.llm_config, 'chatglm_base_url', '')
                    elif m == 'deepseek':
                        if not api_key:
                            api_key = getattr(cfg.llm_config, 'deepseek_api_key', '')
                        if not base_url:
                            base_url = getattr(cfg.llm_config, 'deepseek_base_url', '')
                    elif m == 'openrouter':
                        if not api_key:
                            api_key = getattr(cfg.llm_config, 'openrouter_api_key', '')
                        if not base_url:
                            base_url = getattr(cfg.llm_config, 'openrouter_base_url', '')
                    elif m == 'siliconflow':
                        if not api_key:
                            api_key = getattr(cfg.llm_config, 'siliconflow_api_key', '')
                        if not base_url:
                            base_url = getattr(cfg.llm_config, 'siliconflow_base_url', '')
                    elif m == 'doubao':
                        if not api_key:
                            api_key = getattr(cfg.llm_config, 'doubao_api_key', '')
                        if not base_url:
                            base_url = getattr(cfg.llm_config, 'doubao_base_url', '')
                    elif m == 'spark':
                        if not api_key:
                            api_key = getattr(cfg.llm_config, 'spark_api_key', '')
                        if not extra.get('appid'):
                            extra['appid'] = getattr(cfg.llm_config, 'spark_appid', '')
                        if not extra.get('api_secret'):
                            extra['api_secret'] = getattr(cfg.llm_config, 'spark_api_secret', '')
                    elif m in ('azure-tts','azure'):
                        if not api_key:
                            api_key = getattr(cfg.tts_model_config, 'azure_tts_key', '') or getattr(cfg.tts_model_config, 'azure_subscription_key', '')
                        if not extra.get('region'):
                            extra['region'] = getattr(cfg.tts_model_config, 'azure_tts_region', '') or getattr(cfg.tts_model_config, 'azure_region', '')
                except Exception:
                    pass

            if not api_type:
                return jsonify({'code': 1, 'msg': '缺少参数: api_type', 'data': None}), 400

            # helper
            def ok(latency, status=200, detail='OK'):
                return jsonify({
                    'code': 0,
                    'msg': '连接成功',
                    'data': {
                        'api_type': api_type,
                        'status': 'connected',
                        'http_status': status,
                        'latency_ms': int(latency * 1000),
                        'detail': detail
                    }
                })

            def _format_http_error(status: int, body_snippet: str) -> str:
                """根据HTTP状态码和返回内容生成更友好的错误说明"""
                try:
                    txt = (body_snippet or '').strip()
                except Exception:
                    txt = ''

                # 解析上游错误体，识别常见错误码并给出可操作提示
                err_code = ''
                err_msg = ''
                err_status = ''
                if txt:
                    try:
                        parsed = json.loads(txt)
                        if isinstance(parsed, dict):
                            e = parsed.get('error') if isinstance(parsed.get('error'), dict) else parsed
                            err_code = str(e.get('code') or e.get('type') or '').lower()
                            err_msg = str(e.get('message') or '')
                            err_status = str(e.get('status') or '').lower()  # Gemini: NOT_FOUND
                    except Exception:
                        pass

                # 优先按上游错误码给出精确提示
                model_err_codes = ('model_not_found', 'model_not_available', 'no_available_channel',
                                'model_not_found_error', 'model_does_not_exist',
                                'not_found_error', 'not_found')  # Anthropic not_found_error, Gemini NOT_FOUND
                if err_code in model_err_codes or err_status in ('not_found', 'not_found_error'):
                    hint = f'上游不存在该模型'
                    if err_msg:
                        hint += f'：{err_msg}'
                    hint += '。请到“获取上游模型”拉取真实可用模型列表，或核对模型 ID 拼写。'
                    return f'模型不可用（HTTP {status}）：{hint}'
                if err_code in ('invalid_api_key', 'authentication_error', 'unauthorized',
                                'permission_denied'):
                    return f'鉴权失败（HTTP {status}）：请检查 API Key 是否正确、是否有对应权限。{(" 服务器返回：" + err_msg) if err_msg else ""}'
                # 图片相关错误：覆盖 OpenAI 系 invalid_value(input) / invalid_request_error 以及
                # 其他网关的 invalid_image / image_not_supported 等命名
                err_param = ''
                if txt:
                    try:
                        parsed = json.loads(txt)
                        if isinstance(parsed, dict):
                            e = parsed.get('error') if isinstance(parsed.get('error'), dict) else parsed
                            err_param = str(e.get('param') or '').lower()
                    except Exception:
                        pass
                is_image_error = (
                    err_code in ('invalid_image', 'image_not_supported', 'unsupported_media_type',
                                 'invalid_image_url', 'image_too_small', 'image_error')
                    or (err_code == 'invalid_value' and err_param in ('input', 'image', 'image_url'))
                    or (err_code == 'invalid_request_error' and err_param in ('input', 'image', 'image_url'))
                    or 'image' in err_msg.lower() and 'valid' in err_msg.lower()
                )
                if is_image_error:
                    hint = '上游拒绝接收测试图片'
                    if err_msg:
                        hint += f'：{err_msg}'
                    hint += '。该模型可能不支持图像输入，请改用支持视觉的模型（如 gpt-4o-mini、gpt-5.4 等）。'
                    return f'图片不被支持（HTTP {status}）：{hint}'

                # 基础前缀：按状态码归类
                if status in (401, 403):
                    prefix = f'鉴权失败（HTTP {status}），请检查 API Key/Secret 是否正确、是否有对应权限。'
                elif 400 <= status < 500:
                    prefix = f'请求配置可能有误（HTTP {status}），请检查模型名称、Base URL 等参数。'
                elif 500 <= status < 600:
                    prefix = f'服务端异常（HTTP {status}），可能是目标服务不稳定或限流，请稍后重试。'
                else:
                    prefix = f'请求失败（HTTP {status}）。'

                if txt:
                    # 附上服务端返回的关键片段，便于快速定位问题
                    return f"{prefix} 服务器返回：{txt}"
                return prefix

            def _err_with_model_hint(base, headers, model_id, status, body_text):
                """当 chat/completions 因模型问题失败时，主动拉取上游 /models 列表，
                在错误提示中给出可用模型建议，避免用户反复试错。"""
                body_snippet = (body_text or '')[:300]
                base_msg = _format_http_error(status, body_snippet)

                # 仅在疑似模型问题时才拉取列表，避免对鉴权失败等场景发起额外请求
                lowered = body_snippet.lower()
                model_related = (
                    'model_not_found' in lowered or 'no_available_channel' in lowered
                    or 'model not' in lowered or 'does not exist' in lowered
                    or 'unknown model' in lowered or 'not found' in lowered
                )
                if not model_related:
                    return err(status, body_snippet)

                available = []
                try:
                    mr = requests.get(base + '/models', headers=headers, timeout=6)
                    if mr.status_code == 200:
                        data = mr.json() or {}
                        items = data.get('data') if isinstance(data, dict) else data
                        if isinstance(items, list):
                            available = [str(m.get('id')) for m in items if isinstance(m, dict) and m.get('id')]
                except Exception:
                    pass

                if available:
                    # 只展示前 12 个，避免提示过长
                    shown = available[:12]
                    suffix = ' 等' if len(available) > 12 else ''
                    final_msg = f"{base_msg} 上游可用模型：{', '.join(shown)}{suffix}"
                    return err(status, final_msg, _formatted=True)
                return err(status, body_snippet)

            def err(status, detail, _formatted=False):
                # _formatted=True 表示 detail 已经是面向用户的最终消息，无需再次格式化
                msg = detail if _formatted else _format_http_error(status, detail)
                return jsonify({
                    'code': 1,
                    'msg': msg,
                    'data': {
                        'api_type': api_type,
                        'status': 'error',
                        'http_status': status,
                        'detail': detail
                    }
                }), 200

            timeout = float(extra.get('timeout', 5))
            visual_probe = extra.get('visual_probe') is True
            visual_api_types = {'gpt4v', 'custom_vision', 'claude_vision', 'gemini_vision', 'qwen_vl'}
            if visual_probe and api_type not in visual_api_types:
                return err(400, '该接口不支持视觉探测。')
            if visual_probe and api_type == 'qwen_vl':
                return err(400, '不支持本接口的视觉探测，请使用实际任务验证。')
            t0 = _time.perf_counter()

            # OpenAI 及自定义 OpenAI 兼容 API：用真实 Chat Completions 校验模型可用性，
            # 避免仅 /models 可达但所选模型不可用的误报。
            if api_type in ('openai', 'gpt4v', 'custom_openai', 'custom_vision'):
                base = base_url.rstrip('/') if base_url else 'https://api.openai.com/v1'
                # custom_vision 复用 custom_openai 的密钥/Base URL，但模型 ID 必须是视觉模型，
                # 禁止静默回退到 custom_openai_model（文本模型），否则会让用户误以为视觉能力不可用。
                model_id = ''
                if api_type == 'custom_vision':
                    model_id = str(extra.get('model') or '').strip()
                    if not model_id:
                        try:
                            from backend.config.ai_config import get_config_manager
                            _custom_config = get_config_manager().llm_config
                            model_id = getattr(_custom_config, 'custom_openai_vision_model', '')
                        except Exception:
                            model_id = ''
                    if not api_key:
                        try:
                            api_key = getattr(get_config_manager().llm_config, 'custom_openai_api_key', '') or ''
                        except Exception:
                            pass
                    if not base_url:
                        try:
                            base_url = getattr(get_config_manager().llm_config, 'custom_openai_base_url', '') or ''
                        except Exception:
                            pass
                        base = base_url.rstrip('/') if base_url else base
                if not model_id:
                    model_id = extra.get('model') or ''
                # 兜底：从配置文件读取对应模型 ID
                if not model_id:
                    try:
                        from backend.config.ai_config import get_config_manager
                        _cfg = get_config_manager()
                        _field_map = {
                            'openai': 'openai_model', 'gpt4v': 'gpt4v_model',
                            'custom_openai': 'custom_openai_model', 'custom_vision': 'custom_openai_vision_model',
                        }
                        _f = _field_map.get(api_type)
                        if _f:
                            if api_type in ('gpt4v',):
                                model_id = getattr(_cfg.vision_config, _f, '') or ''
                            else:
                                model_id = getattr(_cfg.llm_config, _f, '') or ''
                            if api_type == 'custom_vision' and not model_id:
                                model_id = getattr(_cfg.llm_config, 'custom_openai_model', '') or ''
                    except Exception:
                        pass

                valid_base_url, base_url_error = _validate_outbound_base_url(base)
                if not valid_base_url:
                    return err(400, base_url_error)
                headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
                # 只有用户在设置页主动确认后，才发送内置极小测试图执行真实视觉推理。
                if visual_probe:
                    if not model_id:
                        return err(400, '请先选择视觉模型。')
                    try:
                        r = requests.post(
                            base + '/chat/completions',
                            headers=headers,
                            json={
                                'model': model_id,
                                'messages': [{'role': 'user', 'content': [
                                    {'type': 'text', 'text': '只回答图片主颜色。'},
                                    {'type': 'image_url', 'image_url': {
                                        'url': f'data:image/jpeg;base64,{_VISUAL_PROBE_JPEG_BASE64}'
                                    }},
                                ]}],
                                'max_tokens': 4,
                                'stream': False,
                            },
                            timeout=max(timeout, 15),
                            allow_redirects=False,
                        )
                        if r.status_code == 200:
                            return ok(_time.perf_counter() - t0, r.status_code, '视觉探测成功')
                        return _err_with_model_hint(base, headers, model_id, r.status_code, r.text)
                    except requests.RequestException:
                        return err(0, '视觉探测请求异常，请检查网络和服务配置。')
                # 普通测试保持纯文本，绝不发送图片以避免产生图片推理费用。
                if model_id:
                    try:
                        r = requests.post(
                            base + '/chat/completions',
                            headers=headers,
                            json={
                                'model': model_id,
                                'messages': [{'role': 'user', 'content': 'hi'}],
                                'max_tokens': 1,
                                'stream': False
                            },
                            timeout=max(timeout, 15)
                        )
                        if r.status_code == 200:
                            return ok(_time.perf_counter()-t0, r.status_code, f'模型 {model_id} 可用')
                        return _err_with_model_hint(base, headers, model_id, r.status_code, r.text)
                    except Exception as exc:
                        return err(0, f'Chat Completions 请求异常：{exc}')
                # 未提供模型 ID 时退回 /models 列表校验
                r = requests.get(base + '/models', headers=headers, timeout=timeout)
                if r.status_code == 200:
                    return ok(_time.perf_counter()-t0, r.status_code, '未指定模型 ID，仅校验 /models 列表')
                return err(r.status_code, r.text[:300])

            # Anthropic / Claude / Claude Vision
            if api_type in ('anthropic', 'claude_vision'):
                base = (base_url.rstrip('/') if base_url else 'https://api.anthropic.com')
                valid_base_url, base_url_error = _validate_outbound_base_url(base)
                if not valid_base_url:
                    return err(400, base_url_error)
                headers = {'x-api-key': api_key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
                if visual_probe:
                    model_id = str(extra.get('model') or '').strip()
                    if not model_id:
                        return err(400, '请先选择视觉模型。')
                    url = base + '/messages' if base.endswith('/v1') else base + '/v1/messages'
                    try:
                        r = requests.post(
                            url,
                            headers=headers,
                            json={
                                'model': model_id,
                                'max_tokens': 4,
                                'messages': [{'role': 'user', 'content': [
                                    {'type': 'image', 'source': {
                                        'type': 'base64', 'media_type': 'image/jpeg',
                                        'data': _VISUAL_PROBE_JPEG_BASE64,
                                    }},
                                    {'type': 'text', 'text': '只回答图片主颜色。'},
                                ]}],
                            },
                            timeout=max(timeout, 15),
                            allow_redirects=False,
                        )
                        if r.status_code == 200:
                            return ok(_time.perf_counter() - t0, r.status_code, '视觉探测成功')
                        return err(r.status_code, r.text[:300] or '视觉探测请求被上游拒绝。')
                    except requests.RequestException:
                        return err(0, '视觉探测请求异常，请检查网络和服务配置。')
                url = base + '/models' if base.endswith('/v1') else base + '/v1/models'
                r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=False)
                if r.status_code == 200:
                    return ok(_time.perf_counter()-t0, r.status_code)
                return err(r.status_code, r.text[:300])

            # Google Gemini / Gemini Vision
            if api_type in ('gemini', 'gemini_vision'):
                base = (base_url.rstrip('/') if base_url else 'https://generativelanguage.googleapis.com/v1beta')
                if not base.endswith(('/v1beta', '/v1')):
                    base += '/v1beta'
                valid_base_url, base_url_error = _validate_outbound_base_url(base)
                if not valid_base_url:
                    return err(400, base_url_error)
                if visual_probe:
                    model_id = str(extra.get('model') or '').strip()
                    if not model_id:
                        return err(400, '请先选择视觉模型。')
                    try:
                        r = requests.post(
                            base + f'/models/{model_id}:generateContent',
                            params={'key': api_key},
                            json={'contents': [{'parts': [
                                {'text': '只回答图片主颜色。'},
                                {'inline_data': {
                                    'mime_type': 'image/jpeg', 'data': _VISUAL_PROBE_JPEG_BASE64,
                                }},
                            ]}], 'generationConfig': {'maxOutputTokens': 4}},
                            timeout=max(timeout, 15),
                            allow_redirects=False,
                        )
                        if r.status_code == 200:
                            return ok(_time.perf_counter() - t0, r.status_code, '视觉探测成功')
                        return err(r.status_code, r.text[:300] or '视觉探测请求被上游拒绝。')
                    except requests.RequestException:
                        return err(0, '视觉探测请求异常，请检查网络和服务配置。')
                r = requests.get(base + '/models', params={'key': api_key}, timeout=timeout, allow_redirects=False)
                if r.status_code == 200:
                    return ok(_time.perf_counter()-t0, r.status_code)
                return err(r.status_code, r.text[:300])

            # DeepSeek
            if api_type == 'deepseek':
                base = (base_url.rstrip('/') if base_url else 'https://api.deepseek.com/v1')
                url = base + '/models'
                headers = {'Authorization': f'Bearer {api_key}'}
                r = requests.get(url, headers=headers, timeout=timeout)
                if r.status_code == 200:
                    return ok(_time.perf_counter()-t0, r.status_code)
                return err(r.status_code, r.text[:300])

            # Kimi (Moonshot)
            if api_type == 'kimi':
                base = (base_url.rstrip('/') if base_url else 'https://api.moonshot.cn/v1')
                url = base + '/models'
                headers = {'Authorization': f'Bearer {api_key}'}
                r = requests.get(url, headers=headers, timeout=timeout)
                if r.status_code == 200:
                    return ok(_time.perf_counter()-t0, r.status_code)
                return err(r.status_code, r.text[:300])

            # 通义千问 / Qwen-VL（DashScope OpenAI 兼容接口）
            if api_type in ('qwen', 'qwen_vl'):
                base = (base_url.rstrip('/') if base_url else 'https://dashscope.aliyuncs.com/compatible-mode/v1')
                url = base + '/models'
                headers = {'Authorization': f'Bearer {api_key}'}
                r = requests.get(url, headers=headers, timeout=timeout)
                if r.status_code in (200, 401, 403):  # 401/403 也代表网络可达与Key已校验
                    if r.status_code == 200:
                        return ok(_time.perf_counter()-t0, r.status_code)
                    return err(r.status_code, r.text[:300])
                return err(r.status_code, r.text[:300])

            # 文心一言 (Baidu) - 仅获取access_token校验
            if api_type in ('ernie', 'wenxin'):
                try:
                    ak, sk = (api_key.split(':', 1) + [''])[:2]
                except Exception:
                    ak, sk = api_key, ''
                if not ak or not sk:
                    return err(400, '需要传入 "api_key:secret_key"')
                token_url = f'https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={ak}&client_secret={sk}'
                r = requests.get(token_url, timeout=timeout)
                if r.status_code == 200 and 'access_token' in r.text:
                    return ok(_time.perf_counter()-t0, r.status_code)
                return err(r.status_code, r.text[:300])

            # ChatGLM (Zhipu)
            if api_type in ('chatglm', 'zhipu'):
                if not api_key:
                    return err(400, '需要填写 API Key')
                base = (base_url.rstrip('/') if base_url else 'https://open.bigmodel.cn/api/paas/v4')
                url = base + '/models'
                headers = {'Authorization': f'Bearer {api_key}'}
                r = requests.get(url, headers=headers, timeout=timeout)
                if r.status_code in (200, 401, 403):
                    if r.status_code == 200:
                        return ok(_time.perf_counter()-t0, r.status_code)
                    return err(r.status_code, r.text[:300])
                return err(r.status_code, r.text[:300])

            # OpenRouter（中转站）
            if api_type == 'openrouter':
                base = (base_url.rstrip('/') if base_url else 'https://openrouter.ai/api/v1')
                url = base + '/models'
                headers = {'Authorization': f'Bearer {api_key}'}
                r = requests.get(url, headers=headers, timeout=timeout)
                if r.status_code == 200:
                    return ok(_time.perf_counter()-t0, r.status_code)
                return err(r.status_code, r.text[:300])

            # SiliconFlow（硅基流动中转站）
            if api_type == 'siliconflow':
                base = (base_url.rstrip('/') if base_url else 'https://api.siliconflow.cn/v1')
                url = base + '/models'
                headers = {'Authorization': f'Bearer {api_key}'}
                r = requests.get(url, headers=headers, timeout=timeout)
                if r.status_code == 200:
                    return ok(_time.perf_counter()-t0, r.status_code)
                return err(r.status_code, r.text[:300])

            # 火山豆包
            if api_type == 'doubao':
                base = (base_url.rstrip('/') if base_url else 'https://ark.cn-beijing.volces.com/api/v3')
                url = base + '/models'
                headers = {'Authorization': f'Bearer {api_key}'}
                r = requests.get(url, headers=headers, timeout=timeout)
                if r.status_code in (200, 401, 403):
                    if r.status_code == 200:
                        return ok(_time.perf_counter()-t0, r.status_code)
                    return err(r.status_code, r.text[:300])
                return err(r.status_code, r.text[:300])

            # 讯飞星火：调用鉴权后的 WebSocket 握手，验证 APPID、API Key 与 API Secret。
            if api_type == 'spark':
                import base64
                import hashlib
                import hmac
                from datetime import datetime, timezone
                from email.utils import format_datetime
                from urllib.parse import urlencode

                appid = str(extra.get('appid') or '').strip()
                api_secret = str(extra.get('api_secret') or '').strip()
                if not appid or not api_key or not api_secret:
                    return err(400, '需要填写 APPID、API Key 和 API Secret')

                host = 'spark-api.xf-yun.com'
                path = '/v3.5/chat'
                date = format_datetime(datetime.now(timezone.utc), usegmt=True)
                signature_origin = f'host: {host}\ndate: {date}\nGET {path} HTTP/1.1'
                signature = base64.b64encode(
                    hmac.new(
                        api_secret.encode('utf-8'),
                        signature_origin.encode('utf-8'),
                        digestmod=hashlib.sha256,
                    ).digest()
                ).decode('utf-8')
                authorization_origin = (
                    f'api_key="{api_key}", algorithm="hmac-sha256", '
                    f'headers="host date request-line", signature="{signature}"'
                )
                authorization = base64.b64encode(
                    authorization_origin.encode('utf-8')
                ).decode('utf-8')
                query = urlencode({
                    'authorization': authorization,
                    'date': date,
                    'host': host,
                })
                url = f'https://{host}{path}?{query}'
                import http.client
                import os

                headers = {
                    'Host': host,
                    'Origin': 'https://spark-api.xf-yun.com',
                    'Connection': 'Upgrade',
                    'Upgrade': 'websocket',
                    'Sec-WebSocket-Version': '13',
                    'Sec-WebSocket-Key': base64.b64encode(os.urandom(16)).decode('ascii'),
                }
                connection = http.client.HTTPSConnection(host, timeout=timeout)
                connection.request('GET', f'{path}?{query}', headers=headers)
                response = connection.getresponse()
                status = response.status
                detail = response.read(300).decode('utf-8', errors='replace')
                connection.close()
                if status == 101:
                    return ok(_time.perf_counter() - t0, status, 'WebSocket 鉴权成功')
                return err(status, detail)

            # Azure TTS - 列出可用声音
            if api_type in ('azure-tts', 'azure'):
                region = (extra.get('region') or '').strip() or 'eastus'
                url = f'https://{region}.tts.speech.microsoft.com/cognitiveservices/voices/list'
                headers = {'Ocp-Apim-Subscription-Key': api_key}
                r = requests.get(url, headers=headers, timeout=timeout)
                if r.status_code == 200:
                    return ok(_time.perf_counter()-t0, r.status_code, f'{len(r.json())} voices')
                return err(r.status_code, r.text[:300])

            return jsonify({'code': 1, 'msg': f'不支持的api_type: {api_type}', 'data': None}), 400

        except Exception as e:
            logger.error(f'❌ 测试API连接失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'测试失败: {str(e)}', 'data': None}), 500

    @app.route('/api/settings/reset', methods=['POST'])
    def reset_all_settings():
        """恢复所有设置为默认值（删除 settings 表中记录）"""
        conn = None
        try:
            conn = db_manager.get_connection()
            cur = conn.cursor()
            cur.execute('DELETE FROM settings')
            conn.commit()

            from backend.config.ai_config import (
                CensorConfig, GlobalConfig, LLMConfig, LocalModelConfig, ProxyConfig,
                TTSConfig, TTSModelConfig, VisionConfig, get_config_manager,
            )
            cfg = get_config_manager()
            cfg.llm_config = LLMConfig()
            cfg.vision_config = VisionConfig()
            cfg.tts_model_config = TTSModelConfig()
            cfg.proxy_config = ProxyConfig()
            cfg.tts_config = TTSConfig()
            cfg.censor_config = CensorConfig()
            cfg.global_config = GlobalConfig()
            cfg.local_model_config = LocalModelConfig()
            if not cfg.save_config():
                raise RuntimeError('默认配置保存失败')

            gs = get_global_state()
            if not gs.reload_config():
                raise RuntimeError('运行时配置重载失败')
            for category in gs.user_settings:
                gs.user_settings[category] = {}
            _apply_proxy_settings({})
            gs.emit_event('settings_updated', {
                'keys': list(gs.user_settings.keys()),
                'settings': gs.user_settings,
            })
            return jsonify({'code': 0, 'msg': '重置成功', 'data': None})
        except Exception as e:
            logger.error(f'❌ 重置设置失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'重置失败: {str(e)}', 'data': None}), 500
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    @app.route('/api/settings/clear-cache', methods=['POST'])
    def clear_cache():
        """清理临时缓存目录"""
        try:
            from backend.config.paths import clean_temp_dir
            stats = clean_temp_dir()
            return jsonify({'code': 0, 'msg': '清理成功', 'data': stats})
        except Exception as e:
            logger.error(f'❌ 清理缓存失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'清理失败: {str(e)}', 'data': None}), 500

    @app.route('/api/update/check', methods=['GET'])
    def check_update():
        """检查更新

        当前未集成远程更新服务，因此只返回本地版本信息，并提示无在线更新。
        """
        try:
            try:
                # 优先从 backend 包中获取版本号
                from backend import __version__ as backend_version
                current_version = str(backend_version)
            except Exception:
                current_version = '3.0'

            data = {
                'hasUpdate': False,
                'version': current_version,
                'notes': '当前安装版本为本地构建，尚未配置远程更新服务。如需升级，请关注项目发布页或手动下载安装新版。'
            }
            return jsonify({'code': 0, 'msg': '获取成功', 'data': data})
        except Exception as e:
            logger.error(f'❌ 检查更新失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'检查失败: {str(e)}', 'data': None}), 500

    @app.route('/api/update/download', methods=['POST'])
    def download_update():
        """下载更新

        当前未配置在线更新/下载通道，接口仅返回说明信息，不提供虚构下载链接。
        """
        try:
            return jsonify({
                'code': 1,
                'msg': '当前版本未集成自动更新通道，请前往项目发布页手动下载最新安装包。',
                'data': {
                    'downloadUrl': None
                }
            })
        except Exception as e:
            logger.error(f'❌ 下载更新失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'下载失败: {str(e)}', 'data': None}), 500

    # ====== 辅助函数：设置实时生效 ======
    def _apply_proxy_settings(advanced_config):
        """应用代理设置到环境变量和全局配置"""
        try:
            proxy_enable = advanced_config.get('proxyEnable', False)
            proxy_server = advanced_config.get('proxyServer', '')

            if proxy_enable and proxy_server:
                import os
                os.environ['HTTP_PROXY'] = proxy_server
                os.environ['HTTPS_PROXY'] = proxy_server
                os.environ['http_proxy'] = proxy_server
                os.environ['https_proxy'] = proxy_server
                logger.info(f'✅ 代理已启用: {proxy_server}')
            else:
                import os
                for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
                    if key in os.environ:
                        del os.environ[key]
                logger.info('✅ 代理已禁用')

            # 更新配置管理器中的代理配置
            try:
                from backend.config.ai_config import get_config_manager
                cfg = get_config_manager()
                if hasattr(cfg, 'proxy_config'):
                    cfg.proxy_config.use_proxy = proxy_enable
                    cfg.proxy_config.proxy_url = proxy_server
                    cfg.save_config()
            except Exception:
                pass
        except Exception as e:
            logger.warning(f'⚠️ 应用代理设置时出错: {e}')

    def _apply_log_level(level_str):
        """应用日志级别"""
        try:
            import logging
            level_map = {
                'debug': logging.DEBUG,
                'info': logging.INFO,
                'warning': logging.WARNING,
                'error': logging.ERROR,
            }
            level = level_map.get(str(level_str).lower(), logging.INFO)

            # 更新根日志级别
            logging.getLogger().setLevel(level)

            # 更新项目日志级别
            for logger_name in ['JJYB_AI智剪', 'JJYB_AI智剪']:
                lg = logging.getLogger(logger_name)
                if lg:
                    lg.setLevel(level)

            logger.info(f'✅ 日志级别已设置为: {level_str}')
        except Exception as e:
            logger.warning(f'⚠️ 应用日志级别时出错: {e}')

    logger.info('✅ 设置管理API路由注册完成')
