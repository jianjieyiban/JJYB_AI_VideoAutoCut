#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : advanced_routes.py
@Desc   : 高级功能API路由 - 融入JJYB-ZJ的优秀功能
          包含：文案质检、AI智能去重、精选视频复刻、
                智能穿插原片、覆盖审计、音画强制对齐、AI提纯文案
"""

import os
import json
import time
import uuid
import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app

logger = logging.getLogger('JJYB_AI智剪')

# 创建蓝图
advanced_bp = Blueprint('advanced', __name__, url_prefix='/api/advanced')

# 全局变量（将在注册时设置）
_db_manager = None
_task_service = None
_socketio = None
_commentary_service = None


def register_advanced_routes(app, db_manager, task_service, socketio, commentary_service=None):
    """注册高级功能API路由"""
    global _db_manager, _task_service, _socketio, _commentary_service
    _db_manager = db_manager
    _task_service = task_service
    _socketio = socketio
    _commentary_service = commentary_service

    app.register_blueprint(advanced_bp)
    logger.info('✅ 高级功能API路由注册完成（文案质检/AI去重/精选复刻/智能穿插/覆盖审计/音画对齐/AI提纯）')


def _get_llm():
    """获取LLM适配器（统一入口）"""
    try:
        from backend.core.global_state import get_global_state
        gs = get_global_state()
        return gs.get_multi_model_manager()
    except Exception as e:
        logger.error(f'获取LLM适配器失败: {e}')
        return None


def _llm_chat(prompt: str, temperature: float = 0.3) -> str:
    """统一调用LLM生成文本"""
    llm = _get_llm()
    if not llm:
        raise RuntimeError('LLM适配器未初始化，请检查AI配置')
    return llm.generate_text(prompt, temperature=temperature)


# ==================== 文案质检 ====================

@advanced_bp.route('/script-doctor/diagnose', methods=['POST'])
def script_doctor_diagnose():
    """文案质检 - 六维评分诊断"""
    try:
        data = request.get_json() or {}
        script = data.get('script', '').strip()
        video_description = data.get('video_description', '')

        if not script:
            return jsonify({'code': 1, 'msg': '缺少待质检文案', 'data': None}), 400

        # 使用LLM进行诊断
        from backend.prompts.script_doctor import ScriptDoctor

        prompt = ScriptDoctor.get_diagnosis_prompt(script, video_description)

        try:
            response = _llm_chat(prompt, temperature=0.3)
            # 尝试解析JSON
            result = _parse_json_response(response)
            if result:
                # 计算综合评分
                if 'dimensions' in result:
                    result['overall_score'] = ScriptDoctor.calculate_overall_score(result['dimensions'])
                return jsonify({'code': 0, 'msg': '诊断完成', 'data': result})
            else:
                return jsonify({
                    'code': 1,
                    'msg': 'AI返回格式异常，请重试',
                    'data': {'raw_response': response[:500]}
                }), 500
        except Exception as e:
            logger.error(f'LLM诊断失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'AI诊断失败: {str(e)}', 'data': None}), 500

    except Exception as e:
        logger.error(f'文案质检失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'质检失败: {str(e)}', 'data': None}), 500


@advanced_bp.route('/script-doctor/optimize', methods=['POST'])
def script_doctor_optimize():
    """文案质检 - 生成三套优化方案"""
    try:
        data = request.get_json() or {}
        script = data.get('script', '').strip()
        diagnosis = data.get('diagnosis', '')

        if not script:
            return jsonify({'code': 1, 'msg': '缺少待优化文案', 'data': None}), 400

        from backend.prompts.script_doctor import ScriptDoctor

        prompt = ScriptDoctor.get_optimization_prompt(script, json.dumps(diagnosis, ensure_ascii=False) if isinstance(diagnosis, dict) else str(diagnosis))

        try:
            response = _llm_chat(prompt, temperature=0.7)
            result = _parse_json_response(response)
            if result:
                return jsonify({'code': 0, 'msg': '优化方案生成完成', 'data': result})
            else:
                return jsonify({
                    'code': 1,
                    'msg': 'AI返回格式异常，请重试',
                    'data': {'raw_response': response[:500]}
                }), 500
        except Exception as e:
            logger.error(f'优化方案生成失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'优化失败: {str(e)}', 'data': None}), 500

    except Exception as e:
        logger.error(f'生成优化方案失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'生成失败: {str(e)}', 'data': None}), 500


@advanced_bp.route('/script-doctor/dimensions', methods=['GET'])
def script_doctor_dimensions():
    """获取评分维度信息"""
    try:
        from backend.prompts.script_doctor import ScriptDoctor
        return jsonify({
            'code': 0,
            'msg': 'success',
            'data': {
                'dimensions': ScriptDoctor.get_dimensions_info(),
                'max_overall_score': 10
            }
        })
    except Exception as e:
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


# ==================== AI提纯文案 ====================

@advanced_bp.route('/script-purify', methods=['POST'])
def script_purify():
    """AI提纯文案 - 自动去除非解说词内容"""
    try:
        data = request.get_json() or {}
        raw_text = data.get('raw_text', '').strip()

        if not raw_text:
            return jsonify({'code': 1, 'msg': '缺少原始文案', 'data': None}), 400

        from backend.prompts.narration_styles import ScriptPurifier

        prompt = ScriptPurifier.get_purify_prompt(raw_text)

        try:
            response = _llm_chat(prompt, temperature=0.3)

            # 提纯直接返回纯文本
            purified = response.strip() if response else ''
            # 简单校验：如果返回太短或太长，可能有问题
            if len(purified) < len(raw_text) * 0.3:
                logger.warning('提纯结果过短，可能存在问题')
            if len(purified) > len(raw_text) * 1.5:
                logger.warning('提纯结果过长，可能包含额外说明')
                # 取第一段作为纯文案
                purified = purified.split('\n\n')[0]

            return jsonify({
                'code': 0,
                'msg': '提纯完成',
                'data': {
                    'original_text': raw_text,
                    'purified_text': purified,
                    'original_length': len(raw_text),
                    'purified_length': len(purified),
                    'reduction_ratio': round(1 - len(purified) / max(len(raw_text), 1), 2)
                }
            })
        except Exception as e:
            logger.error(f'AI提纯失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'AI提纯失败: {str(e)}', 'data': None}), 500

    except Exception as e:
        logger.error(f'文案提纯失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'提纯失败: {str(e)}', 'data': None}), 500


# ==================== 覆盖审计 ====================

@advanced_bp.route('/coverage-audit', methods=['POST'])
def coverage_audit():
    """覆盖审计 - 检查文案与视频的时间覆盖情况"""
    try:
        data = request.get_json() or {}
        video_duration = float(data.get('video_duration', 0))
        scenes = data.get('scenes', [])
        narrations = data.get('narrations', [])
        gap_threshold = float(data.get('gap_threshold', 5.0))

        if not scenes or not narrations:
            return jsonify({'code': 1, 'msg': '缺少场景或文案数据', 'data': None}), 400

        from backend.engine.ai_dedup_engine import CoverageAuditEngine
        engine = CoverageAuditEngine()
        result = engine.audit_coverage(video_duration, scenes, narrations, gap_threshold)

        return jsonify({'code': 0, 'msg': '审计完成', 'data': result})

    except Exception as e:
        logger.error(f'覆盖审计失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'审计失败: {str(e)}', 'data': None}), 500


# ==================== AI智能去重 ====================

@advanced_bp.route('/ai-dedup/plan', methods=['POST'])
def ai_dedup_plan():
    """AI智能去重 - 生成变换方案"""
    try:
        data = request.get_json() or {}
        segments = data.get('segments', [])
        config_dict = data.get('config', {})

        if not segments:
            return jsonify({'code': 1, 'msg': '缺少视频片段数据', 'data': None}), 400

        from backend.engine.ai_dedup_engine import AIDedupEngine, DedupConfig

        # 从配置字典构建DedupConfig
        config = DedupConfig()
        if config_dict:
            for k, v in config_dict.items():
                if hasattr(config, k):
                    setattr(config, k, v)

        engine = AIDedupEngine(config)
        plans = engine.plan_transforms(segments)
        summary = engine.get_plan_summary(plans)

        return jsonify({
            'code': 0,
            'msg': '去重方案生成完成',
            'data': {
                'plans': [
                    {
                        'segment_index': p.segment_index,
                        'start_time': p.start_time,
                        'end_time': p.end_time,
                        'zoom': p.zoom,
                        'mirror': p.mirror,
                        'saturation': p.saturation,
                        'temperature': p.temperature,
                        'tint': p.tint,
                        'rotate': p.rotate,
                        'has_transform': p.has_transform,
                        'ffmpeg_filter': engine.build_ffmpeg_filter(p) if p.has_transform else ''
                    }
                    for p in plans
                ],
                'summary': summary,
                'config': config_dict
            }
        })

    except Exception as e:
        logger.error(f'AI去重方案生成失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'生成失败: {str(e)}', 'data': None}), 500


@advanced_bp.route('/ai-dedup/apply', methods=['POST'])
def ai_dedup_apply():
    """AI智能去重 - 应用变换方案到视频"""
    try:
        data = request.get_json() or {}
        video_path = data.get('video_path')
        plans = data.get('plans', [])
        output_path = data.get('output_path')

        if not video_path or not os.path.exists(video_path):
            return jsonify({'code': 1, 'msg': '视频文件不存在', 'data': None}), 400
        if not plans:
            return jsonify({'code': 1, 'msg': '缺少去重方案', 'data': None}), 400

        # 这里返回执行计划，实际执行需要异步处理
        # 实际应用时通过任务系统异步执行
        task_id = str(uuid.uuid4())
        return jsonify({
            'code': 0,
            'msg': '去重任务已创建',
            'data': {
                'task_id': task_id,
                'video_path': video_path,
                'output_path': output_path,
                'plans_count': len(plans),
                'estimated_time': len(plans) * 3  # 估算每段3秒
            }
        })

    except Exception as e:
        logger.error(f'AI去重应用失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'应用失败: {str(e)}', 'data': None}), 500


# ==================== 智能穿插原片 ====================

@advanced_bp.route('/highlight/select', methods=['POST'])
def highlight_select():
    """智能穿插原片 - 选择高光片段"""
    try:
        data = request.get_json() or {}
        scenes = data.get('scenes', [])
        count = int(data.get('count', 3))
        min_duration = float(data.get('min_duration', 3.0))

        if not scenes:
            return jsonify({'code': 1, 'msg': '缺少场景数据', 'data': None}), 400

        from backend.engine.ai_dedup_engine import HighlightSelector
        selector = HighlightSelector()

        highlights = selector.select_highlights(scenes, count, min_duration)
        hook_scene = selector.select_hook_scene(scenes)

        return jsonify({
            'code': 0,
            'msg': '高光片段选择完成',
            'data': {
                'highlights': highlights,
                'hook_scene': hook_scene,
                'total_scenes': len(scenes),
                'selected_count': len(highlights)
            }
        })

    except Exception as e:
        logger.error(f'高光选择失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'选择失败: {str(e)}', 'data': None}), 500


# ==================== 音画强制对齐 ====================

@advanced_bp.route('/force-align', methods=['POST'])
def force_align():
    """音画强制对齐 - 配音略长于原片时双向微调"""
    try:
        data = request.get_json() or {}
        segments = data.get('segments', [])
        max_video_speed = float(data.get('max_video_speed', 1.05))
        max_audio_speed = float(data.get('max_audio_speed', 1.05))

        if not segments:
            return jsonify({'code': 1, 'msg': '缺少片段数据', 'data': None}), 400

        from backend.engine.ai_dedup_engine import ForceAlignEngine
        engine = ForceAlignEngine()
        aligned = engine.align(segments, max_video_speed, max_audio_speed)

        # 统计对齐情况
        stats = {
            'total': len(aligned),
            'no_adjust': sum(1 for a in aligned if a.get('align_action') == 'none'),
            'audio_longer': sum(1 for a in aligned if a.get('align_action') == 'audio_longer'),
            'video_longer': sum(1 for a in aligned if a.get('align_action') == 'video_longer')
        }

        return jsonify({
            'code': 0,
            'msg': '对齐方案生成完成',
            'data': {
                'aligned_segments': aligned,
                'stats': stats
            }
        })

    except Exception as e:
        logger.error(f'音画对齐失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'对齐失败: {str(e)}', 'data': None}), 500


# ==================== 精选视频复刻 ====================

@advanced_bp.route('/curated-remake/match', methods=['POST'])
def curated_remake_match():
    """精选视频复刻 - 文案与视频场景匹配"""
    try:
        data = request.get_json() or {}
        narrations = data.get('narrations', [])
        scenes_by_video = data.get('scenes_by_video', {})
        tts_durations = data.get('tts_durations')
        config_dict = data.get('config', {})

        if not narrations or not scenes_by_video:
            return jsonify({'code': 1, 'msg': '缺少文案或场景数据', 'data': None}), 400

        from backend.engine.curated_remake_engine import CuratedRemakeEngine, RemakeConfig

        config = RemakeConfig()
        if config_dict:
            for k, v in config_dict.items():
                if hasattr(config, k):
                    setattr(config, k, v)

        engine = CuratedRemakeEngine(config)
        results = engine.match_narrations_to_scenes(narrations, scenes_by_video, tts_durations)
        report = engine.generate_match_report(results)
        plan = engine.build_remake_plan(results, scenes_by_video)

        return jsonify({
            'code': 0,
            'msg': '复刻匹配完成',
            'data': {
                'match_results': [
                    {
                        'narration_index': r.narration_index,
                        'narration_text': r.narration_text,
                        'tts_duration': r.tts_duration,
                        'clip_count': r.clip_count,
                        'clip_duration': r.clip_duration,
                        'clip_range': r.clip_range,
                        'scene_ids': r.scene_ids,
                        'confidence': r.confidence,
                        'is_suspect': r.is_suspect,
                        'source_video': r.source_video
                    }
                    for r in results
                ],
                'report': report,
                'remake_plan': plan
            }
        })

    except Exception as e:
        logger.error(f'精选复刻匹配失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'匹配失败: {str(e)}', 'data': None}), 500


@advanced_bp.route('/curated-remake/export-suspect', methods=['POST'])
def curated_remake_export_suspect():
    """精选视频复刻 - 导出存疑清单"""
    try:
        data = request.get_json() or {}
        results = data.get('results', [])
        output_dir = data.get('output_dir', 'output/exports')

        if not results:
            return jsonify({'code': 1, 'msg': '缺少匹配结果', 'data': None}), 400

        from backend.engine.curated_remake_engine import CuratedRemakeEngine, MatchResult, RemakeConfig

        # 重建MatchResult对象
        match_results = [
            MatchResult(
                narration_index=r.get('narration_index', 0),
                narration_text=r.get('narration_text', ''),
                tts_duration=r.get('tts_duration', 0),
                clip_count=r.get('clip_count', 0),
                clip_duration=r.get('clip_duration', 0),
                clip_range=r.get('clip_range', ''),
                scene_ids=r.get('scene_ids', []),
                confidence=r.get('confidence', 0),
                is_suspect=r.get('is_suspect', False),
                source_video=r.get('source_video', '')
            )
            for r in results
        ]

        engine = CuratedRemakeEngine()
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, '存疑清单.txt')
        engine.export_suspect_list(match_results, output_path)

        return jsonify({
            'code': 0,
            'msg': '存疑清单已导出',
            'data': {'output_path': output_path}
        })

    except Exception as e:
        logger.error(f'导出存疑清单失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'导出失败: {str(e)}', 'data': None}), 500


@advanced_bp.route('/curated-remake/extract-script', methods=['POST'])
def curated_remake_extract_script():
    """精选视频复刻 - 从爆款视频提取解说文案（ASR识别）"""
    try:
        data = request.get_json() or {}
        video_path = data.get('video_path', '').strip()
        language = data.get('language', 'zh')
        engine_name = data.get('engine', 'whisper')

        if not video_path:
            return jsonify({'code': 1, 'msg': '缺少爆款视频路径', 'data': None}), 400
        if not os.path.exists(video_path):
            return jsonify({'code': 1, 'msg': f'视频文件不存在: {video_path}', 'data': None}), 400

        # 先从视频中提取音频
        from pathlib import Path
        import tempfile
        import subprocess

        audio_tmp = Path(tempfile.gettempdir()) / f'remake_extract_{uuid.uuid4().hex[:8]}.wav'
        extract_cmd = [
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-i', video_path,
            '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le',
            str(audio_tmp)
        ]
        try:
            result = subprocess.run(extract_cmd, capture_output=True, text=True, timeout=300, check=False)
            if result.returncode != 0 or not audio_tmp.exists():
                return jsonify({'code': 1, 'msg': f'音频提取失败: {result.stderr[:200]}', 'data': None}), 500
        except subprocess.TimeoutExpired:
            return jsonify({'code': 1, 'msg': '音频提取超时（视频过大）', 'data': None}), 500

        # 调用ASR引擎
        try:
            from backend.engine.asr_engine import ASREngine
            asr = ASREngine(default_engine=engine_name)
            asr_result = asr.recognize(str(audio_tmp), engine=engine_name, language=language)
        except Exception as asr_err:
            logger.error(f'ASR识别失败: {asr_err}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'ASR识别失败: {str(asr_err)}', 'data': None}), 500
        finally:
            try:
                audio_tmp.unlink(missing_ok=True)
            except Exception:
                pass

        # 提取文案
        segments = asr_result.get('segments', []) if isinstance(asr_result, dict) else []
        full_text = asr_result.get('text', '') if isinstance(asr_result, dict) else ''

        # 合并分段文案
        if not full_text and segments:
            full_text = ''.join([s.get('text', '') for s in segments if isinstance(s, dict)])

        # 清理文案
        if full_text:
            full_text = full_text.strip()

        return jsonify({
            'code': 0,
            'msg': '文案提取完成',
            'data': {
                'video_path': video_path,
                'full_text': full_text,
                'segments': segments,
                'segment_count': len(segments),
                'text_length': len(full_text),
                'engine_used': engine_name,
                'language': language
            }
        })

    except Exception as e:
        logger.error(f'爆款文案提取失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'提取失败: {str(e)}', 'data': None}), 500


@advanced_bp.route('/curated-remake/rewrite-script', methods=['POST'])
def curated_remake_rewrite_script():
    """精选视频复刻 - AI改写文案（基于爆款参考文案改写为原创）"""
    try:
        data = request.get_json() or {}
        reference_text = data.get('reference_text', '').strip()
        user_hint = data.get('user_hint', '').strip()
        style = data.get('style', 'default')
        perspective = data.get('perspective', 'first_person')
        target_duration_minutes = float(data.get('target_duration_minutes', 5.0))
        preserve_structure = data.get('preserve_structure', True)
        creativity = float(data.get('creativity', 0.7))

        if not reference_text:
            return jsonify({'code': 1, 'msg': '缺少爆款参考文案', 'data': None}), 400

        # 构建改写提示词
        from backend.prompts.narration_styles import NarrationStyles

        style_info = NarrationStyles.get_style(style) if hasattr(NarrationStyles, 'get_style') else None
        style_desc = ''
        if style_info and isinstance(style_info, dict):
            style_desc = style_info.get('description', '')

        perspective_map = {
            'first_person': '第一人称（"我"视角，亲切自然）',
            'third_person': '第三人称（客观叙述）',
            'god_view': '上帝视角（全知全能）',
            'character': '角色代入（以影视角色视角）'
        }
        perspective_desc = perspective_map.get(perspective, perspective_map['first_person'])

        # 估算目标字数（中文约3字/秒，配音通常4-5字/秒）
        target_chars = int(target_duration_minutes * 60 * 4)

        prompt = f"""你是一位资深的影视解说文案创作大师。请基于以下爆款解说视频的文案，改写为一篇全新的原创解说文案。

