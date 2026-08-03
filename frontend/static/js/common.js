/**
 * JJYB_AI智剪 - 通用JavaScript工具库
 * 提供所有页面共用的功能
 */

// 全局配置
const APP_CONFIG = {
    apiBase: '/api',
    socketUrl: window.location.origin,
    uploadMaxSize: 500 * 1024 * 1024 // 500MB
};

// Socket.IO连接管理
class SocketManager {
    constructor() {
        this.socket = null;
        this.connected = false;
        this.init();
    }

    init() {
        try {
            if (typeof io !== 'undefined') {
                this.socket = io(APP_CONFIG.socketUrl);

                this.socket.on('connect', () => {
                    this.connected = true;
                    console.log('✅ Socket.IO 连接成功');
                });

                this.socket.on('disconnect', () => {
                    this.connected = false;
                    console.log('⚠️ Socket.IO 连接断开');
                });

                this.socket.on('error', (error) => {
                    console.error('❌ Socket.IO 错误:', error);
                });
            } else {
                console.warn('⚠️ Socket.IO 未加载');
            }
        } catch (error) {
            console.error('❌ Socket.IO 初始化失败:', error);
        }
    }

    on(event, callback) {
        if (this.socket) {
            this.socket.on(event, callback);
        }
    }

    emit(event, data) {
        if (this.socket && this.connected) {
            this.socket.emit(event, data);
        }
    }
}

// 创建全局Socket管理器
const socketManager = new SocketManager();

// Layui layer 兜底实现：CDN 未加载时提供可关闭、非阻塞的最小兼容层
(function () {
    if (typeof window === 'undefined' || typeof window.layer !== 'undefined') return;

    let nextId = 1;
    const instances = {};
    const topId = () => Object.keys(instances).map(Number).sort((a, b) => b - a)[0];
    const close = (id) => {
        const instance = instances[id];
        if (!instance) return;
        if (instance.timer) clearTimeout(instance.timer);
        if (instance.node && instance.node.parentNode) instance.node.parentNode.removeChild(instance.node);
        delete instances[id];
        if (typeof instance.options.end === 'function') instance.options.end();
    };
    const runCancel = (id) => {
        const instance = instances[id];
        if (!instance) return;
        if (typeof instance.options.cancel === 'function' && instance.options.cancel(id) === false) return;
        close(id);
    };
    const createMask = (shade) => {
        const mask = document.createElement('div');
        mask.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:' + (shade === 0 ? 'transparent' : 'rgba(0,0,0,.35)');
        return mask;
    };
    const open = (options) => {
        const opts = options || {}, id = nextId++, mask = createMask(opts.shade);
        const box = document.createElement('div');
        box.style.cssText = 'background:#172033;color:#f8fafc;border:1px solid rgba(148,163,184,.28);border-radius:12px;max-width:90vw;max-height:90vh;overflow:auto;box-shadow:0 10px 30px rgba(0,0,0,.25);font-size:13px;';
        if (Array.isArray(opts.area)) { if (opts.area[0]) box.style.width = opts.area[0]; if (opts.area[1]) box.style.height = opts.area[1]; }
        if (opts.title) {
            const header = document.createElement('div');
            header.style.cssText = 'padding:10px 14px;border-bottom:1px solid rgba(148,163,184,.2);display:flex;align-items:center;justify-content:space-between;font-weight:600;';
            const title = document.createElement('span'); title.textContent = opts.title;
            const closeBtn = document.createElement('button'); closeBtn.type = 'button'; closeBtn.textContent = '×'; closeBtn.setAttribute('aria-label', '关闭'); closeBtn.style.cssText = 'border:0;background:transparent;color:#cbd5e1;font-size:20px;cursor:pointer;';
            closeBtn.addEventListener('click', () => runCancel(id));
            header.append(title, closeBtn); box.appendChild(header);
        }
        const body = document.createElement('div'); body.style.padding = '14px'; body.innerHTML = typeof opts.content === 'string' ? opts.content : ''; box.appendChild(body);
        if (Array.isArray(opts.btn) && opts.btn.length) {
            const footer = document.createElement('div'); footer.style.cssText = 'padding:10px 14px;display:flex;justify-content:flex-end;gap:8px;border-top:1px solid rgba(148,163,184,.2);';
            opts.btn.forEach((label, index) => { const button = document.createElement('button'); button.type = 'button'; button.textContent = label; button.style.cssText = 'display:inline-block;box-sizing:border-box;min-width:60px;height:32px;line-height:30px;padding:0 16px;border-radius:7px;border:1px solid ' + (index === 0 ? '#2563eb' : 'rgba(148,163,184,.3)') + ';background:' + (index === 0 ? '#2563eb' : 'rgba(148,163,184,.16)') + ';color:#fff;cursor:pointer;white-space:nowrap;text-align:center;'; button.addEventListener('click', () => index === 0 && typeof opts.yes === 'function' ? opts.yes(id, box) : runCancel(id)); footer.appendChild(button); });
            box.appendChild(footer);
        }
        if (opts.shadeClose) mask.addEventListener('click', (event) => { if (event.target === mask) runCancel(id); });
        mask.appendChild(box); document.body.appendChild(mask); instances[id] = { node: mask, options: opts };
        if (typeof opts.success === 'function') opts.success(box, id);
        return id;
    };
    const toast = (text, opts) => {
        if (typeof window.showNotification === 'function') { window.showNotification('提示', text, (opts && opts.icon === 2) ? 'error' : 'info'); return 0; }
        const id = nextId++, node = document.createElement('div');
        node.className = 'layui-layer-msg'; node.textContent = text;
        node.style.cssText = 'position:fixed;top:76px;left:50%;transform:translateX(-50%);z-index:1200;max-width:calc(100vw - 32px);padding:12px 16px;border-radius:12px;background:#172033;color:#f8fafc;pointer-events:none;';
        document.body.appendChild(node); instances[id] = { node, options: {}, timer: setTimeout(() => close(id), (opts && opts.time) || 3000) }; return id;
    };
    window.layer = {
        open,
        close,
        closeAll: () => Object.keys(instances).forEach((id) => close(Number(id))),
        closeTop: () => { const id = topId(); if (id) runCancel(id); },
        msg: toast,
        load: (icon, opts) => open(Object.assign({ title: false, content: '<div style="min-width:120px;text-align:center">处理中...</div>', shade: [0.3, '#000'], shadeClose: false }, opts || {})),
        confirm: (text, opts, yes, cancel) => open(Object.assign({}, opts || {}, { content: text, btn: (opts && opts.btn) || ['确认', '取消'], yes: function (id) { if (typeof yes === 'function') yes(id); } , cancel: cancel }))
    };
})();

