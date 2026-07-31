#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : script_doctor.py
@Desc   : 文案质检模块 - 融入JJYB-ZJ的script_doctor功能
          六维评分系统 + 三套优化方案 + 实时诊断反馈
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class DiagnosisResult:
    """诊断结果数据结构"""
    overall_score: float = 0.0
    dimensions: Dict[str, float] = field(default_factory=dict)
    issues: List[Dict] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    optimization_plans: List[Dict] = field(default_factory=list)


class ScriptDoctor:
    """文案质检医生 - 六维评分和优化方案"""
    
    # 六维评分维度
    DIMENSIONS = {
        'hook_power': {
            'name': '开头吸引力',
            'desc': '前3秒是否能抓住观众注意力',
            'weight': 0.20,
            'scoring_criteria': {
                9: '开头有强冲突/悬念/反差，3秒内立即抓住注意力',
                7: '开头有吸引力，但不够强烈',
                5: '开头平淡，需要5秒以上才能进入主题',
                3: '开头冗长铺垫，观众容易流失',
                1: '开头毫无吸引力，无法留住观众'
            }
        },
        'rhythm_control': {
            'name': '节奏控制',
            'desc': '解说节奏是否紧凑有张力',
            'weight': 0.20,
            'scoring_criteria': {
                9: '节奏紧凑，每句都有信息量，无废话',
                7: '节奏较好，偶有冗余',
                5: '节奏一般，部分段落拖沓',
                3: '节奏松散，多处冗长',
                1: '节奏混乱，全程拖沓'
            }
        },
        'emotion_curve': {
            'name': '情绪曲线',
            'desc': '是否有起伏的情绪张力',
            'weight': 0.15,
            'scoring_criteria': {
                9: '情绪起伏明显，有高潮有低谷，张弛有度',
                7: '情绪有起伏，但不够强烈',
                5: '情绪平淡，缺少起伏',
                3: '情绪单一，全程一个调',
                1: '毫无情绪变化，枯燥乏味'
            }
        },
        'info_density': {
            'name': '信息密度',
            'desc': '每段是否都有有效信息',
            'weight': 0.15,
            'scoring_criteria': {
                9: '信息密度高，每句都推进剧情/主题',
                7: '信息密度较好，偶有重复',
                5: '信息密度一般，有重复内容',
                3: '信息密度低，多处重复',
                1: '信息密度极低，大量废话'
            }
        },
        'picture_match': {
            'name': '画面匹配度',
            'desc': '文案与画面是否同步',
            'weight': 0.15,
            'scoring_criteria': {
                9: '文案与画面高度同步，描述精准',
                7: '文案与画面基本匹配',
                5: '文案与画面有偏差',
                3: '文案与画面多处不符',
                1: '文案与画面严重不符'
            }
        },
        'completeness': {
            'name': '完整性',
            'desc': '故事是否完整，有无遗漏',
            'weight': 0.15,
            'scoring_criteria': {
                9: '故事完整，有开头-发展-高潮-结尾',
                7: '故事较完整，但某环节较弱',
                5: '故事不完整，缺少某环节',
                3: '故事残缺，多处跳跃',
                1: '故事支离破碎，无法理解'
            }
        }
    }
    
    # 诊断提示词
    DIAGNOSIS_PROMPT = """## 文案质检任务

你是一名专业的短视频文案质检员，需要对解说文案进行六维评分和问题诊断。

### 评分维度（每项1-10分）：
1. **开头吸引力**（权重20%）：前3秒能否抓住注意力
2. **节奏控制**（权重20%）：节奏是否紧凑有张力
3. **情绪曲线**（权重15%）：情绪是否有起伏
4. **信息密度**（权重15%）：每段是否有有效信息
5. **画面匹配度**（权重15%）：文案与画面是否同步
6. **完整性**（权重15%）：故事是否完整

### 待质检文案：
{script}

### 视频画面描述（可选）：
{video_description}

### 输出格式（严格JSON）：
{{
  "dimensions": {{
    "hook_power": {{"score": 0, "reason": "评分依据"}},
    "rhythm_control": {{"score": 0, "reason": "评分依据"}},
    "emotion_curve": {{"score": 0, "reason": "评分依据"}},
    "info_density": {{"score": 0, "reason": "评分依据"}},
    "picture_match": {{"score": 0, "reason": "评分依据"}},
    "completeness": {{"score": 0, "reason": "评分依据"}}
  }},
  "overall_score": 0.0,
  "issues": [
    {{"type": "问题类型", "location": "问题位置", "description": "问题描述", "severity": "high/medium/low"}}
  ],
  "suggestions": ["改进建议1", "改进建议2"]
}}"""
    
    # 三套优化方案提示词
    OPTIMIZATION_PROMPT = """## 文案优化方案生成

基于质检结果，为文案提供三套优化方案。

### 原始文案：
{script}

### 质检结果：
{diagnosis}

### 输出格式（严格JSON）：
{{
  "plans": [
    {{
      "name": "保守优化",
      "desc": "保持原有风格，只修复明显问题",
      "changes": ["修改点1", "修改点2"],
      "optimized_text": "优化后的完整文案"
    }},
    {{
      "name": "中度优化",
      "desc": "在保持原意的基础上提升节奏和吸引力",
      "changes": ["修改点1", "修改点2"],
      "optimized_text": "优化后的完整文案"
    }},
    {{
      "name": "深度重写",
      "desc": "保留核心信息，重新构思结构和表达",
      "changes": ["修改点1", "修改点2"],
      "optimized_text": "优化后的完整文案"
    }}
  ]
}}"""
    
    @classmethod
    def get_diagnosis_prompt(cls, script: str, video_description: str = '') -> str:
        """生成诊断提示词"""
        return cls.DIAGNOSIS_PROMPT.format(
            script=script,
            video_description=video_description or '（无视频描述）'
        )
    
    @classmethod
    def get_optimization_prompt(cls, script: str, diagnosis: str) -> str:
        """生成优化方案提示词"""
        return cls.OPTIMIZATION_PROMPT.format(
            script=script,
            diagnosis=diagnosis
        )
    
    @classmethod
    def calculate_overall_score(cls, dimensions: Dict[str, Dict]) -> float:
        """计算综合评分"""
        total = 0.0
        for key, config in cls.DIMENSIONS.items():
            if key in dimensions:
                score = dimensions[key].get('score', 5)
                total += score * config['weight']
        return round(total, 2)
    
    @classmethod
    def get_dimensions_info(cls) -> List[Dict]:
        """获取评分维度信息（用于前端展示）"""
        return [
            {
                'key': k,
                'name': v['name'],
                'desc': v['desc'],
                'weight': v['weight'],
                'max_score': 10
            }
            for k, v in cls.DIMENSIONS.items()
        ]


