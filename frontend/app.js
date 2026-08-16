/**
 * Idea-to-Video Generator — Frontend Application
 *
 * Handles project creation, SSE-based real-time progress tracking,
 * dynamic UI updates, and project history management.
 */

// ─────────────────────────────────────────────
// Configuration
// ─────────────────────────────────────────────
const API_BASE = window.location.origin + '/api';
const HISTORY_KEY = 'videogen_history';

// ─────────────────────────────────────────────
// State
// ─────────────────────────────────────────────
let currentProject = null;
let eventSource = null;

// ─────────────────────────────────────────────
// DOM References
// ─────────────────────────────────────────────
const DOM = {
    topicInput:      () => document.getElementById('topic-input'),
    aspectRatio:     () => document.getElementById('aspect-ratio'),
    numScenes:       () => document.getElementById('num-scenes'),
    ttsEngine:       () => document.getElementById('tts-engine'),
    voiceSelect:     () => document.getElementById('voice-select'),
    generateBtn:     () => document.getElementById('generate-btn'),
    inputSection:    () => document.getElementById('input-section'),
    mainContent:     () => document.getElementById('main-content'),
    progressBar:     () => document.getElementById('progress-bar'),
    progressPct:     () => document.getElementById('progress-pct'),
    progressStatus:  () => document.getElementById('progress-status'),
    scenesGrid:      () => document.getElementById('scenes-grid'),
    scenesEmpty:     () => document.getElementById('scenes-empty'),
    logPanel:        () => document.getElementById('log-panel'),
    videoWrapper:    () => document.getElementById('video-wrapper'),
    videoPlaceholder:() => document.getElementById('video-placeholder'),
    videoPlayer:     () => document.getElementById('video-player'),
    videoActions:    () => document.getElementById('video-actions'),
    previewLoading:  () => document.getElementById('preview-loading'),
    historyGrid:     () => document.getElementById('history-grid'),
    historySection:  () => document.getElementById('history-section'),
    toastContainer:  () => document.getElementById('toast-container'),
};

// ─────────────────────────────────────────────
// Initialization
// ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadHistory();

    // Enter key to submit
    DOM.topicInput().addEventListener('keydown', (e) => {
        if (e.key === 'Enter') startGeneration();
    });

    // Update video wrapper aspect ratio when setting changes
    DOM.aspectRatio().addEventListener('change', updateVideoWrapperAspect);
});

// ─────────────────────────────────────────────
// Project Creation
// ─────────────────────────────────────────────
async function startGeneration() {
    const topic = DOM.topicInput().value.trim();
    if (!topic) {
        showToast('Please enter a topic for your video', 'error');
        DOM.topicInput().focus();
        return;
    }

    const aspectRatio = DOM.aspectRatio().value;
    const numScenes = parseInt(DOM.numScenes().value, 10);
    const targetDuration = parseInt(document.getElementById('target-duration').value, 10);
    const ttsEngine = DOM.ttsEngine().value;
    const videoEngine = document.getElementById('video-engine').value;
    const imageEngine = document.getElementById('image-engine').value;
    const voiceId = DOM.voiceSelect().value;

    // Disable input
    DOM.generateBtn().disabled = true;
    DOM.generateBtn().innerHTML = '<span class="loading-spinner"></span> <span>Starting...</span>';

    try {
        const response = await fetch(`${API_BASE}/projects`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                topic,
                aspect_ratio: aspectRatio,
                num_scenes: numScenes,
                target_duration: targetDuration,
                tts_engine: ttsEngine,
                video_engine: videoEngine,
                image_engine: imageEngine,
                voice_id: voiceId,
            }),
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to create project');
        }

        const project = await response.json();
        currentProject = project;

        // Show pipeline dashboard
        showDashboard();
        updateVideoWrapperAspect();

        // Connect to SSE stream
        connectSSE(project.id);

        // Save to history
        saveToHistory(project);

        showToast('Video generation started!', 'success');
        addLog('Project created: ' + project.id, 'info');

    } catch (error) {
        showToast('Error: ' + error.message, 'error');
        console.error('Creation error:', error);
    } finally {
        DOM.generateBtn().disabled = false;
        DOM.generateBtn().innerHTML = '<span>✨</span> <span>Generate Video</span>';
    }
}

