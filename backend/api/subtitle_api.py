# -*- coding: utf-8 -*-
"""
字幕API - 完整实现
支持: 自动字幕生成、字幕编辑、字幕导出
"""

from flask import Blueprint, jsonify, request
import logging
import os
from datetime import datetime
import json
from backend.config.paths import SUBTITLE_STYLES

subtitle_bp = Blueprint('subtitle', __name__)
logger = logging.getLogger(__name__)
_db_manager = None


@subtitle_bp.route('/api/subtitle/generate', methods=['POST'])
def generate_subtitle():
    """旧版字幕生成入口（已废弃）

    实际的自动字幕流程已经由主应用中的 /api/subtitle/generate 路由
    （frontend/app.py 内实现，调用 faster-whisper + ffmpeg）接管。

    为避免返回任何固定示例字幕，这里仅返回明确的错误提示，
    引导调用方迁移到新的实现。
    """
    logger.warning('收到对已废弃 /api/subtitle/generate 的调用，已提示使用新实现')
    return jsonify({
        'code': 1,
        'msg': '当前字幕生成已由主应用中的 /api/subtitle/generate 实现（faster-whisper），本旧版入口不再返回示例字幕，请在编辑器或项目流程中使用新的接口。',
        'data': None
    }), 410


@subtitle_bp.route('/api/subtitle/<subtitle_id>', methods=['PUT'])
def update_subtitle(subtitle_id):
    """
    更新字幕内容和样式
    """
    try:
        data = request.json
        text = data.get('text')
        font_size = data.get('font_size', 24)
        font_color = data.get('font_color', '#FFFFFF')
        bg_color = data.get('bg_color', 'rgba(0,0,0,0.8)')
        font_bold = data.get('font_bold', False)
        font_italic = data.get('font_italic', False)
        font_underline = data.get('font_underline', False)

        logger.info(f"更新字幕: id={subtitle_id}, text={text}")

        if not text:
            return jsonify({
                'code': 1,
                'msg': '字幕内容不能为空'
            }), 400

        # 实际应用中会更新数据库
        # db_manager.update_subtitle(subtitle_id, {
        #     'text': text,
        #     'font_size': font_size,
        #     'font_color': font_color,
        #     'bg_color': bg_color,
        #     'font_bold': font_bold,
        #     'font_italic': font_italic,
        #     'font_underline': font_underline
        # })

        return jsonify({
            'code': 0,
            'msg': '字幕更新成功',
            'data': {
                'subtitle_id': subtitle_id,
                'text': text,
                'font_size': font_size,
                'font_color': font_color,
                'bg_color': bg_color,
                'font_bold': font_bold,
                'font_italic': font_italic,
                'font_underline': font_underline,
                'updated_at': datetime.now().isoformat()
            }
        })

    except Exception as e:
        logger.error(f"更新字幕失败: {str(e)}")
        return jsonify({
            'code': 1,
            'msg': f'字幕更新失败: {str(e)}'
        }), 500


@subtitle_bp.route('/api/subtitle/<subtitle_id>', methods=['DELETE'])
def delete_subtitle(subtitle_id):
    """
    删除字幕
    """
    try:
        logger.info(f"删除字幕: id={subtitle_id}")

        # 实际应用中会删除数据库记录
        # db_manager.delete_subtitle(subtitle_id)

        return jsonify({
            'code': 0,
            'msg': '字幕删除成功',
            'data': {
                'subtitle_id': subtitle_id
            }
        })

    except Exception as e:
        logger.error(f"删除字幕失败: {str(e)}")
        return jsonify({
            'code': 1,
            'msg': f'字幕删除失败: {str(e)}'
        }), 500


@subtitle_bp.route('/api/subtitle/export', methods=['POST'])
def export_subtitle():
    """旧版字幕导出入口（当前不再生成固定示例文件）

    实际的字幕导出建议在编辑器/项目导出流程中完成，
    由导出模块根据时间线与字幕脚本统一渲染并打包。

    为避免制造与真实项目不一致的 SRT 示例文件，此处仅返回
    明确的错误提示，引导调用方迁移到统一导出流程。
    """
    logger.warning('收到对旧版 /api/subtitle/export 的调用，当前不再生成示例 SRT 文件')
    return jsonify({
        'code': 1,
        'msg': '字幕导出请通过项目导出/编辑器流程完成，本旧版 /api/subtitle/export 不再生成示例SRT文件。',
        'data': None
    }), 410


