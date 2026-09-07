'use strict';

const API_BASE = window.location.origin + '/api';
let currentTaskId = null;
let currentWorldUrl = null;
let currentWorldId = null;
let pollTimeout = null;
let pollCount = 0;
let userApiKey = '';
let llmAvailable = false;
let currentMode = 'text';
let uploadedImageFile = null;
let abortController = null;
let aiGeneratedImageUrl = null;
let loadingTimer = null;

// ===== XSS 防护：HTML 转义 =====
function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

function escapeAttr(text) {
    return escapeHtml(text).replace(/'/g, '&#39;');
}

// ===== 模式切换 =====
function switchMode(mode) {
    currentMode = mode;
    document.getElementById('tabText').classList.toggle('active', mode === 'text');
    document.getElementById('tabImage').classList.toggle('active', mode === 'image');
    document.getElementById('modeText').classList.toggle('active', mode === 'text');
    document.getElementById('modeImage').classList.toggle('active', mode === 'image');

    document.getElementById('tabText').setAttribute('aria-selected', mode === 'text');
    document.getElementById('tabImage').setAttribute('aria-selected', mode === 'image');
}

// ===== 页面加载时初始化 =====
document.addEventListener('DOMContentLoaded', async function () {
    // 使用 sessionStorage 而非 localStorage（关闭标签页后自动清除）
    const savedKey = sessionStorage.getItem('worldlabs_api_key');
    if (savedKey) {
        document.getElementById('apiKeyInput').value = savedKey;
        userApiKey = savedKey;
    }
    await checkLlmStatus();
    loadModels();
    loadHistory();
    initImageUpload();
});

// ===== 拉取可用本地模型并填充下拉框 =====
async function loadModels() {
    try {
        const response = await fetch(API_BASE + '/models');
        if (!response.ok) return;
        const data = await response.json();
        if (!data.success) return;

        // LLM 模型（多模型时显示下拉框）
        const llmSel = document.getElementById('llmModelSelect');
        if (data.llm && data.llm.available && data.llm.models && data.llm.models.length > 1) {
            llmSel.innerHTML = data.llm.models.map(function (m) {
                return '<option value="' + escapeAttr(m) + '"' +
                    (m === data.llm.model ? ' selected' : '') + '>' +
                    escapeHtml(m) + '</option>';
            }).join('');
            llmSel.style.display = 'block';
        }

        // 3D 后端（不可用的置灰并附原因）
        const backendSel = document.getElementById('backendSelect');
        ((data.three_d && data.three_d.available_backends) || []).forEach(function (b) {
            const opt = backendSel.querySelector('option[value="' + b.name + '"]');
            if (opt && !b.available) {
                opt.disabled = true;
                opt.textContent += '（不可用: ' + (b.reason || '未知') + '）';
            }
        });

        // 文生图模型 + 默认分辨率
        const t2iSel = document.getElementById('t2iModelSelect');
        const sizeSel = document.getElementById('t2iSizeSelect');
        const models = (data.text_to_image && data.text_to_image.models) || [];
        t2iSel.innerHTML = models.map(function (m) {
            return '<option value="' + escapeAttr(m.id) + '"' +
                (m.is_current ? ' selected' : '') + '>' +
                escapeHtml(m.label) + '</option>';
        }).join('');
        const current = models.find(function (m) { return m.is_current; });
        if (current && sizeSel) {
            sizeSel.value = String(current.default_size || 512);
        }
        // 切换文生图模型时同步推荐分辨率
        t2iSel.addEventListener('change', function () {
            const selected = models.find(function (m) { return m.id === t2iSel.value; });
            if (selected && sizeSel) {
                sizeSel.value = String(selected.default_size || 512);
            }
        });
    } catch (e) {
        console.error('Load models failed:', e);
    }
}

// ===== 生成历史画廊 =====
async function loadHistory() {
    try {
        const response = await fetch(API_BASE + '/history?limit=60');
        if (!response.ok) return;
        const data = await response.json();
        if (!data.success) return;

        const section = document.getElementById('historySection');
        const grid = document.getElementById('historyGrid');
        const entries = data.entries || [];
        if (!entries.length) {
            section.style.display = 'none';
            return;
        }
        section.style.display = 'block';

        const kindLabels = { t2i: '🎨 文生图', three_d: '🧊 3D 多视角', world: '🌍 3D 世界' };
        grid.innerHTML = entries.map(function (e) {
            const p = e.payload || {};
            let thumb = '';
            if (e.kind === 't2i' && p.image_url) thumb = p.image_url;
            else if (e.kind === 'three_d' && (p.view_urls || [])[0]) thumb = p.view_urls[0];
            else if (p.thumbnail_url || p.preview_url) thumb = p.thumbnail_url || p.preview_url;
            const thumbSrc = thumb
                ? (thumb.startsWith('http') ? thumb : window.location.origin + '/' + thumb.replace(/^\/+/, ''))
                : '';
            const thumbHtml = thumbSrc
                ? '<img src="' + escapeAttr(thumbSrc) + '" loading="lazy" onerror="this.style.display=\'none\'">'
                : '<div style="font-size:1.6rem;padding:24px 0;">' + (kindLabels[e.kind] || '📄') + '</div>';
            const statusMark = e.status === 'processing' ? ' ⏳' : '';
            return '<div class="gallery-item" style="position:relative;" ' +
                'onclick="openHistoryItem(\'' + escapeAttr(e.id) + '\')" role="button" tabindex="0">' +
                '<div class="preview" style="background:#000;overflow:hidden;">' + thumbHtml + '</div>' +
                '<div class="gallery-item-info"><p title="' + escapeAttr(e.prompt || '') + '">' +
                escapeHtml((e.prompt || kindLabels[e.kind] || e.kind).slice(0, 30)) +
                '</p><p style="font-size:0.65rem;color:#666;">' +
                (kindLabels[e.kind] || e.kind) + statusMark + ' · ' + escapeHtml(e.created_at || '') + '</p></div>' +
                '<button onclick="event.stopPropagation();deleteHistoryItem(\'' + escapeAttr(e.id) + '\')" ' +
                'aria-label="删除历史" style="position:absolute;top:6px;right:6px;background:rgba(255,0,0,0.7);' +
                'border:none;border-radius:50%;width:22px;height:22px;color:#fff;cursor:pointer;font-size:0.8rem;">×</button>' +
                '</div>';
        }).join('');
    } catch (e) {
        console.error('Load history failed:', e);
    }
}

function openHistoryItem(id) {
    fetch(API_BASE + '/history?limit=200')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            const entry = (data.entries || []).find(function (e) { return e.id === id; });
            if (!entry) return;
            const p = entry.payload || {};
            window.scrollTo({ top: 0, behavior: 'smooth' });
            if (entry.kind === 't2i' && p.image_url) {
                showPlaceholder();
                document.getElementById('resultArea').innerHTML =
                    '<div class="pano-container" style="aspect-ratio:1;max-height:420px;">' +
                    '<img src="' + escapeAttr(p.image_url.startsWith('http') ? p.image_url :
                        window.location.origin + p.image_url) + '" style="width:100%;height:100%;object-fit:contain;">' +
                    '</div>' +
                    '<p style="color:#888;font-size:0.75rem;margin-top:8px;">' + escapeHtml(entry.prompt || '') + '</p>';
            } else if (entry.kind === 'three_d' && (p.view_urls || []).length) {
                showResult({ view_urls: p.view_urls, backend: p.backend,
                             view_count: p.view_count, generation_time: p.generation_time,
                             message: '历史记录 · ' + (entry.prompt || '') });
            } else if (entry.kind === 'world') {
                if (p.world_url || p.preview_url) {
                    showResult({ world_url: p.world_url, preview_url: p.preview_url || p.thumbnail_url,
                                 pano_url: p.pano_url, thumbnail_url: p.thumbnail_url,
                                 caption: p.caption || entry.prompt, world_id: p.world_id });
                } else {
                    showToast('⏳ 该任务未完成（可能已过期）', true);
                }
            }
        })
        .catch(function (e) { console.error('Open history failed:', e); });
}

