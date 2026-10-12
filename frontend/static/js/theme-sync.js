/**
 * JJYB_AI智剪 - 全局设置同步（主题 + 其他设置）
 * 用于 commentary / remix / voiceover / projects / settings 等所有页面
 *
 * 工作原理：
 * 1. 在 <head> 中尽早加载，读取 localStorage 中的设置
 * 2. 立即向 <html> 应用 data-theme 属性，避免主题闪烁（FOUC）
 * 3. 同时注入 light-theme 的 CSS 覆盖样式
 * 4. 监听 storage 事件，当用户在设置页面更改后实时同步所有标签页
 * 5. 后端 /api/settings 中的配置作为兜底数据源
 *
 * 支持的设置模块：
 * - jjybAppearance: 外观设置（主题、颜色、字体、动画等）
 * - jjybLanguage: 语言设置
 * - jjybNotification: 通知设置
 * - jjybPerformance: 性能设置
 * - jjybAdvanced: 高级设置
 * - jjybFileSettings: 文件设置
 */
(function () {
    'use strict';

    // ====== 外观/主题同步 ======
    function parseAppearance() {
        try {
            return JSON.parse(localStorage.getItem('jjybAppearance') || '{}') || {};
        } catch (e) {
            return {};
        }
    }

    function resolveLight(appearance) {
        var theme = (appearance && appearance.theme) || 'system';
        if (theme === 'light') return true;
        if (theme === 'dark') return false;
        // system: 跟随系统
        return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches;
    }

    function applyAppearance(appearance) {
        appearance = appearance || {};
        var root = document.documentElement;
        var isLight = resolveLight(appearance);

        // 在 <html> 上设置 data-theme，方便 CSS 选择器
        root.setAttribute('data-theme', isLight ? 'light' : 'dark');
        if (document.body) {
            document.body.classList.toggle('light-theme', isLight);
            document.body.classList.toggle('dark-theme', !isLight);
        } else {
            // body 还未生成，等待 DOMContentLoaded
            document.addEventListener('DOMContentLoaded', function () {
                document.body.classList.toggle('light-theme', isLight);
                document.body.classList.toggle('dark-theme', !isLight);
            });
        }

        // CSS 变量：与 base.html 保持一致
        var primary = (appearance.themeColor) || '#165DFF';
        root.style.setProperty('--primary-color', primary);
        root.style.setProperty('--theme-primary', primary);
        var opacityValue = Number(appearance.opacity || 90) / 100;
        opacityValue = Math.max(0.5, Math.min(1, opacityValue));
        root.style.setProperty('--theme-opacity', String(opacityValue));

        var fontMap = { small: '14px', normal: '16px', large: '18px' };
        root.style.setProperty('--theme-font-size', fontMap[appearance.fontSize] || '16px');

        var iconMap = { small: '0.85', normal: '1', large: '1.15' };
        root.style.setProperty('--theme-icon-size', iconMap[appearance.iconSize] || '1');

        root.classList.toggle('no-animations', appearance.animation === false);
        root.classList.toggle('no-glass', appearance.glassEffect === false);
    }

    function injectLightThemeCSS() {
        if (document.getElementById('jjyb-theme-sync-css')) return;
        var style = document.createElement('style');
        style.id = 'jjyb-theme-sync-css';
        style.textContent = [
            ':root { --primary-color: #165DFF; --theme-primary: #165DFF; --theme-opacity: .9; --theme-font-size: 16px; --theme-icon-size: 1; }',
            'html.no-animations *, html.no-animations *::before, html.no-animations *::after { animation: none !important; transition: none !important; }',
            'html.no-glass .glass-card, html.no-glass .glass-effect { backdrop-filter: none; -webkit-backdrop-filter: none; }',
            // 浅色主题背景与文字
            'body.light-theme { background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%) !important; color: #0f172a !important; }',
            'body.light-theme .glass-effect { background: rgba(255,255,255,var(--theme-opacity)) !important; border-color: rgba(148,163,184,.35) !important; box-shadow: 0 8px 32px rgba(15,23,42,.12) !important; }',
            'body.light-theme .glass-card { background: linear-gradient(135deg, rgba(255,255,255,var(--theme-opacity)), rgba(241,245,249,var(--theme-opacity))) !important; border-color: rgba(148,163,184,.35) !important; }',
            // 覆盖常见深色背景卡片
            'body.light-theme [style*="background: rgba(30,41,59"],',
            'body.light-theme [style*="background:rgba(30,41,59"],',
            'body.light-theme [style*="background: rgba(15,23,42"],',
            'body.light-theme [style*="background:rgba(15,23,42"],',
            'body.light-theme [style*="background: rgba(30, 41, 59"],',
            'body.light-theme [style*="background: rgba(15, 23, 42"],',
            'body.light-theme [style*="background-color: rgba(30,41,59"],',
            'body.light-theme [style*="background-color:rgba(30,41,59"],',
            'body.light-theme [style*="background-color: rgba(15,23,42"],',
            'body.light-theme [style*="background-color:rgba(15,23,42"],',
            'body.light-theme [style*="background-color: rgba(30, 41, 59"],',
            'body.light-theme [style*="background-color: rgba(15, 23, 42"],',
            'body.light-theme [style*="background: linear-gradient(135deg, rgba(30,"],',
            'body.light-theme [style*="background:linear-gradient(135deg, rgba(30,"],',
            'body.light-theme [style*="background: linear-gradient(135deg, rgba(15,"],',
            'body.light-theme [style*="background:linear-gradient(135deg, rgba(15,"] { background: rgba(255,255,255,0.85) !important; background-color: rgba(255,255,255,0.85) !important; }',
            // 文字颜色覆盖：白色文字改为深色
            'body.light-theme [style*="color: white"],',
            'body.light-theme [style*="color:white"],',
            'body.light-theme [style*="color: #fff"],',
            'body.light-theme [style*="color:#fff"],',
            'body.light-theme [style*="color: #FFFFFF"],',
            'body.light-theme [style*="color:#FFFFFF"],',
            'body.light-theme [style*="color: rgba(255,255,255,0.9)"],',
            'body.light-theme [style*="color:rgba(255,255,255,0.9)"],',
            'body.light-theme [style*="color: rgba(255,255,255,0.95)"],',
            'body.light-theme [style*="color:rgba(255,255,255,0.95)"],',
            'body.light-theme [style*="color: rgba(255, 255, 255, 0.9)"],',
            'body.light-theme [style*="color: rgba(255, 255, 255, 0.95)"],',
            'body.light-theme [style*="color: #F8FAFC"],',
            'body.light-theme [style*="color:#F8FAFC"],',
            'body.light-theme [style*="color: #f8fafc"],',
            'body.light-theme [style*="color:#f8fafc"] { color: #1e293b !important; }',
            'body.light-theme [style*="color: rgba(255,255,255,0.6)"],',
            'body.light-theme [style*="color:rgba(255,255,255,0.6)"],',
            'body.light-theme [style*="color: rgba(255, 255, 255, 0.6)"],',
            'body.light-theme [style*="color: rgba(255,255,255,0.7)"],',
            'body.light-theme [style*="color:rgba(255,255,255,0.7)"] { color: #475569 !important; }',
            // 输入框、文本域、选择框背景
            'body.light-theme input, body.light-theme textarea, body.light-theme select { background-color: rgba(255,255,255,0.9) !important; color: #1e293b !important; border-color: rgba(148,163,184,.35) !important; }',
            'body.light-theme input::placeholder, body.light-theme textarea::placeholder { color: #94a3b8 !important; }',
            // layui-layer 弹层也跟随浅色
            'body.light-theme .layui-layer, body.light-theme .layui-layer-msg { background: #ffffff !important; color: #1e293b !important; border-color: rgba(148,163,184,.35) !important; }',
            // 滚动条适配
            'body.light-theme ::-webkit-scrollbar-thumb { background: rgba(148,163,184,.5) !important; }',
            'body.light-theme ::-webkit-scrollbar-track { background: rgba(241,245,249,.8) !important; }',
            // 透明背景容器（如按钮 hover）保留原色但增加可读性
            'body.light-theme .text-text-primary { color: #0f172a !important; }',
            'body.light-theme .text-text-secondary { color: #475569 !important; }',
            // ====== 基于 CSS 类的白色文字覆盖（独立页面） ======
            // 首页 logo/tagline/subtitle
            'body.light-theme .logo { background: linear-gradient(135deg, #1e293b 0%, #475569 100%) !important; -webkit-background-clip: text !important; background-clip: text !important; -webkit-text-fill-color: transparent !important; text-shadow: none !important; }',
            'body.light-theme .tagline { color: #1e293b !important; }',
            'body.light-theme .subtitle { color: #475569 !important; }',
            // 各独立页面顶部标题（page-header / header）
            'body.light-theme .page-header h1, body.light-theme .page-header p { color: #1e293b !important; text-shadow: none !important; }',
            'body.light-theme .header h1, body.light-theme .header p { color: #1e293b !important; text-shadow: none !important; }',
            'body.light-theme .header .logo { color: #1e293b !important; }',
            // 模式选择页面
            'body.light-theme .mode-title { color: #1e293b !important; }',
            'body.light-theme .mode-description { color: #475569 !important; }',
            'body.light-theme .mode-features li { color: #475569 !important; }',
            // 导航按钮文字（在浅色背景下）
            'body.light-theme .nav-btn { color: #1e293b !important; background: rgba(255,255,255,0.85) !important; border-color: rgba(148,163,184,.35) !important; }',
            'body.light-theme .back-button { color: #1e293b !important; background: rgba(255,255,255,0.9) !important; }',
            // 快捷链接
            'body.light-theme .quick-link { color: #1e293b !important; background: rgba(255,255,255,0.9) !important; border-color: rgba(148,163,184,.35) !important; }',
            // 首页导航提示文字
            'body.light-theme .nav-hint { color: #475569 !important; }',
            // 菜单徽章（设置页面"核心"等标签）
            'body.light-theme .menu-badge { color: #1e293b !important; background: rgba(100,116,139,0.15) !important; }',
            // 通用：浅色主题下页面标题/副标题（仅直接在 body 背景上的）
            'body.light-theme .page-title, body.light-theme .section-title { color: #1e293b !important; }'
        ].join('\n');
        document.head.appendChild(style);
    }

    // ====== 初始化 ======
    // 1. 先注入 CSS（不依赖 body）
    injectLightThemeCSS();
    // 2. 立即应用主题
    applyAppearance(parseAppearance());

    // 3. 监听系统主题变化（仅在 system 模式下生效）
    if (window.matchMedia) {
        var media = window.matchMedia('(prefers-color-scheme: light)');
        if (media.addEventListener) {
            media.addEventListener('change', function () {
                var saved = parseAppearance();
                if (!saved.theme || saved.theme === 'system') {
                    applyAppearance(saved);
                }
            });
        } else if (media.addListener) {
            media.addListener(function () {
                var saved = parseAppearance();
                if (!saved.theme || saved.theme === 'system') {
                    applyAppearance(saved);
                }
            });
        }
    }

    function applyLanguage(settings) {
        if (settings && settings.app && window.appI18n) {
            window.appI18n.apply(settings.app);
        }
    }

    document.addEventListener('jjyb-language-changed', function (event) {
        applyLanguage(event.detail);
    });

    // 4. 监听跨标签页 storage 事件
    window.addEventListener('storage', function (event) {
        if (event.key === 'jjybAppearance') {
            try {
                applyAppearance(JSON.parse(event.newValue || '{}'));
            } catch (e) {
                // ignore parse errors
            }
        }
        if (event.key === 'jjybLanguage') {
            try { applyLanguage(JSON.parse(event.newValue || '{}')); } catch (e) {}
        }
    });

    // 5. 暴露给全局以便其他脚本调用
    window.applyJJYBAppearance = function (appearance) {
        applyAppearance(appearance || {});
        try { localStorage.setItem('jjybAppearance', JSON.stringify(appearance || {})); } catch (e) {}
    };

    // 6. 启动后从后端拉取一次最新设置作为兜底
    //    优先级：localStorage（用户本地偏好） > 后端（兜底默认值）
    //    仅当 localStorage 中缺少某字段时，才用后端值填充
    try {
        document.addEventListener('DOMContentLoaded', function () {
            var localData = parseAppearance();
            fetch('/api/settings', { cache: 'no-cache' })
                .then(function (r) { return r.json(); })
                .then(function (result) {
                    if (result && result.code === 0 && result.data && result.data.appearance) {
                        var serverAppearance = result.data.appearance || {};
                        // 以本地为准，仅用后端填补本地缺失的字段
                        var merged = {};
                        var allKeys = Object.keys(serverAppearance).concat(Object.keys(localData));
                        for (var i = 0; i < allKeys.length; i++) {
                            var k = allKeys[i];
                            if (localData[k] !== undefined && localData[k] !== null && localData[k] !== '') {
                                merged[k] = localData[k];
                            } else if (serverAppearance[k] !== undefined && serverAppearance[k] !== null) {
                                merged[k] = serverAppearance[k];
                            }
                        }
                        applyAppearance(merged);
                        // 同步回 localStorage，确保一致性
                        try { localStorage.setItem('jjybAppearance', JSON.stringify(merged)); } catch (e) {}

                        // 同步其他设置模块（从后端拉取到 localStorage，作为兜底）
                        var otherModules = ['language', 'file', 'notification', 'performance', 'advanced'];
                        var storageKeys = {
                            language: 'jjybLanguage',
                            file: 'jjybFileSettings',
                            notification: 'jjybNotification',
                            performance: 'jjybPerformance',
                            advanced: 'jjybAdvanced'
                        };
                        otherModules.forEach(function (mod) {
                            if (result.data[mod]) {
                                var storageKey = storageKeys[mod];
                                try {
                                    var localVal = localStorage.getItem(storageKey);
                                    if (!localVal) {
                                        localStorage.setItem(storageKey, JSON.stringify(result.data[mod]));
                                        if (mod === 'language') applyLanguage(result.data[mod]);
                                    }
                                } catch (e) {}
                            }
                        });
                    }
                })
                .catch(function () { /* 静默失败，保留 localStorage 数据 */ });
        });
    } catch (e) { /* ignore */ }

    // ====== 其他设置模块同步 ======
    // 通用：解析 localStorage 中的设置
    function parseSettings(storageKey) {
        try { return JSON.parse(localStorage.getItem(storageKey) || '{}') || {}; }
        catch (e) { return {}; }
    }

    // 应用高级设置（开发者模式等）
    function applyAdvancedSettings(settings) {
        if (!settings) return;
        var root = document.documentElement;
        if (settings.developerMode === true) {
            root.classList.add('developer-mode');
        } else {
            root.classList.remove('developer-mode');
        }
    }

    // 暴露全局方法
    window.jjybGetSetting = function (module, key, defaultValue) {
        var storageMap = {
            appearance: 'jjybAppearance',
            language: 'jjybLanguage',
            file: 'jjybFileSettings',
            notification: 'jjybNotification',
            performance: 'jjybPerformance',
            advanced: 'jjybAdvanced'
        };
        var storageKey = storageMap[module];
        if (!storageKey) return defaultValue;
        var settings = parseSettings(storageKey);
        if (key === undefined || key === null) return settings;
        return settings[key] !== undefined ? settings[key] : defaultValue;
    };

    // 设置变更事件分发（跨页面通过 storage 事件同步）
    var moduleStorageMap = {
        'jjybAppearance': 'appearance',
        'jjybLanguage': 'language',
        'jjybFileSettings': 'file',
        'jjybNotification': 'notification',
        'jjybPerformance': 'performance',
        'jjybAdvanced': 'advanced'
    };

    window.addEventListener('storage', function (event) {
        // 外观主题同步（原有功能）
        if (event.key === 'jjybAppearance') {
            try {
                applyAppearance(JSON.parse(event.newValue || '{}'));
                document.dispatchEvent(new CustomEvent('jjyb-appearance-changed', {
                    detail: JSON.parse(event.newValue || '{}')
                }));
            } catch (e) { /* ignore parse errors */ }
        }

        // 高级设置同步
        if (event.key === 'jjybAdvanced') {
            try {
                var adv = JSON.parse(event.newValue || '{}');
                applyAdvancedSettings(adv);
                document.dispatchEvent(new CustomEvent('jjyb-advanced-changed', { detail: adv }));
            } catch (e) {}
        }

        // 其他设置模块 - 只分发事件，由各页面自行处理
        var moduleName = moduleStorageMap[event.key];
        if (moduleName && moduleName !== 'appearance' && moduleName !== 'advanced') {
            try {
                var detail = JSON.parse(event.newValue || '{}');
                var eventName = moduleName === 'file'
                    ? 'jjyb-file-settings-changed'
                    : 'jjyb-' + moduleName + '-changed';
                document.dispatchEvent(new CustomEvent(eventName, { detail: detail }));
            } catch (e) {}
        }
    });

    // 初始应用高级设置
    try {
        applyAdvancedSettings(parseSettings('jjybAdvanced'));
    } catch (e) {}

    console.log('✅ JJYB 全局设置同步已加载（主题 + 语言 + 通知 + 性能 + 高级 + 文件）');
})();