// ─────────────────────────────────────────────
// SSE Connection
// ─────────────────────────────────────────────
function connectSSE(projectId) {
    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource(`${API_BASE}/projects/${projectId}/stream`);

    eventSource.addEventListener('connected', (e) => {
        const data = JSON.parse(e.data);
        addLog('Connected to pipeline stream', 'info');
        updateProgress(data.progress || 0, data.status || 'pending');
    });

    eventSource.addEventListener('status_change', (e) => {
        const data = JSON.parse(e.data);
        addLog(data.message || 'Status updated', 'info');
        updateProgress(data.progress || 0);
        updatePipelineSteps(data.status);
    });

    eventSource.addEventListener('script_ready', (e) => {
        const data = JSON.parse(e.data);
        addLog(data.message || 'Script ready', 'success');
        updateProgress(data.progress || 15);
        renderScenes(data.scenes || []);
        updatePipelineSteps('generating_media');
        setStepComplete('script');
    });

    eventSource.addEventListener('scene_update', (e) => {
        const data = JSON.parse(e.data);
        addLog(data.message || 'Scene updated', 'info');
        updateSceneStatus(data.scene_index, data.scene_status);
        if (data.progress) updateProgress(data.progress);
    });

    eventSource.addEventListener('complete', (e) => {
        const data = JSON.parse(e.data);
        addLog('🎉 ' + (data.message || 'Video generation complete!'), 'success');
        updateProgress(100);
        setStepComplete('media');
        setStepComplete('assembly');
        setStepComplete('complete');
        showVideoPlayer(data.final_video_url);
        updateHistoryStatus(currentProject.id, 'completed');
        showToast('Your video is ready! 🎬', 'success');
        eventSource.close();
    });

    eventSource.addEventListener('error', (e) => {
        if (e.data) {
            const data = JSON.parse(e.data);
            addLog('❌ ' + (data.message || 'Pipeline error'), 'error');
            showToast('Generation failed: ' + (data.error || 'Unknown error'), 'error');
            updateHistoryStatus(currentProject.id, 'failed');
        }
        eventSource.close();
    });

    eventSource.addEventListener('ping', () => {
        // Keepalive — do nothing
    });

    eventSource.onerror = () => {
        // SSE reconnect is automatic, but log it
        addLog('Connection interrupted, reconnecting...', 'error');
    };
}