// API请求封装
class API {
    static async request(url, options = {}) {
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json'
            }
        };

        const config = { ...defaultOptions, ...options };

        let response;
        try {
            response = await fetch(url, config);
        } catch (error) {
            console.error('API请求失败(网络错误):', error);
            throw new Error('网络请求失败，请检查服务是否正在运行');
        }

        // 优先尝试解析JSON（后端错误响应也使用 jsonify 返回结构化数据）
        let data = null;
        const rawText = await response.text();
        if (rawText) {
            try {
                data = JSON.parse(rawText);
            } catch (_) {
                // 响应不是JSON（可能是HTML错误页）
                if (!response.ok) {
                    console.error(`API请求失败: HTTP ${response.status} ${response.statusText}`, url);
                    throw new Error(`服务器返回错误 (HTTP ${response.status})，请稍后重试或检查后端日志`);
                }
                throw new Error('服务器返回了非JSON响应，可能服务异常');
            }
        }

        // 即使解析成功，仍需检查HTTP状态码
        if (!response.ok && data && !data.code) {
            // 后端未返回结构化 code 字段，但HTTP状态非2xx
            console.error(`API请求失败: HTTP ${response.status}`, url, data);
            throw new Error(data.msg || data.message || `服务器返回错误 (HTTP ${response.status})`);
        }

        return data;
    }

    static async get(url) {
        return this.request(url, { method: 'GET' });
    }

    static async post(url, data) {
        return this.request(url, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    static async put(url, data) {
        return this.request(url, {
            method: 'PUT',
            body: JSON.stringify(data)
        });
    }

    static async delete(url) {
        return this.request(url, { method: 'DELETE' });
    }
}

// 文件上传处理
class FileUploader {
    constructor(options = {}) {
        this.maxSize = options.maxSize || APP_CONFIG.uploadMaxSize;
        this.acceptTypes = options.acceptTypes || '*';
        this.onProgress = options.onProgress || (() => {});
        this.onSuccess = options.onSuccess || (() => {});
        this.onError = options.onError || (() => {});
    }

    async upload(file, url) {
        // 检查文件大小
        if (file.size > this.maxSize) {
            this.onError(new Error(`文件大小超过限制 (${this.maxSize / 1024 / 1024}MB)`));
            return;
        }

        const formData = new FormData();
        formData.append('file', file);

        try {
            const xhr = new XMLHttpRequest();

            // 监听上传进度
            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) {
                    const percent = Math.round((e.loaded / e.total) * 100);
                    this.onProgress(percent);
                }
            });

            // 监听完成
            xhr.addEventListener('load', () => {
                if (xhr.status === 200) {
                    const response = JSON.parse(xhr.responseText);
                    this.onSuccess(response);
                } else {
                    this.onError(new Error(`上传失败: ${xhr.statusText}`));
                }
            });

            // 监听错误
            xhr.addEventListener('error', () => {
                this.onError(new Error('上传失败'));
            });

            xhr.open('POST', url);
            xhr.send(formData);
        } catch (error) {
            this.onError(error);
        }
    }
}