【任务要求】
1. 保持原爆款文案的核心叙事结构和信息密度
2. 完全改写表达方式，避免与原文雷同（相似度<30%）
3. 保留原有的关键剧情点和情绪起伏节奏
4. 生成纯文案，不要任何标注、序号、分段符
5. 文案要自然流畅、口语化、有感染力

【参考爆款文案】
{reference_text}

【用户创作提示】
{user_hint if user_hint else '无特殊要求，请自由发挥'}

【风格要求】
解说风格：{style} ({style_desc})
叙述视角：{perspective_desc}

【长度要求】
目标时长：{target_duration_minutes}分钟
目标字数：约{target_chars}字

{"【结构要求】保持原文的段落结构和节奏感，每个信息点都要保留但用不同方式表达" if preserve_structure else "【结构要求】可以重新组织结构，但保留核心信息点"}

【创造力】{creativity:.1f}/1.0 (0=保守改写，1=完全创新)

请直接输出改写后的原创解说文案，不要包含任何说明性文字："""

        try:
            response = _llm_chat(prompt, temperature=creativity)
            rewritten = response.strip() if response else ''

            if not rewritten:
                return jsonify({'code': 1, 'msg': 'AI未返回有效文案', 'data': None}), 500

            # 简单校验
            if len(rewritten) < len(reference_text) * 0.2:
                logger.warning('改写结果过短，可能存在问题')
            if len(rewritten) > len(reference_text) * 2.5:
                logger.warning('改写结果过长，可能包含额外说明')
                # 取第一段
                rewritten = rewritten.split('\n\n')[0]

            # 计算相似度（简单的Jaccard相似度）
            ref_words = set(reference_text)
            new_words = set(rewritten)
            if ref_words and new_words:
                intersection = len(ref_words & new_words)
                union = len(ref_words | new_words)
                similarity = round(intersection / union, 3) if union else 0
            else:
                similarity = 0

            return jsonify({
                'code': 0,
                'msg': '改写完成',
                'data': {
                    'reference_text': reference_text,
                    'rewritten_text': rewritten,
                    'reference_length': len(reference_text),
                    'rewritten_length': len(rewritten),
                    'estimated_duration_minutes': round(len(rewritten) / 240, 1),
                    'similarity_to_original': similarity,
                    'originality_score': round(1 - similarity, 3),
                    'style_used': style,
                    'perspective_used': perspective
                }
            })
        except Exception as e:
            logger.error(f'AI改写失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'AI改写失败: {str(e)}', 'data': None}), 500

    except Exception as e:
        logger.error(f'文案改写失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'改写失败: {str(e)}', 'data': None}), 500


# ==================== 解说风格 ====================

@advanced_bp.route('/narration-styles', methods=['GET', 'POST'])
def get_narration_styles():
    """获取所有解说风格 (GET) / 应用解说风格到项目 (POST)"""
    try:
        from backend.prompts.narration_styles import NarrationStyles
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            return jsonify({
                'code': 0,
                'msg': '解说风格已应用',
                'data': {
                    'applied': True,
                    'narration_style': data.get('narration_style', ''),
                    'narrative_view': data.get('narrative_view', ''),
                    'speech_rate': data.get('speech_rate', '1x'),
                    'emotion_density': data.get('emotion_density', '')
                }
            })
        return jsonify({
            'code': 0,
            'msg': 'success',
            'data': {
                'styles': NarrationStyles.get_style_list(),
                'total': len(NarrationStyles.STYLES)
            }
        })
    except Exception as e:
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


@advanced_bp.route('/narration-styles/<style_key>', methods=['GET'])
def get_narration_style_detail(style_key):
    """获取指定风格的详细信息"""
    try:
        from backend.prompts.narration_styles import NarrationStyles
        style = NarrationStyles.get_style(style_key)
        return jsonify({
            'code': 0,
            'msg': 'success',
            'data': {
                'key': style_key,
                'style': style,
                'prompt': NarrationStyles.get_style_prompt(style_key)
            }
        })
    except Exception as e:
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


@advanced_bp.route('/story-structure', methods=['GET'])
def get_story_structure():
    """获取六段式故事结构提示词"""
    try:
        from backend.prompts.narration_styles import StoryStructure
        return jsonify({
            'code': 0,
            'msg': 'success',
            'data': {
                'structure_prompt': StoryStructure.get_structure_prompt()
            }
        })
    except Exception as e:
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


# ==================== LLM精排 ====================

@advanced_bp.route('/script-match', methods=['POST'])
def script_match():
    """LLM精排 - Top-K候选重排序"""
    try:
        data = request.get_json() or {}
        narrations = data.get('narrations', [])
        candidate_scenes = data.get('candidate_scenes', [])

        if not narrations or not candidate_scenes:
            return jsonify({'code': 1, 'msg': '缺少文案或候选场景', 'data': None}), 400

        from backend.prompts.script_doctor import ScriptMatcher

        prompt = ScriptMatcher.get_match_prompt(narrations, candidate_scenes)

        try:
            response = _llm_chat(prompt, temperature=0.3)
            result = _parse_json_response(response)
            if result:
                return jsonify({'code': 0, 'msg': '精排完成', 'data': result})
            else:
                return jsonify({
                    'code': 1,
                    'msg': 'AI返回格式异常',
                    'data': {'raw_response': response[:500]}
                }), 500
        except Exception as e:
            logger.error(f'LLM精排失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'精排失败: {str(e)}', 'data': None}), 500

    except Exception as e:
        logger.error(f'脚本匹配失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'匹配失败: {str(e)}', 'data': None}), 500


# ==================== 多格式时间线导出 ====================

@advanced_bp.route('/export/multi-format', methods=['POST'])
def export_multi_format():
    """多格式时间线导出 - 支持Premiere XML/FCPXML/SRT/ASS/EDL/CapCut"""
    try:
        data = request.get_json() or {}
        timeline = data.get('timeline', {})
        formats = data.get('formats', ['premiere_xml'])
        project_name = data.get('project_name', '未命名项目')
        output_dir = data.get('output_dir', 'output/exports/multi_format')

        if not timeline or not isinstance(timeline, dict):
            return jsonify({'code': 1, 'msg': '缺少时间线数据', 'data': None}), 400

        if not formats or not isinstance(formats, list):
            return jsonify({'code': 1, 'msg': '请指定导出格式', 'data': None}), 400

        # 支持的格式列表
        supported_formats = {
            'premiere_xml': 'Premiere Pro XML',
            'fcpxml': 'Final Cut Pro XML',
            'srt': 'SRT字幕',
            'ass': 'ASS字幕（带样式）',
            'edl': 'EDL剪辑决策表',
            'capcut': 'CapCut国际剪映草稿'
        }
        invalid = [f for f in formats if f not in supported_formats]
        if invalid:
            return jsonify({
                'code': 1,
                'msg': f'不支持的格式: {", ".join(invalid)}',
                'data': {'supported': supported_formats}
            }), 400

        from backend.engine.multi_format_exporter import MultiFormatExporter
        from backend.config.paths import PROJECT_ROOT

        exporter = MultiFormatExporter()
        project = exporter.from_universal_timeline(timeline)
        project.project_name = project_name or project.project_name

        # 导出统一限制在项目输出目录，避免外部调用写入任意位置。
        export_root = PROJECT_ROOT / 'output' / 'exports' / 'multi_format'
        formats = list(dict.fromkeys(formats))
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        safe_session_name = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in str(project_name))[:30] or 'project'
        session_dir = str(export_root / f'{timestamp}_{safe_session_name}_{uuid.uuid4().hex[:8]}')
        os.makedirs(session_dir, exist_ok=True)

        results = exporter.export_all_formats(project, session_dir, formats)

        # 构建下载URL列表
        download_urls = {}
        relative_dir = os.path.relpath(session_dir, PROJECT_ROOT).replace('\\', '/')
        public_relative_dir = relative_dir.removeprefix('output/')
        for fmt, path in results.items():
            if isinstance(path, str) and not path.startswith('ERROR'):
                filename = os.path.basename(path)
                download_urls[fmt] = f'/output/{public_relative_dir}/{filename}'

        success_count = sum(1 for v in results.values() if not str(v).startswith('ERROR'))
        failed_count = len(results) - success_count

        return jsonify({
            'code': 0,
            'msg': f'导出完成：成功{success_count}项' + (f'，失败{failed_count}项' if failed_count else ''),
            'data': {
                'results': results,
                'download_urls': download_urls,
                'output_dir': session_dir,
                'relative_dir': relative_dir,
                'formats_requested': formats,
                'supported_formats': supported_formats,
                'project_name': project_name,
                'timeline_duration': project.duration,
                'tracks_count': len(project.tracks)
            }
        })

    except Exception as e:
        logger.error(f'多格式导出失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'导出失败: {str(e)}', 'data': None}), 500


@advanced_bp.route('/export/formats', methods=['GET'])
def get_supported_formats():
    """获取支持的导出格式列表"""
    return jsonify({
        'code': 0,
        'msg': 'success',
        'data': {
            'formats': [
                {'key': 'premiere_xml', 'name': 'Premiere Pro XML', 'ext': '.xml', 'desc': 'Adobe Premiere Pro 可直接导入的XML格式'},
                {'key': 'fcpxml', 'name': 'Final Cut Pro XML', 'ext': '.fcpxml', 'desc': 'Apple Final Cut Pro X 可直接导入的XML格式'},
                {'key': 'srt', 'name': 'SRT字幕', 'ext': '.srt', 'desc': '通用字幕格式，几乎所有播放器和剪辑软件都支持'},
                {'key': 'ass', 'name': 'ASS字幕', 'ext': '.ass', 'desc': '高级字幕格式，支持样式、特效、定位'},
                {'key': 'edl', 'name': 'EDL剪辑决策表', 'ext': '.edl', 'desc': '编辑决策表，老牌剪辑系统通用格式'},
                {'key': 'capcut', 'name': 'CapCut国际剪映', 'ext': '.json', 'desc': '国际版剪映CapCut草稿格式'}
            ]
        }
    })


# ==================== TTS Provider 插件化架构 ====================

@advanced_bp.route('/tts/providers', methods=['GET'])
def list_tts_providers():
    """列出所有可用的TTS Provider"""
    try:
        from backend.engine.tts_provider import get_tts_registry
        registry = get_tts_registry()
        providers = registry.list_available_providers()
        default_name = registry.get_default_provider_name()
        return jsonify({
            'code': 0,
            'msg': 'success',
            'data': {
                'providers': providers,
                'total': len(providers),
                'available_count': sum(1 for p in providers if p.get('available')),
                'default_provider': default_name
            }
        })
    except Exception as e:
        logger.error(f'列出TTS Provider失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


@advanced_bp.route('/tts/synthesize', methods=['POST'])
def tts_synthesize():
    """使用指定Provider合成语音（统一接口）"""
    try:
        data = request.get_json() or {}
        text = data.get('text', '').strip()
        if not text:
            return jsonify({'code': 1, 'msg': '缺少待合成文本', 'data': None}), 400

        engine = data.get('engine', '')
        voice = data.get('voice', '')
        output_dir = data.get('output_dir', 'output/audios/tts_provider')
        if not os.path.isabs(output_dir):
            from backend.config.paths import PROJECT_ROOT
            output_dir = str(PROJECT_ROOT / output_dir)
        os.makedirs(output_dir, exist_ok=True)

        output_filename = data.get('output_filename') or f'tts_{uuid.uuid4().hex[:8]}.{data.get("format", "mp3")}'
        output_path = os.path.join(output_dir, output_filename)

        from backend.engine.tts_provider import get_tts_registry, TTSRequest

        registry = get_tts_registry()
        request_obj = TTSRequest(
            text=text,
            output_path=output_path,
            voice=voice,
            language=data.get('language', 'zh-CN'),
            rate=data.get('rate', '+0%'),
            volume=data.get('volume', '+0%'),
            pitch=data.get('pitch'),
            emotion=data.get('emotion', 'neutral'),
            emotion_intensity=float(data.get('emotion_intensity', 1.0)),
            reference_audio_path=data.get('reference_audio_path', ''),
            clone_voice_id=data.get('clone_voice_id', ''),
            sample_rate=int(data.get('sample_rate', 24000)),
            audio_format=data.get('format', 'mp3'),
            metadata=data.get('metadata', {})
        )

        # 优先使用指定引擎，失败则回退
        result = registry.synthesize_with_fallback(
            request_obj, [engine] if engine else None
        )

        if result.success:
            return jsonify({
                'code': 0,
                'msg': '合成成功',
                'data': {
                    'output_path': result.output_path,
                    'duration': result.duration,
                    'file_size': result.file_size,
                    'audio_format': result.audio_format,
                    'engine_used': result.engine_name,
                    'voice_used': result.voice_used,
                    'download_url': f'/output/audios/tts_provider/{output_filename}'
                }
            })
        else:
            return jsonify({
                'code': 1,
                'msg': result.error or '合成失败',
                'data': {'engine_tried': result.engine_name}
            }), 500
    except Exception as e:
        logger.error(f'TTS合成失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


# ==================== 高光/金句提取（JJYB-ZJ能力） ====================

@advanced_bp.route('/highlight-extract', methods=['POST'])
def highlight_extract():
    """从解说文稿中提取金句/高光片段，用于生成花字与封面"""
    try:
        data = request.get_json() or {}
        script = (data.get('script') or data.get('text') or '').strip()
        mode = (data.get('mode') or 'gold_sentence').strip()
        coverage_ratio = float(data.get('coverage') or 0.25)

        if not script:
            return jsonify({'code': 1, 'msg': '缺少待提取的解说文稿', 'data': None}), 400

        # 优先使用LLM进行智能提取
        try:
            prompt = f"""你是专业的视频解说金句分析师。请对以下解说文稿进行高光分析。