async function deleteHistoryItem(id) {
    if (!confirm('删除这条历史记录及其生成文件？')) return;
    try {
        const response = await fetch(API_BASE + '/history/' + encodeURIComponent(id),
                                     { method: 'DELETE', headers: getAuthHeaders() });
        if (!response.ok) throw new Error('HTTP ' + response.status);
        showToast('🗑️ 已删除');
        loadHistory();
    } catch (e) {
        showToast('⚠️ 删除失败: ' + e.message, true);
    }
}

// ===== 检测本地 LLM =====
async function checkLlmStatus() {
    const statusEl = document.getElementById('llmStatus');
    try {
        const response = await fetch(API_BASE + '/llm-status');
        if (!response.ok) {
            throw new Error('HTTP error! status: ' + response.status);
        }
        const data = await response.json();
        if (data.available) {
            llmAvailable = true;
            statusEl.textContent = '✓ ' + data.type.toUpperCase();
            statusEl.className = 'api-status ok';
        } else {
            llmAvailable = false;
            statusEl.textContent = '未连接';
            statusEl.className = 'api-status error';
        }
    } catch (e) {
        llmAvailable = false;
        statusEl.textContent = '检测失败';
        statusEl.className = 'api-status error';
        console.error('LLM status check failed:', e);
    }
}

function toggleLlm() {
    // 状态由 checkbox 的 checked 属性直接读取，无需额外处理
}

function saveApiKey() {
    const key = document.getElementById('apiKeyInput').value.trim();
    if (key) {
        sessionStorage.setItem('worldlabs_api_key', key);
        userApiKey = key;
        showToast('✅ API Key 已保存');
    } else {
        sessionStorage.removeItem('worldlabs_api_key');
        userApiKey = '';
        showToast('⚠️ 已清除 API Key');
    }
}

// ===== 构建 API Key 请求头 =====
function getAuthHeaders() {
    const headers = {};
    if (userApiKey) {
        headers['X-API-Key'] = userApiKey;
    }
    return headers;
}

