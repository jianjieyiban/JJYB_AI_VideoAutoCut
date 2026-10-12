"""
原创解说API路由 - 完整AI流程
"""

import logging
import os
import uuid
import json
import threading
import time
import subprocess
from pathlib import Path
from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename
from backend.config.paths import PROJECT_ROOT

from backend.config.ai_config import (
    AIServiceError,
    AIConfigurationError,
    AIRequestError,
    AIResponseError,
)

logger = logging.getLogger('JJYB_AI智剪')


def _resolve_existing_video_path(value):
    """Resolve absolute, project-relative, and upload URL paths consistently."""
    raw = str(value or '').strip()
    if not raw:
        return None
    candidates = []
    path = Path(raw).expanduser()
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(PROJECT_ROOT / path)
    if raw.startswith('/'):
        candidates.append(PROJECT_ROOT / raw.lstrip('/'))
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate.absolute()
        if resolved.is_file():
            return str(resolved)
    return None


# ==========================================================================
# 模型厂商标识归一化（Brand-based Model Key Normalization）
# 后端永远只认 ai_config.py 可识别的服务名：
#   LLM    → custom_openai / openai / anthropic / gemini / qwen / ernie /
#            chatglm / deepseek / openrouter / siliconflow / doubao / spark / kimi / tencent
#   Vision → custom_vision / gpt4v / claude_vision / gemini_vision / qwen_vl /
#            baidu_vision / tencent_vision / spark_vision / chatglm / doubao_vision
# 旧 model_id（如 qwen-max、gpt-4o、kimi 等）和品牌名（alibaba/google/baidu 等）
# 均在入口统一映射为服务名，避免后端因模型迭代、编号过时或命名不一致导致路由失效。
# ==========================================================================
_TEXT_MODEL_BRAND_MAP = {
    # ---------- 自定义（核心：custom-llm → custom_openai） ----------
    'custom': 'custom_openai', 'custom-llm': 'custom_openai', 'custom_openai': 'custom_openai',
    'customllm': 'custom_openai',
    # ---------- OpenAI ----------
    'openai': 'openai', 'gpt': 'openai', 'gpt-4o': 'openai', 'gpt-4o-mini': 'openai',
    'gpt-4': 'openai', 'gpt-4-turbo': 'openai', 'gpt-3.5': 'openai', 'gpt-3.5-turbo': 'openai',
    'o1': 'openai', 'o3': 'openai',
    # ---------- Anthropic ----------
    'anthropic': 'anthropic', 'claude': 'anthropic', 'claude-3': 'anthropic',
    'claude-3.5': 'anthropic', 'claude-3.5-sonnet': 'anthropic', 'claude-3-opus': 'anthropic',
    'claude-3-haiku': 'anthropic', 'claude-3.7': 'anthropic',
    # ---------- Google (Gemini) ----------
    'google': 'gemini', 'gemini': 'gemini', 'gemini-1.5': 'gemini', 'gemini-1.5-pro': 'gemini',
    'gemini-2.0': 'gemini', 'gemini-2.5': 'gemini', 'google-gemini': 'gemini',
    # ---------- 百度 (文心/ERNIE) ----------
    'baidu': 'ernie', 'wenxin': 'ernie', 'ernie': 'ernie', 'ernie-4.0': 'ernie',
    'ernie-3.5': 'ernie', 'ernie-lite': 'ernie', 'ernie-speed': 'ernie',
    # ---------- 阿里 (通义/Qwen) ----------
    'alibaba': 'qwen', 'qwen': 'qwen', 'qwen-turbo': 'qwen', 'qwen-max': 'qwen',
    'qwen-plus': 'qwen', 'qwen-long': 'qwen', 'qwen2.5': 'qwen', 'tongyi': 'qwen',
    # ---------- 智谱 (ChatGLM) ----------
    'zhipu': 'chatglm', 'chatglm': 'chatglm', 'glm': 'chatglm', 'glm-4': 'chatglm',
    'glm-4v': 'chatglm', 'glm-4-plus': 'chatglm', 'glm-3': 'chatglm',
    # ---------- DeepSeek ----------
    'deepseek': 'deepseek', 'deepseek-v3': 'deepseek', 'deepseek-r1': 'deepseek',
    # ---------- MiniMax / Kimi ----------
    'minimax': 'kimi', 'kimi': 'kimi', 'moonshot': 'kimi',
    # ---------- 讯飞 (Spark) ----------
    'iflytek': 'spark', 'spark': 'spark', 'xinghuo': 'spark',
    # ---------- 字节 (豆包/Doubao) ----------
    'bytedance': 'doubao', 'volcano': 'doubao', 'huoshan': 'doubao', 'doubao': 'doubao',
    # ---------- 腾讯 (混元) ----------
    'tencent': 'tencent', 'hunyuan': 'tencent',
    # ---------- 聚合网关 ----------
    'openrouter': 'openrouter', 'open-router': 'openrouter',
    'siliconflow': 'siliconflow', 'silicon-flow': 'siliconflow',
}