// ─────────────────────────────────────────────
// UI Updates
// ─────────────────────────────────────────────
function showDashboard() {
    DOM.mainContent().classList.remove('hidden');
    DOM.inputSection().style.opacity = '0.6';
    DOM.inputSection().style.pointerEvents = 'none';
    DOM.previewLoading().classList.remove('hidden');

    // Reset pipeline steps
    document.querySelectorAll('.pipeline-step').forEach(step => {
        step.classList.remove('active', 'completed', 'failed');
    });
    document.getElementById('step-script').classList.add('active');

    // Clear scenes
    DOM.scenesEmpty().classList.remove('hidden');
    const grid = DOM.scenesGrid();
    grid.querySelectorAll('.scene-card').forEach(c => c.remove());

    // Reset video
    DOM.videoPlayer().classList.add('hidden');
    DOM.videoPlaceholder().classList.remove('hidden');
    DOM.videoActions().classList.add('hidden');

    // Clear log
    DOM.logPanel().innerHTML = '';

    // Scroll to dashboard
    DOM.mainContent().scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function updateProgress(progress, statusText) {
    const pct = Math.min(100, Math.max(0, progress));
    DOM.progressBar().style.width = pct + '%';
    DOM.progressPct().textContent = Math.round(pct) + '%';

    if (statusText) {
        const labels = {
            'pending': 'Initializing...',
            'generating_script': '✍️ Generating Script...',
            'generating_media': '🎨 Generating Media...',
            'assembling': '🔧 Assembling Video...',
            'completed': '✅ Complete!',
            'failed': '❌ Failed',
        };
        DOM.progressStatus().textContent = labels[statusText] || statusText;
    }
}

function updatePipelineSteps(status) {
    const stepMap = {
        'generating_script': 'script',
        'generating_media': 'media',
        'assembling': 'assembly',
        'completed': 'complete',
    };

    const activeStep = stepMap[status];
    if (!activeStep) return;

    document.querySelectorAll('.pipeline-step').forEach(step => {
        step.classList.remove('active');
    });

    const el = document.getElementById('step-' + activeStep);
    if (el) el.classList.add('active');
}

function setStepComplete(stepName) {
    const el = document.getElementById('step-' + stepName);
    if (el) {
        el.classList.remove('active');
        el.classList.add('completed');
        el.querySelector('.step-indicator').textContent = '✓';
    }
}

function renderScenes(scenes) {
    DOM.scenesEmpty().classList.add('hidden');
    const grid = DOM.scenesGrid();

    // Remove old scene cards
    grid.querySelectorAll('.scene-card').forEach(c => c.remove());

    scenes.forEach((scene, i) => {
        const card = document.createElement('div');
        card.className = 'scene-card fade-in';
        card.id = `scene-card-${i}`;
        card.innerHTML = `
            <div class="scene-header">
                <span class="scene-number">Scene ${i + 1}</span>
                <span class="scene-status-badge badge-pending" id="scene-badge-${i}">Pending</span>
            </div>
            <div class="scene-narration">"${escapeHtml(scene.narration)}"</div>
            <div class="scene-prompt">🎨 ${escapeHtml(scene.visual_prompt)}</div>
        `;
        grid.appendChild(card);
    });
}

function updateSceneStatus(index, status) {
    const card = document.getElementById(`scene-card-${index}`);
    const badge = document.getElementById(`scene-badge-${index}`);
    if (!card || !badge) return;

    card.classList.remove('active', 'completed');

    const statusConfig = {
        'pending':          { text: 'Pending',      css: 'badge-pending' },
        'generating_audio': { text: 'Audio...',     css: 'badge-active' },
        'generating_video': { text: 'Video...',     css: 'badge-active' },
        'generating_media': { text: 'Generating...',css: 'badge-active' },
        'merging':          { text: 'Merging...',   css: 'badge-active' },
        'completed':        { text: 'Done ✓',      css: 'badge-completed' },
        'failed':           { text: 'Failed ✕',    css: 'badge-failed' },
    };

    const config = statusConfig[status] || statusConfig['pending'];
    badge.textContent = config.text;
    badge.className = 'scene-status-badge ' + config.css;

    if (status === 'completed') card.classList.add('completed');
    else if (status !== 'pending' && status !== 'failed') card.classList.add('active');
}

function showVideoPlayer(videoUrl) {
    DOM.videoPlaceholder().classList.add('hidden');
    DOM.previewLoading().classList.add('hidden');

    const player = DOM.videoPlayer();
    player.src = videoUrl;
    player.classList.remove('hidden');
    player.load();

    DOM.videoActions().classList.remove('hidden');

    // Re-enable input
    DOM.inputSection().style.opacity = '1';
    DOM.inputSection().style.pointerEvents = 'auto';
}

function updateVideoWrapperAspect() {
    const wrapper = DOM.videoWrapper();
    wrapper.classList.remove('landscape', 'square');
    const ratio = DOM.aspectRatio().value;
    if (ratio === '16:9') wrapper.classList.add('landscape');
    else if (ratio === '1:1') wrapper.classList.add('square');
}

// ─────────────────────────────────────────────
// Actions
// ─────────────────────────────────────────────
function downloadVideo() {
    if (!currentProject) return;
    window.open(`${API_BASE}/projects/${currentProject.id}/download`, '_blank');
}

function newProject() {
    // Reset state
    currentProject = null;
    if (eventSource) eventSource.close();

    // Reset UI
    DOM.mainContent().classList.add('hidden');
    DOM.inputSection().style.opacity = '1';
    DOM.inputSection().style.pointerEvents = 'auto';
    DOM.topicInput().value = '';
    DOM.topicInput().focus();

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function loadProject(projectId) {
    try {
        const response = await fetch(`${API_BASE}/projects/${projectId}`);
        if (!response.ok) throw new Error('Project not found');

        const project = await response.json();
        currentProject = project;

        // Set input values
        DOM.topicInput().value = project.topic;
        DOM.aspectRatio().value = project.aspect_ratio;
        DOM.numScenes().value = project.num_scenes;

        showDashboard();
        updateVideoWrapperAspect();
        updateProgress(project.progress, project.status);

        // Render scenes if available
        if (project.scenes && project.scenes.length > 0) {
            renderScenes(project.scenes);
            project.scenes.forEach(s => updateSceneStatus(s.index, s.status));
        }

        // Show video if completed
        if (project.status === 'completed' && project.final_video_path) {
            showVideoPlayer(`${API_BASE}/projects/${project.id}/download`);
            setStepComplete('script');
            setStepComplete('media');
            setStepComplete('assembly');
            setStepComplete('complete');
        }

        // Connect SSE if still in progress
        if (!['completed', 'failed'].includes(project.status)) {
            connectSSE(project.id);
        }

        addLog('Loaded project: ' + project.id, 'info');

    } catch (error) {
        showToast('Could not load project: ' + error.message, 'error');
    }
}

async function deleteProject(projectId, event) {
    event.stopPropagation();

    if (!confirm('Delete this project and all its files?')) return;

    try {
        await fetch(`${API_BASE}/projects/${projectId}`, { method: 'DELETE' });
        removeFromHistory(projectId);
        showToast('Project deleted', 'info');
    } catch (error) {
        showToast('Failed to delete project', 'error');
    }
}

// ─────────────────────────────────────────────
// Activity Log
// ─────────────────────────────────────────────
function addLog(message, type = 'info') {
    const panel = DOM.logPanel();
    const now = new Date().toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });

    const entry = document.createElement('div');
    entry.className = `log-entry log-${type} fade-in`;
    entry.innerHTML = `
        <span class="log-time">${now}</span>
        <span class="log-msg">${escapeHtml(message)}</span>
    `;

    panel.appendChild(entry);
    panel.scrollTop = panel.scrollHeight;
}