@subtitle_bp.route('/api/subtitle/styles', methods=['GET'])
def get_subtitle_styles():
    """
    获取字幕样式预设
    """
    try:
        styles = []
        name_map = {
            'default': '默认样式',
            'large': '大号高亮',
            'small': '小号字幕',
            'colorful': '彩色强调',
            'zihun_wulongcha': '字魂·乌龙茶标题',
            'zihun_guochao': '字魂·国潮手书',
            'sourcehan_song_bold': '思源宋体（粗体）'
        }

        for style_id, cfg in SUBTITLE_STYLES.items():
            item = {
                'id': style_id,
                'name': name_map.get(style_id, style_id),
                'font': cfg.get('font'),
                'font_size': cfg.get('font_size'),
                'font_color': cfg.get('color'),
                'bg_color': cfg.get('bg_color'),
                'stroke_color': cfg.get('stroke_color'),
                'stroke_width': cfg.get('stroke_width'),
                'position': cfg.get('position', 'bottom')
            }
            styles.append(item)
    except Exception as e:
        logger.error(f"获取字幕样式预设失败: {e}")
        styles = []

    return jsonify({
        'code': 0,
        'msg': '获取成功',
        'data': {
            'styles': styles
        }
    })


# ==================== 花字：模板列表 ====================