// ===== 图片上传 =====
function initImageUpload() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('imageInput');

    document.getElementById('inputTypeSelect').addEventListener('change', function (e) {
        setInputType(e.target.value);
    });

    fileInput.addEventListener('change', function (e) {
        if (!e.target.files || !e.target.files.length) return;
        if (inputType === 'multi') {
            uploadedImageFiles = [];
            Array.from(e.target.files).forEach(handleImageFile);
            if (!uploadedImageFiles.length) removeImage();
        } else {
            handleImageFile(e.target.files[0]);
        }
    });

    uploadArea.addEventListener('dragover', function (e) {
        e.preventDefault();
        e.stopPropagation();
        uploadArea.classList.add('drag-over');
    });

    uploadArea.addEventListener('dragleave', function (e) {
        e.preventDefault();
        e.stopPropagation();
        uploadArea.classList.remove('drag-over');
    });

    uploadArea.addEventListener('drop', function (e) {
        e.preventDefault();
        e.stopPropagation();
        uploadArea.classList.remove('drag-over');
        var files = Array.from(e.dataTransfer.files);
        if (inputType === 'multi') {
            uploadedImageFiles = [];
            files.forEach(handleImageFile);
            if (!uploadedImageFiles.length) {
                showToast('⚠️ 请上传图片文件', true);
                removeImage();
            }
        } else if (files[0] && (files[0].type.startsWith('image/') ||
                   (inputType === 'video' && files[0].type.startsWith('video/')))) {
            handleImageFile(files[0]);
        } else {
            showToast('⚠️ 请上传图片文件', true);
        }
    });
}

// ===== 素材输入类型（单图 / 多图 / 视频） =====
var inputType = 'single';
var uploadedImageFiles = [];  // 多图模式
var uploadedVideoFile = null; // 视频模式

function setInputType(type) {
    inputType = type;
    const input = document.getElementById('imageInput');
    const icon = document.querySelector('#uploadArea .upload-icon');
    const hint = document.querySelector('#uploadArea .upload-hint span');
    if (type === 'multi') {
        input.multiple = true;
        input.accept = 'image/*';
        icon.textContent = '🖼️';
        hint.textContent = '选择 2-8 张同一场景的图片（世界重建效果更好，走 World Labs）';
    } else if (type === 'video') {
        input.multiple = false;
        input.accept = 'video/mp4,video/webm,video/quicktime,video/x-msvideo';
        icon.textContent = '🎬';
        hint.textContent = '选择视频文件（mp4 / webm / mov，≤100MB，走 World Labs）';
    } else {
        input.multiple = false;
        input.accept = 'image/*';
        icon.textContent = '📷';
        hint.textContent = '支持 JPG / PNG / WEBP，最大 10MB';
    }
    removeImage();
}

function handleImageFile(file) {
    if (inputType === 'video') {
        if (file.size > 100 * 1024 * 1024) {
            showToast('⚠️ 视频不能超过 100MB', true);
            return;
        }
        uploadedVideoFile = file;
        uploadedImageFiles = [];
        uploadedImageFile = null;
        const ext = file.name.split('.').pop().toLowerCase();
        if (!['mp4', 'webm', 'mov', 'avi'].includes(ext)) {
            showToast('⚠️ 视频仅支持 mp4 / webm / mov / avi', true);
            return;
        }
        showImagePreview('🎬 ' + file.name + '（' + (file.size / 1024 / 1024).toFixed(1) + 'MB）');
        return;
    }

    if (inputType === 'multi') {
        if (file.size > 10 * 1024 * 1024) {
            showToast('⚠️ 单张图片不能超过 10MB', true);
            return;
        }
        var ext2 = file.name.split('.').pop().toLowerCase();
        if (!['jpg', 'jpeg', 'png', 'webp'].includes(ext2)) {
            showToast('⚠️ 只支持 JPG / PNG / WEBP 格式', true);
            return;
        }
        uploadedImageFiles.push(file);
        uploadedImageFile = null;
        uploadedVideoFile = null;
        showImagePreview('已选 ' + uploadedImageFiles.length + ' 张图片');
        return;
    }

    // 单图模式（原逻辑）
    if (file.size > 10 * 1024 * 1024) {
        showToast('⚠️ 图片不能超过 10MB', true);
        return;
    }
    var ext = file.name.split('.').pop().toLowerCase();
    if (!['jpg', 'jpeg', 'png', 'webp'].includes(ext)) {
        showToast('⚠️ 只支持 JPG / PNG / WEBP 格式', true);
        return;
    }
    uploadedImageFile = file;
    uploadedImageFiles = [];
    uploadedVideoFile = null;
    var reader = new FileReader();
    reader.onload = function (e) {
        document.getElementById('previewImg').src = e.target.result;
        document.getElementById('imagePreviewBox').style.display = 'block';
        document.getElementById('uploadArea').style.display = 'none';
    };
    reader.onerror = function () {
        showToast('⚠️ 图片读取失败', true);
    };
    reader.readAsDataURL(file);
}

function showImagePreview(text) {
    document.getElementById('previewImg').style.display = 'none';
    document.getElementById('imagePreviewBox').style.display = 'block';
    let info = document.getElementById('multiImageInfo');
    if (!info) {
        info = document.createElement('div');
        info.id = 'multiImageInfo';
        info.style.cssText = 'font-size:0.75rem;color:#aaa;margin-top:6px;';
        document.getElementById('imagePreviewBox').appendChild(info);
    }
    info.textContent = text;
    document.getElementById('uploadArea').style.display = 'none';
}

function removeImage() {
    uploadedImageFile = null;
    uploadedImageFiles = [];
    uploadedVideoFile = null;
    document.getElementById('imageInput').value = '';
    document.getElementById('imagePreviewBox').style.display = 'none';
    const pv = document.getElementById('previewImg');
    if (pv) { pv.style.display = 'block'; pv.src = ''; }
    const info = document.getElementById('multiImageInfo');
    if (info) info.textContent = '';
    document.getElementById('uploadArea').style.display = 'block';
}

