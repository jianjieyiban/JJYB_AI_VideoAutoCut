#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : checkpoint_service.py
@Desc   : 断点续跑服务 - 融入JJYB-ZJ的断点续跑能力
          任务执行过程中持久化进度，异常中断后可从断点继续
          支持LLM文稿生成、TTS配音、视频处理等多阶段任务的断点恢复
"""

import os
import json
import logging
import time
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
import threading

logger = logging.getLogger('JJYB_AI智剪')


@dataclass
class TaskCheckpoint:
    """任务断点"""
    task_id: str
    project_id: str = ''
    task_type: str = ''           # commentary / remix / voiceover / export
    current_stage: str = ''       # 当前阶段
    completed_stages: List[str] = field(default_factory=list)  # 已完成阶段
    stage_progress: Dict[str, float] = field(default_factory=dict)  # 各阶段进度
    stage_data: Dict[str, Any] = field(default_factory=dict)  # 各阶段数据快照
    created_at: str = ''
    updated_at: str = ''
    status: str = 'running'       # running / paused / completed / failed / interrupted
    error_message: str = ''
    total_progress: float = 0.0   # 总进度（0-100）
    metadata: Dict[str, Any] = field(default_factory=dict)


class CheckpointService:
    """断点续跑服务"""

    # 标准任务阶段定义
    TASK_STAGES = {
        'commentary': [
            'upload',           # 上传视频
            'segment',          # 智能分割
            'analyze',          # 视觉分析
            'script_generate',  # 文案生成
            'script_optimize',  # 文案优化
            'tts_generate',     # TTS配音
            'subtitle_align',   # 字幕对齐
            'video_compose',    # 视频合成
            'export'            # 导出
        ],
        'remix': [
            'upload',
            'segment',
            'config',
            'bgm_select',
            'beat_detect',
            'clip_plan',
            'tts_generate',
            'video_compose',
            'export'
        ],
        'voiceover': [
            'prepare',
            'tts_generate',
            'audio_post',
            'export'
        ]
    }

    def __init__(self, checkpoint_dir: Optional[str] = None):
        if checkpoint_dir:
            self.checkpoint_dir = Path(checkpoint_dir)
        else:
            from backend.config.paths import PROJECT_ROOT
            self.checkpoint_dir = PROJECT_ROOT / 'temp' / 'checkpoints'
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cache: Dict[str, TaskCheckpoint] = {}
        logger.info(f'断点续跑服务初始化完成，目录: {self.checkpoint_dir}')

    def _checkpoint_path(self, task_id: str) -> Path:
        """获取断点文件路径"""
        safe_id = ''.join(c for c in task_id if c.isalnum() or c in ('-', '_'))
        return self.checkpoint_dir / f'{safe_id}.json'

    def create_checkpoint(self, task_id: str, project_id: str = '',
                          task_type: str = 'commentary') -> TaskCheckpoint:
        """创建任务断点"""
        with self._lock:
            # A user may click "save checkpoint" while the task service is already
            # maintaining this task's checkpoint. Do not reset completed stages or the
            # durable resume payload in that situation.
            existing = self.get_checkpoint(task_id)
            if existing:
                if project_id and not existing.project_id:
                    existing.project_id = project_id
                if task_type and not existing.task_type:
                    existing.task_type = task_type
                existing.updated_at = datetime.now().isoformat()
                self._save(existing)
                return existing
            cp = TaskCheckpoint(
                task_id=task_id,
                project_id=project_id,
                task_type=task_type,
                created_at=datetime.now().isoformat(),
                updated_at=datetime.now().isoformat(),
                status='running'
            )
            self._save(cp)
            self._cache[task_id] = cp
            logger.info(f'任务断点已创建: {task_id} (type={task_type})')
            return cp

    def get_checkpoint(self, task_id: str) -> Optional[TaskCheckpoint]:
        """获取任务断点"""
        with self._lock:
            if task_id in self._cache:
                return self._cache[task_id]
            path = self._checkpoint_path(task_id)
            if not path.exists():
                return None
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                cp = TaskCheckpoint(**data)
                self._cache[task_id] = cp
                return cp
            except Exception as e:
                logger.error(f'加载断点失败: {task_id} - {e}')
                return None

    def update_checkpoint(self, task_id: str, stage: Optional[str] = None,
                          stage_progress: Optional[float] = None,
                          stage_data: Optional[Dict] = None,
                          status: Optional[str] = None,
                          error_message: Optional[str] = None,
                          metadata: Optional[Dict] = None) -> Optional[TaskCheckpoint]:
        """更新任务断点"""
        with self._lock:
            cp = self.get_checkpoint(task_id)
            if not cp:
                logger.warning(f'更新断点失败：{task_id} 不存在')
                return None

            if stage is not None:
                cp.current_stage = stage
            if stage_progress is not None:
                cp.stage_progress[cp.current_stage] = stage_progress
            if stage_data is not None:
                # 合并而非覆盖（保留历史快照）
                existing = cp.stage_data.get(cp.current_stage, {})
                existing.update(stage_data)
                cp.stage_data[cp.current_stage] = existing
            if status is not None:
                cp.status = status
            if error_message is not None:
                cp.error_message = error_message
            if metadata is not None:
                cp.metadata.update(metadata)

            cp.updated_at = datetime.now().isoformat()
            cp.total_progress = self._calculate_total_progress(cp)

            self._save(cp)
            return cp

    def mark_stage_completed(self, task_id: str, stage: str,
                              stage_data: Optional[Dict] = None) -> Optional[TaskCheckpoint]:
        """标记阶段完成"""
        with self._lock:
            cp = self.get_checkpoint(task_id)
            if not cp:
                return None
            if stage not in cp.completed_stages:
                cp.completed_stages.append(stage)
            cp.stage_progress[stage] = 100.0
            if stage_data:
                cp.stage_data[stage] = stage_data
            cp.updated_at = datetime.now().isoformat()
            cp.total_progress = self._calculate_total_progress(cp)
            self._save(cp)
            logger.info(f'任务 {task_id} 阶段 [{stage}] 完成，总进度 {cp.total_progress:.1f}%')
            return cp

    def get_resume_point(self, task_id: str) -> Optional[Dict]:
        """获取断点恢复点"""
        cp = self.get_checkpoint(task_id)
        if not cp:
            return None
        if cp.status == 'completed':
            return {'should_resume': False, 'reason': '任务已完成'}

        stages = self.TASK_STAGES.get(cp.task_type, [])
        if not stages:
            return {'should_resume': False, 'reason': f'未知任务类型: {cp.task_type}'}

        # 找到第一个未完成的阶段
        next_stage = None
        for stage in stages:
            if stage not in cp.completed_stages:
                next_stage = stage
                break

        if not next_stage:
            return {
                'should_resume': True,
                'reason': '所有阶段已完成但状态未标记完成',
                'next_stage': 'finalize',
                'checkpoint': asdict(cp)
            }

        return {
            'should_resume': True,
            'reason': f'从阶段 [{next_stage}] 继续',
            'next_stage': next_stage,
            'completed_stages': cp.completed_stages,
            'stage_progress': cp.stage_progress,
            'stage_data': cp.stage_data,
            'total_progress': cp.total_progress,
            'checkpoint': asdict(cp)
        }

    def list_interrupted_tasks(self, task_type: Optional[str] = None) -> List[Dict]:
        """列出所有可恢复的断点任务"""
        result = []
        for path in self.checkpoint_dir.glob('*.json'):
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if data.get('status') in ('running', 'interrupted', 'paused'):
                    if task_type and data.get('task_type') != task_type:
                        continue
                    result.append({
                        'task_id': data.get('task_id'),
                        'project_id': data.get('project_id'),
                        'task_type': data.get('task_type'),
                        'current_stage': data.get('current_stage'),
                        'completed_stages': data.get('completed_stages', []),
                        'total_progress': data.get('total_progress', 0),
                        'status': data.get('status'),
                        'updated_at': data.get('updated_at'),
                        'can_resume': True
                    })
            except Exception as e:
                logger.warning(f'读取断点文件失败: {path} - {e}')
        result.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
        return result

    def delete_checkpoint(self, task_id: str) -> bool:
        """删除任务断点"""
        with self._lock:
            path = self._checkpoint_path(task_id)
            if path.exists():
                try:
                    path.unlink()
                except Exception as e:
                    logger.error(f'删除断点失败: {task_id} - {e}')
                    return False
            if task_id in self._cache:
                del self._cache[task_id]
            return True

    def _calculate_total_progress(self, cp: TaskCheckpoint) -> float:
        """计算总进度"""
        stages = self.TASK_STAGES.get(cp.task_type, [])
        if not stages:
            return 0.0
        total = 0.0
        for stage in stages:
            if stage in cp.completed_stages:
                total += 100.0 / len(stages)
            elif stage in cp.stage_progress:
                total += cp.stage_progress[stage] / len(stages)
        return round(total, 1)

    def _save(self, cp: TaskCheckpoint) -> None:
        """保存断点"""
        path = self._checkpoint_path(cp.task_id)
        try:
            data = asdict(cp)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        except Exception as e:
            logger.error(f'保存断点失败: {cp.task_id} - {e}')
            raise


# 全局单例
_checkpoint_service: Optional[CheckpointService] = None


def get_checkpoint_service() -> CheckpointService:
    """获取断点续跑服务单例"""
    global _checkpoint_service
    if _checkpoint_service is None:
        _checkpoint_service = CheckpointService()
    return _checkpoint_service


# ==================== 流式生成辅助 ====================

class StreamGenerator:
    """流式生成辅助器 - 用于LLM流式输出和TTS流式合成"""

    def __init__(self):
        self.callbacks: Dict[str, List[Callable]] = {
            'on_start': [],
            'on_chunk': [],
            'on_complete': [],
            'on_error': []
        }

    def on(self, event: str, callback: Callable) -> 'StreamGenerator':
        """注册事件回调"""
        if event in self.callbacks:
            self.callbacks[event].append(callback)
        return self

    def emit(self, event: str, *args, **kwargs) -> None:
        """触发事件"""
        for cb in self.callbacks.get(event, []):
            try:
                cb(*args, **kwargs)
            except Exception as e:
                logger.error(f'流式回调异常 [{event}]: {e}')

    def stream_llm(self, prompt: str, engine: str = '',
                   temperature: float = 0.7, max_tokens: int = 4000) -> Any:
        """流式生成LLM文本"""
        self.emit('on_start', {'type': 'llm', 'engine': engine, 'prompt_length': len(prompt)})

        try:
            from backend.core.global_state import get_global_state
            gs = get_global_state()
            manager = gs.get_multi_model_manager()

            # 尝试调用支持流式的接口
            adapter = manager.get_adapter(engine) if engine else None
            if adapter is None:
                # 使用默认适配器
                if not engine and manager.config_manager:
                    engine = manager.config_manager.llm_config.default_model
                adapter = manager.get_adapter(engine)

            if adapter is None:
                raise RuntimeError(f'无法获取LLM适配器: {engine}')

            # 检查适配器是否支持流式
            stream_method = getattr(adapter, 'generate_text_stream', None) or \
                            getattr(adapter, 'stream_generate', None)

            full_text = ''
            if stream_method and callable(stream_method):
                # 使用流式接口
                for chunk in stream_method(prompt, temperature=temperature, max_tokens=max_tokens):
                    if isinstance(chunk, str):
                        full_text += chunk
                        self.emit('on_chunk', {'text': chunk, 'total_length': len(full_text)})
                    elif isinstance(chunk, dict) and 'text' in chunk:
                        full_text += chunk['text']
                        self.emit('on_chunk', chunk)
            else:
                # 适配器不支持流式，回退到普通调用并模拟流式输出
                logger.info(f'适配器 {engine} 不支持流式，使用回退方案')
                full_text = adapter.generate_text(prompt, temperature=temperature)
                # 模拟流式：按句子切分
                import re
                sentences = re.split(r'(?<=[。！？!?；;。\n])', full_text)
                for sentence in sentences:
                    if sentence.strip():
                        self.emit('on_chunk', {'text': sentence, 'total_length': len(full_text)})
                        time.sleep(0.05)  # 模拟延迟

            self.emit('on_complete', {'text': full_text, 'length': len(full_text)})
            return full_text
        except Exception as e:
            logger.error(f'流式LLM生成失败: {e}', exc_info=True)
            self.emit('on_error', {'error': str(e)})
            raise

    def stream_tts(self, text: str, output_path: str, engine: str = 'edge-tts',
                   voice: str = '', **kwargs) -> str:
        """流式TTS合成（边合成边输出）"""
        self.emit('on_start', {'type': 'tts', 'engine': engine, 'text_length': len(text)})
        try:
            from backend.engine.tts_provider import get_tts_registry, TTSRequest

            registry = get_tts_registry()
            provider = registry.get_provider(engine)

            if not provider or not provider.is_available():
                raise RuntimeError(f'TTS Provider [{engine}] 不可用')

            # 检查是否支持流式
            if provider.supports_streaming:
                # 真正的流式合成
                import asyncio

                async def _stream():
                    request = TTSRequest(
                        text=text, output_path=output_path, voice=voice, **kwargs
                    )
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    with open(output_path, 'wb') as f:
                        async for chunk in provider.synthesize_stream(request):
                            f.write(chunk)
                            self.emit('on_chunk', {'size': len(chunk)})

                asyncio.run(_stream())
            else:
                # 普通合成
                request = TTSRequest(
                    text=text, output_path=output_path, voice=voice, **kwargs
                )
                result = provider.synthesize(request)
                if not result.success:
                    raise RuntimeError(result.error)
                self.emit('on_chunk', {'size': result.file_size, 'duration': result.duration})

            self.emit('on_complete', {'output_path': output_path})
            return output_path
        except Exception as e:
            logger.error(f'流式TTS合成失败: {e}', exc_info=True)
            self.emit('on_error', {'error': str(e)})
            raise


# 全局流式生成器
_stream_generator: Optional[StreamGenerator] = None


def get_stream_generator() -> StreamGenerator:
    """获取流式生成器单例"""
    global _stream_generator
    if _stream_generator is None:
        _stream_generator = StreamGenerator()
    return _stream_generator
