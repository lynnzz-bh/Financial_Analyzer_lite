"""本模块负责集中读取项目配置，包括版本号、目录路径、LLM 参数和 AKShare 补丁参数。所有配置都来自环境变量或固定目录，避免在业务代码中硬编码路径和密钥。"""

from pathlib import Path
import os

from dotenv import load_dotenv
from pydantic import BaseModel

PROJECT_VERSION = "0.5.3"
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUT_DIR = DATA_DIR / "output"

load_dotenv(BASE_DIR / ".env", override=True)


class LLMSettings(BaseModel):
    api_key: str = ""
    base_url: str = ""
    model: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


class AkshareProxySettings(BaseModel):
    token: str = ""
    gateway: str = "101.201.173.125"
    retry: int = 30
    fast: bool = True


def _as_bool(value: str, default: bool = True) -> bool:
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


DEEPSEEK_SETTINGS = LLMSettings(
    api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    base_url=os.getenv("DEEPSEEK_BASE_URL", ""),
    model=os.getenv("DEEPSEEK_MODEL", ""),
)
QWEN_SETTINGS = LLMSettings(
    api_key=os.getenv("QWEN_API_KEY", ""),
    base_url=os.getenv("QWEN_BASE_URL", ""),
    model=os.getenv("QWEN_MODEL", ""),
)
AKSHARE_PROXY_SETTINGS = AkshareProxySettings(
    token=os.getenv("AKSHARE_PROXY_TOKEN", ""),
    gateway=os.getenv("AKSHARE_PROXY_GATEWAY", "101.201.173.125"),
    retry=int(os.getenv("AKSHARE_PROXY_RETRY", "30") or 30),
    fast=_as_bool(os.getenv("AKSHARE_PROXY_FAST", "true"), True),
)
