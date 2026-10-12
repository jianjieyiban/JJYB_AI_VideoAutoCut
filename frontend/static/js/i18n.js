(function () {
    'use strict';

    var storageKey = 'jjybLanguage';
    var defaultLanguage = 'zh-CN'; // 默认中文

    // Unicode辅助函数
    function c() {
        var result = '';
        for (var i = 0; i < arguments.length; i++) {
            result += String.fromCharCode(arguments[i]);
        }
        return result;
    }

    var messages = {
        'en-US': {
            // ==================== 导航和基础 ====================
            appName: 'JJYB_AI智剪',
            appSubtitle: 'Professional Video Editor',
            editor: 'Editor',
            projects: 'Projects',
            mediaLibrary: 'Media Library',
            aiFeatures: 'AI Features',
            settings: 'Settings',
            newProject: 'New Project',
            save: 'Save',
            export: 'Export',
            videoSource: 'Video Source',
            recognitionLanguage: 'Recognition Language',

            // ==================== 用户菜单 ====================
            userMenu: 'User Menu',
            personalCenter: 'Personal Center',
            logout: 'Logout',

            // ==================== 通知 ====================
            notifications: 'Notifications',
            notificationsUnread: 'notifications, unread',
            markAllRead: 'Mark All Read',
            clearAll: 'Clear All',
            refresh: 'Refresh',
            noNotifications: 'No notifications',
            realtimeSync: 'Real-time sync',
            basedOnProjectData: 'Based on project data',

            // ==================== 侧边栏 ====================
            currentProject: 'Current Project',
            noProjectSelected: 'No project selected',
            createNewProject: 'Create New Project',
            recentProjects: 'Recent Projects',
            noRecentProjects: 'No recent projects',
            quickTools: 'Quick Tools',
            aiDubbing: 'AI Dubbing',
            autoSubtitle: 'Auto Subtitle',
            smartClip: 'Smart Clip',
            imageEnhance: 'Enhance',

            // ==================== 右侧面板 ====================
            contextPanel: 'Context Panel',
            ready: 'Ready',
            currentWorkspace: 'Current Workspace',
            workspaceTip: 'Select materials to adjust clip properties, color, and export settings.',

            // ==================== 剪辑属性 ====================
            clipProperties: 'Clip Properties',
            position: 'Position',
            scale: 'Scale',
            rotation: 'Rotation',
            volume: 'Volume',

            // ==================== 色彩校正 ====================
            colorCorrection: 'Color Correction',
            brightness: 'Brightness',
            contrast: 'Contrast',
            saturation: 'Saturation',
            hue: 'Hue',

            // ==================== 特效 ====================
            effects: 'Effects',
            colorGrade: 'Color Grading',
            filters: 'Filters',
            transitions: 'Transitions',
            visualEffects: 'Visual Effects',

            // ==================== 导出设置 ====================
            exportSettings: 'Export Settings',
            format: 'Format',
            resolution: 'Resolution',
            frameRate: 'Frame Rate',
            quality: 'Quality',
            bitrate: 'Bitrate',
            mp4Recommended: 'MP4 (Recommended)',
            exportVideo: 'Export Video',

            // ==================== 通用数值 ====================
            coordX: 'X',
            coordY: 'Y',
            minValue: '0%',
            maxValue: '200%',

            // ==================== index页面 ====================
            loadingEditor: 'Loading editor...',
            firstLoadTip: 'First load may take a few seconds',
            videoPreview: 'Video Preview',
            fullscreenPreview: 'Fullscreen Preview',
            clipInspector: 'Clip Inspector',
            inspectorTip: 'Select color correction, export settings, or history to view parameters here.',

            // ==================== settings页面 ====================
            backHome: 'Back to Home',
            systemSettings: 'System Settings',
            configureWorkspace: 'Configure your editing workspace',
            core: 'Core',
            appearanceSettings: 'Appearance',
            languageSettings: 'Language',
            performanceSettings: 'Performance',
            advancedSettings: 'Advanced',
            aiModelConfigCenter: 'AI Model API Configuration',
            aiModelConfigTip: 'Configure API keys for AI platforms',
            saveAllConfig: 'Save All Config',
            storageStatus: 'Storage Status',
            projectOverview: 'Project Overview',
            used: 'Used',
            total: 'Total',

            // ==================== settings快捷导航 ====================
            originalCommentary: 'Original Commentary',
            aiVoiceover: 'AI Voiceover',
            editorMode: 'Editor',

            // ==================== 设置页面UI ====================
            editorLayout: 'Editor Layout',
            autoCollapseSidebar: 'Collapse Right Panel by Default',
            autoCollapseTip: 'On: auto-collapse on enter; Off: remember last state',
            resetDefault: 'Reset Default',
            saveSettings: 'Save Settings',

            // ==================== 项目操作 ====================
            projectName: 'Project Name',
            projectDescription: 'Description',
            createProject: 'Create Project',
            openProject: 'Open Project',
            deleteProject: 'Delete Project',
            duplicateProject: 'Duplicate Project',
            exportProject: 'Export Project',
            importProject: 'Import Project',
            projectCreated: 'Project created successfully',
            projectSaved: 'Project saved',
            projectDeleted: 'Project deleted',
            confirmDelete: 'Are you sure you want to delete this project?',

            // ==================== 素材库 ====================
            uploadMaterial: 'Upload Material',
            dragDropHint: 'Drag and drop files here or click to upload',
            supportedFormats: 'Supported formats',
            materialDeleted: 'Material deleted',
            batchImport: 'Batch Import',
            folderImport: 'Import Folder',
            searchMaterials: 'Search materials...',
            sortBy: 'Sort by',
            filterBy: 'Filter by',
            dateAdded: 'Date Added',
            name: 'Name',
            duration: 'Duration',
            size: 'Size',
            type: 'Type',
            video: 'Video',
            audio: 'Audio',
            image: 'Image',

            // ==================== 视频编辑 ====================
            addClip: 'Add Clip',
            removeClip: 'Remove Clip',
            trimClip: 'Trim Clip',
            splitClip: 'Split Clip',
            mergeClips: 'Merge Clips',
            undo: 'Undo',
            redo: 'Redo',
            preview: 'Preview',
            fullscreen: 'Fullscreen',
            timeline: 'Timeline',
            zoomIn: 'Zoom In',
            zoomOut: 'Zoom Out',
            fitToWindow: 'Fit to Window',

            // ==================== AI功能 ====================
            aiDubbingTitle: 'AI Dubbing',
            aiSubtitleTitle: 'AI Subtitle',
            aiClipTitle: 'AI Smart Clip',
            aiEnhanceTitle: 'AI Enhance',
            selectVoice: 'Select Voice',
            voicePreview: 'Preview Voice',
            generateDubbing: 'Generate Dubbing',
            subtitleStyle: 'Subtitle Style',
            subtitlePosition: 'Subtitle Position',
            generateSubtitles: 'Generate Subtitles',
            autoDetectScenes: 'Auto Detect Scenes',
            highlightSelection: 'Highlight Selection',
            qualityEnhancement: 'Quality Enhancement',

            // ==================== 设置页面 ====================
            // API配置
            apiConfig: 'API Configuration',
            apiKey: 'API Key',
            baseUrl: 'Base URL',
            model: 'Model',
            testConnection: 'Test Connection',
            connectionSuccess: 'Connection successful',
            connectionFailed: 'Connection failed',
            saveConfig: 'Save Configuration',

            // 视觉模型
            visionModels: 'Vision Models',
            gpt4v: 'GPT-4V',
            claudeVision: 'Claude Vision',
            geminiVision: 'Gemini Vision',
            qwenVL: 'Qwen-VL',

            // 语音模型
            voiceModels: 'Voice Models',
            azureTTS: 'Azure TTS',
            volcanoVoice: 'Volcano Voice Clone',
            selectRegion: 'Select Region',
            previewAudio: 'Preview Audio',

            // 图片生成
            imageModels: 'Image Generation',
            dalle: 'DALL-E',
            tongyiWanxiang: 'Tongyi Wanxiang',
            wenxinYige: 'Wenxin Yige',
            cogview: 'CogView',
            doubaoImage: 'Doubao Image',
            siliconFlow: 'SiliconFlow',

            // 外观设置
            appearance: 'Appearance',
            theme: 'Theme',
            themeMode: 'Theme Mode',
            themeColor: 'Theme Color',
            lightMode: 'Light Mode',
            darkMode: 'Dark Mode',
            autoMode: 'Auto (System)',
            transparency: 'Transparency',
            interfaceScale: 'Interface Scale',

            // 语言设置
            language: 'Language',
            chinese: '中文',
            english: 'English',
            selectLanguage: 'Select Language',

            // 文件设置
            fileSettings: 'File Settings',
            defaultSavePath: 'Default Save Path',
            exportFormat: 'Export Format',
            videoQuality: 'Video Quality',
            autoSave: 'Auto Save',
            autoSaveInterval: 'Auto Save Interval',
            minutes: 'minutes',

            // 通知设置
            notificationSettings: 'Notification Settings',
            desktopNotification: 'Desktop Notification',
            soundAlert: 'Sound Alert',
            taskCompleteNotification: 'Task Complete Notification',
            errorNotification: 'Error Notification',
            enable: 'Enable',
            disable: 'Disable',

            // 性能设置
            performance: 'Performance',
            gpuAcceleration: 'GPU Acceleration',
            multiThreading: 'Multi-threading',
            aiModelQuality: 'AI Model Quality',
            memoryLimit: 'Memory Limit',
            low: 'Low',
            medium: 'Medium',
            high: 'High',

            // 高级设置
            advanced: 'Advanced',
            ffmpegPath: 'FFmpeg Path',
            selectFFmpeg: 'Select FFmpeg',
            proxySettings: 'Proxy Settings',
            proxyEnabled: 'Enable Proxy',
            proxyAddress: 'Proxy Address',
            logLevel: 'Log Level',
            debug: 'Debug',
            info: 'Info',
            warning: 'Warning',
            error: 'Error',
            autoUpdate: 'Auto Update',
            developerMode: 'Developer Mode',

            // 关于
            about: 'About',
            systemInfo: 'System Information',
            version: 'Version',
            checkUpdate: 'Check for Updates',
            officialWebsite: 'Official Website',
            documentation: 'Documentation',
            reportIssue: 'Report Issue',
            license: 'License',

            // ==================== 通用按钮和提示 ====================
            confirm: 'Confirm',
            cancel: 'Cancel',
            close: 'Close',
            apply: 'Apply',
            reset: 'Reset',
            clear: 'Clear',
            delete: 'Delete',
            edit: 'Edit',
            add: 'Add',
            remove: 'Remove',
            copy: 'Copy',
            paste: 'Paste',
            download: 'Download',
            upload: 'Upload',
            loading: 'Loading...',
            processing: 'Processing...',
            success: 'Success',
            failed: 'Failed',
            warning: 'Warning',
            error: 'Error',
            tips: 'Tips',
            help: 'Help',
            yes: 'Yes',
            no: 'No',
            ok: 'OK',
            done: 'Done',
            next: 'Next',
            previous: 'Previous',
            finish: 'Finish',
            skip: 'Skip',
            back: 'Back',
            search: 'Search',
            refresh: 'Refresh',
            selectAll: 'Select All',
            deselectAll: 'Deselect All',
            selectFile: 'Select File',
            selectFolder: 'Select Folder',
            browse: 'Browse',
            chooseFile: 'Choose File',

            // ==================== 错误消息 ====================
            networkError: 'Network error, please check your connection',
            serverError: 'Server error, please try again later',
            fileNotFound: 'File not found',
            invalidFormat: 'Invalid format',
            fileTooLarge: 'File too large',
            unsupportedFormat: 'Unsupported format',
            insufficientSpace: 'Insufficient disk space',
            permissionDenied: 'Permission denied',
            unknownError: 'Unknown error',

            // ==================== 任务状态 ====================
            taskQueue: 'Task Queue',
            taskProgress: 'Task Progress',
            taskCompleted: 'Task Completed',
            taskFailed: 'Task Failed',
            taskPaused: 'Task Paused',
            taskCancelled: 'Task Cancelled',
            taskPending: 'Pending',
            taskRunning: 'Running',
            estimatedTime: 'Estimated time',
            remaining: 'remaining',

            // ==================== 混剪功能 ====================
            remixMode: 'Remix Mode',
            importVideos: 'Import Videos',
            batchProcess: 'Batch Process',
            selectTemplate: 'Select Template',
            remixStyle: 'Remix Style',
            beatMatch: 'Beat Match',
            autoTransition: 'Auto Transition',
            generatePreview: 'Generate Preview',
            exportHighQuality: 'Export High Quality',

            // ==================== 解说功能 ====================
            commentaryMode: 'Commentary Mode',
            scriptEditor: 'Script Editor',
            voiceSelection: 'Voice Selection',
            backgroundMusic: 'Background Music',
            generateCommentary: 'Generate Commentary',
            adjustTiming: 'Adjust Timing',
            syncWithVideo: 'Sync with Video',

            // ==================== 配音功能 ====================
            voiceoverMode: 'Voiceover Mode',
            textToSpeech: 'Text to Speech',
            voiceClone: 'Voice Clone',
            recordAudio: 'Record Audio',
            importAudio: 'Import Audio',
            adjustPitch: 'Adjust Pitch',
            adjustSpeed: 'Adjust Speed',

            // ==================== 字幕功能 ====================
            subtitleMode: 'Subtitle Mode',
            importSubtitle: 'Import Subtitle',
            exportSubtitle: 'Export Subtitle',
            subtitleFormat: 'Subtitle Format',
            srtFormat: 'SRT',
            assFormat: 'ASS',
            vttFormat: 'VTT',
            fontSize: 'Font Size',
            fontColor: 'Font Color',
            fontFamily: 'Font Family',
            outline: 'Outline',
            shadow: 'Shadow',
            backgroundColor: 'Background Color',

            // ==================== 高级功能 ====================
            batchExport: 'Batch Export',
            scheduledExport: 'Scheduled Export',
            exportQueue: 'Export Queue',
            watermark: 'Watermark',
            addWatermark: 'Add Watermark',
            watermarkPosition: 'Watermark Position',
            watermarkOpacity: 'Watermark Opacity',

            // ==================== 工具提示 ====================
            uploadTip: 'Click or drag files to upload',
            projectTip: 'Click to open project',
            settingsTip: 'Configure application settings',
            saveTip: 'Save current project',
            exportTip: 'Export current project',
            helpTip: 'View help documentation'
        },

        'zh-CN': {
            // ==================== 导航和基础 ====================
            appName: 'JJYB_AI智剪',
            appSubtitle: '专业视频编辑器',
            editor: '编辑器',
            projects: '项目',
            mediaLibrary: '素材库',
            aiFeatures: 'AI功能',
            settings: '设置',
            newProject: '新建项目',
            save: '保存',
            export: '导出',
            videoSource: '视频源',
            recognitionLanguage: '识别语言',

            // ==================== 用户菜单 ====================
            userMenu: '用户菜单',
            personalCenter: '个人中心',
            logout: '退出登录',

            // ==================== 通知 ====================
            notifications: '通知',
            notificationsUnread: '通知，未读',
            markAllRead: '全部已读',
            clearAll: '清空',
            refresh: '刷新',
            noNotifications: '暂无通知',
            realtimeSync: '任务事件实时同步',
            basedOnProjectData: '以项目数据为准',

            // ==================== 侧边栏 ====================
            currentProject: '当前项目',
            noProjectSelected: '未选择项目',
            createNewProject: '创建新项目',
            recentProjects: '最近项目',
            noRecentProjects: '暂无最近项目',
            quickTools: '快速工具',
            aiDubbing: 'AI配音',
            autoSubtitle: '自动字幕',
            smartClip: '智能剪辑',
            imageEnhance: '画质增强',

            // ==================== 右侧面板 ====================
            contextPanel: '上下文面板',
            ready: '就绪',
            currentWorkspace: '当前工作区',
            workspaceTip: '选择素材后可在此调整剪辑属性、色彩与导出参数。',

            // ==================== 剪辑属性 ====================
            clipProperties: '剪辑属性',
            position: '位置',
            scale: '缩放',
            rotation: '旋转',
            volume: '音量',

            // ==================== 色彩校正 ====================
            colorCorrection: '色彩校正',
            brightness: '亮度',
            contrast: '对比度',
            saturation: '饱和度',
            hue: '色调',

            // ==================== 特效 ====================
            effects: '特效',
            colorGrade: '色彩校正',
            filters: '滤镜',
            transitions: '转场',
            visualEffects: '视觉效果',

            // ==================== 导出设置 ====================
            exportSettings: '导出设置',
            format: '格式',
            resolution: '分辨率',
            frameRate: '帧率',
            quality: '质量',
            bitrate: '码率',
            mp4Recommended: 'MP4 (推荐)',
            exportVideo: '导出视频',

            // ==================== 通用数值 ====================
            coordX: 'X',
            coordY: 'Y',
            minValue: '0%',
            maxValue: '200%',

            // ==================== index页面 ====================
            loadingEditor: '正在加载编辑器...',
            firstLoadTip: '首次加载可能需要几秒钟',
            videoPreview: '视频预览',
            fullscreenPreview: '全屏预览',
            clipInspector: '剪辑检查器',
            inspectorTip: '选择色彩校正、导出设置或历史操作后，相关参数会在此处显示。',

            // ==================== settings页面 ====================
            backHome: '返回首页',
            systemSettings: '系统设置',
            configureWorkspace: '配置您的智剪工作区',
            core: '核心',
            appearanceSettings: '外观设置',
            languageSettings: '语言设置',
            performanceSettings: '性能设置',
            advancedSettings: '高级设置',
            aiModelConfigCenter: 'AI大模型API配置中心',
            aiModelConfigTip: '配置各大AI平台的API密钥，解锁强大的智能创作能力',
            saveAllConfig: '保存所有配置',
            storageStatus: '存储情况',
            projectOverview: '项目概览',
            used: '已用 --',
            total: '总计 --',

            // ==================== settings快捷导航 ====================
            originalCommentary: '原创解说',
            aiVoiceover: 'AI配音',
            editorMode: '编辑器',

            // ==================== 设置页面UI ====================
            editorLayout: '编辑器布局',
            autoCollapseSidebar: '默认折叠右侧属性栏',
            autoCollapseTip: '开启：进入编辑器时自动折叠；关闭：记住上次状态',
            resetDefault: '恢复默认',
            saveSettings: '保存设置',

            // ==================== 项目操作 ====================
            projectName: '项目名称',
            projectDescription: '项目描述',
            createProject: '创建项目',
            openProject: '打开项目',
            deleteProject: '删除项目',
            duplicateProject: '复制项目',
            exportProject: '导出项目',
            importProject: '导入项目',
            projectCreated: '项目创建成功',
            projectSaved: '项目已保存',
            projectDeleted: '项目已删除',
            confirmDelete: '确定要删除此项目吗？',

            // ==================== 素材库 ====================
            uploadMaterial: '上传素材',
            dragDropHint: '拖拽文件到此处或点击上传',
            supportedFormats: '支持的格式',
            materialDeleted: '素材已删除',
            batchImport: '批量导入',
            folderImport: '导入文件夹',
            searchMaterials: '搜索素材...',
            sortBy: '排序方式',
            filterBy: '筛选方式',
            dateAdded: '添加日期',
            name: '名称',
            duration: '时长',
            size: '大小',
            type: '类型',
            video: '视频',
            audio: '音频',
            image: '图片',

            // ==================== 视频编辑 ====================
            addClip: '添加片段',
            removeClip: '删除片段',
            trimClip: '裁剪片段',
            splitClip: '分割片段',
            mergeClips: '合并片段',
            undo: '撤销',
            redo: '重做',
            preview: '预览',
            fullscreen: '全屏',
            timeline: '时间线',
            zoomIn: '放大',
            zoomOut: '缩小',
            fitToWindow: '适应窗口',

            // ==================== AI功能 ====================
            aiDubbingTitle: 'AI配音',
            aiSubtitleTitle: 'AI字幕',
            aiClipTitle: 'AI智能剪辑',
            aiEnhanceTitle: 'AI增强',
            selectVoice: '选择音色',
            voicePreview: '试听音色',
            generateDubbing: '生成配音',
            subtitleStyle: '字幕样式',
            subtitlePosition: '字幕位置',
            generateSubtitles: '生成字幕',
            autoDetectScenes: '自动检测场景',
            highlightSelection: '精彩片段',
            qualityEnhancement: '质量增强',

            // ==================== 设置页面 ====================
            // API配置
            apiConfig: 'API配置',
            apiKey: 'API密钥',
            baseUrl: '接口地址',
            model: '模型',
            testConnection: '测试连接',
            connectionSuccess: '连接成功',
            connectionFailed: '连接失败',
            saveConfig: '保存配置',

            // 视觉模型
            visionModels: '视觉模型',
            gpt4v: 'GPT-4V',
            claudeVision: 'Claude Vision',
            geminiVision: 'Gemini Vision',
            qwenVL: 'Qwen-VL',

            // 语音模型
            voiceModels: '语音模型',
            azureTTS: 'Azure语音合成',
            volcanoVoice: '火山引擎语音克隆',
            selectRegion: '选择区域',
            previewAudio: '试听音频',

            // 图片生成
            imageModels: '图片生成',
            dalle: 'DALL-E',
            tongyiWanxiang: '通义万相',
            wenxinYige: '文心一格',
            cogview: 'CogView',
            doubaoImage: '豆包生图',
            siliconFlow: 'SiliconFlow',

            // 外观设置
            appearance: '外观',
            theme: '主题',
            themeMode: '主题模式',
            themeColor: '主题颜色',
            lightMode: '浅色模式',
            darkMode: '深色模式',
            autoMode: '跟随系统',
            transparency: '透明度',
            interfaceScale: '界面缩放',

            // 语言设置
            language: '语言',
            chinese: '中文',
            english: 'English',
            selectLanguage: '选择语言',

            // 文件设置
            fileSettings: '文件设置',
            defaultSavePath: '默认保存路径',
            exportFormat: '导出格式',
            videoQuality: '视频质量',
            autoSave: '自动保存',
            autoSaveInterval: '自动保存间隔',
            minutes: '分钟',

            // 通知设置
            notificationSettings: '通知设置',
            desktopNotification: '桌面通知',
            soundAlert: '声音提示',
            taskCompleteNotification: '任务完成通知',
            errorNotification: '错误通知',
            enable: '启用',
            disable: '禁用',

            // 性能设置
            performance: '性能',
            gpuAcceleration: 'GPU加速',
            multiThreading: '多线程',
            aiModelQuality: 'AI模型质量',
            memoryLimit: '内存限制',
            low: '低',
            medium: '中',
            high: '高',

            // 高级设置
            advanced: '高级',
            ffmpegPath: 'FFmpeg路径',
            selectFFmpeg: '选择FFmpeg',
            proxySettings: '代理设置',
            proxyEnabled: '启用代理',
            proxyAddress: '代理地址',
            logLevel: '日志级别',
            debug: '调试',
            info: '信息',
            warning: '警告',
            error: '错误',
            autoUpdate: '自动更新',
            developerMode: '开发者模式',

            // 关于
            about: '关于',
            systemInfo: '系统信息',
            version: '版本',
            checkUpdate: '检查更新',
            officialWebsite: '官方网站',
            documentation: '使用文档',
            reportIssue: '报告问题',
            license: '许可证',

            // ==================== 通用按钮和提示 ====================
            confirm: '确认',
            cancel: '取消',
            close: '关闭',
            apply: '应用',
            reset: '重置',
            clear: '清空',
            delete: '删除',
            edit: '编辑',
            add: '添加',
            remove: '移除',
            copy: '复制',
            paste: '粘贴',
            download: '下载',
            upload: '上传',
            loading: '加载中...',
            processing: '处理中...',
            success: '成功',
            failed: '失败',
            warning: '警告',
            error: '错误',
            tips: '提示',
            help: '帮助',
            yes: '是',
            no: '否',
            ok: '确定',
            done: '完成',
            next: '下一步',
            previous: '上一步',
            finish: '完成',
            skip: '跳过',
            back: '返回',
            search: '搜索',
            refresh: '刷新',
            selectAll: '全选',
            deselectAll: '取消全选',
            selectFile: '选择文件',
            selectFolder: '选择文件夹',
            browse: '浏览',
            chooseFile: '选择文件',
            openSettings: '打开设置',

            // ==================== 错误消息 ====================
            networkError: '网络错误，请检查网络连接',
            serverError: '服务器错误，请稍后重试',
            fileNotFound: '文件未找到',
            invalidFormat: '无效的格式',
            fileTooLarge: '文件过大',
            unsupportedFormat: '不支持的格式',
            insufficientSpace: '磁盘空间不足',
            permissionDenied: '权限不足',
            unknownError: '未知错误',

            // ==================== 任务状态 ====================
            taskQueue: '任务队列',
            taskProgress: '任务进度',
            taskCompleted: '任务完成',
            taskFailed: '任务失败',
            taskPaused: '任务暂停',
            taskCancelled: '任务取消',
            taskPending: '等待中',
            taskRunning: '运行中',
            estimatedTime: '预计剩余时间',
            remaining: '剩余',

            // ==================== 混剪功能 ====================
            remixMode: '混剪模式',
            importVideos: '导入视频',
            batchProcess: '批量处理',
            selectTemplate: '选择模板',
            remixStyle: '混剪风格',
            beatMatch: '节拍匹配',
            autoTransition: '自动转场',
            generatePreview: '生成预览',
            exportHighQuality: '高质量导出',

            // ==================== 解说功能 ====================
            commentaryMode: '解说模式',
            scriptEditor: '脚本编辑',
            voiceSelection: '音色选择',
            backgroundMusic: '背景音乐',
            generateCommentary: '生成解说',
            adjustTiming: '调整时长',
            syncWithVideo: '与视频同步',

            // ==================== 配音功能 ====================
            voiceoverMode: '配音模式',
            textToSpeech: '文字转语音',
            voiceClone: '声音克隆',
            recordAudio: '录制音频',
            importAudio: '导入音频',
            adjustPitch: '调整音调',
            adjustSpeed: '调整语速',

            // ==================== 字幕功能 ====================
            subtitleMode: '字幕模式',
            importSubtitle: '导入字幕',
            exportSubtitle: '导出字幕',
            subtitleFormat: '字幕格式',
            srtFormat: 'SRT',
            assFormat: 'ASS',
            vttFormat: 'VTT',
            fontSize: '字体大小',
            fontColor: '字体颜色',
            fontFamily: '字体',
            outline: '描边',
            shadow: '阴影',
            backgroundColor: '背景颜色',

            // ==================== 高级功能 ====================
            batchExport: '批量导出',
            scheduledExport: '定时导出',
            exportQueue: '导出队列',
            watermark: '水印',
            addWatermark: '添加水印',
            watermarkPosition: '水印位置',
            watermarkOpacity: '水印透明度',

            // ==================== 工具提示 ====================
            uploadTip: '点击或拖拽文件上传',
            projectTip: '点击打开项目',
            settingsTip: '配置应用设置',
            saveTip: '保存当前项目',
            exportTip: '导出当前项目',
            helpTip: '查看帮助文档'
        }
    };

    // 语言标准化
    function normalize(language) {
        if (!language) return defaultLanguage;
        var lang = String(language).toLowerCase();
        if (lang.indexOf('zh') === 0 || lang === 'chinese' || lang === '中文') {
            return 'zh-CN';
        }
        return 'en-US';
    }

    // 获取保存的语言
    function savedLanguage() {
        try {
            var value = JSON.parse(localStorage.getItem(storageKey) || '{}');
            return normalize(value.app);
        } catch (error) {
            return defaultLanguage;
        }
    }

    // 翻译单个key
    function translate(key, language) {
        var dictionary = messages[normalize(language)];
        return dictionary[key] || key;
    }

    // 应用翻译到页面
    function apply(language) {
        language = normalize(language);
        document.documentElement.lang = language;
        document.documentElement.dir = 'ltr';

        // 翻译带有data-i18n属性的元素
        var selector = '[data-i18n], [data-i18n-title], [data-i18n-placeholder], [data-i18n-aria-label]';
        var elements = document.querySelectorAll(selector);
        for (var i = 0; i < elements.length; i++) {
            var element = elements[i];
            var key = element.getAttribute('data-i18n');
            if (key) {
                var translation = translate(key, language);
                // 如果元素包含HTML，先保留HTML结构只翻译文本节点
                if (element.children.length === 0) {
                    element.textContent = translation;
                } else {
                    // 如果有子元素，尝试翻译第一个文本节点
                    var textNode = null;
                    for (var j = 0; j < element.childNodes.length; j++) {
                        if (element.childNodes[j].nodeType === Node.TEXT_NODE) {
                            textNode = element.childNodes[j];
                            break;
                        }
                    }
                    if (textNode) {
                        textNode.textContent = translation;
                    }
                }
            }

            var titleKey = element.getAttribute('data-i18n-title');
            if (titleKey) element.title = translate(titleKey, language);

            var placeholderKey = element.getAttribute('data-i18n-placeholder');
            if (placeholderKey) element.placeholder = translate(placeholderKey, language);

            var ariaKey = element.getAttribute('data-i18n-aria-label');
            if (ariaKey) element.setAttribute('aria-label', translate(ariaKey, language));
        }

        // 触发翻译完成事件
        document.dispatchEvent(new CustomEvent('jjyb-i18n-applied', { detail: { language: language } }));
    }

    // 保存并应用语言
    function persist(language) {
        language = normalize(language);
        var value = {};
        try { value = JSON.parse(localStorage.getItem(storageKey) || '{}') || {}; } catch (error) {}
        value.app = language;
        try { localStorage.setItem(storageKey, JSON.stringify(value)); } catch (error) {}
        apply(language);
    }

    // 公开API
    window.appI18n = {
        apply: apply,
        applySettings: function (settings) { apply(settings && settings.app); },
        setLanguage: persist,
        getLanguage: savedLanguage,
        t: function (key) { return translate(key, savedLanguage()); },
        // 获取所有支持的语言
        getSupportedLanguages: function () {
            return [
                { code: 'zh-CN', name: '中文', nativeName: '中文' },
                { code: 'en-US', name: 'English', nativeName: 'English' }
            ];
        },
        // 获取所有翻译key
        getAllKeys: function () {
            return Object.keys(messages['en-US']);
        },
        // 翻译函数别名
        translate: translate
    };

    // DOM加载完成后应用翻译
    document.addEventListener('DOMContentLoaded', function () { apply(savedLanguage()); });

    // 监听localStorage变化
    window.addEventListener('storage', function (event) {
        if (event.key === storageKey) apply(savedLanguage());
    });
}());
