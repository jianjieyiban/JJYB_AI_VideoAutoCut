#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : narration_prompts.py
@Author : AI Assistant (基于NarratoAI学习)
@Date   : 2025-11-10
@Desc   : 原创解说提示词模板 - 包含黄金三秒开头等爆款技巧
"""

from typing import Dict, List


class NarrationPrompts:
    """原创解说提示词管理类"""
    
    # 系统提示词
    SYSTEM_PROMPT = "你是一名资深的短视频解说导演和编剧，深谙病毒式传播规律和用户心理，擅长创作让人停不下来的高粘性解说内容，同时熟悉动画解说、影视解说（第一人称/第三人称）和纪录片解说的专业创作方法。"
    
    # 十大爆款开头钩子类型
    HOOK_TYPES = {
        'suspense': {
            'name': '悬念式',
            'template': '你绝对想不到接下来会发生什么...',
            'examples': [
                '你绝对想不到，这个普通的视频背后隐藏着什么秘密...',
                '接下来发生的事，让所有人都傻眼了...',
                '这个结局，99%的人都猜不到...'
            ]
        },
        'reversal': {
            'name': '反转式',
            'template': '所有人都以为...但真相却是...',
            'examples': [
                '所有人都以为他要失败了，但接下来的反转太惊人...',
                '表面看起来很简单，但真相却让人震惊...',
                '大家都想错了，真正的原因竟然是...'
            ]
        },
        'numbers': {
            'name': '数字冲击',
            'template': '仅用3步/5分钟/1个技巧...',
            'examples': [
                '仅用3个步骤，就能实现惊人效果...',
                '5分钟学会专业技巧...',
                '1个方法改变一切...'
            ]
        },
        'pain_point': {
            'name': '痛点切入',
            'template': '还在为...发愁吗？',
            'examples': [
                '还在为这个问题苦恼吗？答案来了...',
                '是不是经常遇到这种情况？今天教你解决...',
                '这个难题困扰了很多人，其实很简单...'
            ]
        },
        'exclamation': {
            'name': '惊叹式',
            'template': '太震撼了！这才是...',
            'examples': [
                '太震撼了！这才是真正的技巧...',
                '简直不敢相信，原来可以这样做...',
                '厉害了！这个方法绝了...'
            ]
        },
        'question': {
            'name': '疑问引导',
            'template': '为什么...？答案让人意外',
            'examples': [
                '为什么会这样？答案出乎意料...',
                '你知道背后的原因吗？',
                '这是怎么做到的？秘密在这里...'
            ]
        },
        'contrast': {
            'name': '对比冲突',
            'template': '新手VS高手，差距竟然这么大',
            'examples': [
                '新手和高手的区别，竟然这么明显...',
                '看看前后对比，差距太大了...',
                '同样的事情，不同的人做出天壤之别...'
            ]
        },
        'secret': {
            'name': '秘密揭露',
            'template': '内行人才知道的...',
            'examples': [
                '内行人才知道的小秘密...',
                '这个技巧，99%的人不知道...',
                '行家不会告诉你的真相...'
            ]
        },
        'empathy': {
            'name': '情感共鸣',
            'template': '有多少人和我一样...',
            'examples': [
                '有多少人和我一样，曾经也这样想...',
                '相信很多人都有同样的感受...',
                '如果你也遇到过这种情况...'
            ]
        },
        'subvert': {
            'name': '颠覆认知',
            'template': '原来我们一直都错了...',
            'examples': [
                '原来我们一直都理解错了...',
                '没想到，真相竟然是这样...',
                '所有人的认知都被颠覆了...'
            ]
        }
    }

    # 影视/动画/纪录片解说高级风格指引（从影视解说提示词中提炼，作为补充规范）
    FILM_STYLE_GUIDE = """## 影视/动画/纪录片解说高级规范（根据内容类型灵活套用）

### A. 第三人称动画解说（怀旧风）
- 开头 3 秒用时代对比、童年记忆或教育价值制造强吸引力。
- 主线按时间顺序推进，多用“随后/忽然/这时/哪曾想”等词串联事件。
- 放大角色神态与动作细节，善用四字短语增强节奏感。
- 适当保留原片的静默与留白，不要把所有空镜头填满解说。
- 结尾点明教育或价值内核，可自然提炼“团结协作、诚信、互助”等主题。