// 通知提示
class Notification {
    static success(message, duration = 3000) {
        this.show(message, 'success', duration);
    }

    static error(message, duration = 3000) {
        this.show(message, 'error', duration);
    }

    static warning(message, duration = 3000) {
        this.show(message, 'warning', duration);
    }

    static info(message, duration = 3000) {
        this.show(message, 'info', duration);
    }

    static show(message, type = 'info', duration = 3000) {
        if (typeof window.showNotification === 'function') {
            const title = { success: '成功', error: '错误', warning: '提示', info: '提示' }[type] || '提示';
            window.showNotification(title, message, type);
            return;
        }
        if (typeof layer !== 'undefined') {
            const icon = {
                'success': 1,
                'error': 2,
                'warning': 3,
                'info': 0
            }[type] || 0;

            layer.msg(message, {
                icon: icon,
                time: duration,
                offset: 't',
                anim: 2,
                shade: 0
            });
        }
    }

    static confirm(message, onConfirm, onCancel) {
        if (typeof layer !== 'undefined') {
            layer.confirm(message, {
                btn: ['确认', '取消']
            }, function(index) {
                if (onConfirm) onConfirm();
                layer.close(index);
            }, function() {
                if (onCancel) onCancel();
            });
        } else {
            if (confirm(message)) {
                if (onConfirm) onConfirm();
            } else {
                if (onCancel) onCancel();
            }
        }
    }
}

// 进度条管理
class ProgressBar {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.progressBar = null;
        this.progressText = null;
        this.init();
    }

    init() {
        if (!this.container) return;

        this.progressBar = this.container.querySelector('.progress-fill');
        this.progressText = this.container.querySelector('.progress-text');
    }

    show() {
        if (this.container) {
            this.container.style.display = 'block';
        }
    }

    hide() {
        if (this.container) {
            this.container.style.display = 'none';
        }
    }

    update(percent, message = '') {
        if (this.progressBar) {
            this.progressBar.style.width = percent + '%';
            this.progressBar.textContent = percent + '%';
        }
        if (this.progressText && message) {
            this.progressText.textContent = message;
        }
    }

    reset() {
        this.update(0, '');
        this.hide();
    }
}

// 表单验证
class FormValidator {
    static validate(formId, rules) {
        const form = document.getElementById(formId);
        if (!form) return false;

        const errors = [];

        for (const [field, rule] of Object.entries(rules)) {
            const element = form.querySelector(`[name="${field}"]`);
            if (!element) continue;

            const value = element.value.trim();

            // 必填验证
            if (rule.required && !value) {
                errors.push(`${rule.label || field} 不能为空`);
                continue;
            }

            // 最小长度验证
            if (rule.minLength && value.length < rule.minLength) {
                errors.push(`${rule.label || field} 长度不能小于 ${rule.minLength}`);
            }

            // 最大长度验证
            if (rule.maxLength && value.length > rule.maxLength) {
                errors.push(`${rule.label || field} 长度不能大于 ${rule.maxLength}`);
            }

            // 正则验证
            if (rule.pattern && !rule.pattern.test(value)) {
                errors.push(`${rule.label || field} 格式不正确`);
            }

            // 自定义验证
            if (rule.validator && !rule.validator(value)) {
                errors.push(rule.message || `${rule.label || field} 验证失败`);
            }
        }

        if (errors.length > 0) {
            Notification.error(errors[0]);
            return false;
        }

        return true;
    }
}

