from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import core


APP_ROOT = Path(__file__).resolve().parent
CACHE_DIR = APP_ROOT / "cache"


st.set_page_config(page_title="Stock Strength Alert GUI", page_icon="📈", layout="centered")
st.markdown(
    """
    <style>
    .block-container { max-width: 900px; padding: 1.2rem 1rem 3rem; }
    .app-title { color: #17324d; font-size: 2rem; font-weight: 800; line-height: 1.2; margin-bottom: .2rem; }
    .signal-card { padding: 1rem 1.1rem; border-radius: 14px; background: #e8f0f7; margin: .8rem 0 1rem; }
    .signal-text { color: #17324d; font-size: 1.7rem; font-weight: 800; }
    .small-note { color: #506579; font-size: .92rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="app-title">個股三層轉強提醒</div>', unsafe_allow_html=True)
st.markdown('<div class="small-note">Yahoo 行情與公開籌碼每日更新；CMoney 當日快照若存在則優先使用。</div>', unsafe_allow_html=True)
st.info("記憶口訣：黃燈等、綠燈試、雙綠加、紅燈停；灰燈先觀察。")

stock_key = st.selectbox("選擇股票", list(core.STOCKS), key="stock_key")
stock = core.STOCKS[stock_key]
symbol = stock["symbol"]
prefix = symbol.split(".")[0]
history_path = CACHE_DIR / f"{prefix}_history.csv"
chip_path = CACHE_DIR / f"{prefix}_chip_snapshot.json"
update_meta_path = CACHE_DIR / f"{prefix}_update_meta.json"

if st.button("更新今日收盤＋Yahoo籌碼（每日一次）", type="primary", width="stretch"):
    already_updated = update_meta_path.exists() and datetime.now().strftime("%Y-%m-%d") in update_meta_path.read_text(encoding="utf-8")
    if already_updated:
        st.info("今天已更新過；直接使用下方快取分析即可。")
    else:
        try:
            with st.spinner("正在取得 Yahoo 行情與公開籌碼…"):
                history = core.fetch_history(symbol)
                cached_chip = core.load_chip_snapshot(chip_path)
                yahoo_chip = core.fetch_chip_snapshot(symbol)
                chip = core.select_chip_snapshot(cached_chip, yahoo_chip, history.index[-1])
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                history.to_csv(history_path, encoding="utf-8-sig")
                if chip is not None:
                    core.save_chip_snapshot(chip_path, chip)
                update_meta_path.write_text(json.dumps({"last_update_date": datetime.now().strftime("%Y-%m-%d")}), encoding="utf-8")
            st.success(f"{stock['name']} 已更新：{history.index[-1].date()}")
        except Exception as exc:
            st.error(f"更新失敗：{type(exc).__name__}。可先使用既有快取。")

if not history_path.exists():
    st.warning("尚未有這檔股票的行情快取，請按上方更新按鈕。")
    st.stop()

try:
    history = core.normalise_history(pd.read_csv(history_path, index_col=0, parse_dates=True))
    chip = core.load_chip_snapshot(chip_path)
    analysis = core.analyse_history(history, chip)
except Exception as exc:
    st.error(f"分析失敗：{type(exc).__name__}。請重新更新行情。")
    st.stop()

current = analysis["current"]
st.markdown(f'<div class="signal-card"><div class="signal-text">{current["label"]}</div></div>', unsafe_allow_html=True)
st.write(
    f"資料日期：{current['date']}｜收盤：{current['price']:.2f}｜{current['moving_average_state']}｜"
    f"月線：{current['ma20']:.2f}｜季線：{current['ma60']:.2f}"
)

metric_cols = st.columns(4)
for column, label, value in zip(
    metric_cols,
    ("動態支撐", "動態壓力", "量比", "ATR"),
    (f"{current['support']:.2f}", f"{current['resistance']:.2f}", f"{current['volume_ratio']:.2f}×", f"{current['atr']:.2f}"),
):
    column.metric(label, value)

st.subheader("你現在怎麼做")
st.code(core.action_guidance(current, observation_only=stock.get("observation_only", False)), language=None)

st.subheader("判斷依據")
for reason in current["reasons"]:
    st.write(f"• {reason}")

st.subheader("資料狀態")
chip_state = current["chip"]
st.write(f"來源：{chip_state.get('source', '籌碼資料缺口')}｜日期：{chip_state.get('as_of', current['date'])}")
st.write(f"外資：{chip_state.get('foreign_net', '—')} 張｜持股：{chip_state.get('foreign_holder_percent', '—')}%｜趨勢：{chip_state.get('foreign_trend', '未提供')}")
st.write(f"三大法人：{chip_state.get('institutional_net', '—')} 張｜持股：{chip_state.get('institutional_holder_percent', '—')}%｜趨勢：{chip_state.get('institutional_trend', '未提供')}")
st.write(f"大戶：{chip_state.get('large_holder_percent', '—')}%｜趨勢：{chip_state.get('large_holder_trend', '未提供')}")
st.write(f"散戶：{chip_state.get('retail_holder_percent', '—')}%｜趨勢：{chip_state.get('retail_holder_trend', '未提供')}")
if chip_state.get("source_note"):
    st.caption(chip_state["source_note"])

with st.expander("歷史回測案例"):
    if analysis["events"]:
        rows = [{"日期": item["date"], "燈號": item["label"], "價格": round(item["price"], 2), "依據": item["reason"]} for item in analysis["events"]]
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.write("目前沒有足夠案例。")

st.caption("提醒：這是分段觀察工具，不是投資保證；沒有的籌碼資料不會用成交量冒充。")
