// ========== JJYB_AI智剪 - 编辑器项目/素材/时间线闭环 ==========
window.addEventListener('load', () => {
    const state = window.__JJYB__ = window.__JJYB__ || {};
    const escapeHtml = value => String(value || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const notice = (message, type) => typeof window.showNotification === 'function'
        ? window.showNotification(type === 'error' ? '错误' : type === 'success' ? '成功' : '提示', message, type || 'info')
        : alert(message);
    const getProject = () => state.currentProject || (window.currentProjectId ? {id: window.currentProjectId} : null);
    const setProject = project => {
        state.currentProject = project || null;
        window.currentProjectId = project && project.id || '';
        try { sessionStorage.setItem('current_project_id', window.currentProjectId); sessionStorage.setItem('current_project_name', project && project.name || ''); } catch (_) {}
        const display = document.getElementById('project-name-display');
        if (display) display.textContent = project && project.name || '当前项目';
    };
    try {
        const projectId = sessionStorage.getItem('current_project_id');
        const projectName = sessionStorage.getItem('current_project_name');
        if (projectId && !state.currentProject) state.currentProject = {id: projectId, name: projectName || '当前项目'};
        if (projectId && !window.currentProjectId) window.currentProjectId = projectId;
    } catch (_) {}
    const requireProject = () => {
        const project = getProject();
        if (!project || !project.id) { notice('请先新建或打开一个项目', 'error'); return null; }
        return project;
    };
    const api = async (url, options) => {
        const response = await fetch(url, options);
        const data = await response.json();
        if (!response.ok || !data || data.code !== 0) throw new Error(data && data.msg || '请求失败');
        return data.data;
    };
    const outputSettings = () => ({
        format: document.getElementById('export-format-select')?.value || 'mp4',
        resolution: document.getElementById('export-resolution-select')?.value || '1920x1080',
        fps: document.getElementById('export-fps-select')?.value || '30',
        quality: document.getElementById('export-quality-select')?.value || 'medium',
        codec: document.getElementById('export-codec-select')?.value || 'h264'
    });

    window.newProject = async () => {
        const name = prompt('请输入项目名称：', '未命名项目');
        if (name === null) return;
        try {
            const project = await api('/api/projects', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({
                name: name || '未命名项目', type: 'video', description: '视频编辑项目', config: {editor: {tracks: [], track_states: {}}}
            })});
            setProject(project);
            if (typeof window.clearAllTracks === 'function') window.clearAllTracks();
            else document.querySelectorAll('[id$="-track-1"]').forEach(track => track.querySelectorAll('[data-type]').forEach(el => el.remove()));
            window.loadRecentProjects?.();
            notice('新项目创建成功', 'success');
        } catch (error) { notice('创建失败：' + error.message, 'error'); }
    };

    window.__JJYBSaveProject = window.saveProject = async () => {
        const project = requireProject(); if (!project) return;
        const editor = {
            tracks: typeof window.collectTracksData === 'function' ? window.collectTracksData() : [],
            track_states: window.trackStates || {}, current_filters: window.currentFilters || {}, export: outputSettings()
        };
        const displayedName = document.getElementById('project-name-display')?.textContent?.trim();
        const name = project.name || displayedName || sessionStorage.getItem('current_project_name') || '未命名项目';
        project.name = name;
        try {
            const updated = await api('/api/projects/' + encodeURIComponent(project.id), {method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({name, config: {editor}})});
            setProject(updated); notice('项目已保存', 'success');
        } catch (error) { notice('保存失败：' + error.message, 'error'); }
    };

    window.openProject = async projectId => {
        try {
            const project = await api('/api/projects/' + encodeURIComponent(projectId));
            setProject(project);
            window.restoreEditorProject?.(project.config?.editor || {});
            window.refreshMaterials();
            notice('已打开项目', 'success');
        } catch (error) { notice('打开失败：' + error.message, 'error'); }
    };

    window.__JJYBImportMedia = window.importMedia = () => {
        const project = requireProject(); if (!project) return;
        const input = document.createElement('input'); input.type = 'file'; input.multiple = true; input.accept = 'video/*,audio/*,image/*';
        input.onchange = async () => {
            for (const file of Array.from(input.files || [])) {
                const type = file.type.startsWith('video/') ? 'video' : file.type.startsWith('audio/') ? 'audio' : file.type.startsWith('image/') ? 'image' : 'other';
                const form = new FormData(); form.append('file', file); form.append('type', type);
                try {
                    const upload = await api('/api/upload', {method:'POST', body: form});
                    await api('/api/materials', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({project_id:project.id, type, name:upload.filename || file.name, path:upload.path, size:upload.size || file.size, duration:0, metadata:{}})});
                } catch (error) { notice(file.name + ' 上传失败：' + error.message, 'error'); }
            }
            window.refreshMaterials();
        };
        input.click();
    };

    window.refreshMaterials = async () => {
        const project = requireProject(); if (!project) return;
        const list = document.getElementById('materials-list'); if (!list) return;
        list.innerHTML = '<div class="text-text-secondary text-xs">加载中...</div>';
        try {
            const materials = await api('/api/materials?project_id=' + encodeURIComponent(project.id));
            list.innerHTML = materials.map(material => `<div class="material-item glass-card rounded-lg p-2 cursor-pointer" data-material-id="${escapeHtml(material.id)}" data-material-type="${escapeHtml(material.type)}" data-material-name="${escapeHtml(material.name)}" data-material-path="${escapeHtml(material.path)}" data-material-duration="${Number(material.duration) || 0}" onclick="addMaterialToTimeline('${escapeHtml(material.id)}')"><div class="w-full h-20 bg-gradient-to-br from-primary/20 to-secondary/20 rounded-lg mb-2 flex items-center justify-center"><i class="fa ${material.type === 'audio' ? 'fa-music' : material.type === 'image' ? 'fa-image' : 'fa-film'} text-primary text-lg"></i></div><p class="text-xs text-text-secondary truncate">${escapeHtml(material.name)}</p></div>`).join('') || '<div class="text-text-secondary text-xs">暂无素材</div>';
        } catch (error) { list.innerHTML = '<div class="text-red-400 text-xs">加载失败</div>'; }
    };

    window.filterMaterials = type => {
        document.querySelectorAll('.material-item').forEach(item => { item.style.display = (!type || type === 'all' || item.dataset.materialType === type) ? '' : 'none'; });
        document.querySelectorAll('.material-filter-btn, [data-material-filter]').forEach(button => {
            const buttonType = button.dataset.type || button.dataset.materialFilter;
            button.classList.toggle('active', buttonType === type);
        });
    };

    window.addMaterialToTimeline = materialId => {
        const item = document.querySelector('.material-item[data-material-id="' + (window.CSS?.escape ? CSS.escape(String(materialId)) : String(materialId)) + '"]');
        if (!item || typeof window.addMediaToTrack !== 'function') return false;
        const type = item.dataset.materialType || 'video';
        const track = document.getElementById(type === 'audio' ? 'audio-track-1' : 'video-track-1');
        if (!track) { notice('未找到对应时间线轨道', 'error'); return false; }
        const path = item.dataset.materialPath || '';
        const source = /^https?:\/\//.test(path) || path.startsWith('/') ? path : '/' + path.replace(/^\.\//, '');
        const file = new File([], item.dataset.materialName || '素材', {type: type === 'audio' ? 'audio/*' : type === 'image' ? 'image/*' : 'video/*'});
        const clip = window.addMediaToTrack(file, track, track.id, {type, name:file.name, url:source, duration:Number(item.dataset.materialDuration) || undefined, materialId});
        if (clip) clip.dataset.materialId = String(materialId);
        return Boolean(clip);
    };

    window.exportVideo = async () => {
        const project = requireProject(); if (!project) return;
        const timeline = typeof window.collectTracksData === 'function' ? window.collectTracksData() : [];
        const effects_hints = typeof window.collectTimelineEffectHints === 'function' ? window.collectTimelineEffectHints() : {filters:window.currentFilters || {}};
        try {
            const result = await api('/api/export/video', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(Object.assign(outputSettings(), {project_id:project.id, timeline, effects_hints}))});
            if (result.download_url && typeof window.downloadExportedVideo === 'function') window.downloadExportedVideo(result.download_url, result.file_name);
            else notice('导出成功：' + (result.download_url || ''), 'success');
        } catch (error) { notice('导出失败：' + error.message, 'error'); }
    };

    window.loadRecentProjects = async () => {
        const list = document.getElementById('recent-projects'); if (!list) return;
        try { const data = await api('/api/projects?limit=10&order=desc&sort=updated_at'); list.innerHTML = (data.projects || []).map(p => `<div class="operation-btn p-3 glass-card rounded-xl cursor-pointer" onclick="openProject('${escapeHtml(p.id)}')"><p class="text-sm font-medium truncate">${escapeHtml(p.name)}</p></div>`).join(''); } catch (_) {}
    };
    window.loadRecentProjects();
})();
