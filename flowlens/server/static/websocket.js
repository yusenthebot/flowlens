/* FlowLens Dashboard — WebSocket real-time update handling */
'use strict';


// =========================================================================
// WebSocket — Real-time trace stream
// =========================================================================
function connectWebSocket() {
  if (wsConnection && wsConnection.readyState === WebSocket.OPEN) return;

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/traces`;

  try {
    wsConnection = new WebSocket(wsUrl);
  } catch (err) {
    console.warn('WebSocket connection failed:', err);
    updateWsStatus('error');
    scheduleWsReconnect();
    return;
  }

  wsConnection.onopen = () => {
    console.log('WebSocket connected');
    wsReconnectAttempts = 0;
    updateWsStatus('connected');
  };

  wsConnection.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.event === 'connected') {
        console.log('WS handshake:', msg.data.message);
        updateWsStatus('connected');
      } else if (msg.event === 'trace_ingested') {
        handleLiveTrace(msg.data);
        handleLiveTraceUpdate(msg.data);
      }
    } catch (err) {
      console.warn('WS message parse error:', err);
    }
  };

  wsConnection.onclose = (evt) => {
    console.log('WebSocket disconnected, code:', evt.code);
    updateWsStatus('disconnected');
    // Only schedule reconnect if not already pending
    if (!wsReconnectTimer) {
      scheduleWsReconnect();
    }
  };

  wsConnection.onerror = (err) => {
    console.warn('WebSocket error:', err);
    updateWsStatus('error');
    // onerror is followed by onclose in browsers; the onclose handler
    // will trigger reconnect. No need to call scheduleWsReconnect here.
  };
}

function scheduleWsReconnect() {
  if (wsReconnectTimer) return; // already scheduled
  wsReconnectAttempts++;
  // Exponential backoff: 1s, 2s, 4s, 8s, ... max 30s
  const delay = Math.min(1000 * Math.pow(2, wsReconnectAttempts - 1), 30000);
  console.log(`WS reconnecting in ${delay}ms (attempt ${wsReconnectAttempts})`);
  wsReconnectTimer = setTimeout(() => {
    wsReconnectTimer = null;
    connectWebSocket();
  }, delay);
}

function updateWsStatus(state) {
  const dot = document.getElementById('ws-dot');
  const label = document.getElementById('ws-label');
  if (state === 'connected') {
    dot.className = 'w-2 h-2 rounded-full bg-emerald-500 pulse-dot';
    label.textContent = 'Live';
    label.className = 'text-emerald-400';
  } else if (state === 'disconnected') {
    dot.className = 'w-2 h-2 rounded-full bg-amber-500';
    label.textContent = 'Reconnecting...';
    label.className = 'text-amber-400';
  } else {
    dot.className = 'w-2 h-2 rounded-full bg-red-500';
    label.textContent = 'Disconnected';
    label.className = 'text-red-400';
  }
}

/** Handle a newly ingested trace received via WebSocket */
function handleLiveTrace(traceData) {
  // Show toast for error traces
  if (traceData.has_errors) {
    showToast(`Error trace: ${traceData.trace_id.substring(0, 12)}... (${traceData.service_name || 'unknown'})`, 'error', 5000);
  }

  // Push to live activity feed
  const agentTag = (traceData.tags || {}).agent || (traceData.metadata || {}).agent || traceData.service_name || 'unknown';
  const actionLabel = traceData.service_name
    ? `New trace — ${traceData.service_name} (${traceData.span_count || 0} spans)`
    : `New trace — ${(traceData.trace_id || '').substring(0, 12)}...`;
  addToLiveFeed({
    agent: agentTag,
    action: actionLabel,
    status: traceData.has_errors ? 'error' : 'ok',
    timestamp: traceData.start_time || Date.now() / 1000,
  });

  // Push to agent terminal if open
  _pushToAgentTerminal(agentTag, {
    tool: traceData.service_name || 'trace',
    status: traceData.has_errors ? 'error' : 'ok',
    duration_ms: traceData.duration_ms || 0,
    timestamp: traceData.start_time || Date.now() / 1000,
    error: traceData.has_errors ? 'error in trace' : null,
  });

  // Push to per-agent live feed (on Agents tab)
  _pushToAgentFeed(agentTag, {
    tool: traceData.service_name || 'trace',
    status: traceData.has_errors ? 'error' : 'ok',
    duration_ms: traceData.duration_ms || 0,
    timestamp: traceData.start_time || Date.now() / 1000,
    error: traceData.has_errors ? 'error in trace' : null,
  });

  // If on overview, prepend to recent traces list
  if (currentView === 'overview') {
    const container = document.getElementById('recent-traces-list');
    // Check if it contains the skeleton placeholder
    const isEmpty = container.querySelector('.skeleton');
    if (isEmpty) container.innerHTML = '';

    const rowHtml = renderTraceRow(traceData, true);
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = rowHtml;
    const newRow = tempDiv.firstElementChild;
    if (newRow) {
      newRow.classList.add('new-trace-highlight');
      // Remove existing dividers by wrapping
      const wrapper = document.createElement('div');
      wrapper.className = 'border-b border-white/5';
      wrapper.appendChild(newRow);
      container.insertBefore(wrapper, container.firstChild);

      // Keep only 8 most recent
      while (container.children.length > 8) {
        container.removeChild(container.lastChild);
      }
    }
    // Also refresh stats and agent activity
    loadStats();
    loadAgentActivity();
  }

  // If on traces list, prepend there too
  if (currentView === 'traces') {
    const container = document.getElementById('traces-list');
    const isEmpty = container.querySelector('.skeleton');
    if (isEmpty) container.innerHTML = '';

    const rowHtml = renderTraceRow(traceData, false);
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = rowHtml;
    const newRow = tempDiv.firstElementChild;
    if (newRow) {
      newRow.classList.add('new-trace-highlight');
      container.insertBefore(newRow, container.firstChild);
    }
  }
}

// =========================================================================
// Live Pulse Indicator
// =========================================================================
let _livePulseTimer = null;
function flashLivePulse() {
  const pulse = document.getElementById('live-pulse');
  if (!pulse) return;
  pulse.classList.remove('hidden');
  if (_livePulseTimer) clearTimeout(_livePulseTimer);
  _livePulseTimer = setTimeout(() => {
    pulse.classList.add('hidden');
    _livePulseTimer = null;
  }, 2000);
}

// =========================================================================
// WebSocket Live Update Handler
// =========================================================================
function handleLiveTraceUpdate(traceData) {
  flashLivePulse();

  // Toast for new trace (existing showToast signature: message, type, duration)
  showToast(`New trace from ${traceData.service_name || 'agent'}`, 'info', 3000);

  // --- Notification hooks ---
  const agentName = traceData.service_name || 'unknown';
  const traceId = traceData.trace_id || null;

  // Error trace notification
  if (traceData.has_errors) {
    addNotification('error', 'Error trace detected',
      `Agent: ${agentName} — trace ${traceId ? traceId.substring(0, 12) + '...' : 'unknown'}`,
      traceId);
  }

  // New agent detected notification
  if (agentName && agentName !== 'unknown' && !knownAgents.has(agentName)) {
    if (knownAgents.size > 0) {
      // Only fire when knownAgents is already seeded (not on first-ever load)
      addNotification('info', 'New agent detected',
        `Agent "${agentName}" is reporting for the first time.`,
        traceId);
    }
    knownAgents.add(agentName);
  }

  // Cost spike notification (single trace > $0.10)
  const traceCost = traceData.total_cost || traceData.cost || 0;
  if (traceCost > 0.10) {
    addNotification('warning', 'Cost spike detected',
      `Agent: ${agentName} — $${traceCost.toFixed(4)} in single trace`,
      traceId);
  }
  // --- End notification hooks ---

  // Flash the corresponding agent card in the Live Monitor
  const monitorAgentName = traceData.tags?.agent || traceData.metadata?.agent || traceData.service_name;
  if (monitorAgentName) {
    const cards = document.querySelectorAll('#live-monitor [data-agent]');
    cards.forEach(card => {
      if (card.dataset.agent === monitorAgentName) {
        card.classList.add('ring-2', 'ring-emerald-400/50');
        setTimeout(() => card.classList.remove('ring-2', 'ring-emerald-400/50'), 2000);
      }
    });
  }

  // Lightweight refresh on WebSocket event — only update stats + traces, skip heavy calls
  if (currentView === 'overview') {
    loadStats();
    loadRecentTraces();
  } else if (currentView === 'traces') {
    loadTraces();
  }
}

/** Push a real-time event to a specific agent's live feed panel */
function _pushToAgentFeed(agentName, ev) {
  const feed = document.getElementById(`agent-feed-${agentName}`);
  if (!feed) return;

  const timeAgo = formatTimeAgo(ev.timestamp);
  const isError = ev.status === 'error';
  const toolName = ev.tool || '?';
  const statusDot = isError
    ? '<span style="width:5px;height:5px;border-radius:50%;background:#ef4444;flex-shrink:0;display:inline-block;"></span>'
    : '<span style="width:5px;height:5px;border-radius:50%;background:#34d399;flex-shrink:0;display:inline-block;"></span>';
  const durStr = ev.duration_ms > 0 ? `${Math.round(ev.duration_ms)}ms` : '';
  const errorHint = isError && ev.error ? ` — ${escHtml(String(ev.error)).substring(0, 40)}` : '';

  const row = document.createElement('div');
  row.className = `flex items-center gap-1.5 py-0.5 text-[10px] leading-tight ${isError ? 'text-red-400' : 'text-slate-400'}`;
  row.title = `${toolName} ${durStr}${errorHint}`;
  row.innerHTML = `${statusDot}
    <span class="font-medium ${isError ? 'text-red-300' : 'text-slate-300'}" style="min-width:48px;">${escHtml(toolName)}</span>
    <span class="text-slate-600 flex-1 truncate">${durStr}${errorHint}</span>
    <span class="text-slate-600 flex-shrink-0">${timeAgo}</span>`;

  // Remove "Loading..." or "No recent" placeholder
  const placeholder = feed.querySelector('.italic');
  if (placeholder) placeholder.remove();

  // Prepend new event
  feed.insertBefore(row, feed.firstChild);

  // Keep max 8 events
  while (feed.children.length > 8) {
    feed.removeChild(feed.lastChild);
  }
}

/** Push a real-time event into the tmux pane for this agent */
function _pushToAgentTerminal(agentName, ev) {
  if (!document.getElementById('tmux-terminal') || _termMinimized) return;
  const pane = _termPanes.find(p => p.agent === agentName);
  if (!pane) return;
  const body = document.getElementById(`tmux-pane-body-${pane.id}`);
  if (!body) return;

  const lineHtml = _termFormatLine(ev, {});
  const tmp = document.createElement('div');
  tmp.innerHTML = lineHtml;
  const line = tmp.firstElementChild;
  if (line) { body.appendChild(line); body.scrollTop = body.scrollHeight; }
}