### B. 第一人称影视解说（强代入视角）
- 全程保持“我”的第一人称视角，通过内心独白暴露真实情绪和动机。
- 开头 3 秒直接抛出“我”的核心困境或冲突，制造强烈悬念。
- 重点放大“爽点时刻”：逆袭、反杀、智商碾压、命运反转等关键节点。
- 多用“而这时”“就在这时”“没想到”“原来”“竟然”等反转与悬念词。
- 巧妙埋下问题与反问，引导观众互动，比如“你们觉得我该怎么选？”。

### C. 原声片段与解说配合（适用于影视类）
- 合理保留原声片段：关键剧情推进、情绪爆发、经典台词或时代感台词。
- 解说与原声时段避免互相覆盖，时间线连续且不重叠，整体保持 7:3 或 8:2 的解说:原声比例即可，不必绝对精确。
- 在情绪高峰、转折或经典台词位置，让画面与原声先说话，解说适当收束或起到承上启下作用。

### D. 语言与合规性要求
- 使用简体中文，语言口语化但保持专业度，避免低俗表达和过度网络梗，符合国内主流短视频平台规则。
- 注重画面感与故事感：多用具体动作、表情、环境细节，而不是空泛形容词。
- 适度强调正向价值观：成长、选择、责任、亲情、友情等，提升作品深度。
- 对于面向儿童或家庭受众的内容，保持语言纯净，避免暴力、恐怖、极端情绪的渲染。
    """
    
    @staticmethod
    def get_mode_instruction(narration_mode: str) -> str:
        """根据解说类型返回补充创作规范"""
        mode = (narration_mode or 'general').lower()

        # 影视解说 · 第一人称
        if mode == 'film_1st':
            return (
                "- 解说类型：**影视解说 · 第一人称**（全程“我”的视角）。\n"
                "- 文案围绕“我”看到什么、想到什么、感受到什么展开，像在讲自己的经历。\n"
                "- 适度暴露真实情绪和心理活动，放大矛盾、选择和爽点（逆袭/翻盘/反转）。\n"
                "- 一段话内部不要在第一人称和第三人称之间来回切换。"
            )

        # 影视解说 · 第三人称
        if mode == 'film_3rd':
            return (
                "- 解说类型：**影视解说 · 第三人称**（旁白讲故事）。\n"
                "- 以“他/她/他们”为主语，像讲故事一样串联人物行为和剧情发展。\n"
                "- 重点标出冲突起点、反转节点和结局，句子干净利落，有节奏感。\n"
                "- 高能桥段和经典台词可留给原声，解说负责承上启下和总结。"
            )

        # 影视解说 · 爱情感情线
        if mode == 'romance':
            return (
                "- 解说类型：**影视解说 · 爱情感情线**。\n"
                "- 把情感推进当作主线，明确“相遇-靠近-矛盾-分离-和解/结局”等情感节点。\n"
                "- 多写眼神、动作、细微反应，用少量内心独白强化暧昧、拉扯和心态变化。\n"
                "- 避免过度狗血或极端价值观，整体基调以真诚、共鸣为主。"
            )

        # 影视解说 · 悬疑反转专用
        if mode == 'suspense_twist':
            return (
                "- 解说类型：**影视解说 · 悬疑反转专用**。\n"
                "- 重点突出“线索-疑点-误导-真相”的结构，适度保留悬念，不要一开始就把全部答案说完。\n"
                "- 用清晰的时间线和因果关系帮助观众理顺复杂剧情，避免逻辑混乱。\n"
                "- 反转处要提前埋伏笔，点出细节，用一两句总结“原来真正的关键是……”。"
            )

        # 动画解说 · 第三人称怀旧
        if mode == 'animation_3rd':
            return (
                "- 解说类型：**动画解说 · 第三人称怀旧风**。\n"
                "- 适当点出“童年”“小时候”“那几年”等关键词，营造年代感与共鸣。\n"
                "- 多写角色的表情、动作和夸张场面，句子短而有节奏，适当用四字短语。\n"
                "- 结尾自然点出故事寓意和正向价值（友谊、勇气、成长等）。"
            )

        # 纪录片解说 · 旁白
        if mode == 'documentary':
            return (
                "- 解说类型：**纪录片解说 · 旁白风**。\n"
                "- 语气客观、冷静，以信息和画面事实为主，少用夸张修辞。\n"
                "- 结构清晰：先交代背景，再说明过程，最后点出结果或影响。\n"
                "- 避免过度主观评价和网络流行语，整体偏专业、理性。"
            )

        # 美食解说 · 探店后厨风
        if mode == 'food_commentary':
            return (
                "- 解说类型：**美食解说 · 探店后厨风**。\n"
                "- 开头从画面可确认的价格反差、稀缺食材、排队热度、分量或一道菜的关键工艺中择一切入；没有明确画面依据时，不编造店名、价格、产地和热度。\n"
                "- 按镜头顺序讲清备料、清洗、切配、下锅、火候、出锅、摆盘和品尝，用短句与具体动词带出节奏和画面感。\n"
                "- 重点写可见食材、关键动作、烹饪工艺、成品卖相，以及基于画面的审慎口感联想；不确定的味道用“看起来”“像是”“预计会”等表达。\n"
                "- 语言口语自然、有食欲但不过度堆砌夸张词；结尾概括最突出的风味或看点，并用一句自然互动收束。"
            )

        # 默认：通用解说
        return (
            "- 解说类型：**通用解说**，适合大多数内容。\n"
            "- 可在第一人称与第三人称之间自由选择，但同一段内部保持统一。\n"
            "- 口语化、易懂、有节奏，像在和朋友聊天，但避免低俗和刻意制造冲突。"
        )

    @staticmethod
    def get_narration_prompt(video_frame_description: str, hook_type: str = 'suspense', narration_mode: str = 'general') -> str:
        """
        生成原创解说提示词
        
        Args:
            video_frame_description: 视频帧分析描述（Markdown格式）
            hook_type: 开头钩子类型，可选值见HOOK_TYPES
            narration_mode: 解说类型，可选值见get_mode_instruction（如 general/film_1st/film_3rd/animation_3rd/documentary/romance/suspense_twist）
        
        Returns:
            完整的提示词
        """
        hook_info = NarrationPrompts.HOOK_TYPES.get(hook_type, NarrationPrompts.HOOK_TYPES['suspense'])
        hook_name = hook_info['name']
        hook_examples = '\n'.join([f'  - {ex}' for ex in hook_info['examples']])
        mode_instruction = NarrationPrompts.get_mode_instruction(narration_mode)
        
        prompt = f"""作为一名短视频解说导演，你需要深入理解病毒式传播的核心规律。以下是爆款短视频解说的核心技巧：

