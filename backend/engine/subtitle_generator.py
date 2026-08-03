#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : subtitle_generator.py
@Author : AI Assistant (基于NarratoAI + JJYB-ZJ学习)
@Date   : 2025-11-10
@Desc   : 智能字幕生成器
          支持从文案生成SRT字幕、时间戳对齐、字幕优化
          支持花字（样式化字幕）生成、ASS格式富文本字幕
"""

import os
import re
import json
from typing import List, Dict, Optional, Tuple
from datetime import timedelta
from loguru import logger


# ==================== 花字模板预设（对齐JJYB-ZJ的8套主流风格） ====================
FLOWER_TEMPLATES = {
    'neon': {
        'name': '霓虹花字',
        'primary_color': '&H008A3BFF',  # ABGR 紫粉
        'stroke_color': '&H00FFFFFF',   # 白描边
        'outline': 3,
        'shadow_color': '&H00000000',
        'shadow_depth': 2,
        'blur': 2,
        'bold': True,
        'fontsize': 48,
        'fontname': 'Microsoft YaHei',
        'animation_tag': r'\t(0,600,\fscx120\fscy120)\t(600,1200,\fscx100\fscy100)',
        'bg_box': True
    },
    'gold': {
        'name': '烫金质感',
        'primary_color': '&H0014F5FF',
        'stroke_color': '&H00B48A00',
        'outline': 3,
        'shadow_color': '&H00000000',
        'shadow_depth': 3,
        'blur': 1,
        'bold': True,
        'fontsize': 50,
        'fontname': 'Microsoft YaHei',
        'animation_tag': r'\fad(200,200)',
        'bg_box': True
    },
    'gradient': {
        'name': '渐变流光',
        'primary_color': '&H00FFFFFF',
        'stroke_color': '&H000080FF',
        'outline': 2,
        'shadow_color': '&H00000000',
        'shadow_depth': 2,
        'blur': 0,
        'bold': True,
        'fontsize': 46,
        'fontname': 'Microsoft YaHei',
        'animation_tag': r'\t(0,2000,\3c&HFF8000&)',
        'bg_box': False
    },
    'pop': {
        'name': '可爱气泡',
        'primary_color': '&H00FFFFFF',
        'stroke_color': '&H00D040FF',
        'outline': 4,
        'shadow_color': '&H00804080',
        'shadow_depth': 2,
        'blur': 1,
        'bold': True,
        'fontsize': 48,
        'fontname': 'Microsoft YaHei',
        'animation_tag': r'\t(0,400,\fscx120\fscy120)\t(400,800,\fscx100\fscy100)',
        'bg_box': True
    },
    'ink': {
        'name': '水墨国风',
        'primary_color': '&H00101010',
        'stroke_color': '&H00FFFFFF',
        'outline': 2,
        'shadow_color': '&H00606060',
        'shadow_depth': 2,
        'blur': 2,
        'bold': False,
        'fontsize': 46,
        'fontname': 'STXingkai',
        'animation_tag': r'\fad(500,500)',
        'bg_box': False
    },
    'tech': {
        'name': '科技电光',
        'primary_color': '&H00FFFF00',
        'stroke_color': '&H00FF0080',
        'outline': 2,
        'shadow_color': '&H000080FF',
        'shadow_depth': 3,
        'blur': 3,
        'bold': True,
        'fontsize': 46,
        'fontname': 'Consolas',
        'animation_tag': r'\t(0,500,\1c&H00FFFF&)\t(500,1000,\1c&HFF0080&)',
        'bg_box': False
    },
    'vintage': {
        'name': '复古胶片',
        'primary_color': '&H00E6D2B5',
        'stroke_color': '&H00202020',
        'outline': 3,
        'shadow_color': '&H00101010',
        'shadow_depth': 3,
        'blur': 1,
        'bold': False,
        'fontsize': 48,
        'fontname': 'SimSun',
        'animation_tag': r'\fad(300,300)',
        'bg_box': True
    },
    'simple': {
        'name': '极简高对比',
        'primary_color': '&H00FFFFFF',
        'stroke_color': '&H00000000',
        'outline': 4,
        'shadow_color': '&H00000000',
        'shadow_depth': 2,
        'blur': 0,
        'bold': True,
        'fontsize': 50,
        'fontname': 'Microsoft YaHei',
        'animation_tag': r'\fad(200,200)',
        'bg_box': False
    }
}


class SubtitleGenerator:
    """
    智能字幕生成器

    功能：
    1. 从解说文案生成SRT字幕
    2. 时间戳格式转换
    3. 字幕文本优化（断句、长度控制）
    4. 多语言支持
    5. 花字（样式化字幕）检测与生成
    6. ASS格式富文本字幕输出（支持样式/动画/位置）
    7. 金句/数字/情绪词/专有名词自动识别并套用花字
    """

    def __init__(self):
        """初始化字幕生成器"""
        self.max_chars_per_line = 20  # 每行最多字符数
        self.max_lines = 2             # 最多行数
        # 花字默认配置（可被外部覆盖）
        self.default_flower_config = {
            'enabled': True,
            'scope': 'intro10',      # intro10 / selective / full
            'frequency': 'medium',   # low / medium / high
            'detect_emotion': True,
            'detect_number': True,
            'detect_proper_noun': True,
            'detect_gold': True,
            'keyword_emphasize': True,
            'top_keywords': 8,
            'force_keywords': [],
            'block_keywords': [],
            'template': 'neon',
            'primary_color': None,
            'stroke_color': None,
            'shadow_color': None,
            'glow_color': None,
            'position': 'bottom',   # top / center / bottom / custom
            'animation': 'bounce',
            'jianying_track': True,
            'per_text_layer': True,
            'export_ass': True,
            'cover_gold': True,
            'sound_effects_enabled': False,
            'sound_effect_volume': 0.18,
            'sound_effect_cooldown_ms': 600,
            # 旧配置键兼容；新配置键优先。
            'flower_sfx_enabled': False,
            'flower_sfx_volume': 0.18,
            'flower_sfx_cooldown_ms': 600,
            'flower_sfx_mapping': {}
        }
        # 情绪词词典
        self.emotion_words = [
            '太香了', '绝了', '超棒', '必看', 'yyds', '震撼', '炸裂', '爆燃', '感动', '心疼',
            '卧槽', '我去', '牛啊', '离谱', '惊艳', '惊艳全场', '泪目', '哭了', '热血', '高能',
            '警告', '注意', '关键', '重要', '核心', '重点', '压轴', '王炸', '高潮', '反转'
        ]
        # 专有名词粗匹配正则
        self.proper_noun_patterns = [
            r'[\u4e00-\u9fa5]{2,4}(?:菜|饭|面|汤|酱|肉|鱼|鸡|鸭|牛|羊|猪|海鲜)',  # 菜名
            r'[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*',  # 英文专有名词
            r'《[^》]+》'  # 书名号内容
        ]
        logger.info("SubtitleGenerator初始化完成（含花字+ASS支持）")

    def generate_srt_from_script(self, narration_script: Dict, output_path: str) -> str:
        """
        从解说文案生成SRT字幕

        Args:
            narration_script: 解说文案数据
                {
                    "narrations": [
                        {"time_range": "00:00:00-00:00:05", "text": "文本..."},
                        ...
                    ]
                }
            output_path: 输出SRT文件路径

        Returns:
            SRT文件路径
        """
        logger.info("开始生成SRT字幕")

        narrations = narration_script.get('narrations', [])
        if not narrations:
            logger.warning("解说文案为空，无法生成字幕")
            return None

        srt_content = []

        for i, narration in enumerate(narrations, start=1):
            time_range = narration.get('time_range', '00:00:00-00:00:05')
            text = narration.get('text', '')

            # 解析时间范围
            start_time, end_time = self._parse_time_range(time_range)

            # 优化文本（断句）
            optimized_text = self._optimize_subtitle_text(text)

            # 生成SRT条目
            srt_entry = self._create_srt_entry(i, start_time, end_time, optimized_text)
            srt_content.append(srt_entry)

        # 写入文件
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n\n'.join(srt_content))

        logger.success(f"✅ SRT字幕生成完成: {output_path}")
        return output_path

    def _parse_time_range(self, time_range: str) -> tuple:
        """
        解析时间范围字符串

        Args:
            time_range: "00:00:00-00:00:05" 或 "0.0s-5.0s"

        Returns:
            (start_time_str, end_time_str) SRT格式时间戳
        """
        # 处理秒数格式（例如：0.0s-5.0s）
        if 's' in time_range:
            parts = time_range.replace('s', '').split('-')
            start_seconds = float(parts[0])
            end_seconds = float(parts[1])

            start_time_str = self._seconds_to_srt_time(start_seconds)
            end_time_str = self._seconds_to_srt_time(end_seconds)
        else:
            # 处理时间戳格式（例如：00:00:00-00:00:05）
            parts = time_range.split('-')
            start_time_str = self._convert_to_srt_time(parts[0].strip())
            end_time_str = self._convert_to_srt_time(parts[1].strip())

        return start_time_str, end_time_str

    def _seconds_to_srt_time(self, seconds: float) -> str:
        """
        将秒数转换为SRT时间格式

        Args:
            seconds: 秒数

        Returns:
            SRT格式时间戳 "HH:MM:SS,mmm"
        """
        total = float(seconds)
        # 使用“乘1000加0.5再取整”的方式避免浮点和banker rounding问题
        total_ms = int(total * 1000 + 0.5)
        total_secs, milliseconds = divmod(total_ms, 1000)
        hours = total_secs // 3600
        minutes = (total_secs % 3600) // 60
        secs = total_secs % 60
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

    def _convert_to_srt_time(self, time_str: str) -> str:
        """
        转换时间字符串为SRT格式

        Args:
            time_str: "HH:MM:SS" 或 "HH:MM:SS.mmm"

        Returns:
            SRT格式 "HH:MM:SS,mmm"
        """
        # 将.替换为,（SRT使用逗号）
        srt_time = time_str.replace('.', ',')

        # 确保有毫秒部分
        if ',' not in srt_time:
            srt_time += ',000'

        return srt_time

    def _optimize_subtitle_text(self, text: str) -> str:
        """字幕文本规整：横排优先，超长时分两行字数尽量接近（平衡断句），避免长短不齐。"""
        if not text:
            return ''
        # 移除多余空白
        text = re.sub(r'\s+', '', text)

        # （1）单条字幕单行优先（横排），<= 16 字（默认 max_chars_per_line 常用值为18~22，这里稍微保守点）
        max_len = max(10, int(getattr(self, 'max_chars_per_line', 0) or 18))
        if len(text) <= max_len:
            return text

        # （2）按标点分句：(，。！？；：,.!?;:)
        sep_re = r'([，。！？、；：,.!?;:])'
        split_parts = re.split(sep_re, text)
        # 合并"分句 + 紧跟标点"作为一个块
        blocks: List[str] = []
        for i in range(0, len(split_parts), 2):
            chunk = split_parts[i]
            pun = split_parts[i + 1] if i + 1 < len(split_parts) else ''
            if chunk or pun:
                blocks.append((chunk or '') + (pun or ''))
        # 如果分不出块（没有任何标点），退化到纯字数平分
        if len(blocks) <= 1:
            mid = len(text) // 2
            # 尝试在 mid±3 范围找最小字节差的切点（中文字保证左右差 <= 4）
            best = mid
            best_diff = abs(len(text[:mid]) - len(text[mid:]))
            for k in range(max(3, max_len // 3), len(text) - 3):
                d = abs(k - (len(text) - k))
                if d < best_diff:
                    best_diff = d; best = k
                if best_diff <= 1:
                    break
            return (text[:best] + '\n' + text[best:]).strip('\n')

        # （3）贪心累积：每行尽量接近 总行数一半
        max_lines = max(2, int(getattr(self, 'max_lines', 0) or 2))
        # 只在 2 行时做平衡分行（max_lines>2 时保持原策略）
        if max_lines >= 2 and len(text) > max_len:
            target_half = len(text) / 2
            best_split_point = None
            best_split_diff = float('inf')
            cursor = 0
            for bi, block in enumerate(blocks[:-1]):
                cursor += len(block)
                diff = abs(cursor - target_half)
                # 单行不能超过 max_len*1.1（否则宁可继续堆）
                if cursor <= int(max_len * 1.08) and diff < best_split_diff:
                    best_split_diff = diff
                    best_split_point = bi
            if best_split_point is not None and best_split_diff <= len(text) * 0.22:
                line1 = ''.join(blocks[:best_split_point + 1])
                line2 = ''.join(blocks[best_split_point + 1:])
                # 平衡兜底：若某行还超过 max_len * 1.3，退化裁剪（通常不会发生）
                if len(line1) > int(max_len * 1.35):
                    line1 = line1[:int(max_len * 1.2)]
                if len(line2) > int(max_len * 1.35):
                    line2 = line2[:int(max_len * 1.2)]
                # 字数差 > 6 的再尝试：把 line1 末尾的 1 个短句块挪给 line2（或反向）
                if abs(len(line1) - len(line2)) > 6 and blocks:
                    # 差异大时放弃标点块，改成纯字数平分
                    mid = len(text) // 2
                    # 在 mid±3 附近找标点作为最佳切（避免切断词语）
                    offset_map = {}
                    for delta in range(-6, 7):
                        p = min(max(3, mid + delta), len(text) - 3)
                        if text[p - 1] in '，。！？、；：,.!?;:':
                            # 刚好切在标点之后（标点放上行）
                            offset_map[abs(p - mid) + (0 if abs(delta) <= 3 else 1)] = p
                    if offset_map:
                        pick = offset_map[min(offset_map.keys())]
                        line1, line2 = text[:pick], text[pick:]
                    else:
                        line1, line2 = text[:mid], text[mid:]
                return (line1.rstrip() + '\n' + line2.lstrip()).strip('\n')

        # （4）退化：沿用原始 accum 策略按 max_chars_per_line 堆行（3行及以上）
        lines: List[str] = []
        current = ''
        for block in blocks:
            if len(current + block) <= max_len:
                current += block
            else:
                if current:
                    lines.append(current)
                current = block
        if current:
            lines.append(current)
        if len(lines) > max_lines:
            # 合并最后超出的行到最后一行
            merged = ''.join(lines[max_lines - 1:])
            lines = lines[:max_lines - 1] + [merged]
        return '\n'.join(lines[:max_lines])

    def _create_srt_entry(self, index: int, start_time: str, end_time: str, text: str) -> str:
        """
        创建SRT条目

        Args:
            index: 序号
            start_time: 开始时间
            end_time: 结束时间
            text: 字幕文本

        Returns:
            SRT格式条目
        """
        return f"{index}\n{start_time} --> {end_time}\n{text}"

    def merge_srt_files(self, srt_files: List[str], output_path: str) -> str:
        """
        合并多个SRT文件

        Args:
            srt_files: SRT文件路径列表
            output_path: 输出文件路径

        Returns:
            合并后的SRT文件路径
        """
        logger.info(f"开始合并{len(srt_files)}个SRT文件")

        all_entries = []

        for srt_file in srt_files:
            with open(srt_file, 'r', encoding='utf-8') as f:
                content = f.read()
                all_entries.append(content)

        # 合并并重新编号
        merged_content = '\n\n'.join(all_entries)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(merged_content)

        logger.success(f"✅ SRT文件合并完成: {output_path}")
        return output_path

    # ==================== 花字：关键词检测 ====================

    def detect_flower_spans(self, text: str, flower_config: Optional[Dict] = None) -> List[Dict]:
        """
        在一行字幕文本中检测需要花字处理的片段
        返回列表：[{"start": int, "end": int, "text": str, "type": "number|emotion|proper|gold|keyword", "score": float}]
        """
        cfg = dict(self.default_flower_config, **(flower_config or {}))
        if not cfg.get('enabled'):
            return []
        spans = []
        used_ranges = []

        def _add_span(s, e, t, typ, score):
            # 避免重叠
            for us, ue in used_ranges:
                if not (e <= us or s >= ue):
                    return
            spans.append({'start': s, 'end': e, 'text': t, 'type': typ, 'score': score})
            used_ranges.append((s, e))

        # 1) 强制关键词
        force_words = cfg.get('force_keywords') or []
        if isinstance(force_words, str):
            force_words = [w.strip() for w in re.split(r'[,，\s]+', force_words) if w.strip()]
        block_words = cfg.get('block_keywords') or []
        if isinstance(block_words, str):
            block_words = [w.strip() for w in re.split(r'[,，\s]+', block_words) if w.strip()]

        for w in force_words:
            for m in re.finditer(re.escape(w), text):
                _add_span(m.start(), m.end(), m.group(), 'keyword', 0.99)
        # 2) 数字（带单位优先）
        if cfg.get('detect_number'):
            for m in re.finditer(r'\d+(?:\.\d+)?(?:秒|分|小时|分钟|克|kg|g|ml|元|块|天|年|个月|周|次|人|%)?', text):
                _add_span(m.start(), m.end(), m.group(), 'number', 0.85)
        # 3) 情绪词
        if cfg.get('detect_emotion'):
            for w in self.emotion_words:
                for m in re.finditer(re.escape(w), text):
                    _add_span(m.start(), m.end(), m.group(), 'emotion', 0.8)
        # 4) 专有名词（菜名等）
        if cfg.get('detect_proper_noun'):
            for pat in self.proper_noun_patterns:
                for m in re.finditer(pat, text):
                    _add_span(m.start(), m.end(), m.group(), 'proper', 0.75)
        # 5) 屏蔽词过滤
        if block_words:
            spans = [s for s in spans if s['text'] not in block_words and not any(b in s['text'] for b in block_words)]
        # 按频率裁剪
        freq = cfg.get('frequency') or 'medium'
        max_spans = {'low': 1, 'medium': 3, 'high': 99}.get(freq, 3)
        spans.sort(key=lambda x: x['score'], reverse=True)
        spans = spans[:max_spans]
        spans.sort(key=lambda x: x['start'])
        return spans

    def _resolve_flower_template(self, flower_config: Dict) -> Dict:
        """解析花字模板 + 用户自定义颜色覆盖"""
        cfg = dict(self.default_flower_config, **(flower_config or {}))
        tpl_name = cfg.get('template') or 'neon'
        tpl = dict(FLOWER_TEMPLATES.get(tpl_name) or FLOWER_TEMPLATES['neon'])
        # 用户自定义颜色覆盖（#RRGGBB -> ASS &HAABBGGRR）
        def _hex_to_ass(hex_color: str, alpha='00') -> str:
            if not hex_color or not hex_color.startswith('#') or len(hex_color) < 7:
                return None
            r, g, b = hex_color[1:3], hex_color[3:5], hex_color[5:7]
            return f"&H{alpha}{b}{g}{r}"
        user_pri = _hex_to_ass(cfg.get('primary_color') or '')
        user_strk = _hex_to_ass(cfg.get('stroke_color') or '')
        user_sha = _hex_to_ass(cfg.get('shadow_color') or '')
        user_glow = _hex_to_ass(cfg.get('glow_color') or '', alpha='40')
        if user_pri: tpl['primary_color'] = user_pri
        if user_strk: tpl['stroke_color'] = user_strk
        if user_sha: tpl['shadow_color'] = user_sha
        return tpl

    # ==================== 花字：应用到一行文本 -> ASS 标签包裹 ====================

    def wrap_flower_ass(self, plain_line: str, flower_config: Optional[Dict] = None,
                        line_index: int = 0, total_lines: int = 1) -> Tuple[str, List[Dict]]:
        """
        对一行字幕文本：检测花字词 -> 用ASS override标签包裹
        返回：(ass_line_text, used_flower_meta_list)
        """
        cfg = dict(self.default_flower_config, **(flower_config or {}))
        meta = []
        if not cfg.get('enabled'):
            return plain_line, meta
        # 范围判定：intro10=仅片头10行，selective=按分数，full=全部
        scope = cfg.get('scope') or 'intro10'
        if scope == 'intro10' and line_index >= 10:
            return plain_line, meta
        spans = self.detect_flower_spans(plain_line, cfg)
        if not spans:
            return plain_line, meta
        tpl = self._resolve_flower_template(cfg)
        # 按位置构造
        ass_line = []
        cursor = 0
        open_tag = (
            r'{'
            + rf'\c{tpl["primary_color"]}'
            + rf'\3c{tpl["stroke_color"]}'
            + rf'\4c{tpl.get("glow_color") or tpl["shadow_color"]}'
            + rf'\bord{tpl["outline"]}'
            + rf'\shad{tpl["shadow_depth"]}'
            + (r'\b1' if tpl['bold'] else r'\b0')
            + rf'\blur{tpl["blur"]}'
            + rf'\fn{tpl["fontname"]}\fs{tpl["fontsize"]}'
            + (tpl.get('animation_tag') or '')
            + r'}'
        )
        close_tag = r'{\r}'
        for sp in spans:
            ass_line.append(plain_line[cursor:sp['start']])
            ass_line.append(open_tag + sp['text'] + close_tag)
            cursor = sp['end']
            meta.append({
                'text': sp['text'], 'type': sp['type'], 'score': sp['score'],
                'template': cfg.get('template'), 'line_index': line_index
            })
        ass_line.append(plain_line[cursor:])
        return ''.join(ass_line), meta

    # ==================== 生成完整 ASS 字幕文件（含样式+花字） ====================

    def generate_ass_from_script(self, narration_script: Dict, output_path: str,
                                  flower_config: Optional[Dict] = None,
                                  video_width: int = 1920, video_height: int = 1080) -> Dict:
        """
        从解说文案生成带花字的ASS字幕
        返回：{'ass_path': str, 'flower_meta_list': [...], 'summary': {...}}
        """
        cfg = dict(self.default_flower_config, **(flower_config or {}))
        narrations = narration_script.get('narrations', [])
        if not narrations:
            logger.warning("解说文案为空，无法生成ASS字幕")
            return {'ass_path': None, 'flower_meta_list': [], 'summary': {}}
        tpl = self._resolve_flower_template(cfg)
        position = cfg.get('position') or 'bottom'
        # 定位：Alignment=2底部, 8顶部, 5居中
        alignment_map = {'bottom': 2, 'top': 8, 'center': 5, 'custom': 2}
        alignment = alignment_map.get(position, 2)
        # 统一横排 + 底部安全区：margin_v 加大到 70 左右（避免被台标/进度条遮挡），line_max_width 放宽到 0.88
        margin_v = max(54, int(margin_v) if isinstance(margin_v, (int, float)) else 70)
        if position == 'bottom':
            margin_v = max(margin_v, 74)
        # 写ASS头
        header_lines = [
            '[Script Info]',
            'Title: JJYB_AI智剪 - 花字字幕',
            'ScriptType: v4.00+',
            'WrapStyle: 0',
            'PlayResX: %d' % video_width,
            'PlayResY: %d' % video_height,
            'ScaledBorderAndShadow: yes',
            '',
            '[V4+ Styles]',
            'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
        ]
        # 基础字幕样式
        base_style = (
            f'Style: Default,Microsoft YaHei,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,'
            f'-1,0,0,0,100,100,0,0,1,3,2,{alignment},40,40,{margin_v},1'
        )
        # 花字样式（基于模板）
        flower_style = (
            f'Style: Flower,{tpl["fontname"]},{tpl["fontsize"]},{tpl["primary_color"]},&H000000FF,'
            f'{tpl["stroke_color"]},{tpl["shadow_color"]},'
            f'{1 if tpl["bold"] else 0},0,0,0,100,100,0,0,'
            f'{1 if tpl.get("bg_box") else 3},{tpl["outline"]},{tpl["shadow_depth"]},{alignment},40,40,{margin_v},1'
        )
        header_lines += [base_style, flower_style, '', '[Events]',
                         'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
        # 逐行生成事件
        events = []
        all_flower_meta = []
        for i, nar in enumerate(narrations):
            time_range = nar.get('time_range', '00:00:00-00:00:05')
            text = nar.get('text', '')
            start_s, end_s = self._parse_time_range_seconds(time_range)
            start_ass = self._seconds_to_ass_time(start_s)
            end_ass = self._seconds_to_ass_time(end_s)
            # 基础行
            optimized = self._optimize_subtitle_text(text)
            # 花字应用
            ass_text_parts = []
            line_meta_accum = []
            sub_lines = optimized.split('\n')
            for li, sl in enumerate(sub_lines):
                wline, meta = self.wrap_flower_ass(sl, cfg, line_index=i, total_lines=len(narrations))
                ass_text_parts.append(wline)
                line_meta_accum.extend(meta)
            ass_text = r'\N'.join(ass_text_parts)
            all_flower_meta.extend(line_meta_accum)
            # 若有花字，用Flower样式；否则Default
            style_used = 'Flower' if line_meta_accum else 'Default'
            layer = 1 if line_meta_accum else 0
            events.append(
                f'Dialogue: {layer},{start_ass},{end_ass},{style_used},,0,0,0,,{ass_text}'
            )
        # 落盘
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8-sig') as f:
            f.write('\n'.join(header_lines + events) + '\n')
        summary = {
            'total_lines': len(narrations),
            'flower_lines': len(set(m['line_index'] for m in all_flower_meta)),
            'flower_count': len(all_flower_meta),
            'template': cfg.get('template'),
            'scope': cfg.get('scope'),
            'frequency': cfg.get('frequency')
        }
        logger.success(f"✅ ASS花字字幕生成完成: {output_path} | {summary}")
        return {'ass_path': output_path, 'flower_meta_list': all_flower_meta, 'summary': summary}

    # ==================== 花字：剪映草稿用独立轨道数据 ====================

    def build_jianying_flower_track(self, narration_script: Dict, flower_config: Optional[Dict] = None) -> Dict:
        """
        生成剪映草稿导入用的「花字独立轨道」描述数据
        返回 JSON 可序列化结构，包含每一处花字的位置、时间、样式
        """
        cfg = dict(self.default_flower_config, **(flower_config or {}))
        narrations = narration_script.get('narrations', [])
        tpl = self._resolve_flower_template(cfg)
        track_items = []
        for i, nar in enumerate(narrations):
            time_range = nar.get('time_range', '00:00:00-00:00:05')
            start_s, end_s = self._parse_time_range_seconds(time_range)
            text = nar.get('text', '')
            spans = self.detect_flower_spans(text, cfg)
            if cfg.get('scope') == 'intro10' and i >= 10:
                spans = []
            for sp in spans:
                # 每段花字独立一条（对应per_text_layer=True），或合并
                item = {
                    'id': f'flower_{i}_{sp["start"]}',
                    'track_type': 'flower_text',
                    'text': sp['text'],
                    'type': sp['type'],
                    'score': sp['score'],
                    'time_start_ms': int(start_s * 1000),
                    'time_end_ms': int(end_s * 1000),
                    'template': cfg.get('template'),
                    'style': {
                        'fontname': tpl['fontname'],
                        'fontsize': tpl['fontsize'],
                        'bold': tpl['bold'],
                        'primary_color': cfg.get('primary_color') or '#ffffff',
                        'stroke_color': cfg.get('stroke_color') or '#000000',
                        'outline': tpl['outline'],
                        'shadow': tpl['shadow_depth'],
                        'blur': tpl['blur'],
                        'animation': cfg.get('animation') or 'bounce',
                        'position': cfg.get('position') or 'bottom',
                        'bg_box': tpl.get('bg_box', False)
                    }
                }
                track_items.append(item)
        try:
            from backend.utils.flower_sfx import build_flower_sfx_items
            flower_sfx = build_flower_sfx_items(track_items, cfg)
        except Exception as exc:
            logger.warning('花字音效构建失败，已跳过: %s', exc)
            flower_sfx = []
        logger.info(f"✅ 剪映花字轨道构建完成，共 {len(track_items)} 处花字，音效 {len(flower_sfx)} 个")
        return {
            'enabled': cfg.get('enabled', True),
            'per_text_layer': cfg.get('per_text_layer', True),
            'jianying_track': cfg.get('jianying_track', True),
            'items': track_items,
            'flower_sfx': flower_sfx
        }

    # ==================== 辅助：秒 -> ASS 时间格式 ====================

    @staticmethod
    def _parse_time_range_seconds(time_range: str) -> Tuple[float, float]:
        """把各种时间范围字符串 -> (start_seconds, end_seconds)"""
        if 's' in time_range:
            parts = time_range.replace('s', '').split('-')
            return float(parts[0]), float(parts[1])
        def _ts_to_sec(ts):
            ts = ts.strip()
            parts = ts.split(':')
            parts = [float(p) for p in parts]
            while len(parts) < 3: parts.insert(0, 0.0)
            h, m, s = parts
            return h * 3600 + m * 60 + s
        a, b = time_range.split('-')
        return _ts_to_sec(a), _ts_to_sec(b)

    @staticmethod
    def _seconds_to_ass_time(seconds: float) -> str:
        total = max(0.0, float(seconds))
        total_cs = int(total * 100 + 0.5)
        h, rem = divmod(total_cs, 3600 * 100)
        m, rem = divmod(rem, 60 * 100)
        s, cs = divmod(rem, 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# 便捷函数
def generate_ass_with_flower(narration_script: Dict, output_path: str,
                              flower_config: Optional[Dict] = None, **kw) -> Dict:
    gen = SubtitleGenerator()
    return gen.generate_ass_from_script(narration_script, output_path, flower_config, **kw)
def generate_srt(narration_script: Dict, output_path: str) -> str:
    """
    便捷函数：生成SRT字幕

    Args:
        narration_script: 解说文案
        output_path: 输出路径

    Returns:
        SRT文件路径
    """
    generator = SubtitleGenerator()
    return generator.generate_srt_from_script(narration_script, output_path)


if __name__ == '__main__':
    # 测试代码
    test_script = {
        'narrations': [
            {
                'time_range': '0.0s-5.0s',
                'text': '欢迎来到这个精彩的视频，让我们一起探索有趣的内容。'
            },
            {
                'time_range': '5.0s-10.0s',
                'text': '在这个片段中，我们可以看到很多精彩的画面。'
            },
            {
                'time_range': '10.0s-15.0s',
                'text': '感谢观看，我们下期再见！'
            }
        ]
    }

    output_srt = 'output/test_subtitle.srt'
    os.makedirs(os.path.dirname(output_srt), exist_ok=True)

    result = generate_srt(test_script, output_srt)

    if result:
        print(f"字幕生成成功: {result}")
        with open(result, 'r', encoding='utf-8') as f:
            print("\n生成的SRT内容：")
            print(f.read())
    else:
        print("字幕生成失败")
