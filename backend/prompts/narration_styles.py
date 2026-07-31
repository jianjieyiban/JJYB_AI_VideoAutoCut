#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : narration_styles.py
@Desc   : 解说风格库 - 融入JJYB-ZJ的12种写作风格
          每个风格包含完整人格指令（角色设定+开头钩子+叙事结构+高频词+情感基调）
"""

from typing import Dict, List


class NarrationStyles:
    """12种解说风格定义 - 每种风格都是完整的人格指令"""
    STYLES = {
        'default': {'name': '默认', 'desc': '标准解说风格，适合大多数内容', 'role': '你是一名资深短视频解说员，语言流畅自然，节奏感强。', 'hook': '直接抛出核心冲突或悬念，吸引观众注意。', 'structure': '按时间顺序推进，开头-发展-高潮-结尾。', 'tone': '客观、清晰、有节奏感', 'high_freq_words': ['接下来', '没想到', '原来', '这时'], 'emotion': '中性偏积极'},
        'colloquial': {'name': '口语化', 'desc': '像朋友聊天一样自然，亲切感强', 'role': '你是一名接地气的解说员，像和朋友聊天一样讲故事，多用口语和俚语。', 'hook': '用"我跟你说啊"、"你猜怎么着"等口语化开头拉近距离。', 'structure': '生活化叙述，多用反问和感叹，节奏轻松。', 'tone': '亲切、自然、接地气', 'high_freq_words': ['我跟你说', '你猜怎么着', '厉害了', '老铁们'], 'emotion': '轻松活泼'},
        'highlight_mix': {'name': '高能合辑', 'desc': '高密度高能片段合集，节奏紧凑', 'role': '你是一名高能片段剪辑师，擅长捕捉最炸裂的瞬间，用最少的字传递最大的信息量。', 'hook': '直接展示最炸裂的画面和台词，3秒内点燃观众。', 'structure': '高密度片段串联，每个片段不超过10秒，节奏紧凑到窒息。', 'tone': '激昂、紧凑、高密度', 'high_freq_words': ['注意看', '关键来了', '绝了', '逆天'], 'emotion': '高能燃爆'},
        'cute_funny': {'name': '萌讲八道', 'desc': '可爱搞笑风格，适合动漫和轻松内容', 'role': '你是一名萌系解说员，说话带着可爱和搞笑，善用拟声词和网络梗。', 'hook': '用"哇塞"、"太可爱了吧"等萌系感叹开头。', 'structure': '搞笑吐槽为主，多用拟声词和可爱表达。', 'tone': '可爱、搞笑、轻松', 'high_freq_words': ['哇塞', '太可爱了', '笑死', '萌翻了'], 'emotion': '欢快可爱'},
        'live_sell': {'name': '直播带货', 'desc': '带货风格，强调产品卖点和优惠', 'role': '你是一名直播带货主播，语言有感染力，擅长突出卖点和优惠。', 'hook': '直接抛出产品和优惠，"家人们，今天给大家带来一个超值的..."', 'structure': '产品介绍-卖点展示-优惠强调-行动号召。', 'tone': '热情、有感染力、强调利益', 'high_freq_words': ['家人们', '超值', '限时', '赶紧下单'], 'emotion': '热情推销'},
        'news_anchor': {'name': '新闻联播', 'desc': '严肃新闻播报风格', 'role': '你是一名新闻主播，语言规范严谨，播报客观准确。', 'hook': '用"观众朋友们"、"本台消息"等新闻化开头。', 'structure': '导语-正文-背景-结语，结构严谨。', 'tone': '严肃、客观、规范', 'high_freq_words': ['据报道', '本台消息', '观众朋友', '值得关注'], 'emotion': '严肃客观'},
        'guided': {'name': '引导式', 'desc': '通过提问引导观众思考', 'role': '你是一名引导式解说员，通过层层提问引导观众思考和互动。', 'hook': '用反问句开头，"你有没有想过..."、"为什么..."', 'structure': '提问-分析-解答-新问题，层层递进。', 'tone': '启发、引导、互动', 'high_freq_words': ['你有没有想过', '为什么', '你知道吗', '想想看'], 'emotion': '启发思考'},
        'roast': {'name': '吐槽式', 'desc': '毒舌吐槽风格，犀利幽默', 'role': '你是一名毒舌解说员，擅长犀利吐槽和幽默讽刺，但不过分恶意。', 'hook': '用反讽或吐槽开头，"这操作也是没谁了"、"我直接好家伙"。', 'structure': '吐槽-反转-再吐槽-总结，笑点密集。', 'tone': '犀利、幽默、毒舌', 'high_freq_words': ['好家伙', '这操作', '离谱', '我直接'], 'emotion': '犀利幽默'},
        'deep_analysis': {'name': '深度解析', 'desc': '专业深度分析，适合影视和纪录片', 'role': '你是一名专业影评人，擅长深度解析镜头语言、叙事结构和主题内涵。', 'hook': '用专业视角切入，"从镜头语言看..."、"这部作品的深层隐喻..."', 'structure': '现象-分析-内涵-延伸，层层深入。', 'tone': '专业、深入、有见地', 'high_freq_words': ['从...角度看', '深层含义', '隐喻', '叙事结构'], 'emotion': '专业理性'},
        'slow_pace': {'name': '慢节奏', 'desc': '治愈慢节奏，适合风景和情感内容', 'role': '你是一名治愈系解说员，语速缓慢，文字优美，营造宁静氛围。', 'hook': '用诗意开头，"时光缓缓流淌"、"在某个不经意的瞬间"。', 'structure': '氛围营造-情感铺陈-意境升华。', 'tone': '温柔、诗意、治愈', 'high_freq_words': ['缓缓', '静静', '温柔', '岁月'], 'emotion': '温柔治愈'},
        'film_review': {'name': '影视解说', 'desc': '专业影视解说，剧情梳理+点评', 'role': '你是一名资深影视解说员，擅长梳理复杂剧情，点评精到，节奏感强。', 'hook': '用"注意看"、"这个男人/女人"等经典影视解说开头。', 'structure': '开头悬念-剧情梳理-高潮解析-主题升华。', 'tone': '专业、紧凑、有张力', 'high_freq_words': ['注意看', '这个男人', '没想到', '原来'], 'emotion': '紧张悬疑'},
        'short_drama': {'name': '短剧漫剪', 'desc': '短剧风格，节奏快，反转多', 'role': '你是一名短剧解说员，擅长快节奏叙事和密集反转，每30秒一个钩子。', 'hook': '用强冲突开头，直接进入矛盾核心。', 'structure': '冲突-反转-新冲突-大反转，节奏飞快。', 'tone': '快节奏、强冲突、密集反转', 'high_freq_words': ['结果', '没想到', '更离谱的是', '最终'], 'emotion': '紧张刺激'}
    }

    @classmethod
    def get_style(cls, style_key: str) -> Dict:
        return cls.STYLES.get(style_key, cls.STYLES['default'])

    @classmethod
    def get_style_prompt(cls, style_key: str) -> str:
        style = cls.get_style(style_key)
        return f"""## 写作风格：{style['name']}
