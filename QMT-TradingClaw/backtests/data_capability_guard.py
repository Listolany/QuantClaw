#!/usr/bin/env python3
"""Data capability guard for requirement preflight."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Set


# Baseline capability list from SDK_USER_API.md (documented interfaces).
DOCUMENTED_APIS: Set[str] = {
    "stock_basic", "stk_premarket", "trade_cal", "stock_st", "st", "stock_hsgt",
    "namechange", "stock_company", "stk_managers", "stk_rewards", "bse_mapping", "new_share", "bak_basic",
    "stk_mins", "daily", "stk_weekly_monthly", "stk_week_month_adj", "weekly", "monthly",
    "adj_factor", "daily_basic", "stk_limit", "suspend_d", "stk_auction", "stk_auction_o", "stk_auction_c",
    "hsgt_top10", "ggt_top10", "ggt_daily", "ggt_monthly",
    "income", "balancesheet", "cashflow", "forecast", "express", "dividend", "fina_indicator", "fina_audit",
    "fina_mainbz", "disclosure_date",
    "top10_holders", "top10_floatholders", "pledge_stat", "pledge_detail", "repurchase", "share_float",
    "block_trade", "stk_holdernumber", "stk_holdertrade", "report_rc", "ccass_hold", "ccass_hold_detail", "hk_hold",
    "cyq_perf", "cyq_chips", "stk_factor_pro", "stk_nineturn", "stk_ah_comparison",
    "margin_detail", "margin_secs", "margin", "slb_len",
    "moneyflow", "moneyflow_ths", "moneyflow_dc", "moneyflow_cnt_ths", "moneyflow_ind_ths",
    "moneyflow_ind_dc", "moneyflow_mkt_dc", "moneyflow_hsgt",
    "top_list", "top_inst", "limit_list_ths", "limit_list_d", "limit_step", "limit_cpt_list",
    "ths_index", "ths_daily", "ths_member", "dc_index", "dc_member", "dc_daily", "tdx_index", "tdx_member", "tdx_daily",
    "stk_surv", "broker_recommend", "hm_list", "hm_detail", "ths_hot", "dc_hot", "kpl_list", "kpl_concept_cons",
}

# Requirement keyword -> expected APIs.
KEYWORD_API_RULES: Dict[str, List[str]] = {
    "分钟": ["stk_mins"],
    "分时": ["stk_mins"],
    "tick": ["stk_mins"],
    "日线": ["daily"],
    "周线": ["weekly"],
    "月线": ["monthly"],
    "复权": ["adj_factor"],
    "财务": ["income", "balancesheet", "cashflow", "fina_indicator"],
    "利润表": ["income"],
    "资产负债": ["balancesheet"],
    "现金流": ["cashflow"],
    "审计": ["fina_audit"],
    "分红": ["dividend"],
    "资金流": ["moneyflow", "moneyflow_ths", "moneyflow_dc"],
    "融资融券": ["margin", "margin_detail"],
    "龙虎榜": ["top_list", "top_inst"],
    "涨停": ["limit_list_d", "stk_limit"],
    "连板": ["limit_step"],
    "板块": ["ths_index", "ths_member", "dc_index", "dc_member", "tdx_index", "tdx_member"],
    "概念": ["ths_index", "ths_member", "dc_index", "dc_member"],
    "行业": ["ths_index", "ths_daily"],
    "指数": ["ths_daily", "dc_daily", "tdx_daily"],
    "港股通": ["ggt_daily", "ggt_monthly", "ggt_top10", "hsgt_top10"],
    "持股": ["hk_hold", "ccass_hold", "ccass_hold_detail"],
    "机构调研": ["stk_surv"],
    "热榜": ["ths_hot", "dc_hot"],
}

# Keywords that usually imply out-of-scope or ambiguous requirement.
UNSUPPORTED_HINTS: Dict[str, str] = {
    "期权": "当前编排器默认股票策略，期权需要单独执行链路。",
    "期货": "当前编排器默认股票策略，期货需要单独执行链路。",
    "新闻情绪": "SDK_USER_API 文档未声明新闻情绪接口，需改为热榜/资金流代理指标或接入外部源。",
    "宏观": "SDK_USER_API 文档未声明宏观经济接口，需明确替代数据源。",
}


def list_runtime_apis() -> Set[str]:
    token = os.getenv("QGDATA_TOKEN", "")
    if not token:
        return set()
    try:
        import qgdata as qg  # type: ignore
        qg.set_token(token)
        pro = qg.pro_api(timeout=10.0)
        apis = pro.list_apis(enabled_only=True)
        if isinstance(apis, list):
            return {str(x) for x in apis}
        if isinstance(apis, dict):
            return {str(k) for k in apis.keys()}
    except Exception:
        return set()
    return set()


@dataclass
class CapabilityResult:
    ok: bool
    status: str
    required_apis: List[str]
    missing_apis: List[str]
    matched_rules: List[str]
    unsupported_reasons: List[str]
    suggestion: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "required_apis": self.required_apis,
            "missing_apis": self.missing_apis,
            "matched_rules": self.matched_rules,
            "unsupported_reasons": self.unsupported_reasons,
            "suggestion": self.suggestion,
        }


def evaluate_requirement(requirement: str) -> CapabilityResult:
    text = requirement.lower()
    required: Set[str] = set()
    matched_rules: List[str] = []
    for keyword, apis in KEYWORD_API_RULES.items():
        if keyword.lower() in text:
            required.update(apis)
            matched_rules.append(keyword)

    unsupported: List[str] = []
    for keyword, reason in UNSUPPORTED_HINTS.items():
        if keyword.lower() in text:
            unsupported.append(f"{keyword}: {reason}")

    runtime_apis = list_runtime_apis()
    available = runtime_apis if runtime_apis else DOCUMENTED_APIS
    missing = sorted(api for api in required if api not in available)

    if unsupported:
        return CapabilityResult(
            ok=False,
            status="unsupported",
            required_apis=sorted(required),
            missing_apis=missing,
            matched_rules=matched_rules,
            unsupported_reasons=unsupported,
            suggestion="请先改写需求为股票+文档内可用数据接口，或扩展数据源后再执行。",
        )

    if missing:
        return CapabilityResult(
            ok=False,
            status="clarification_needed",
            required_apis=sorted(required),
            missing_apis=missing,
            matched_rules=matched_rules,
            unsupported_reasons=[],
            suggestion="当前需求依赖的部分数据接口不可用。请调整需求，或先启用缺失接口。",
        )

    return CapabilityResult(
        ok=True,
        status="ok",
        required_apis=sorted(required),
        missing_apis=[],
        matched_rules=matched_rules,
        unsupported_reasons=[],
        suggestion="数据能力检查通过，可启动编排。",
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="QGData capability preflight")
    parser.add_argument("--requirement", required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate_requirement(args.requirement).to_dict(), ensure_ascii=False, indent=2))