_VISION_MODEL_BRAND_MAP = {
    # ---------- 自定义视觉 ----------
    'custom': 'custom_vision', 'custom-vision': 'custom_vision', 'custom_vision': 'custom_vision',
    'customvision': 'custom_vision',
    # ---------- OpenAI Vision (GPT-4V / GPT-4o) ----------
    'openai': 'gpt4v', 'gpt4v': 'gpt4v', 'gpt-4v': 'gpt4v', 'gpt-4-vision': 'gpt4v',
    'gpt-4o': 'gpt4v', 'gpt-4o-mini': 'gpt4v', 'o1': 'gpt4v',
    # ---------- Anthropic Vision ----------
    'anthropic': 'claude_vision', 'claude-vision': 'claude_vision', 'claude': 'claude_vision',
    'claude_vision': 'claude_vision',
    # ---------- Google Gemini Vision ----------
    'google': 'gemini_vision', 'gemini-vision': 'gemini_vision', 'gemini': 'gemini_vision',
    'gemini_vision': 'gemini_vision',
    # ---------- 百度视觉 ----------
    'baidu': 'baidu_vision', 'baidu-vision': 'baidu_vision', 'ernie-vision': 'baidu_vision',
    'baidu_vision': 'baidu_vision',
    # ---------- 阿里 (通义千问 VL) ----------
    'alibaba': 'qwen_vl', 'qwen-vl': 'qwen_vl', 'qwen-vl-max': 'qwen_vl', 'qwen': 'qwen_vl',
    'qwen-vl-plus': 'qwen_vl', 'qwen_vl': 'qwen_vl', 'tongyi-vl': 'qwen_vl',
    # ---------- 智谱 GLM 视觉 ----------
    'zhipu': 'chatglm', 'glm-4v': 'chatglm', 'chatglm-vision': 'chatglm',
    # ---------- 字节 豆包视觉 ----------
    'bytedance': 'doubao_vision', 'doubao-vision': 'doubao_vision', 'volcano-vision': 'doubao_vision',
    # ---------- 腾讯 混元视觉 ----------
    'tencent': 'tencent_vision', 'hunyuan-vision': 'tencent_vision',
    # ---------- MiniMax ----------
    'minimax': 'chatglm',
}


def _normalize_text_brand(raw):
    if raw is None:
        return None
    k = str(raw).strip().lower()
    if not k:
        return None
    if k in _TEXT_MODEL_BRAND_MAP:
        return _TEXT_MODEL_BRAND_MAP[k]
    # 前缀匹配（兜底 qwen-max-2025-xx、gpt-4o-2024-xx 等）
    for prefix in ('gpt-', 'claude', 'gemini', 'qwen', 'ernie', 'glm', 'deepseek',
                   'kimi', 'spark', 'doubao', 'hunyuan', 'wenxin', 'chatglm'):
        if k.startswith(prefix):
            # 用完整前缀 key（如 'qwen-turbo' → 'qwen' → 再取 'qwen'）
            if prefix in _TEXT_MODEL_BRAND_MAP:
                return _TEXT_MODEL_BRAND_MAP[prefix]
            # 取第一个能命中的
            for mapped_key, mapped_value in _TEXT_MODEL_BRAND_MAP.items():
                if mapped_key == prefix:
                    return mapped_value
    return raw


def _normalize_vision_brand(raw):
    if raw is None:
        return None
    k = str(raw).strip().lower()
    if not k:
        return None
    if k in _VISION_MODEL_BRAND_MAP:
        return _VISION_MODEL_BRAND_MAP[k]
    for prefix in ('gpt4v', 'gpt-4v', 'qwen-vl', 'glm-4v', 'claude', 'gemini', 'ernie-',
                   'doubao', 'hunyuan'):
        if k.startswith(prefix):
            if prefix in _VISION_MODEL_BRAND_MAP:
                return _VISION_MODEL_BRAND_MAP[prefix]
    return raw


def normalize_model_brand_keys(payload):
    """递归把 payload 里所有 model_key 归一化成厂商标识。"""
    if isinstance(payload, dict):
        # llm / llm_model
        for k in ('llm', 'llm_model'):
            if k in payload:
                normalized = _normalize_text_brand(payload[k])
                if normalized is not None:
                    payload[k] = normalized
        # vision / vision_model / visionModel
        for k in ('vision', 'vision_model', 'visionModel'):
            if k in payload:
                normalized = _normalize_vision_brand(payload[k])
                if normalized is not None:
                    payload[k] = normalized
        # 递归子对象
        for v in payload.values():
            normalize_model_brand_keys(v)
    elif isinstance(payload, list):
        for item in payload:
            normalize_model_brand_keys(item)
    return payload


def _safe_ai_error_response(exc: Exception, default_msg: str = 'AI 服务不可用'):
    """将 AIServiceError 转换为对用户安全的错误响应，不暴露内部路径或供应商报文。"""
    if isinstance(exc, AIConfigurationError):
        status, failure_scope = 422, 'ai_configuration'
        logger.error('AIConfigurationError: %s | code=%s', exc.user_message, exc.code)
    elif isinstance(exc, AIRequestError):
        status, failure_scope = 503, 'remote_vision'
        logger.error('AIRequestError: %s | code=%s | cause=%s', exc.user_message, exc.code, exc.__cause__ or '')
    elif isinstance(exc, AIResponseError):
        status, failure_scope = 502, 'remote_vision'
        logger.error('AIResponseError: %s | code=%s', exc.user_message, exc.code)
    elif isinstance(exc, AIServiceError):
        status, failure_scope = 500, 'ai_service'
        logger.error('AIServiceError: %s | code=%s', exc.user_message, exc.code)
    else:
        logger.exception(default_msg)
        return jsonify({'code': 1, 'msg': default_msg, 'data': None}), 500

    return jsonify({
        'code': 1,
        'msg': exc.user_message,
        'data': None,
        'error_code': exc.code,
        'failure_scope': failure_scope,
    }), status


