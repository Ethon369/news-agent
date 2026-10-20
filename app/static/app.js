/* ==========================================================================
   AI Daily · 每日 AI 新闻助手 —— 前端逻辑
   原生 JavaScript，无框架 / 无构建 / 无外部依赖。
   接口契约：docs/API_CONTRACT.md（统一信封 { code, message, data }）。
   ========================================================================== */
(function () {
  'use strict';

  const API_BASE = '/api';
  const POLL_INTERVAL = 1200;
  const RESULT_PREVIEW_CHARS = 1200;
  const RESULT_AUTO_OPEN_CHARS = 220;
  const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
  const TIME_ONLY = /^([01]\d|2[0-3]):[0-5]\d$/;
  const CHANNEL_LABELS = { web: '站内', feishu: '飞书', email: '邮件' };

  /* ------------------------------------------------------------------ *
   * 0. 通用工具
   * ------------------------------------------------------------------ */

  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));

  const ESCAPE_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  /** 所有插入 innerHTML 的动态文本都必须先经过 esc()。 */
  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (char) => ESCAPE_MAP[char]);
  }

  const pad2 = (value) => String(value).padStart(2, '0');

  function formatNumber(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '0';
    return number.toLocaleString('zh-CN');
  }

  function formatDuration(ms) {
    const value = Number(ms);
    if (!Number.isFinite(value) || value <= 0) return '0 ms';
    if (value < 1000) return `${Math.round(value)} ms`;
    const seconds = value / 1000;
    if (seconds < 60) return `${seconds.toFixed(1)} s`;
    const minutes = Math.floor(seconds / 60);
    return `${minutes} 分 ${Math.round(seconds % 60)} 秒`;
  }

  function formatBytes(chars) {
    const value = Number(chars) || 0;
    if (value < 1024) return `${value} 字符`;
    return `${(value / 1024).toFixed(1)} KB`;
  }

  function formatDayText(value) {
    const text = String(value == null ? '' : value);
    if (DATE_ONLY.test(text)) {
      const parts = text.split('-');
      return `${parts[0]}年${parts[1]}月${parts[2]}日`;
    }
    const date = new Date(text);
    if (Number.isNaN(date.getTime())) return text || '—';
    return `${date.getFullYear()}年${pad2(date.getMonth() + 1)}月${pad2(date.getDate())}日`;
  }

  function formatBriefingDate(item) {
    if (!item) return '—';
    const source = item.briefing_date || item.created_at;
    const text = String(source == null ? '' : source);
    if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(0, 10);
    const date = new Date(text);
    if (Number.isNaN(date.getTime())) return text || '—';
    return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
  }

  function formatDateTime(value) {
    const text = String(value == null ? '' : value);
    if (!text) return '—';
    if (DATE_ONLY.test(text)) return formatDayText(text);
    const date = new Date(text);
    if (Number.isNaN(date.getTime())) return text;
    return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(
      date.getHours()
    )}:${pad2(date.getMinutes())}`;
  }

  function formatTime(date) {
    const value = date instanceof Date ? date : new Date();
    return `${pad2(value.getHours())}:${pad2(value.getMinutes())}:${pad2(value.getSeconds())}`;
  }

  function clampNumber(value, min, max, fallback) {
    const number = Number(value);
    if (!Number.isFinite(number)) return fallback;
    return Math.min(max, Math.max(min, Math.round(number)));
  }

  function uniqCaseInsensitive(list) {
    const seen = new Set();
    return list.filter((item) => {
      const key = String(item).trim().toLowerCase();
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function parseList(value) {
    return uniqCaseInsensitive(
      String(value == null ? '' : value)
        .split(/[,，、;\n]/)
        .map((part) => part.trim())
        .filter(Boolean)
    ).slice(0, 30);
  }

  function safeExternalUrl(raw) {
    const value = String(raw == null ? '' : raw).trim();
    if (!value) return '';
    try {
      const url = new URL(value, window.location.origin);
      if (url.protocol === 'http:' || url.protocol === 'https:') return url.href;
    } catch (error) {
      return '';
    }
    return '';
  }

  /* ------------------------------------------------------------------ *
   * 1. 内联图标（无 emoji、无图标字体）
   * ------------------------------------------------------------------ */

  const ICONS = {
    sparkles:
      '<path d="M12 3l1.9 4.8 4.8 1.9-4.8 1.9L12 16.4l-1.9-4.8L5.3 9.7l4.8-1.9L12 3z"/><path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z" fill="currentColor" stroke="none" opacity=".65"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    close: '<path d="M18 6L6 18M6 6l12 12"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/>',
    play: '<path d="M8 5.2c0-.8.9-1.3 1.6-.9l9.2 6.1c.6.4.6 1.3 0 1.7l-9.2 6.1c-.7.4-1.6-.1-1.6-.9V5.2z" fill="currentColor" stroke="none"/>',
    check: '<path d="M20 6L9 17l-5-5"/>',
    'check-circle':
      '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="M22 4L12 14.01l-3-3"/>',
    alert:
      '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    calendar:
      '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M8 2v4M16 2v4M3 10h18"/>',
    user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    layers:
      '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>',
    'file-text':
      '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8M16 17H8M10 9H8"/>',
    terminal: '<path d="M4 17l6-6-6-6"/><path d="M12 19h8"/>',
    message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    send: '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/>',
    external:
      '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14L21 3"/>',
    'chevron-left': '<path d="M15 18l-6-6 6-6"/>',
    inbox:
      '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    activity: '<path d="M3 12h4l3 8 4-16 3 8h4"/>',
    mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-8.97 5.7a2 2 0 0 1-2.06 0L2 7"/>'
  };

  function icon(name, size) {
    const paths = ICONS[name] || ICONS.info;
    const dimension = size || 16;
    return `<svg width="${dimension}" height="${dimension}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${paths}</svg>`;
  }

  /* ------------------------------------------------------------------ *
   * 2. API 层（所有网络请求集中于此）
   * ------------------------------------------------------------------ */

  class ApiError extends Error {
    constructor(message, code, status) {
      super(message || '请求失败');
      this.name = 'ApiError';
      this.code = Number.isFinite(code) ? code : -1;
      this.status = status || 0;
    }
  }

  const api = {
    async request(path, options) {
      const opts = options || {};
      const init = { method: opts.method || 'GET', headers: { Accept: 'application/json' } };
      if (opts.body !== undefined) {
        init.headers['Content-Type'] = 'application/json';
        init.body = JSON.stringify(opts.body);
      }
      let response;
      try {
        response = await fetch(API_BASE + path, init);
      } catch (error) {
        throw new ApiError('无法连接后端服务，请确认 API 已启动。', -1, 0);
      }
      let payload = null;
      try {
        payload = await response.json();
      } catch (error) {
        throw new ApiError('服务返回了无法解析的响应。', -1, response.status);
      }
      if (!response.ok || !payload || payload.code !== 0) {
        throw new ApiError(
          (payload && payload.message) || `请求失败（HTTP ${response.status}）`,
          payload ? payload.code : -1,
          response.status
        );
      }
      return payload.data;
    },

    meta() {
      return this.request('/meta');
    },
    users() {
      return this.request('/users');
    },
    user(id) {
      return this.request(`/users/${encodeURIComponent(id)}`);
    },
    createUser(payload) {
      return this.request('/users', { method: 'POST', body: payload });
    },
    updateSubscription(id, payload) {
      return this.request(`/users/${encodeURIComponent(id)}/subscription`, {
        method: 'PUT',
        body: payload
      });
    },
    briefings(userId, limit, offset) {
      const query = `?limit=${encodeURIComponent(limit || 20)}&offset=${encodeURIComponent(offset || 0)}`;
      return this.request(`/users/${encodeURIComponent(userId)}/briefings${query}`);
    },
    briefing(id) {
      return this.request(`/briefings/${encodeURIComponent(id)}`);
    },
    startRun(userId) {
      return this.request(`/users/${encodeURIComponent(userId)}/run`, { method: 'POST' });
    },
    run(id) {
      return this.request(`/runs/${encodeURIComponent(id)}`);
    }
  };

  /* ------------------------------------------------------------------ *
   * 3. 应用状态
   * ------------------------------------------------------------------ */

  function freshRunState() {
    return { id: null, data: null, timer: null, rendered: 0, startedAt: 0, polling: false };
  }

  const state = {
    meta: null,
    users: [],
    currentUserId: null,
    user: null,
    topics: [],
    briefings: [],
    activeBriefingId: null,
    briefingDetail: null,
    activeTab: 'briefings',
    profileLoading: true,
    profileError: null,
    briefingsLoading: false,
    briefingsError: null,
    busy: { create: false, save: false, refresh: false, run: false },
    run: freshRunState()
  };

  /* ------------------------------------------------------------------ *
   * 4. 通用 UI：Toast / 错误态 / 按钮 loading
   * ------------------------------------------------------------------ */

  function toast(type, title, description, code) {
    const region = $('#toast-region');
    if (!region) return;
    const variant = type === 'success' || type === 'error' || type === 'info' ? type : 'info';
    const iconName = variant === 'success' ? 'check-circle' : variant === 'error' ? 'alert' : 'info';
    const node = document.createElement('div');
    node.className = `toast toast-${variant}`;
    node.innerHTML = `
      <span class="toast-icon" aria-hidden="true">${icon(iconName, 14)}</span>
      <div class="toast-body">
        <p class="toast-title">${esc(title)}</p>
        ${description ? `<p class="toast-desc">${esc(description)}</p>` : ''}
        ${code && Number(code) !== 0 ? `<p class="toast-code">code ${esc(code)}</p>` : ''}
      </div>
      <button type="button" class="toast-close" aria-label="关闭提示">${icon('close', 13)}</button>`;
    const remove = () => {
      node.classList.add('is-leaving');
      window.setTimeout(() => node.remove(), 170);
    };
    const closeButton = node.querySelector('.toast-close');
    if (closeButton) closeButton.addEventListener('click', remove);
    region.appendChild(node);
    while (region.children.length > 4) region.firstElementChild.remove();
    window.setTimeout(remove, variant === 'error' ? 6500 : 3800);
  }

  function errorStateHTML(title, message, action, actionLabel) {
    return `<div class="empty">
      <span class="empty-icon danger" aria-hidden="true">${icon('alert', 20)}</span>
      <p class="empty-title">${esc(title)}</p>
      <p class="empty-desc">${esc(message || '请稍后重试。')}</p>
      ${
        action
          ? `<button type="button" class="btn btn-ghost btn-sm" data-action="${action}">${icon(
              'refresh',
              14
            )} ${esc(actionLabel || '重试')}</button>`
          : ''
      }
    </div>`;
  }

  function setButtonLoading(button, loading, label) {
    if (!button) return;
    if (loading) {
      if (!button.dataset.idleHtml) button.dataset.idleHtml = button.innerHTML;
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      button.innerHTML = `<span class="spinner" aria-hidden="true"></span><span>${esc(
        label || '处理中…'
      )}</span>`;
    } else {
      button.disabled = false;
      button.removeAttribute('aria-busy');
      if (button.dataset.idleHtml) {
        button.innerHTML = button.dataset.idleHtml;
        delete button.dataset.idleHtml;
      }
    }
  }

  function showFormError(node, message) {
    if (!node) return;
    node.textContent = message;
    node.hidden = false;
  }

  function hideFormError(node) {
    if (!node) return;
    node.textContent = '';
    node.hidden = true;
  }

  /* ------------------------------------------------------------------ *
   * 5. 安全 Markdown 渲染：先整体 HTML 转义，再解析为白名单标签
   * ------------------------------------------------------------------ */

  function sanitizeMarkdownUrl(raw) {
    // raw 已被 HTML 转义，这里只用于协议白名单判断
    const decoded = String(raw).replace(/&amp;/g, '&').replace(/&#39;/g, "'").replace(/&quot;/g, '"');
    try {
      const url = new URL(decoded, window.location.origin);
      if (url.protocol === 'http:' || url.protocol === 'https:') return url.href;
    } catch (error) {
      return '';
    }
    return '';
  }

  function inlineMarkdown(text) {
    let output = String(text);
    output = output.replace(/`([^`]+)`/g, '<code>$1</code>');
    output = output.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label, href) => {
      const safe = sanitizeMarkdownUrl(href);
      return safe
        ? `<a href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${label}</a>`
        : label;
    });
    output = output.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    output = output.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
    return output;
  }

  /**
   * 后端生成的 content_md 以 "# {简报标题}" 开头，而详情头部已经展示了标题；
   * 渲染正文时去掉首个 H1，避免视觉重复（只处理第一行标题，其余 Markdown 保留）。
   */
  function stripLeadingHeading(markdown) {
    const text = String(markdown == null ? '' : markdown);
    return text.replace(/^\s*#\s+[^\n]*(?:\n|$)/, '').replace(/^\s*\n/, '');
  }

  function renderMarkdown(markdown) {
    const source = String(markdown == null ? '' : markdown).replace(/\r\n?/g, '\n');
    const escaped = esc(source); // 步骤 1：整体转义，杜绝原始 HTML 注入
    const lines = escaped.split('\n');
    let html = '';
    let paragraph = [];
    let listType = null;

    const flushParagraph = () => {
      if (!paragraph.length) return;
      html += `<p>${inlineMarkdown(paragraph.join(' '))}</p>`;
      paragraph = [];
    };
    const closeList = () => {
      if (!listType) return;
      html += `</${listType}>`;
      listType = null;
    };
    const openList = (type) => {
      flushParagraph();
      if (listType === type) return;
      closeList();
      html += `<${type}>`;
      listType = type;
    };

    lines.forEach((line) => {
      const trimmed = line.trim();
      if (!trimmed) {
        flushParagraph();
        closeList();
        return;
      }
      let match = /^(#{1,6})\s+(.*)$/.exec(trimmed);
      if (match) {
        flushParagraph();
        closeList();
        const level = match[1].length <= 2 ? 5 : 6;
        html += `<h${level}>${inlineMarkdown(match[2])}</h${level}>`;
        return;
      }
      if (/^([-*_])\1{2,}$/.test(trimmed)) {
        flushParagraph();
        closeList();
        html += '<hr>';
        return;
      }
      match = /^>\s?(.*)$/.exec(trimmed);
      if (match) {
        flushParagraph();
        closeList();
        html += `<blockquote><p>${inlineMarkdown(match[1])}</p></blockquote>`;
        return;
      }
      match = /^[-*+]\s+(.*)$/.exec(trimmed);
      if (match) {
        openList('ul');
        html += `<li>${inlineMarkdown(match[1])}</li>`;
        return;
      }
      match = /^\d+[.)]\s+(.*)$/.exec(trimmed);
      if (match) {
        openList('ol');
        html += `<li>${inlineMarkdown(match[1])}</li>`;
        return;
      }
      closeList();
      paragraph.push(trimmed);
    });
    flushParagraph();
    closeList();
    return html;
  }

  /* ------------------------------------------------------------------ *
   * 6. 顶部栏：模型徽标 / 身份切换
   * ------------------------------------------------------------------ */

  function badgeHTML(label, extra) {
    return `<span class="badge-dot" aria-hidden="true"></span><span class="badge-label">${esc(
      label
    )}</span>${
      extra ? `<span class="badge-extra"> · ${esc(extra)}</span>` : ''
    }`;
  }

  function renderMeta() {
    const meta = state.meta || {};
    const badge = $('#llm-badge');
    if (!badge) return;
    const model = meta.model ? String(meta.model) : '';
    if (meta.llm_mode === 'real') {
      badge.className = 'badge badge-success';
      badge.innerHTML = badgeHTML('真实模型', model);
      badge.title = 'LLM_MODE=real：由真实模型驱动 Agent 循环';
    } else if (meta.llm_mode === 'mock') {
      badge.className = 'badge badge-warning';
      badge.innerHTML = badgeHTML('Mock 模式', model);
      badge.title = 'LLM_MODE=mock：离线脚本模型，零密钥可演示完整流程';
    } else {
      badge.className = 'badge badge-muted';
      badge.innerHTML = badgeHTML('模型模式未知', '');
      badge.title = 'GET /api/meta 未返回 llm_mode';
    }
    const version = $('#version-text');
    if (version && meta.version) version.textContent = `v${meta.version}`;
  }

  function renderMetaError(error) {
    const badge = $('#llm-badge');
    if (!badge) return;
    badge.className = 'badge badge-danger';
    badge.innerHTML = badgeHTML('模型信息不可用', '');
    badge.title = error ? error.message : '无法读取 /api/meta';
  }

  function renderUserSwitcher() {
    const wrap = $('#user-switcher');
    const select = $('#user-select');
    if (!wrap || !select) return;
    if (!state.users.length) {
      wrap.hidden = true;
      select.innerHTML = '';
      return;
    }
    wrap.hidden = false;
    select.innerHTML = state.users
      .map(
        (user) =>
          `<option value="${esc(user.id)}">${esc(user.name)} · #${esc(user.id)}</option>`
      )
      .join('');
    syncUserSelect();
  }

  function syncUserSelect() {
    const select = $('#user-select');
    if (!select || state.currentUserId == null) return;
    select.value = String(state.currentUserId);
  }

  /* ------------------------------------------------------------------ *
   * 7. 左栏：身份与订阅
   * ------------------------------------------------------------------ */

  function profileSkeletonHTML() {
    return `<div class="skeleton-stack" aria-hidden="true">
      <div class="skeleton skeleton-row">
        <div class="skeleton skeleton-avatar"></div>
        <div class="skeleton-lines">
          <div class="skeleton skeleton-line w-60"></div>
          <div class="skeleton skeleton-line w-40"></div>
        </div>
      </div>
      <div class="skeleton skeleton-line w-40"></div>
      <div class="skeleton skeleton-block"></div>
      <div class="skeleton skeleton-line w-60"></div>
      <div class="skeleton skeleton-block"></div>
      <div class="skeleton skeleton-line w-40"></div>
      <div class="skeleton skeleton-block"></div>
    </div>`;
  }

  function createPanelHTML() {
    return `<div class="create-intro">
        <span class="empty-icon" aria-hidden="true">${icon('user', 20)}</span>
        <div>
          <p class="create-title">创建你的第一个身份</p>
          <p class="create-desc">填好称呼即可开始；订阅偏好和历史简报都绑定在这个身份上。</p>
        </div>
      </div>
      <form id="inline-create-form" novalidate>
        <div class="field">
          <label for="inline-name">称呼 <span class="req">必填</span></label>
          <input id="inline-name" name="name" class="input" type="text" maxlength="40" autocomplete="name" placeholder="例如：张三" required>
        </div>
        <div class="field">
          <label for="inline-email">邮箱 <span class="optional">可选</span></label>
          <input id="inline-email" name="email" class="input" type="email" maxlength="120" autocomplete="email" placeholder="zhang@example.com" aria-describedby="inline-email-hint">
          <p id="inline-email-hint" class="hint">用于邮件推送；留空则只接收站内简报。</p>
        </div>
        <p class="form-error" id="inline-create-error" role="alert" hidden></p>
        <button type="submit" class="btn btn-primary btn-block" id="inline-create-submit">${icon(
          'plus',
          16
        )} 创建身份</button>
      </form>`;
  }

  function identityHTML(user) {
    const name = String(user.name || '未命名');
    const initial = name.trim().slice(0, 1).toUpperCase() || '?';
    return `<div class="identity">
      <div class="avatar" aria-hidden="true">${esc(initial)}</div>
      <div class="identity-main">
        <p class="identity-name">${esc(name)} <span class="identity-id">#${esc(user.id)}</span></p>
        <p class="identity-meta">
          ${icon('mail', 13)}
          <span>${esc(user.email || '未填写邮箱')}</span>
        </p>
        <p class="identity-meta">
          ${icon('clock', 13)}
          <span>创建于 ${esc(formatDateTime(user.created_at))}</span>
          <span class="dot-sep" aria-hidden="true">·</span>
          <span>${esc(user.timezone || 'Asia/Shanghai')}</span>
        </p>
      </div>
    </div>`;
  }

  function channelHintText() {
    if (!state.meta || !Array.isArray(state.meta.channels_available)) {
      return '未配置的渠道会记为跳过，不影响简报生成。';
    }
    const available = state.meta.channels_available;
    const missing = ['web', 'feishu', 'email']
      .filter((channel) => !available.includes(channel))
      .map((channel) => CHANNEL_LABELS[channel]);
    if (!missing.length) return '三个渠道均已配置。';
    return `${missing.join(' / ')}渠道未配置，推送会记为跳过。`;
  }

  function prefsFormHTML(user, subscription) {
    const sub = subscription || {};
    const channels = Array.isArray(sub.channels) ? sub.channels : ['web'];
    const maxItems = clampNumber(sub.max_items, 3, 10, 5);
    const pushTime = TIME_ONLY.test(String(sub.push_time || '')) ? sub.push_time : '08:00';
    const enabled = sub.enabled !== false;
    const available = state.meta && Array.isArray(state.meta.channels_available)
      ? state.meta.channels_available
      : null;
    const channelOptions = [
      ['web', '站内'],
      ['feishu', '飞书'],
      ['email', '邮件']
    ]
      .map(([value, label]) => {
        const unavailable = available ? !available.includes(value) : false;
        const title = unavailable ? `${label}渠道当前环境未配置，推送会记为跳过或失败` : '';
        return `<label class="channel-option${unavailable ? ' is-unavailable' : ''}"${
          title ? ` title="${esc(title)}"` : ''
        }>
          <input class="cb" type="checkbox" name="channels" value="${value}" ${
          channels.includes(value) ? 'checked' : ''
        }>
          <span class="channel-name">${label}</span>
        </label>`;
      })
      .join('');

    return `<form id="prefs-form" class="prefs-form" novalidate>
      <div class="field">
        <div class="field-head">
          <label id="topics-label" for="topic-entry">关注话题</label>
          <button type="button" class="link-btn" data-action="fill-suggestions">${icon(
            'sparkles',
            12
          )} 一键填入推荐</button>
        </div>
        <div class="chip-input" role="group" aria-labelledby="topics-label">
          <span class="chip-list" id="topic-chip-list"></span>
          <input id="topic-entry" class="chip-entry" type="text" placeholder="输入话题后回车添加" autocomplete="off" aria-label="添加关注话题">
        </div>
        <div class="suggestions" id="topic-suggestions" aria-label="推荐话题"></div>
      </div>

      <div class="field">
        <label for="prefs-keywords">关键词 <span class="optional">可选</span></label>
        <input id="prefs-keywords" class="input" type="text" placeholder="例如：DeepSeek, MCP, LangGraph" value="${esc(
          (Array.isArray(sub.keywords) ? sub.keywords : []).join(', ')
        )}" title="用逗号分隔；命中关键词的新闻排序更靠前">
      </div>

      <div class="field">
        <label for="prefs-exclude">排除关键词 <span class="optional">可选</span></label>
        <input id="prefs-exclude" class="input" type="text" placeholder="例如：招聘, 融资" value="${esc(
          (Array.isArray(sub.exclude_keywords) ? sub.exclude_keywords : []).join(', ')
        )}" title="命中即剔除，适合过滤招聘、融资等噪声">
      </div>

      <div class="grid-2">
        <div class="field">
          <label for="prefs-max-items">每日条数 <span class="label-note">3–10 条</span></label>
          <div class="range-row">
            <input type="range" id="prefs-max-items" min="3" max="10" step="1" value="${maxItems}" title="每日简报条数，3–10 条">
            <output id="prefs-max-output" for="prefs-max-items">${maxItems} 条</output>
          </div>
        </div>
        <div class="field">
          <label for="prefs-push-time">推送时间 <span class="label-note">${esc(
            user.timezone || 'Asia/Shanghai'
          )}</span></label>
          <input type="time" id="prefs-push-time" class="input" value="${esc(pushTime)}" title="每日推送时间，按 ${esc(
            user.timezone || 'Asia/Shanghai'
          )} 时区">
        </div>
      </div>

      <fieldset class="channels-field">
        <legend>推送渠道</legend>
        <div class="channel-grid">${channelOptions}</div>
        <p class="hint" id="prefs-channel-hint">${esc(channelHintText())}</p>
      </fieldset>

      <label class="switch-row">
        <input type="checkbox" id="prefs-enabled" class="sr-only" ${enabled ? 'checked' : ''}>
        <span class="switch" aria-hidden="true"></span>
        <span class="switch-copy">
          <span class="switch-title">启用每日推送</span>
          <span class="switch-desc">关闭后仍可手动生成简报</span>
        </span>
      </label>

      <p class="form-error" id="prefs-error" role="alert" hidden></p>
    </form>`;
  }

  function renderProfile() {
    const body = $('#profile-body');
    const badge = $('#profile-badge');
    const actions = $('#profile-actions');
    if (!body) return;
    if (badge) badge.hidden = true;
    if (actions) actions.hidden = true;

    if (state.profileLoading) {
      body.innerHTML = profileSkeletonHTML();
      return;
    }
    if (state.profileError) {
      body.innerHTML = errorStateHTML(
        '身份列表加载失败',
        state.profileError.message,
        'retry-users',
        '重新加载'
      );
      return;
    }
    if (!state.users.length) {
      body.innerHTML = createPanelHTML();
      bindProfileEvents();
      return;
    }
    if (!state.user) {
      body.innerHTML = profileSkeletonHTML();
      return;
    }

    const subscription = state.user.subscription || {};
    if (badge) {
      badge.hidden = false;
      badge.innerHTML = `<span class="badge badge-neutral"><span class="badge-dot" aria-hidden="true"></span>${esc(
        subscription.enabled === false ? '已暂停' : '订阅中'
      )}</span>`;
    }
    if (actions) actions.hidden = false;
    const note = $('#prefs-note');
    if (note) note.textContent = '保存后立即生效';
    body.innerHTML = identityHTML(state.user) + prefsFormHTML(state.user, subscription);
    renderTopicChips();
    renderSuggestions();
    bindProfileEvents();
  }

  function bindProfileEvents() {
    const form = $('#prefs-form');
    if (form) {
      form.addEventListener('submit', onSavePrefs);
      const range = $('#prefs-max-items');
      if (range) {
        range.addEventListener('input', () => {
          const output = $('#prefs-max-output');
          if (output) output.textContent = `${range.value} 条`;
        });
      }
      const entry = $('#topic-entry');
      if (entry) entry.addEventListener('keydown', onTopicEntryKeydown);
    }
    const inlineForm = $('#inline-create-form');
    if (inlineForm) {
      inlineForm.addEventListener('submit', (event) => onCreateUser(event, 'inline'));
      const nameInput = $('#inline-name');
      if (nameInput) nameInput.addEventListener('input', () => nameInput.removeAttribute('aria-invalid'));
    }
  }

  function renderTopicChips() {
    const list = $('#topic-chip-list');
    if (!list) return;
    if (!state.topics.length) {
      list.innerHTML = '<span class="chip-empty">还没有添加话题</span>';
      return;
    }
    list.innerHTML = state.topics
      .map(
        (topic) => `<span class="chip">${esc(topic)}<button type="button" class="chip-x" data-action="remove-topic" data-topic="${esc(
          topic
        )}" aria-label="移除话题 ${esc(topic)}">${icon('close', 12)}</button></span>`
      )
      .join('');
  }

  function renderSuggestions() {
    const box = $('#topic-suggestions');
    if (!box) return;
    const suggestions =
      state.meta && Array.isArray(state.meta.topic_suggestions) ? state.meta.topic_suggestions : [];
    const available = suggestions.filter(
      (topic) => !state.topics.some((item) => item.toLowerCase() === String(topic).toLowerCase())
    );
    if (!available.length) {
      box.innerHTML = '';
      return;
    }
    box.innerHTML = available
      .map(
        (topic) =>
          `<button type="button" class="sugg-chip" data-action="toggle-topic" data-topic="${esc(
            topic
          )}" aria-pressed="false">${icon('plus', 11)}${esc(topic)}</button>`
      )
      .join('');
  }

  function addTopics(values) {
    const candidates = Array.isArray(values) ? values : parseList(values);
    let added = false;
    candidates.forEach((raw) => {
      const value = String(raw).trim();
      if (!value || state.topics.length >= 20) return;
      const exists = state.topics.some((topic) => topic.toLowerCase() === value.toLowerCase());
      if (exists) return;
      state.topics.push(value);
      added = true;
    });
    if (added) {
      renderTopicChips();
      renderSuggestions();
    }
    return added;
  }

  function removeTopic(topic) {
    const index = state.topics.findIndex((item) => item === topic);
    if (index >= 0) state.topics.splice(index, 1);
    renderTopicChips();
    renderSuggestions();
    const entry = $('#topic-entry');
    if (entry) entry.focus();
  }

  function toggleTopic(topic) {
    const index = state.topics.findIndex(
      (item) => item.toLowerCase() === String(topic).toLowerCase()
    );
    if (index >= 0) state.topics.splice(index, 1);
    else if (state.topics.length < 20) state.topics.push(topic);
    renderTopicChips();
    renderSuggestions();
    const entry = $('#topic-entry');
    if (entry) entry.focus();
  }

  function fillSuggestions() {
    const suggestions =
      state.meta && Array.isArray(state.meta.topic_suggestions) ? state.meta.topic_suggestions : [];
    if (!suggestions.length) {
      toast('info', '暂无推荐话题', '服务端没有返回 topic_suggestions。');
      return;
    }
    const added = addTopics(suggestions);
    toast(
      added ? 'success' : 'info',
      added ? '已填入推荐话题' : '推荐话题已全部添加',
      `当前关注 ${state.topics.length} 个话题。`
    );
  }

  function onTopicEntryKeydown(event) {
    const entry = event.currentTarget;
    if (event.key === 'Enter' || event.key === ',' || event.key === '，') {
      event.preventDefault();
      const value = entry.value;
      if (!value.trim()) return;
      addTopics(parseList(value));
      entry.value = '';
    } else if (event.key === 'Backspace' && !entry.value && state.topics.length) {
      state.topics.pop();
      renderTopicChips();
      renderSuggestions();
    }
  }

  function validateCreate(nameInput, emailInput, errorNode) {
    nameInput.removeAttribute('aria-invalid');
    emailInput.removeAttribute('aria-invalid');
    const name = nameInput.value.trim();
    const email = emailInput.value.trim();
    if (!name) {
      nameInput.setAttribute('aria-invalid', 'true');
      nameInput.focus();
      showFormError(errorNode, '请填写称呼。');
      return null;
    }
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) {
      emailInput.setAttribute('aria-invalid', 'true');
      emailInput.focus();
      showFormError(errorNode, '邮箱格式看起来不对，请检查后再试。');
      return null;
    }
    return { name, email };
  }

  async function onCreateUser(event, source) {
    if (event) event.preventDefault();
    if (state.busy.create) return;
    const prefix = source === 'dialog' ? 'dialog' : 'inline';
    const nameInput = $(`#${prefix}-name`);
    const emailInput = $(`#${prefix}-email`);
    const errorNode = $(`#${prefix}-create-error`);
    const submit = $(`#${prefix}-create-submit`);
    if (!nameInput || !emailInput) return;

    const values = validateCreate(nameInput, emailInput, errorNode);
    if (!values) return;

    state.busy.create = true;
    setButtonLoading(submit, true, '创建中…');
    try {
      const payload = { name: values.name };
      if (values.email) payload.email = values.email;
      const created = await api.createUser(payload);
      state.users = [created].concat(
        state.users.filter((user) => String(user.id) !== String(created.id))
      );
      state.profileLoading = false;
      state.profileError = null;
      renderUserSwitcher();
      if (source === 'dialog') closeCreateDialog();
      toast('success', '身份已创建', `现在是「${created.name}」的简报空间。`);
      await selectUser(created.id);
    } catch (error) {
      const message = error && error.message ? error.message : '创建身份失败。';
      showFormError(errorNode, message);
      toast('error', '创建身份失败', message, error && error.code);
    } finally {
      state.busy.create = false;
      setButtonLoading(submit, false);
    }
  }

  async function onSavePrefs(event) {
    event.preventDefault();
    if (!state.user || state.busy.save) return;
    const form = event.currentTarget;
    const errorNode = $('#prefs-error');
    const maxItems = clampNumber($('#prefs-max-items') ? $('#prefs-max-items').value : 5, 3, 10, 5);
    const pushTime = String($('#prefs-push-time') ? $('#prefs-push-time').value : '').trim();
    const channels = $$('input[name="channels"]:checked', form).map((input) => input.value);

    if (!TIME_ONLY.test(pushTime)) {
      showFormError(errorNode, '推送时间格式应为 HH:MM。');
      toast('error', '保存失败', '推送时间格式应为 HH:MM。');
      return;
    }
    if (!channels.length) {
      showFormError(errorNode, '请至少选择一个推送渠道。');
      toast('error', '保存失败', '请至少选择一个推送渠道。');
      return;
    }

    const payload = {
      topics: state.topics.slice(),
      keywords: parseList($('#prefs-keywords') ? $('#prefs-keywords').value : ''),
      exclude_keywords: parseList($('#prefs-exclude') ? $('#prefs-exclude').value : ''),
      max_items: maxItems,
      channels,
      push_time: pushTime,
      enabled: $('#prefs-enabled') ? $('#prefs-enabled').checked : true
    };

    hideFormError(errorNode);
    state.busy.save = true;
    const button = $('#save-prefs');
    setButtonLoading(button, true, '保存中…');
    try {
      const updated = await api.updateSubscription(state.user.id, payload);
      state.user.subscription = updated || payload;
      const index = state.users.findIndex((user) => String(user.id) === String(state.user.id));
      if (index >= 0) state.users[index] = state.user;
      const note = $('#prefs-note');
      if (note) note.textContent = `已保存 · ${formatTime(new Date())}`;
      renderProfileBadge();
      toast('success', '偏好已保存', 'Agent 下次运行时会按新的偏好检索新闻。');
    } catch (error) {
      const message = error && error.message ? error.message : '保存偏好失败。';
      showFormError(errorNode, message);
      toast('error', '保存失败', message, error && error.code);
    } finally {
      state.busy.save = false;
      setButtonLoading(button, false);
    }
  }

  function renderProfileBadge() {
    const badge = $('#profile-badge');
    if (!badge || !state.user) return;
    const subscription = state.user.subscription || {};
    badge.hidden = false;
    badge.innerHTML = `<span class="badge badge-neutral"><span class="badge-dot" aria-hidden="true"></span>${esc(
      subscription.enabled === false ? '已暂停' : '订阅中'
    )}</span>`;
  }

  /* ------------------------------------------------------------------ *
   * 8. 新建身份对话框
   * ------------------------------------------------------------------ */

  function openCreateDialog() {
    const dialog = $('#new-user-dialog');
    const form = $('#dialog-create-form');
    if (!dialog) return;
    if (form) form.reset();
    const errorNode = $('#dialog-create-error');
    hideFormError(errorNode);
    ['dialog-name', 'dialog-email'].forEach((id) => {
      const input = $(`#${id}`);
      if (input) input.removeAttribute('aria-invalid');
    });
    if (typeof dialog.showModal === 'function') {
      if (!dialog.open) dialog.showModal();
    } else {
      dialog.setAttribute('open', '');
    }
    const nameInput = $('#dialog-name');
    if (nameInput) window.setTimeout(() => nameInput.focus(), 30);
  }

  function closeCreateDialog() {
    const dialog = $('#new-user-dialog');
    if (dialog && dialog.open && typeof dialog.close === 'function') dialog.close();
  }

  function onNewUserButton() {
    if (!state.users.length) {
      const input = $('#inline-name');
      if (input) {
        input.focus();
        input.scrollIntoView({ block: 'center', behavior: 'smooth' });
      } else {
        openCreateDialog();
      }
      return;
    }
    openCreateDialog();
  }

  /* ------------------------------------------------------------------ *
   * 9. 右栏：历史简报
   * ------------------------------------------------------------------ */

  function briefingsSkeletonHTML(count) {
    return `<div class="skeleton-stack" aria-hidden="true">${Array.from(
      { length: count || 3 },
      () => '<div class="skeleton skeleton-item"></div>'
    ).join('')}</div>`;
  }

  function detailSkeletonHTML() {
    return `<div class="detail-loading" aria-hidden="true">
      <div class="skeleton skeleton-line w-40"></div>
      <div class="skeleton skeleton-title"></div>
      <div class="skeleton skeleton-line w-60"></div>
      <div class="skeleton detail-hero"></div>
      <div class="skeleton skeleton-line"></div>
      <div class="skeleton skeleton-line"></div>
      <div class="skeleton skeleton-line w-60"></div>
    </div>`;
  }

  function detailPlaceholderHTML() {
    return `<div class="empty empty-lg">
      <span class="empty-icon" aria-hidden="true">${icon('file-text', 20)}</span>
      <p class="empty-title">选择一份简报</p>
      <p class="empty-desc">左侧列出了这个身份的历史简报；点击任意一份查看正文、入选新闻与推送记录。</p>
      <button class="btn btn-ghost btn-sm" type="button" data-action="open-run-tab">去运行一次 Agent</button>
    </div>`;
  }

  function updateBriefingsCount() {
    const node = $('#briefings-count');
    if (!node) return;
    if (state.profileLoading || state.briefingsLoading) {
      node.textContent = '…';
      return;
    }
    if (state.briefingsError || state.profileError) {
      node.textContent = '!';
      return;
    }
    if (!state.users.length) {
      node.textContent = '0';
      return;
    }
    node.textContent = String(state.briefings.length || 0);
  }

  function renderBriefings() {
    const list = $('#briefing-list');
    const hint = $('#briefings-hint');
    if (!list) return;
    updateBriefingsCount();

    if (state.profileLoading || state.briefingsLoading) {
      list.innerHTML = briefingsSkeletonHTML(3);
      if (hint) hint.textContent = '加载中…';
      return;
    }
    if (state.profileError) {
      list.innerHTML = errorStateHTML('身份加载失败', state.profileError.message, 'retry-users');
      if (hint) hint.textContent = '';
      return;
    }
    if (state.briefingsError) {
      list.innerHTML = errorStateHTML(
        '简报列表加载失败',
        state.briefingsError.message,
        'retry-briefings'
      );
      if (hint) hint.textContent = '';
      return;
    }
    if (!state.users.length) {
      list.innerHTML = `<div class="empty">
        <span class="empty-icon" aria-hidden="true">${icon('user', 20)}</span>
        <p class="empty-title">还没有身份</p>
        <p class="empty-desc">先创建一个身份，才能生成并保存每日简报。</p>
        <button class="btn btn-ghost btn-sm" type="button" data-action="new-user">${icon(
          'plus',
          14
        )} 新建身份</button>
      </div>`;
      if (hint) hint.textContent = '';
      return;
    }
    if (!state.briefings.length) {
      list.innerHTML = `<div class="empty">
        <span class="empty-icon" aria-hidden="true">${icon('inbox', 20)}</span>
        <p class="empty-title">还没有历史简报</p>
        <p class="empty-desc">运行一次 Agent，生成的第一份简报会出现在这里。</p>
        <button class="btn btn-ghost btn-sm" type="button" data-action="start-run">${icon(
          'play',
          14
        )} 立即生成简报</button>
      </div>`;
      if (hint) hint.textContent = '';
      return;
    }
    if (hint) hint.textContent = `共 ${state.briefings.length} 份`;
    list.innerHTML = state.briefings
      .map((item) => {
        const active =
          state.activeBriefingId != null &&
          String(item.id) === String(state.activeBriefingId);
        return `<button type="button" class="briefing-item" data-action="open-briefing" data-id="${esc(
          item.id
        )}" ${active ? 'aria-current="true"' : ''}>
          <span class="bi-top">
            <span class="bi-date">${esc(formatBriefingDate(item))}</span>
            <span class="bi-count">${esc(item.item_count != null ? item.item_count : 0)} 条</span>
          </span>
          <span class="bi-title">${esc(item.title || '未命名简报')}</span>
          <span class="bi-summary">${esc(item.summary || '')}</span>
        </button>`;
      })
      .join('');
  }

  function renderDetailLoading() {
    const container = $('#briefing-detail');
    if (container) container.innerHTML = detailSkeletonHTML();
  }

  function renderBriefingDetail(options) {
    const opts = options || {};
    const container = $('#briefing-detail');
    if (!container) return;
    if (opts.loading) {
      renderDetailLoading();
      return;
    }
    if (opts.error) {
      container.innerHTML = errorStateHTML(
        '简报详情加载失败',
        opts.error.message,
        'retry-briefing',
        '重新加载'
      );
      return;
    }
    const detail = state.briefingDetail;
    if (
      !detail ||
      state.activeBriefingId == null ||
      String(detail.id) !== String(state.activeBriefingId)
    ) {
      container.innerHTML = detailPlaceholderHTML();
      return;
    }
    container.innerHTML = detailHTML(detail);
  }

  function deliveryHTML(delivery) {
    const statusMap = {
      success: { label: '已推送', cls: 'delivery-success' },
      skipped: { label: '已跳过', cls: 'delivery-skipped' },
      failed: { label: '推送失败', cls: 'delivery-failed' }
    };
    const status = statusMap[delivery.status] || {
      label: String(delivery.status || '未知状态'),
      cls: 'delivery-skipped'
    };
    const channel = CHANNEL_LABELS[delivery.channel] || String(delivery.channel || '未知渠道');
    return `<span class="delivery ${status.cls}" title="${esc(delivery.detail || '')}">
      <span class="delivery-dot" aria-hidden="true"></span>
      <span>${esc(channel)} · ${esc(status.label)}</span>
      ${delivery.detail ? `<span class="delivery-detail">${esc(delivery.detail)}</span>` : ''}
    </span>`;
  }

  function itemHTML(item) {
    const tags = Array.isArray(item.tags) ? item.tags : [];
    const url = safeExternalUrl(item.url);
    const titleText = esc(item.title || '无标题');
    const title = url
      ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${titleText}${icon(
          'external',
          12
        )}</a>`
      : titleText;
    const scoreValue = Number(item.score);
    const score =
      item.score != null && item.score !== '' && Number.isFinite(scoreValue)
        ? `<span class="item-score" title="相关度得分">${esc(scoreValue.toFixed(2))}</span>`
        : '';
    const metaBits = [];
    if (item.source) metaBits.push(`<span>${esc(item.source)}</span>`);
    if (item.source && item.published_at) {
      metaBits.push('<span class="dot-sep" aria-hidden="true">·</span>');
    }
    if (item.published_at) metaBits.push(`<span>${esc(formatDateTime(item.published_at))}</span>`);
    return `<li class="item-card">
      <span class="item-rank" aria-hidden="true">${esc(item.rank != null ? item.rank : '·')}</span>
      <div class="item-body">
        <div class="item-head">
          <h5 class="item-title">${title}</h5>
          ${score}
        </div>
        ${metaBits.length ? `<p class="item-meta">${metaBits.join('')}</p>` : ''}
        ${item.summary ? `<p class="item-summary">${esc(item.summary)}</p>` : ''}
        ${
          item.evidence_level
            ? `<p class="item-evidence"><span class="item-evidence-label">证据范围</span><span>${esc(
                item.evidence_level
              )}</span></p>`
            : ''
        }
        ${
          item.reason
            ? `<p class="item-reason"><span class="item-reason-label">入选理由</span><span>${esc(
                item.reason
              )}</span></p>`
            : ''
        }
        ${
          tags.length
            ? `<div class="item-tags">${tags
                .map((tag) => `<span class="tag">${esc(tag)}</span>`)
                .join('')}</div>`
            : ''
        }
      </div>
    </li>`;
  }

  function detailHTML(detail) {
    const items = Array.isArray(detail.items) ? detail.items : [];
    const deliveries = Array.isArray(detail.deliveries) ? detail.deliveries : [];
    const itemCount = detail.item_count != null ? detail.item_count : items.length;
    const content = stripLeadingHeading(detail.content_md);
    return `<div class="detail-topbar">
        <button class="btn btn-ghost btn-sm detail-back" type="button" data-action="back-to-list">${icon(
          'chevron-left',
          15
        )} 返回列表</button>
      </div>
      <header class="detail-head">
        <p class="detail-eyebrow">${icon('sparkles', 12)} 简报详情</p>
        <h3 class="detail-title" tabindex="-1">${esc(detail.title || '未命名简报')}</h3>
        ${detail.summary ? `<p class="detail-summary">${esc(detail.summary)}</p>` : ''}
        <div class="detail-meta">
          <span>${icon('calendar', 13)} ${esc(formatDayText(detail.briefing_date))}</span>
          <span>${icon('layers', 13)} ${esc(itemCount)} 条新闻</span>
          <span>${icon('clock', 13)} ${esc(formatDateTime(detail.created_at))}</span>
        </div>
        ${
          deliveries.length
            ? `<div class="deliveries" aria-label="推送记录">${deliveries
                .map(deliveryHTML)
                .join('')}</div>`
            : ''
        }
      </header>
      ${
        content
          ? `<section class="detail-section">
              <h4 class="section-title">简报正文</h4>
              <div class="markdown">${renderMarkdown(content)}</div>
            </section>`
          : ''
      }
      <section class="detail-section">
        <h4 class="section-title">入选新闻 <span class="section-count">${esc(items.length)}</span></h4>
        ${
          items.length
            ? `<ol class="item-list">${items.map(itemHTML).join('')}</ol>`
            : `<p class="hint">这份简报没有结构化条目。</p>`
        }
      </section>`;
  }

  function openDetailView(isOpen) {
    const layout = $('#panel-briefings');
    if (!layout) return;
    const wasOpen = layout.classList.contains('is-detail-open');
    layout.classList.toggle('is-detail-open', Boolean(isOpen));
    if (
      isOpen &&
      !wasOpen &&
      window.matchMedia('(max-width: 767px)').matches
    ) {
      const panel = $('.work-panel');
      if (panel) panel.scrollIntoView({ block: 'start' });
    }
  }

  function focusActiveBriefing() {
    const active = $('.briefing-item[aria-current="true"]');
    if (active) {
      active.focus();
      return;
    }
    const refresh = $('#refresh-briefings');
    if (refresh) refresh.focus();
  }

  function focusDetailHeading() {
    if (!window.matchMedia('(max-width: 767px)').matches) return;
    const heading = $('.detail-title');
    if (heading) {
      if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
      heading.focus({ preventScroll: true });
    }
  }

  async function openBriefing(id) {
    const briefingId = Number(id);
    if (!Number.isFinite(briefingId)) return;
    const isMobile = window.matchMedia('(max-width: 767px)').matches;
    const activeWasFocused =
      document.activeElement &&
      document.activeElement.classList &&
      document.activeElement.classList.contains('briefing-item');
    state.activeBriefingId = briefingId;
    renderBriefings();
    openDetailView(true);
    renderBriefingDetail({ loading: true });
    try {
      const detail = await api.briefing(briefingId);
      if (String(state.activeBriefingId) !== String(briefingId)) return;
      state.briefingDetail = detail;
      renderBriefingDetail();
      if (isMobile) {
        focusDetailHeading();
      } else if (activeWasFocused) {
        const active = $('.briefing-item[aria-current="true"]');
        if (active) active.focus({ preventScroll: true });
      }
    } catch (error) {
      if (String(state.activeBriefingId) !== String(briefingId)) return;
      state.briefingDetail = null;
      renderBriefingDetail({ error });
      toast('error', '简报详情加载失败', error.message, error.code);
    }
  }

  /**
   * 加载历史简报。
   * options.openId      加载后打开指定简报（运行成功后调用）
   * options.autoOpen    首屏 / 切换身份时自动打开第一份（仅桌面端）
   * options.keepActive  刷新时保持当前打开的简报
   */
  async function loadBriefings(options) {
    const opts = options || {};
    if (state.currentUserId == null) {
      state.briefingsLoading = false;
      renderBriefings();
      return false;
    }
    const requestUserId = state.currentUserId;
    state.briefingsLoading = true;
    state.briefingsError = null;
    renderBriefings();
    try {
      const list = await api.briefings(requestUserId, 20, 0);
      if (state.currentUserId !== requestUserId) return false; // 身份已切换，丢弃过期响应
      state.briefings = Array.isArray(list) ? list : [];
      state.briefingsLoading = false;
      const ids = state.briefings.map((item) => String(item.id));
      if (
        state.activeBriefingId != null &&
        !ids.includes(String(state.activeBriefingId))
      ) {
        state.activeBriefingId = null;
        state.briefingDetail = null;
      }
      renderBriefings();

      if (opts.openId != null) {
        setTab('briefings');
        await openBriefing(opts.openId);
        return true;
      }
      if (opts.keepActive && state.activeBriefingId != null) {
        await openBriefing(state.activeBriefingId);
        return true;
      }
      if (opts.autoOpen && window.matchMedia('(min-width: 768px)').matches) {
        if (state.briefings.length) {
          await openBriefing(state.briefings[0].id);
          return true;
        }
      }
      renderBriefingDetail();
      return true;
    } catch (error) {
      state.briefingsLoading = false;
      state.briefingsError = error;
      renderBriefings();
      renderBriefingDetail();
      if (!opts.silent) toast('error', '简报列表加载失败', error.message, error.code);
      return false;
    }
  }

  async function onRefreshBriefings() {
    if (state.currentUserId == null) {
      toast('info', '还没有身份', '先在左侧创建一个身份。');
      return;
    }
    if (state.busy.refresh) return;
    state.busy.refresh = true;
    const button = $('#refresh-briefings');
    const svg = button ? button.querySelector('svg') : null;
    if (button) {
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
    }
    if (svg) svg.classList.add('is-spinning');
    try {
      const ok = await loadBriefings({ keepActive: true });
      if (ok) {
        toast('success', '已刷新', `历史简报共 ${state.briefings.length} 份。`);
      }
    } finally {
      state.busy.refresh = false;
      if (button) {
        button.disabled = false;
        button.removeAttribute('aria-busy');
      }
      if (svg) svg.classList.remove('is-spinning');
    }
  }

  /* ------------------------------------------------------------------ *
   * 10. 右栏：运行轨迹
   * ------------------------------------------------------------------ */

  function isRunActive() {
    const data = state.run.data;
    return Boolean(data) && (data.status === 'running' || data.status === 'queued');
  }

  function updateRunButton() {
    const button = $('#run-btn');
    const label = $('#run-btn-text');
    const iconSlot = button ? button.querySelector('.btn-icon-slot') : null;
    if (!button || !label) return;
    const active = isRunActive();
    const busy = state.busy.run || active;
    button.disabled = busy;
    button.setAttribute('aria-busy', active ? 'true' : 'false');
    if (busy) {
      if (active) {
        label.textContent =
          state.run.data && state.run.data.status === 'queued' ? '运行排队中…' : '生成中…';
      } else {
        label.textContent = '提交中…';
      }
      if (iconSlot) iconSlot.innerHTML = '<span class="spinner" aria-hidden="true"></span>';
    } else {
      label.textContent = '立即生成简报';
      if (iconSlot) iconSlot.innerHTML = icon('play', 17);
    }
  }

  function renderRunStatus(data) {
    const node = $('#run-status');
    if (!node) return;
    const status = data ? String(data.status || 'running') : 'idle';
    if (node.dataset.status === status) return;
    node.dataset.status = status;
    if (!data) {
      node.innerHTML = '<span class="badge badge-neutral"><span class="badge-dot" aria-hidden="true"></span>待运行</span>';
      return;
    }
    const map = {
      queued: { label: '排队中', cls: 'badge-neutral' },
      running: { label: '运行中', cls: 'badge-running' },
      success: { label: '已完成', cls: 'badge-success' },
      failed: { label: '运行失败', cls: 'badge-danger' }
    };
    const conf = map[status] || { label: status, cls: 'badge-neutral' };
    node.innerHTML = `<span class="badge ${conf.cls}"><span class="badge-dot" aria-hidden="true"></span>${esc(
      conf.label
    )}</span>`;
  }

  function renderRunMeta(data) {
    const node = $('#run-meta');
    if (!node) return;
    if (!data) {
      node.hidden = true;
      node.textContent = '';
      return;
    }
    const bits = [];
    if (data.id != null) bits.push(`运行 #${data.id}`);
    if (data.llm_mode) bits.push(String(data.llm_mode));
    if (data.model) bits.push(String(data.model));
    if (data.trigger) {
      bits.push(data.trigger === 'schedule' ? '定时触发' : data.trigger === 'manual' ? '手动触发' : String(data.trigger));
    }
    node.hidden = !bits.length;
    node.textContent = bits.join(' · ');
  }

  function computeElapsed(data) {
    if (!data) return '—';
    const started = data.started_at ? Date.parse(data.started_at) : state.run.startedAt;
    if (!Number.isFinite(started)) return '—';
    let finished = data.finished_at ? Date.parse(data.finished_at) : 0;
    if (!Number.isFinite(finished) || !finished) {
      if (!isRunActive()) return '—';
      finished = Date.now();
    }
    return formatDuration(Math.max(0, finished - started));
  }

  function renderRunStats(data) {
    const box = $('#run-stats');
    if (!box) return;
    if (!data) {
      box.hidden = true;
      box.innerHTML = '';
      return;
    }
    const steps = Number(data.step_count) || state.run.rendered;
    const tools = Number(data.tool_call_count) || 0;
    const promptTokens = Number(data.prompt_tokens) || 0;
    const completionTokens = Number(data.completion_tokens) || 0;
    const stats = [
      ['步骤', formatNumber(steps)],
      ['工具调用', formatNumber(tools)],
      ['输入 Tokens', formatNumber(promptTokens)],
      ['输出 Tokens', formatNumber(completionTokens)],
      ['耗时', computeElapsed(data)]
    ];
    box.hidden = false;
    box.innerHTML = stats
      .map(
        ([label, value]) =>
          `<div class="stat"><span class="stat-label">${esc(label)}</span><span class="stat-value">${esc(
            value
          )}</span></div>`
      )
      .join('');
  }

  function renderRunAlert(error, mode) {
    const box = $('#run-alert');
    if (!box) return;
    if (!error) {
      box.hidden = true;
      box.innerHTML = '';
      return;
    }
    const message = typeof error === 'string' ? error : (error && error.message) || '未知错误';
    const code = typeof error === 'object' && error && error.code ? `（code ${error.code}）` : '';
    const isPollError = mode === 'poll';
    box.hidden = false;
    box.innerHTML = `<div class="callout callout-danger" role="alert">
      <span class="callout-icon" aria-hidden="true">${icon('alert', 15)}</span>
      <div class="callout-body">
        <p class="callout-title">${isPollError ? '运行状态拉取失败' : '运行未完成'}</p>
        <p class="callout-desc">${esc(message)}${esc(code)}</p>
        <div class="callout-actions">
          <button type="button" class="btn btn-ghost btn-sm" data-action="${isPollError ? 'resume-run' : 'retry-run'}">${icon(
            'refresh',
            14
          )} ${isPollError ? '重新连接' : '重试'}</button>
        </div>
      </div>
    </div>`;
  }

  function stepMeta(step) {
    const tool = String(step.tool_name || '');
    if (tool === 'publish_briefing') {
      return { label: '发布简报', icon: 'send', variant: 'final' };
    }
    if (tool) return { label: '工具调用', icon: 'terminal', variant: 'tool' };
    const kind = String(step.kind || '');
    const map = {
      assistant_message: { label: '模型思考', icon: 'message', variant: 'assistant' },
      final_answer: { label: '最终回答', icon: 'check-circle', variant: 'final' },
      final: { label: '最终回答', icon: 'check-circle', variant: 'final' },
      error: { label: '错误', icon: 'alert', variant: 'error' },
      system: { label: '系统消息', icon: 'info', variant: 'assistant' }
    };
    return map[kind] || { label: kind || '步骤', icon: 'file-text', variant: 'assistant' };
  }

  function prettyToolArgs(raw) {
    const text = String(raw == null ? '' : raw);
    if (!text.trim()) return '';
    try {
      return JSON.stringify(JSON.parse(text), null, 2);
    } catch (error) {
      return text;
    }
  }

  function renderToolResult(result) {
    const full = String(result);
    const truncated = full.length > RESULT_PREVIEW_CHARS;
    const shown = truncated
      ? `${full.slice(0, RESULT_PREVIEW_CHARS)}\n… 已截断（共 ${full.length} 字符）`
      : full;
    const open = full.length <= RESULT_AUTO_OPEN_CHARS ? ' open' : '';
    return `<details class="step-result"${open}>
      <summary>${icon('terminal', 13)}<span>工具结果</span><span class="tl-result-size">${esc(
        formatBytes(full.length)
      )}</span></summary>
      <pre class="code-block" tabindex="0" aria-label="工具结果">${esc(shown)}</pre>
    </details>`;
  }

  function stepHTML(step) {
    const meta = stepMeta(step);
    const thought = String(step.thought || '');
    const args = prettyToolArgs(step.tool_args);
    const result = String(step.tool_result || '');
    const duration = Number(step.duration_ms);
    const durationText = Number.isFinite(duration) && duration > 0 ? formatDuration(duration) : '';
    const stepIndex = step.step_index != null ? step.step_index : '—';
    return `<li class="tl-item tl-${meta.variant}">
      <span class="tl-marker" aria-hidden="true">${icon(meta.icon, 15)}</span>
      <div class="tl-card">
        <div class="tl-row">
          <span class="tl-index">#${esc(stepIndex)}</span>
          <span class="tl-kind">${esc(meta.label)}</span>
          ${step.tool_name ? `<code class="tl-tool">${esc(step.tool_name)}</code>` : ''}
          ${
            durationText
              ? `<span class="tl-dur" title="耗时 ${esc(duration)} ms">${esc(durationText)}</span>`
              : ''
          }
        </div>
        ${thought ? `<p class="tl-thought">${esc(thought)}</p>` : ''}
        ${
          args
            ? `<div class="tl-block"><div class="tl-block-label">工具参数</div><pre class="code-block" tabindex="0" aria-label="工具参数">${esc(
                args
              )}</pre></div>`
            : ''
        }
        ${result ? renderToolResult(result) : ''}
      </div>
    </li>`;
  }

  function appendRunSteps(steps) {
    const list = $('#run-steps');
    if (!list) return;
    const sorted = steps
      .slice()
      .sort((a, b) => Number(a.step_index || 0) - Number(b.step_index || 0));
    if (sorted.length < state.run.rendered) {
      list.innerHTML = '';
      state.run.rendered = 0;
    }
    const fresh = sorted.slice(state.run.rendered);
    if (!fresh.length) return;
    list.insertAdjacentHTML('beforeend', fresh.map(stepHTML).join(''));
    const items = list.querySelectorAll('.tl-item');
    const startIndex = Math.max(0, items.length - fresh.length);
    for (let i = startIndex; i < items.length; i += 1) items[i].classList.add('tl-new');
    state.run.rendered = sorted.length;
    const empty = $('#run-empty');
    if (empty) empty.hidden = true;
  }

  function renderRunPanel() {
    renderRunStatus(state.run.data);
    renderRunMeta(state.run.data);
    renderRunStats(state.run.data);
    renderRunAlert(null);
    const steps = $('#run-steps');
    if (steps) steps.innerHTML = '';
    const empty = $('#run-empty');
    if (empty) empty.hidden = false;
    const dot = $('#run-dot');
    if (dot) dot.hidden = true;
    updateRunButton();
  }

  function stopRunPolling() {
    if (state.run.timer) {
      window.clearInterval(state.run.timer);
      state.run.timer = null;
    }
  }

  function resetRunPanel() {
    stopRunPolling();
    state.run = freshRunState();
    renderRunPanel();
    const scroll = $('#run-scroll');
    if (scroll) scroll.scrollTop = 0;
  }

  async function pollRun() {
    const runId = state.run.id;
    if (runId == null || state.run.polling) return;
    state.run.polling = true;
    try {
      const data = await api.run(runId);
      if (state.run.id !== runId) return;
      if (!data) throw new ApiError('运行详情为空。', -1, 200);
      state.run.data = data;
      renderRunStatus(data);
      renderRunMeta(data);
      renderRunStats(data);
      renderRunAlert(data.status === 'failed' ? data.error || 'Agent 运行失败。' : null);
      appendRunSteps(Array.isArray(data.steps) ? data.steps : []);

      if (data.status === 'success') {
        stopRunPolling();
        const dot = $('#run-dot');
        if (dot) dot.hidden = true;
        updateRunButton();
        toast(
          'success',
          '简报已生成',
          data.briefing_id != null
            ? `运行 #${runId} 完成，正在打开第 #${data.briefing_id} 份简报。`
            : `运行 #${runId} 已完成。`
        );
        if (data.briefing_id != null) {
          await loadBriefings({ openId: data.briefing_id });
          const tab = $('#tab-briefings');
          if (tab) tab.focus({ preventScroll: true });
        } else {
          await loadBriefings({ keepActive: false });
        }
      } else if (data.status === 'failed') {
        stopRunPolling();
        const dot = $('#run-dot');
        if (dot) dot.hidden = true;
        updateRunButton();
        toast('error', '运行失败', data.error || 'Agent 运行未完成，请查看轨迹。');
      } else {
        updateRunButton();
      }
    } catch (error) {
      stopRunPolling();
      const dot = $('#run-dot');
      if (dot) dot.hidden = true;
      renderRunAlert(error, 'poll');
      updateRunButton();
      toast('error', '运行状态刷新失败', error.message, error.code);
    } finally {
      state.run.polling = false;
    }
  }

  function resumeRunPolling() {
    if (state.run.id == null) return;
    renderRunAlert(null);
    const dot = $('#run-dot');
    if (dot) dot.hidden = false;
    pollRun();
    state.run.timer = window.setInterval(pollRun, POLL_INTERVAL);
  }

  async function startRun() {
    if (!state.user) {
      toast('info', '还没有身份', '先在左侧创建一个身份，再生成简报。');
      onNewUserButton();
      return;
    }
    if (state.busy.run || isRunActive()) return;
    const runUserId = state.user.id;
    setTab('run');
    resetRunPanel();
    state.busy.run = true;
    state.run.startedAt = Date.now();
    updateRunButton();
    try {
      const response = await api.startRun(runUserId);
      if (!state.user || state.user.id !== runUserId) return; // 期间切换了身份，丢弃本次运行结果
      const runId = response && (response.run_id != null ? response.run_id : response.id);
      if (runId == null) throw new ApiError('后端没有返回 run_id。', -1, 200);
      state.run.id = runId;
      state.run.data = { id: runId, status: response.status || 'queued', steps: [] };
      renderRunStatus(state.run.data);
      renderRunMeta(state.run.data);
      renderRunStats(state.run.data);
      const empty = $('#run-empty');
      if (empty) empty.hidden = true;
      const dot = $('#run-dot');
      if (dot) dot.hidden = false;
      toast('info', '已提交运行', `运行 #${runId} 已进入队列，正在逐条拉取轨迹。`);
      updateRunButton();
      pollRun();
      state.run.timer = window.setInterval(pollRun, POLL_INTERVAL);
    } catch (error) {
      state.run.id = null;
      state.run.data = { id: null, status: 'failed', steps: [], error: error.message };
      renderRunStatus(state.run.data);
      renderRunMeta(null);
      renderRunStats(null);
      renderRunAlert(error);
      const empty = $('#run-empty');
      if (empty) empty.hidden = true;
      const dot = $('#run-dot');
      if (dot) dot.hidden = true;
      toast('error', '触发运行失败', error.message, error.code);
    } finally {
      state.busy.run = false;
      updateRunButton();
    }
  }

  /* ------------------------------------------------------------------ *
   * 11. 身份切换 / 首屏加载
   * ------------------------------------------------------------------ */

  function syncUserSelectValue() {
    const select = $('#user-select');
    if (select && state.currentUserId != null) select.value = String(state.currentUserId);
  }

  async function selectUser(userId) {
    const id = Number(userId);
    if (!Number.isFinite(id)) return;
    resetRunPanel();
    state.currentUserId = id;
    state.activeBriefingId = null;
    state.briefingDetail = null;
    state.profileLoading = false;
    state.profileError = null;
    let user = state.users.find((item) => Number(item.id) === id) || null;
    if (!user) {
      try {
        user = await api.user(id);
      } catch (error) {
        toast('error', '身份加载失败', error.message, error.code);
      }
    }
    state.user = user;
    state.topics =
      user && user.subscription && Array.isArray(user.subscription.topics)
        ? user.subscription.topics.slice()
        : [];
    syncUserSelectValue();
    renderUserSwitcher();
    renderProfile();
    await loadBriefings({ autoOpen: true });
  }

  async function loadUsers() {
    state.profileLoading = true;
    state.profileError = null;
    renderProfile();
    try {
      const users = await api.users();
      state.users = Array.isArray(users) ? users : [];
      state.profileLoading = false;
      renderUserSwitcher();
      if (!state.users.length) {
        state.currentUserId = null;
        state.user = null;
        state.topics = [];
        state.briefings = [];
        state.briefingsLoading = false;
        renderProfile();
        renderBriefings();
        renderBriefingDetail();
        return;
      }
      const currentExists =
        state.currentUserId != null &&
        state.users.some((user) => String(user.id) === String(state.currentUserId));
      const nextId = currentExists ? state.currentUserId : state.users[0].id;
      await selectUser(nextId);
      state.profileLoading = false;
    } catch (error) {
      state.profileLoading = false;
      state.profileError = error;
      renderProfile();
      renderBriefings();
      renderBriefingDetail();
      toast('error', '身份加载失败', error.message, error.code);
    }
  }

  async function loadMeta() {
    try {
      const meta = await api.meta();
      state.meta = meta || {};
      renderMeta();
    } catch (error) {
      state.meta = null;
      renderMetaError(error);
    }
  }

  async function onUserChange(event) {
    const nextId = Number(event.currentTarget.value);
    if (!Number.isFinite(nextId) || String(nextId) === String(state.currentUserId)) return;
    const previousRunning = isRunActive();
    const nextUser = state.users.find((user) => Number(user.id) === nextId);
    await selectUser(nextId);
    if (nextUser) {
      toast(
        previousRunning ? 'info' : 'success',
        '已切换身份',
        previousRunning
          ? `现在查看「${nextUser.name}」。上一个身份的运行仍在后台继续。`
          : `现在查看「${nextUser.name}」的简报空间。`
      );
    }
  }

  /* ------------------------------------------------------------------ *
   * 12. 标签页
   * ------------------------------------------------------------------ */

  function setTab(tab, options) {
    const next = tab === 'run' ? 'run' : 'briefings';
    state.activeTab = next;
    const briefingsTab = $('#tab-briefings');
    const runTab = $('#tab-run');
    const briefingsPanel = $('#panel-briefings');
    const runPanel = $('#panel-run');
    if (briefingsTab && runTab) {
      briefingsTab.setAttribute('aria-selected', next === 'briefings' ? 'true' : 'false');
      runTab.setAttribute('aria-selected', next === 'run' ? 'true' : 'false');
      briefingsTab.tabIndex = next === 'briefings' ? 0 : -1;
      runTab.tabIndex = next === 'run' ? 0 : -1;
    }
    if (briefingsPanel) briefingsPanel.hidden = next !== 'briefings';
    if (runPanel) runPanel.hidden = next !== 'run';
    if (options && options.focusTab) {
      const target = next === 'run' ? runTab : briefingsTab;
      if (target) target.focus();
    }
  }

  function onTabKeydown(event) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const tabs = $$('.tab');
    if (!tabs.length) return;
    event.preventDefault();
    const current = tabs.indexOf(document.activeElement);
    let index = current;
    if (event.key === 'ArrowRight') index = (current + 1 + tabs.length) % tabs.length;
    else if (event.key === 'ArrowLeft') index = (current - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') index = 0;
    else if (event.key === 'End') index = tabs.length - 1;
    const target = tabs[index];
    if (!target) return;
    target.focus();
    setTab(target.id === 'tab-run' ? 'run' : 'briefings');
  }

  /* ------------------------------------------------------------------ *
   * 13. 事件绑定
   * ------------------------------------------------------------------ */

  function onDocumentClick(event) {
    const element = event.target instanceof Element ? event.target.closest('[data-action]') : null;
    if (!element) return;
    const action = element.getAttribute('data-action');
    const id = element.getAttribute('data-id');
    const topic = element.getAttribute('data-topic');
    switch (action) {
      case 'open-briefing':
        openBriefing(id);
        break;
      case 'back-to-list':
        openDetailView(false);
        focusActiveBriefing();
        break;
      case 'open-run-tab':
        setTab('run', { focusTab: true });
        break;
      case 'start-run':
        startRun();
        break;
      case 'remove-topic':
        removeTopic(topic);
        break;
      case 'toggle-topic':
        toggleTopic(topic);
        break;
      case 'fill-suggestions':
        fillSuggestions();
        break;
      case 'new-user':
        onNewUserButton();
        break;
      case 'retry-users':
        loadUsers();
        break;
      case 'retry-briefings':
        loadBriefings({ keepActive: true });
        break;
      case 'retry-briefing':
        if (state.activeBriefingId != null) openBriefing(state.activeBriefingId);
        break;
      case 'retry-run':
        startRun();
        break;
      case 'resume-run':
        resumeRunPolling();
        break;
      case 'close-dialog':
        closeCreateDialog();
        break;
      default:
        break;
    }
  }

  function bindStaticEvents() {
    $$('.tab').forEach((tab) => {
      tab.addEventListener('click', () => {
        setTab(tab.id === 'tab-run' ? 'run' : 'briefings');
      });
    });
    const tablist = $('.tabs');
    if (tablist) tablist.addEventListener('keydown', onTabKeydown);

    const refresh = $('#refresh-briefings');
    if (refresh) refresh.addEventListener('click', onRefreshBriefings);

    const runButton = $('#run-btn');
    if (runButton) runButton.addEventListener('click', startRun);

    const userSelect = $('#user-select');
    if (userSelect) userSelect.addEventListener('change', onUserChange);

    const newUserButton = $('#new-user-btn');
    if (newUserButton) newUserButton.addEventListener('click', onNewUserButton);

    document.addEventListener('click', onDocumentClick);

    const dialogForm = $('#dialog-create-form');
    if (dialogForm) {
      dialogForm.addEventListener('submit', (event) => onCreateUser(event, 'dialog'));
      const nameInput = $('#dialog-name');
      if (nameInput) {
        nameInput.addEventListener('input', () => nameInput.removeAttribute('aria-invalid'));
      }
      const emailInput = $('#dialog-email');
      if (emailInput) {
        emailInput.addEventListener('input', () => emailInput.removeAttribute('aria-invalid'));
      }
    }
    const dialog = $('#new-user-dialog');
    if (dialog) {
      dialog.addEventListener('click', (event) => {
        if (event.target === dialog) closeCreateDialog();
      });
    }

    window.addEventListener('beforeunload', stopRunPolling);
  }

  /* ------------------------------------------------------------------ *
   * 14. 启动
   * ------------------------------------------------------------------ */

  async function init() {
    bindStaticEvents();
    updateRunButton();
    await loadMeta();
    await loadUsers();
    setTab('briefings');
  }

  // 调试入口：仅用于开发自测（例如校验 Markdown 转义），不参与页面渲染。
  window.AIDailyDebug = {
    state,
    api,
    renderMarkdown,
    stripLeadingHeading,
    formatDateTime,
    formatDayText
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
