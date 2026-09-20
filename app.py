from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import core


APP_ROOT = Path(__file__).resolve().parent
CACHE_DIR = APP_ROOT / "cache"
UPDATE_SCHEMA_VERSION = "2"
STOCK_KEYS = list(core.STOCKS)


st.set_page_config(page_title="Stock Strength Alert GUI", page_icon="📈", layout="centered")
st.markdown(
    """
    <style>
    .block-container { max-width: 900px; padding: 1rem .8rem 2.5rem; }
    h1, h2, h3 { font-size: 1.08rem !important; line-height: 1 !important; margin-top: .8rem !important; }
    .stApp p, .stApp li, .stApp label, .stApp button, .stApp [data-testid="stMarkdownContainer"], .stAlert, .stAlert p, [data-testid="stCaptionContainer"] { line-height: 1 !important; }
    .small-note { color: #506579; font-size: .92rem; line-height: 1 !important; }
    .signal-card { padding: .7rem .8rem; border-radius: 12px; margin: .65rem 0 .8rem; border-left: 6px solid; }
    .signal-text { font-size: 1rem; font-weight: 800; line-height: 1 !important; }
    .signal-yellow { background: #fff8dc; border-color: #d9a400; color: #765800; }
    .signal-green { background: #eaf7ed; border-color: #2f9e5b; color: #176b38; }
    .signal-double-green { background: #dff5e7; border-color: #168448; color: #0d5c30; }
    .signal-red { background: #fdeaea; border-color: #c43d4b; color: #8c1f2d; }
    .signal-neutral { background: #f0eef7; border-color: #8276a8; color: #51476f; }
    </style>
    """,
    unsafe_allow_html=True,
)


def cache_paths(symbol: str) -> tuple[Path, Path, Path]:
    prefix = symbol.split(".")[0]
    return (
        CACHE_DIR / f"{prefix}_history.csv",
        CACHE_DIR / f"{prefix}_chip_snapshot.json",
        CACHE_DIR / f"{prefix}_update_meta.json",
    )


def was_updated_today(meta_path: Path) -> bool:
    if not meta_path.exists():
        return False
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        metadata.get("last_update_date") == datetime.now().strftime("%Y-%m-%d")
        and metadata.get("schema_version") == UPDATE_SCHEMA_VERSION
    )


def update_stock(stock_key: str, force: bool = False) -> tuple[bool, str]:
    stock = core.STOCKS[stock_key]
    history_path, chip_path, update_meta_path = cache_paths(stock["symbol"])
    if not force and was_updated_today(update_meta_path):
        return True, "今日已更新"
    try:
        history = core.fetch_history(stock["symbol"])
        cached_chip = core.load_chip_snapshot(chip_path)
        yahoo_chip = core.fetch_chip_snapshot(stock["symbol"])
        chip = core.select_chip_snapshot(cached_chip, yahoo_chip, history.index[-1])
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        history.to_csv(history_path, encoding="utf-8-sig")
        if chip is not None:
            core.save_chip_snapshot(chip_path, chip)
        update_meta_path.write_text(
            json.dumps(
                {
                    "last_update_date": datetime.now().strftime("%Y-%m-%d"),
                    "schema_version": UPDATE_SCHEMA_VERSION,
                }
            ),
            encoding="utf-8",
        )
        return True, str(history.index[-1].date())
    except Exception as exc:
        return False, f"{type(exc).__name__}"


def load_analysis(stock_key: str, include_events: bool = False) -> dict | None:
    stock = core.STOCKS[stock_key]
    history_path, chip_path, _ = cache_paths(stock["symbol"])
    if not history_path.exists():
        return None
    try:
        history = core.normalise_history(pd.read_csv(history_path, index_col=0, parse_dates=True))
        chip = core.load_chip_snapshot(chip_path)
        return core.analyse_history(history, chip, include_events=include_events)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def signal_group(label: str) -> str:
    if label.startswith("🟢🟢"):
        return "🟢🟢 第3層"
    if label.startswith("🟢"):
        return "🟢 第2層"
    if label.startswith("🟡"):
        return "🟡 第1層"
    if label.startswith("🔴"):
        return "🔴 判斷失敗"
    return "⚪ 尚未進入第1層"


def render_signal(current: dict) -> None:
    label = current["label"]
    if label.startswith("🟢🟢"):
        signal_class = "signal-double-green"
    elif label.startswith("🟢"):
        signal_class = "signal-green"
    elif label.startswith("🟡"):
        signal_class = "signal-yellow"
    elif label.startswith("🔴"):
        signal_class = "signal-red"
    else:
        signal_class = "signal-neutral"
    st.markdown(
        f'<div class="signal-card {signal_class}"><div class="signal-text">{label}</div></div>',
        unsafe_allow_html=True,
    )


