"""本模块封装 akshare-proxy-patch 初始化逻辑。凡调用东方财富网相关 AKShare 接口，必须先执行强制补丁；非东方财富接口可跳过或软初始化。"""

from importlib import import_module
from typing import Any

from config.settings import AKSHARE_PROXY_SETTINGS
from src.utils.logger import get_logger

logger = get_logger(__name__)
_PATCH_INSTALLED = False


class AksharePatchRequiredError(RuntimeError):
    """东方财富接口缺少补丁 token 时抛出的明确错误。"""


def ensure_akshare_patch(required: bool) -> bool:
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return True
    settings = AKSHARE_PROXY_SETTINGS
    if not settings.token:
        if required:
            raise AksharePatchRequiredError("调用东方财富网相关 AKShare 接口前必须配置 AKSHARE_PROXY_TOKEN。")
        logger.info("未配置 AKSHARE_PROXY_TOKEN，非东方财富接口跳过补丁。")
        return False
    try:
        install_patch = getattr(import_module("akshare_proxy_patch"), "install_patch")
        _call_install_patch(install_patch, settings)
        _PATCH_INSTALLED = True
        logger.info("akshare-proxy-patch 已在导入 akshare 前完成初始化。")
        return True
    except Exception as exc:
        if required:
            raise AksharePatchRequiredError(f"AKShare 补丁初始化失败：{exc}") from exc
        logger.warning("AKShare 补丁初始化失败，非强制场景继续运行：%s", exc)
        return False


def _call_install_patch(install_patch: Any, settings: Any) -> None:
    kwargs = {
        "auth_ip": settings.gateway,
        "auth_token": settings.token,
        "retry": settings.retry,
        "hook_domains": [
            "fund.eastmoney.com",
            "push2.eastmoney.com",
            "push2his.eastmoney.com",
            "emweb.securities.eastmoney.com",
            "datacenter-web.eastmoney.com",
        ],
        "fast": settings.fast,
    }
    try:
        install_patch(**kwargs)
    except TypeError:
        install_patch(settings.gateway, settings.token, settings.retry)
