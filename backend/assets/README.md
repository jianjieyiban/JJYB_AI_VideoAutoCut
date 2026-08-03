# Backend Assets 资源文件夹

## 📁 目录结构

```
backend/assets/
├── fonts/          # 字体文件
├── images/         # 图片资源
└── audio/          # 音频资源
```

---

## 🔤 fonts/ - 字体文件夹

### 当前可用字体：

#### **wryh.ttf** - 微软雅黑
- **用途**: 视频字幕默认字体
- **语言**: 简体中文
- **授权**: 系统字体
- **大小**: ~15MB
- **推荐场景**: 通用中文字幕

### 推荐添加的字体：

#### 1. **思源黑体** (SourceHanSansCN.ttf)
- **下载**: https://github.com/adobe-fonts/source-han-sans
- **优点**: 开源免费，字形优美
- **大小**: ~28MB
- **适合**: 正式场合、专业视频

#### 2. **阿里巴巴普惠体** (Alibaba-PuHuiTi.ttf)
- **下载**: https://www.alibabafonts.com/
- **优点**: 免费商用，现代风格
- **大小**: ~10MB
- **适合**: 商业视频、营销内容

#### 3. **Roboto** (Roboto-Regular.ttf)
- **下载**: https://fonts.google.com/specimen/Roboto
- **优点**: 英文字体，清晰易读
- **大小**: ~168KB
- **适合**: 英文字幕、双语字幕

### 字体使用示例：

```python
from backend.config.paths import get_font_path, DEFAULT_FONT

# 使用默认字体
font = get_font_path()

# 使用指定字体
font = get_font_path('SourceHanSansCN.ttf')

# 如果字体不存在，自动回退到默认字体
```

---

## 🖼️ images/ - 图片资源

### 建议存放内容：

1. **logo.png** - 项目Logo
   - 尺寸: 512x512px
   - 格式: PNG透明背景
   - 用途: 水印、品牌标识

2. **watermark.png** - 视频水印
   - 尺寸: 200x60px
   - 格式: PNG透明背景
   - 位置: 视频右下角

3. **default_cover.jpg** - 默认封面
   - 尺寸: 1920x1080px
   - 格式: JPG
   - 用途: 视频缩略图

4. **loading.gif** - 加载动画
   - 尺寸: 100x100px
   - 格式: GIF
   - 用途: 前端加载提示

---

## 🎵 audio/ - 音频资源

### 建议存放内容：

1. **default_bgm.mp3** - 默认背景音乐
   - 时长: 3-5分钟循环
   - 码率: 128kbps
   - 用途: 视频背景音乐

2. **transition.mp3** - 转场音效
   - 时长: <1秒
   - 码率: 128kbps
   - 用途: 视频片段转场

3. **intro.mp3** - 片头音乐
   - 时长: 5-10秒
   - 码率: 192kbps
   - 用途: 视频开场

### 音频使用示例：

```python
from backend.config.paths import AUDIO_DIR

# BGM路径
default_bgm = AUDIO_DIR / 'default_bgm.mp3'

# 在视频合成中使用
composer.merge_materials(
    video_path='input.mp4',
    audio_path='voice.mp3',
    bgm_path=str(default_bgm),
    output_path='output.mp4'
)
```

---

## 🔧 配置文件

所有路径配置统一在 `backend/config/paths.py` 中管理：

```python
from backend.config.paths import (
    FONTS_DIR,      # 字体目录
    IMAGES_DIR,     # 图片目录
    AUDIO_DIR,      # 音频目录
    DEFAULT_FONT,   # 默认字体路径
    get_font_path,  # 获取字体路径函数
)
```

---

## 📦 资源添加指南

### 添加新字体：

1. 将字体文件复制到 `fonts/` 目录
2. 确保文件名使用英文（如 `SourceHanSans.ttf`）
3. 在代码中通过 `get_font_path('SourceHanSans.ttf')` 使用

### 添加新图片：

1. 将图片文件复制到 `images/` 目录
2. 推荐使用有意义的文件名（如 `logo_dark.png`）
3. 通过 `IMAGES_DIR / 'logo_dark.png'` 访问

### 添加新音频：

1. 将音频文件复制到 `audio/` 目录
2. 推荐使用MP3格式（兼容性好）
3. 通过 `AUDIO_DIR / 'custom_bgm.mp3'` 访问

---

## ⚠️ 注意事项

### 版权合规：
- ✅ 使用开源字体或已授权字体
- ✅ 音频资源需要版权授权
- ✅ 图片素材确保有使用权

### 文件大小：
- 字体文件: 建议<30MB
- 图片文件: 建议<5MB
- 音频文件: 建议<10MB

### 命名规范：
- 使用小写字母和下划线
- 避免中文文件名
- 避免特殊字符

---

## 🔗 相关文档

- [路径配置文档](../config/paths.py)
- [视频合成文档](../engine/video_composer.py)
- [资源分析报告](../../RESOURCE_ANALYSIS_REPORT.md)

---

## 📝 更新日志

### 2025-11-10
- ✅ 创建资源文件夹结构
- ✅ 添加微软雅黑字体
- ✅ 配置默认资源路径
- ✅ 集成到视频合成器

---

**维护者**: AI Assistant
**最后更新**: 2025-11-10
