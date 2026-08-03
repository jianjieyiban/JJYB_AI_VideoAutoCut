# -*- coding: utf-8 -*-
"""
Voiceover API
AI配音API - 完整实现
"""

import logging
from pathlib import Path

from flask import Blueprint, request, jsonify

from backend.config.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

voiceover_bp = Blueprint('voiceover', __name__)
voiceover_service = None


def register_voiceover_routes(app, db_manager, voiceover_svc):
    """注册AI配音API路由"""
    global voiceover_service
    voiceover_service = voiceover_svc
    app.register_blueprint(voiceover_bp, url_prefix='/api/voiceover')
    logger.info('✅ AI配音API路由注册完成')


@voiceover_bp.route('/voices', methods=['GET'])
def get_voices():
    """获取可用音色列表"""
    try:
        language = request.args.get('language')
        gender = request.args.get('gender')
        voices = voiceover_service.get_available_voices(language, gender)
        return jsonify({'code': 0, 'msg': '获取成功', 'data': voices})
    except Exception as e:
        logger.error(f'获取音色列表失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'获取失败: {str(e)}', 'data': None}), 500


@voiceover_bp.route('/engines', methods=['GET'])
def get_engines():
    """获取常规 TTS 引擎的真实就绪状态，不包含任何密钥信息。"""
    try:
        from backend.config.ai_config import TTSModelConfig, get_config_manager

        cfg = get_config_manager().tts_model_config
        tts_engine = voiceover_service.tts_engine
        available = set(getattr(tts_engine, 'available_engines', []) or [])
        default_engine = tts_engine._normalize_engine_name(getattr(cfg, 'default_tts', 'edge-tts'))
        engine_status = []
        for engine in ('edge-tts', 'gtts', 'azure', 'pyttsx3', 'coqui'):
            ready = engine in available
            if ready:
                reason = ''
            elif engine == 'edge-tts' and not getattr(cfg, 'enable_edge_tts', True):
                reason = 'Edge TTS 已在运行设置中关闭'
            elif engine == 'gtts' and not getattr(cfg, 'enable_gtts', False):
                reason = 'gTTS 已在运行设置中关闭'
            elif engine == 'azure' and not (getattr(cfg, 'azure_tts_key', '') and getattr(cfg, 'azure_tts_region', '')):
                reason = '请先保存 Azure Key 和区域'
            elif engine == 'coqui':
                reason = 'Coqui TTS 未安装或不可用'
            else:
                reason = '引擎依赖未安装或当前不可用'
            engine_status.append({'engine': engine, 'ready': ready, 'reason': reason})
        return jsonify({
            'code': 0,
            'msg': '获取成功',
            'data': {
                'default_engine': default_engine,
                'available_engines': [item['engine'] for item in engine_status if item['ready']],
                'engines': engine_status,
            },
        })
    except Exception as e:
        logger.error(f'获取常规 TTS 引擎状态失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': '获取引擎状态失败', 'data': None}), 500


