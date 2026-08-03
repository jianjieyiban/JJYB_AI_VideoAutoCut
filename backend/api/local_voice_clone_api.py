# -*- coding: utf-8 -*-
"""IndexTTS2 本地声音复刻 API。"""

import logging

from flask import Blueprint, current_app, jsonify, request

from backend.config.paths import PROJECT_ROOT
from backend.services.local_voice_clone_service import (
    LocalVoiceCloneError,
    local_voice_clone_service,
)

logger = logging.getLogger(__name__)

local_voice_clone_bp = Blueprint("local_voice_clone", __name__)


def register_local_voice_clone_routes(app, db_manager=None):
    """注册独立的 IndexTTS2 本地声音复刻接口。"""
    app.config["LOCAL_VOICE_CLONE_DB_MANAGER"] = db_manager
    app.register_blueprint(local_voice_clone_bp, url_prefix="/api/local-voice-clone")
    logger.info("本地声音复刻路由已注册")


def _response(code, message, data=None, status=200):
    return jsonify({"code": code, "msg": message, "data": data}), status


@local_voice_clone_bp.route("/health", methods=["GET"])
def health():
    return _response(0, "已获取本地声音复刻状态", local_voice_clone_service.status())


@local_voice_clone_bp.route("/voices", methods=["GET"])
def voices():
    status = local_voice_clone_service.status()
    return _response(0, "IndexTTS2 不提供预置音色；请上传已获授权的参考音频", {
        "status": status,
        "voices": [],
        "reference_audio_required": True,
    })


@local_voice_clone_bp.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _response(1, "请求必须为 JSON 对象", status=400)
    if data.get("consent") is not True:
        return _response(1, "必须明确确认已获得参考音频对应权利人的授权（consent=true）", status=403)

    text = data.get("text")
    reference_path = data.get("reference_audio") or data.get("reference_audio_path")
    if not isinstance(text, str) or not text.strip():
        return _response(1, "文本不能为空", status=400)
    if not reference_path:
        return _response(1, "必须提供参考音频", status=400)

    try:
        reference_audio = local_voice_clone_service.resolve_upload_audio(reference_path)
        result = local_voice_clone_service.generate(text, reference_audio)

        project_id = data.get("project_id")
        db_manager = current_app.config.get("LOCAL_VOICE_CLONE_DB_MANAGER")
        if project_id and db_manager:
            project = db_manager.get_project(project_id)
            if not project:
                return _response(1, "项目不存在，未保存复刻配音", status=404)
            output_file = PROJECT_ROOT / result["output_path"]
            material = db_manager.create_material(
                project_id=project_id,
                material_type="audio",
                name=output_file.name,
                path=result["output_path"],
                size=output_file.stat().st_size,
                metadata={
                    "engine": "IndexTTS2",
                    "device": result["device_used"],
                    "source": "local_voice_replication",
                },
            )
            result["material"] = material
        return _response(0, "IndexTTS2 生成完成", result)
    except LocalVoiceCloneError as exc:
        logger.warning("本地声音复刻请求未完成：%s", str(exc))
        return _response(1, str(exc), {
            "engine_requested": "IndexTTS2",
            "engine_used": None,
            "fallback": False,
        }, 422)
    except Exception:
        logger.exception("本地声音复刻请求发生未预期错误")
        return _response(1, "本地声音复刻生成失败", {
            "engine_requested": "IndexTTS2",
            "engine_used": None,
            "fallback": False,
        }, 500)


# 新增：/status 别名（对应前端 /api/local-voice-clone/status，也兼容老前缀）
@local_voice_clone_bp.route("/status", methods=["GET"])
def status_alias():
    engine_query = (request.args.get("engine") or "").lower()
    stat = local_voice_clone_service.status()
    extra = {}
    if engine_query and engine_query not in ("indextts2", "indextts", "index-tts2", ""):
        extra["engine"] = engine_query
        extra["reason"] = stat.get("reason") or f"当前引擎仅支持 IndexTTS2，不支持 {engine_query}"
    data = {**stat, **extra}
    return _response(0, "已获取 IndexTTS2 运行状态", data)


# 新增：/upload-train 上传参考音频并直接克隆（简化链路：上传文件→落盘→自动训练音色ID）
@local_voice_clone_bp.route("/upload-train", methods=["POST"])
def upload_and_train():
    """前端上传参考音频 -> 落盘到本地 -> 返回可直接作为 voice_id 使用的结果
    兼容前端 FormData: audio(file) / voice_name / source
    """
    try:
        from werkzeug.datastructures import FileStorage
        file = request.files.get('audio') or request.files.get('file')
        if not isinstance(file, FileStorage) or not file.filename:
            return _response(1, "请求缺少音频文件（字段名：audio）", status=400)

        voice_name = (request.form.get('voice_name') or 'user_clone_' + __import__('datetime').datetime.now().strftime('%Y%m%d%H%M%S')).strip()
        source_tag = (request.form.get('source') or 'commentary').strip()

        save_dir = PROJECT_ROOT / 'uploads' / 'voices' / source_tag
        save_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(ch for ch in file.filename if ch.isalnum() or ch in '-_. ')[:80] or 'ref.wav'
        save_path = save_dir / f"{voice_name}_{__import__('uuid').uuid4().hex[:6]}_{safe_name}"
        file.save(str(save_path))

        # 预调用一次 status 保证引擎可正常解析参考音频
        stat = local_voice_clone_service.status()
        # 返回一个直接可用的 voice_id（=保存的绝对路径，供 tts_engine._synthesize_indextts2 识别）
        voice_id = str(save_path.resolve())
        from backend.utils.file_utils import get_audio_duration_safe
        duration = 0.0
        try:
            duration = float(get_audio_duration_safe(str(save_path)) or 0.0)
        except Exception:
            duration = 0.0
        db_manager = current_app.config.get("LOCAL_VOICE_CLONE_DB_MANAGER")
        if db_manager:
            try:
                pid = request.form.get('project_id') or None
                if pid:
                    db_manager.create_material(
                        project_id=pid,
                        material_type="audio",
                        name=save_path.name,
                        path=str(save_path.relative_to(PROJECT_ROOT)).replace('\\', '/'),
                        size=save_path.stat().st_size,
                        metadata={"engine": "IndexTTS2", "voice_id": voice_id, "tag": "clone_reference"}
                    )
            except Exception:
                pass
        return _response(0, "参考音频上传成功，已生成音色ID", {
            "voice_id": voice_id,
            "name": voice_name,
            "duration_sec": round(duration, 2),
            "saved_path": str(save_path.relative_to(PROJECT_ROOT)).replace('\\', '/'),
            "absolute_path": str(save_path.resolve()),
            "engine_ready": stat.get('ready', False),
            "reason": stat.get('reason') or ''
        })
    except LocalVoiceCloneError as exc:
        return _response(1, str(exc), status=422)
    except Exception as e:
        logger.exception("上传参考音频失败")
        return _response(1, f"上传失败：{str(e)}", status=500)