// ===== 示例加载 =====
function loadExample(text) {
    switchMode('text');
    document.getElementById('prompt').value = text;
    window.scrollTo({ top: 0, behavior: 'smooth' });
    showToast('📝 已加载示例提示词');
}

function clearForm() {
    if (confirm('确定要清空所有输入吗？')) {
        if (currentMode === 'text') {
            document.getElementById('prompt').value = '';
            document.getElementById('enhancedPromptBox').style.display = 'none';
            removeAiImage();
        } else {
            removeImage();
            document.getElementById('imagePrompt').value = '';
        }
        showPlaceholder();
        showToast('🗑️ 已清空表单');
    }
}

function showPlaceholder() {
    document.getElementById('resultArea').innerHTML =
        '<div class="result-placeholder">' +
        '<div class="icon">🌍</div>' +
        '<p>在左侧输入描述或上传图片</p>' +
        '<p style="margin-top: 8px;">点击生成按钮，你的 3D 世界将在这里展示</p>' +
        '</div>';
}

// ===== Toast =====
function showToast(message, isError) {
    var toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = 'toast' + (isError ? ' error' : '');
    toast.classList.add('show');
    setTimeout(function () { toast.classList.remove('show'); }, 3000);
}

function showLoading() {
    document.getElementById('resultArea').innerHTML =
        '<div class="loading-container">' +
        '<div class="spinner"></div>' +
        '<div class="loading-text">正在生成你的 3D 世界...</div>' +
        '<div class="loading-subtext" id="loadingSubtext">预计需要 30 秒 ~ 5 分钟</div>' +
        '<div id="loadingTimer" style="color:#00ff88;font-size:0.9rem;margin-top:8px;font-variant-numeric:tabular-nums;">⏱ 已用 0 秒</div>' +
        '<button class="btn btn-cancel" style="max-width:200px;margin-top:15px;" onclick="cancelGeneration()">❌ 取消生成</button>' +
        '</div>';
    // 启动计时器
    var startTime = Date.now();
    if (loadingTimer) clearInterval(loadingTimer);
    loadingTimer = setInterval(function () {
        var elapsed = Math.floor((Date.now() - startTime) / 1000);
        var mins = Math.floor(elapsed / 60);
        var secs = elapsed % 60;
        var timerEl = document.getElementById('loadingTimer');
        if (timerEl) {
            timerEl.textContent = '⏱ 已用 ' + mins + ' 分 ' + secs + ' 秒';
        }
        // 超过 3 分钟时更新提示
        var subEl = document.getElementById('loadingSubtext');
        if (subEl && elapsed > 180) {
            subEl.textContent = '生成中，请耐心等待...';
            subEl.style.color = '#ffaa00';
        }
    }, 1000);
}

function stopLoadingTimer() {
    if (loadingTimer) {
        clearInterval(loadingTimer);
        loadingTimer = null;
    }
}

// ===== 取消生成 =====
function cancelGeneration() {
    stopLoadingTimer();
    if (abortController) {
        abortController.abort();
        abortController = null;
    }
    if (pollTimeout) {
        clearTimeout(pollTimeout);
        pollTimeout = null;
    }
    currentTaskId = null;
    var btn = document.getElementById('generateBtn');
    btn.disabled = false;
    btn.textContent = '🚀 开始生成';
    showPlaceholder();
    showToast('❌ 已取消生成');
}

function showResult(data) {
    var area = document.getElementById('resultArea');

    // ===== 检测结果类型：Stable Zero123 多视角 vs World Labs =====
    if (data.view_urls && Array.isArray(data.view_urls) && data.view_urls.length > 0) {
        showStable3DResult(data);
        return;
    }

    // ===== World Labs 结果处理 =====
    currentWorldUrl = data.world_url || data.pano_url;
    currentWorldId = data.world_id || null;
    var previewUrl = data.preview_url || data.thumbnail_url || data.pano_url;

    var thumbnailHtml = '';
    if (previewUrl) {
        var safeUrl = escapeAttr(previewUrl);
        thumbnailHtml =
            '<img src="' + safeUrl + '" alt="Preview" style="width:100%;height:100%;object-fit:cover;" ' +
            'onerror="this.parentElement.innerHTML=' +
            '\'&lt;div style=&quot;color:#666;display:flex;align-items:center;justify-content:center;height:100%;&quot;&gt;预览加载失败&lt;/div&gt;\'">';
    }

    var actionButtons = '';
    if (data.world_url) {
        actionButtons += '<button class="btn btn-primary" onclick="window.open(\'' + escapeAttr(data.world_url) + '\', \'_blank\')">🌐 打开 3D 世界</button>';
    }
    if (data.pano_url) {
        actionButtons += '<button class="btn btn-secondary" onclick="window.open(\'' + escapeAttr(data.pano_url) + '\', \'_blank\')">🖼️ 全景图</button>';
    }
    if (currentWorldId) {
        actionButtons += '<button class="btn btn-secondary" onclick="openSplatViewer(\'' + escapeAttr(currentWorldId) + '\')">🧊 网页查看 3D</button>';
        actionButtons += '<button class="btn btn-secondary" onclick="exportWorld(\'' + escapeAttr(currentWorldId) + '\')">📦 导出 PLY 点云</button>';
    }
    actionButtons += '<button class="btn btn-secondary" onclick="copyLink()">📋 复制链接</button>';

    var engineBadge = data.engine_used
        ? '<span style="color:#00d2ff;font-size:0.75rem;">🔧 ' + escapeHtml(data.engine_used) + '</span>'
        : '';
    var captionText = escapeHtml(data.caption || '3D 世界已生成');

    area.innerHTML =
        '<div class="pano-container" style="background:#000;">' +
        thumbnailHtml +
        '<div style="color:#666;display:flex;align-items:center;justify-content:center;height:100%;">生成中...</div>' +
        '</div>' +
        '<div style="margin-top:10px;padding:8px;background:rgba(255,255,255,0.05);border-radius:6px;">' +
        '<p style="color:#aaa;font-size:0.8rem;">' + captionText + '</p>' +
        engineBadge +
        '</div>' +
        '<div class="result-actions" style="margin-top:12px;">' +
        actionButtons +
        '</div>';

    // 如果有 thumbnailHtml，移除 "生成中..." 占位
    if (thumbnailHtml) {
        var placeholderDiv = area.querySelector('.pano-container > div');
        if (placeholderDiv) placeholderDiv.remove();
    }
    // 结果落定后刷新历史画廊
    loadHistory();
}

