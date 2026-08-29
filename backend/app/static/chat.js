/**
 * RTAI Chat - Vanilla JavaScript Client
 * Connects to RTAI backend via WebSocket (Protocol v1)
 */

// ===== State =====
const state = {
    ws: null,
    isGenerating: false,
    sessionId: 'session-' + Date.now(),
    turnId: 0,
    requestCounter: 0,
    currentDelta: '',
    currentMessageDiv: null,
    projectFolder: '',
    capabilities: {
        agents: [],
        models: [],
        modes: [],
        thinkingLevels: []
    },
    selectedModel: '',
    selectedAgent: '',
    selectedMode: '',
    thinkingLevel: 'off',
    openDropdown: null  // 'agent', 'model', 'thinking', or null
};

// ===== DOM Elements =====
const elements = {
    statusDot: document.getElementById('statusDot'),
    statusText: document.getElementById('statusText'),
    cwdText: document.getElementById('cwdText'),
    messages: document.getElementById('messages'),
    input: document.getElementById('input'),
    sendBtn: document.getElementById('sendBtn'),
    stopBtn: document.getElementById('stopBtn'),
    headerTitle: document.getElementById('headerTitle'),
    modelName: document.getElementById('modelName'),
    modelPicker: document.getElementById('modelPicker'),
    searchInput: document.getElementById('searchInput'),
    projectFolder: document.getElementById('projectFolder'),
    sessionList: document.getElementById('sessionList')
};

// ===== Theme =====
function toggleTheme() {
    const html = document.documentElement;
    const isDark = html.classList.toggle('dark');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
}

function loadTheme() {
    const saved = localStorage.getItem('theme');
    if (saved === 'light') {
        document.documentElement.classList.remove('dark');
    }
}

// ===== Dropdown Helpers =====
function openDropdown(type) {
    if (state.openDropdown === type) {
        closeDropdown();
        return;
    }
    closeDropdown();
    state.openDropdown = type;

    const dropdown = document.getElementById(`${type}Dropdown`);
    if (dropdown) {
        dropdown.classList.add('active');
        const btn = document.getElementById(`${type}Btn`);
        if (btn) {
            const rect = btn.getBoundingClientRect();
            const dropdownContent = dropdown.querySelector('.dropdown-content');
            
            // Ensure content is visible to measure
            dropdownContent.style.visibility = 'hidden';
            dropdownContent.style.display = 'block';
            const contentHeight = dropdownContent.scrollHeight;
            dropdownContent.style.display = '';
            dropdownContent.style.visibility = '';
            
            const dropdownHeight = Math.min(260, contentHeight);
            
            // Check if opening downward would go off screen
            const spaceBelow = window.innerHeight - rect.bottom;
            const spaceAbove = rect.top;
            
            let top, left;
            left = rect.left;
            
            if (spaceBelow < dropdownHeight && spaceAbove > dropdownHeight) {
                // Open upward
                top = rect.top - dropdownHeight - 4;
            } else {
                // Open downward
                top = rect.bottom + 4;
            }
            
            // Check right edge
            const dropdownWidth = dropdown.offsetWidth || 200;
            if (left + dropdownWidth > window.innerWidth) {
                left = Math.max(4, window.innerWidth - dropdownWidth - 4);
            }
            
            dropdown.style.top = top + 'px';
            dropdown.style.left = left + 'px';
            
            // Add scroll if needed
            dropdownContent.style.maxHeight = dropdownHeight + 'px';
        }
    }
}

function closeDropdown() {
    if (state.openDropdown) {
        const type = state.openDropdown;
        state.openDropdown = null;
        const dropdown = document.getElementById(`${type}Dropdown`);
        if (dropdown) {
            dropdown.classList.remove('active');
            const dropdownContent = dropdown.querySelector('.dropdown-content');
            if (dropdownContent) {
                dropdownContent.style.maxHeight = '';
                dropdownContent.style.overflowY = '';
            }
        }
    }
}

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
    if (!e.target.closest('.ctrl-btn') && !e.target.closest('.dropdown')) {
        closeDropdown();
    }
});

function selectAgent(agentId) {
    state.selectedAgent = agentId;
    const btn = document.getElementById('agentBtn');
    if (btn) {
        const agent = state.capabilities.agents.find(a => a.id === agentId);
        btn.title = agent ? agent.label : agentId;
        btn.querySelector('.btn-label').textContent = agent ? agent.label : agentId;
    }
    closeDropdown();
    sendSelectAgent(agentId);
}

