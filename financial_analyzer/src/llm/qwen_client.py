"""本模块封装 Qwen 的 OpenAI-compatible 调用。文件头部提醒用户需手动配置 API Key，未配置时仅返回审核不可用状态。"""

from config.settings import QWEN_SETTINGS

MANUAL_API_NOTICE = "请在 .env 中手动填写 QWEN_API_KEY、QWEN_BASE_URL 和 QWEN_MODEL。"


def call_qwen(prompt: str) -> dict[str, str]:
    if not QWEN_SETTINGS.enabled:
        return {"status": "disabled", "content": f"Qwen 未配置，已跳过模型审核。{MANUAL_API_NOTICE}"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=QWEN_SETTINGS.api_key, base_url=QWEN_SETTINGS.base_url)
        response = client.chat.completions.create(model=QWEN_SETTINGS.model, messages=[{"role": "user", "content": prompt}], temperature=0.1)
        return {"status": "ok", "content": response.choices[0].message.content or ""}
    except Exception as exc:
        return {"status": "error", "content": f"Qwen 调用失败：{exc}"}