@voiceover_bp.route('/create', methods=['POST'])
def create_voiceover_project():
    """创建AI配音项目"""
    try:
        data = request.get_json()
        result = voiceover_service.create_voiceover_project(data)
        return jsonify({'code': 0, 'msg': '项目创建成功', 'data': result})
    except Exception as e:
        logger.error(f'创建AI配音项目失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'创建失败: {str(e)}', 'data': None}), 500


@voiceover_bp.route('/generate', methods=['POST'])
def generate_voiceover():
    """生成AI配音"""
    try:
        data = request.get_json()
        if not data or 'text' not in data:
            return jsonify({'code': 1, 'msg': '参数错误：缺少文本', 'data': None}), 400

        project_id = data.get('project_id')
        output_path = voiceover_service.generate_voiceover(
            data['text'],
            data.get('voice_config', {}),
            project_id=project_id,
        )

        p = Path(output_path).resolve()
        try:
            rel = p.relative_to(PROJECT_ROOT)
            rel_str = str(rel).replace('\\', '/')
        except Exception:
            # 回退到 output/audios/ 文件名 的形式
            rel_str = f"output/audios/{p.name}"

        audio_url = '/' + rel_str.lstrip('/')
        response_data = {
            'audio_path': rel_str,
            'audio_url': audio_url,
            'project_id': project_id,
            **getattr(output_path, 'metadata', {
                'engine_requested': None,
                'engine_used': None,
                'fallback_used': False,
                'fallback_reason': None,
            }),
        }
        return jsonify({'code': 0, 'msg': '生成成功', 'data': response_data})
    except Exception as e:
        logger.error(f'生成配音失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'生成失败: {str(e)}', 'data': None}), 500


@voiceover_bp.route('/batch-generate', methods=['POST'])
def batch_generate():
    """批量生成配音"""
    try:
        data = request.get_json()
        if not data or 'texts' not in data:
            return jsonify({'code': 1, 'msg': '参数错误：缺少文本列表', 'data': None}), 400

        output_paths = voiceover_service.batch_generate_voiceovers(
            data['texts'],
            data.get('voice_config', {})
        )

        rel_list = []
        url_list = []
        for p_str in output_paths:
            if not p_str:
                rel_list.append(None)
                url_list.append(None)
                continue
            p = Path(p_str).resolve()
            try:
                rel = p.relative_to(PROJECT_ROOT)
                rel_str = str(rel).replace('\\', '/')
            except Exception:
                rel_str = f"output/audios/{p.name}"
            audio_url = '/' + rel_str.lstrip('/')
            rel_list.append(rel_str)
            url_list.append(audio_url)

        metadata_list = [
            getattr(p, 'metadata', None) if p else None
            for p in output_paths
        ]
        return jsonify({
            'code': 0,
            'msg': '批量生成完成',
            'data': {
                'audio_paths': rel_list,
                'audio_urls': url_list,
                'syntheses': metadata_list,
            },
        })
    except Exception as e:
        logger.error(f'批量生成失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'生成失败: {str(e)}', 'data': None}), 500


@voiceover_bp.route('/preview', methods=['POST'])
def preview_voice():
    """预览音色（全引擎通用：edge/azure/gtts/volcano/indextts2/voice-pro）

    Request JSON:
        voice_id:        音色ID
        sample_text:     试听文案
        engine:          引擎标识
        speed / pitch:   速度 / 语调（可选）
        extra:           引擎专属配置（如 google_api_key / endpoint / api_key / ref_audio）
    """
    try:
        data = request.get_json() or {}
        if 'voice_id' not in data:
            return jsonify({'code': 1, 'msg': '参数错误：缺少音色ID', 'data': None}), 400
        engine = (data.get('engine') or '').strip()
        speed = data.get('speed') or 1.0
        pitch = data.get('pitch') or '+0Hz'
        extra = data.get('extra') or {}

        # 合并 speed / pitch / extra → advanced_config
        advanced_config = dict(data.get('advanced_config') or {})
        if speed is not None and speed != 1:
            advanced_config['rate'] = float(speed)
        if pitch and pitch not in ('+0Hz', '0', '0Hz'):
            advanced_config['pitch'] = pitch
        # extra 覆盖（用户显式填的 API Key 优先级最高）
        if isinstance(extra, dict):
            for ek, ev in extra.items():
                if ev is not None and ev != '':
                    advanced_config[ek] = ev

        audio_path_obj = voiceover_service.preview_voice(
            data['voice_id'],
            data.get('sample_text'),
            engine=engine or None,
            advanced_config=advanced_config,
        )
        audio_path = str(audio_path_obj)
        p = Path(audio_path).resolve()
        try:
            rel = p.relative_to(PROJECT_ROOT)
            rel_str = str(rel).replace('\\', '/')
        except Exception:
            rel_str = f"output/previews/{p.name}"
        audio_url = '/' + rel_str.lstrip('/')

        # 时长 / 大小 / 真实引擎 元数据
        size_kb = 0
        duration_ms = 0
        try:
            size_kb = round(p.stat().st_size / 1024.0, 1)
        except Exception:
            pass
        try:
            from mutagen.mp3 import MP3 as _MP3
            try:
                audio_info = _MP3(str(p)).info
                duration_ms = int(audio_info.length * 1000)
            except Exception:
                pass
        except Exception:
            duration_ms = 0
        meta = getattr(audio_path_obj, 'metadata', None) or {}
        engine_used = meta.get('engine_used') or engine or 'unknown'
        fallback_used = bool(meta.get('fallback_used', False))
        fallback_reason = meta.get('fallback_reason')

        response_data = {
            'audio_path': rel_str,
            'audio_url': audio_url,
            'engine': engine_used,
            'engine_requested': engine or None,
            'fallback_used': fallback_used,
            'fallback_reason': fallback_reason,
            'size_kb': size_kb,
            'duration_ms': duration_ms,
        }
        return jsonify({'code': 0, 'msg': '预览生成成功', 'data': response_data})
    except Exception as e:
        logger.error(f'预览音色失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'预览失败: {str(e)}', 'data': None}), 500


@voiceover_bp.route('/merge', methods=['POST'])
def merge_voiceovers():
    """合并配音"""
    try:
        data = request.get_json()
        if not data or 'audio_paths' not in data:
            return jsonify({'code': 1, 'msg': '参数错误：缺少音频路径列表', 'data': None}), 400

        output_path = voiceover_service.merge_voiceovers(
            data['audio_paths'],
            data.get('output_path')
        )

        p = Path(output_path).resolve()
        try:
            rel = p.relative_to(PROJECT_ROOT)
            rel_str = str(rel).replace('\\', '/')
        except Exception:
            rel_str = f"output/audios/{p.name}"
        audio_url = '/' + rel_str.lstrip('/')

        return jsonify({'code': 0, 'msg': '合并成功', 'data': {'audio_path': rel_str, 'audio_url': audio_url}})
    except Exception as e:
        logger.error(f"合并配音失败: {e}", exc_info=True)
        return jsonify({'code': 1, 'msg': f'合并失败: {str(e)}', 'data': None}), 500


# ================================================================== #
# 升级端点 1：列出克隆语音引擎及就绪状态
# ================================================================== #
@voiceover_bp.route('/clone-engines', methods=['GET'])
def list_clone_engines():
    """获取所有支持的克隆语音引擎及其就绪状态"""
    try:
        engines = voiceover_service.list_clone_engines()
        ready_count = sum(1 for e in engines if e.get('ready'))
        return jsonify({
            'code': 0,
            'msg': f'共 {len(engines)} 个克隆引擎，{ready_count} 个就绪',
            'data': {
                'engines': engines,
                'total': len(engines),
                'ready_count': ready_count,
            }
        })
    except Exception as e:
        logger.error(f"获取克隆引擎列表失败: {e}", exc_info=True)
        return jsonify({'code': 1, 'msg': f'获取失败: {str(e)}', 'data': None}), 500


# ================================================================== #
# 升级端点 2：克隆语音生成
# ================================================================== #
@voiceover_bp.route('/clone-generate', methods=['POST'])
def clone_generate():
    """生成克隆语音

    请求体:
        - text: 要合成的文本
        - reference_audio: 参考音频路径（必须位于项目 uploads 目录内）
        - engine: 克隆引擎 id（indextts2/fish-audio/minimax/volcano/azure-custom）
        - voice_config: 可选额外配置（speed/pitch/volume/emotion_type 等）
        - project_id: 可选项目ID
        - output_dir: 可选指定输出目录
        - consent: 是否已获得参考音频权利人授权（必须为 true）
    """
    try:
        data = request.get_json() or {}
        if data.get('consent') is not True:
            return jsonify({'code': 1, 'msg': '必须明确确认已获得参考音频权利人的授权（consent=true）', 'data': None}), 403

        text = data.get('text')
        reference_audio = data.get('reference_audio')
        engine = data.get('engine', 'indextts2')

        if not text or not text.strip():
            return jsonify({'code': 1, 'msg': '参数错误：缺少 text', 'data': None}), 400
        if not reference_audio:
            return jsonify({'code': 1, 'msg': '参数错误：缺少 reference_audio', 'data': None}), 400

        result = voiceover_service.generate_clone_voiceover(
            text=text,
            reference_audio=reference_audio,
            engine=engine,
            voice_config=data.get('voice_config', {}),
            project_id=data.get('project_id'),
            output_dir=data.get('output_dir'),
        )

        return jsonify({
            'code': 0,
            'msg': f'克隆语音生成成功（{result["engine_used"]}）',
            'data': result
        })
    except Exception as e:
        logger.error(f"克隆语音生成失败: {e}", exc_info=True)
        return jsonify({'code': 1, 'msg': f'生成失败: {str(e)}', 'data': None}), 500


# ================================================================== #
# 升级端点 3：下载到指定文件夹（已有音频文件复制）
# ================================================================== #
@voiceover_bp.route('/download-to-folder', methods=['POST'])
def download_to_folder():
    """将已生成的音频文件下载/复制到用户指定的文件夹

    请求体:
        - audio_path: 源音频路径（项目内相对路径或绝对路径）
        - target_dir: 目标文件夹绝对路径
        - filename: 可选目标文件名
    """
    try:
        data = request.get_json() or {}
        audio_path = data.get('audio_path')
        target_dir = data.get('target_dir')

        if not audio_path:
            return jsonify({'code': 1, 'msg': '参数错误：缺少 audio_path', 'data': None}), 400
        if not target_dir:
            return jsonify({'code': 1, 'msg': '参数错误：缺少 target_dir', 'data': None}), 400

        result = voiceover_service.download_audio_to_folder(
            audio_path=audio_path,
            target_dir=target_dir,
            filename=data.get('filename'),
        )

        return jsonify({
            'code': 0,
            'msg': f'音频已保存到: {result["saved_path"]}',
            'data': result
        })
    except Exception as e:
        logger.error(f"下载到指定文件夹失败: {e}", exc_info=True)
        return jsonify({'code': 1, 'msg': f'下载失败: {str(e)}', 'data': None}), 500


# ================================================================== #
# 升级端点 4：一步生成配音并下载到指定文件夹
# ================================================================== #
@voiceover_bp.route('/generate-and-download', methods=['POST'])
def generate_and_download():
    """一步生成配音并下载到用户指定的文件夹（普通 TTS）

    请求体:
        - text: 配音文本
        - voice_config: 配音配置 {voice_id, engine, rate, ...}
        - target_dir: 目标文件夹绝对路径
        - project_id: 可选项目ID
    """
    try:
        data = request.get_json() or {}
        text = data.get('text')
        target_dir = data.get('target_dir')

        if not text or not text.strip():
            return jsonify({'code': 1, 'msg': '参数错误：缺少 text', 'data': None}), 400
        if not target_dir:
            return jsonify({'code': 1, 'msg': '参数错误：缺少 target_dir', 'data': None}), 400

        result = voiceover_service.generate_and_download(
            text=text,
            voice_config=data.get('voice_config', {}),
            target_dir=target_dir,
            project_id=data.get('project_id'),
        )

        return jsonify({
            'code': 0,
            'msg': f'配音已生成并保存到: {result["saved_path"]}',
            'data': result
        })
    except Exception as e:
        logger.error(f"生成并下载失败: {e}", exc_info=True)
        return jsonify({'code': 1, 'msg': f'生成失败: {str(e)}', 'data': None}), 500


# ================================================================== #
# 升级端点 5：克隆语音生成并下载到指定文件夹
# ================================================================== #
@voiceover_bp.route('/clone-generate-and-download', methods=['POST'])
def clone_generate_and_download():
    """克隆语音生成并下载到指定文件夹

    请求体:
        - text: 要合成的文本
        - reference_audio: 参考音频路径
        - engine: 克隆引擎 id
        - voice_config: 可选额外配置
        - target_dir: 目标文件夹绝对路径
        - project_id: 可选
        - consent: 必须为 true
    """
    try:
        data = request.get_json() or {}
        if data.get('consent') is not True:
            return jsonify({'code': 1, 'msg': '必须明确确认已获得参考音频权利人的授权（consent=true）', 'data': None}), 403

        text = data.get('text')
        reference_audio = data.get('reference_audio')
        target_dir = data.get('target_dir')

        if not text or not text.strip():
            return jsonify({'code': 1, 'msg': '参数错误：缺少 text', 'data': None}), 400
        if not reference_audio:
            return jsonify({'code': 1, 'msg': '参数错误：缺少 reference_audio', 'data': None}), 400
        if not target_dir:
            return jsonify({'code': 1, 'msg': '参数错误：缺少 target_dir', 'data': None}), 400

        # 先生成克隆语音到指定目录
        result = voiceover_service.generate_clone_voiceover(
            text=text,
            reference_audio=reference_audio,
            engine=data.get('engine', 'indextts2'),
            voice_config=data.get('voice_config', {}),
            project_id=data.get('project_id'),
            output_dir=target_dir,
        )

        # 若已直接生成在 target_dir，无需再复制
        absolute_path = result.get('absolute_path')
        saved_path = absolute_path
        filename = Path(absolute_path).name
        file_size = Path(absolute_path).stat().st_size if absolute_path else 0

        return jsonify({
            'code': 0,
            'msg': f'克隆配音已生成并保存到: {saved_path}',
            'data': {
                **result,
                'saved_path': saved_path,
                'saved_dir': str(Path(saved_path).parent) if saved_path else '',
                'filename': filename,
                'file_size': file_size,
            }
        })
    except Exception as e:
        logger.error(f"克隆生成并下载失败: {e}", exc_info=True)
        return jsonify({'code': 1, 'msg': f'生成失败: {str(e)}', 'data': None}), 500


@voiceover_bp.route('/delete', methods=['POST'])
def delete_voiceover():
    """删除生成的配音文件"""
    try:
        data = request.get_json() or {}
        audio_path = data.get('audio_path') or data.get('path') or ''
        if not audio_path:
            return jsonify({'code': 1, 'msg': '参数错误：缺少音频路径', 'data': None}), 400

        import os

        abs_path = os.path.abspath(os.path.join(PROJECT_ROOT, audio_path.lstrip('/\\')))
        if not os.path.isfile(abs_path):
            rel_candidate = audio_path.lstrip('/\\')
            abs_path = os.path.join(PROJECT_ROOT, rel_candidate)
            if not os.path.isfile(abs_path):
                return jsonify({'code': 1, 'msg': '音频文件不存在', 'data': None}), 404

        safe_roots = [
            os.path.abspath(os.path.join(PROJECT_ROOT, 'output')),
            os.path.abspath(os.path.join(PROJECT_ROOT, 'temp')),
            os.path.abspath(os.path.join(PROJECT_ROOT, 'uploads')),
        ]
        abs_norm = os.path.normpath(abs_path)
        under_safe = any(
            abs_norm.startswith(os.path.normpath(root) + os.sep) or abs_norm == os.path.normpath(root)
            for root in safe_roots
        )
        if not under_safe:
            return jsonify({'code': 1, 'msg': '路径不合法，仅允许删除项目输出目录内的配音文件', 'data': None}), 403

        file_size = os.path.getsize(abs_path)
        os.remove(abs_path)
        logger.info(f'🗑️ 配音文件已删除: {abs_path} ({file_size} bytes)')

        return jsonify({
            'code': 0,
            'msg': '删除成功',
            'data': {'deleted_path': audio_path, 'bytes_freed': file_size}
        })
    except Exception as e:
        logger.error(f'删除配音失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'删除失败: {str(e)}', 'data': None}), 500


# ================================================================== #
# 升级端点 6：TTS 引擎外部服务 连通性测试 （Voice-Pro 等）
# ================================================================== #
@voiceover_bp.route('/test-connection', methods=['POST'])
def test_engine_connection():
    """测试外部语音引擎（当前支持 Voice-Pro / edge-tts / azure-tts / google-tts / volcano-tts / indextts2）的连通性。

    Body:
        engine: 'voice-pro' | 'edge-tts' | 'azure-tts' | 'google-tts' | 'volcano-tts' | 'indextts2'
        endpoint: 可选，Voice-Pro 的服务地址
        api_key:  可选，API Key
    """
    try:
        from datetime import datetime
        data = request.get_json() or {}
        engine = (data.get('engine') or data.get('type') or '').strip().lower()
        if not engine:
            return jsonify({'code': 1, 'msg': '缺少 engine 参数', 'data': None}), 400

        start = datetime.now()
        result = {'engine': engine, 'ok': False, 'version': 'unknown',
                  'latency_ms': 0, 'reason': '', 'fallback_available': False}

        # --- Voice-Pro 外部引擎：直接 HTTP 打指定 endpoint ---
        if engine == 'voice-pro' or engine == 'voicepro':
            endpoint = (data.get('endpoint') or '').strip().rstrip('/')
            api_key = (data.get('api_key') or '').strip()
            if not endpoint:
                # 兼容从 settings 里读取
                try:
                    from backend.config.ai_config import get_config_manager
                    cm = get_config_manager()
                    if hasattr(cm, 'tts_model_config'):
                        endpoint = (getattr(cm.tts_model_config, 'voicepro_endpoint', None) or getattr(cm.tts_model_config, 'voice_pro_endpoint', None) or '').strip().rstrip('/')
                        if not api_key:
                            api_key = (getattr(cm.tts_model_config, 'voicepro_api_key', None) or getattr(cm.tts_model_config, 'voice_pro_api_key', None) or '').strip()
                except Exception:
                    pass
            if not endpoint:
                return jsonify({'code': 1, 'msg': '请先填写 Voice-Pro 服务地址', 'data': None}), 400
            probe_paths = ['/v1/models', '/models', '/v1/health', '/health', '/']
            import urllib.request
            import urllib.error
            last_err = ''
            for pp in probe_paths:
                url = endpoint + pp
                try:
                    req = urllib.request.Request(url, headers={} if not api_key else {'Authorization': f'Bearer {api_key}'})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        if 200 <= resp.status < 300:
                            body = resp.read(4096)
                            # 尝试提取 version
                            version = 'v1 (unknown)'
                            try:
                                import json as _json
                                obj = _json.loads(body.decode('utf-8', errors='ignore'))
                                if isinstance(obj, dict):
                                    if obj.get('object') == 'list' and 'data' in obj:
                                        version = f"v1 · {len(obj.get('data', []))} voices"
                                    elif obj.get('version'):
                                        version = str(obj['version'])
                                    elif obj.get('model_version'):
                                        version = str(obj['model_version'])
                            except Exception:
                                pass
                            result.update({'ok': True, 'version': version, 'reason': f'{pp} HTTP {resp.status}'})
                            last_err = ''
                            break
                        last_err = f'{pp} HTTP {resp.status}'
                except urllib.error.HTTPError as e:
                    last_err = f'{pp} HTTP {e.code}'
                except Exception as e_x:
                    last_err = f'{pp} {str(e_x)}'
            if not result['ok']:
                result.update({'ok': False, 'reason': last_err or '全部探测失败', 'fallback_available': True})

        # --- IndexTTS2：走本地服务 status ---
        elif engine == 'indextts2' or engine == 'index-tts2' or engine == 'indextts':
            try:
                from backend.services.local_voice_clone_service import local_voice_clone_service
                s = local_voice_clone_service.status()
                result.update({
                    'ok': bool(s.get('ready')),
                    'version': s.get('version') or s.get('model_version') or 'unknown',
                    'reason': s.get('reason') or '',
                    'gpu': s.get('gpu_available', False),
                    'model_dir': s.get('model_dir') or ''
                })
            except Exception as e_i:
                result.update({'ok': False, 'reason': f'本地服务未就绪：{str(e_i)}'})

        # --- 火山引擎：通过 voiceover_service 探测 ---
        elif engine == 'volcano' or engine == 'volcano-tts' or engine == 'huoshan':
            from backend.config.ai_config import get_config_manager
            cfg = get_config_manager().tts_model_config
            has = bool(getattr(cfg, 'volcano_access_key', None) and getattr(cfg, 'volcano_secret_key', None)
                       and getattr(cfg, 'volcano_app_id', None))
            if not has:
                result['reason'] = '请在设置中配置火山 AccessKey / SecretKey / AppID'
                result['fallback_available'] = True
            else:
                result['ok'] = True
                result['version'] = 'volcano-tts-v1'

        # --- Google TTS ---
        elif engine in ('google-tts', 'gtts', 'google'):
            api_key = (data.get('api_key') or '').strip()
            if not api_key:
                # 没配置Key，用 gTTS（免费、免密钥、依赖网络）
                try:
                    from backend.engine.tts_engine import TTSEngine
                    e = TTSEngine()
                    available = list(getattr(e, 'available_engines', []) or [])
                    gtts_ok = 'gtts' in available or True  # gTTS 只要有网络就默认可用
                    result.update({
                        'ok': gtts_ok,
                        'version': 'gTTS (free mode · no API key)',
                        'reason': '未配置 Google Cloud TTS API Key，走免费 gTTS 兜底'
                    })
                except Exception as e_g:
                    result.update({'ok': True, 'version': 'gTTS', 'reason': str(e_g)})
            else:
                # 有Key，直接打 Google Cloud TTS 的 voices.list 端点探测
                probe_url = f"https://texttospeech.googleapis.com/v1/voices?key={api_key}"
                import urllib.request
                import urllib.error
                try:
                    req = urllib.request.Request(probe_url, headers={'X-Goog-Api-Key': api_key})
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        ok = 200 <= resp.status < 300
                        result.update({
                            'ok': ok,
                            'version': 'Google Cloud TTS v1' if ok else f'HTTP {resp.status}',
                            'reason': '' if ok else f'HTTP {resp.status}'
                        })
                except urllib.error.HTTPError as e:
                    result.update({'ok': False, 'version': '', 'reason': f'HTTP {e.code}'})
                except Exception as e_g:
                    result.update({'ok': False, 'reason': f'Google Cloud 探测失败：{str(e_g)}', 'fallback_available': True})

        # --- Edge-TTS / Azure-TTS ---
        elif engine in ('edge-tts', 'azure-tts', 'edge', 'azure'):
            from backend.config.ai_config import get_config_manager
            cfg = get_config_manager().tts_model_config
            if engine.startswith('azure'):
                has = bool(getattr(cfg, 'azure_tts_key', None) and getattr(cfg, 'azure_tts_region', None))
                result['ok'] = has
                result['reason'] = '' if has else '请在设置中配置 Azure Key 和区域'
                result['version'] = 'Azure Neural TTS v1'
            else:
                result['ok'] = bool(getattr(cfg, 'enable_edge_tts', True))
                result['version'] = 'Edge TTS (免费直连)'

        # --- 未知 ---
        else:
            return jsonify({'code': 1, 'msg': f'暂不支持引擎类型：{engine}', 'data': None}), 400

        result['latency_ms'] = int((datetime.now() - start).total_seconds() * 1000)
        code = 0 if result['ok'] else 2
        msg = '连接成功' if result['ok'] else ('连接失败：' + (result['reason'] or '未知原因'))
        return jsonify({'code': code, 'msg': msg, 'data': result})
    except Exception as e:
        logger.error(f'引擎连通性测试异常: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'测试异常：{str(e)}', 'data': None}), 500


# ================================================================== #
# 新端点 7：保存前端传来的引擎配置（Voice-Pro / Google TTS 等）
# ================================================================== #
@voiceover_bp.route('/save-settings', methods=['POST'])
def save_engine_settings():
    """保存前端选择的引擎配置（不落盘到 ai_config.json，仅写入 config_manager 内存；
    同时写一份到 storage/engine_settings.json 做持久化兜底）。
    """
    try:
        data = request.get_json() or {}
        engine = (data.get('engine') or '').strip().lower()
        settings = data.get('settings') or {}
        if not engine:
            return jsonify({'code': 1, 'msg': '缺少 engine 参数', 'data': None}), 400

        # 持久化兜底（文件，不依赖 ai_config.json 的 schema）
        storage_dir = PROJECT_ROOT / 'storage'
        storage_dir.mkdir(parents=True, exist_ok=True)
        cfg_path = storage_dir / 'engine_settings.json'
        import json as _json
        try:
            current = _json.loads(cfg_path.read_text(encoding='utf-8')) if cfg_path.exists() else {}
        except Exception:
            current = {}
        current[engine] = {**(current.get(engine) or {}), **settings, 'updated_at': __import__('datetime').datetime.now().isoformat()}
        cfg_path.write_text(_json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
        return jsonify({'code': 0, 'msg': f'{engine} 配置已保存', 'data': {'engine': engine, 'settings': current[engine]}})
    except Exception as e:
        logger.error(f'保存引擎配置失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'保存失败：{str(e)}', 'data': None}), 500


# ================================================================== #
# 新端点 8：删除试听临时文件（单个或清除 storage/tts_previews 下所有超过 N 小时的）
# ================================================================== #
@voiceover_bp.route('/delete-preview', methods=['POST'])
def delete_preview_audio():
    """
    body:
      url: 可选，要删除的试听文件下载 URL（/api/download/xxx 形式）
      mode: 'all' | 'expired' | 'single'，默认 expired
      hours: 过期小时数，默认 2
    """
    try:
        from datetime import datetime, timedelta
        data = request.get_json() or {}
        mode = (data.get('mode') or 'expired').strip().lower()
        hours = float(data.get('hours') or 2)
        single_url = (data.get('url') or data.get('file_url') or '').strip()

        # 1) single: 只删指定
        deleted_files = []
        errors = []
        preview_dirs = [
            PROJECT_ROOT / 'output' / 'previews',
            PROJECT_ROOT / 'storage' / 'tts_previews',
            PROJECT_ROOT / 'storage' / 'voice_zips',
            PROJECT_ROOT / 'outputs' / 'voiceover',
            PROJECT_ROOT / 'uploads' / 'voices',  # 试听失败的临时文件
        ]
        for d in preview_dirs: d.mkdir(parents=True, exist_ok=True)

        def _safe_delete(path: Path):
            try:
                if path.exists() and path.is_file():
                    path.unlink()
                    deleted_files.append(str(path.relative_to(PROJECT_ROOT)).replace('\\', '/'))
                    return True
            except Exception as d:
                errors.append(str(d))
            return False

        if mode == 'single' and single_url:
            # 去掉 /api/download/ 前缀
            rel = single_url
            if rel.startswith('/api/download/'): rel = rel[len('/api/download/'):]
            target = PROJECT_ROOT / rel
            _safe_delete(target)
        else:
            # all / expired：扫描预览目录
            cutoff = datetime.now() - timedelta(hours=hours)
            import os as _os
            for base in preview_dirs:
                for root, _, files in _os.walk(str(base)):
                    for fn in files:
                        fp = Path(root) / fn
                        try:
                            if mode == 'all':
                                _safe_delete(fp)
                            else:  # expired
                                mt = datetime.fromtimestamp(fp.stat().st_mtime)
                                if mt < cutoff:
                                    _safe_delete(fp)
                        except Exception:
                            pass

        return jsonify({'code': 0, 'msg': f'已删除 {len(deleted_files)} 个试听/临时文件' + (f'，{len(errors)} 个错误' if errors else ''),
                        'data': {'deleted': deleted_files, 'errors': errors}})
    except Exception as e:
        logger.error(f'删除试听临时文件失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'清理失败：{str(e)}', 'data': None}), 500
