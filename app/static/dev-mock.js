/* ==========================================================================
 * dev-mock.js —— 仅开发自测，生产不启用。
 *
 * 当页面 URL 带 ?devmock=1 时，拦截同源 /api/* 的 fetch 请求，返回与
 * docs/API_CONTRACT.md 完全一致的示例数据，用于「没有后端」时的界面预览、
 * 交互自测与截图。
 *
 * 额外开关：
 *   ?devmock=1&devmockfail=1   让「立即生成简报」在数步之后进入 failed 状态，
 *                              用于检查统一错误信封与失败态展示。
 *
 * 说明：不修改 window.fetch 之外任何全局对象；不带参数时本文件直接 return，
 *       生产环境不会生效。运行中的步骤按每次 GET /api/runs/{id} 递增 2 条，
 *       便于观察前端 1200ms 轮询的增量渲染行为。
 * ========================================================================== */
(function () {
  'use strict';

  const params = new URLSearchParams(window.location.search);
  if (params.get('devmock') !== '1') return;
  if (typeof window.fetch !== 'function' || typeof Response !== 'function') return;

  const FAIL_RUN = params.get('devmockfail') === '1';
  const nativeFetch = window.fetch.bind(window);
  const pad = (value) => String(value).padStart(2, '0');
  const clone = (value) => (value == null ? value : JSON.parse(JSON.stringify(value)));
  const iso = (date) => date.toISOString();
  const ymd = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  const delay = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

  const NOW = new Date();
  const hoursAgo = (hours) => new Date(NOW.getTime() - hours * 3600 * 1000);

  function ok(data) {
    return { status: 200, payload: { code: 0, message: 'ok', data: clone(data) } };
  }

  function fail(code, message) {
    const statusMap = { 40001: 400, 40401: 404, 40901: 409, 50001: 500, 50301: 503 };
    return { status: statusMap[code] || 400, payload: { code, message, data: null } };
  }

  /* ---------------------------- 元信息 ---------------------------- */

  const META = {
    version: '0.1.0',
    llm_mode: 'mock',
    model: 'deepseek-chat',
    channels_available: ['web', 'feishu'],
    topic_suggestions: ['AI Agent', '大模型', '开源模型', '算力芯片', 'AI 应用'],
    news_sources: ['Bing News RSS', 'Hacker News', 'arXiv cs.AI', 'TechCrunch AI', '机器之心'],
    daily_run_time: '08:00'
  };

  /* ---------------------------- 简报内容 ---------------------------- */

  const CONTENT_TODAY = [
    '## 今日焦点',
    '',
    '今天 AI 圈的主线是 **Agent 工程化**：DeepSeek 给工具调用加上 KV 缓存，MCP 草案补上流式资源，LangGraph 0.6 让长流程的状态迁移更可预测。',
    '',
    '> 本期 5 条来自过去 48 小时的公开来源，已按你的偏好（AI Agent / 大模型 / 开源模型）筛选，并用 `search_content` 与历史归档做过去重。',
    '',
    '### Agent 工具链',
    '',
    '- **DeepSeek 工具调用缓存**：把重复的 MCP 工具描述缓存到 KV，官方称 Agent 首轮延迟下降约 40%。[原文](https://www.deepseek.com/blog/agent-tool-cache)',
    '- **MCP 1.1 草案**：新增 `resources/stream` 能力，客户端可以增量读取长资源，适合大文档检索场景。',
    '- **LangGraph 0.6**：状态迁移语义调整，长流程 Agent 的恢复行为更可控。',
    '',
    '### 开源与评测',
    '',
    '- 开源模型在 SWE-bench 上首次超过 60%，缩小了与闭源模型的工程能力差距。',
    '- AI 编程助手开始强调「多 Agent 协作」，从单轮补全走向任务编排。',
    '',
    '---',
    '',
    '**给评审的一句话**：这 5 条的抓取顺序（先查历史、再搜索、再抓正文）由模型自己决定，不是写死的流水线。'
  ].join('\n');

  const CONTENT_YESTERDAY = [
    '## 昨日回顾',
    '',
    '开源模型是昨天的主角：**Qwen3** 发布了新的开源权重，社区很快把评测补上；同时 Agent 评测基准更新，开始区分「单工具」和「多步工具链」场景。',
    '',
    '### 值得回看',
    '',
    '- Qwen3 开源权重发布，覆盖 8B / 32B 两个尺寸。',
    '- Agent 评测基准加入多步工具链用例，长程任务权重提高。',
    '- 向量数据库发布新版本，召回延迟进一步下降。',
    '',
    '> 昨天这 3 条与你今天看到的内容没有重复 URL。'
  ].join('\n');

  const CONTENT_EARLIER = [
    '## 归档摘要',
    '',
    '这一期关注算力与基础设施：**GPU 供应** 出现新的排期消息，Agent 框架的横向对比也更新了。',
    '',
    '- 新一代 GPU 交付周期缩短。',
    '- 主流 Agent 框架横向对比：工具注册、轨迹记录、沙箱能力。'
  ].join('\n');

  const NEWS = [
    {
      title: 'DeepSeek 为 Agent 工具调用加上 KV 缓存',
      url: 'https://www.deepseek.com/blog/agent-tool-cache',
      source: 'DeepSeek Blog',
      published_at: iso(hoursAgo(5.5)),
      summary:
        '官方示例显示，新的工具描述缓存层会按 schema 哈希复用 MCP 工具定义，Agent 首轮决策不再重复传输大段 JSON，官方称首轮延迟下降约 40%。',
      reason: '命中关键词 DeepSeek；与「AI Agent」话题直接相关，且过去 48 小时首次出现。',
      tags: ['DeepSeek', 'Agent'],
      score: 0.94
    },
    {
      title: 'MCP 规范 1.1 草案：新增资源流式读取能力',
      url: 'https://modelcontextprotocol.io/specification/draft',
      source: 'Model Context Protocol',
      published_at: iso(hoursAgo(8)),
      summary:
        '草案补上 resources/stream 语义，客户端可以增量读取长文档与日志，减少一次性拉取超大资源带来的超时问题。',
      reason: '命中关键词 MCP；属于协议层更新，对你的 Agent 工具链选型有直接影响。',
      tags: ['MCP', '协议'],
      score: 0.91
    },
    {
      title: 'LangGraph 0.6 发布：图状态迁移更可预测',
      url: 'https://blog.langchain.dev/langgraph-0-6/',
      source: 'LangChain Blog',
      published_at: iso(hoursAgo(14)),
      summary:
        '新版本调整了条件边与恢复点的语义，长流程 Agent 中断后可以从最近的可恢复状态继续，减少重复调用工具。',
      reason: '命中关键词 LangGraph；与「Agent 编排」主题相关。',
      tags: ['LangGraph', 'Agent'],
      score: 0.87
    },
    {
      title: '开源模型在 SWE-bench 上首次超过 60%',
      url: 'https://news.ycombinator.com/item?id=42810000',
      source: 'Hacker News',
      published_at: iso(hoursAgo(19)),
      summary:
        '一个 32B 开源模型在 SWE-bench Verified 上取得 61.2% 的成绩，社区讨论集中在数据污染与真实工程可用性两点。',
      reason: '命中「开源模型」话题；评测结果需要结合数据污染讨论一起看。',
      tags: ['开源模型', '评测'],
      score: 0.84
    },
    {
      title: 'AI 编程助手进入「多 Agent 协作」阶段',
      url: 'https://techcrunch.com/2026/10/20/ai-coding-agents-collaboration/',
      source: 'TechCrunch AI',
      published_at: iso(hoursAgo(23)),
      summary:
        '多家厂商开始把单轮补全升级为规划、执行、审查三个角色协作的编程 Agent，并强调可观测的中间产物。',
      reason: '命中「AI 应用」话题；与本次简报的 Agent 主题一致。',
      tags: ['AI 应用', 'Agent'],
      score: 0.8
    },
    {
      title: 'Qwen3 开源权重发布，覆盖 8B / 32B 两个尺寸',
      url: 'https://qwenlm.github.io/blog/qwen3-open-weights/',
      source: 'Qwen Blog',
      published_at: iso(hoursAgo(30)),
      summary: '新的开源权重在中文推理与工具调用评测上有明显提升，社区已开始补第三方复现。',
      reason: '命中「开源模型」话题；属于当天最受关注的开源发布。',
      tags: ['Qwen3', '开源模型'],
      score: 0.9
    },
    {
      title: 'Agent 评测基准加入多步工具链用例',
      url: 'https://arxiv.org/abs/2610.01234',
      source: 'arXiv cs.AI',
      published_at: iso(hoursAgo(33)),
      summary: '新基准把长程任务权重提高，要求模型在有限步数内完成检索、校验与写入三类操作。',
      reason: '与「Agent 评测」相关，能解释为什么最近的排行榜变化较大。',
      tags: ['评测', 'Agent'],
      score: 0.82
    },
    {
      title: '新一代 GPU 交付周期缩短',
      url: 'https://www.jiqizhixin.com/articles/2026-10-18-gpu-supply',
      source: '机器之心',
      published_at: iso(hoursAgo(52)),
      summary: '供应链消息称新一代加速卡的平均交付周期从 26 周缩短到 14 周，云厂商开始调整报价。',
      reason: '命中「算力芯片」话题；影响 Agent 推理成本。',
      tags: ['算力芯片'],
      score: 0.78
    }
  ];

  function buildItems(indexes) {
    return indexes.map((index, position) => {
      const news = NEWS[index];
      return {
        rank: position + 1,
        title: news.title,
        url: news.url,
        source: news.source,
        published_at: news.published_at,
        summary: news.summary,
        reason: news.reason,
        tags: news.tags,
        score: news.score
      };
    });
  }

  function makeBriefing(id, hours, summary, content, indexes) {
    const created = hoursAgo(hours);
    const items = buildItems(indexes);
    return {
      id,
      title: `AI Daily · ${ymd(created)}`,
      summary,
      content_md: content,
      item_count: items.length,
      briefing_date: ymd(created),
      created_at: iso(created),
      items,
      deliveries: [
        { channel: 'web', status: 'success', detail: '', created_at: iso(created) },
        {
          channel: 'feishu',
          status: 'skipped',
          detail: 'webhook 未配置',
          created_at: iso(created)
        },
        { channel: 'email', status: 'failed', detail: 'SMTP 未配置', created_at: iso(created) }
      ]
    };
  }

  /* ---------------------------- 用户与订阅 ---------------------------- */

  const SUBSCRIPTION_TEMPLATE = {
    topics: [],
    keywords: [],
    exclude_keywords: [],
    max_items: 5,
    language: 'zh',
    channels: ['web'],
    push_time: '08:00',
    enabled: true
  };

  const users = [
    {
      id: 1,
      name: '张三',
      email: 'zhang@example.com',
      timezone: 'Asia/Shanghai',
      created_at: iso(hoursAgo(50)),
      subscription: {
        topics: ['AI Agent', '大模型', '开源模型'],
        keywords: ['DeepSeek', 'MCP', 'LangGraph'],
        exclude_keywords: ['招聘', '融资'],
        max_items: 5,
        language: 'zh',
        channels: ['web', 'feishu', 'email'],
        push_time: '08:00',
        enabled: true
      }
    },
    {
      id: 2,
      name: '李四',
      email: '',
      timezone: 'Asia/Shanghai',
      created_at: iso(hoursAgo(210)),
      subscription: {
        topics: ['算力芯片'],
        keywords: ['GPU'],
        exclude_keywords: [],
        max_items: 3,
        language: 'zh',
        channels: ['web'],
        push_time: '09:30',
        enabled: true
      }
    }
  ];

  let nextUserId = 3;

  const briefings = new Map([
    [
      1,
      [
        makeBriefing(
          3,
          2.5,
          '今日 5 条：DeepSeek 工具调用 KV 缓存上线、MCP 1.1 草案补上流式资源、LangGraph 0.6 调整状态迁移；另有开源模型评测与多 Agent 编程助手进展。',
          CONTENT_TODAY,
          [0, 1, 2, 3, 4]
        ),
        makeBriefing(
          2,
          26,
          '昨日 3 条：Qwen3 开源权重发布、Agent 评测基准加入多步工具链、向量数据库新版本降低召回延迟。',
          CONTENT_YESTERDAY,
          [5, 6, 7]
        ),
        makeBriefing(
          1,
          50,
          '归档 2 条：新一代 GPU 交付周期缩短，主流 Agent 框架横向对比更新。',
          CONTENT_EARLIER,
          [7, 2]
        )
      ]
    ],
    [2, []]
  ]);

  let nextBriefingId = 4;

  const runs = new Map();
  let nextRunId = 40;

  function findUser(id) {
    return users.find((user) => String(user.id) === String(id)) || null;
  }

  function briefingSummaries(userId) {
    const list = briefings.get(Number(userId)) || [];
    return list
      .slice()
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
      .map((item) => ({
        id: item.id,
        title: item.title,
        summary: item.summary,
        item_count: item.item_count,
        briefing_date: item.briefing_date,
        created_at: item.created_at
      }));
  }

  function findBriefing(id) {
    for (const list of briefings.values()) {
      const found = list.find((item) => String(item.id) === String(id));
      if (found) return found;
    }
    return null;
  }

  /* ---------------------------- 运行轨迹计划 ---------------------------- */

  function buildRunPlan(user, startedAt) {
    const today = new Date();
    const publishItems = buildItems([0, 1, 2, 3, 4]).map((item) => ({
      title: item.title,
      url: item.url,
      source: item.source,
      summary: item.summary,
      reason: item.reason
    }));
    const searchResults = NEWS.slice(0, 4).map((news) => ({
      title: news.title,
      url: news.url,
      source: news.source,
      published_at: news.published_at
    }));
    return [
      {
        kind: 'assistant_message',
        thought: '先看看历史简报归档，避免今天重复选题。',
        tool_name: '',
        tool_args: '',
        tool_result: '',
        duration_ms: 0
      },
      {
        kind: 'tool_call',
        thought: '',
        tool_name: 'list_dir',
        tool_args: '{"path": "archive"}',
        tool_result: '2026-10-19.md\n2026-10-18.md\n2026-10-17.md',
        duration_ms: 3
      },
      {
        kind: 'assistant_message',
        thought:
          '昨天已经讲过「Qwen3 开源」和「Agent 评测基准」，今天避开这两个方向，优先确认 DeepSeek 与 MCP 的进展。',
        tool_name: '',
        tool_args: '',
        tool_result: '',
        duration_ms: 0
      },
      {
        kind: 'tool_call',
        thought: '',
        tool_name: 'read_file',
        tool_args: JSON.stringify({ path: 'archive/2026-10-19.md', offset: 0, limit: 8000 }),
        tool_result:
          '## 昨日回顾\n\n开源模型是昨天的主角：Qwen3 发布了新的开源权重……\nAgent 评测基准加入多步工具链用例……\n已推送渠道：web(success), feishu(skipped)',
        duration_ms: 6
      },
      {
        kind: 'tool_call',
        thought: '',
        tool_name: 'search_news',
        tool_args: JSON.stringify({
          query: `${(user.subscription.topics || []).slice(0, 2).join(' ')} ${(
            user.subscription.keywords || []
          )
            .slice(0, 2)
            .join(' ')}`.trim(),
          days: 2,
          limit: 8
        }),
        tool_result: JSON.stringify(searchResults, null, 2),
        duration_ms: 482
      },
      {
        kind: 'assistant_message',
        thought:
          '候选里有 5 条值得跟进。TechCrunch 那条只有标题和摘要，先抓正文确认细节，再决定摘要怎么写。',
        tool_name: '',
        tool_args: '',
        tool_result: '',
        duration_ms: 0
      },
      {
        kind: 'tool_call',
        thought: '',
        tool_name: 'fetch_url',
        tool_args: JSON.stringify({
          url: 'https://techcrunch.com/2026/10/20/ai-coding-agents-collaboration/',
          max_chars: 4000
        }),
        tool_result:
          '标题：AI 编程助手进入「多 Agent 协作」阶段\n来源：TechCrunch AI\n\n正文：多家厂商开始把单轮补全升级为规划、执行、审查三个角色协作的编程 Agent。与早期只强调补全速度不同，新的产品把重点放在可观测的中间产物上：规划阶段输出任务分解，执行阶段记录每次工具调用，审查阶段单独检查改动范围。\n\n一位受访工程师表示，多 Agent 协作真正的难点不是模型能力，而是状态管理与失败恢复——这也是本周 MCP 与 LangGraph 更新的共同方向。',
        duration_ms: 842
      },
      {
        kind: 'tool_call',
        thought: '',
        tool_name: 'search_content',
        tool_args: JSON.stringify({ keyword: 'DeepSeek', dir: 'archive' }),
        tool_result: '未命中：archive 中没有包含 DeepSeek 的历史简报，说明今天这条是首次出现。',
        duration_ms: 4
      },
      {
        kind: 'tool_call',
        thought: '',
        tool_name: 'write_file',
        tool_args: JSON.stringify({
          path: `cache/${ymd(today)}-news.json`,
          content: JSON.stringify({ count: 8, kept: 5, deduped: 3 })
        }),
        tool_result: `已写入 cache/${ymd(today)}-news.json（4,821 bytes）`,
        duration_ms: 5
      },
      {
        kind: 'tool_call',
        thought: '',
        tool_name: 'publish_briefing',
        tool_args: JSON.stringify({
          title: `AI Daily · ${ymd(today)}`,
          summary: '今日 5 条：Agent 工程化成为主线，DeepSeek 工具缓存与 MCP 流式资源值得关注。',
          items: publishItems
        }),
        tool_result: JSON.stringify(
          { ok: true, briefing_id: nextBriefingId, item_count: 5, deliveries: ['web', 'feishu'] },
          null,
          2
        ),
        duration_ms: 11
      },
      {
        kind: 'final_answer',
        thought:
          '简报已经发布，共 5 条，覆盖 Agent 工具链与开源模型进展。轨迹与推送结果都已落库。',
        tool_name: '',
        tool_args: '',
        tool_result: '',
        duration_ms: 0
      }
    ];
  }

  function publicRun(run) {
    return {
      id: run.id,
      user_id: run.user_id,
      status: run.status,
      trigger: run.trigger,
      llm_mode: run.llm_mode,
      model: run.model,
      step_count: run.steps.length,
      tool_call_count: run.steps.filter((step) => step.tool_name).length,
      prompt_tokens: run.prompt_tokens,
      completion_tokens: run.completion_tokens,
      briefing_id: run.briefing_id,
      error: run.error,
      started_at: run.started_at,
      finished_at: run.finished_at,
      steps: run.steps.slice()
    };
  }

  function buildRunBriefing(run) {
    const created = new Date();
    const items = buildItems([0, 1, 2, 3, 4]);
    const briefing = {
      id: nextBriefingId++,
      title: `AI Daily · ${ymd(created)}`,
      summary: '手动运行生成：Agent 自主完成历史去重、新闻检索、正文核实与发布，共 5 条。',
      content_md: CONTENT_TODAY,
      item_count: items.length,
      briefing_date: ymd(created),
      created_at: iso(created),
      items,
      deliveries: [
        { channel: 'web', status: 'success', detail: '', created_at: iso(created) },
        {
          channel: 'feishu',
          status: 'skipped',
          detail: 'webhook 未配置',
          created_at: iso(created)
        }
      ]
    };
    const list = briefings.get(Number(run.user_id)) || [];
    list.unshift(briefing);
    briefings.set(Number(run.user_id), list);
    return briefing;
  }

  function startRun(userId) {
    const user = findUser(userId);
    if (!user) return fail(40401, 'user not found');
    const id = nextRunId++;
    const started = new Date();
    const run = {
      id,
      user_id: user.id,
      status: 'queued',
      trigger: 'manual',
      llm_mode: META.llm_mode,
      model: META.model,
      prompt_tokens: 0,
      completion_tokens: 0,
      briefing_id: null,
      error: '',
      started_at: iso(started),
      finished_at: null,
      steps: [],
      reveal: 0,
      plan: buildRunPlan(user, started)
    };
    runs.set(id, run);
    return ok({ run_id: id, status: 'queued' });
  }

  function getRun(runId) {
    const run = runs.get(Number(runId));
    if (!run) return fail(40401, 'run not found');
    if (run.status === 'queued') run.status = 'running';
    if (run.status === 'running') {
      const nextSteps = run.plan.slice(run.reveal, run.reveal + 2);
      nextSteps.forEach((step, offset) => {
        const stepIndex = run.reveal + offset;
        run.steps.push({
          step_index: stepIndex,
          kind: step.kind,
          thought: step.thought,
          tool_name: step.tool_name,
          tool_args: step.tool_args,
          tool_result: step.tool_result,
          duration_ms: step.duration_ms,
          created_at: iso(new Date(Date.parse(run.started_at) + stepIndex * 1700))
        });
      });
      run.reveal += nextSteps.length;
      run.prompt_tokens = 3200 + run.reveal * 140;
      run.completion_tokens = 860 + run.reveal * 46;

      if (FAIL_RUN && run.reveal >= 4) {
        run.status = 'failed';
        run.error = 'LLM 返回 429（rate limit），已重试 3 次仍失败；运行记录已落库，可稍后重试。';
        run.finished_at = iso(new Date());
      } else if (run.reveal >= run.plan.length) {
        run.status = 'success';
        run.finished_at = iso(new Date());
        run.prompt_tokens = 3820;
        run.completion_tokens = 1180;
        const briefing = buildRunBriefing(run);
        run.briefing_id = briefing.id;
      }
    }
    return ok(publicRun(run));
  }

  /* ---------------------------- 订阅校验 ---------------------------- */

  function updateSubscription(userId, body) {
    const user = findUser(userId);
    if (!user) return fail(40401, 'user not found');
    const payload = body && typeof body === 'object' ? body : {};
    const next = Object.assign({}, SUBSCRIPTION_TEMPLATE, user.subscription);

    if (payload.topics !== undefined) {
      if (!Array.isArray(payload.topics)) return fail(40001, 'topics must be an array');
      next.topics = payload.topics.map(String).filter(Boolean).slice(0, 20);
    }
    if (payload.keywords !== undefined) {
      if (!Array.isArray(payload.keywords)) return fail(40001, 'keywords must be an array');
      next.keywords = payload.keywords.map(String).filter(Boolean).slice(0, 30);
    }
    if (payload.exclude_keywords !== undefined) {
      if (!Array.isArray(payload.exclude_keywords)) {
        return fail(40001, 'exclude_keywords must be an array');
      }
      next.exclude_keywords = payload.exclude_keywords.map(String).filter(Boolean).slice(0, 30);
    }
    if (payload.max_items !== undefined) {
      const maxItems = Number(payload.max_items);
      if (!Number.isInteger(maxItems) || maxItems < 3 || maxItems > 10) {
        return fail(40001, 'max_items must be an integer between 3 and 10');
      }
      next.max_items = maxItems;
    }
    if (payload.language !== undefined) next.language = String(payload.language);
    if (payload.channels !== undefined) {
      if (!Array.isArray(payload.channels)) return fail(40001, 'channels must be an array');
      const allowed = ['web', 'feishu', 'email'];
      if (payload.channels.some((channel) => !allowed.includes(channel))) {
        return fail(40001, 'channels only accept web | feishu | email');
      }
      next.channels = payload.channels.slice();
    }
    if (payload.push_time !== undefined) {
      if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(String(payload.push_time))) {
        return fail(40001, 'push_time must match HH:MM');
      }
      next.push_time = String(payload.push_time);
    }
    if (payload.enabled !== undefined) next.enabled = Boolean(payload.enabled);

    user.subscription = next;
    return ok(next);
  }

  /* ---------------------------- 路由 ---------------------------- */

  function route(method, url, body) {
    const path = url.pathname.replace(/^\/api/, '');
    const parts = path.split('/').filter(Boolean);

    if (method === 'GET' && path === '/meta') return ok(META);
    if (method === 'GET' && path === '/health') {
      return ok({ status: 'ok', version: '0.1.0' });
    }

    if (parts[0] === 'users') {
      if (parts.length === 1 && method === 'GET') {
        const sorted = users
          .slice()
          .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
        return ok(sorted);
      }
      if (parts.length === 1 && method === 'POST') {
        const name = body && body.name != null ? String(body.name).trim() : '';
        if (!name) return fail(40001, 'name is required');
        if (name.length > 40) return fail(40001, 'name must be 40 characters or fewer');
        const email = body && body.email ? String(body.email).trim() : '';
        if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
          return fail(40001, 'email format is invalid');
        }
        if (email && users.some((user) => user.email.toLowerCase() === email.toLowerCase())) {
          return fail(40901, 'email already exists');
        }
        const created = {
          id: nextUserId++,
          name,
          email,
          timezone: 'Asia/Shanghai',
          created_at: iso(new Date()),
          subscription: clone(SUBSCRIPTION_TEMPLATE)
        };
        users.unshift(created);
        briefings.set(created.id, []);
        return ok(created);
      }

      const userId = parts[1];
      const user = findUser(userId);
      if (!user) return fail(40401, 'user not found');
      if (parts.length === 2 && method === 'GET') return ok(user);
      if (parts[2] === 'subscription' && method === 'PUT') {
        return updateSubscription(userId, body);
      }
      if (parts[2] === 'briefings' && method === 'GET') {
        const limit = Math.max(1, Math.min(100, Number(url.searchParams.get('limit')) || 20));
        const offset = Math.max(0, Number(url.searchParams.get('offset')) || 0);
        return ok(briefingSummaries(userId).slice(offset, offset + limit));
      }
      if (parts[2] === 'run' && method === 'POST') {
        return startRun(userId);
      }
      return fail(40401, `mock: unknown user route ${method} ${path}`);
    }

    if (parts[0] === 'briefings' && parts.length === 2 && method === 'GET') {
      const briefing = findBriefing(parts[1]);
      if (!briefing) return fail(40401, 'briefing not found');
      return ok(briefing);
    }

    if (parts[0] === 'runs') {
      if (parts.length === 1 && method === 'GET') {
        const userId = url.searchParams.get('user_id');
        const limit = Math.max(1, Math.min(50, Number(url.searchParams.get('limit')) || 10));
        const list = Array.from(runs.values())
          .filter((run) => (userId == null ? true : String(run.user_id) === String(userId)))
          .sort((a, b) => b.id - a.id)
          .slice(0, limit)
          .map((run) => {
            const summary = publicRun(run);
            delete summary.steps;
            return summary;
          });
        return ok(list);
      }
      if (parts.length === 2 && method === 'GET') return getRun(parts[1]);
      return fail(40401, `mock: unknown run route ${method} ${path}`);
    }

    return fail(40401, `mock: unknown endpoint ${method} ${path}`);
  }

  /* ---------------------------- fetch 拦截 ---------------------------- */

  function readBody(init) {
    if (!init || init.body == null) return null;
    if (typeof init.body === 'string') {
      try {
        return JSON.parse(init.body);
      } catch (error) {
        return null;
      }
    }
    return null;
  }

  window.fetch = async function devMockFetch(input, init) {
    const rawUrl =
      typeof input === 'string' ? input : input && input.url ? input.url : String(input);
    let url;
    try {
      url = new URL(rawUrl, window.location.origin);
    } catch (error) {
      return nativeFetch(input, init);
    }
    if (url.origin !== window.location.origin || !url.pathname.startsWith('/api/')) {
      return nativeFetch(input, init);
    }

    const method = String(
      (init && init.method) || (input && input.method) || 'GET'
    ).toUpperCase();
    await delay(140 + Math.random() * 160);

    let result;
    try {
      result = route(method, url, readBody(init));
    } catch (error) {
      result = {
        status: 500,
        payload: { code: 50001, message: `mock internal error: ${error.message}`, data: null }
      };
    }

    return new Response(JSON.stringify(result.payload), {
      status: result.status,
      headers: { 'Content-Type': 'application/json; charset=utf-8', 'X-Dev-Mock': '1' }
    });
  };

  // 自测辅助：在控制台查看 / 重置 mock 数据。
  window.__devmock = {
    meta: META,
    users,
    briefings,
    runs,
    resetRuns() {
      runs.clear();
      nextRunId = 40;
    }
  };

  console.info(
    '[dev-mock] 已启用示例数据（仅开发自测，生产不启用）。URL 带 ?devmock=1 生效；加 &devmockfail=1 可查看失败态。'
  );
})();