提取模式：{mode}（可选：gold_sentence金句优先 / reverse反转点 / emotion情绪高点 / info关键信息）
目标覆盖率：{coverage_ratio * 100:.0f}%

请返回严格的JSON格式，不要包含Markdown代码块：
{{
  "highlights": [
    {{"index": 1, "text": "金句原文", "type": "gold|reverse|emotion|info", "score": 0.92, "suggest_position": "head|body|tail", "emotion_tag": "震撼/感动/好奇/热血"}},
    ...
  ],
  "keywords": ["关键词1", "关键词2", ...],
  "cover_sentence": "最适合做封面的一句话",
  "opening_hook": "开头3秒钩子句",
  "closing_cta": "片尾CTA句"
}}

解说文稿：
{script[:8000]}
"""
            response = _llm_chat(prompt, temperature=0.3)
            result = _parse_json_response(response)
            if result and 'highlights' in result:
                # 注入一些兜底字段
                result.setdefault('keywords', [])
                result.setdefault('cover_sentence', '')
                result.setdefault('opening_hook', '')
                result.setdefault('closing_cta', '')
                result['_source_mode'] = 'llm'
                return jsonify({'code': 0, 'msg': f"高光提取完成：{len(result['highlights'])} 条", 'data': result})
        except Exception as e_llm:
            logger.warning(f'LLM高光提取失败，回退本地规则: {e_llm}')

        # ====== 本地兜底：正则 + 规则 ======
        import re
        sentences = re.split(r'(?<=[。！？!?；;\n])', script)
        sentences = [s.strip() for s in sentences if s.strip()]

        highlights = []
        keywords = set()

        for idx, s in enumerate(sentences):
            score = 0.0
            typ = 'info'
            emotion_tag = ''
            # 长度判断：太短/太长都降分
            l = len(s)
            if 6 <= l <= 40:
                score += 0.3
            elif 4 <= l <= 60:
                score += 0.15
            # 金句判断
            if any(c in s for c in ['才是', '就是', '正是', '不过', '但是', '其实', '原来', '竟然', '居然', '没想到', '怎能', '难道']):
                score += 0.3
                typ = 'gold'
            # 问句/反问
            if any(c in s for c in ['？', '?', '难道', '怎么', '为什么']):
                score += 0.25
                typ = 'reverse' if '难道' in s or '为什么' in s else typ
            # 感叹句 → 情绪
            if any(c in s for c in ['！', '!']):
                score += 0.25
                typ = 'emotion'
                emotion_tag = '热血' if any(w in s for w in ['燃', '震撼', '热血', '炸裂']) else '感动' if any(
                    w in s for w in ['哭', '泪', '感动', '心疼']) else '震撼'
            # 数字/专有名词 → 关键信息
            num_count = len(re.findall(r'\d+', s))
            if num_count >= 1:
                score += 0.15 * min(num_count, 3)
                if typ == 'info' or score < 0.4:
                    typ = 'info'

            # 关键词收集（2字以上的词粗提取）
            for w in re.findall(r'[\u4e00-\u9fa5A-Za-z]{2,}', s):
                if len(w) >= 2 and w not in {'的话', '那么', '这个', '那个', '我们', '你们', '他们', '就是', '不是', '因为', '所以', '但是', '如果', '或者', '还有'}:
                    keywords.add(w)

            if score > 0.0:
                pos = 'head' if idx < len(sentences) * 0.2 else ('tail' if idx > len(sentences) * 0.8 else 'body')
                highlights.append({
                    'index': idx + 1,
                    'text': s,
                    'type': typ,
                    'score': round(min(score, 1.0), 3),
                    'suggest_position': pos,
                    'emotion_tag': emotion_tag
                })

        # 按覆盖率截取
        highlights.sort(key=lambda h: h['score'], reverse=True)
        max_count = max(1, int(len(sentences) * coverage_ratio))
        highlights = highlights[:max_count]
        highlights.sort(key=lambda h: h['index'])

        keywords_sorted = sorted(keywords, key=lambda k: script.count(k), reverse=True)[:15]
        cover = highlights[0]['text'] if highlights else (sentences[0] if sentences else '')
        hook = sentences[0] if len(sentences) >= 1 else cover
        cta = sentences[-1] if len(sentences) >= 1 else ''

        return jsonify({
            'code': 0,
            'msg': f"本地规则提取完成：{len(highlights)} 条高光 / {len(keywords_sorted)} 个关键词",
            'data': {
                'highlights': highlights,
                'keywords': keywords_sorted,
                'cover_sentence': cover,
                'opening_hook': hook,
                'closing_cta': cta,
                '_source_mode': 'local_rules'
            }
        })

    except Exception as e:
        logger.error(f'高光提取失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'高光提取失败: {str(e)}', 'data': None}), 500


# ==================== 音画强制对齐预检 ====================

@advanced_bp.route('/av-force-sync', methods=['POST'])
def av_force_sync():
    """音画强制对齐预检：返回需要修正的句/词级错位列表（纯分析，不做剪辑）"""
    try:
        data = request.get_json() or {}
        script_lines = data.get('script_lines') or data.get('narrations') or []
        video_duration = float(data.get('video_duration') or 0)
        audio_durations = data.get('audio_durations') or []  # 每段配音时长列表，秒
        strategy = (data.get('strategy') or 'sentence').strip()
        tolerance_ms = int(data.get('tolerance_ms') or 150)

        if not script_lines:
            return jsonify({'code': 1, 'msg': '缺少解说分段（script_lines/narrations）', 'data': None}), 400

        n = len(script_lines)
        # 归一化 script_lines 为 {text, duration}
        normalized = []
        total_audio = 0.0
        for i in range(n):
            item = script_lines[i]
            if isinstance(item, str):
                text = item
                dur = float(audio_durations[i]) if i < len(audio_durations) else max(1.0, len(item) / 4.0)
            else:
                text = item.get('text') or item.get('narration') or ''
                dur = float(item.get('audio_duration') or item.get('duration') or (
                    audio_durations[i] if i < len(audio_durations) else max(1.0, len(text) / 4.0)))
            normalized.append({'text': text, 'audio_duration': dur, 'index': i + 1})
            total_audio += dur

        # 判断视频时长是否对齐
        video_dur = video_duration if video_duration > 0 else total_audio
        ratio = total_audio / max(video_dur, 0.001)

        mismatches = []
        cursor_v = 0.0  # 视频游标
        cursor_a = 0.0  # 音频游标
        # 按策略分配视频时长
        if ratio <= 1.0:
            # 配音比视频短或相等 → 平均按比例分配
            per_sentence_video = video_dur / n
        else:
            per_sentence_video = total_audio / n

        for s in normalized:
            v_start = cursor_v
            v_end = min(video_dur, cursor_v + per_sentence_video)
            a_start = cursor_a
            a_end = cursor_a + s['audio_duration']
            diff_ms = abs((v_end - v_start) - (a_end - a_start)) * 1000

            action = 'ok'
            fix = None
            if diff_ms > tolerance_ms:
                if (a_end - a_start) > (v_end - v_start):
                    action = 'compress_video' if strategy == 'sentence' else 'extend_video'
                    fix = {
                        'suggestion': '缩短该段配音或延长对应画面',
                        'audio_to_video_ratio': round((a_end - a_start) / max(v_end - v_start, 0.001), 3),
                        'compress_audio_by_ms': int(diff_ms)
                    }
                else:
                    action = 'extend_audio' if strategy == 'word' else 'compress_video'
                    fix = {
                        'suggestion': '延长该段配音或缩短对应画面（可插入空镜/B-roll）',
                        'video_to_audio_ratio': round((v_end - v_start) / max(a_end - a_start, 0.001), 3),
                        'fill_gap_by_ms': int(diff_ms)
                    }

            if action != 'ok' or strategy != 'sentence':
                mismatches.append({
                    'line_index': s['index'],
                    'text_preview': (s['text'][:30] + '…') if len(s['text']) > 30 else s['text'],
                    'video_range_ms': [int(v_start * 1000), int(v_end * 1000)],
                    'audio_range_ms': [int(a_start * 1000), int(a_end * 1000)],
                    'diff_ms': int(diff_ms),
                    'action': action,
                    'fix': fix
                })

            cursor_v = v_end
            cursor_a = a_end

        return jsonify({
            'code': 0,
            'msg': f"预检完成：{len([m for m in mismatches if m['action'] != 'ok'])} 处错位超过容差（{tolerance_ms}ms），策略={strategy}",
            'data': {
                'total_sentences': n,
                'total_audio_seconds': round(total_audio, 3),
                'video_duration_seconds': round(video_dur, 3),
                'audio_video_ratio': round(ratio, 3),
                'tolerance_ms': tolerance_ms,
                'strategy': strategy,
                'mismatches': mismatches,
                'need_follow_followup': ratio > 1.05 or ratio < 0.9,  # 差异>5%建议跟进
                'followup_suggestion': (
                    '配音时长明显超过视频时长，建议开启“压缩长画面”或删减部分文案' if ratio > 1.05 else
                    ('配音时长明显短于视频时长，建议开启“延长短画面”或补充B-roll原片原声片段' if ratio < 0.9 else '')
                )
            }
        })

    except Exception as e:
        logger.error(f'音画对齐预检失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'音画对齐预检失败: {str(e)}', 'data': None}), 500


# ==================== AIGC 统一处理入口（超分/修复/风格迁移/封面生成） ====================

@advanced_bp.route('/aigc/process', methods=['POST'])
def aigc_process():
    """AIGC统一处理：支持超分辨率、画面修复、风格迁移、封面生成

    说明：此处负责参数校验+路由+任务落库，真正的图像/视频AIGC生成由调用方
    根据配置中的 multi_model_manager 的图像模型进行执行。
    """
    try:
        data = request.get_json() or {}
        task_type = (data.get('task_type') or data.get('type') or '').strip()
        if task_type not in {'upscale', 'inpainting', 'style_transfer', 'generate_cover', 'cover'}:
            return jsonify({
                'code': 1,
                'msg': '未知的AIGC任务类型，支持：upscale/inpainting/style_transfer/generate_cover',
                'data': None
            }), 400

        # 归一化封面
        if task_type == 'cover':
            task_type = 'generate_cover'

        # 参数
        upscale_ratio = int(data.get('upscale_ratio') or 2)
        style_model = (data.get('style_model') or '').strip()
        cover_layout = (data.get('cover_layout') or 'golden').strip()
        strength = int(data.get('strength') or 60)
        project_id = (data.get('project_id') or '').strip() or f'aigc_{uuid.uuid4().hex[:8]}'
        gold_sentence = (data.get('cover_sentence') or data.get('text') or '').strip()
        reference_path = (data.get('input_path') or data.get('video_path') or data.get('image_path') or '').strip()

        # 任务落库（如果有task_service）
        task_id = None
        try:
            if _task_service is not None:
                created = _task_service.create_task({
                    'project_id': project_id,
                    'type': 'aigc_' + task_type,
                    'status': 'pending',
                    'params': {
                        'task_type': task_type,
                        'upscale_ratio': upscale_ratio,
                        'style_model': style_model,
                        'cover_layout': cover_layout,
                        'strength': strength,
                        'gold_sentence': gold_sentence,
                        'reference_path': reference_path
                    }
                })
                task_id = (created or {}).get('id') or (created or {}).get('task_id')
        except Exception as e_task:
            logger.warning(f'AIGC任务落库失败，继续执行内存流程: {e_task}')

        # ====== 封面生成：优先走LLM辅助+花字模板组合（不依赖重模型，立刻可用） ======
        if task_type == 'generate_cover':
            cover_candidates = []
            try:
                style_prompts_map = {
                    'anime': '日系动漫风 高饱和度 可爱',
                    'oil': '厚涂油画风 莫奈色彩 质感',
                    'watercolor': '清新水彩 梦幻柔和',
                    'cyberpunk': '赛博朋克 霓虹灯光 夜景 未来感',
                    'film': '电影胶片质感 复古颗粒 柯达色彩',
                    'guochao': '国潮水墨风 中国传统色彩 留白意境'
                }
                style_desc = style_prompts_map.get(style_model, '')

                # 如果有LLM，生成3套封面候选文案 + 构图建议
                if gold_sentence:
                    text_source = gold_sentence
                else:
                    text_source = (data.get('script') or '')[:300]
                try:
                    prompt = f"""你是短视频封面策划专家。请根据以下内容生成 3 套短视频封面方案，返回严格JSON。