// ─────────────────────────────────────────────
// Project History (localStorage)
// ─────────────────────────────────────────────
function getHistory() {
    try {
        return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    } catch {
        return [];
    }
}

function saveToHistory(project) {
    const history = getHistory();
    history.unshift({
        id: project.id,
        topic: project.topic,
        status: project.status,
        aspect_ratio: project.aspect_ratio,
        created_at: project.created_at,
    });
    // Keep last 20
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, 20)));
    loadHistory();
}

function updateHistoryStatus(projectId, status) {
    const history = getHistory();
    const item = history.find(h => h.id === projectId);
    if (item) {
        item.status = status;
        localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
        loadHistory();
    }
}

function removeFromHistory(projectId) {
    const history = getHistory().filter(h => h.id !== projectId);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
    loadHistory();
}

function loadHistory() {
    const history = getHistory();
    const grid = DOM.historyGrid();
    grid.innerHTML = '';

    if (history.length === 0) {
        DOM.historySection().classList.add('hidden');
        return;
    }

    DOM.historySection().classList.remove('hidden');

    history.forEach(item => {
        const card = document.createElement('div');
        card.className = 'history-card';
        card.onclick = () => loadProject(item.id);

        const statusClass = {
            'completed': 'badge-completed',
            'failed': 'badge-failed',
            'pending': 'badge-pending',
        }[item.status] || 'badge-active';

        const statusLabel = {
            'completed': '✓ Done',
            'failed': '✕ Failed',
            'pending': 'Pending',
        }[item.status] || 'In Progress';

        const date = new Date(item.created_at).toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });

        card.innerHTML = `
            <div class="history-card-topic">${escapeHtml(item.topic)}</div>
            <div class="history-card-meta">
                <span class="history-card-date">${date}</span>
                <span class="history-card-status ${statusClass}">${statusLabel}</span>
            </div>
        `;

        grid.appendChild(card);
    });
}

// ─────────────────────────────────────────────
// Toast Notifications
// ─────────────────────────────────────────────
function showToast(message, type = 'info') {
    const container = DOM.toastContainer();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ─────────────────────────────────────────────
// Utilities
// ─────────────────────────────────────────────
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ─────────────────────────────────────────────
// TTS Engine / Voice Management
// ─────────────────────────────────────────────
const EDGE_VOICES = [
    { id: 'en-US-GuyNeural',      label: 'Guy (US Male)' },
    { id: 'en-US-JennyNeural',    label: 'Jenny (US Female)' },
    { id: 'en-US-AriaNeural',     label: 'Aria (US Female, Expressive)' },
    { id: 'en-GB-RyanNeural',     label: 'Ryan (British Male)' },
    { id: 'en-GB-SoniaNeural',    label: 'Sonia (British Female)' },
    { id: 'en-AU-WilliamNeural',  label: 'William (Australian Male)' },
    { id: 'en-IN-PrabhatNeural',  label: 'Prabhat (Indian Male - English)' },
    { id: 'en-IN-NeerjaNeural',   label: 'Neerja (Indian Female - English)' },
    { id: 'hi-IN-MadhurNeural',   label: 'Madhur (Hindi Male)' },
    { id: 'hi-IN-SwaraNeural',    label: 'Swara (Hindi Female)' },
];

const ELEVENLABS_VOICES = [
    { id: 'JBFqnCBsd6RMkjVDRZzb', label: 'George (Male)' },
    { id: 'EXAVITQu4vr4xnSDxMaL', label: 'Sarah (Female)' },
    { id: '21m00Tcm4TlvDq8ikWAM', label: 'Rachel (Female)' },
    { id: 'ErXwobaYiN019PkySvjV', label: 'Antoni (Male)' },
];

function onEngineChange() {
    const engine = DOM.ttsEngine().value;
    const select = DOM.voiceSelect();
    const voices = engine === 'elevenlabs' ? ELEVENLABS_VOICES : EDGE_VOICES;

    select.innerHTML = '';
    voices.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.id;
        opt.textContent = v.label;
        select.appendChild(opt);
    });
}

