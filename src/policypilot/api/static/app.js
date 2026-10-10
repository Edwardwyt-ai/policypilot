const elements = {
  apiKey: document.querySelector("#api-key"),
  userId: document.querySelector("#user-id"),
  connect: document.querySelector("#connect"),
  newChat: document.querySelector("#new-chat"),
  toggleKey: document.querySelector("#toggle-key"),
  connectionStatus: document.querySelector("#connection-status"),
  connectionDetail: document.querySelector("#connection-detail"),
  runtimeStatus: document.querySelector("#runtime-status"),
  conversationLabel: document.querySelector("#conversation-label"),
  messages: document.querySelector("#messages"),
  emptyState: document.querySelector("#empty-state"),
  composer: document.querySelector("#composer"),
  input: document.querySelector("#message-input"),
  send: document.querySelector("#send-message"),
  composerNote: document.querySelector("#composer-note"),
  pending: document.querySelector("#pending-action"),
  pendingTool: document.querySelector("#pending-tool"),
  pendingArguments: document.querySelector("#pending-arguments"),
  confirmAction: document.querySelector("#confirm-action"),
  cancelAction: document.querySelector("#cancel-action"),
  toast: document.querySelector("#toast"),
};

const state = {
  conversationId: null,
  pendingAction: null,
  busy: false,
  connected: false,
};

let toastTimer = null;

function requestId(prefix) {
  const value = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  return `${prefix}-${value}`;
}

function credentials() {
  return {
    apiKey: elements.apiKey.value.trim(),
    userId: elements.userId.value.trim(),
  };
}

function headers() {
  const { apiKey } = credentials();
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${apiKey}`,
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...headers(), ...(options.headers || {}) },
  });
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) {
      // Keep the HTTP fallback when the body is not JSON.
    }
    throw new Error(detail);
  }
  return response.json();
}

function setRuntimeStatus(label, status) {
  elements.runtimeStatus.dataset.state = status;
  elements.runtimeStatus.querySelector("span:last-child").textContent = label;
}

function setBusy(busy, label = "正在处理") {
  state.busy = busy;
  elements.apiKey.disabled = busy;
  elements.connect.disabled = busy;
  elements.newChat.disabled = busy || !state.connected;
  elements.input.disabled = busy || !state.connected || Boolean(state.pendingAction);
  elements.send.disabled = elements.input.disabled || !elements.input.value.trim();
  elements.confirmAction.disabled = busy;
  elements.cancelAction.disabled = busy;
  setRuntimeStatus(busy ? label : state.connected ? "服务就绪" : "待连接", busy ? "busy" : state.connected ? "online" : "offline");
}

function showToast(message) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  toastTimer = setTimeout(() => {
    elements.toast.hidden = true;
  }, 4200);
}

function setConnection(status, detail, stateName) {
  elements.connectionStatus.textContent = status;
  elements.connectionStatus.dataset.state = stateName;
  elements.connectionDetail.textContent = detail;
}

function saveCredentials() {
  const { apiKey } = credentials();
  sessionStorage.setItem("policypilot.apiKey", apiKey);
  sessionStorage.removeItem("policypilot.userId");
}

function restoreCredentials() {
  elements.apiKey.value = sessionStorage.getItem("policypilot.apiKey") || "";
  elements.userId.value = "";
  elements.userId.readOnly = true;
}

function resetConversation() {
  state.conversationId = null;
  state.pendingAction = null;
  elements.pending.hidden = true;
  elements.messages.replaceChildren(elements.emptyState);
  elements.emptyState.hidden = false;
  elements.conversationLabel.textContent = "尚未创建会话";
  elements.composerNote.textContent = state.connected ? "输入自然语言问题" : "连接服务后即可开始对话";
}

async function createConversation() {
  const conversation = await api("/v1/conversations", {
    method: "POST",
    body: JSON.stringify({ metadata: { channel: "web-ui" } }),
  });
  state.conversationId = conversation.id;
  elements.conversationLabel.textContent = `会话 ${conversation.id.slice(0, 8)}`;
  return conversation;
}

async function connect() {
  const { apiKey } = credentials();
  if (!apiKey) {
    showToast("请输入 API Key。");
    return;
  }
  setBusy(true, "正在连接");
  try {
    saveCredentials();
    const identity = await api("/v1/me");
    elements.userId.value = identity.user_id;
    const ready = await fetch("/health/ready").then((response) => {
      if (!response.ok) throw new Error("服务尚未就绪");
      return response.json();
    });
    state.connected = true;
    resetConversation();
    await createConversation();
    const model = ready.details?.embedding_model || ready.details?.retrieval_variant || "runtime";
    setConnection("已连接", `运行时就绪 · ${model}`, "online");
    elements.composerNote.textContent = "输入自然语言问题";
    elements.input.focus();
  } catch (error) {
    state.connected = false;
    resetConversation();
    setConnection("连接失败", error.message, "error");
    showToast(error.message);
  } finally {
    setBusy(false);
  }
}

function timeLabel() {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date());
}

function appendMessage(role, text, detail = "") {
  elements.emptyState.hidden = true;
  if (elements.emptyState.parentNode === elements.messages) {
    elements.emptyState.remove();
  }
  const row = document.createElement("article");
  row.className = "message-row";
  row.dataset.role = role;

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = role === "assistant" ? "P" : "你";

  const content = document.createElement("div");
  content.className = "message-content";
  const meta = document.createElement("div");
  meta.className = "message-meta";
  const author = document.createElement("strong");
  author.textContent = role === "assistant" ? "PolicyPilot" : "你";
  const timestamp = document.createElement("span");
  timestamp.textContent = timeLabel();
  meta.append(author, timestamp);

  const body = document.createElement("p");
  body.className = "message-text";
  body.textContent = text || "操作已处理。";
  content.append(meta, body);
  if (detail) {
    const info = document.createElement("div");
    info.className = "message-detail";
    info.textContent = detail;
    content.append(info);
  }
  row.append(avatar, content);
  elements.messages.append(row);
  elements.messages.scrollTop = elements.messages.scrollHeight;
  return row;
}

function appendThinking() {
  const row = appendMessage("assistant", "正在分析");
  row.classList.add("thinking");
  row.querySelector(".message-text").classList.add("thinking-dots");
  return row;
}

function renderPending(action) {
  state.pendingAction = action || null;
  elements.pending.hidden = !action;
  if (action) {
    elements.pendingTool.textContent = action.tool_name;
    elements.pendingArguments.textContent = JSON.stringify(action.arguments, null, 2);
    elements.composerNote.textContent = "请先确认或取消待执行操作";
  } else {
    elements.composerNote.textContent = "输入自然语言问题";
  }
  setBusy(false);
}

function renderTurn(turn) {
  const detail = turn.tool_calls_executed
    ? `已执行 ${turn.tool_calls_executed} 次读取工具 · 事件 ${turn.event_sequence}`
    : `事件 ${turn.event_sequence}`;
  appendMessage("assistant", turn.assistant_message, detail);
  renderPending(turn.pending_action);
}

async function sendMessage(event) {
  event.preventDefault();
  const content = elements.input.value.trim();
  if (!content || state.busy || state.pendingAction) return;
  if (!state.conversationId) {
    showToast("请先连接服务并创建会话。");
    return;
  }

  appendMessage("user", content);
  elements.input.value = "";
  resizeInput();
  setBusy(true, "Agent 正在工作");
  const thinking = appendThinking();
  try {
    const turn = await api(`/v1/conversations/${state.conversationId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content, request_id: requestId("message") }),
    });
    thinking.remove();
    renderTurn(turn);
  } catch (error) {
    thinking.remove();
    appendMessage("assistant", `请求失败：${error.message}`);
    showToast(error.message);
    setBusy(false);
  }
}

