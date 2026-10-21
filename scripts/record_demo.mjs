/**
 * AI Daily 演示录屏脚本（Playwright 自动驱动 + 录制）
 *
 * 前置：
 *   1) 服务已启动（建议真实模型 + 独立 demo 数据库）：
 *        LLM_MODE=real LLM_API_KEY=... DATABASE_URL=sqlite:///./data/demo.db python -m app serve --port 8000
 *   2) 已准备演示身份与一份历史简报：python scripts/seed_demo.py --run
 *
 * 运行：
 *   node scripts/record_demo.mjs
 * 产物：
 *   docs/demo/raw/*.webm
 */

import { createRequire } from "node:module";
import { mkdirSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("D:/nodejs/node_modules/@playwright/cli/node_modules/playwright");

const BASE = process.env.APP_URL || "http://127.0.0.1:8000";
const OUT_DIR = resolve("docs/demo/raw");
const VIEWPORT = { width: 1440, height: 900 };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 在页面里注入一个"录制光标"，让录屏能看清点击位置（真实鼠标事件由 CDP 派发）
const CURSOR_SCRIPT = `(() => {
  if (window.__demoCursorInstalled) return;
  window.__demoCursorInstalled = true;
  const install = () => {
    const style = document.createElement('style');
    style.textContent = \`
      #__demo_cursor{position:fixed;left:-50px;top:-50px;width:16px;height:16px;border-radius:50%;
        background:rgba(124,58,237,.92);border:2.5px solid #fff;box-shadow:0 3px 12px rgba(0,0,0,.35);
        pointer-events:none;z-index:2147483647;transform:translate(-50%,-50%);
        transition:left .08s linear,top .08s linear,width .1s,height .1s}
      #__demo_cursor.clicking{width:11px;height:11px;background:#fff;border-color:rgba(124,58,237,.92)}
      .__demo_ripple{position:fixed;width:14px;height:14px;border-radius:50%;border:2px solid rgba(124,58,237,.9);
        pointer-events:none;z-index:2147483646;transform:translate(-50%,-50%);animation:__demo_rip .55s ease-out forwards}
      @keyframes __demo_rip{to{width:56px;height:56px;opacity:0}}
    \`;
    document.head.appendChild(style);
    const cursor = document.createElement('div');
    cursor.id = '__demo_cursor';
    document.documentElement.appendChild(cursor);
    let last = { x: -50, y: -50 };
    const move = (e) => {
      last = { x: e.clientX, y: e.clientY };
      cursor.style.left = e.clientX + 'px';
      cursor.style.top = e.clientY + 'px';
    };
    window.addEventListener('mousemove', move, true);
    window.addEventListener('mousedown', (e) => {
      move(e);
      cursor.classList.add('clicking');
      const ripple = document.createElement('div');
      ripple.className = '__demo_ripple';
      ripple.style.left = e.clientX + 'px';
      ripple.style.top = e.clientY + 'px';
      document.documentElement.appendChild(ripple);
      setTimeout(() => ripple.remove(), 650);
    }, true);
    window.addEventListener('mouseup', () => cursor.classList.remove('clicking'), true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
})();`;

async function main() {
  mkdirSync(OUT_DIR, { recursive: true });
  // 优先使用系统 Chrome（Playwright 自带 chromium 未安装时也能录）
  const launchOptions = { headless: true };
  const channel = process.env.BROWSER_CHANNEL || "chrome";
  if (channel) launchOptions.channel = channel;
  const browser = await chromium.launch(launchOptions);
  const context = await browser.newContext({
    viewport: VIEWPORT,
    recordVideo: { dir: OUT_DIR, size: VIEWPORT },
    deviceScaleFactor: 1,
  });
  await context.addInitScript(CURSOR_SCRIPT);
  const page = await context.newPage();
  page.setDefaultTimeout(30000);

  const center = async (locator) => {
    const box = await locator.first().boundingBox();
    if (!box) throw new Error("元素不可见，无法点击");
    return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  };

  const moveTo = async (locator, settle = 500) => {
    const { x, y } = await center(locator);
    await page.mouse.move(x, y, { steps: 24 });
    await sleep(settle);
  };

  const clickEl = async (locator, settle = 900) => {
    const { x, y } = await center(locator);
    await page.mouse.move(x, y, { steps: 20 });
    await sleep(380);
    await page.mouse.down();
    await sleep(90);
    await page.mouse.up();
    await sleep(settle);
  };

  console.log("[demo] 打开页面…");
  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(`pageerror: ${error.message}`));
  await page.goto(BASE, { waitUntil: "domcontentloaded" });
  try {
    await page.waitForFunction(
      () => {
        const badge = document.querySelector("#llm-badge");
        return badge && !badge.textContent.includes("读取");
      },
      { timeout: 30000 },
    );
  } catch (error) {
    console.error("[demo] 页面未就绪，调试信息：");
    console.error("  title:", await page.title().catch(() => "?"));
    console.error("  badge:", await page.locator("#llm-badge").innerText().catch(() => "(无元素)"));
    console.error("  bodyText:", (await page.locator("body").innerText().catch(() => "")).slice(0, 400));
    console.error("  consoleErrors:", consoleErrors.slice(0, 10));
    await page.screenshot({ path: "docs/demo/debug.png" }).catch(() => {});
    throw error;
  }
  if (process.env.PROBE === "1") {
    console.log("[demo] PROBE 模式：页面正常，退出。");
    await context.close();
    await browser.close();
    return;
  }
  await sleep(1200);

  console.log("[demo] 展示顶部身份与模型徽标…");
  await moveTo(page.locator("#llm-badge"), 1600);
  await moveTo(page.locator("#user-select"), 900);

  console.log("[demo] 展示订阅偏好…");
  await moveTo(page.locator("#profile-body .chip, #profile-body [class*='chip']"), 900).catch(() => {});
  const keywordInput = page.locator("#profile-body textarea, #profile-body input[type='text']").first();
  await moveTo(keywordInput, 800);
  await moveTo(page.locator("#save-prefs"), 900);

  const briefingCount = await page.locator(".briefing-item").count();
  if (briefingCount > 0) {
    console.log("[demo] 展示历史简报…");
    await clickEl(page.locator("#tab-briefings"), 800);
    await clickEl(page.locator(".briefing-item"), 2200);
    await page.mouse.move(1050, 620, { steps: 18 });
    await sleep(600);
    await page.mouse.wheel(0, 420);
    await sleep(1500);
    await page.mouse.wheel(0, -420);
    await sleep(800);
  }

  const traceCount = await page.locator("#run-steps .tl-item").count();
  if (traceCount > 0) {
    console.log("[demo] 展示运行轨迹（上一次真实运行）…");
    await clickEl(page.locator("#tab-run"), 1000);
    await moveTo(page.locator("#run-steps"), 700).catch(() => {});
    await page.locator("#run-scroll").evaluate((el) => (el.scrollTop = el.scrollHeight));
    await sleep(1600);
    await page.locator("#run-scroll").evaluate((el) => (el.scrollTop = 0));
    await sleep(1000);
  } else {
    console.log("[demo] 暂无历史轨迹，展示运行页引导…");
    await clickEl(page.locator("#tab-run"), 1200);
    await moveTo(page.locator("#run-empty"), 1600).catch(() => {});
  }

  console.log("[demo] 触发一次真实运行…");
  await clickEl(page.locator("#run-btn"), 1600);
  const startedAt = Date.now();
  const deadline = startedAt + 140000;
  let finished = false;
  let lastScrollAt = 0;
  while (Date.now() < deadline) {
    const statusText = await page.locator("#run-status").innerText().catch(() => "");
    if (/已完成|失败|成功/.test(statusText)) {
      finished = true;
      break;
    }
    // 让轨迹像瀑布一样滚动，展示"每一步都是模型决策"
    if (Date.now() - lastScrollAt > 2400) {
      await page.locator("#run-scroll").evaluate((el) => {
        el.scrollTop = Math.min(el.scrollTop + el.clientHeight * 0.62, el.scrollHeight);
      });
      await page.mouse.move(880, 520, { steps: 8 });
      lastScrollAt = Date.now();
    }
    await sleep(600);
  }
  console.log(`[demo] 运行结束：${finished ? "完成" : "超时"}，用时 ${((Date.now() - startedAt) / 1000).toFixed(0)}s`);
  await sleep(1800);

  // 运行成功后 UI 会自动切到新简报；这里再明确展示一次轨迹与简报
  await clickEl(page.locator("#tab-run"), 900);
  await page.locator("#run-scroll").evaluate((el) => (el.scrollTop = el.scrollHeight));
  await sleep(1800);
  await page.locator("#run-scroll").evaluate((el) => (el.scrollTop = 0));
  await sleep(900);

  console.log("[demo] 展示生成结果…");
  await clickEl(page.locator("#tab-briefings"), 900);
  await clickEl(page.locator(".briefing-item"), 1600);
  await page.mouse.move(1060, 640, { steps: 18 });
  await sleep(700);
  await page.mouse.wheel(0, 520);
  await sleep(1200);
  await page.mouse.wheel(0, -260);
  await sleep(1000);

  const video = page.video();
  await page.close();
  await context.close();
  await browser.close();
  const videoPath = await video.path();
  console.log(`\n[demo] 录屏完成：${videoPath}`);
  console.log("[demo] raw 目录内容：", readdirSync(OUT_DIR).join(", "));
}

main().catch(async (error) => {
  console.error("[demo] 录制失败：", error);
  process.exitCode = 1;
});