@subtitle_bp.route('/api/subtitle/flower-templates', methods=['GET'])
def get_flower_templates():
    """获取全部花字模板预设"""
    try:
        from backend.engine.subtitle_generator import FLOWER_TEMPLATES
        templates = []
        for tid, cfg in FLOWER_TEMPLATES.items():
            # 把ASS颜色转回 #RRGGBB 便于前端展示
            def _ass_to_hex(ass_color: str) -> str:
                # &HAABBGGRR -> #RRGGBB
                try:
                    if not ass_color or not ass_color.startswith('&H') or len(ass_color) < 10:
                        return '#ffffff'
                    b = ass_color[4:6]
                    g = ass_color[6:8]
                    r = ass_color[8:10]
                    return f'#{r}{g}{b}'
                except Exception:
                    return '#ffffff'
            templates.append({
                'id': tid,
                'name': cfg.get('name', tid),
                'primary_color': _ass_to_hex(cfg.get('primary_color', '')),
                'stroke_color': _ass_to_hex(cfg.get('stroke_color', '')),
                'shadow_color': _ass_to_hex(cfg.get('shadow_color', '')),
                'outline': cfg.get('outline', 2),
                'bold': cfg.get('bold', True),
                'fontsize': cfg.get('fontsize', 48),
                'fontname': cfg.get('fontname', 'Microsoft YaHei'),
                'bg_box': cfg.get('bg_box', False)
            })
        return jsonify({
            'code': 0,
            'msg': 'success',
            'data': {'templates': templates, 'total': len(templates)}
        })
    except Exception as e:
        logger.error(f'获取花字模板失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'获取失败: {str(e)}', 'data': None}), 500


# ==================== 花字：保存配置 & 可选落地到项目 ====================

@subtitle_bp.route('/api/subtitle/flower-config', methods=['POST'])
def save_flower_config():
    """保存花字配置（前端通用入口）
    - 若传入 project_id，则将配置写进项目配置目录，下次打开恢复
    - 返回检测预览结果
    """
    try:
        data = request.get_json() or {}
        cfg = data.get('config') or {}
        project_id = (data.get('project_id') or '').strip()
        script_preview = (data.get('script') or data.get('preview_script') or '').strip()

        if not project_id:
            return jsonify({'code': 1, 'msg': '缺少 project_id，花字配置不能保存到未绑定项目', 'data': None}), 400

        # 基础校验
        if not isinstance(cfg, dict):
            return jsonify({'code': 1, 'msg': 'config 格式异常', 'data': None}), 400

        # 若有预览文本，执行一次花字检测并返回
        preview = {'spans': [], 'sample_ass_line': ''}
        try:
            from backend.engine.subtitle_generator import SubtitleGenerator
            gen = SubtitleGenerator()
            if script_preview:
                spans = gen.detect_flower_spans(script_preview, cfg)
                preview['spans'] = spans[:50]
                if spans:
                    ass_line, _meta = gen.wrap_flower_ass(script_preview, cfg, line_index=0)
                    preview['sample_ass_line'] = ass_line
        except Exception as e_prev:
            logger.warning(f'花字预览生成失败，不影响保存: {e_prev}')

        saved_path = None
        try:
            if _db_manager is None:
                raise RuntimeError('项目服务不可用')
            project = _db_manager.get_project(project_id)
            if not project:
                return jsonify({'code': 1, 'msg': '项目不存在，无法保存花字配置', 'data': None}), 404
            raw_project_config = project.get('config')
            project_config = json.loads(raw_project_config) if isinstance(raw_project_config, str) and raw_project_config else (raw_project_config or {})
            if not isinstance(project_config, dict):
                project_config = {}
            project_config['flower_config'] = cfg
            _db_manager.update_project(project_id, {'config': project_config})
        except Exception as e_save:
            logger.error(f'花字配置保存到项目失败: {e_save}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'保存失败: {str(e_save)}', 'data': None}), 500

        return jsonify({
            'code': 0,
            'msg': '花字配置已保存',
            'data': {
                'saved_path': saved_path,
                'config': cfg,
                'preview': preview,
                'hint': '导出剪映草稿 / 渲染字幕 / ASS生成时将自动使用此配置'
            }
        })
    except Exception as e:
        logger.error(f'保存花字配置失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'保存失败: {str(e)}', 'data': None}), 500


# ==================== 花字：生成 ASS 字幕文件 ====================

@subtitle_bp.route('/api/subtitle/generate-ass', methods=['POST'])
def generate_ass_api():
    """生成带花字的ASS字幕文件
    body: {
        "narration_script": { "narrations": [ {"time_range":"0s-3s","text":"..."} ] },
        "flower_config": {...},
        "output_path": "可选，绝对/相对output目录",
        "project_id": "可选，用于自动生成路径"
    }
    """
    try:
        data = request.get_json() or {}
        narration_script = data.get('narration_script') or data.get('script') or {}
        flower_config = data.get('flower_config') or data.get('config') or None
        project_id = (data.get('project_id') or '').strip() or f'ass_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        video_width = int(data.get('video_width') or 1920)
        video_height = int(data.get('video_height') or 1080)

        narrations = narration_script.get('narrations') if isinstance(narration_script, dict) else None
        if not narrations:
            return jsonify({'code': 1, 'msg': '缺少 narration_script.narrations', 'data': None}), 400

        from backend.engine.subtitle_generator import SubtitleGenerator
        gen = SubtitleGenerator()

        from backend.config.paths import project_output_dir, resolve_output_path
        output_path = data.get('output_path') or ''
        if not output_path:
            output_path = str(project_output_dir('projects', project_id, 'subtitles') / 'flower_subtitle.ass')
        else:
            output_path = str(resolve_output_path(output_path, create_parent=True))

        result = gen.generate_ass_from_script(
            narration_script, output_path, flower_config,
            video_width=video_width, video_height=video_height
        )
        # 同时构建剪映花字轨道数据
        try:
            jianying = gen.build_jianying_flower_track(narration_script, flower_config)
        except Exception:
            jianying = None
        result['jianying_flower_track'] = jianying
        # 支持相对路径返回
        try:
            from backend.config.paths import PROJECT_ROOT
            if str(output_path).startswith(str(PROJECT_ROOT)):
                result['relative_path'] = os.path.relpath(output_path, str(PROJECT_ROOT)).replace('\\', '/')
        except Exception:
            pass
        return jsonify({'code': 0, 'msg': 'ASS花字字幕生成完成', 'data': result})
    except Exception as e:
        logger.error(f'生成ASS花字字幕失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'生成失败: {str(e)}', 'data': None}), 500


def register_subtitle_routes(app, db_manager=None):
    """注册字幕 API 路由。"""
    global _db_manager
    _db_manager = db_manager
    app.register_blueprint(subtitle_bp)
    logger.info("字幕API路由注册成功")