// ===== Stable Zero123 多视角结果展示 =====
var current3DViews = [];
var current3DIndex = 0;

function showStable3DResult(data) {
    var area = document.getElementById('resultArea');
    var viewUrls = data.view_urls || [];
    current3DViews = viewUrls.map(function (url) {
        return url.startsWith('http') ? url : (window.location.origin + '/' + url);
    });
    current3DIndex = 0;

    currentWorldUrl = current3DViews[0] || null;

    var viewLabels = ['正面视角', '左侧视角', '背面视角', '俯视视角', '右侧视角', '3/4 视角', '特写视角', '广角视角'];

    var thumbsHtml = '';
    current3DViews.forEach(function (url, i) {
        var safeUrl = escapeAttr(url);
        var label = viewLabels[i] || ('视角 ' + (i + 1));
        thumbsHtml +=
            '<div class="view-thumb' + (i === 0 ? ' active' : '') + '" ' +
            'data-index="' + i + '" ' +
            'onclick="switch3DView(' + i + ')" ' +
            'style="position:relative;border-radius:6px;overflow:hidden;cursor:pointer;transition:all 0.2s;border:2px solid ' + (i === 0 ? '#00ff88' : 'transparent') + ';opacity:' + (i === 0 ? '1' : '0.5') + ';">' +
            '<img src="' + safeUrl + '" alt="' + escapeAttr(label) + '" loading="lazy" decoding="async" ' +
            'style="width:100%;aspect-ratio:1;object-fit:cover;background:#000;display:block;">' +
            '<div style="position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,0.7);padding:3px 6px;font-size:0.7rem;text-align:center;">' + escapeHtml(label) + '</div>' +
            '</div>';
    });

    var caption = escapeHtml(data.message || '已生成 ' + viewUrls.length + ' 个3D视角');
    var genTime = data.generation_time
        ? '（耗时 ' + data.generation_time.toFixed(1) + 's）'
        : '';
    var firstSafeUrl = escapeAttr(current3DViews[0] || '');

    area.innerHTML =
        '<div style="margin-bottom:10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">' +
        '<span style="display:inline-block;padding:3px 10px;border-radius:12px;background:rgba(0,255,136,0.15);color:#00ff88;font-size:0.75rem;">🔓 Stable Zero123 开源引擎</span>' +
        '<span style="color:#888;font-size:0.75rem;">' + caption + genTime + '</span>' +
        '</div>' +
        // 主图大图展示
        '<div class="pano-container" style="aspect-ratio:1;max-height:400px;display:flex;align-items:center;justify-content:center;background:#000;position:relative;border-radius:8px;overflow:hidden;">' +
        '<img id="main3DView" src="' + firstSafeUrl + '" alt="3D 视角" decoding="async" ' +
        'style="max-width:100%;max-height:100%;object-fit:contain;transition:opacity 0.3s;" ' +
        'onclick="open3DViewer()" ' +
        'title="点击打开全屏 3D 预览">' +
        '<div style="position:absolute;top:8px;right:8px;background:rgba(0,0,0,0.6);padding:4px 10px;border-radius:4px;font-size:0.7rem;color:#00ff88;cursor:pointer;" onclick="open3DViewer()">🌐 全屏 3D 预览</div>' +
        '<div id="view3DLabel" style="position:absolute;bottom:8px;left:8px;background:rgba(0,0,0,0.6);padding:4px 10px;border-radius:4px;font-size:0.75rem;color:#fff;">' + escapeHtml(viewLabels[0] || '视角 1') + '</div>' +
        '</div>' +
        // 缩略图导航
        '<div style="display:grid;grid-template-columns:repeat(' + Math.min(current3DViews.length, 4) + ',1fr);gap:6px;margin-top:8px;">' +
        thumbsHtml +
        '</div>' +
        // 操作按钮
        '<div class="result-actions" style="margin-top:12px;">' +
        '<button class="btn btn-primary" onclick="open3DViewer()">🌐 全屏 3D 预览</button>' +
        '<button class="btn btn-secondary" onclick="autoRotate3D()" id="rotateBtn">🔄 自动旋转</button>' +
        '<button class="btn btn-secondary" onclick="downloadAllViews()">📥 下载所有视角</button>' +
        '<button class="btn btn-secondary" onclick="exportOrbitVideo()">🎥 环绕视频</button>' +
        '<button class="btn btn-secondary" onclick="copyLink()">📋 复制链接</button>' +
        '</div>';
}