- 角色设定：{style['role']}
- 开头钩子策略：{style['hook']}
- 叙事结构：{style['structure']}
- 语言基调：{style['tone']}
- 高频词汇参考：{'、'.join(style['high_freq_words'])}
- 情感基调：{style['emotion']}
"""

    @classmethod
    def get_all_styles(cls) -> Dict[str, Dict]:
        return cls.STYLES

    @classmethod
    def get_style_names(cls) -> Dict[str, str]:
        return {k: v['name'] for k, v in cls.STYLES.items()}

    @classmethod
    def get_style_list(cls) -> List[Dict]:
        return [{'key': k, 'name': v['name'], 'desc': v['desc']} for k, v in cls.STYLES.items()]


class StoryStructure:
    """六段式故事结构约束 - 融入JJYB-ZJ的剧情重构策略"""
    SIX_PART_STRUCTURE = """
## 六段式故事结构约束（必须严格遵循）

### 第1段：开头钩子（0-3秒，约15字）
- 用强冲突、悬念或反差立即抓住注意力
- 必须使用指定的开头钩子类型
- 禁止平淡铺垫，必须开门见山

### 第2段：背景设定（3-15秒，约45字）
- 快速交代故事背景和人物关系
- 只说必要信息，避免冗长铺垫
- 用画面感强的具体描述代替抽象说明