async function resolveAction(operation) {
  if (!state.pendingAction || state.busy) return;
  setBusy(true, operation === "confirm" ? "正在执行操作" : "正在取消操作");
  try {
    const actionId = state.pendingAction.action_id;
    const turn = await api(
      `/v1/conversations/${state.conversationId}/actions/${actionId}/${operation}`,
      {
        method: "POST",
        body: JSON.stringify({ request_id: requestId(operation) }),
      },
    );
    elements.pending.hidden = true;
    state.pendingAction = null;
    renderTurn(turn);
  } catch (error) {
    showToast(error.message);
    setBusy(false);
  }
}

async function newChat() {
  if (!state.connected || state.busy) return;
  setBusy(true, "正在创建会话");
  try {
    resetConversation();
    await createConversation();
    elements.input.focus();
  } catch (error) {
    showToast(error.message);
  } finally {
    setBusy(false);
  }
}

function resizeInput() {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 150)}px`;
  elements.send.disabled = state.busy || !state.connected || Boolean(state.pendingAction) || !elements.input.value.trim();
}

elements.connect.addEventListener("click", connect);
elements.newChat.addEventListener("click", newChat);
elements.composer.addEventListener("submit", sendMessage);
elements.input.addEventListener("input", resizeInput);
elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.composer.requestSubmit();
  }
});
elements.confirmAction.addEventListener("click", () => resolveAction("confirm"));
elements.cancelAction.addEventListener("click", () => resolveAction("cancel"));
elements.toggleKey.addEventListener("click", () => {
  const hidden = elements.apiKey.type === "password";
  elements.apiKey.type = hidden ? "text" : "password";
  elements.toggleKey.setAttribute("aria-label", hidden ? "隐藏 API Key" : "显示 API Key");
  elements.toggleKey.setAttribute("title", hidden ? "隐藏 API Key" : "显示 API Key");
});
document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    elements.input.value = button.dataset.prompt;
    resizeInput();
    elements.input.focus();
  });
});

restoreCredentials();
setBusy(false);