## 黄金三秒法则
开头 3 秒决定用户是否继续观看，必须立即抓住注意力。

## 本次使用的开头钩子类型：{hook_name}
示例：
{hook_examples}

## 十大爆款开头钩子类型（供参考）：
1. **悬念式**："你绝对想不到接下来会发生什么..."
2. **反转式**："所有人都以为...但真相却是..."
3. **数字冲击**："仅用 3 步/5 分钟/1 个技巧..."
4. **痛点切入**："还在为...发愁吗？"
5. **惊叹式**："太震撼了！这才是..."
6. **疑问引导**："为什么...？答案让人意外"
7. **对比冲突**："新手 VS 高手，差距竟然这么大"
8. **秘密揭露**："内行人才知道的..."
9. **情感共鸣**："有多少人和我一样..."
10. **颠覆认知**："原来我们一直都错了..."

## 解说文案核心要素：
- **节奏感**：短句为主，控制在 15-20 字/句，朗朗上口
- **画面感**：用具体动作和细节描述，避免抽象概念
- **情绪起伏**：制造期待、惊喜、满足的情绪曲线
- **信息密度**：每 5-10 秒一个信息点，保持新鲜感
- **口语化**：像朋友聊天，避免书面语和专业术语
- **留白艺术**：关键时刻停顿，让画面说话

{NarrationPrompts.FILM_STYLE_GUIDE}

## 本次解说类型要求：
{mode_instruction}

## 结构范式：
【开头】钩子引入（0-3秒）→ 【发展】情节推进（3-30秒）→ 【高潮】惊艳时刻（30-45秒）→ 【收尾】强化记忆/引导互动（45-60秒）

## 视频内容分析：
{video_frame_description}

## 创作要求：
**创作步骤：**
1. 分析视频主题和核心亮点
2. 使用"{hook_name}"钩子类型设计开头
3. 提炼每个画面的最吸引人的细节
4. 设计情绪曲线和节奏变化
5. 确保解说与画面高度同步