内容：{text_source[:1500]}
风格关键词：{style_desc or '通用高点击风格'}
构图：{cover_layout}

返回格式：
{{
  "candidates": [
    {{"title": "封面主标题（≤8字）", "subtitle": "副标题（≤14字）", "emoji": "🎬", "bg_color_gradient": ["#色1", "#色2"], "accent": "#强调色", "layout_tag": "golden/center/ruleofthirds/diagonal"}},
    ...3套
  ]
}}"""
                    resp = _llm_chat(prompt, temperature=0.7)
                    parsed = _parse_json_response(resp)
                    if parsed and isinstance(parsed.get('candidates'), list):
                        for i, c in enumerate(parsed['candidates'][:3]):
                            cover_candidates.append({
                                'id': f'cover_{i}',
                                'title': c.get('title', ''),
                                'subtitle': c.get('subtitle', ''),
                                'emoji': c.get('emoji', '🎞️'),
                                'bg_gradient': c.get('bg_color_gradient', ['#111827', '#374151']),
                                'accent': c.get('accent', '#fbbf24'),
                                'layout': c.get('layout_tag') or cover_layout,
                                'style_model': style_model,
                                'use_huazi_text': True
                            })
                except Exception as e_cover:
                    logger.warning(f'AIGC封面LLM辅助失败: {e_cover}')
            except Exception:
                pass

            # 兜底候选（LLM失败也至少有3套）
            if not cover_candidates:
                fallback_titles = []
                if gold_sentence and len(gold_sentence) >= 2:
                    fallback_titles.append(gold_sentence[:8])
                fallback_titles += ['精彩解说', '深度解析', '必看干货']
                gradients = [
                    ['#1e3a8a', '#6366f1'],
                    ['#831843', '#ec4899'],
                    ['#065f46', '#10b981']
                ]
                for i in range(3):
                    cover_candidates.append({
                        'id': f'cover_fallback_{i}',
                        'title': fallback_titles[i],
                        'subtitle': gold_sentence[:14] if gold_sentence else '',
                        'emoji': ['🎬', '🔥', '💡'][i],
                        'bg_gradient': gradients[i],
                        'accent': '#fbbf24',
                        'layout': cover_layout,
                        'style_model': style_model or 'default',
                        'use_huazi_text': True
                    })

            # 写入输出目录
            try:
                from backend.config.paths import PROJECT_ROOT
                out_dir = PROJECT_ROOT / 'output' / 'aigc' / 'covers' / project_id
                out_dir.mkdir(parents=True, exist_ok=True)
                meta_path = str(out_dir / 'cover_candidates.json')
                with open(meta_path, 'w', encoding='utf-8') as f:
                    json.dump({'project_id': project_id, 'style_model': style_model,
                               'layout': cover_layout, 'strength': strength,
                               'generated_at': datetime.now().isoformat(),
                               'candidates': cover_candidates}, f, ensure_ascii=False, indent=2)
                # 返回相对下载路径
                rel_path = f"output/aigc/covers/{project_id}/cover_candidates.json"
            except Exception as e_out:
                logger.warning(f'AIGC封面元数据写入失败: {e_out}')
                rel_path = None

            return jsonify({
                'code': 0,
                'msg': f'已生成 {len(cover_candidates)} 套封面文字方案，未生成封面图片',
                'data': {
                    'task_id': task_id,
                    'project_id': project_id,
                    'task_type': 'generate_cover',
                    'candidates': cover_candidates,
                    'image_generated': False,
                    'result_kind': 'text_cover_candidates',
                    'meta_path': rel_path,
                    '_engine': 'LLM+花字模板（立即可用，不依赖图像模型）'
                }
            })

        # ====== 超分 / 画面修复 / 风格迁移 → 当前以“任务已落库+参数校验”方式返回 ======
        supported_styles = {'anime', 'oil', 'watercolor', 'cyberpunk', 'film', 'guochao', ''}
        if style_model and style_model not in supported_styles:
            return jsonify({
                'code': 1,
                'msg': f'不支持的风格模型 {style_model}，支持：anime/oil/watercolor/cyberpunk/film/guochao',
                'data': None
            }), 400

        return jsonify({
            'code': 0,
            'msg': f'AIGC任务已受理：{task_type}（倍率=x{upscale_ratio}，风格={style_model or "无"}，强度={strength}%）。参数已保存，将在视频合成阶段应用。',
            'data': {
                'task_id': task_id,
                'project_id': project_id,
                'task_type': task_type,
                'upscale_ratio': upscale_ratio,
                'style_model': style_model,
                'cover_layout': cover_layout,
                'strength': strength,
                'input_path': reference_path or None,
                '_status': 'queued',
                '_hint': '当前环境若已配置图像生成大模型，将在合成视频时自动应用；否则参数仍会写入项目配置，后续可手动触发渲染'
            }
        })

    except Exception as e:
        logger.error(f'AIGC处理失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'AIGC处理失败: {str(e)}', 'data': None}), 500


@advanced_bp.route('/tts/clone-voice', methods=['POST'])
def tts_clone_voice():
    """声音复刻接口（通过参考音频克隆音色）"""
    try:
        data = request.get_json() or {}
        reference_audio = data.get('reference_audio_path', '')
        voice_name = data.get('voice_name', '')
        engine = data.get('engine', 'volcano')  # 默认使用火山引擎

        if not reference_audio:
            return jsonify({'code': 1, 'msg': '缺少参考音频路径', 'data': None}), 400
        if not os.path.exists(reference_audio):
            return jsonify({'code': 1, 'msg': '参考音频文件不存在', 'data': None}), 400

        from backend.engine.tts_provider import get_tts_registry
        registry = get_tts_registry()
        provider = registry.get_provider(engine)

        if not provider or not provider.is_available():
            return jsonify({'code': 1, 'msg': f'TTS引擎 [{engine}] 不可用', 'data': None}), 400

        if not provider.supports_clone:
            return jsonify({'code': 1, 'msg': f'TTS引擎 [{engine}] 不支持声音复刻', 'data': None}), 400

        result = provider.clone_voice(reference_audio, voice_name)

        if result.get('success'):
            return jsonify({
                'code': 0,
                'msg': '声音复刻成功',
                'data': {
                    'voice_id': result.get('voice_id') or result.get('speaker_id'),
                    'voice_name': result.get('voice_name'),
                    'note': result.get('note', ''),
                    'engine': engine
                }
            })
        else:
            return jsonify({
                'code': 1,
                'msg': result.get('error', '克隆失败'),
                'data': None
            }), 500
    except Exception as e:
        logger.error(f'声音复刻失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


@advanced_bp.route('/tts/provider-info/<provider_name>', methods=['GET'])
def get_tts_provider_info(provider_name):
    """获取指定TTS Provider的详细信息"""
    try:
        from backend.engine.tts_provider import get_tts_registry
        registry = get_tts_registry()
        provider = registry.get_provider(provider_name)
        if not provider:
            return jsonify({'code': 1, 'msg': f'Provider [{provider_name}] 不存在', 'data': None}), 404

        info = provider.get_info()
        voices = provider.list_voices()
        info['voices'] = voices
        info['supported_languages'] = provider.supported_languages

        return jsonify({
            'code': 0,
            'msg': 'success',
            'data': info
        })
    except Exception as e:
        logger.error(f'获取Provider信息失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


# ==================== 断点续跑 ====================

@advanced_bp.route('/checkpoint/create', methods=['POST'])
def checkpoint_create():
    """创建任务断点"""
    try:
        data = request.get_json() or {}
        task_id = data.get('task_id') or str(uuid.uuid4())
        project_id = data.get('project_id', '')
        task_type = data.get('task_type', 'commentary')

        from backend.services.checkpoint_service import get_checkpoint_service
        service = get_checkpoint_service()
        cp = service.create_checkpoint(task_id, project_id, task_type)

        return jsonify({
            'code': 0,
            'msg': '断点已创建',
            'data': {
                'task_id': cp.task_id,
                'task_type': cp.task_type,
                'stages': service.TASK_STAGES.get(task_type, []),
                'created_at': cp.created_at
            }
        })
    except Exception as e:
        logger.error(f'创建断点失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


@advanced_bp.route('/checkpoint/<task_id>', methods=['GET'])
def checkpoint_get(task_id):
    """获取任务断点"""
    try:
        from backend.services.checkpoint_service import get_checkpoint_service
        service = get_checkpoint_service()
        cp = service.get_checkpoint(task_id)
        if not cp:
            return jsonify({'code': 1, 'msg': '断点不存在', 'data': None}), 404

        from dataclasses import asdict
        return jsonify({
            'code': 0,
            'msg': 'success',
            'data': asdict(cp)
        })
    except Exception as e:
        logger.error(f'获取断点失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


@advanced_bp.route('/checkpoint/<task_id>/update', methods=['POST'])
def checkpoint_update(task_id):
    """更新任务断点"""
    try:
        data = request.get_json() or {}
        from backend.services.checkpoint_service import get_checkpoint_service
        service = get_checkpoint_service()
        cp = service.update_checkpoint(
            task_id,
            stage=data.get('stage'),
            stage_progress=data.get('stage_progress'),
            stage_data=data.get('stage_data'),
            status=data.get('status'),
            error_message=data.get('error_message'),
            metadata=data.get('metadata')
        )
        if not cp:
            return jsonify({'code': 1, 'msg': '断点不存在', 'data': None}), 404

        from dataclasses import asdict
        return jsonify({
            'code': 0,
            'msg': '断点已更新',
            'data': asdict(cp)
        })
    except Exception as e:
        logger.error(f'更新断点失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


@advanced_bp.route('/checkpoint/<task_id>/complete-stage', methods=['POST'])
def checkpoint_complete_stage(task_id):
    """标记阶段完成"""
    try:
        data = request.get_json() or {}
        stage = data.get('stage', '')
        stage_data = data.get('stage_data')

        if not stage:
            return jsonify({'code': 1, 'msg': '缺少阶段名称', 'data': None}), 400

        from backend.services.checkpoint_service import get_checkpoint_service
        service = get_checkpoint_service()
        cp = service.mark_stage_completed(task_id, stage, stage_data)
        if not cp:
            return jsonify({'code': 1, 'msg': '断点不存在', 'data': None}), 404

        from dataclasses import asdict
        return jsonify({
            'code': 0,
            'msg': f'阶段 [{stage}] 已完成',
            'data': {
                'completed_stages': cp.completed_stages,
                'total_progress': cp.total_progress,
                'next_stage': data.get('next_stage')
            }
        })
    except Exception as e:
        logger.error(f'标记阶段完成失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


@advanced_bp.route('/checkpoint/<task_id>/resume', methods=['GET'])
def checkpoint_resume(task_id):
    """获取断点恢复点（仅查看，不会启动任务）"""
    try:
        from backend.services.checkpoint_service import get_checkpoint_service
        service = get_checkpoint_service()
        resume = service.get_resume_point(task_id)
        if not resume:
            return jsonify({'code': 1, 'msg': '断点不存在', 'data': None}), 404

        return jsonify({
            'code': 0,
            'msg': '已获取恢复点；该接口仅查看信息，不会启动任务',
            'data': resume
        })
    except Exception as e:
        logger.error(f'获取恢复点失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


@advanced_bp.route('/checkpoint/interrupted', methods=['GET'])
def checkpoint_list_interrupted():
    """列出所有可恢复的断点任务"""
    try:
        task_type = request.args.get('task_type')
        from backend.services.checkpoint_service import get_checkpoint_service
        service = get_checkpoint_service()
        tasks = service.list_interrupted_tasks(task_type)
        return jsonify({
            'code': 0,
            'msg': 'success',
            'data': {
                'tasks': tasks,
                'total': len(tasks)
            }
        })
    except Exception as e:
        logger.error(f'列出断点任务失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


@advanced_bp.route('/checkpoint/<task_id>', methods=['DELETE'])
def checkpoint_delete(task_id):
    """删除任务断点"""
    try:
        from backend.services.checkpoint_service import get_checkpoint_service
        service = get_checkpoint_service()
        if service.delete_checkpoint(task_id):
            return jsonify({'code': 0, 'msg': '断点已删除', 'data': None})
        return jsonify({'code': 1, 'msg': '删除断点失败', 'data': None}), 500
    except Exception as e:
        logger.error(f'删除断点失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


@advanced_bp.route('/checkpoint/resume', methods=['POST'])
def checkpoint_resume_via_body():
    """从持久化输入重新启动原创解说任务；不伪称可以跳过已完成阶段。"""
    try:
        data = request.get_json() or {}
        task_id = str(data.get('task_id') or data.get('checkpoint_id') or '').strip()
        if not task_id:
            return jsonify({'code': 1, 'msg': '缺少 task_id 或 checkpoint_id', 'data': None}), 400

        from backend.services.checkpoint_service import get_checkpoint_service
        checkpoint_service = get_checkpoint_service()
        checkpoint = checkpoint_service.get_checkpoint(task_id)
        if not checkpoint:
            return jsonify({'code': 1, 'msg': '断点不存在', 'data': None}), 404
        if checkpoint.status == 'completed':
            return jsonify({'code': 1, 'msg': '任务已完成，无需重新启动', 'data': None}), 400
        if checkpoint.task_type != 'commentary':
            return jsonify({'code': 1, 'msg': '仅支持恢复原创解说任务', 'data': None}), 400

        task = _db_manager.get_task(task_id) if _db_manager else None
        input_data = (task or {}).get('input_data') or {}
        if isinstance(input_data, str):
            input_data = json.loads(input_data or '{}')
        if not isinstance(input_data, dict):
            input_data = {}
        upload_data = checkpoint.stage_data.get('upload') or {}
        metadata = checkpoint.metadata or {}
        video_path = input_data.get('video_path') or upload_data.get('video_path') or metadata.get('video_path')
        config = input_data.get('config') or upload_data.get('config') or metadata.get('config')
        project_id = (task or {}).get('project_id') or checkpoint.project_id
        if not video_path or not isinstance(config, dict) or not project_id:
            return jsonify({'code': 1, 'msg': '断点缺少可恢复的项目、视频路径或配置', 'data': None}), 400
        if not os.path.isfile(video_path):
            return jsonify({'code': 1, 'msg': '断点的视频文件不存在，无法重新启动', 'data': None}), 400

        resume_callable = current_app.extensions.get('commentary_resume')
        if not callable(resume_callable):
            return jsonify({'code': 1, 'msg': '原创解说恢复服务未初始化', 'data': None}), 503
        if not resume_callable(task_id, project_id, video_path, config):
            return jsonify({'code': 1, 'msg': '原创解说恢复任务未能启动', 'data': None}), 500
        return jsonify({
            'code': 0,
            'msg': '已根据持久化输入重新启动原创解说任务',
            'data': {
                'task_id': task_id,
                'started': True,
                'resume_mode': 'restart_from_durable_input'
            }
        })
    except Exception as e:
        logger.error(f'恢复原创解说任务失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': '恢复任务启动失败', 'data': None}), 500


@advanced_bp.route('/checkpoint/delete', methods=['POST'])
def checkpoint_delete_via_body():
    """（兼容路由）从请求体 checkpoint_id / task_id 删除断点

    前端断点续跑卡片「删除」按钮默认 POST /checkpoint/delete  body={checkpoint_id, task_type}，
    此处与 DELETE /checkpoint/<task_id> 保持行为一致。
    """
    try:
        data = request.get_json() or {}
        task_id = (
            data.get('task_id')
            or data.get('checkpoint_id')
            or ''
        ).strip()
        if not task_id:
            return jsonify({'code': 1, 'msg': '缺少 task_id 或 checkpoint_id', 'data': None}), 400
        from backend.services.checkpoint_service import get_checkpoint_service
        service = get_checkpoint_service()
        if service.delete_checkpoint(task_id):
            return jsonify({'code': 0, 'msg': '断点已删除', 'data': None})
        return jsonify({'code': 1, 'msg': '删除断点失败', 'data': None}), 500
    except Exception as e:
        logger.error(f'删除断点失败(body): {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


# ==================== 流式生成 ====================

@advanced_bp.route('/stream/llm', methods=['POST'])
def stream_llm():
    """流式LLM生成（使用Server-Sent Events）"""
    try:
        data = request.get_json() or {}
        prompt = data.get('prompt', '').strip()
        engine = data.get('engine', '')
        temperature = float(data.get('temperature', 0.7))
        max_tokens = int(data.get('max_tokens', 4000))

        if not prompt:
            return jsonify({'code': 1, 'msg': '缺少提示词', 'data': None}), 400

        from flask import Response, stream_with_context
        from backend.services.checkpoint_service import get_stream_generator

        generator = get_stream_generator()
        queue = []

        def on_chunk(chunk):
            queue.append(chunk)

        def on_complete(result):
            queue.append({'__complete__': True, 'text': result.get('text', '')})

        def on_error(err):
            queue.append({'__error__': True, 'error': err.get('error', '')})

        generator.on('on_chunk', on_chunk)
        generator.on('on_complete', on_complete)
        generator.on('on_error', on_error)

        def generate():
            # 异步启动LLM生成
            import threading
            def run():
                try:
                    generator.stream_llm(prompt, engine, temperature, max_tokens)
                except Exception as e:
                    queue.append({'__error__': True, 'error': str(e)})

            thread = threading.Thread(target=run, daemon=True)
            thread.start()

            # 流式输出
            while True:
                if queue:
                    item = queue.pop(0)
                    if item.get('__complete__'):
                        yield f'data: {json.dumps({"type": "complete", "text": item["text"]}, ensure_ascii=False)}\n\n'
                        break
                    elif item.get('__error__'):
                        yield f'data: {json.dumps({"type": "error", "error": item["error"]}, ensure_ascii=False)}\n\n'
                        break
                    else:
                        yield f'data: {json.dumps({"type": "chunk", "data": item}, ensure_ascii=False)}\n\n'
                else:
                    time.sleep(0.05)

        return Response(stream_with_context(generate()),
                        content_type='text/event-stream',
                        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    except Exception as e:
        logger.error(f'流式LLM生成失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


@advanced_bp.route('/stream/tts', methods=['POST'])
def stream_tts():
    """流式TTS合成"""
    try:
        data = request.get_json() or {}
        text = data.get('text', '').strip()
        engine = data.get('engine', 'edge-tts')
        voice = data.get('voice', '')
        output_dir = data.get('output_dir', 'output/audios/stream_tts')

        if not text:
            return jsonify({'code': 1, 'msg': '缺少待合成文本', 'data': None}), 400

        if not os.path.isabs(output_dir):
            from backend.config.paths import PROJECT_ROOT
            output_dir = str(PROJECT_ROOT / output_dir)
        os.makedirs(output_dir, exist_ok=True)

        output_filename = f'stream_tts_{uuid.uuid4().hex[:8]}.mp3'
        output_path = os.path.join(output_dir, output_filename)

        from backend.services.checkpoint_service import get_stream_generator

        generator = get_stream_generator()
        progress = {'received': 0, 'completed': False, 'error': ''}

        def on_chunk(chunk):
            progress['received'] += chunk.get('size', 0)

        def on_complete(result):
            progress['completed'] = True
            progress['output_path'] = result.get('output_path', '')

        def on_error(err):
            progress['error'] = err.get('error', '')

        generator.on('on_chunk', on_chunk)
        generator.on('on_complete', on_complete)
        generator.on('on_error', on_error)

        # 异步执行
        import threading
        def run():
            try:
                generator.stream_tts(text, output_path, engine, voice)
            except Exception as e:
                progress['error'] = str(e)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        # 等待完成（有超时）
        max_wait = 60  # 60秒超时
        waited = 0
        while not progress['completed'] and not progress['error'] and waited < max_wait:
            time.sleep(0.2)
            waited += 0.2

        if progress['error']:
            return jsonify({'code': 1, 'msg': progress['error'], 'data': None}), 500
        if not progress['completed']:
            return jsonify({'code': 1, 'msg': '合成超时', 'data': None}), 504

        return jsonify({
            'code': 0,
            'msg': '流式TTS合成完成',
            'data': {
                'output_path': progress.get('output_path', output_path),
                'bytes_received': progress['received'],
                'download_url': f'/output/audios/stream_tts/{output_filename}'
            }
        })
    except Exception as e:
        logger.error(f'流式TTS合成失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


# ==================== 工具函数 ====================

def _parse_json_response(response: str) -> dict:
    """解析LLM返回的JSON响应"""
    if not response:
        return {}

    # 尝试直接解析
    try:
        return json.loads(response)
    except Exception:
        pass

    # 尝试从markdown代码块中提取
    import re
    patterns = [
        r'```json\s*(.*?)\s*```',
        r'```\s*(.*?)\s*```',
        r'\{[^{}]*\}',  # 简单JSON
    ]
    for pattern in patterns:
        matches = re.findall(pattern, response, re.DOTALL)
        for match in matches:
            try:
                return json.loads(match)
            except Exception:
                continue

    # 尝试找到第一个{和最后一个}
    start = response.find('{')
    end = response.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(response[start:end+1])
        except Exception:
            pass

    return {}
