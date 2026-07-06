
        const API_BASE = window.location.origin + '/api';
        let currentTaskId = null;
        let currentWorldUrl = null;
        let pollInterval = null;
        let checkCount = 0;
        let userApiKey = '';
        let llmAvailable = false;
        let currentMode = 'text';
        let uploadedImageFile = null;
        let abortController = null;

        // ===== 模式切换 =====
        function switchMode(mode) {
            currentMode = mode;
            document.getElementById('tabText').classList.toggle('active', mode === 'text');
            document.getElementById('tabImage').classList.toggle('active', mode === 'image');
            document.getElementById('modeText').classList.toggle('active', mode === 'text');
            document.getElementById('modeImage').classList.toggle('active', mode === 'image');
            
            // 更新 ARIA 属性
            document.getElementById('tabText').setAttribute('aria-selected', mode === 'text');
            document.getElementById('tabImage').setAttribute('aria-selected', mode === 'image');
        }

        // ===== 页面加载时初始化 =====
        document.addEventListener('DOMContentLoaded', async function () {
            const savedKey = localStorage.getItem('worldlabs_api_key');
            if (savedKey) {
                document.getElementById('apiKeyInput').value = savedKey;
                userApiKey = savedKey;
            }
            await checkLlmStatus();
            initImageUpload();
        });

        // ===== 检测本地 LLM =====
        async function checkLlmStatus() {
            const statusEl = document.getElementById('llmStatus');
            try {
                const response = await fetch(`${API_BASE}/llm-status`);
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const data = await response.json();
                if (data.available) {
                    llmAvailable = true;
                    statusEl.textContent = `✓ ${data.type.toUpperCase()}`;
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
            const useLlm = document.getElementById('useLlmToggle').checked;
            console.log('Local LLM toggle:', useLlm);
        }

        function saveApiKey() {
            const key = document.getElementById('apiKeyInput').value.trim();
            if (key) {
                localStorage.setItem('worldlabs_api_key', key);
                userApiKey = key;
                showToast('✅ API Key 已保存');
            } else {
                localStorage.removeItem('worldlabs_api_key');
                userApiKey = '';
                showToast('⚠️ 已清除 API Key');
            }
        }

        // ===== 图片上传 =====
        function initImageUpload() {
            const uploadArea = document.getElementById('uploadArea');
            const fileInput = document.getElementById('imageInput');

            // 点击上传
            fileInput.addEventListener('change', function (e) {
                if (e.target.files && e.target.files[0]) {
                    handleImageFile(e.target.files[0]);
                }
            });

            // 拖拽上传
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
                const file = e.dataTransfer.files[0];
                if (file && file.type.startsWith('image/')) {
                    handleImageFile(file);
                } else {
                    showToast('⚠️ 请上传图片文件', true);
                }
            });
        }

        function handleImageFile(file) {
            if (file.size > 10 * 1024 * 1024) {
                showToast('⚠️ 图片不能超过 10MB', true);
                return;
            }
            const ext = file.name.split('.').pop().toLowerCase();
            if (!['jpg', 'jpeg', 'png', 'webp'].includes(ext)) {
                showToast('⚠️ 只支持 JPG / PNG / WEBP 格式', true);
                return;
            }
            uploadedImageFile = file;
            const reader = new FileReader();
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

        function removeImage() {
            uploadedImageFile = null;
            document.getElementById('imageInput').value = '';
            document.getElementById('imagePreviewBox').style.display = 'none';
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
                } else {
                    removeImage();
                    document.getElementById('imagePrompt').value = '';
                }
                showPlaceholder();
                showToast('🗑️ 已清空表单');
            }
        }

        function showPlaceholder() {
            document.getElementById('resultArea').innerHTML = `
                <div class="result-placeholder">
                    <div class="icon">🌍</div>
                    <p>在左侧输入描述或上传图片</p>
                    <p style="margin-top: 8px;">点击生成按钮，你的 3D 世界将在这里展示</p>
                </div>
            `;
        }

        // ===== Toast =====
        function showToast(message, isError = false) {
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.className = 'toast' + (isError ? ' error' : '');
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 3000);
        }

        function showLoading() {
            document.getElementById('resultArea').innerHTML = `
                <div class="loading-container">
                    <div class="spinner"></div>
                    <div class="loading-text">正在生成你的 3D 世界...</div>
                    <div class="loading-subtext">预计需要 30 秒 ~ 5 分钟</div>
                </div>
            `;
        }

        function showResult(data) {
            const area = document.getElementById('resultArea');

            // ===== 检测结果类型：Stable Zero123 多视角 vs World Labs =====
            if (data.view_urls && Array.isArray(data.view_urls) && data.view_urls.length > 0) {
                showStable3DResult(data);
                return;
            }

            // ===== World Labs 结果处理 =====
            currentWorldUrl = data.world_url || data.pano_url;
            const previewUrl = data.preview_url || data.thumbnail_url || data.pano_url;

            let thumbnailHtml = '';
            if (previewUrl) {
                thumbnailHtml = `<img src="${previewUrl}" alt="Preview" style="width:100%;height:100%;object-fit:cover;" onerror="this.parentElement.innerHTML='<div style=\"color:#666;display:flex;align-items:center;justify-content:center;height:100%;\">预览加载失败</div>'">`;
            }

            let actionButtons = '';
            if (data.world_url) {
                actionButtons += `<button class="btn btn-primary" onclick="window.open('${data.world_url}', '_blank')">🌐 打开 3D 世界</button>`;
            }
            if (data.pano_url) {
                actionButtons += `<button class="btn btn-secondary" onclick="window.open('${data.pano_url}', '_blank')">🖼️ 全景图</button>`;
            }
            actionButtons += `<button class="btn btn-secondary" onclick="copyLink()">📋 复制链接</button>`;

            const engineBadge = data.engine_used ? `<span style="color:#00d2ff;font-size:0.75rem;">🔧 ${data.engine_used}</span>` : '';

            area.innerHTML = `
                <div class="pano-container" style="background:#000;">
                    ${thumbnailHtml || '<div style="color:#666;display:flex;align-items:center;justify-content:center;height:100%;">生成中...</div>'}
                </div>
                <div style="margin-top:10px;padding:8px;background:rgba(255,255,255,0.05);border-radius:6px;">
                    <p style="color:#aaa;font-size:0.8rem;">${data.caption || '3D 世界已生成'}</p>
                    ${engineBadge}
                </div>
                <div class="result-actions" style="margin-top:12px;">
                    ${actionButtons}
                </div>
            `;
        }

        // ===== Stable Zero123 多视角结果展示 =====
        function showStable3DResult(data) {
            const area = document.getElementById('resultArea');
            const viewUrls = data.view_urls || [];

            // 保存第一个视角URL作为可复制链接
            currentWorldUrl = viewUrls[0] ? (window.location.origin + '/' + viewUrls[0]) : null;

            // 构建多视角画廊
            let galleryHtml = '';
            viewUrls.forEach((url, i) => {
                const fullUrl = url.startsWith('http') ? url : (window.location.origin + '/' + url);
                galleryHtml += `
                    <div style="position:relative;border-radius:8px;overflow:hidden;cursor:pointer;transition:transform 0.2s;" onmouseover="this.style.transform='scale(1.02)'" onmouseout="this.style.transform='scale(1)'" onclick="window.open('${fullUrl}', '_blank')">
                        <img src="${fullUrl}" alt="视角 ${i + 1}" style="width:100%;aspect-ratio:1;object-fit:cover;background:#000;display:block;" onerror="this.parentElement.innerHTML='<div style=\"aspect-ratio:1;display:flex;align-items:center;justify-content:center;color:#666;background:#111;\">加载失败</div>'">
                        <div style="position:absolute;bottom:0;left:0;right:0;background:rgba(0,0,0,0.6);padding:4px 8px;font-size:0.75rem;">视角 ${i + 1}</div>
                    </div>
                `;
            });

            const gridCols = viewUrls.length >= 4 ? 'repeat(4, 1fr)' : `repeat(${viewUrls.length}, 1fr)`;
            const caption = data.message || `已生成 ${viewUrls.length} 个3D视角`;
            const genTime = data.generation_time ? `（耗时 ${data.generation_time.toFixed(1)}s）` : '';

            area.innerHTML = `
                <div style="margin-bottom:10px;">
                    <span style="display:inline-block;padding:3px 10px;border-radius:12px;background:rgba(0,255,136,0.15);color:#00ff88;font-size:0.75rem;">🔓 Stable Zero123 开源引擎</span>
                </div>
                <div class="pano-container" style="aspect-ratio:auto;min-height:200px;padding:12px;">
                    <div style="display:grid;grid-template-columns:${gridCols};gap:8px;width:100%;">
                        ${galleryHtml}
                    </div>
                </div>
                <div style="margin-top:10px;padding:8px;background:rgba(255,255,255,0.05);border-radius:6px;">
                    <p style="color:#aaa;font-size:0.8rem;">${caption}${genTime}</p>
                </div>
                <div class="result-actions" style="margin-top:12px;">
                    <button class="btn btn-primary" onclick="downloadAllViews(${JSON.stringify(viewUrls).replace(/"/g, '&quot;')})">📥 下载所有视角</button>
                    <button class="btn btn-secondary" onclick="copyLink()">📋 复制链接</button>
                </div>
            `;
        }

        // ===== 下载所有视角 =====
        function downloadAllViews(viewUrls) {
            if (!viewUrls || !viewUrls.length) return;
            viewUrls.forEach((url, i) => {
                const fullUrl = url.startsWith('http') ? url : (window.location.origin + '/' + url);
                setTimeout(() => {
                    const a = document.createElement('a');
                    a.href = fullUrl;
                    a.download = `3d_view_${i + 1}.png`;
                    a.click();
                }, i * 300);
            });
            showToast('📥 开始下载所有视角...');
        }

        function showError(message) {
            document.getElementById('resultArea').innerHTML = `
                <div class="result-placeholder" style="color: #ff6b6b;">
                    <div class="icon">❌</div>
                    <p>生成失败</p>
                    <p style="margin-top: 8px; font-size: 0.85rem;">${message}</p>
                    <button class="btn btn-secondary" style="margin-top: 15px;" onclick="showPlaceholder()">返回</button>
                </div>
            `;
        }

        function copyLink() {
            if (currentWorldUrl) {
                navigator.clipboard.writeText(currentWorldUrl).then(() => {
                    showToast('✅ 链接已复制');
                }).catch(err => {
                    console.error('Copy failed:', err);
                    showToast('⚠️ 复制失败，请手动复制', true);
                });
            }
        }

        // ===== 核心：生成 3D 世界 =====
        async function generateWorld() {
            const mode = currentMode;
            const prompt = mode === 'text'
                ? document.getElementById('prompt').value.trim()
                : document.getElementById('imagePrompt').value.trim();

            if (mode === 'text' && !prompt) {
                showToast('⚠️ 请输入提示词', true);
                return;
            }
            if (mode === 'image' && !uploadedImageFile) {
                showToast('⚠️ 请上传图片', true);
                return;
            }

            const btn = document.getElementById('generateBtn');
            btn.disabled = true;
            btn.textContent = '⏳ 生成中...';

            showLoading();
            checkCount = 0;

            // 取消之前的请求
            if (abortController) {
                abortController.abort();
            }
            abortController = new AbortController();

            try {
                const useLlm = document.getElementById('useLlmToggle').checked;
                const engineChoice = document.getElementById('engineSelect') ? document.getElementById('engineSelect').value : 'auto';
                const formData = new FormData();
                formData.append('prompt', prompt || '');
                formData.append('use_local_llm', useLlm && llmAvailable ? 'true' : 'false');
                formData.append('engine', engineChoice);
                if (userApiKey) {
                    formData.append('api_key', userApiKey);
                }

                if (mode === 'image' && uploadedImageFile) {
                    formData.append('image', uploadedImageFile);
                }

                const response = await fetch(`${API_BASE}/create`, {
                    method: 'POST',
                    body: formData,
                    signal: abortController.signal
                });

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const data = await response.json();

                if (data.enhanced_prompt) {
                    document.getElementById('enhancedPromptBox').style.display = 'block';
                    document.getElementById('enhancedPromptText').textContent = data.enhanced_prompt;
                } else {
                    document.getElementById('enhancedPromptBox').style.display = 'none';
                }

                if (data.success) {
                    if (data.status === 'completed' && data.result) {
                        // 合并 engine_used 到 result 中，供 showResult 使用
                        if (data.engine_used) {
                            data.result.engine_used = data.engine_used;
                        }
                        showResult(data.result);
                        const engineMsg = data.engine_used ? `（${data.engine_used}）` : '';
                        showToast('🎉 生成完成！' + engineMsg);
                    } else if (data.engine_used === 'stable-zero123' && data.result && data.result.view_urls) {
                        // Stable Zero123 直接返回结果（status=completed 但 result 在顶层）
                        showResult(data.result);
                        showToast('🎉 Stable Zero123 生成完成！');
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
                btn.disabled = false;
                btn.textContent = '🚀 开始生成';
            }
        }

        function startPolling() {
            if (pollInterval) clearInterval(pollInterval);

            pollInterval = setInterval(async () => {
                checkCount++;

                try {
                    let url = `${API_BASE}/task/${currentTaskId}`;
                    if (userApiKey) {
                        url += `?api_key=${encodeURIComponent(userApiKey)}`;
                    }

                    const response = await fetch(url);
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }

                    const data = await response.json();

                    if (data.success) {
                        if (data.status === 'completed') {
                            clearInterval(pollInterval);
                            showResult(data.result);
                            showToast('🎉 生成完成！');
                        } else if (checkCount > 60) {
                            clearInterval(pollInterval);
                            showError('生成超时，请稍后重试');
                        } else {
                            const progress = data.progress || '生成中...';
                            document.getElementById('resultArea').innerHTML = `
                                <div class="loading-container">
                                    <div class="spinner"></div>
                                    <div class="loading-text">${progress}</div>
                                    <div class="loading-subtext">已等待 ${checkCount * 3} 秒...</div>
                                </div>
                            `;
                        }
                    } else {
                        clearInterval(pollInterval);
                        showError(data.error || '获取状态失败');
                    }
                } catch (error) {
                    if (error.name === 'AbortError') {
                        return;
                    }
                    console.error('Poll error:', error);
                }
            }, 3000);
        }

        window.addEventListener('beforeunload', () => {
            if (pollInterval) clearInterval(pollInterval);
            if (abortController) abortController.abort();
        });
    