**必须遵循的创作原则：**
- 开头 3 秒必须使用"{hook_name}"钩子技巧，立即抓住注意力
- 每句话控制在 15-20 字，确保节奏明快
- 用动词和具体细节描述，增强画面感
- 制造悬念和期待，让用户想看到最后
- 在关键视觉高潮处，适当留白让画面说话
- 结尾呼应开头，强化记忆点或引导互动

## 输出格式：
请严格按照以下 JSON 结构输出一个对象：

{{
  "title": "视频标题（简短有吸引力）",
  "opening": "开场白（吸引观众注意）",
  "segments": [
    {{
        "scene_id": 0,
        "start_time": 0.0,
        "end_time": 5.0,
        "text": "这一段的解说文本",
        "emotion": "neutral",
        "emphasis": ["重点词1", "重点词2"]
    }}
  ],
  "closing": "结束语（总结或呼吁）"
}}

## 重要限制：
1. 仅输出一个 JSON 对象，结构必须包含 title/opening/segments/closing 四个顶层字段
2. 解说文案的语言使用简体中文
3. 严禁虚构画面，所有画面描述只能从视频内容分析中提取
4. 不要编造与画面严重不符的时间线，start_time/end_time 只能在视频实际时长范围内做合理划分
5. 开头必须使用"{hook_name}"钩子技巧，遵循黄金三秒法则
6. 每个片段的解说文案要与画面内容精准匹配
7. 保持解说的连贯性、故事性和节奏感
8. 控制单句长度在 15-20 字，确保口语化表达
9. 在视觉高潮处适当精简文案，让画面自己说话
10. 整体风格要符合当前主流短视频平台的受欢迎特征"""
        
        return prompt
    
    @staticmethod
    def get_all_hook_types() -> Dict[str, Dict]:
        """获取所有开头钩子类型"""
        return NarrationPrompts.HOOK_TYPES
    
    @staticmethod
    def get_hook_type_names() -> List[str]:
        """获取所有钩子类型的键名"""
        return list(NarrationPrompts.HOOK_TYPES.keys())
    
    @staticmethod
    def get_hook_type_display_names() -> Dict[str, str]:
        """获取钩子类型的显示名称"""
        return {key: value['name'] for key, value in NarrationPrompts.HOOK_TYPES.items()}


# 便捷函数
def generate_narration_prompt(
    video_description: str,
    hook_type: str = 'suspense',
    custom_requirements: str = None,
    narration_mode: str = 'general'
) -> str:
    """生成原创解说提示词（便捷函数）

    Args:
        video_description: 视频内容描述
        hook_type: 开头钩子类型
        custom_requirements: 自定义要求（可选）
        narration_mode: 解说类型（例如 general/film_1st/film_3rd/animation_3rd/documentary/romance/suspense_twist）

    Returns:
        完整提示词
    """
    prompt = NarrationPrompts.get_narration_prompt(video_description, hook_type, narration_mode)
    
    if custom_requirements:
        prompt += f"\n\n## 用户自定义要求：\n{custom_requirements}"
    
    return prompt


if __name__ == '__main__':
    # 测试代码
    test_description = """
    ## 片段 1
    - 时间范围：00:00:00-00:00:05
    - 片段描述：主角登场
    - 详细描述：
      - 00:00:00: 画面显示一个人走进房间
      - 00:00:03: 人物转身面向镜头
    
    ## 片段 2
    - 时间范围：00:00:05-00:00:10
    - 片段描述：介绍背景
    - 详细描述：
      - 00:00:05: 展示房间内的环境
      - 00:00:08: 特写镜头聚焦在桌上的物品
    """
    
    # 测试不同的钩子类型
    for hook_key in ['suspense', 'reversal', 'exclamation']:
        print(f"\n{'='*60}")
        print(f"钩子类型: {NarrationPrompts.HOOK_TYPES[hook_key]['name']}")
        print('='*60)
        prompt = generate_narration_prompt(test_description, hook_key)
        print(prompt[:500] + '...')  # 只显示前500字符
    
    # 显示所有可用的钩子类型
    print(f"\n{'='*60}")
    print("所有可用的钩子类型：")
    print('='*60)
    for key, info in NarrationPrompts.get_all_hook_types().items():
        print(f"- {key}: {info['name']}")
        print(f"  模板: {info['template']}")