function switch3DView(index) {
    if (index < 0 || index >= current3DViews.length) return;
    current3DIndex = index;
    var img = document.getElementById('main3DView');
    if (img) {
        img.style.opacity = '0.3';
        setTimeout(function () {
            img.src = current3DViews[index];
            img.style.opacity = '1';
        }, 150);
    }
    var label = document.getElementById('view3DLabel');
    var labels = ['正面视角', '左侧视角', '背面视角', '俯视视角', '右侧视角', '3/4 视角', '特写视角', '广角视角'];
    if (label) label.textContent = labels[index] || ('视角 ' + (index + 1));
    // 更新缩略图状态
    var thumbs = document.querySelectorAll('.view-thumb');
    thumbs.forEach(function (el, i) {
        if (i === index) {
            el.style.border = '2px solid #00ff88';
            el.style.opacity = '1';
            el.classList.add('active');
        } else {
            el.style.border = '2px solid transparent';
            el.style.opacity = '0.5';
            el.classList.remove('active');
        }
    });
}

var rotateTimer = null;
function autoRotate3D() {
    var btn = document.getElementById('rotateBtn');
    if (rotateTimer) {
        clearInterval(rotateTimer);
        rotateTimer = null;
        if (btn) btn.textContent = '🔄 自动旋转';
        return;
    }
    if (btn) btn.textContent = '⏸ 停止旋转';
    rotateTimer = setInterval(function () {
        current3DIndex = (current3DIndex + 1) % current3DViews.length;
        switch3DView(current3DIndex);
    }, 1500);
}

function open3DViewer() {
    var urls = current3DViews.map(encodeURIComponent).join(',');
    window.open('/3d-viewer.html?views=' + urls, '_blank', 'width=1024,height=768');
}

// ===== 下载所有视角（直接使用全局 current3DViews，避免向 onclick 属性注入 JSON） =====
function downloadAllViews() {
    current3DViews.forEach(function (url, i) {
        setTimeout(function () {
            var a = document.createElement('a');
            a.href = url;
            a.download = '3d_view_' + (i + 1) + '.png';
            a.click();
        }, i * 300);
    });
    showToast('📥 开始下载所有视角...');
}

// ===== 6 视角合成环绕视频 =====
async function exportOrbitVideo() {
    if (!current3DViews.length) {
        showToast('⚠️ 没有可用的视角图片', true);
        return;
    }
    showToast('🎥 正在合成环绕视频...');
    try {
        var response = await fetch(API_BASE + '/export-orbit-video', {
            method: 'POST',
            headers: Object.assign(
                { 'Content-Type': 'application/json' }, getAuthHeaders()
            ),
            body: JSON.stringify({ view_urls: current3DViews, fps: 8, hold: 2 })
        });
        if (!response.ok) {
            var errData = null;
            try { errData = await response.json(); } catch (e) { /* ignore */ }
            throw new Error((errData && errData.error) || 'HTTP ' + response.status);
        }
        var data = await response.json();
        if (data.success && data.video_url) {
            showResult({ video_url: data.video_url,
                         message: '环绕视频 · ' + data.frames + ' 帧 @ ' + data.fps + 'fps' });
            showToast('🎥 环绕视频合成完成');
        } else {
            throw new Error(data.error || '合成失败');
        }
    } catch (error) {
        console.error('Orbit video failed:', error);
        showToast('⚠️ 环绕视频合成失败: ' + error.message, true);
    }
}

function showError(message) {
    var safeMsg = escapeHtml(message);
    document.getElementById('resultArea').innerHTML =
        '<div class="result-placeholder" style="color: #ff6b6b;">' +
        '<div class="icon">❌</div>' +
        '<p>生成失败</p>' +
        '<p style="margin-top: 8px; font-size: 0.85rem;">' + safeMsg + '</p>' +
        '<button class="btn btn-secondary" style="margin-top: 15px;" onclick="showPlaceholder()">返回</button>' +
        '</div>';
}

function copyLink() {
    if (currentWorldUrl) {
        navigator.clipboard.writeText(currentWorldUrl).then(function () {
            showToast('✅ 链接已复制');
        }).catch(function (err) {
            console.error('Copy failed:', err);
            showToast('⚠️ 复制失败，请手动复制', true);
        });
    }
}