function selectModel(modelId) {
    state.selectedModel = modelId;
    const btn = document.getElementById('modelBtn');
    if (btn) {
        const model = state.capabilities.models.find(m => m.id === modelId);
        btn.title = model ? model.label : modelId;
        btn.querySelector('.btn-label').textContent = model ? model.label : modelId;
        document.getElementById('modelName').textContent = model ? model.label : modelId;
    }
    closeDropdown();
    sendSelectModel(modelId);
}

function setThinkingLevel(level) {
    state.thinkingLevel = level;
    const btn = document.getElementById('thinkingBtn');
    if (btn) {
        const labels = { off: 'Off', low: 'Low', medium: 'Medium', high: 'High' };
        btn.title = labels[level] || level;
        btn.querySelector('.btn-label').textContent = labels[level] || level;
    }
    closeDropdown();
    sendSetThinking(level);
}

function sendSelectAgent(agentId) {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    state.requestCounter++;
    const message = {
        protocol_version: 1,
        type: 'select_agent',
        request_id: `req-agent-${state.requestCounter}`,
        session_id: state.sessionId,
        agent_id: agentId
    };
    state.ws.send(JSON.stringify(message));
}

function sendSelectModel(modelId) {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    state.requestCounter++;
    const message = {
        protocol_version: 1,
        type: 'select_model',
        request_id: `req-model-${state.requestCounter}`,
        session_id: state.sessionId,
        model_id: modelId
    };
    state.ws.send(JSON.stringify(message));
}

function sendSetThinking(level) {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    state.requestCounter++;
    const message = {
        protocol_version: 1,
        type: 'set_thinking',
        request_id: `req-thinking-${state.requestCounter}`,
        session_id: state.sessionId,
        level: level
    };
    state.ws.send(JSON.stringify(message));
}

// ===== WebSocket Connection =====
function connect() {
    const folder = elements.projectFolder.value.trim();
    state.projectFolder = folder;

    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = folder ? `${scheme}://${location.host}/ws?cwd=${encodeURIComponent(folder)}` : `${scheme}://${location.host}/ws`;

    state.sessionId = 'session-' + Date.now();
    state.turnId = 0;
    state.requestCounter = 0;

    if (state.ws) {
        state.ws.close();
    }

    state.ws = new WebSocket(url);

    state.ws.onopen = () => {
        setStatus('connecting', 'Connecting...');
    };

    state.ws.onclose = () => {
        setStatus('disconnected', 'Disconnected');
        elements.cwdText.textContent = '';
        state.ws = null;
        // Auto-retry after 3 seconds if there's a project folder
        if (folder) {
            setTimeout(connect, 3000);
        }
    };

    state.ws.onerror = () => {
        setStatus('error', 'Connection error');
    };

    state.ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleEvent(data);
        } catch (e) {
            console.error('Failed to parse message:', e);
        }
    };
}

function setStatus(state, text) {
    elements.statusDot.className = 'status-dot ' + state;
    elements.statusText.textContent = text;
}

// ===== Event Handler =====
function handleEvent(data) {
    console.log('Event:', data.type, data);

    switch (data.type) {
        case 'status':
            handleStatus(data);
            break;

        case 'error':
            handleError(data);
            break;

        case 'command_result':
            handleCommandResult(data);
            break;

        case 'user_message':
            appendUserMessage(data);
            break;

        case 'delta':
            appendDelta(data);
            break;

        case 'done':
            finishGeneration(data);
            break;

        case 'agents_available':
            handleAgentsAvailable(data);
            break;

        case 'models_available':
            handleModelsAvailable(data);
            break;

        case 'model_selected':
            handleModelSelected(data);
            break;

        case 'thinking_available':
            handleThinkingAvailable(data);
            break;

        case 'tool_start':
            handleToolStart(data);
            break;

        case 'tool_result':
            handleToolResult(data);
            break;
    }
}

function handleStatus(data) {
    if (data.state === 'starting') {
        setStatus('connecting', 'Starting...');
    } else if (data.state === 'ready') {
        setStatus('connected', 'Ready');
        elements.cwdText.textContent = data.cwd || '';
    } else if (data.state === 'disconnected') {
        setStatus('disconnected', 'Disconnected');
    }
}

