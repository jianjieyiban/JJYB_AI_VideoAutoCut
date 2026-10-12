# 开源AI视频剪辑项目参考

## 一、核心参考项目

### 1. **OpenSource-Clipping** (强烈推荐)
**GitHub**: https://github.com/NaufalRizqullah/opensource-clipping  
**Star**: ⭐ 活跃维护中  
**功能完整性**: ⭐⭐⭐⭐⭐  

#### 核心特性（可借鉴）:
| 功能模块 | 技术实现 | 借鉴价值 |
|---------|---------|---------|
| AI转录 | Faster-Whisper (large-v3) | 替换现有ASR引擎 |
| AI内容分析 | Google Gemini | 增强精彩片段检测 |
| 人脸追踪 | MediaPipe BlazeFace | 优化智能裁剪 |
| KTV字幕 | ASS字幕逐字高亮 | 替换现有字幕方案 |
| BGM处理 | 侧链压缩(ducking) | 增强音频混音 |
| 语音配音 | Gemini生成脚本 + edge-tts | 可直接集成 |
| 播客分屏 | Pyannote说话人分离 | 新功能开发 |
| 自动上传 | YouTube/FB API | 扩展功能 |

#### 最佳借鉴点:
1. **Karaoke字幕系统** - 逐字高亮样式，非常适合短视频
2. **BGM侧链压缩** - 自动降低人声期间的BGM音量
3. **智能人脸追踪** - 带平滑过渡和防抖动算法
4. **Gemini脚本生成** - 自动化解说文案生成

---

### 2. **Clippyme** (Opus Clip开源替代)
**GitHub**: https://github.com/fralapo/clippyme  
**描述**: 自托管Opus Clip替代方案

#### 特性:
- Gemini驱动的病毒片段检测
- 自动转录+字幕
- 说话人自动取景
- 浏览器内编辑
- 一键发布TikTok/Reels/Shorts

#### 借鉴点:
- 完整的前后端架构
- 实时编辑预览功能

---

### 3. **OpenShorts**
**GitHub**: https://github.com/mutonby/openshorts  
**官网**: https://www.openshorts.app  
**License**: MIT

#### 特性:
- AI视频剪辑生成器
- Whisper转录+PySceneDetect
- MCP Server + API + CLI
- Docker一键部署
- 支持TikTok/Instagram/YouTube Shorts

#### 借鉴点:
- 完整的MCP协议支持
- Docker部署方案
- 视频源处理管道

---

### 4. **AI-Youtube-Shorts-Generator**
**GitHub**: https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator  
**描述**: Opus Clip/Vidyo.ai/Klap/SubMagic开源替代

#### 特性:
- LLM精彩片段检测
- Whisper转录
- 自动竖屏裁剪
- 无水印/无积分限制

---

## 二、字幕相关项目

### 1. **subvert**
**GitHub**: https://github.com/aschmelyun/subvert  
从视频生成字幕、摘要和章节

### 2. **auto-subtitles**
**GitHub**: https://github.com/Eyevinn/auto-subtitles  
Whisper自动字幕生成

### 3. **opensubs**
**GitHub**: https://github.com/open-subs/opensubs  
本地浏览器内字幕工具（Whisper+翻译+烧录）

#### 字幕最佳实践:
```python
# 推荐的字幕处理流程（来自opensubs）
1. Whisper转录 → SRT时间轴
2. 字幕样式处理 → ASS格式（支持逐字高亮）
3. 烧录到视频 → FFmpeg滤镜
```

---

## 三、TTS/语音相关项目

### 1. **GSV-TTS-Lite**
**GitHub**: https://github.com/chinokikiss/GSV-TTS-Lite  
GPT-SoVITS推理引擎，少样本声音克隆

### 2. **qwen3-tts-apple-silicon**
**GitHub**: https://github.com/kapi2800/qwen3-tts-apple-silicon  
Apple Silicon本地TTS，支持声音克隆

### 3. **chatterbox-tts-api**
**GitHub**: https://github.com/travisvn/chatterbox-tts-api  
本地TTS API，OpenAI兼容接口，支持声音克隆

#### TTS最佳实践:
- **快速方案**: edge-tts（免费，已在你的项目中）
- **高质量方案**: GPT-SoVITS（声音克隆）
- **API方案**: OpenAI TTS兼容接口

---

## 四、可直接集成的模块

### 1. Karaoke字幕生成
**来源**: opensource-clipping  
**文件**: `core/subtitle_generator.py`

核心逻辑:
```python
# 逐字高亮ASS字幕生成
def create_karaoke_subtitle(text, timestamps, style):
    # 逐字设置开始/结束时间
    # 添加高亮动画效果
    pass
```

### 2. BGM侧链压缩
**来源**: opensource-clipping  
**文件**: `core/audio_processor.py`

核心逻辑:
```python
# 侧链压缩实现
def apply_sidechain_compression(video_audio, bgm_audio):
    # 1. 检测人声
    # 2. 当人声存在时降低BGM音量
    # 3. 人声结束后恢复BGM
```

### 3. 人脸追踪裁剪
**来源**: opensource-clipping  
**文件**: `core/face_tracker.py`

核心逻辑:
```python
# MediaPipe人脸追踪
def track_and_crop(video_path, output_ratio):
    # 1. 使用BlazeFace检测人脸
    # 2. 平滑过渡（防止抖动）
    # 3. 计算裁剪区域
    # 4. 应用到视频
```

---

## 五、集成建议优先级

### 高优先级（立即可用）
1. **Karaoke字幕系统** - 视觉效果提升显著
2. **BGM侧链压缩** - 音频质量提升
3. **Faster-Whisper集成** - 替换/增强现有ASR

### 中优先级（下一版本）
4. **Gemini脚本生成** - 增强AI解说
5. **人脸追踪优化** - 改善竖屏裁剪
6. **自动上传API** - 扩展发布渠道

### 低优先级（长期规划）
7. **声音克隆** - 个性化配音
8. **B-Roll自动插入** - 丰富视频内容
9. **多平台发布** - TikTok/Reels集成

---

## 六、快速集成清单

```bash
# 1. 克隆参考项目
git clone https://github.com/NaufalRizqullah/opensource-clipping.git

# 2. 查看核心模块
ls opensource-clipping/core/

# 3. 关键文件
├── subtitle_generator.py  # 字幕生成
├── audio_processor.py     # 音频处理
├── face_tracker.py       # 人脸追踪
├── video_composer.py      # 视频合成
└── ai_analyzer.py         # AI分析
```

---

## 七、依赖包参考

```txt
# 核心依赖（来自opensource-clipping）
faster-whisper>=1.0.0
edge-tts>=0.0.0
moviepy>=1.0.3
mediapipe>=0.10.0
pyannote.audio>=3.0.0
ass>=0.6
gtts>=0.0.0
pydub>=0.25.0
cv2>=4.8.0
numpy>=1.24.0
```

---

更新时间: 2024-10-12
