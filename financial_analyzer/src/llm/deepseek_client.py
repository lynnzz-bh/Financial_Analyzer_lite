"""本模块封装 DeepSeek 的 OpenAI-compatible 调用。文件头部提醒用户需手动配置 API Key，未配置时返回禁用状态而不伪造分析。"""

from config.settings import DEEPSEEK_SETTINGS

MANUAL_API_NOTICE = "请在 .env 中手动填写 DEEPSEEK_API_KEY、DEEPSEEK_BASE_URL 和 DEEPSEEK_MODEL。"


def call_deepseek(prompt: str) -> dict[str, str]:
    if not DEEPSEEK_SETTINGS.enabled:
        return {"status": "disabled", "content": f"DeepSeek 未配置，已跳过模型分析。{MANUAL_API_NOTICE}"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=DEEPSEEK_SETTINGS.api_key, base_url=DEEPSEEK_SETTINGS.base_url)
        response = client.chat.completions.create(model=DEEPSEEK_SETTINGS.model, messages=[{"role": "user", "content": prompt}], temperature=0.2)
        return {"status": "ok", "content": response.choices[0].message.content or ""}
    except Exception as exc:
        return {"status": "error", "content": f"DeepSeek 调用失败：{exc}"}