def register_commentary_routes_enhanced(app, db_manager, task_service, socketio):
    """注册原创解说API路由（增强版）"""

    # 初始化增强服务
    from backend.services.commentary_service_enhanced import CommentaryServiceEnhanced
    commentary_service = CommentaryServiceEnhanced(db_manager, socketio, task_service)

    def resume_commentary(task_id, project_id, video_path, config):
        def _run_process():
            commentary_service.process_video(project_id, video_path, config, task_id=task_id)

        threading.Thread(target=_run_process, daemon=True).start()
        return True

    app.extensions['commentary_resume'] = resume_commentary

    logger.info('✅ 原创解说API路由（增强版）注册完成')

    @app.route('/api/commentary/create', methods=['POST'])
    def create_commentary_project():
        """创建原创解说项目"""
        try:
            data = request.get_json()
            normalize_model_brand_keys(data)
            result = commentary_service.create_project(data)
            return jsonify(result)
        except Exception as e:
            logger.error(f'❌ 创建项目失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/commentary/analyze', methods=['POST'])
    def analyze_video():
        """分析视频画面

        将前端 config 透传给 _analyze_video，确保严格模式、provider 选择
        能按请求生效；支持真实 project_id 而非固定 'temp'。
        """
        task_id = None

        def mark_task_failed(error: Exception):
            if not task_id:
                return
            try:
                db_manager.update_task_progress(task_id, 100)
                db_manager.update_task_status(task_id, 'failed', error_message=str(error))
            except Exception:
                logger.warning('视频分析任务状态更新失败: %s', task_id, exc_info=True)

        def mark_task_completed(output_data):
            db_manager.update_task_progress(task_id, 100)
            db_manager.update_task_status(task_id, 'completed', output_data=output_data)

        try:
            data = request.get_json() or {}
            normalize_model_brand_keys(data)
            video_path = str(data.get('video_path') or '').replace('\\', '/')
            config = data.get('config') or {}
            project_id = data.get('project_id') or 'temp'
            precomputed_shots = data.get('precomputed_shots') or data.get('shots')

            if not isinstance(precomputed_shots, list) or not precomputed_shots:
                return jsonify({'code': 1, 'msg': '缺少有效分镜，请先完成智能分镜后再分析', 'data': None}), 400
            validated_shots = []
            for index, shot in enumerate(precomputed_shots):
                if not isinstance(shot, dict):
                    return jsonify({'code': 1, 'msg': f'第 {index + 1} 个镜头格式无效', 'data': None}), 400
                try:
                    start_time = float(shot.get('start_time', shot.get('start')))
                    end_time = float(shot.get('end_time', shot.get('end')))
                    start_frame = int(shot.get('start_frame', 0))
                    end_frame = int(shot.get('end_frame', start_frame))
                except (TypeError, ValueError):
                    return jsonify({'code': 1, 'msg': f'第 {index + 1} 个镜头时间或帧范围无效', 'data': None}), 400
                if start_time < 0 or end_time <= start_time or start_frame < 0 or end_frame < start_frame:
                    return jsonify({'code': 1, 'msg': f'第 {index + 1} 个镜头范围不合法', 'data': None}), 400
                normalized = dict(shot)
                normalized.update(start_time=start_time, end_time=end_time,
                                  duration=end_time - start_time,
                                  start_frame=start_frame, end_frame=end_frame)
                validated_shots.append(normalized)
            config['precomputed_shots'] = validated_shots

            if not video_path:
                return jsonify({'code': 1, 'msg': '缺少视频文件路径', 'data': None}), 400
            # 支持相对路径：相对项目根目录（backend/..）
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            if os.path.isabs(video_path):
                video_path_abs = video_path
            else:
                video_path_abs = os.path.normpath(os.path.join(base_dir, video_path))
            resolved_video_path = _resolve_existing_video_path(video_path)
            if not resolved_video_path:
                return jsonify({'code': 1, 'msg': '视频文件不存在', 'data': None}), 400
            video_path_abs = resolved_video_path

            # 创建任务（使用真实 project_id 以便结果回写项目）
            task_id = str(uuid.uuid4())
            db_manager.create_task(
                task_id=task_id,
                task_type='video_analysis',
                project_id=project_id,
                input_data={
                    'description': '视频画面分析',
                    'video_path': video_path_abs,
                    'config': {key: value for key, value in config.items() if key != 'precomputed_shots'},
                    'shot_count': len(validated_shots),
                }
            )

            # 执行分析 - 透传 config 使严格模式和 provider 选择生效
            results = commentary_service._analyze_video(video_path_abs, task_id, config)

            if results:
                # 移除不可序列化字段（如关键帧中的图像ndarray）并做JSON安全化
                try:
                    if isinstance(results.get('keyframes'), list):
                        for kf in results['keyframes']:
                            if isinstance(kf, dict) and 'image' in kf:
                                kf['image'] = None
                except Exception:
                    pass
                try:
                    safe_data = json.loads(json.dumps(results, ensure_ascii=False, default=lambda o: None))
                except Exception:
                    # 兜底：直接不带关键帧图像字段
                    safe_data = {'scenes': results.get('scenes'), 'descriptions': results.get('descriptions'), 'summary': results.get('summary')}
                # 附加真实分析来源元数据
                if isinstance(safe_data, dict):
                    safe_data['task_id'] = task_id
                    safe_data.setdefault('analysis_metadata', {
                        'source': results.get('analysis_source') or 'vision_engine',
                        'strict_mode': bool(config.get('strict_ai_results', True)),
                    })
                mark_task_completed(safe_data)
                return jsonify({'code': 0, 'msg': '分析完成', 'data': safe_data})
            else:
                error = RuntimeError('分析失败')
                mark_task_failed(error)
                return jsonify({'code': 1, 'msg': '分析失败', 'data': None}), 500

        except (AIConfigurationError, AIRequestError, AIResponseError) as e:
            mark_task_failed(e)
            return _safe_ai_error_response(e, '视频分析失败')
        except Exception as e:
            logger.error(f'❌ 视频分析失败: {e}')
            mark_task_failed(e)
            return jsonify({'code': 1, 'msg': '视频分析失败，请稍后重试。', 'data': None}), 500

    @app.route('/api/commentary/generate-script', methods=['POST'])
    def generate_script():
        """生成解说文案"""
        try:
            data = request.get_json()
            normalize_model_brand_keys(data)
            vision_results = data.get('vision_results')
            config = data.get('config', {})
            # 将前端单独传入的 llm_model 合并进配置，便于后端根据该值切换当前使用的LLM
            try:
                llm_model = data.get('llm_model')
                if llm_model:
                    config['llm'] = llm_model
            except Exception:
                pass

            if not vision_results:
                return jsonify({'code': 1, 'msg': '缺少视频分析结果', 'data': None}), 400

            # 创建临时任务
            task_id = str(uuid.uuid4())
            db_manager.create_task(
                task_id=task_id,
                task_type='script_generation',
                project_id='temp',
                input_data={'description': '文案生成'}
            )
            task = {'id': task_id}

            # 生成文案
            script = commentary_service._generate_script(vision_results, config, task['id'])

            if script:
                return jsonify({'code': 0, 'msg': '生成完成', 'data': script})
            else:
                return jsonify({'code': 1, 'msg': '生成失败', 'data': None}), 500

        except (AIConfigurationError, AIRequestError, AIResponseError) as e:
            return _safe_ai_error_response(e, '文案生成失败')
        except Exception as e:
            logger.error(f'❌ 文案生成失败: {e}')
            return jsonify({'code': 1, 'msg': f'生成失败: {str(e)}', 'data': None}), 500

    @app.route('/api/commentary/process', methods=['POST'])
    def process_video():
        """完整处理流程"""
        try:
            data = request.get_json()
            normalize_model_brand_keys(data)
            project_id = data.get('project_id')
            video_path = data.get('video_path')
            config = data.get('config', {})

            if not project_id or not video_path:
                return jsonify({'code': 1, 'msg': '缺少必要参数', 'data': None}), 400

            video_path = _resolve_existing_video_path(video_path)
            if not video_path:
                return jsonify({'code': 1, 'msg': '视频文件不存在', 'data': None}), 400

            # 在后台执行完整处理，避免长视频的镜头分析阻塞 HTTP 响应，导致前端无法绑定任务进度。
            task_id = str(data.get('task_id') or uuid.uuid4())

            def _run_process():
                commentary_service.process_video(project_id, video_path, config, task_id=task_id)

            threading.Thread(target=_run_process, daemon=True).start()
            return jsonify({
                'code': 0,
                'msg': '处理任务已启动',
                'data': {'task_id': task_id, 'project_id': project_id}
            })

        except (AIConfigurationError, AIRequestError, AIResponseError) as e:
            return _safe_ai_error_response(e, '处理失败')
        except Exception as e:
            logger.error(f'❌ 处理失败: {e}')
            return jsonify({'code': 1, 'msg': f'处理失败: {str(e)}', 'data': None}), 500

    @app.route('/api/commentary/result/<project_id>', methods=['GET'])
    def get_result(project_id):
        """获取处理结果"""
        try:
            result = commentary_service.get_project_result(project_id)
            return jsonify(result)
        except Exception as e:
            logger.error(f'❌ 获取结果失败: {e}')
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/commentary/optimize-script', methods=['POST'])
    def optimize_script():
        """AI优化已有解说文稿

        请求体:
            - script_text: 原始文稿文本
            - config: 配置（style, emotion_tone, llm 等）
        """
        try:
            data = request.get_json() or {}
            normalize_model_brand_keys(data)
            script_text = data.get('script_text', '')
            config = data.get('config', {})

            try:
                llm_model = data.get('llm_model')
                if llm_model:
                    config['llm'] = llm_model
            except Exception:
                pass

            if not script_text or not str(script_text).strip():
                return jsonify({'code': 1, 'msg': '缺少文稿文本', 'data': None}), 400

            task_id = str(uuid.uuid4())
            db_manager.create_task(
                task_id=task_id,
                task_type='script_optimization',
                project_id='temp',
                input_data={'description': 'AI优化文稿'}
            )

            result = commentary_service._optimize_script(script_text, config, task_id)

            if result:
                return jsonify({'code': 0, 'msg': '优化完成', 'data': result})
            else:
                return jsonify({'code': 1, 'msg': '优化失败，请检查AI配置后重试', 'data': None}), 500

        except (AIConfigurationError, AIRequestError, AIResponseError) as e:
            return _safe_ai_error_response(e, '文稿优化失败')
        except Exception as e:
            logger.error(f'❌ 文稿优化失败: {e}')
            return jsonify({'code': 1, 'msg': f'优化失败: {str(e)}', 'data': None}), 500

    # =====================================================================
    # 🩺 文案质检（对接 advanced_routes 的 ScriptDoctor diagnose / optimize）
    # =====================================================================
    @app.route('/api/commentary/qc-check', methods=['POST'])
    def commentary_qc_check():
        """文案质检 · 6维评分诊断
        优先通过 advanced_bp 内部调用 script-doctor/diagnose，失败时返回规则兜底的空壳让前端继续走可视化。
        """
        try:
            data = request.get_json() or {}
            text = (data.get('text') or data.get('script') or '').strip()
            if not text or len(text) < 20:
                return jsonify({'code': 1, 'msg': '请粘贴不少于 20 字的待诊断文案', 'data': None}), 400

            # 1) 优先走 advanced_routes 的诊断逻辑（复用 ScriptDoctor + LLM）
            try:
                from backend.api.advanced_routes import advanced_bp
                # 临时伪造一个子请求复用 advanced_bp 里的诊断实现：通过调用内部脚本诊断函数
                try:
                    from backend.prompts.script_doctor import ScriptDoctor
                    # 统一 LLM 入口
                    try:
                        from backend.core.global_state import get_global_state
                        mgr = get_global_state().get_multi_model_manager()
                        prompt = ScriptDoctor.get_diagnosis_prompt(text, '')
                        resp_text = mgr.generate_text(prompt, temperature=0.3)
                    except Exception as e_inner:
                        logger.warning(f'质检LLM调用失败，使用纯规则兜底: {e_inner}')
                        resp_text = ''
                    # 解析响应
                    import re as _re
                    def _pjson(s):
                        if not s: return None
                        m = _re.search(r'\{[\s\S]*\}', s)
                        if not m: return None
                        try: return json.loads(m.group(0))
                        except Exception: return None
                    parsed = _pjson(resp_text) if resp_text else None
                    if parsed and 'dimensions' in parsed:
                        # 统一对外评分到 0-100；兼容模型返回的 0-10 或 0-100 分制。
                        dims = parsed['dimensions']
                        weights = ScriptDoctor.DIMENSIONS if hasattr(ScriptDoctor,'DIMENSIONS') else {}
                        normalized_dims = {}
                        total = 0; weight_total = 0
                        for k, v in dims.items():
                            item = v if isinstance(v, dict) else {'score': v}
                            try:
                                raw_score = float(item.get('score', 0))
                            except (TypeError, ValueError):
                                raw_score = 0
                            score = raw_score * 10 if raw_score <= 10 else raw_score
                            item['score'] = round(max(0, min(100, score)), 1)
                            normalized_dims[k] = item
                            weight = float((weights.get(k) or {}).get('weight') or 0.16)
                            total += item['score'] * weight; weight_total += weight
                        parsed['dimensions'] = normalized_dims
                        parsed['overall_score'] = round(total / max(weight_total, 0.001), 1)
                        parsed['score_scale'] = 100
                        # 补齐 stats / hard_metrics / advice（避免前端可视化空掉）
                        clean = text.replace('\u3000',' ').replace('\r','').replace('\n','')
                        zh = len(_re.findall(r'[\u4e00-\u9fa5]', clean))
                        sents = list(filter(None, _re.split(r'[。！？.!?\n]+', text)))
                        avg_len = round(sum(len(s.strip()) for s in sents)/max(len(sents),1)) if sents else 0
                        hook_words = ['注意','竟然','没想到','居然','震撼','震惊','真相','秘密','千万','一定','看完','绝了','离谱','反转','高能','这个男人','这个女人','注意看']
                        hook_cnt = sum(text.count(w) for w in hook_words)
                        hook_density = min(100, round(hook_cnt / max(len(sents),1) * 100))
                        parsed.setdefault('stats', {
                            'word_count': len(clean),
                            'duration': f'{max(1, round(len(clean)/4))}秒',
                            'avg_sentence_length': f'{avg_len}字',
                            'hook_density': f'{hook_density}%'
                        })
                        parsed.setdefault('hard_metrics', [
                            {'name':'字数达标','status':'ok' if len(clean)>=300 else 'warn','value':f'{len(clean)}字'},
                            {'name':'汉字占比','status':'ok' if zh/max(len(clean),1)>0.7 else 'warn','value':f'{round(zh/max(len(clean),1)*100)}%'},
                            {'name':'开头钩子','status':'ok' if any(text[:100].find(w)>=0 for w in hook_words) else 'bad','value':'存在' if any(text[:100].find(w)>=0 for w in hook_words) else '缺失'},
                            {'name':'平均句长','status':'ok' if 12<=avg_len<=35 else ('bad' if avg_len>45 else 'warn'), 'value':f'{avg_len}字'},
                            {'name':'段落结构','status':'ok' if len(text.split('\n\n'))>=3 else 'warn', 'value':f"{len(text.split('\n\n'))}段"}
                        ])
                        parsed.setdefault('advice', (
                            '前3秒一定要放悬念/冲突/反常识钩子；'
                            '句子长度压在 12-32 字；'
                            '情绪曲线要有高低起伏；'
                            '结尾用金句+互动引导（记得关注评论点赞）。'
                        ))
                        return jsonify({'code': 0, 'msg': '质检完成', 'data': parsed})
                except Exception as e2:
                    logger.warning(f'质检ScriptDoctor内部调用失败，返回空结构给前端走兜底: {e2}')
            except Exception as e_imp:
                logger.warning(f'advanced质检不可用，前端将本地规则兜底: {e_imp}')

            # 2) 兜底：返回空结构，前端自己做规则可视化
            return jsonify({'code': 0, 'msg': '质检完成（规则模式）', 'data': {
                'dimensions': {}, 'overall_score': None,
                'issues': [], 'suggestions': [],
                'hard_metrics': [], 'stats': None, 'advice': ''
            }})
        except Exception as e:
            logger.error(f'❌ 文案质检失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'质检失败: {str(e)}', 'data': None}), 500

    @app.route('/api/commentary/qc-rewrite', methods=['POST'])
    def commentary_qc_rewrite():
        """文案质检 · 三套改写方案（A拉长/B短节奏/C黄金爆款）
        优先走 LLM，失败时把 preset 拼在 header 里原样返回（前端会做本地规则改写兜底）。
        """
        try:
            data = request.get_json() or {}
            text = (data.get('text') or '').strip()
            preset = (data.get('preset') or 'c').lower()
            style_hint = (data.get('style_hint') or '')
            if not text:
                return jsonify({'code': 1, 'msg': '缺少待改写文案', 'data': None}), 400
            preset_meta = {
                'a': {'t':0.75, 'name':'拉长细节版', 'req':'补充背景、情感、感官和细节描写，字数+30%~50%，句子拉长到25-40字，沉浸感强，适合解说类长视频。'},
                'b': {'t':0.85, 'name':'极致短节奏版','req':'精简语言，删除所有废话铺垫，每句≤18字；每3秒一小钩10秒一大钩；短视频强引流风格。字数-30%。'},
                'c': {'t':0.80, 'name':'黄金爆款版',  'req':'平台算法偏好写法：3秒钩子前置→3个冲突反转叠情绪→金句收尾→评论区互动引导。综合完播&互动率最优。'}
            }
            m = preset_meta.get(preset, preset_meta['c'])
            try:
                from backend.core.global_state import get_global_state
                mgr = get_global_state().get_multi_model_manager()
                prompt = f"""你是资深影视解说文案改写师。请严格按以下要求改写解说文案：

【改写风格】{m['name']}
【风格要求】{m['req']}
【额外说明】{style_hint}

【输出规则】
- 直接输出改写后的纯文案，不要任何解释、标注、前后说明
- 不要使用 Markdown / 代码块 / 引号包裹
- 口语化、有感染力，符合影视解说语感

【原始文案】
{text}

改写后的纯文案："""
                out = (mgr.generate_text(prompt, temperature=m['t']) or '').strip()
                if out and len(out) >= 50:
                    # 去前后 ``` 等包裹
                    import re as _re
                    out = _re.sub(r'^```(?:\w+)?\s*', '', out)
                    out = _re.sub(r'\s*```$', '', out).strip()
                    return jsonify({'code': 0, 'msg': f'已生成 {m["name"]}', 'data': {'text': out, 'preset': preset, 'name': m['name']}})
            except Exception as e_llm:
                logger.warning(f'质检改写LLM调用失败，让前端本地兜底: {e_llm}')

            # LLM不可用：返回空 data，前端做本地规则兜底
            return jsonify({'code': 0, 'msg': f'{m["name"]} 生成任务已提交（本地兜底）', 'data': {'text': None, 'preset': preset, 'name': m['name']}})
        except Exception as e:
            logger.error(f'❌ 质检改写失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'改写失败: {str(e)}', 'data': None}), 500

    _VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.m4v'}
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]

    def _probe_video(path):
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-show_streams', '-of', 'json', str(path)], capture_output=True, text=True, timeout=30, check=False)
        if result.returncode != 0:
            raise RuntimeError('无法读取视频媒体信息，请确认文件未损坏且 FFmpeg 已安装')
        try:
            data = json.loads(result.stdout or '{}')
            duration = float((data.get('format') or {}).get('duration') or 0)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError('视频媒体信息无效') from exc
        if duration <= 0 or not any(item.get('codec_type') == 'video' for item in data.get('streams', [])):
            raise RuntimeError('文件不是包含有效画面的可处理视频')
        return duration

    def _set_task_status(task_id, status, progress=None, output_data=None, error_message=None):
        db_manager.update_task_status(task_id, status, output_data=output_data, error_message=error_message)
        if progress is not None:
            db_manager.update_task_progress(task_id, progress)

    def _run_ffmpeg(command, output_path):
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800, check=False)
        if result.returncode != 0:
            detail = (result.stderr or '').strip().splitlines()
            raise RuntimeError(f'FFmpeg 处理失败：{detail[-1] if detail else "未知错误"}')
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError('FFmpeg 未生成输出文件')
        _probe_video(output_path)

    @app.route('/api/commentary/output/<task_id>', methods=['GET'])
    def download_commentary_output(task_id):
        task = db_manager.get_task(task_id)
        if not task or task.get('status') != 'completed':
            return jsonify({'code': 1, 'msg': '任务尚未完成或不存在', 'data': None}), 404
        try:
            output_path = Path(json.loads(task.get('output_data') or '{}').get('output_path') or '').resolve()
            output_path.relative_to((_PROJECT_ROOT / 'output' / 'exports').resolve())
        except (ValueError, TypeError, json.JSONDecodeError):
            return jsonify({'code': 1, 'msg': '任务输出记录无效', 'data': None}), 404
        if not output_path.is_file():
            return jsonify({'code': 1, 'msg': '任务输出文件不存在', 'data': None}), 404
        return send_file(output_path, as_attachment=True, download_name=output_path.name)

    @app.route('/api/commentary/rewrite-upload', methods=['POST'])
    def commentary_rewrite_upload():
        """仅提供基础水平翻转，不声称 AI 换帧、去重或版权规避。"""
        try:
            file_storage = request.files.get('video')
            if not file_storage or not file_storage.filename:
                return jsonify({'code': 1, 'msg': '请先选择成品解说视频文件', 'data': None}), 400
            strength = (request.form.get('strength') or 'light').strip().lower()
            if strength != 'light':
                return jsonify({'code': 1, 'msg': '当前仅支持“基础水平翻转”画面处理；AI 换帧、调速和镜头重排未实现，不能提交。', 'data': None}), 422
            extension = Path(secure_filename(file_storage.filename)).suffix.lower()
            if extension not in _VIDEO_EXTENSIONS:
                return jsonify({'code': 1, 'msg': f'不支持的视频格式：{extension or "无扩展名"}', 'data': None}), 400
            output_dir = _PROJECT_ROOT / 'output' / 'exports' / 'rewrite'
            output_dir.mkdir(parents=True, exist_ok=True)
            task_id = str(uuid.uuid4())
            source_path = output_dir / f'source_{task_id}{extension}'
            file_storage.save(source_path)
            if not source_path.is_file() or source_path.stat().st_size == 0:
                raise RuntimeError('上传文件保存失败')
            _probe_video(source_path)
            db_manager.create_task(task_id=task_id, task_type='video_rewrite', project_id='rewrite_auto', input_data={'video_path': str(source_path), 'strength': strength, 'operation': '基础水平翻转'})

            def worker():
                try:
                    _set_task_status(task_id, 'running', progress=5)
                    output_path = output_dir / f'rewrite_{task_id}.mp4'
                    _run_ffmpeg(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source_path), '-vf', 'hflip', '-map', '0:v:0', '-map', '0:a?', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', str(output_path)], output_path)
                    _set_task_status(task_id, 'completed', progress=100, output_data={'output_path': str(output_path), 'output_url': f'/api/commentary/output/{task_id}', 'operation': '基础水平翻转'})
                except Exception as exc:
                    logger.error('[基础画面处理] 任务失败: %s', exc, exc_info=True)
                    _set_task_status(task_id, 'failed', progress=100, error_message=str(exc))

            threading.Thread(target=worker, daemon=True).start()
            return jsonify({'code': 0, 'msg': '任务已提交，正在验证并处理视频', 'data': {'task_id': task_id, 'status': 'pending'}})
        except FileNotFoundError:
            return jsonify({'code': 1, 'msg': '未检测到 FFmpeg/ffprobe，无法处理视频', 'data': None}), 503
        except Exception as exc:
            logger.error('基础画面处理提交失败: %s', exc, exc_info=True)
            return jsonify({'code': 1, 'msg': f'提交失败：{exc}', 'data': None}), 500

    @app.route('/api/commentary/remake', methods=['POST'])
    def commentary_remake():
        """上传解说成品和原片，生成真实的截取或对照视频，不伪称自动复刻。"""
        try:
            narration = request.files.get('narration')
            originals = [item for item in request.files.getlist('originals') if item and item.filename]
            mode = (request.form.get('mode') or 'left_right_compare').strip()
            if not narration or not narration.filename:
                return jsonify({'code': 1, 'msg': '请上传解说成品视频', 'data': None}), 400
            if not originals:
                return jsonify({'code': 1, 'msg': '请至少上传一个原片视频', 'data': None}), 400
            if mode not in {'original_only', 'left_right_compare', 'picture_in_picture'}:
                return jsonify({'code': 1, 'msg': '该模式未实现真实可用产物；仅支持原片截取、左右对照或画中画对照。', 'data': None}), 422
            task_id = str(uuid.uuid4())
            task_dir = _PROJECT_ROOT / 'output' / 'exports' / 'remake' / task_id
            task_dir.mkdir(parents=True, exist_ok=True)

            def save_video(file_storage, name):
                extension = Path(secure_filename(file_storage.filename)).suffix.lower()
                if extension not in _VIDEO_EXTENSIONS:
                    raise ValueError(f'不支持的视频格式：{extension or "无扩展名"}')
                path = task_dir / f'{name}{extension}'
                file_storage.save(path)
                if not path.is_file() or path.stat().st_size == 0:
                    raise RuntimeError('上传文件保存失败')
                return path

            narration_path = save_video(narration, 'narration')
            original_path = save_video(originals[0], 'original_0')
            narration_duration = _probe_video(narration_path)
            original_duration = _probe_video(original_path)
            db_manager.create_task(task_id=task_id, task_type='curated_remake', project_id='remake_auto', input_data={'narration_path': str(narration_path), 'original_paths': [str(original_path)], 'mode': mode, 'operation': '生成对照/截取视频，不执行内容匹配或自动复刻'})

            def worker():
                try:
                    _set_task_status(task_id, 'running', progress=5)
                    output_path = task_dir / f'remake_{mode}.mp4'
                    if mode == 'original_only':
                        operation = '按解说时长截取首个原片'
                        command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(original_path), '-t', f'{min(narration_duration, original_duration):.3f}', '-map', '0:v:0', '-map', '0:a?', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', str(output_path)]
                    elif mode == 'left_right_compare':
                        operation = '左侧解说成品、右侧首个原片的对照视频'
                        command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(narration_path), '-i', str(original_path), '-filter_complex', '[0:v]scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2[n];[1:v]scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2[o];[n][o]hstack=inputs=2[v]', '-map', '[v]', '-map', '0:a?', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', str(output_path)]
                    else:
                        operation = '解说成品画中画显示首个原片的对照视频'
                        command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(narration_path), '-i', str(original_path), '-filter_complex', '[1:v]scale=320:-2[overlay];[0:v][overlay]overlay=W-w-20:H-h-20[v]', '-map', '[v]', '-map', '0:a?', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', str(output_path)]
                    _run_ffmpeg(command, output_path)
                    _set_task_status(task_id, 'completed', progress=100, output_data={'output_path': str(output_path), 'output_url': f'/api/commentary/output/{task_id}', 'operation': operation})
                except Exception as exc:
                    logger.error('[精选复刻] 任务失败: %s', exc, exc_info=True)
                    _set_task_status(task_id, 'failed', progress=100, error_message=str(exc))

            threading.Thread(target=worker, daemon=True).start()
            return jsonify({'code': 0, 'msg': '任务已提交，正在验证文件并生成对照产物', 'data': {'task_id': task_id, 'status': 'pending'}})
        except ValueError as exc:
            return jsonify({'code': 1, 'msg': str(exc), 'data': None}), 400
        except FileNotFoundError:
            return jsonify({'code': 1, 'msg': '未检测到 FFmpeg/ffprobe，无法处理视频', 'data': None}), 503
        except Exception as exc:
            logger.error('精选复刻提交失败: %s', exc, exc_info=True)
            return jsonify({'code': 1, 'msg': f'提交失败：{exc}', 'data': None}), 500

    # =====================================================================
    # ✨ 文案优化工作台（对话式）
    # =====================================================================
    @app.route('/api/commentary/optimize-chat', methods=['POST'])
    def commentary_optimize_chat():
        """对话式文案优化：按 Skill 标签 + 预设等级 + 视角 + 语言 生成优化文案。
        优先走 LLM，失败时把用户输入拼在原文案后返回，让前端始终有内容。
        """
        try:
            data = request.get_json() or {}
            normalize_model_brand_keys(data)
            input_text = (data.get('input_text') or '').strip()
            skills = data.get('skills') or ['默认空白']
            preset = (data.get('preset') or '默认（新手推荐）').strip()
            pov = (data.get('pov') or '第三人称').strip()
            lang = (data.get('lang') or 'cn 中文').strip()
            llm_brand = (data.get('llm_brand') or '').strip()
            context_script = (data.get('context_script') or '').strip()
            if not input_text:
                return jsonify({'code': 1, 'msg': '请输入优化要求或提示词', 'data': None}), 400

            try:
                from backend.core.global_state import get_global_state
                mgr = get_global_state().get_multi_model_manager()
                skill_line = '、'.join([s for s in skills if isinstance(s,str) and s != '默认空白']) or '（默认：保持原解说风格，不强制特定写法）'
                prompt = f"""你是资深影视解说文案优化师。

【当前上下文（已有解说文案，可参考）】
{context_script[:8000] if context_script else '(暂无已有文案，请根据用户要求独立创作一段示例优化建议)'}

【用户本次的优化要求】
{input_text}

【已激活 Skill 标签】{skill_line}
【润色强度/预设】{preset}
【叙述视角】{pov}
【输出语言】{lang}

【输出规则】
- 直接输出优化后的解说文案（或修改建议+优化后的示例文案），不要解释和前后缀
- 口语化、有感染力，符合平台爆款解说语感
- 输出纯文本，不要 Markdown / 代码块"""
                out = (mgr.generate_text(prompt, temperature=0.75) or '').strip()
                if out and len(out) >= 20:
                    import re as _re
                    out = _re.sub(r'^```(?:\w+)?\s*', '', out)
                    out = _re.sub(r'\s*```$', '', out).strip()
                    return jsonify({'code': 0, 'msg': '优化完成', 'data': {'text': out, 'llm_brand': llm_brand}})
            except Exception as e_llm:
                logger.warning(f'优化工作台LLM失败，走本地拼接兜底: {e_llm}')

            # LLM 不可用时只返回模式和建议，不伪造“优化后的文案”。
            return jsonify({'code': 0, 'msg': 'AI 未连通，已切换本地建议模式', 'data': {
                'text': None,
                'mode': 'local_suggestions',
                'llm_brand': llm_brand,
                'suggestions': [
                    '前3秒放入悬念、冲突或反常识钩子，避免铺垫。',
                    '每句控制在 12-32 字，以短句控节奏、长句提供信息。',
                    '按“平静→冲突→反转→金句收尾”组织情绪曲线。',
                    '补充镜头、特写、远景等画面指示，增强音画对应。',
                    '结尾加入明确的互动引导。'
                ]
            }})
        except Exception as e:
            logger.error(f'❌ 文案优化对话失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'优化失败: {str(e)}', 'data': None}), 500

    return commentary_service
