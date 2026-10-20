"""交互式/命令行配置 .env 的小工具（不会把密钥写进仓库，只改被 gitignore 的 .env）。

用法示例：
    # 配置 QQ 邮箱推送（授权码不是登录密码）
    python scripts/configure_env.py --qq-email 3427669981@qq.com --qq-auth <授权码> \
        --push-channels web,email

    # 顺带配置真实模型
    python scripts/configure_env.py --llm-api-key sk-xxx --llm-mode real
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"


def set_key(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    line = f"{key}={value}"
    if pattern.search(text):
        return pattern.sub(line, text)
    return text.rstrip() + "\n" + line + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="更新本地 .env（仅本地生效）")
    parser.add_argument("--qq-email")
    parser.add_argument("--qq-auth", help="QQ 邮箱 SMTP 授权码（非登录密码）")
    parser.add_argument("--push-channels", help="例如 web,email")
    parser.add_argument("--llm-api-key")
    parser.add_argument("--llm-mode", choices=["real", "mock"])
    args = parser.parse_args()

    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""

    if args.qq_email and args.qq_auth:
        for key, value in {
            "SMTP_HOST": "smtp.qq.com",
            "SMTP_PORT": "465",
            "SMTP_USER": args.qq_email,
            "SMTP_PASSWORD": args.qq_auth,
            "SMTP_FROM": args.qq_email,
            "SMTP_USE_SSL": "true",
        }.items():
            text = set_key(text, key, value)

    if args.push_channels:
        text = set_key(text, "PUSH_CHANNELS", args.push_channels)
    if args.llm_api_key:
        text = set_key(text, "LLM_API_KEY", args.llm_api_key)
    if args.llm_mode:
        text = set_key(text, "LLM_MODE", args.llm_mode)

    ENV_PATH.write_text(text, encoding="utf-8")

    # 只打印脱敏后的关键配置
    masked = []
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if re.match(r"^(SMTP_PASSWORD|LLM_API_KEY)=", line):
            masked.append("SMTP_PASSWORD=***masked***" if line.startswith("SMTP_PASSWORD") else "LLM_API_KEY=***masked***")
        elif re.match(r"^(SMTP_HOST|SMTP_PORT|SMTP_USER|SMTP_FROM|SMTP_USE_SSL|PUSH_CHANNELS|LLM_MODE)=", line):
            masked.append(line)
    print("已更新 .env：")
    print("\n".join(masked))


if __name__ == "__main__":
    main()
