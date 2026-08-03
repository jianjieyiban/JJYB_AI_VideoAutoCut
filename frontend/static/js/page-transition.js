/**
 * 页面预加载辅助。
 * 普通链接保留浏览器原生导航，避免替换 body 或显示切换遮罩。
 */
(function() {
    'use strict';

    const CONFIG = {
        cacheEnabled: true,
        preloadEnabled: true,
        maxCacheSize: 10
    };
    const pageCache = new Map();
    const preloadQueue = new Set();

    function cachePage(url, html) {
        if (!CONFIG.cacheEnabled) return;
        if (pageCache.size >= CONFIG.maxCacheSize) {
            pageCache.delete(pageCache.keys().next().value);
        }
        pageCache.set(url, html);
    }

    async function preloadPage(url) {
        if (!CONFIG.preloadEnabled || !url || pageCache.has(url) || preloadQueue.has(url)) return;

        preloadQueue.add(url);
        try {
            const response = await fetch(url, {
                method: 'GET',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            if (response.ok) {
                cachePage(url, await response.text());
            }
        } catch (error) {
            console.warn('页面预加载失败:', url);
        } finally {
            preloadQueue.delete(url);
        }
    }

    function handleLinkHover(event) {
        const link = event.target.closest('a[href]');
        if (!link || link.target === '_blank' || link.hasAttribute('download')) return;

        const href = link.getAttribute('href');
        if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;

        const url = new URL(href, window.location.href);
        if (url.origin === window.location.origin) {
            preloadPage(url.pathname + url.search);
        }
    }

    function init() {
        document.addEventListener('mouseenter', handleLinkHover, true);
        document.addEventListener('focusin', handleLinkHover, true);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.PageTransition = {
        preloadPage,
        clearCache: () => pageCache.clear(),
        config: CONFIG
    };
})();