// 工具函数
const Utils = {
    // 格式化文件大小
    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
    },

    // 格式化时间
    formatTime(seconds) {
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);

        const parts = [];
        if (h > 0) parts.push(h.toString().padStart(2, '0'));
        parts.push(m.toString().padStart(2, '0'));
        parts.push(s.toString().padStart(2, '0'));

        return parts.join(':');
    },

    // 防抖
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },

    // 节流
    throttle(func, limit) {
        let inThrottle;
        return function(...args) {
            if (!inThrottle) {
                func.apply(this, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    },

    // 生成UUID
    generateUUID() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    },

    // 复制到剪贴板
    copyToClipboard(text) {
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text).then(() => {
                Notification.success('已复制到剪贴板');
            }).catch(err => {
                console.error('复制失败:', err);
                Notification.error('复制失败');
            });
        } else {
            // 备用方案
            const textarea = document.createElement('textarea');
            textarea.value = text;
            document.body.appendChild(textarea);
            textarea.select();
            try {
                document.execCommand('copy');
                Notification.success('已复制到剪贴板');
            } catch (err) {
                Notification.error('复制失败');
            }
            document.body.removeChild(textarea);
        }
    }
};

// 统一的后端错误信息简化函数
function simplifyBackendError(raw, defaultMsg) {
    if (!raw) return defaultMsg || '处理失败，请稍后重试。';
    const text = String(raw);
    const lower = text.toLowerCase();

    // 大模型 / API 鉴权相关错误
    if (
        lower.includes('api key') ||
        lower.includes('apikey') ||
        lower.includes('invalid authentication') ||
        lower.includes('unauthorized') ||
        lower.includes('permission denied') ||
        lower.includes('invalid api') ||
        lower.includes('missing api') ||
        text.includes('鉴权失败') ||
        text.includes('未配置') ||
        text.includes('密钥错误') ||
        text.includes('密钥无效')
    ) {
        return '调用大模型失败：API 密钥可能未配置或无效，请前往“系统设置 - API配置”检查对应模型的密钥、Base URL 和权限是否正确。';
    }

    // TTS / 配音相关错误
    if (lower.includes('edge-tts') || lower.includes('gtts') || lower.includes('pyttsx3') || lower.includes('azure') || lower.includes('tts')) {
        return '配音生成失败：底层语音合成引擎出错，建议更换配音引擎或稍后重试。';
    }

    // 视频/音频处理（FFmpeg）相关错误
    if (lower.includes('ffmpeg')) {
        if (lower.includes('no such file') || lower.includes('not found')) {
            return '视频处理失败：后端找不到对应的视频/音频文件，请检查素材是否已成功上传或是否被清理。';
        }
        if (lower.includes('invalid') || lower.includes('unknown')) {
            return '视频处理失败：FFmpeg 报告不支持的编码或损坏的媒体文件，建议先本地转码为常见 MP4(H.264/AAC) 后再尝试。';
        }
        if (lower.includes('out of memory')) {
            return '视频处理失败：处理过程中内存不足，建议降低分辨率、缩短时长或分段处理。';
        }
        return '视频处理失败：底层 FFmpeg 编码/转码出错，建议检查源文件格式并适当降低分辨率/时长后重试。';
    }

    // 音频分析（Librosa）相关错误
    if (lower.includes('librosa')) {
        if (lower.includes('no backend') || lower.includes('sndfile')) {
            return '音乐卡点分析失败：当前环境缺少音频解码依赖，暂不支持该音频格式，建议转换为标准 MP3/WAV 后再上传。';
        }
        return '音乐卡点分析失败：Librosa 在解析该音频文件时出错，可能是文件损坏或格式异常。';
    }

    // 通用文件不存在错误
    if (lower.includes('no such file') || lower.includes('file not found')) {
        return '处理失败：后端找不到对应的文件，请检查素材是否已成功上传或是否被清理。';
    }

    // 超时错误
    if (lower.includes('timeout') || lower.includes('timed out')) {
        return '处理失败：后端处理超时，可能是任务过长或服务器压力较大，建议缩短素材时长或稍后重试。';
    }

    // 连接失败错误
    if (lower.includes('connection') && lower.includes('refused')) {
        return '处理失败：无法连接后端服务，请确认服务是否正在运行。';
    }

    return defaultMsg || ('处理失败：' + text);
}

// 导出到全局
window.APP_CONFIG = APP_CONFIG;
window.socketManager = socketManager;
window.API = API;
window.FileUploader = FileUploader;
window.Notification = Notification;
window.ProgressBar = ProgressBar;
window.FormValidator = FormValidator;
window.Utils = Utils;
window.simplifyBackendError = simplifyBackendError;

console.log('✅ JJYB_AI智剪 通用工具库加载完成');
