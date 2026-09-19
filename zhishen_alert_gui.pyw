from __future__ import annotations

import os
import queue
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import pandas as pd

import core


APP_ROOT = Path(__file__).resolve().parent
CACHE_DIR = APP_ROOT / "cache"
STOCKS = core.STOCKS


class ZhishenApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.stock_key = "智伸科 4551"
        self.stock = STOCKS[self.stock_key]
        self.root.title(f"個股三層轉強提醒｜目前：{self.stock['name']} {self.stock['symbol'].split('.')[0]}")
        self.root.geometry("1020x760")
        self.root.minsize(760, 600)
        self.root.configure(bg="#f4f7fb")
        self.result_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.buttons: list[ttk.Button] = []
        self._build_ui()
        self._load_cache()
        self.root.after(150, self._poll_queue)

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Microsoft JhengHei UI", 21, "bold"), foreground="#17324d")
        style.configure("Sub.TLabel", font=("Microsoft JhengHei UI", 10), foreground="#506579")
        style.configure("Action.TButton", font=("Microsoft JhengHei UI", 11, "bold"), padding=(10, 7))
        style.configure("Treeview", rowheight=29, font=("Microsoft JhengHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft JhengHei UI", 10, "bold"))

        shell = ttk.Frame(self.root, padding=(22, 18, 22, 16))
        shell.pack(fill="both", expand=True)
        self.app_title_var = tk.StringVar(value=f"個股三層轉強提醒｜目前：{self.stock['name']} {self.stock['symbol'].split('.')[0]}")
        ttk.Label(shell, textvariable=self.app_title_var, style="Title.TLabel").pack(anchor="w")
        ttk.Label(shell, text="Yahoo 行情每日更新；CMoney 籌碼優先，Yahoo 公開籌碼只補缺口；開啟先讀快取。", style="Sub.TLabel").pack(anchor="w", pady=(3, 12))
        ttk.Label(shell, text="記憶口訣：黃燈等、綠燈試、雙綠加、紅燈停；灰燈先觀察。", style="Sub.TLabel").pack(anchor="w", pady=(0, 8))

        stock_bar = ttk.Frame(shell)
        stock_bar.pack(fill="x", pady=(0, 10))
        ttk.Label(stock_bar, text="選擇股票：", style="Sub.TLabel").pack(side="left", padx=(0, 6))
        self.stock_var = tk.StringVar(value=self.stock_key)
        self.stock_box = ttk.Combobox(stock_bar, textvariable=self.stock_var, values=list(STOCKS), state="readonly", width=22)
        self.stock_box.pack(side="left")
        self.stock_box.bind("<<ComboboxSelected>>", self._on_stock_changed)

        action_bar = ttk.Frame(shell)
        action_bar.pack(fill="x", pady=(0, 10))
        for text, command in (
            ("更新今日收盤＋Yahoo籌碼（每日一次）", lambda: self._start_refresh(True)),
            ("使用快取重新分析", self._load_cache),
            ("開啟快取資料夾", self._open_cache),
        ):
            button = ttk.Button(action_bar, text=text, command=command, style="Action.TButton")
            button.pack(side="left", padx=(0, 8))
            self.buttons.append(button)
        self.status_var = tk.StringVar(value="尚未載入資料；盤後可按『更新今日收盤＋Yahoo籌碼（每日一次）』。")
        ttk.Label(shell, textvariable=self.status_var, style="Sub.TLabel").pack(anchor="w", pady=(0, 8))

        notebook = ttk.Notebook(shell)
        notebook.pack(fill="both", expand=True)
        overview_tab = ttk.Frame(notebook, padding=12)
        backtest_tab = ttk.Frame(notebook, padding=12)
        notebook.add(overview_tab, text="目前燈號")
        notebook.add(backtest_tab, text="歷史回測案例")

        overview_canvas = tk.Canvas(overview_tab, highlightthickness=0, bg="#f4f7fb")
        overview_scrollbar = ttk.Scrollbar(overview_tab, orient="vertical", command=overview_canvas.yview)
        overview_canvas.configure(yscrollcommand=overview_scrollbar.set)
        overview_scrollbar.pack(side="right", fill="y")
        overview_canvas.pack(side="left", fill="both", expand=True)
        overview_content = ttk.Frame(overview_canvas, padding=4)
        overview_window = overview_canvas.create_window((0, 0), window=overview_content, anchor="nw")

        def update_overview_scrollregion(_event: object = None) -> None:
            overview_canvas.configure(scrollregion=overview_canvas.bbox("all"))

        def resize_overview_content(event: tk.Event) -> None:
            overview_canvas.itemconfigure(overview_window, width=event.width)

        overview_content.bind("<Configure>", update_overview_scrollregion)
        overview_canvas.bind("<Configure>", resize_overview_content)
        overview_tab = overview_content

        self.signal_frame = tk.Frame(overview_tab, bg="#dfe7ef", padx=18, pady=14)
        self.signal_frame.pack(fill="x", pady=(0, 12))
        self.signal_var = tk.StringVar(value="尚未分析")
        self.signal_detail_var = tk.StringVar(value="")
        self.signal_label = tk.Label(self.signal_frame, textvariable=self.signal_var, font=("Microsoft JhengHei UI", 24, "bold"), bg="#dfe7ef", fg="#17324d")
        self.signal_label.pack(anchor="w")
        self.signal_detail_label = tk.Label(self.signal_frame, textvariable=self.signal_detail_var, font=("Microsoft JhengHei UI", 11), bg="#dfe7ef", fg="#334e68", wraplength=900, justify="left")
        self.signal_detail_label.pack(anchor="w", pady=(7, 0))

        metric_frame = ttk.Frame(overview_tab)
        metric_frame.pack(fill="x", pady=(0, 10))
        self.metric_vars: dict[str, tk.StringVar] = {}
        metrics = (("date", "資料日期"), ("price", "收盤"), ("ma20", "月線 MA20"), ("ma60", "季線 MA60"), ("support", "動態支撐"), ("resistance", "動態壓力"), ("volume_ratio", "量比"), ("atr", "ATR"))
        for index, (key, label) in enumerate(metrics):
            row, column = divmod(index, 4)
            box = ttk.Frame(metric_frame, padding=(8, 8))
            box.grid(row=row, column=column, sticky="nsew")
            metric_frame.columnconfigure(column, weight=1)
            ttk.Label(box, text=label, style="Sub.TLabel").pack(anchor="w")
            variable = tk.StringVar(value="—")
            self.metric_vars[key] = variable
            ttk.Label(box, textvariable=variable, font=("Microsoft JhengHei UI", 14, "bold"), foreground="#17324d").pack(anchor="w", pady=(3, 0))

        self.reason_text = self._make_text(overview_tab, "判斷依據", height=5)
        self.action_text = self._make_text(overview_tab, "你現在怎麼做（目前全部按持股判斷）", height=5)
        self.chip_text = self._make_text(overview_tab, "資料狀態", height=8)
        ttk.Label(overview_tab, text="提醒：燈號是分段觀察工具，不是保證低點；籌碼資料缺口時不會用成交量冒充大戶／法人。", style="Sub.TLabel", wraplength=920).pack(anchor="w", pady=(9, 0))

        columns = ("date", "signal", "price", "reason", "chip")
        self.table = ttk.Treeview(backtest_tab, columns=columns, show="headings")
        headings = {"date": "日期", "signal": "燈號", "price": "價格", "reason": "當時依據", "chip": "籌碼狀態"}
        widths = {"date": 100, "signal": 160, "price": 80, "reason": 410, "chip": 180}
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(column, width=widths[column], anchor="w")
        scrollbar = ttk.Scrollbar(backtest_tab, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _make_text(self, parent: ttk.Frame, title: str, height: int = 4) -> tk.Text:
        ttk.Label(parent, text=title, font=("Microsoft JhengHei UI", 11, "bold"), foreground="#17324d").pack(anchor="w", pady=(4, 4))
        widget = tk.Text(parent, height=height, wrap="word", font=("Microsoft JhengHei UI", 10), bg="#ffffff", fg="#263746", relief="solid", borderwidth=1, padx=8, pady=6)
        widget.pack(fill="x", pady=(0, 6))
        widget.configure(state="disabled")
        return widget

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _load_cache(self) -> None:
        history_path, chip_path, update_meta_path = self._cache_paths()
        try:
            if not history_path.exists():
                self.status_var.set("尚未有行情快取；盤後按『更新今日收盤＋Yahoo籌碼（每日一次）』才會連線抓取。")
                return
            history = core.normalise_history(pd.read_csv(history_path, index_col=0, parse_dates=True))
            chip = core.load_chip_snapshot(chip_path)
            self._show_result(core.analyse_history(history, chip))
            status = f"已讀取本機快取：{history_path.name}｜{datetime.fromtimestamp(history_path.stat().st_mtime):%Y-%m-%d %H:%M}"
            if self._updated_today(update_meta_path):
                status += "｜今日已更新過，不會重複下載"
            self.status_var.set(status)
        except Exception as exc:
            self.status_var.set(f"快取讀取失敗：{type(exc).__name__}；請重新更新行情。")

    def _start_refresh(self, include_chip: bool) -> None:
        history_path, chip_path, update_meta_path = self._cache_paths()
        if self._updated_today(update_meta_path):
            self.status_var.set("今日收盤已更新過；本次不重複下載，請按『使用快取重新分析』即可。")
            return
        self._set_busy(True)
        mode = "行情＋Yahoo公開籌碼" if include_chip else "行情"
        self.status_var.set(f"正在更新{mode}，視窗仍可操作；完成後會自動顯示燈號。")

        def work() -> None:
            try:
                history = core.fetch_history(self.stock["symbol"])
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                history.to_csv(history_path, encoding="utf-8-sig")
                cached_chip = core.load_chip_snapshot(chip_path)
                yahoo_chip = core.fetch_chip_snapshot(self.stock["symbol"]) if include_chip else None
                chip = core.select_chip_snapshot(cached_chip, yahoo_chip, history.index[-1])
                if include_chip and chip is not None:
                    core.save_chip_snapshot(chip_path, chip)
                update_meta_path.write_text(
                    '{"last_update_date": "' + datetime.now().strftime("%Y-%m-%d") + '"}',
                    encoding="utf-8",
                )
                self.result_queue.put(("ok", (history, chip)))
            except Exception as exc:
                self.result_queue.put(("error", f"更新失敗：{type(exc).__name__}｜請稍後再試，或先使用既有快取。"))

        threading.Thread(target=work, daemon=True).start()

    def _poll_queue(self) -> None:
        try:
            status, payload = self.result_queue.get_nowait()
        except queue.Empty:
            self.root.after(150, self._poll_queue)
            return
        self._set_busy(False)
        if status == "ok":
            history, chip = payload
            self._show_result(core.analyse_history(history, chip))
            self.status_var.set(f"更新完成：{datetime.now():%Y-%m-%d %H:%M}｜今日不再重複下載，資料只存本機快取。")
        else:
            self.status_var.set(str(payload))
            messagebox.showwarning("智伸科提醒", str(payload))
        self.root.after(150, self._poll_queue)

    def _set_busy(self, busy: bool) -> None:
        for button in self.buttons:
            button.configure(state="disabled" if busy else "normal")

    def _show_result(self, analysis: dict) -> None:
        current = analysis["current"]
        stage_colors = {0: ("#ffe1e1", "#a51d2d"), 1: ("#fff3bf", "#8b6508"), 2: ("#d8f3dc", "#1b6e35"), 3: ("#c7f9cc", "#126b2f")}
        background, foreground = stage_colors.get(current["stage"], ("#dfe7ef", "#17324d"))
        self.signal_frame.configure(bg=background)
        self.signal_label.configure(bg=background, fg=foreground)
        self.signal_detail_label.configure(bg=background, fg=foreground)
        self.signal_var.set(current["label"])
        basis = "量價已確認"
        if current["chip_gap"]:
            basis += "｜籌碼尚未確認（資料缺口）"
        elif current["chip_confirmed"]:
            basis += "｜法人／外資同步確認"
            if current.get("chip_partial"):
                basis += "（精確差值未提供）"
        elif current["chip"].get("holder_trend_direction") == "outflow":
            basis += "｜大戶向下、散戶向上，籌碼趨勢偏外流"
        else:
            basis += "｜籌碼方向未形成同向確認"
        operation_note = ""
        if current["price"] < current["ma60"]:
            operation_note = f"｜現價低於季線 {current['ma60']:.2f}：已持股先不加碼，等站回季線；空手才適用小量試單"
        else:
            operation_note = f"｜現價在季線上方 {current['price'] - current['ma60']:.2f}"
        self.signal_detail_var.set(f"{current['date']}｜現價 {current['price']:.2f}｜{current['moving_average_state']}｜月線 {current['ma20']:.2f}｜季線 {current['ma60']:.2f}｜{basis}{operation_note}")
        self.metric_vars["date"].set(current["date"])
        self.metric_vars["price"].set(f"{current['price']:.2f}")
        self.metric_vars["ma20"].set(f"{current['ma20']:.2f}")
        self.metric_vars["ma60"].set(f"{current['ma60']:.2f}")
        self.metric_vars["support"].set(f"{current['support']:.2f}")
        self.metric_vars["resistance"].set(f"{current['resistance']:.2f}")
        self.metric_vars["volume_ratio"].set(f"{current['volume_ratio']:.2f}×")
        self.metric_vars["atr"].set(f"{current['atr']:.2f}")
        self._set_text(self.reason_text, "\n".join(f"• {reason}" for reason in current["reasons"]) or "目前尚未形成足夠訊號，先觀察。")
        self._set_text(self.action_text, "目前名單皆視為已持股；請看下面的『持股操作』：\n" + self._action_guidance(current))
        chip_state = current["chip"]
        chip_lines = [
            f"來源：{chip_state.get('source', '籌碼資料缺口')}｜日期：{chip_state.get('as_of', current['date'])}",
            f"• 外資：{self._net_text(chip_state.get('foreign_net'))}｜持股：{self._format_percent(chip_state.get('foreign_holder_percent'))}｜趨勢：{self._trend_text(chip_state.get('foreign_trend'))}",
            f"• 三大法人：{self._net_text(chip_state.get('institutional_net'))}｜持股：{self._format_percent(chip_state.get('institutional_holder_percent'))}｜趨勢：{self._trend_text(chip_state.get('institutional_trend'))}",
            f"• 大戶：{self._format_percent(chip_state.get('large_holder_percent'))}｜趨勢：{self._trend_text(chip_state.get('large_holder_trend'))}",
            f"• 散戶：{self._format_percent(chip_state.get('retail_holder_percent'))}｜趨勢：{self._trend_text(chip_state.get('retail_holder_trend'))}",
        ]
        if chip_state.get("broker_net") is not None:
            chip_lines.append(f"• 主力：{self._net_text(chip_state['broker_net'])}｜趨勢：{self._trend_text(chip_state.get('broker_trend'))}")
        if chip_state.get("retail_net") is not None:
            chip_lines.append(f"• 散戶買賣超：{self._net_text(chip_state['retail_net'])}｜趨勢：{self._trend_text(chip_state.get('retail_trend'))}")
        if chip_state.get("source_note"):
            chip_lines.append(f"• 使用規則：{chip_state['source_note']}")
        chip_lines.append(f"• 籌碼判讀：{chip_state.get('label', '籌碼資料缺口')}")
        self._set_text(self.chip_text, "\n".join(chip_lines))
        for item in self.table.get_children():
            self.table.delete(item)
        for event in analysis["events"]:
            self.table.insert("", "end", values=(event["date"], event["label"], f"{event['price']:.2f}", event["reason"], event["chip"]))

    def _action_guidance(self, current: dict) -> str:
        return core.action_guidance(current, observation_only=self.stock.get("observation_only", False))

    @staticmethod
    def _trend_text(value: object) -> str:
        return {"up": "向上", "down": "向下"}.get(str(value), "未提供")

    @staticmethod
    def _net_text(value: object) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "淨額未提供"
        if number > 0:
            return f"買超 {number:g} 張"
        if number < 0:
            return f"賣超 {abs(number):g} 張"
        return "持平 0 張"

    @staticmethod
    def _format_percent(value: object) -> str:
        try:
            return f"持股 {float(value):.2f}%"
        except (TypeError, ValueError):
            return "比例未提供"

    def _open_cache(self) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(CACHE_DIR)

    def _cache_paths(self) -> tuple[Path, Path, Path]:
        prefix = self.stock["symbol"].split(".")[0]
        return CACHE_DIR / f"{prefix}_history.csv", CACHE_DIR / f"{prefix}_chip_snapshot.json", CACHE_DIR / f"{prefix}_update_meta.json"

    def _on_stock_changed(self, _event: object = None) -> None:
        self.stock_key = self.stock_var.get()
        self.stock = STOCKS[self.stock_key]
        symbol = self.stock["symbol"].split(".")[0]
        self.root.title(f"個股三層轉強提醒｜目前：{self.stock['name']} {symbol}")
        self.app_title_var.set(f"個股三層轉強提醒｜目前：{self.stock['name']} {symbol}")
        self._load_cache()

    def _updated_today(self, update_meta_path: Path) -> bool:
        if not update_meta_path.exists():
            return False
        try:
            value = update_meta_path.read_text(encoding="utf-8")
            return datetime.now().strftime("%Y-%m-%d") in value
        except OSError:
            return False


if __name__ == "__main__":
    app_root = tk.Tk()
    ZhishenApp(app_root)
    app_root.mainloop()