function handleAgentsAvailable(data) {
    if (data.available && data.agents && data.agents.length > 0) {
        state.capabilities.agents = data.agents;
        // Auto-select first agent
        if (!state.selectedAgent) {
            state.selectedAgent = data.agents[0].id;
            const btn = document.getElementById('agentBtn');
            if (btn) {
                btn.title = data.agents[0].label;
                btn.querySelector('.btn-label').textContent = data.agents[0].label;
            }
        }
        populateAgentDropdown();
        console.log('Agents available:', data.agents);
    }
}

function handleModelsAvailable(data) {
    if (data.available && data.models && data.models.length > 0) {
        state.capabilities.models = data.models;
        // Auto-select first model
        if (!state.selectedModel) {
            state.selectedModel = data.models[0].id;
            document.getElementById('modelName').textContent = data.models[0].label || data.models[0].id;
            const btn = document.getElementById('modelBtn');
            if (btn) {
                btn.title = data.models[0].label;
                btn.querySelector('.btn-label').textContent = data.models[0].label;
            }
        }
        populateModelDropdown();
        console.log('Models available:', data.models);
    }
}

function handleModelSelected(data) {
    state.selectedModel = data.model_id;
    const btn = document.getElementById('modelBtn');
    if (btn && data.model_id) {
        const model = state.capabilities.models.find(m => m.id === data.model_id);
        if (model) {
            btn.title = model.label;
            btn.querySelector('.btn-label').textContent = model.label;
        }
    }
    console.log('Model selected:', data.model_id);
}

function handleThinkingAvailable(data) {
    if (data.available && data.thinking_levels) {
        state.capabilities.thinkingLevels = data.thinking_levels;
        if (!state.thinkingLevel || !data.thinking_levels.includes(state.thinkingLevel)) {
            state.thinkingLevel = data.thinking_levels[0] || 'off';
        }
        const btn = document.getElementById('thinkingBtn');
        if (btn) {
            const labels = { off: 'Off', low: 'Low', medium: 'Medium', high: 'High' };
            btn.title = labels[state.thinkingLevel] || state.thinkingLevel;
            btn.querySelector('.btn-label').textContent = labels[state.thinkingLevel] || state.thinkingLevel;
        }
        populateThinkingDropdown();
        console.log('Thinking levels:', data.thinking_levels);
    }
}

function handleCommandResult(data) {
    if (!data.success) {
        console.error('Command failed:', data.command, data.message);
        appendMessage('error', `Command failed: ${data.message || 'Unknown error'}`);
    }
}

function handleError(data) {
    console.error('Error event:', data.message, data.code);
    appendMessage('error', data.message || 'An error occurred');
    if (data.code === 'project_folder_not_provided') {
        setStatus('error', 'No project folder');
    }
}

// ===== Message Handling =====
function appendMessage(role, text) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    div.innerHTML = `
        <div class="avatar">${role === 'user' ? 'U' : role === 'agent' ? 'AI' : '⚠'}</div>
        <div class="bubble">${formatMessage(text)}</div>
    `;
    elements.messages.appendChild(div);
    scrollToBottom();
    return div;
}

function appendUserMessage(data) {
    // User message already displayed, but track it
    console.log('User message sent:', data.text);
}

function appendDelta(data) {
    state.currentDelta += data.text || '';

    if (!state.currentMessageDiv) {
        state.currentMessageDiv = appendMessage('agent', '');
    }

    const html = formatMessage(state.currentDelta);
    state.currentMessageDiv.querySelector('.bubble').innerHTML = html;
    scrollToBottom();
}

function finishGeneration(data) {
    state.isGenerating = false;
    state.sendBtn.style.display = '';
    elements.stopBtn.style.display = 'none';
    state.currentDelta = '';
    state.currentMessageDiv = null;
}

function handleToolStart(data) {
    console.log('Tool started:', data.title || data.tool_call_id);
}

function handleToolResult(data) {
    console.log('Tool result:', data.status, data.content);
}

// ===== Send Message =====
function sendMessage() {
    const text = elements.input.value.trim();
    if (!text || state.isGenerating || !state.ws) return;

    // Add user message immediately
    appendMessage('user', text);

    // Clear input
    elements.input.value = '';
    elements.input.style.height = 'auto';

    // Update header
    elements.headerTitle.textContent = text.substring(0, 40) + (text.length > 40 ? '...' : '');

    // Send to backend with proper protocol v1 format
    state.turnId++;
    state.requestCounter++;

    const message = {
        protocol_version: 1,
        type: 'prompt',
        request_id: `req-${state.requestCounter}`,
        session_id: state.sessionId,
        turn_id: `turn-${state.turnId}`,
        message_id: `msg-${Date.now()}`,
        text: text
    };

    console.log('Sending prompt:', message);
    state.ws.send(JSON.stringify(message));

    state.isGenerating = true;
    state.sendBtn.style.display = 'none';
    elements.stopBtn.style.display = '';
    state.currentDelta = '';
    state.currentMessageDiv = null;
}