// ===== 导出世界资产（PLY 点云 / GLB 网格） =====
async function exportWorld(worldId) {
    showToast('📦 正在请求导出...');
    try {
        var response = await fetch(API_BASE + '/export-world/' + encodeURIComponent(worldId), {
            method: 'POST',
            headers: Object.assign(
                { 'Content-Type': 'application/json' }, getAuthHeaders()
            ),
            body: JSON.stringify({ asset_type: 'splats', format: 'ply' })
        });
        if (!response.ok) {
            var errData = null;
            try { errData = await response.json(); } catch (e) { /* ignore */ }
            throw new Error((errData && errData.error) || 'HTTP ' + response.status);
        }
        var data = await response.json();
        if (data.success && data.download_url) {
            window.open(data.download_url, '_blank');
            showToast('📦 PLY 导出完成，已开始下载');
        } else if (data.success) {
            showToast('⏳ 导出处理中，请稍后重试');
        } else {
            throw new Error(data.error || '导出失败');
        }
    } catch (error) {
        console.error('Export failed:', error);
        showToast('⚠️ 导出失败: ' + error.message, true);
    }
}

// ===== 网页内 3D 查看器（Gaussian Splats） =====
function openSplatViewer(worldId) {
    window.open('/splat-viewer.html?world=' + encodeURIComponent(worldId),
                '_blank', 'width=1280,height=800');
}

// ===== AI 生成图片 =====
async function generateImageFromText() {
    var prompt = document.getElementById('prompt').value.trim();
    if (!prompt) {
        showToast('⚠️ 请先输入提示词', true);
        return;
    }

    var btn = document.getElementById('aiGenImgBtn');
    btn.disabled = true;
    btn.textContent = '⏳ AI 生成图片中...';

    try {
        var formData = new FormData();
        formData.append('prompt', prompt);

        // 附加所选文生图模型与分辨率
        var t2iModelSel = document.getElementById('t2iModelSelect');
        var t2iSizeSel = document.getElementById('t2iSizeSelect');
        if (t2iModelSel && t2iModelSel.value) {
            formData.append('model', t2iModelSel.value);
        }
        if (t2iSizeSel && t2iSizeSel.value) {
            formData.append('width', t2iSizeSel.value);
            formData.append('height', t2iSizeSel.value);
        }

        var response = await fetch(API_BASE + '/generate-image', {
            method: 'POST',
            body: formData,
            headers: getAuthHeaders()
        });

        if (!response.ok) {
            var errData = null;
            try { errData = await response.json(); } catch (e) { /* ignore */ }
            var errMsg = errData && errData.error
                ? errData.error
                : 'HTTP error! status: ' + response.status;
            throw new Error(errMsg);
        }

        var data = await response.json();
        if (data.success) {
            aiGeneratedImageUrl = data.image_url;
            var fullUrl = data.image_url.startsWith('http')
                ? data.image_url
                : (window.location.origin + data.image_url);
            document.getElementById('aiGenPreviewImg').src = fullUrl;
            document.getElementById('aiImageBox').style.display = 'block';

            var infoText = '⏱ ' + data.generation_time + 's';
            if (data.size) infoText += '  |  🖼 ' + data.size;
            document.getElementById('aiImageInfo').textContent = infoText;

            loadHistory();
            showToast('✅ AI 图片生成完成！点击"开始生成"创建 3D');
        } else {
            throw new Error(data.error || '生成失败');
        }
    } catch (error) {
        showError(error.message);
        showToast('⚠️ 图片生成失败: ' + error.message, true);
    } finally {
        btn.disabled = false;
        btn.textContent = '🎨 AI 生成图片';
    }
}

function removeAiImage() {
    aiGeneratedImageUrl = null;
    document.getElementById('aiGenPreviewImg').src = '';
    document.getElementById('aiImageBox').style.display = 'none';
}