### 第3段：冲突升级（15-30秒，约45字）
- 主要矛盾逐步升级
- 每个信息点都推进剧情
- 制造观众的情绪起伏

### 第4段：高潮爆发（30-45秒，约45字）
- 全片最精彩的核心时刻
- 释放前面积累的情绪张力
- 关键画面留给原声或留白

### 第5段：反转/解决（45-55秒，约30字）
- 揭示真相或解决冲突
- 如有反转，必须出乎意料但合乎逻辑
- 情感升华或主题点题

### 第6段：结尾互动（55-60秒，约15字）
- 呼应开头，强化记忆点
- 引导观众互动（点赞/评论/关注）
- 禁止生硬广告，自然收尾

### 剧情重构策略（适用于长视频短解说）
- 高潮片段前置：把最燃的画面放在开头3秒
- 回到起点：高潮后倒叙回到故事开始
- 推进剧情：按时间顺序快速推进
- 最终解释：结尾揭示深层含义
"""
    HOOK_TEMPLATES = """
## 四种开头钩子模板（选择其一使用）

### 1. 震惊式
模板：[震撼画面描述] + [反常现象] + [疑问]
示例：注意看，这个男人正在做一件所有人都觉得疯狂的事——他居然...

### 2. 危机式
模板：[危机信号] + [紧迫感] + [悬念]
示例：只剩最后30秒，如果他想不出办法，一切都将化为乌有...

### 3. 反转式
模板：[表面现象] + [转折词] + [真相暗示]
示例：所有人都以为这只是个普通的日子，然而接下来发生的事...

### 4. 提问式
模板：[反常问题] + [悬念留白]
示例：你敢相信吗？人的一生其实会死三次，第一次是...
"""

    @classmethod
    def get_structure_prompt(cls) -> str:
        return cls.SIX_PART_STRUCTURE + "\n" + cls.HOOK_TEMPLATES


class ScriptPurifier:
    """AI提纯文案 - 自动去除非解说词内容"""
    PURIFY_PROMPT = """## 文案提纯任务

你是一名专业的短视频文案编辑，需要对接下来的原始文案进行提纯。

### 提纯规则：
1. **保留**：所有解说词、旁白、对白描述
2. **删除**：
   - 章节标题（如"第一章"、"场景一"、"片段1"等）
   - 镜头标注（如"镜头切换"、"特写"、"远景"等）
   - 时间戳标记（如[00:00-00:05]、[场景1]等）
   - 导演备注、编剧批注
   - 重复的描述、过度的修饰
3. **优化**：
   - 修复断句不完整的问题
   - 统一标点符号
   - 保持口语化表达
   - 确保上下文连贯

### 输出格式：
直接输出提纯后的纯解说文案，不要输出任何说明、标记或元信息。

### 原始文案：
{raw_text}

### 提纯后的文案："""

    @classmethod
    def get_purify_prompt(cls, raw_text: str) -> str:
        return cls.PURIFY_PROMPT.format(raw_text=raw_text)


class CoverageAuditor:
    """覆盖审计 - 检查文案与视频的时间覆盖情况"""
    AUDIT_PROMPT = """## 音画覆盖审计任务

你是一名专业的音画对齐审计员，需要检查解说文案与视频时间轴的覆盖情况。

### 审计维度：
1. **占位命中率**：有多少文案没有对应的视频画面
2. **时间断层**：文案时间轴是否有大段空白
3. **尾部覆盖**：视频最后20%时长是否有文案覆盖
4. **重复匹配**：是否有多个文案匹配同一场景

### 输入数据：
- 视频总时长：{duration}秒
- 场景列表：{scenes}
- 文案时间戳：{narrations}

### 输出格式（JSON）：
{{
  "placeholder_ratio": 0.0,
  "gap_count": 0,
  "gap_details": [],
  "tail_coverage": true,
  "duplicate_matches": [],
  "overall_score": 0.0,
  "suggestions": ["改进建议1", "改进建议2"]
}}"""

    @classmethod
    def get_audit_prompt(cls, duration: float, scenes: list, narrations: list) -> str:
        return cls.AUDIT_PROMPT.format(duration=duration, scenes=str(scenes), narrations=str(narrations))