function stopGeneration() {
    if (!state.isGenerating || !state.ws) return;

    state.requestCounter++;

    const message = {
        protocol_version: 1,
        type: 'cancel',
        request_id: `req-cancel-${state.requestCounter}`,
        session_id: state.sessionId,
        turn_id: `turn-${state.turnId}`
    };

    console.log('Sending cancel:', message);
    state.ws.send(JSON.stringify(message));

    state.isGenerating = false;
    state.sendBtn.style.display = '';
    elements.stopBtn.style.display = 'none';
    state.currentDelta = '';
    state.currentMessageDiv = null;
}

// ===== Session Management =====
function selectSession(el, title) {
    document.querySelectorAll('.session-item').forEach(item => {
        item.classList.remove('active');
    });
    el.classList.add('active');
    elements.headerTitle.textContent = title;
}

function newSession() {
    state.sessionId = 'session-' + Date.now();
    state.turnId = 0;
    state.requestCounter = 0;
    elements.headerTitle.textContent = 'New Session';
    elements.messages.innerHTML = '';
    appendMessage('agent', 'New session started. Enter a message to begin.');
}

// ===== Dropdown Population =====
function populateAgentDropdown() {
    const container = document.getElementById('agentDropdownContent');
    if (!container || state.capabilities.agents.length === 0) return;

    container.innerHTML = state.capabilities.agents.map(agent => `
        <div class="dropdown-item ${agent.id === state.selectedAgent ? 'active' : ''}"
             onclick="selectAgent('${agent.id}')">
            ${agent.label}
        </div>
    `).join('');
}

function populateModelDropdown() {
    const container = document.getElementById('modelDropdownContent');
    if (!container || state.capabilities.models.length === 0) return;

    container.innerHTML = state.capabilities.models.map(model => `
        <div class="dropdown-item ${model.id === state.selectedModel ? 'active' : ''}"
             onclick="selectModel('${model.id}')">
            ${model.label}
        </div>
    `).join('');
}

function populateThinkingDropdown() {
    const container = document.getElementById('thinkingDropdownContent');
    if (!container) return;

    const labels = { off: 'Thinking off', low: 'Think low', medium: 'Think medium', high: 'Think high' };
    const levels = ['off', 'low', 'medium', 'high']
        .filter(l => state.capabilities.thinkingLevels.includes(l));

    container.innerHTML = levels.map(level => `
        <div class="dropdown-item ${level === state.thinkingLevel ? 'active' : ''}"
             onclick="setThinkingLevel('${level}')">
            ${labels[level] || level}
        </div>
    `).join('');
}

// ===== Utilities =====
function formatMessage(text) {
    if (!text) return '';

    let html = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\n/g, '<br>');

    // Code blocks
    html = html.replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Bold
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // Italic
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');

    return html;
}

function scrollToBottom() {
    elements.messages.scrollTop = elements.messages.scrollHeight;
}

// ===== Input Events =====
elements.input.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 140) + 'px';
});

elements.input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

elements.projectFolder.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        connect();
    }
});

// ===== Search =====
elements.searchInput.addEventListener('input', (e) => {
    const term = e.target.value.toLowerCase();
    document.querySelectorAll('.session-item').forEach(item => {
        const title = item.querySelector('.session-title').textContent.toLowerCase();
        item.style.display = title.includes(term) ? 'flex' : 'none';
    });
});

// ===== Button Event Listeners =====
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('agentBtn').addEventListener('click', () => openDropdown('agent'));
    document.getElementById('modelBtn').addEventListener('click', () => openDropdown('model'));
    document.getElementById('thinkingBtn').addEventListener('click', () => openDropdown('thinking'));
});

// ===== Initialize =====
function init() {
    loadTheme();

    // Auto-connect if project folder is set in localStorage
    const stored = localStorage.getItem('project-folder');
    if (stored) {
        elements.projectFolder.value = stored;
        connect();
    }

    // Focus input after brief delay
    setTimeout(() => {
        elements.input.focus();
    }, 500);
}

// Store project folder when changed
elements.projectFolder.addEventListener('change', (e) => {
    localStorage.setItem('project-folder', e.target.value);
});

// Start when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
