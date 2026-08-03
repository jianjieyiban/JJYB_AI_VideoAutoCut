"""
配置管理API路由
处理所有配置的保存、读取和同步
"""

import logging
from dataclasses import asdict, fields
from flask import request, jsonify

logger = logging.getLogger('JJYB_AI智剪')


def register_config_routes(app):
    """注册配置管理路由"""

    from backend.config.ai_config import get_config_manager
    from backend.core.global_state import get_global_state

    def _is_sensitive(name):
        lowered = name.lower()
        return 'api_key' in lowered or 'secret' in lowered or lowered.endswith('_key')

    def _looks_like_masked_value(name: str, value) -> bool:
        """判断字符串看起来像掩码值（应跳过，避免覆盖真实密钥）。

        条件（满足任一即可跳过保存）：
        1) 只含 * 字符（原判断，兼容旧格式 8 个连续 *）
        2) 含连续 4 个或以上 *（如 sk-***************** 等）
        3) 长度 >= 8 且 * 字符占比 >= 30%（如自定义占位掩码 ****A****）
        """
        if not isinstance(value, str):
            return False
        s = value.strip()
        if not s:
            return False
        if not _is_sensitive(name):
            return False
        # 条件 1：全星号
        if set(s) == {'*'}:
            return True
        # 条件 2：连续 4 个及以上星号
        if '****' in s:
            return True
        # 条件 3：星号占比 >= 30% 且长度 >= 8
        if len(s) >= 8 and (s.count('*') / len(s)) >= 0.30:
            return True
        return False

    def _masked_dataclass(config):
        result = asdict(config)
        for name, value in result.items():
            if _is_sensitive(name) and isinstance(value, str) and value:
                result[name] = '*' * 8
        return result

    def _apply_dataclass(config, data):
        allowed = {field.name for field in fields(config)}
        for name, value in (data or {}).items():
            if name not in allowed or value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
                # 增强：看起来像掩码的字符串一律跳过，避免把 8* / ****A**** / sk-********* 之类存进去
                if _looks_like_masked_value(name, value):
                    logger.info(f'🙈 跳过疑似掩码字符串，不覆盖 {type(config).__name__}.{name}')
                    continue
            setattr(config, name, value)

    global_state = get_global_state()

    @app.route('/api/config/llm', methods=['GET'])
    def get_llm_config():
        """获取LLM配置"""
        try:
            config_manager = get_config_manager()
            config = _masked_dataclass(config_manager.llm_config)
            return jsonify({'code': 0, 'msg': '获取成功', 'data': config})
        except Exception as e:
            logger.error(f'❌ 获取LLM配置失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/config/llm', methods=['POST'])
    def save_llm_config():
        """保存LLM配置"""
        try:
            data = request.get_json() or {}
            config_manager = get_config_manager()
            _apply_dataclass(config_manager.llm_config, data)
            if 'default_model' in data:
                config_manager.llm_config.default_model = config_manager.normalize_llm_provider(data['default_model'])
            config_manager.save_config()
            if not global_state.reload_config():
                raise RuntimeError('运行时配置重载失败')
            if 'default_model' in data:
                global_state.set_active_llm_model(config_manager.llm_config.default_model)

            logger.info('✅ LLM配置保存成功')
            return jsonify({'code': 0, 'msg': '保存成功', 'data': None})

        except Exception as e:
            logger.error(f'❌ 保存LLM配置失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/config/vision', methods=['GET'])
    def get_vision_config():
        """获取视觉模型配置"""
        try:
            config_manager = get_config_manager()
            config = _masked_dataclass(config_manager.vision_config)
            return jsonify({'code': 0, 'msg': '获取成功', 'data': config})
        except Exception as e:
            logger.error(f'❌ 获取视觉配置失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/config/vision', methods=['POST'])
    def save_vision_config():
        """保存视觉模型配置"""
        try:
            data = request.get_json() or {}
            config_manager = get_config_manager()
            _apply_dataclass(config_manager.vision_config, data)
            if 'default_model' in data:
                config_manager.vision_config.default_model = config_manager.normalize_vision_provider(data['default_model'])
            config_manager.save_config()
            if not global_state.reload_config():
                raise RuntimeError('运行时配置重载失败')
            if 'default_model' in data:
                global_state.set_active_vision_model(config_manager.vision_config.default_model)

            logger.info('✅ 视觉配置保存成功')
            return jsonify({'code': 0, 'msg': '保存成功', 'data': None})

        except Exception as e:
            logger.error(f'❌ 保存视觉配置失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/config/censor', methods=['GET'])
    def get_censor_config():
        """获取违禁词配置"""
        try:
            config_manager = get_config_manager()
            config = {
                'enable_censor': config_manager.censor_config.enable_censor,
                'censor_tool': config_manager.censor_config.censor_tool,
                'custom_words': config_manager.censor_config.custom_words
            }
            return jsonify({'code': 0, 'msg': '获取成功', 'data': config})
        except Exception as e:
            logger.error(f'❌ 获取违禁词配置失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/config/censor', methods=['POST'])
    def save_censor_config():
        """保存违禁词配置"""
        try:
            data = request.get_json() or {}
            config_manager = get_config_manager()

            if 'enable_censor' in data:
                config_manager.censor_config.enable_censor = data['enable_censor']
            if 'censor_tool' in data:
                config_manager.censor_config.censor_tool = data['censor_tool']
            if 'custom_words' in data:
                config_manager.censor_config.custom_words = data['custom_words']

            config_manager.save_config()
            config_manager.save_censor_words()

            logger.info('✅ 违禁词配置保存成功')
            return jsonify({'code': 0, 'msg': '保存成功', 'data': None})

        except Exception as e:
            logger.error(f'❌ 保存违禁词配置失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/config/censor/add', methods=['POST'])
    def add_censor_word():
        """添加违禁词"""
        try:
            data = request.get_json()
            word = data.get('word')
            category = data.get('category', '其他')

            if not word:
                return jsonify({'code': 1, 'msg': '违禁词不能为空', 'data': None}), 400

            success = config_manager.add_censor_word(word, category)

            if success:
                return jsonify({'code': 0, 'msg': '添加成功', 'data': None})
            else:
                return jsonify({'code': 1, 'msg': '违禁词已存在', 'data': None}), 400

        except Exception as e:
            logger.error(f'❌ 添加违禁词失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/config/censor/remove', methods=['POST'])
    def remove_censor_word():
        """删除违禁词"""
        try:
            data = request.get_json()
            word = data.get('word')

            if not word:
                return jsonify({'code': 1, 'msg': '违禁词不能为空', 'data': None}), 400

            success = config_manager.remove_censor_word(word)

            if success:
                return jsonify({'code': 0, 'msg': '删除成功', 'data': None})
            else:
                return jsonify({'code': 1, 'msg': '违禁词不存在', 'data': None}), 400

        except Exception as e:
            logger.error(f'❌ 删除违禁词失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/config/models/available', methods=['GET'])
    def get_available_models():
        """获取所有可用的模型"""
        try:
            models = global_state.get_available_models()
            return jsonify({'code': 0, 'msg': '获取成功', 'data': models})
        except Exception as e:
            logger.error(f'❌ 获取可用模型失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/config/models/switch', methods=['POST'])
    def switch_model():
        """切换模型"""
        try:
            data = request.get_json()
            model_type = data.get('type')  # 'llm' or 'vision'
            model_name = data.get('model')

            if model_type == 'llm':
                global_state.set_active_llm_model(model_name)
            elif model_type == 'vision':
                global_state.set_active_vision_model(model_name)
            else:
                return jsonify({'code': 1, 'msg': '无效的模型类型', 'data': None}), 400

            return jsonify({'code': 0, 'msg': '切换成功', 'data': None})

        except Exception as e:
            logger.error(f'❌ 切换模型失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/config/system/status', methods=['GET'])
    def get_system_status():
        """获取系统状态"""
        try:
            status = global_state.get_system_status()
            return jsonify({'code': 0, 'msg': '获取成功', 'data': status})
        except Exception as e:
            logger.error(f'❌ 获取系统状态失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/config/reload', methods=['POST'])
    def reload_config():
        """重新加载配置"""
        try:
            success = global_state.reload_config()
            if success:
                return jsonify({'code': 0, 'msg': '重新加载成功', 'data': None})
            else:
                return jsonify({'code': 1, 'msg': '重新加载失败', 'data': None}), 500
        except Exception as e:
            logger.error(f'❌ 重新加载配置失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    # ================= 封面图像生成配置 =================

    @app.route('/api/config/image', methods=['GET'])
    def get_image_config():
        """获取封面/图像生成配置。

        注意：API Key 不做服务端脱敏！
        原因：前端 input[type="password"] 本身会把输入显示为小圆点（用户看不到明文），
        但 input.value 必须是真实字符串，否则用户"重新打开后没重新手动输入 Key 就点保存"时，
        会把服务端返回的 8 个 * 当成真实 Key 覆盖数据库中的真实值，导致后续生成时走 fallback。
        这里是本机内部接口（127.0.0.1），不存在明文传输给公网第三方的安全风险。
        """
        try:
            config_manager = get_config_manager()
            # 不做 _masked_dataclass：直接返回真实 Key（input[type=password] 前端会自动显示成小圆点）
            config = asdict(config_manager.image_config)
            # 顺便注入当前连接信息（不含密钥，仅用于前端展示默认参数）
            conn = {
                'default_size': config_manager.image_config.default_size,
                'default_quality': config_manager.image_config.default_quality,
                'default_style': config_manager.image_config.default_style,
                'default_n': config_manager.image_config.default_n,
                'save_dir': config_manager.image_config.save_dir,
                'provider': config_manager.normalize_image_provider(),
            }
            config['_connection'] = conn
            return jsonify({'code': 0, 'msg': '获取成功', 'data': config})
        except Exception as e:
            logger.error(f'❌ 获取封面生成配置失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/config/image', methods=['POST'])
    def save_image_config():
        """保存封面/图像生成配置"""
        try:
            data = request.get_json() or {}
            config_manager = get_config_manager()
            _apply_dataclass(config_manager.image_config, data)
            if 'default_model' in data:
                config_manager.image_config.default_model = config_manager.normalize_image_provider(data['default_model'])
            config_manager.save_config()
            if not global_state.reload_config():
                raise RuntimeError('运行时配置重载失败')
            logger.info('✅ 封面生成配置保存成功')
            return jsonify({'code': 0, 'msg': '保存成功', 'data': None})
        except Exception as e:
            logger.error(f'❌ 保存封面生成配置失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/config/image/test', methods=['POST'])
    def test_image_config():
        """测试封面生成配置连通性（轻量级：只发一个极小prompt验证key/URL是否可达）"""
        try:
            import time
            import requests as _req

            data = request.get_json() or {}
            provider = (data.get('provider') or '').strip() or None
            config_manager = get_config_manager()
            conn = config_manager.get_image_connection(provider)

            api_key = conn.get('api_key') or conn.get('secret_id')
            secret_key = conn.get('secret_key') or ''
            base_url = (conn.get('base_url') or '').rstrip('/')
            model = conn.get('model') or ''
            norm_provider = config_manager.normalize_image_provider(provider)

            masked_fields = [
                name for name, value in (
                    ('api_key', conn.get('api_key')),
                    ('secret_id', conn.get('secret_id')),
                    ('secret_key', secret_key),
                ) if _looks_like_masked_value(name, value)
            ]
            if masked_fields:
                return jsonify({
                    'code': 1,
                    'msg': '图片专属密钥是掩码污染值，真实 Key 无法恢复，请在图片区重新输入完整 Key 并保存',
                    'reason': 'masked_key_corrupted',
                    'data': {'provider': norm_provider, 'ok': False, 'reason': 'masked_key_corrupted'},
                }), 422

            # 把取到的 Key 特征打印到日志，方便排查"取到了 8 个 * / 空值"
            try:
                s = str(api_key or '')
                if len(s) >= 12:
                    preview = s[:8] + '*' * (len(s) - 11) + s[-3:]
                elif len(s) > 0:
                    preview = '*' * len(s)
                else:
                    preview = '(EMPTY!)'
                logger.info(f'[test-image-config] 测试图像模型连通: provider={norm_provider}, base={base_url or "(空)"}, model={model or "(空)"}, key={preview}')
            except Exception:
                pass

            if not api_key:
                return jsonify({
                    'code': 1,
                    'msg': (f'{norm_provider} 尚未配置 API Key / SecretId。'
                            f'请打开「设置 → API 配置 → 图片生成模型 / 自定义 OpenAI 兼容（图像版）」填好后，先点「保存配置」再测试。'),
                    'data': {'provider': norm_provider, 'ok': False}
                }), 422
            if norm_provider not in ('baidu', 'tencent') and not base_url:
                return jsonify({
                    'code': 1,
                    'msg': f'{norm_provider} 缺少 Base URL（请填好并先点保存配置）',
                    'data': {'provider': norm_provider, 'ok': False}
                }), 422

            # 不同厂商走不同的轻量测试方式
            t0 = time.time()
            ok, info = False, ''
            timeout = 12
            try:
                if norm_provider in ('openai', 'siliconflow', 'openrouter', 'doubao', 'chatglm', 'custom_openai', 'minimax', 'qwen'):
                    # 统一走 OpenAI 兼容的 /models 列表探测（最轻，不消耗额度）
                    test_url = f'{base_url}/models'
                    headers = {'Authorization': f'Bearer {api_key}'}
                    if norm_provider == 'minimax' and conn.get('group_id'):
                        headers['X-Flexflow-Group-ID'] = conn['group_id']
                    r = _req.get(test_url, headers=headers, timeout=timeout)
                    ok = 200 <= r.status_code < 400
                    info = f'GET /models -> HTTP {r.status_code}'
                    if not ok:
                        snippet = (r.text or '').strip()[:200]
                        info += f'  {snippet}'
                elif norm_provider == 'baidu':
                    # 百度：请求 token 接口探测
                    r = _req.post(
                        'https://aip.baidubce.com/oauth/2.0/token',
                        params={'grant_type': 'client_credentials',
                                'client_id': api_key,
                                'client_secret': conn.get('secret_key') or ''},
                        timeout=timeout,
                    )
                    ok = 200 <= r.status_code < 400 and 'access_token' in (r.text or '')
                    info = f'百度token探测 -> HTTP {r.status_code}'
                elif norm_provider == 'tencent':
                    # 腾讯：密钥格式校验即可（实际签名调用复杂，避免这里引入SDK依赖）
                    sid = conn.get('secret_id') or ''
                    skey = conn.get('secret_key') or ''
                    ok = len(sid) >= 8 and len(skey) >= 8
                    info = '腾讯 SecretId/SecretKey 长度校验' if ok else '腾讯 SecretId/SecretKey 过短'
                else:
                    ok, info = False, f'暂不支持 {norm_provider} 的自动探测，请直接使用'
            except Exception as req_e:
                ok, info = False, f'网络请求失败: {req_e}'

            dt = round(time.time() - t0, 2)
            if ok:
                return jsonify({
                    'code': 0,
                    'msg': f'{norm_provider} 连接成功 · {info} · 耗时 {dt}s',
                    'data': {'provider': norm_provider, 'model': model, 'latency_s': dt, 'ok': True}
                })
            return jsonify({
                'code': 1,
                'msg': f'{norm_provider} 连接失败 · {info}',
                'data': {'provider': norm_provider, 'model': model, 'latency_s': dt, 'ok': False}
            }), 502
        except Exception as e:
            logger.error(f'❌ 测试封面配置失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/config/image/providers', methods=['GET'])
    def list_image_providers():
        """返回支持的封面生成厂商列表（给前端下拉框）"""
        providers = [
            {'key': 'custom_openai', 'label': '自定义 OpenAI 兼容（推荐）', 'hint': 'SD / Flux / 自建代理 / OneAPI / NewAPI'},
            {'key': 'siliconflow',  'label': 'SiliconFlow 聚合图像（SD3/Flux）', 'hint': '国内可访问，支持多款开源模型'},
            {'key': 'openrouter',   'label': 'OpenRouter 聚合', 'hint': 'DALL-E 3 / SD3 等'},
            {'key': 'openai',       'label': 'OpenAI DALL-E 3', 'hint': '官方原版，需海外网络'},
            {'key': 'qwen',         'label': '阿里云 通义万相', 'hint': 'DashScope wanx-v1'},
            {'key': 'doubao',       'label': '字节 豆包生图（Seedream）', 'hint': '火山方舟'},
            {'key': 'chatglm',      'label': '智谱 CogView', 'hint': 'BigModel.cn'},
            {'key': 'minimax',      'label': 'MiniMax 日月生图', 'hint': 'MiniMax Chat'},
            {'key': 'baidu',        'label': '百度 文心一格', 'hint': '百度智能云 AI 绘画'},
            {'key': 'tencent',      'label': '腾讯 混元生图', 'hint': '腾讯云 TII'},
        ]
        return jsonify({'code': 0, 'msg': 'ok', 'data': providers})

    @app.route('/api/config/get', methods=['GET'])
    def get_all_config():
        """获取所有配置（统一接口）"""
        try:
            config_data = {
                'llm': _masked_dataclass(config_manager.llm_config),
                'vision': _masked_dataclass(config_manager.vision_config),
                'tts_model': _masked_dataclass(config_manager.tts_model_config),
                'image': _masked_dataclass(config_manager.image_config),
                'proxy': asdict(config_manager.proxy_config),
                'tts': asdict(config_manager.tts_config),
                'censor': asdict(config_manager.censor_config),
                'global': asdict(config_manager.global_config),
                'local_model': asdict(config_manager.local_model_config)
            }
            return jsonify({'code': 0, 'msg': '获取配置成功', 'data': {'config': config_data}})
        except Exception as e:
            logger.error(f'❌ 获取配置失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/config/save', methods=['POST'])
    def save_all_config():
        """保存所有配置（统一接口）"""
        try:
            logger.info('=' * 80)
            logger.info('💾 [统一配置保存] 开始处理请求')

            data = request.get_json() or {}
            config_manager = get_config_manager()
            # 过滤空值与脱敏占位值，避免覆盖真实密钥
            def _should_keep(k, v):
                if v is None:
                    return False
                if isinstance(v, str):
                    s = v.strip()
                    if s == '':
                        return False
                    if ('api_key' in k.lower()) or ('secret' in k.lower()):
                        star = s.count('*')
                        if star >= 4 and star >= (len(s) // 2):
                            logger.info(f'🙈 [统一配置保存] 跳过脱敏/占位值: {k}')
                            return False
                return True
            data = {kk: vv for kk, vv in data.items() if _should_keep(kk, vv)}

            updated_keys = []
            for config_name, config in (
                ('llm', config_manager.llm_config),
                ('vision', config_manager.vision_config),
                ('tts_model', config_manager.tts_model_config),
                ('image', config_manager.image_config),
            ):
                before = asdict(config)
                _apply_dataclass(config, data.get(config_name, data))
                updated_keys.extend(
                    f'{config_name}.{name}' for name, value in asdict(config).items()
                    if before.get(name) != value
                )
            if 'default_model' in data:
                config_manager.llm_config.default_model = config_manager.normalize_llm_provider(data['default_model'])
            if 'default_vision_model' in data:
                config_manager.vision_config.default_model = config_manager.normalize_vision_provider(data['default_vision_model'])
            if 'default_image_model' in data:
                config_manager.image_config.default_model = config_manager.normalize_image_provider(data['default_image_model'])

            logger.info(f'📝 [统一配置保存] 更新了 {len(updated_keys)} 个配置项: {updated_keys}')

            # 保存配置到文件
            logger.info('💾 [统一配置保存] 准备保存配置文件...')
            config_manager.save_config()
            if not global_state.reload_config():
                raise RuntimeError('运行时配置重载失败')
            logger.info('✅ [统一配置保存] 配置文件保存并已应用！')

            logger.info('🎉 [统一配置保存] 全部完成！')
            logger.info('=' * 80)
            return jsonify({'code': 0, 'msg': '配置保存成功', 'data': None})

        except Exception as e:
            logger.error(f'❌ [统一配置保存] 发生异常: {e}', exc_info=True)
            logger.info('=' * 80)
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    logger.info('✅ 配置管理路由注册完成')

    # ================================================================== #
    # /api/ai-config/* 兼容端点（前端 commentary.html 直接调用）
    # ================================================================== #

    @app.route('/api/ai-config/get', methods=['GET'])
    def ai_config_get():
        """获取AI配置（兼容前端 /api/ai-config/get 调用）"""
        try:
            config_data = {
                'llm': _masked_dataclass(config_manager.llm_config),
                'vision': _masked_dataclass(config_manager.vision_config),
                'tts_model': _masked_dataclass(config_manager.tts_model_config),
                'image': _masked_dataclass(config_manager.image_config),
                'proxy': asdict(config_manager.proxy_config),
                'tts': asdict(config_manager.tts_config),
                'censor': asdict(config_manager.censor_config),
                'global': asdict(config_manager.global_config),
                'local_model': asdict(config_manager.local_model_config),
                'jianying_draft_path': getattr(config_manager.global_config, 'jianying_draft_path', ''),
                'tts_workers': getattr(config_manager.tts_config, 'workers', 4),
            }
            return jsonify({'code': 0, 'msg': '获取成功', 'data': config_data})
        except Exception as e:
            logger.error(f'❌ /api/ai-config/get 失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/ai-config/save', methods=['POST'])
    def ai_config_save():
        """保存AI配置（兼容前端 /api/ai-config/save 调用）"""
        try:
            data = request.get_json() or {}
            # 过滤空值和脱敏占位
            def _should_keep(k, v):
                if v is None: return False
                if isinstance(v, str):
                    s = v.strip()
                    if not s: return False
                    if ('api_key' in k.lower()) or ('secret' in k.lower()):
                        star = s.count('*')
                        if star >= 4 and star >= (len(s) // 2): return False
                return True
            data = {kk: vv for kk, vv in data.items() if _should_keep(kk, vv)}

            updated_keys = []
            for config_name, config in (
                ('llm', config_manager.llm_config),
                ('vision', config_manager.vision_config),
                ('tts_model', config_manager.tts_model_config),
                ('image', config_manager.image_config),
                ('proxy', config_manager.proxy_config),
                ('tts', config_manager.tts_config),
                ('censor', config_manager.censor_config),
                ('global', config_manager.global_config),
                ('local_model', config_manager.local_model_config),
            ):
                sub = data.get(config_name)
                if isinstance(sub, dict) and sub:
                    _apply_dataclass(config, sub)
                    updated_keys.append(config_name)

            # 顶层字段直接映射
            for top_key in ('jianying_draft_path', 'tts_workers'):
                if top_key in data:
                    if top_key == 'jianying_draft_path':
                        setattr(config_manager.global_config, 'jianying_draft_path', str(data[top_key]))
                        updated_keys.append('jianying_draft_path')
                    elif top_key == 'tts_workers':
                        setattr(config_manager.tts_config, 'workers', int(data[top_key]))
                        updated_keys.append('tts_workers')

            if updated_keys:
                config_manager.save_config()
                global_state.reload_config()

            logger.info(f'✅ /api/ai-config/save 完成，更新: {updated_keys}')
            return jsonify({'code': 0, 'msg': '配置保存成功', 'data': {'updated': updated_keys}})
        except Exception as e:
            logger.error(f'❌ /api/ai-config/save 失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/ai-config/test-llm', methods=['POST'])
    def ai_config_test_llm():
        """测试LLM连通性（文本模型专用，不要和图像生成 / 视觉模型混用）。

        brand 取值规则（本次修正避免 system-default 直接传 model_type）：
        - 空 / 'system-default' / 'custom-llm' / None → 使用后台默认文本模型（LLMConfig.default_model，通常是 custom_openai）
        - 具体厂商标（openai/qwen 等）→ 显式选中文本模型厂商
        """
        try:
            data = request.get_json() or {}
            brand_raw = data.get('brand', '') or ''
            brand_str = str(brand_raw).strip()

            from backend.config.ai_config import get_config_manager
            from backend.engine.multi_model_adapter import get_multi_model_manager
            cm = get_config_manager()
            manager = get_multi_model_manager()

            # 1) 把 'system-default' / 空值 / 'custom-llm' 统一解析成真正的文本模型 provider
            resolved_brand: Optional[str]
            if brand_str in ('', 'system-default', 'custom-llm'):
                resolved_brand = None  # 不传 → manager.generate_text 自动读 llm_config.default_model
                display_brand = cm.normalize_llm_provider()
            else:
                resolved_brand = cm.normalize_llm_provider(brand_str)
                display_brand = resolved_brand

            # 2) 确认对应连接是否配了密钥（缺 Key 时给出明确提示，而不是报错 "找不到适配器"）
            try:
                conn = cm.get_llm_connection(resolved_brand)
                if not conn.get('api_key') and resolved_brand not in ('spark', 'ernie'):
                    return jsonify({
                        'code': 1,
                        'msg': (f'{display_brand} 尚未配置 API Key（建议：设置页 → 模型统一后台 → {display_brand} / 自定义 OpenAI 兼容）')
                    })
            except Exception as _ck:
                logger.debug(f'检查 LLM 连接配置时发生警告（不影响）: {_ck}')

            ok = False
            msg = ''
            try:
                resp = manager.chat(
                    messages=[{'role': 'user', 'content': '你好，请回复1'}],
                    model_type=resolved_brand,  # None → 自动读 LLMConfig.default_model
                    max_tokens=10
                )
                ok = bool(resp)
                if ok:
                    preview = (str(resp) or '').strip().replace('\n', ' ')[:40]
                    msg = f'[文本模型] {display_brand} 连通正常（回复: {preview if preview else "空文本"}）'
                else:
                    msg = f'[文本模型] {display_brand} 返回为空'
            except Exception as ex:
                # 把常见报错翻译得更可读
                raw_err = str(ex)
                if '无法获取' in raw_err and '模型适配器' in raw_err:
                    msg = (f'[文本模型] {display_brand} 未找到可用适配器。'
                           f'请在「设置页 → 模型统一后台」填写并保存 自定义 OpenAI（推荐）'
                           f'或其他文本厂商的 API Key / Base URL / 默认模型。详细信息: {raw_err}')
                else:
                    msg = f'[文本模型] {display_brand} 连通失败: {raw_err}'

            return jsonify({'code': 0 if ok else 1, 'msg': msg})
        except Exception as e:
            logger.error(f'❌ /api/ai-config/test-llm 失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'测试内部错误: {e}'}), 500

    @app.route('/api/ai-config/test-all', methods=['POST'])
    def ai_config_test_all():
        """测试所有 API 连通性（三类模型严格分流：文本→chat，视觉→analyze_image，图像→images/models 探测）。"""
        try:
            import requests as _req
            import time as _t
            data = request.get_json() or {}
            results = []

            from backend.config.ai_config import get_config_manager
            from backend.engine.multi_model_adapter import get_multi_model_manager
            cm = get_config_manager()
            manager = get_multi_model_manager()

            test_items = [
                ('[文本] LLM 文案模型',      data.get('llm_brand', 'system-default'),   'llm'),
                ('[视觉] 画面分析模型',      data.get('vision_brand', 'custom-vision'),  'vision'),
                ('[图像] AI 封面生成模型',   data.get('cover_brand', None),              'image'),
                ('[文本] 匹配模型',         data.get('match_brand', 'system-default'),  'llm'),
            ]

            for name, brand, model_type in test_items:
                try:
                    if not brand and model_type != 'image':
                        results.append({'name': name, 'ok': False, 'msg': '未配置品牌'})
                        continue
                    # ========== 1. 文本模型（chat） ==========
                    if model_type == 'llm':
                        resolved = None if brand in ('system-default', '', 'custom-llm') else cm.normalize_llm_provider(brand)
                        resp = manager.chat(
                            messages=[{'role': 'user', 'content': '你好，请回复"收到"'}],
                            model_type=resolved,
                            max_tokens=5
                        )
                        ok = bool(str(resp or '').strip())
                        results.append({
                            'name': name,
                            'ok': ok,
                            'msg': (f'连通正常（回复片段：{(str(resp)[:30] if resp else "空")}）') if ok else '返回为空'
                        })
                        continue
                    # ========== 2. 视觉模型（图生文，需真实图片，但这里做轻量连通性测试：测 /models 或返回配置完整性） ==========
                    if model_type == 'vision':
                        resolved = None if brand in ('system-default', '', 'custom-vision') else brand
                        conn = cm.get_vision_connection(resolved)
                        api_key = conn.get('api_key') or conn.get('secret_id') or ''
                        base_url = conn.get('base_url') or ''
                        prov = conn.get('provider') or ''
                        if not api_key:
                            results.append({'name': name, 'ok': False, 'msg': f'视觉模型 {prov} 未配置 API Key'})
                            continue
                        if base_url and prov not in ('baidu_vision', 'tencent_vision'):
                            # 轻量探测 GET /models（不消耗额度）
                            t0 = _t.time()
                            try:
                                h = {'Authorization': f'Bearer {api_key}'}
                                r = _req.get(f'{base_url}/models', headers=h, timeout=8)
                                dt = round(_t.time() - t0, 2)
                                ok_model = 200 <= r.status_code < 400
                                results.append({
                                    'name': name,
                                    'ok': ok_model,
                                    'msg': (f'{prov} 探测成功 GET /models HTTP {r.status_code} 耗时 {dt}s')
                                           if ok_model else (f'{prov} 探测失败 HTTP {r.status_code}：{(r.text or "")[:120]}')
                                })
                                continue
                            except Exception as _rr:
                                results.append({'name': name, 'ok': False, 'msg': f'{prov} 探测失败（网络问题）: {_rr}'})
                                continue
                        # baidu / tencent / spark 等：只做配置齐全性校验
                        complete = bool(api_key) and (prov != 'baidu_vision' or bool(conn.get('secret_key'))) and (prov != 'tencent_vision' or bool(conn.get('secret_key')))
                        results.append({
                            'name': name,
                            'ok': complete,
                            'msg': (f'{prov} 配置齐全（视觉模型需要真实图片才能完整验证，此处为配置级通过）')
                                   if complete else f'{prov} 配置不完整（缺少 SecretKey / SecretId 等）'
                        })
                        continue
                    # ========== 3. 图像模型（文生图 / 封面）：走 images 专用探测，和 /api/config/image/test 一致 ==========
                    if model_type == 'image':
                        prov = cm.normalize_image_provider(brand)
                        conn = cm.get_image_connection(brand)
                        api_key = conn.get('api_key') or conn.get('secret_id') or ''
                        base_url = conn.get('base_url') or ''
                        if not api_key and prov not in ('baidu', 'tencent'):
                            results.append({'name': name, 'ok': False, 'msg': f'图像模型 {prov} 未配置 API Key / SecretId'})
                            continue
                        if prov in ('baidu', 'tencent'):
                            complete = bool(api_key) and (prov != 'baidu' or bool(conn.get('secret_key'))) and (prov != 'tencent' or bool(conn.get('secret_key')))
                            results.append({
                                'name': name,
                                'ok': complete,
                                'msg': (f'{prov} 配置齐全（百度/腾讯生图需 AK/SK，此处为配置级通过）')
                                       if complete else f'{prov} 缺少 SecretKey / SecretId'
                            })
                            continue
                        if not base_url:
                            results.append({'name': name, 'ok': False, 'msg': f'图像模型 {prov} 缺少 Base URL'})
                            continue
                        # 轻量探测：GET /models（不消耗额度，确保网关可达 + Key 正确）
                        t0 = _t.time()
                        try:
                            headers = {'Authorization': f'Bearer {api_key}'}
                            if prov == 'minimax' and conn.get('group_id'):
                                headers['X-Flexflow-Group-ID'] = str(conn['group_id'])
                            r = _req.get(f'{base_url}/models', headers=headers, timeout=10)
                            dt = round(_t.time() - t0, 2)
                            ok = 200 <= r.status_code < 400
                            results.append({
                                'name': name,
                                'ok': ok,
                                'msg': (f'{prov} 连通成功 GET /models → HTTP {r.status_code} · 耗时 {dt}s')
                                       if ok else (f'{prov} 连通失败 HTTP {r.status_code} · {(r.text or "")[:120]}')
                            })
                        except Exception as _re:
                            results.append({'name': name, 'ok': False, 'msg': f'{prov} 网络请求失败: {_re}'})
                        continue
                except Exception as ex:
                    results.append({'name': name, 'ok': False, 'msg': f'异常: {str(ex)[:160]}'})

            return jsonify({'code': 0, 'msg': '测试完成', 'data': results})
        except Exception as e:
            logger.error(f'❌ /api/ai-config/test-all 失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e), 'data': []}), 500

    logger.info('✅ AI配置兼容路由注册完成 (/api/ai-config/*)')
