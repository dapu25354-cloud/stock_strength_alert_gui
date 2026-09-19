"""智伸科 4551 專用三層轉強提醒核心。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf


SYMBOL = "4551.TW"
NAME = "智伸科"
STOCKS = {
    "智伸科 4551": {"symbol": "4551.TW", "name": "智伸科"},
    "台達電 2308": {"symbol": "2308.TW", "name": "台達電"},
    "緯穎 6669": {"symbol": "6669.TW", "name": "緯穎"},
    "大立光 3008": {"symbol": "3008.TW", "name": "大立光"},
    "日月光投控 3711": {"symbol": "3711.TW", "name": "日月光投控"},
    "聯鈞 3450": {"symbol": "3450.TW", "name": "聯鈞"},
    "順達 3211": {"symbol": "3211.TWO", "name": "順達"},
    "世禾 3551": {"symbol": "3551.TWO", "name": "世禾"},
    "均華 6640": {"symbol": "6640.TWO", "name": "均華"},
    "研華 2395": {"symbol": "2395.TW", "name": "研華"},
    "緯創 3231": {"symbol": "3231.TW", "name": "緯創"},
    "世界先進 5347": {"symbol": "5347.TWO", "name": "世界先進"},
    "統一超 2912": {"symbol": "2912.TW", "name": "統一超"},
    "長榮航 2618": {"symbol": "2618.TW", "name": "長榮航"},
    "是方 6561": {"symbol": "6561.TWO", "name": "是方", "observation_only": True},
}
APP_ROOT = Path(__file__).resolve().parent
LEGACY_SCRIPTS = APP_ROOT.parent / "levels_app" / "scripts"

try:
    if LEGACY_SCRIPTS.exists() and str(LEGACY_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(LEGACY_SCRIPTS))
    import market_flow as _legacy_market_flow
except Exception:
    _legacy_market_flow = None


def normalise_history(data: pd.DataFrame, min_rows: int = 20) -> pd.DataFrame:
    """保留日 K 必要欄位並清除未完成資料。"""
    if data is None or data.empty:
        raise ValueError("沒有可用的智伸科日 K 資料")
    frame = data.copy()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [column[0] for column in frame.columns]
    rename = {str(column).lower(): column for column in frame.columns}
    required = {name: rename.get(name.lower()) for name in ("Open", "High", "Low", "Close", "Volume")}
    if any(value is None for value in required.values()):
        raise ValueError("日 K 缺少 OHLCV 欄位")
    frame = frame[[required[name] for name in required]].copy()
    frame.columns = list(required)
    index = pd.to_datetime(frame.index)
    frame.index = index.tz_localize(None) if getattr(index, "tz", None) is not None else index
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["High", "Low", "Close", "Volume"])
    frame = frame[(frame["Close"] > 0) & (frame["High"] >= frame["Low"])]
    if len(frame) < min_rows:
        raise ValueError(f"日 K 筆數不足，至少需要 {min_rows} 個交易日")
    return frame


def _with_features(data: pd.DataFrame) -> pd.DataFrame:
    frame = normalise_history(data)
    previous_close = frame["Close"].shift(1)
    true_range = pd.concat(
        [frame["High"] - frame["Low"], (frame["High"] - previous_close).abs(), (frame["Low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    frame["ATR"] = true_range.rolling(14, min_periods=7).mean()
    frame["atr_pct"] = (frame["ATR"] / frame["Close"]).replace([float("inf"), -float("inf")], pd.NA)
    frame["volume_base"] = frame["Volume"].rolling(20, min_periods=10).median()
    frame["volume_ratio"] = (frame["Volume"] / frame["volume_base"]).replace([float("inf"), -float("inf")], pd.NA)
    span = (frame["High"] - frame["Low"]).replace(0, pd.NA)
    frame["close_location"] = ((frame["Close"] - frame["Low"]) / span).fillna(0.5)
    frame["change"] = frame["Close"].pct_change()
    frame["flow_score"] = frame["change"].fillna(0) * frame["volume_ratio"].fillna(1)
    return frame


def learn_profile(data: pd.DataFrame, prepared: bool = False) -> dict[str, Any]:
    """從智伸科自己的歷史資料學出窗口與量價門檻。"""
    frame = data if prepared else _with_features(data)
    ratios = frame["volume_ratio"].dropna()
    down_ratios = frame.loc[frame["change"] < 0, "volume_ratio"].dropna()
    up_ratios = frame.loc[frame["change"] > 0, "volume_ratio"].dropna()
    close_locations = frame.loc[frame["change"] >= 0, "close_location"].dropna()
    positive_flow = frame.loc[frame["flow_score"] > 0, "flow_score"].abs().dropna()

    local_low = frame["Close"].eq(frame["Close"].rolling(5, center=True, min_periods=3).min())
    local_high = frame["Close"].eq(frame["Close"].rolling(5, center=True, min_periods=3).max())
    pivot_dates = frame.index[local_low | local_high]
    intervals = pivot_dates.to_series().diff().dt.days.dropna() / 1.4
    typical_cycle = float(intervals.median()) if not intervals.empty else 14.0
    floor_window = int(max(8, min(25, round(typical_cycle))))
    rebound_window = int(max(15, min(45, round(typical_cycle * 1.6))))

    def quantile(series: pd.Series, value: float, fallback: float) -> float:
        return float(series.quantile(value)) if len(series) >= 8 else fallback

    typical_atr_pct = quantile(frame["atr_pct"].dropna(), 0.5, 0.025)
    return {
        "floor_window": floor_window,
        "rebound_window": rebound_window,
        "shrink_volume": quantile(down_ratios, 0.40, quantile(ratios, 0.35, 0.80)),
        "expand_volume": quantile(up_ratios, 0.72, quantile(ratios, 0.72, 1.25)),
        "close_recovery": quantile(close_locations, 0.60, 0.60),
        "flow_threshold": quantile(positive_flow, 0.55, 0.25),
        "typical_atr_pct": typical_atr_pct,
        "sample_days": len(frame),
    }


def _chip_state(chip_data: dict[str, Any] | None) -> dict[str, Any]:
    if not chip_data:
        return {"available": False, "direction": "unknown", "label": "籌碼資料缺口"}
    if _legacy_market_flow is not None:
        try:
            result = _legacy_market_flow.normalise_chip_flow(chip_data)
            institutional = result.get("institutional_net")
            foreign = result.get("foreign_net")
            directional_values = [float(value) for value in (institutional, foreign) if value is not None]
            if result.get("direction") == "unknown" and directional_values:
                if all(value > 0 for value in directional_values):
                    result["direction"] = "inflow"
                elif all(value < 0 for value in directional_values):
                    result["direction"] = "outflow"
                else:
                    result["direction"] = "mixed"
            source = str(chip_data.get("source") or result.get("source") or "外部籌碼快照")
            facts = []
            if foreign is not None:
                facts.append(f"外資{'買超' if float(foreign) > 0 else '賣超'} {abs(float(foreign)):g} 張")
            if institutional is not None:
                facts.append(f"法人合計{'買超' if float(institutional) > 0 else '賣超'} {abs(float(institutional)):g} 張")
            large_percent = chip_data.get("large_holder_percent")
            retail_percent = chip_data.get("retail_holder_percent")
            institutional_percent = chip_data.get("institutional_holder_percent")
            if large_percent is not None:
                result["large_holder_percent"] = float(large_percent)
                facts.append(f"大戶持股 {float(large_percent):.2f}%")
            if retail_percent is not None:
                result["retail_holder_percent"] = float(retail_percent)
                facts.append(f"散戶持股 {float(retail_percent):.2f}%")
            if institutional_percent is not None:
                result["institutional_holder_percent"] = float(institutional_percent)
                facts.append(f"法人持股 {float(institutional_percent):.2f}%")
            large_trend = str(chip_data.get("large_holder_trend") or "").lower()
            retail_holder_trend = str(chip_data.get("retail_holder_trend") or "").lower()
            institutional_trend = str(chip_data.get("institutional_trend") or "").lower()
            foreign_trend = str(chip_data.get("foreign_trend") or "").lower()
            broker_trend = str(chip_data.get("broker_trend") or "").lower()
            retail_trend = str(chip_data.get("retail_trend") or "").lower()
            result["large_holder_trend"] = large_trend
            result["retail_holder_trend"] = retail_holder_trend
            result["institutional_trend"] = institutional_trend
            result["foreign_trend"] = foreign_trend
            result["broker_trend"] = broker_trend
            result["retail_trend"] = retail_trend
            for field in ("broker_net", "retail_net"):
                if chip_data.get(field) is not None:
                    result[field] = float(chip_data[field])
            if large_trend == "down" and retail_holder_trend == "up":
                result["holder_trend_direction"] = "outflow"
                facts.append("大戶趨勢向下、散戶趨勢向上")
            elif large_trend == "up" and retail_holder_trend == "down":
                result["holder_trend_direction"] = "inflow"
                facts.append("大戶趨勢向上、散戶趨勢向下")
            else:
                result["holder_trend_direction"] = "unknown"
            if institutional_trend == "down" and foreign_trend == "down":
                result["institutional_trend_direction"] = "outflow"
                facts.append("三大法人與外資趨勢向下")
            elif institutional_trend == "up" and foreign_trend == "up":
                result["institutional_trend_direction"] = "inflow"
                facts.append("三大法人與外資趨勢向上")
            else:
                result["institutional_trend_direction"] = "unknown"
            if result["institutional_trend_direction"] == "outflow":
                result["holder_trend_direction"] = "outflow"
            if broker_trend == "down" and retail_trend == "up":
                result["holder_trend_direction"] = "outflow"
                facts.append("主力趨勢向下、散戶買盤累積")
            if chip_data.get("broker_net") is not None:
                facts.append(f"主力{'買超' if float(chip_data['broker_net']) > 0 else '賣超'} {abs(float(chip_data['broker_net'])):g} 張")
            if chip_data.get("retail_net") is not None:
                facts.append(f"散戶{'買超' if float(chip_data['retail_net']) > 0 else '賣超'} {abs(float(chip_data['retail_net'])):g} 張")
            if facts:
                result["label"] = f"{source}；{'、'.join(facts)}。四類趨勢方向已取得，未另列逐日差分數字。"
            result["partial"] = not all((large_trend, retail_holder_trend, institutional_trend, foreign_trend))
            return result
        except Exception:
            pass
    institutional = chip_data.get("institutional_net")
    foreign = chip_data.get("foreign_net")
    value = institutional if institutional is not None else foreign
    if value is not None:
        number = float(value)
        direction = "inflow" if number > 0 else "outflow" if number < 0 else "flat"
        return {"available": True, "direction": direction, "partial": True, "holder_trend_direction": "unknown", "label": f"法人淨額 {number:g} 張；大戶／散戶趨勢未提供"}
    return {"available": False, "direction": "unknown", "label": "籌碼資料缺口"}


def _score_latest(data: pd.DataFrame, profile: dict[str, Any], chip_data: dict[str, Any] | None = None, prepared: bool = False) -> dict[str, Any]:
    frame = data if prepared else _with_features(data)
    index = len(frame) - 1
    row = frame.iloc[index]
    atr = float(row["ATR"]) if pd.notna(row["ATR"]) and row["ATR"] > 0 else float(row["Close"]) * profile["typical_atr_pct"]
    floor_window = min(profile["floor_window"], max(5, index - 3))
    rebound_window = min(profile["rebound_window"], max(8, index - 3))
    prior_floor = float(frame["Low"].iloc[max(0, index - floor_window):index].min())
    recent_low = float(frame["Low"].iloc[max(0, index - 4):index + 1].min())
    resistance = float(frame["High"].iloc[max(0, index - rebound_window):index].max())
    previous_resistance = float(frame["High"].iloc[max(0, index - rebound_window - 1):index - 1].max()) if index > rebound_window else resistance
    recent_lows = frame["Low"].iloc[max(0, index - 2):index + 1]
    recent_ratios = frame["volume_ratio"].iloc[max(0, index - 4):index + 1].dropna()
    recent_changes = frame["change"].iloc[max(0, index - 4):index + 1]
    down_ratios = frame.loc[recent_changes[recent_changes < 0].index, "volume_ratio"].dropna()
    up_ratios = frame.loc[recent_changes[recent_changes > 0].index, "volume_ratio"].dropna()
    down_volume = float(down_ratios.mean()) if not down_ratios.empty else float(recent_ratios.mean())
    up_volume = float(up_ratios.mean()) if not up_ratios.empty else float(recent_ratios.mean())
    flow_window = frame["flow_score"].iloc[max(0, index - 4):index + 1].dropna()
    flow_score = float(flow_window.sum()) if not flow_window.empty else 0.0
    no_new_low = recent_low >= prior_floor - 0.35 * atr
    recovered_close = float(row["close_location"]) >= profile["close_recovery"]
    volume_relief = down_volume <= profile["shrink_volume"]
    higher_low = float(recent_lows.iloc[-1]) >= float(recent_lows.iloc[0]) + 0.10 * atr or recent_lows.is_monotonic_increasing
    buyer_volume = up_volume >= profile["expand_volume"] or flow_score >= profile["flow_threshold"]
    quiet_pullback = float(recent_ratios.tail(2).mean()) <= profile["shrink_volume"] if len(recent_ratios) >= 2 else False
    breakout_buffer = max(0.18 * atr, resistance * profile["typical_atr_pct"] * 0.25)
    breakout = float(row["Close"]) > resistance + breakout_buffer
    hold_line = float(row["Close"]) >= resistance - 0.15 * atr
    previous_hold = float(frame["Close"].iloc[index - 1]) >= previous_resistance - 0.15 * atr if index > 0 else False
    recent_mean = float(frame["Close"].iloc[max(0, index - 4):index + 1].mean())
    older_mean = float(frame["Close"].iloc[max(0, index - 9):max(1, index - 4)].mean())
    trend_up = recent_mean > older_mean
    price_breakout = breakout and hold_line and (previous_hold or float(row["Close"]) > resistance + 0.45 * breakout_buffer)
    chips = _chip_state(chip_data)
    daily_chip_inflow = chips.get("direction") in {"inflow", "strong_hands_inflow"}
    holder_trend_outflow = chips.get("holder_trend_direction") == "outflow"
    chip_inflow = daily_chip_inflow and not holder_trend_outflow
    chip_outflow = chips.get("direction") in {"outflow", "retail_inflow"} or holder_trend_outflow
    hard_breakdown = float(row["Close"]) < prior_floor - 0.50 * atr and not recovered_close

    layer1_score = int(no_new_low) + int(volume_relief) + int(recovered_close)
    layer2_score = int(higher_low) + int(buyer_volume) + int(quiet_pullback)
    price_confirmed = price_breakout and buyer_volume and trend_up and not chip_outflow
    if hard_breakdown:
        stage = 0
        label = "🔴 失敗／停加" if chip_outflow else "🔴 量價破壞／先停加"
    elif price_confirmed:
        stage = 3
        label = "🟢🟢 第3層｜轉強確認" if chips.get("available") and chip_inflow else "🟢🟢 第3層候選"
    elif layer2_score >= 2 and no_new_low:
        stage = 2
        if not chips.get("available"):
            label = "🟢 第2層｜量價回穩，可小試（籌碼尚未確認）"
        else:
            label = "🟢 第2層｜量價回穩，可小試（籌碼分歧）" if chip_outflow else "🟢 第2層｜資金回流，可小試"
    elif layer1_score >= 2:
        stage = 1
        label = "🟡 第1層｜止跌跡象"
    else:
        stage = 0
        label = "⚪ 尚未進入第1層（等待止跌或轉弱）"

    reasons = []
    if no_new_low:
        reasons.append("近期低點未再連續下破")
    if volume_relief:
        reasons.append(f"下跌量縮（{down_volume:.2f}×，個股門檻 {profile['shrink_volume']:.2f}×）")
    if recovered_close:
        reasons.append("殺低後收回日內低檔")
    if higher_low:
        reasons.append("低點墊高")
    if buyer_volume:
        reasons.append(f"上漲量價較強（{up_volume:.2f}×，個股放量門檻 {profile['expand_volume']:.2f}×）")
    if quiet_pullback:
        reasons.append("最近回檔量縮")
    if price_breakout:
        reasons.append(f"突破動態壓力 {resistance:.2f} 並暫時守住")
    if hard_breakdown:
        reasons.append("跌破動態支撐")
    if chip_inflow:
        reasons.append("可取得籌碼顯示資金回流")
    if daily_chip_inflow and holder_trend_outflow:
        reasons.append("法人當日買超，但大戶向下、散戶向上，籌碼趨勢仍偏外流")
    if chip_outflow:
        reasons.append("可取得籌碼顯示資金外流")
    if not chips.get("available"):
        reasons.append("籌碼資料缺口，未用量價推估冒充")

    moving_average_windows = (5, 10, 20, 60, 120, 240)
    moving_averages = {
        f"ma{window}": float(frame["Close"].rolling(window, min_periods=min(window, max(10, window // 2))).mean().iloc[-1])
        for window in moving_average_windows
    }
    valid_moving_averages = [value for value in moving_averages.values() if pd.notna(value)]
    if valid_moving_averages and all(float(row["Close"]) > value for value in valid_moving_averages):
        moving_average_state = "現價站上 5／10／20／60／120／240 日均線"
    elif valid_moving_averages and all(float(row["Close"]) < value for value in valid_moving_averages):
        moving_average_state = "現價低於 5／10／20／60／120／240 日均線"
    else:
        moving_average_state = "均線排列分歧"
    if moving_average_state.startswith("現價站上"):
        reasons.append(moving_average_state)

    return {
        "date": frame.index[-1].strftime("%Y-%m-%d"),
        "price": float(row["Close"]),
        "stage": stage,
        "label": label,
        "reasons": reasons,
        "chip": chips,
        "chip_confirmed": bool(chips.get("available") and chip_inflow),
        "chip_gap": not bool(chips.get("available")),
        "chip_partial": bool(chips.get("partial")),
        "support": prior_floor,
        "resistance": resistance,
        "atr": atr,
        "volume_ratio": float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else 1.0,
        "ma20": float(frame["Close"].rolling(20, min_periods=10).mean().iloc[-1]),
        "ma60": float(frame["Close"].rolling(60, min_periods=30).mean().iloc[-1]),
        "moving_averages": moving_averages,
        "moving_average_state": moving_average_state,
        "profile": profile,
        "checks": {
            "no_new_low": no_new_low,
            "volume_relief": volume_relief,
            "recovered_close": recovered_close,
            "higher_low": higher_low,
            "buyer_volume": buyer_volume,
            "quiet_pullback": quiet_pullback,
            "price_breakout": price_breakout,
            "hard_breakdown": hard_breakdown,
        },
    }


def analyse_history(data: pd.DataFrame, chip_data: dict[str, Any] | None = None) -> dict[str, Any]:
    frame = normalise_history(data)
    prepared = _with_features(frame)
    profile = learn_profile(frame)
    current = _score_latest(prepared, profile, chip_data, prepared=True)
    warmup = max(35, profile["rebound_window"] + 5)
    backtest_start = max(warmup, len(frame) - 420)
    events: list[dict[str, Any]] = []
    last_announced_stage = -1
    last_event_index = -100
    backtest_profile = None
    for index in range(backtest_start, len(frame)):
        prefix = prepared.iloc[: index + 1]
        if backtest_profile is None or (index - backtest_start) % 30 == 0:
            backtest_profile = learn_profile(prefix, prepared=True)
        day_profile = backtest_profile
        result = _score_latest(prefix, day_profile, prepared=True)
        stage = result["stage"]
        is_failure = stage == 0 and result["checks"]["hard_breakdown"]
        is_progression = stage in (1, 2, 3) and stage > last_announced_stage
        if (is_failure or is_progression) and index - last_event_index >= 7:
            events.append({
                "date": result["date"],
                "stage": stage,
                "label": result["label"],
                "price": result["price"],
                "reason": "；".join(result["reasons"][:3]),
                "chip": "回測未接入籌碼快照",
            })
            last_event_index = index
            last_announced_stage = stage if not is_failure else -1
    return {"current": current, "profile": profile, "events": events, "history": frame}


def action_guidance(current: dict[str, Any], observation_only: bool = False) -> str:
    """把訊號翻成空手與持股都看得懂的操作文字。"""
    if observation_only:
        return "空手進場：暫不進場，只觀察成交量是否回來、以及是否有效突破。\n持股操作：先不加碼；低流動性沒有量價確認前維持觀察。"
    stage = current["stage"]
    if stage >= 3 and current.get("chip_confirmed"):
        return "空手進場：可分批進場，不追高、不一次押滿。\n持股操作：核心持股續抱；機動倉可在突破站穩後分批加碼，跌破停損線就停損，不一路攤平。"
    if stage == 2:
        if current["price"] >= current["ma60"]:
            return "空手進場：只小量試單，不追價、不一次押滿。\n持股操作：核心持股先續抱；機動倉可以小量試加，但要先設停損，賭錯就停損、不一路攤平；突破確認與籌碼同步後，再分批加碼。"
        return "空手進場：先不要接刀，等站回季線再小量試單。\n持股操作：原有部位先續抱觀察，不攤平、不加碼；跌破動態支撐時，依停損／減碼計畫處理。"
    if stage == 1:
        return "空手進場：先觀察，不接下跌中的刀。\n持股操作：核心持股先續抱觀察；機動倉先不加，等低點墊高與資金確認。跌破動態支撐時，依停損／減碼計畫處理。"
    if current["checks"].get("hard_breakdown"):
        return "空手進場：不要接刀。\n持股操作：停止機動加碼；若跌破支撐且資金外流，先依停損／減碼計畫處理機動倉。"
    return "空手進場：先觀察，不急著買。\n持股操作：原有部位先續抱或觀察，不攤平、不加碼；等待更明確的轉強證據。"


def fetch_history(symbol: str = SYMBOL, period: str = "3y") -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    data = ticker.history(period=period, auto_adjust=False)
    return normalise_history(data, min_rows=80)


def fetch_chip_snapshot(symbol: str = SYMBOL, timeout: float = 6.0) -> dict[str, Any]:
    if _legacy_market_flow is None:
        return {"available": False, "reason": "未找到公開籌碼資料模組"}
    try:
        return _legacy_market_flow.fetch_yahoo_chip_flow(symbol, timeout=timeout)
    except Exception as exc:
        return {"available": False, "reason": f"公開籌碼讀取失敗（{type(exc).__name__}）"}


def merge_chip_snapshots(primary: dict[str, Any] | None, fallback: dict[str, Any] | None) -> dict[str, Any] | None:
    """合併籌碼快照；CMoney 使用者資料優先，Yahoo 公開資料只補缺口。"""
    if not primary:
        return fallback
    if not fallback:
        return primary
    merged = dict(fallback)
    merged.update({key: value for key, value in primary.items() if value not in (None, "")})
    primary_source = str(primary.get("source") or "")
    fallback_source = str(fallback.get("source") or "Yahoo 公開資料")
    if "CMoney" in primary_source:
        merged["source"] = primary_source
        merged["source_note"] = f"CMoney 優先；Yahoo 公開資料補充（{fallback_source}）"
    else:
        merged["source_note"] = f"Yahoo 公開資料（{fallback_source}）"
    return merged


def select_chip_snapshot(
    cached: dict[str, Any] | None,
    yahoo: dict[str, Any] | None,
    market_date: object | None = None,
) -> dict[str, Any] | None:
    """選擇目前籌碼來源；CMoney 當日快照優先，失效或缺席就用 Yahoo。"""
    cached_source = str((cached or {}).get("source") or "")
    is_cmoney = "CMoney" in cached_source
    target_date = pd.to_datetime(market_date, errors="coerce")
    cached_date = pd.to_datetime((cached or {}).get("as_of"), errors="coerce")
    cmoney_is_current = is_cmoney and pd.notna(target_date) and pd.notna(cached_date) and cached_date.date() >= target_date.date()
    yahoo_available = bool(yahoo and (yahoo.get("source_urls") or yahoo.get("foreign_net") is not None or yahoo.get("institutional_net") is not None))
    if cmoney_is_current:
        return merge_chip_snapshots(cached, yahoo)
    if yahoo_available:
        selected = dict(yahoo)
        if is_cmoney:
            selected["source_note"] = f"CMoney 快照日期 {cached.get('as_of') or '未標示'} 非目前交易日；本次改用 Yahoo 公開資料"
        return selected
    if cached:
        selected = dict(cached)
        if is_cmoney and pd.notna(cached_date) and pd.notna(target_date) and cached_date.date() < target_date.date():
            selected["source_note"] = "Yahoo 暫時無法取得；先沿用較早的 CMoney 快照，請勿視為今日籌碼"
        return selected
    return yahoo


def save_chip_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, default=str, indent=2), encoding="utf-8")


def load_chip_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None
