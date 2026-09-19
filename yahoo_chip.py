"""Yahoo Taiwan public chip snapshot reader for the standalone app."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd
import requests


YAHOO_TW_QUOTE = "https://tw.finance.yahoo.com/quote"
YAHOO_TW_QUOTE_FALLBACK = "https://tw.stock.yahoo.com/quote"
YAHOO_HEADERS = {"User-Agent": "Mozilla/5.0 (Stock Strength Alert public-data reader)"}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) else None


def _safe_symbol(symbol: str) -> str | None:
    value = str(symbol or "").strip()
    return value if re.fullmatch(r"[A-Za-z0-9.^-]+", value) else None


def _date_text(value: Any) -> str:
    text = str(value or "")
    if "T" in text:
        return text[:10]
    return text.replace("/", "-")


def _latest(rows: Any, date_key: str = "date") -> dict[str, Any]:
    if not isinstance(rows, list):
        return {}
    valid = [row for row in rows if isinstance(row, dict)]
    valid.sort(key=lambda row: str(row.get(date_key) or row.get("fullDate") or ""))
    return valid[-1] if valid else {}


def _json_fragment(html: str, marker: str) -> Any | None:
    start = html.find(marker)
    if start < 0:
        return None
    object_begin = html.find("{", start + len(marker))
    list_begin = html.find("[", start + len(marker))
    candidates = [position for position in (object_begin, list_begin) if position >= 0]
    begin = min(candidates) if candidates else -1
    if begin < 0:
        return None
    opening = html[begin]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for index in range(begin, len(html)):
        char = html[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[begin:index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _first_matching_object(html: str, pattern: str) -> Any | None:
    match = re.search(pattern, html)
    return _json_fragment(html, match.group(0)) if match else None


def _empty(reason: str, errors: list[str] | None = None) -> dict[str, Any]:
    return {
        "available": False,
        "source": "未提供",
        "as_of": "",
        "direction": "unknown",
        "large_holder_change": None,
        "retail_holder_change": None,
        "foreign_net": None,
        "institutional_net": None,
        "broker_net": None,
        "margin_change": None,
        "margin_balance": None,
        "short_balance": None,
        "large_holder_percent": None,
        "large_holder_count": None,
        "foreign_holder_percent": None,
        "foreign_holder_change": None,
        "institutional_detail": {},
        "broker_detail": {},
        "margin_detail": {},
        "holder_detail": {},
        "evidence": [],
        "source_urls": [],
        "fetch_errors": list(errors or []),
        "reason": reason,
    }


def _parse_pages(pages: dict[str, str], symbol: str) -> dict[str, Any]:
    result: dict[str, Any] = {"source": "Yahoo股市公開籌碼頁", "source_urls": []}

    institutional_state = _json_fragment(
        pages.get("institutional-trading", ""),
        f'"institutionBuySell-100-day-{symbol}":',
    )
    institutional_data = institutional_state.get("data", {}) if isinstance(institutional_state, dict) else {}
    latest = _latest(institutional_data.get("trades"))
    if latest:
        result.update({
            "as_of": _date_text(latest.get("date") or latest.get("formattedDate")),
            "foreign_net": latest.get("foreignDiffVolK"),
            "institutional_net": latest.get("totalDiffVolK"),
            "institutional_detail": {
                "date": _date_text(latest.get("date") or latest.get("formattedDate")),
                "foreign_net": latest.get("foreignDiffVolK"),
                "investment_trust_net": latest.get("investmentTrustDiffVolK"),
                "dealer_net": latest.get("dealerDiffVolK"),
                "total_net": latest.get("totalDiffVolK"),
            },
        })
        result["source_urls"].append(f"{YAHOO_TW_QUOTE}/{symbol}/institutional-trading")

    broker_data = _first_matching_object(pages.get("broker-trading", ""), r'"brokerTrades":\{"data":')
    if isinstance(broker_data, dict) and (broker_data.get("date") or broker_data.get("totalDifferenceVolK") is not None):
        result["broker_net"] = broker_data.get("totalDifferenceVolK")
        result["broker_detail"] = {"date": _date_text(broker_data.get("date")), "net": broker_data.get("totalDifferenceVolK")}
        result["as_of"] = result.get("as_of") or _date_text(broker_data.get("date"))
        result["source_urls"].append(f"{YAHOO_TW_QUOTE}/{symbol}/broker-trading")

    margin_data = _first_matching_object(pages.get("margin", ""), r'"marginSummary-[^"]+":\{"data":')
    margin_latest = _latest(margin_data.get("list")) if isinstance(margin_data, dict) else {}
    if margin_latest:
        result.update({
            "margin_change": margin_latest.get("financingDiffK"),
            "margin_balance": margin_latest.get("financingTotalVolK"),
            "short_balance": margin_latest.get("shortTotalVolK"),
            "margin_detail": {
                "date": _date_text(margin_latest.get("date")),
                "financing_change": margin_latest.get("financingDiffK"),
                "financing_balance": margin_latest.get("financingTotalVolK"),
                "short_balance": margin_latest.get("shortTotalVolK"),
            },
        })
        result["as_of"] = result.get("as_of") or _date_text(margin_latest.get("date"))
        result["source_urls"].append(f"{YAHOO_TW_QUOTE}/{symbol}/margin")

    holders_state = _first_matching_object(pages.get("major-holders", ""), r'"majorHolders":\{"data":\{"list":')
    holder_rows = [row for row in (holders_state if isinstance(holders_state, list) else []) if isinstance(row, dict)]
    holder_rows.sort(key=lambda row: str(row.get("endDate") or ""), reverse=True)
    if holder_rows:
        latest_holder = holder_rows[0]
        percentage_rows = [row for row in holder_rows if _number(row.get("mainHoldPercent")) is not None]
        holder_change = None
        if len(percentage_rows) >= 2:
            holder_change = _number(percentage_rows[0].get("mainHoldPercent")) - _number(percentage_rows[1].get("mainHoldPercent"))
        result.update({
            "large_holder_percent": latest_holder.get("mainHoldPercent") if _number(latest_holder.get("mainHoldPercent")) is not None else None,
            "large_holder_count": latest_holder.get("mainHolderCount"),
            "large_holder_change": holder_change,
            "foreign_holder_percent": latest_holder.get("foreignHoldPercent"),
            "holder_detail": {
                "latest_period": _date_text(latest_holder.get("endDate")),
                "large_holder_percent": latest_holder.get("mainHoldPercent"),
                "large_holder_count": latest_holder.get("mainHolderCount"),
                "large_holder_change": holder_change,
                "foreign_holder_percent": latest_holder.get("foreignHoldPercent"),
            },
        })
        result["source_urls"].append(f"{YAHOO_TW_QUOTE}/{symbol}/major-holders")

    return result


def fetch_yahoo_chip_flow(symbol: str, timeout: float = 8.0) -> dict[str, Any]:
    safe_symbol = _safe_symbol(symbol)
    if not safe_symbol:
        return _empty("股票代號格式不合法")
    pages: dict[str, str] = {}
    errors: list[str] = []
    markers = {
        "institutional-trading": f'"institutionBuySell-100-day-{safe_symbol}":',
        "broker-trading": '"brokerTrades":{"data":',
        "margin": '"marginSummary-',
        "major-holders": '"majorHolders":{"data":{"list":',
    }

    def fetch_page(page: str) -> tuple[str, str | None, list[str]]:
        page_errors: list[str] = []
        for base_url in (YAHOO_TW_QUOTE_FALLBACK, YAHOO_TW_QUOTE):
            try:
                response = requests.get(f"{base_url}/{safe_symbol}/{page}", headers=YAHOO_HEADERS, timeout=timeout)
                response.raise_for_status()
                content = response.text
                if markers[page] in content:
                    return page, content, page_errors
                page_errors.append(f"{base_url.split('//', 1)[1].split('/', 1)[0]}:missing-state")
            except requests.RequestException as exc:
                page_errors.append(f"{base_url.split('//', 1)[1].split('/', 1)[0]}:{type(exc).__name__}")
        return page, None, page_errors

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(fetch_page, page) for page in markers]
        for future in as_completed(futures):
            page, content, page_errors = future.result()
            if content is not None:
                pages[page] = content
            errors.extend(f"{page}:{error}" for error in page_errors)

    snapshot = _parse_pages(pages, safe_symbol)
    if errors:
        snapshot["fetch_errors"] = errors
    if not snapshot.get("source_urls"):
        return _empty("Yahoo 公開籌碼頁暫時無法取得", errors)
    return snapshot