class ScriptMatcher:
    """LLM精排 - Top-K候选重排序，提升文案与视频匹配精度"""
    
    MATCH_PROMPT = """## 文案-视频场景精排任务

你是一名专业的视频剪辑师，需要为每段解说文案从候选场景中选择最匹配的视频片段。

### 解说文案列表：
{narrations}

### 候选视频场景列表（Top-K）：
{candidate_scenes}

### 匹配规则：
1. 文案内容必须与视频画面语义相关
2. 优先选择有动作、表情、场景切换的画面
3. 避免选择与文案完全无关的静态画面
4. 一个场景可以被多段文案使用，但相邻文案尽量不重复
5. 考虑时间连续性，避免大跨度跳跃

### 输出格式（严格JSON）：
{{
  "matches": [
    {{
      "narration_index": 0,
      "narration_text": "文案预览",
      "best_scene_id": 0,
      "best_scene_reason": "选择原因",
      "alternative_scene_ids": [1, 2],
      "confidence": 0.95
    }}
  ],
  "unmatched_narrations": [],
  "duplicate_warnings": []
}}"""
    
    @classmethod
    def get_match_prompt(cls, narrations: List[str], candidate_scenes: List[Dict]) -> str:
        """生成精排提示词"""
        return cls.MATCH_PROMPT.format(
            narrations='\n'.join([f'{i+1}. {n}' for i, n in enumerate(narrations)]),
            candidate_scenes='\n'.join([
                f'场景{s["id"]}: {s.get("description", "")} ({s.get("start", 0)}-{s.get("end", 0)}s)'
                for s in candidate_scenes
            ])
        )