// ===== 核心：生成 3D 世界 =====
async function generateWorld() {
    var mode = currentMode;
    var prompt = (mode === 'text')
        ? document.getElementById('prompt').value.trim()
        : document.getElementById('imagePrompt').value.trim();

    if (mode === 'text' && !prompt) {
        showToast('⚠️ 请输入提示词', true);
        return;
    }
    if (mode === 'image' && !uploadedImageFile && !uploadedImageFiles.length
        && !uploadedVideoFile) {
        showToast('⚠️ 请上传图片或视频', true);
        return;
    }

    var engineChoice = document.getElementById('engineSelect')
        ? document.getElementById('engineSelect').value
        : 'auto';

    // 多图 / 视频输入仅 World Labs 引擎支持，自动切换
    var usingMultimodal = (mode === 'image')
        && (uploadedImageFiles.length >= 2 || uploadedVideoFile);
    if (usingMultimodal && engineChoice !== 'world_labs') {
        engineChoice = 'world_labs';
        showToast('ℹ️ 多图/视频输入已自动切换到 World Labs 引擎');
    }

    // 文字模式下，Stable Zero123 / 自动选择引擎需要图片输入；
    // 选择 World Labs 时可直接用纯文字生成
    if (mode === 'text' && !aiGeneratedImageUrl && engineChoice !== 'world_labs') {
        showToast('⚠️ 当前引擎需要图片输入。请点击「AI 生成图片」、切换到图片模式，或选择 World Labs 引擎。', true);
        return;
    }

    var btn = document.getElementById('generateBtn');
    btn.disabled = true;
    btn.textContent = '⏳ 生成中...';

    showLoading();
    pollCount = 0;

    // 取消之前的请求
    if (abortController) {
        abortController.abort();
    }
    abortController = new AbortController();

    try {
        var useLlm = document.getElementById('useLlmToggle').checked;
        var formData = new FormData();
        formData.append('prompt', prompt || '');
        formData.append('use_local_llm', useLlm && llmAvailable ? 'true' : 'false');
        formData.append('engine', engineChoice);

        // 附加所选 LLM 模型与 3D 后端
        var llmModelSel = document.getElementById('llmModelSelect');
        var backendSel = document.getElementById('backendSelect');
        if (llmModelSel && llmModelSel.style.display !== 'none' && llmModelSel.value) {
            formData.append('llm_model', llmModelSel.value);
        }
        if (backendSel && backendSel.value) {
            formData.append('three_d_backend', backendSel.value);
        }

        // World Labs Marble 模型与全景标记
        var worldModelSel = document.getElementById('worldModelSelect');
        if (worldModelSel && worldModelSel.value) {
            formData.append('world_model', worldModelSel.value);
        }
        var isPanoToggle = document.getElementById('isPanoToggle');
        if (isPanoToggle && isPanoToggle.checked) {
            formData.append('is_pano', 'true');
        }

        if (mode === 'image' && uploadedImageFile) {
            formData.append('image', uploadedImageFile);
        }

        // 多图 / 视频输入（World Labs 引擎）
        if (mode === 'image' && usingMultimodal) {
            if (uploadedVideoFile) {
                formData.append('video', uploadedVideoFile);
            } else {
                uploadedImageFiles.forEach(function (f) {
                    formData.append('images', f);
                });
                formData.append('reconstruct_images', 'true');
            }
        }

        // 文字模式：如果有 AI 生成的图片，传递 URL
        if (mode === 'text' && aiGeneratedImageUrl) {
            formData.append('image_url', aiGeneratedImageUrl);
        }

        var response = await fetch(API_BASE + '/create', {
            method: 'POST',
            body: formData,
            headers: getAuthHeaders(),
            signal: abortController.signal
        });

        if (!response.ok) {
            var errData = null;
            try { errData = await response.json(); } catch (e) { /* ignore */ }
            var errMsg = errData && errData.error
                ? errData.error
                : 'HTTP error! status: ' + response.status;
            throw new Error(errMsg);
        }

        var data = await response.json();

        if (data.enhanced_prompt) {
            document.getElementById('enhancedPromptBox').style.display = 'block';
            document.getElementById('enhancedPromptText').textContent = data.enhanced_prompt;
        } else {
            document.getElementById('enhancedPromptBox').style.display = 'none';
        }

        if (data.success) {
            if (data.status === 'completed' && data.result) {
                if (data.engine_used) {
                    data.result.engine_used = data.engine_used;
                }
                showResult(data.result);
                var engineMsg = data.engine_used ? '（' + data.engine_used + '）' : '';
                showToast('🎉 生成完成！' + engineMsg);
            } else {
                currentTaskId = data.task_id;
                startPolling();
            }
        } else {
            throw new Error(data.error || '未知错误');
        }
    } catch (error) {
        if (error.name === 'AbortError') {
            console.log('Request aborted');
            return;
        }
        showError(error.message);
        showToast('⚠️ 生成失败: ' + error.message, true);
    } finally {
        stopLoadingTimer();
        btn.disabled = false;
        btn.textContent = '🚀 开始生成';
    }
}

// ===== 指数退避轮询 =====
function startPolling() {
    if (pollTimeout) clearTimeout(pollTimeout);
    pollCount = 0;
    pollOnce();
}

function pollOnce() {
    // 指数退避：3s, 3s, 4.5s, 6.75s, ... 最大 15s
    var delay = Math.min(3000 * Math.pow(1.5, pollCount), 15000);
    pollCount++;

    pollTimeout = setTimeout(async function () {
        try {
            var url = API_BASE + '/task/' + currentTaskId;
            var response = await fetch(url, {
                headers: getAuthHeaders()
            });
            if (!response.ok) {
                throw new Error('HTTP error! status: ' + response.status);
            }

            var data = await response.json();

            if (data.success) {
                if (data.status === 'completed') {
                    pollTimeout = null;
                    showResult(data.result);
                    showToast('🎉 生成完成！');
                    return;
                } else if (pollCount > 60) {
                    pollTimeout = null;
                    showError('生成超时，请稍后重试');
                    return;
                } else {
                    var progress = escapeHtml(data.progress || '生成中...');
                    var elapsed = 0;
                    // 计算已等待的总时间（近似）
                    for (var i = 0; i < pollCount; i++) {
                        elapsed += Math.min(3000 * Math.pow(1.5, i), 15000) / 1000;
                    }
                    document.getElementById('resultArea').innerHTML =
                        '<div class="loading-container">' +
                        '<div class="spinner"></div>' +
                        '<div class="loading-text">' + progress + '</div>' +
                        '<div class="loading-subtext">已等待约 ' + Math.round(elapsed) + ' 秒...</div>' +
                        '<button class="btn btn-cancel" style="max-width:200px;margin-top:15px;" onclick="cancelGeneration()">❌ 取消生成</button>' +
                        '</div>';
                    // 继续轮询
                    pollOnce();
                }
            } else {
                pollTimeout = null;
                showError(data.error || '获取状态失败');
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                return;
            }
            console.error('Poll error:', error);
            // 网络错误时继续重试（指数退避）
            if (pollCount <= 60) {
                pollOnce();
            }
        }
    }, delay);
}

window.addEventListener('beforeunload', function () {
    if (pollTimeout) clearTimeout(pollTimeout);
    if (abortController) abortController.abort();
});
