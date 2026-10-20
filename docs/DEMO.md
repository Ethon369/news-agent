# 3 分钟演示录屏脚本

> 目标：让评审在 3 分钟内看到「Agent 的工具顺序由 LLM 决定」这件事，而不是听介绍。
> 录屏使用 Playwright 自动驱动浏览器 + 录制，可复现、无需人工操作。

## 0. 录制前准备

```bash
# 用独立的演示数据库，避免污染你的开发数据
# .env 中设置（或临时环境变量）：
LLM_MODE=real
LLM_API_KEY=sk-xxx
DATABASE_URL=sqlite:///./data/demo.db

# 启动服务
python -m app serve --port 8000
```

浏览器打开 `http://127.0.0.1:8000`，先新建一个演示身份（如「林悦」，关注 AI Agent / 大模型 / 开源模型），
再手动点一次「立即生成简报」等待完成 —— 这样录制时既有历史简报可展示，又不会触发全量去重。

## 1. 录制

```bash
node scripts/record_demo.mjs
```

产物：`docs/demo/raw/*.webm`（Playwright 原始录制）。

转换为 mp4（Windows 自带 ffmpeg 在 ms-playwright 缓存里）：

```bash
# 找到 ffmpeg
%LOCALAPPDATA%\ms-playwright\ffmpeg-*/ffmpeg-win64.exe
# 转码
ffmpeg -i docs/demo/raw/<video>.webm -c:v libx264 -pix_fmt yuv420p -movflags +faststart docs/demo/ai-daily-demo.mp4
```

## 2. 时间轴与旁白

| 时间 | 画面 | 旁白 |
|---|---|---|
| 0:00-0:08 | 首页加载完成 | 「这是 AI Daily，一个每日 AI 新闻简报 Agent。」 |
| 0:08-0:20 | 鼠标滑过顶部：Mock/真实模型徽标、身份下拉 | 「题目核心要求是：工具调用顺序由 LLM 决定。我把它做成了可回放的运行轨迹。」 |
| 0:20-0:40 | 左栏偏好表单：话题 chip、关键词、每日条数、推送渠道 | 「用户填身份、设置订阅偏好，Agent 按偏好筛选内容。」 |
| 0:40-0:55 | 切到「历史简报」，打开一份简报详情 | 「历史简报落库，每条都有来源链接和入选理由，还能看到推送记录。」 |
| 0:55-1:15 | 切到「运行轨迹」，上下滚动上一次运行的步骤 | 「每次运行，模型的每一步思考、调了哪个工具、参数和结果，全部落库。这里能看到它自己决定先查归档再检索。」 |
| 1:15-1:30 | 点「立即生成简报」 | 「现在触发一次真实运行。注意：没有任何硬编码流程，下一步做什么完全由模型决定。」 |
| 1:30-2:30 | 轨迹实时增长：模型思考 → 工具调用 → 结果；页面自动滚动 | 「模型先看历史归档去重，然后检索；发现学术源不合适会自己换关键词；对关键条目抓正文核实；最后提交简报。」 |
| 2:30-2:50 | 自动跳转到新简报详情 | 「简报生成：5 条新闻，每条有来源、链接、摘要和入选理由。推送记录显示站内成功、飞书已推送。」 |
| 2:50-3:00 | 回到 README 标题 / 测试命令截图（可选切画面） | 「代码仓库分层提交，README 5 分钟跑通，85+ 离线测试。谢谢。」 |

## 3. 旁白音频（可选）

如果不想现场配音，可以用 Windows 内置 TTS 生成旁白音轨再与录屏合并：

```powershell
Add-Type -AssemblyName System.Speech
$syn = New-Object System.Speech.Synthesis.SpeechSynthesizer
$syn.SetOutputToWaveFile("docs/demo/narration.wav")
$syn.Speak("这是 AI Daily，一个每日 AI 新闻简报 Agent。")
$syn.Dispose()
```

```bash
ffmpeg -i docs/demo/ai-daily-demo.mp4 -i docs/demo/narration.wav -c:v copy -c:a aac -shortest docs/demo/ai-daily-demo-narrated.mp4
```

## 4. 录制注意事项

- 使用真实模式（`LLM_MODE=real`），让评审看到真实模型行为；mock 模式仅用于「无密钥快速体验」；
- 演示数据库里先有一份历史简报，便于展示去重与历史功能；
- 单次真实运行约 60-90 秒，录屏中不要剪掉轨迹增长过程——这正是核心证据；
- 若网络导致新闻源失败，可重试一次；`search_news` 多源降级通常能兜住。