def render_detail(stock_key: str, analysis: dict) -> None:
    stock = core.STOCKS[stock_key]
    current = analysis["current"]
    st.markdown(f"### {stock['name']} {stock['symbol'].split('.')[0]}")
    render_signal(current)
    st.write(
        f"資料日期：{current['date']}｜收盤：{current['price']:.2f}｜{current['moving_average_state']}｜"
        f"月線：{current['ma20']:.2f}｜季線：{current['ma60']:.2f}"
    )

    metric_cols = st.columns(4)
    for column, label, value in zip(
        metric_cols,
        ("動態支撐", "動態壓力", "量比", "ATR"),
        (
            f"{current['support']:.2f}",
            f"{current['resistance']:.2f}",
            f"{current['volume_ratio']:.2f}×",
            f"{current['atr']:.2f}",
        ),
    ):
        column.metric(label, value)

    st.subheader("你現在怎麼做")
    st.info("目前名單皆按已持股判斷；請優先看「持股操作」那一行。")
    st.write(core.action_guidance(current, observation_only=stock.get("observation_only", False)))

    st.subheader("判斷依據")
    for reason in current["reasons"]:
        st.write(f"• {reason}")

    st.subheader("資料狀態")
    chip_state = current["chip"]
    st.write(f"來源：{chip_state.get('source', '籌碼資料缺口')}｜日期：{chip_state.get('as_of', current['date'])}")
    st.write(
        f"外資：{chip_state.get('foreign_net', '—')} 張｜持股：{chip_state.get('foreign_holder_percent', '—')}%｜"
        f"趨勢：{chip_state.get('foreign_trend', '未提供')}"
    )
    st.write(
        f"三大法人：{chip_state.get('institutional_net', '—')} 張｜持股：{chip_state.get('institutional_holder_percent', '—')}%｜"
        f"趨勢：{chip_state.get('institutional_trend', '未提供')}"
    )
    st.write(
        f"大戶：{chip_state.get('large_holder_percent', '—')}%｜趨勢：{chip_state.get('large_holder_trend', '未提供')}"
    )
    st.write(
        f"散戶：{chip_state.get('retail_holder_percent', '—')}%｜趨勢：{chip_state.get('retail_holder_trend', '未提供')}"
    )
    if chip_state.get("source_note"):
        st.caption(chip_state["source_note"])

    with st.expander("歷史回測案例"):
        if analysis["events"]:
            rows = [
                {"日期": item["date"], "燈號": item["label"], "價格": round(item["price"], 2), "依據": item["reason"]}
                for item in analysis["events"]
            ]
            st.dataframe(rows, hide_index=True, width="stretch")
        else:
            st.write("目前沒有足夠案例。")


st.title("個股三層轉強提醒")
st.markdown(
    '<div class="small-note">Yahoo 行情與公開籌碼每日更新；CMoney 當日快照若存在則優先使用。</div>',
    unsafe_allow_html=True,
)
st.info("記憶口訣：黃燈等、綠燈試、雙綠加、紅燈停；灰燈先觀察。")

view_mode = st.radio("頁面", ("個股分析", "持股總覽"), horizontal=True, key="view_mode")

if view_mode == "持股總覽":
    st.subheader("持股總覽")
    st.caption("首頁只看燈號與操作；要看均線、籌碼與回測，再進入個股詳情。")
    overview_rows: list[tuple[str, dict | None]] = [(stock_key, load_analysis(stock_key)) for stock_key in STOCK_KEYS]
    grouped: dict[str, list[tuple[str, dict | None]]] = {
        "🟡 第1層｜止跌跡象": [],
        "🟢 第2層｜量價回穩／資金開始接": [],
        "🟢🟢 第3層｜轉強確認": [],
        "⚪ 尚未進入第1層": [],
        "🔴 判斷失敗／停加": [],
        "⚪ 尚未更新": [],
    }
    for stock_key, analysis in overview_rows:
        stock = core.STOCKS[stock_key]
        current = analysis["current"] if analysis else None
        if current is None:
            grouped["⚪ 尚未更新"].append((stock_key, analysis))
            continue
        label = current["label"]
        if label.startswith("🟡"):
            group = "🟡 第1層｜止跌跡象"
        elif label.startswith("🟢🟢"):
            group = "🟢🟢 第3層｜轉強確認"
        elif label.startswith("🟢"):
            group = "🟢 第2層｜量價回穩／資金開始接"
        elif label.startswith("🔴"):
            group = "🔴 判斷失敗／停加"
        else:
            group = "⚪ 尚未進入第1層"
        grouped[group].append((stock_key, analysis))

    for group, entries in grouped.items():
        st.markdown(f"#### {group}")
        if not entries:
            st.caption("目前沒有持股在這一層。")
            continue
        for stock_key, analysis in entries:
            stock = core.STOCKS[stock_key]
            current = analysis["current"] if analysis else None
            if st.button(
                f"{stock['name']} {stock['symbol'].split('.')[0]}",
                key=f"open_{stock_key}",
                width="stretch",
            ):
                st.session_state["selected_stock"] = stock_key
                st.session_state["view_mode"] = "個股分析"
                st.rerun()
            if current is None:
                st.caption("尚未更新今日資料｜按名稱進入後可更新")
            else:
                guidance = core.action_guidance(current, observation_only=stock.get("observation_only", False))
                holding_line = next((line for line in guidance.splitlines() if line.startswith("持股操作：")), guidance)
                st.caption(f"收盤 {current['price']:.2f}｜{current['moving_average_state']}｜{holding_line}")
else:
    stock_menu_col, update_col = st.columns([1.65, 1], vertical_alignment="bottom")
    with stock_menu_col:
        selected_stock = st.selectbox("選擇股票", STOCK_KEYS, key="selected_stock")
    with update_col:
        update_clicked = st.button("更新今日", type="primary", width="stretch")
    stock = core.STOCKS[selected_stock]
    if update_clicked:
        with st.spinner("正在取得 Yahoo 行情與公開籌碼…"):
            success, message = update_stock(selected_stock, force=False)
        if success:
            st.success(f"{stock['name']}：{message}")
        else:
            st.error(f"更新失敗：{message}。可先使用既有快取。")
    analysis = load_analysis(selected_stock, include_events=True)
    if analysis is None:
        st.warning("尚未有這檔股票的行情快取，請按上方更新按鈕。")
    else:
        render_detail(selected_stock, analysis)

st.caption("提醒：這是分段觀察工具，不是投資保證；沒有的籌碼資料不會用成交量冒充。")
