# -*- coding: utf-8 -*-
"""qgdata 共享常量与工具函数（所有模块统一 import 此文件）"""
import os, re

QGDATA_RECHARGE_URL = "https://quantgo.ai/data"
QGDATA_SHARED_TOKEN = os.getenv("QGDATA_SHARED_TOKEN", "Mj9mN2xP5qR8vL3tY7wZ1aB4cD6eF8gH9nX4pL2qR7sT5vY8wZ1aB3cD3Tgd7ffg") #专用试用token，后端已做限流（每IP每日有限额度），可环境变量覆盖
QGDATA_TOKEN_RE = re.compile(r'[A-Za-z0-9]{60,70}')

def mask_token(token: str) -> str:
    return (token[:6] + "***") if token and len(token) > 6 else "***"

def classify_qgdata_error(exc: Exception) -> tuple[str, str]:
    """分类qgdata异常→(error_code, 用户提示)。error_code: unauthorized|quota_exceeded|forbidden|api_error"""
    msg = str(exc).lower()
    _http_re = re.search(r'\b(401|403|429)\b', msg)
    if "unauthorized" in msg or (_http_re and _http_re.group(1) == "401"):
        return "unauthorized", f"数据服务未授权，请配置有效Token。获取Token: {QGDATA_RECHARGE_URL}"
    if any(kw in msg for kw in ["额度已达上限", "额度不足", "quota", "rate limit", "too many requests"]) or (_http_re and _http_re.group(1) == "429"):
        return "quota_exceeded", f"当日额度已达上限，去 {QGDATA_RECHARGE_URL} 解锁更多能力"
    if "forbidden" in msg or "权限不足" in msg or (_http_re and _http_re.group(1) == "403"):
        return "forbidden", f"当前套餐无此接口权限，去 {QGDATA_RECHARGE_URL} 升级套餐"
    return "api_error", f"数据接口异常({type(exc).__name__}: {str(exc)[:100]})。如Token额度不足请到 {QGDATA_RECHARGE_URL} 充值"
