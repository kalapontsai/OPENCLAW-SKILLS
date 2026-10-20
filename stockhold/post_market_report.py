#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
post_market_report.py — 盤後報告產生器
======================================

組合流程:
  1. 從 config.json 讀 deploy_url 與 api_token
  2. GET /api/v1/holdings   → 持倉、數量、平均成本
  3. GET /api/v1/securities → exchange 對應 (TW / TWO)，用來組 yfinance ticker
  4. yfinance 取得「上一個交易日」與「今日」收盤價（含 retry）
     - 若 yfinance 失敗且 ticker 為 .TW，自動改用 TWSE MIS 行情當備援
  5. 逐筆計算 market_value / today_pnl / unrealized_pnl
  6. 匯出 JSON（檔案 + 可選擇 pretty-print 到 stdout）

用法:
    post_market_report.py                      # 用 config.json
    post_market_report.py --no-write --pretty  # 試跑，不寫檔
    post_market_report.py --source twse        # 直接走 TWSE MIS（台股限定）
    post_market_report.py -o /tmp/report.json  # 自訂輸出

設定檔 (config.json):
    deploy_url        必填，stock_hold API 根網址 (https://...)
    api_token         必填，X-API-Token（Settings -> API Token 取得）
    output_path       選填，預設 ./output.json
    price_source      選填，yfinance | twse | auto，預設 yfinance
    history_days      選填，yfinance 回看天數，預設 10
    fallback_to_twse  選填，yfinance 失敗時是否回退 TWSE MIS，預設 true

    字串值可寫 ${ENV_VAR} 引用環境變數，讀取時自動展開。
    範例: "api_token": "${STOCK_HOLD_API_TOKEN}"
    未設定的環境變數會保留為字面 ${VAR}，會在啟動時被拒絕執行。
    config.json.example 使用 https://your-stockhold.example.com 與
    "***" 等 RFC 2606 / 通用 placeholder，這些值在啟動時同樣會被拒絕。

相依: yfinance（見 requirements.txt）。建議在本地 .venv 安裝，避免影響系統 Python。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ---------- 常數 ----------

SCHEMA_VERSION = "1.0"
DEFAULT_HISTORY_DAYS = 10
YF_RETRY_ATTEMPTS = 3
YF_RETRY_BACKOFF = 2.0           # 秒（指數退避基線）
YF_REQ_TIMEOUT = 30
TWSE_MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TWSE_MIS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://mis.twse.com.tw/",
}
TPE = timezone(timedelta(hours=8))  # Asia/Taipei


# ---------- Config ----------

# 啟動時拒絕的 placeholder 模式（確保 config.json 是真實部署值，不是複製範本後忘了改）。
# 涵蓋 RFC 2606 reserved TLD、shell-style 替換變數未解析、`<token>` 風格、以及通用佔位字。
_PLACEHOLDER_RE = re.compile(
    r"""^(
        \*\*\*                       |   # literal ***
        <[^>]+>                     |   # <your-token>
        \$\{[^}]+\}                 |   # ${UNRESOLVED_VAR}
        (your|replace|changeme|xxx|placeholder|example)[-_a-z0-9]*
                                    |   # your-token, replace-with, changeme, xxx, ...
        todo | fixme
    )$""",
    re.IGNORECASE | re.VERBOSE,
)
# RFC 2606 reserved TLD: 不可作為真實 deploy target 出現於 URL。
_RFC2606_TLD_RE = re.compile(
    r"\.(example|invalid|test|localhost)(/|\?|:|$)",
    re.IGNORECASE,
)


def _expand_env(value):
    """對字串值套 os.path.expandvars；非字串原樣回傳。"""
    if isinstance(value, str):
        return os.path.expandvars(value)
    return value


def _is_token_placeholder(value: str) -> bool:
    """api_token 是否仍是 placeholder（拒絕 *** / <...> / ${UNRESOLVED} / your-... 等）。"""
    return bool(_PLACEHOLDER_RE.match(value.strip()))


def _is_url_placeholder(value: str) -> bool:
    """deploy_url 是否仍是 placeholder：非 http(s)、RFC 2606 TLD、或 your-... 風格。"""
    s = value.strip()
    if not s.lower().startswith(("http://", "https://")):
        return True
    if _PLACEHOLDER_RE.match(s):
        return True
    if _RFC2606_TLD_RE.search(s):
        return True
    return False


def load_config(path: Path) -> dict:
    """讀取 config.json，補上預設值，展開 $VAR，拒絕 placeholder。

    - 字串值內 ${ENV_VAR} 會被 os.environ 展開；未設定時保留字面 ${VAR} 並在驗證階段拒絕。
    - 公開 repo 的 config.json.example 預設使用 RFC 2606 placeholder
      (https://your-stockhold.example.com / "***")，這些會在啟動時直接被拒絕，
      避免使用者複製範本後忘記改就直接 commit / 推到線上。
    """
    if not path.exists():
        raise SystemExit(f"ERROR: 設定檔不存在: {path}")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"ERROR: {path} 不是合法 JSON: {e}")

    # 展開環境變數
    cfg = {k: _expand_env(v) for k, v in cfg.items()}

    # 必填 + 拒絕 placeholder
    for key, is_placeholder in (
        ("deploy_url", _is_url_placeholder),
        ("api_token", _is_token_placeholder),
    ):
        v = cfg.get(key)
        if not v or not str(v).strip():
            raise SystemExit(f"ERROR: config.json 缺少必填欄位: {key}")
        if is_placeholder(str(v)):
            unresolved = "${" in str(v)
            hint = (
                "（環境變數未設定，請 export 或在 config.json 直接填值）"
                if unresolved
                else "（請在 config.json 直接填入真實值）"
            )
            raise SystemExit(
                f"ERROR: config.json 的 {key} 仍是 placeholder: {v!r}\n"
                f"       {hint}"
            )

    cfg["deploy_url"] = str(cfg["deploy_url"]).rstrip("/")
    cfg["api_token"] = str(cfg["api_token"]).strip()
    cfg.setdefault("output_path", "./output.json")
    cfg.setdefault("price_source", "yfinance")
    cfg.setdefault("history_days", DEFAULT_HISTORY_DAYS)
    cfg.setdefault("fallback_to_twse", True)
    return cfg


# ---------- stock_hold API 呼叫 ----------

def api_get(base: str, path: str, token: str, *, timeout: int = 30) -> dict:
    """GET stock_hold 端點（urllib + 明確 User-Agent，避免 Cloudflare 403）。"""
    url = f"{base}{path}"
    req = urllib.request.Request(
        url,
        headers={
            "X-API-Token": token,
            "User-Agent": "stockhold-post-market-report/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(
            f"ERROR: API HTTP {e.code} on GET {path} → {body[:300]}"
        )
    except urllib.error.URLError as e:
        raise SystemExit(f"ERROR: 連線到 {url} 失敗: {e.reason}")


def api_get_items(base: str, path: str, token: str) -> list[dict]:
    """GET 端點並回傳 data.items[]，envelope status != ok 時直接中斷。"""
    resp = api_get(base, path, token)
    if resp.get("status") != "ok":
        err = resp.get("error") or {}
        raise SystemExit(
            f"ERROR: API {path} 回傳 status={resp.get('status')!r}, error={err}"
        )
    return (resp.get("data") or {}).get("items") or []


def auth_check(base: str, token: str) -> str:
    """輕量驗證 token，回傳 username。失敗會直接 raise。"""
    resp = api_get(base, "/api/v1/auth/me", token)
    if resp.get("status") != "ok":
        raise SystemExit(f"ERROR: /auth/me 驗證失敗: {resp.get('error')}")
    return (resp.get("data") or {}).get("username", "<unknown>")


# ---------- Ticker 對應 ----------

def to_yf_ticker(symbol: str, exchange: str) -> str:
    """security.symbol + exchange → yfinance ticker（TW→.TW、TWO/TPEX→.TWO）。"""
    s = str(symbol).strip()
    if s.endswith(".TW") or s.endswith(".TWO"):
        return s
    ex = (exchange or "").upper()
    if ex in ("TW", "TWSE", "TSE"):
        return f"{s}.TW"
    if ex in ("TWO", "TPEX", "OTC"):
        return f"{s}.TWO"
    # 預設台股
    return f"{s}.TW"


# ---------- yfinance ----------

def fetch_yf_one(ticker: str, days: int) -> list[dict]:
    """單一 ticker 的歷史收盤價。回傳 [{date: YYYY-MM-DD, close: float}, ...]。"""
    import yfinance as yf  # 在函式內 import，沒裝 venv 時讓錯誤訊息集中

    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=days + 7)
    last_err: Exception | None = None

    for attempt in range(YF_RETRY_ATTEMPTS):
        try:
            t = yf.Ticker(ticker)
            hist = t.history(
                start=start.isoformat(),
                end=end.isoformat(),
                auto_adjust=False,
                actions=False,
                timeout=YF_REQ_TIMEOUT,
            )
            if hist is None or hist.empty:
                raise RuntimeError(f"yfinance {ticker}: empty history")

            rows: list[dict] = []
            for idx, row in hist.iterrows():
                # idx 已是交易所當地時區（TW = +08:00）；取其日期
                d = idx.date() if hasattr(idx, "date") else idx
                rows.append({"date": d.isoformat(), "close": float(row["Close"])})
            return rows
        except Exception as e:
            last_err = e
            if attempt < YF_RETRY_ATTEMPTS - 1:
                sleep = YF_RETRY_BACKOFF * (2 ** attempt) + random.uniform(0, 0.5)
                time.sleep(sleep)

    raise RuntimeError(f"yfinance {ticker} 重試 {YF_RETRY_ATTEMPTS} 次仍失敗: {last_err}")


def fetch_yf_batch(tickers: list[str], days: int) -> dict[str, list[dict]]:
    """批次抓所有 tickers。失敗的 ticker 回傳 [{'error': '...'}]（單元素 list）。"""
    out: dict[str, list[dict]] = {}
    for tk in tickers:
        try:
            out[tk] = fetch_yf_one(tk, days)
        except Exception as e:
            out[tk] = [{"error": str(e)}]
    return out


# ---------- TWSE MIS 備援 ----------

def fetch_twse_one(symbol: str) -> list[dict]:
    """單一上市 ticker 從 TWSE MIS 抓今日最新價 (z) 與昨收 (y)。"""
    url = f"{TWSE_MIS_URL}?ex_ch=tse_{symbol}.tw"
    req = urllib.request.Request(url, headers=TWSE_MIS_HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    rows = body.get("msgArray") or []
    if not rows:
        raise RuntimeError(f"TWSE MIS {symbol}: empty msgArray")
    r = rows[0]
    z = r.get("z")
    y = r.get("y")
    tick_time = r.get("t")
    today_date = datetime.now(TPE).date().isoformat()
    out: list[dict] = []
    # MIS 的 z 在盤中會跳動，盤後則是當日收盤
    if z not in (None, "-", ""):
        out.append({"date": today_date, "close": float(z), "tick_time": tick_time})
    if y not in (None, "-", ""):
        out.append({"date": None, "close": float(y), "kind": "prev_close"})
    if not out:
        raise RuntimeError(f"TWSE MIS {symbol}: 缺 z/y 欄位")
    return out


# ---------- 價格派發 ----------

def fetch_prices(
    tickers: list[str],
    source: str,
    days: int,
    fallback_to_twse: bool,
) -> dict[str, dict[str, Any]]:
    """依設定抓取所有 ticker 行情。

    回傳結構：{ticker: {"rows": [...], "source": str|None, "errors": [str]}}
    """
    if source == "twse":
        result: dict[str, dict[str, Any]] = {}
        for tk in tickers:
            if not tk.endswith(".TW"):
                result[tk] = {
                    "rows": [],
                    "source": None,
                    "errors": [f"twse source 不支援 {tk}（僅支援 .TW）"],
                }
                continue
            try:
                rows = fetch_twse_one(tk.removesuffix(".TW"))
                result[tk] = {"rows": rows, "source": "twse_mis", "errors": []}
            except Exception as e:
                result[tk] = {"rows": [], "source": None, "errors": [str(e)]}
        return result

    # yfinance（或 auto，auto 等同 yfinance + fallback）
    yf_data = fetch_yf_batch(tickers, days)
    result = {}
    for tk, rows in yf_data.items():
        if rows and "error" not in rows[0]:
            result[tk] = {"rows": rows, "source": "yfinance", "errors": []}
            continue

        err_msg = rows[0].get("error") if rows else "empty"
        if fallback_to_twse and tk.endswith(".TW"):
            try:
                twse_rows = fetch_twse_one(tk.removesuffix(".TW"))
                result[tk] = {
                    "rows": twse_rows,
                    "source": "twse_mis_fallback",
                    "errors": [err_msg],
                }
                continue
            except Exception as e2:
                result[tk] = {
                    "rows": [],
                    "source": None,
                    "errors": [err_msg, f"twse fallback failed: {e2}"],
                }
        else:
            result[tk] = {"rows": [], "source": None, "errors": [err_msg]}
    return result


# ---------- 報告組裝 ----------

def select_last_two(rows: list[dict]) -> tuple[dict | None, dict | None]:
    """從 yfinance rows 取 (今日, 上一個交易日)，皆依日期降序排序後取前兩個不同日期。"""
    if not rows:
        return None, None
    sorted_rows = sorted(
        [r for r in rows if r.get("date")],
        key=lambda r: r["date"],
        reverse=True,
    )
    today = sorted_rows[0] if sorted_rows else None
    prev = next(
        (r for r in sorted_rows[1:] if r.get("date") and r.get("date") != today.get("date")),
        None,
    )
    return today, prev


def _round(x: float | None, n: int = 4) -> float | None:
    return round(x, n) if isinstance(x, (int, float)) else None


def _safe_pct(numer: float | None, denom: float | None) -> float | None:
    if numer is None or denom is None or denom == 0:
        return None
    return numer / denom * 100


def compose_report(
    cfg: dict,
    holdings: list[dict],
    securities: list[dict],
    prices: dict[str, dict[str, Any]],
    username: str,
) -> dict:
    sec_by_id = {s["id"]: s for s in securities if "id" in s}
    today_iso = datetime.now(TPE).date().isoformat()

    enriched: list[dict] = []
    total_cost = 0.0
    total_mv = 0.0
    total_today_pnl = 0.0
    total_unrealized = 0.0
    rows_with_price = 0

    for h in holdings:
        sec = sec_by_id.get(h.get("security_id", ""), {})
        sym = h.get("symbol", "")
        exchange = sec.get("exchange") or h.get("exchange") or "TW"
        ticker = to_yf_ticker(sym, exchange)

        qty = float(h.get("qty", 0) or 0)
        avg_cost = float(h.get("avg_cost", 0) or 0)
        cost_basis = qty * avg_cost

        pdata = prices.get(ticker) or {}
        rows = pdata.get("rows") or []
        src = pdata.get("source")
        errs = list(pdata.get("errors") or [])

        yf_today, yf_prev = select_last_two(rows)

        last_close = yf_today.get("close") if yf_today else None
        prev_close = yf_prev.get("close") if yf_prev else None

        # yfinance 缺資料時回退用 stock_hold 自己的 current_price / prev_close
        if last_close is None and h.get("current_price") is not None:
            last_close = float(h["current_price"])
            errs.append("yfinance 缺今日；改用 stock_hold current_price")
        if prev_close is None and h.get("prev_close") is not None:
            prev_close = float(h["prev_close"])
            errs.append("yfinance 缺昨收；改用 stock_hold prev_close")

        mv = qty * last_close if last_close is not None else None
        today_pnl = (
            qty * (last_close - prev_close)
            if (last_close is not None and prev_close is not None)
            else None
        )
        unrealized = qty * (last_close - avg_cost) if last_close is not None else None

        if mv is not None:
            total_mv += mv
            rows_with_price += 1
        if today_pnl is not None:
            total_today_pnl += today_pnl
        if unrealized is not None:
            total_unrealized += unrealized
        total_cost += cost_basis

        today_change = (
            (last_close - prev_close)
            if (last_close is not None and prev_close is not None)
            else None
        )

        enriched.append(
            {
                "symbol": sym,
                "name": h.get("name"),
                "exchange": exchange,
                "yf_ticker": ticker,
                "account_name": h.get("account_name"),
                "currency": h.get("currency"),
                "qty": qty,
                "avg_cost": avg_cost,
                "cost_basis": _round(cost_basis),
                "prev_close": _round(prev_close),
                "last_close": _round(last_close),
                "today_change": _round(today_change),
                "today_change_pct": _round(_safe_pct(today_change, prev_close), 2),
                "market_value": _round(mv),
                "today_pnl": _round(today_pnl),
                "unrealized_pnl": _round(unrealized),
                "unrealized_pnl_pct": _round(_safe_pct(unrealized, cost_basis), 2),
                # portfolio_pct 需等整個迴圈累加 total_mv 結束才能算；
                # 第一輪先放 None，迴圈後再回填，確保所有 holdings 用同一個分母。
                "portfolio_pct": None,
                "price_source": src,
                "errors": errs,
            }
        )

    # 回填 portfolio_pct：個股市值 / 總市值 × 100%
    # 分母 = summary.total_market_value（已 round 過，這裡仍以原始 total_mv 算以避免 double-round 誤差）
    # 個股 market_value 為 null 或 total_mv <= 0 時回傳 None，不臆測。
    for row in enriched:
        if row.get("market_value") is None or total_mv <= 0:
            row["portfolio_pct"] = None
        else:
            row["portfolio_pct"] = _round(
                _safe_pct(row["market_value"], total_mv), 2
            )

    summary = {
        "holdings_count": len(holdings),
        "priced_count": rows_with_price,
        "total_cost_basis": _round(total_cost),
        "total_market_value": _round(total_mv),
        "total_today_pnl": _round(total_today_pnl),
        "total_today_pnl_pct": _round(_safe_pct(total_today_pnl, total_mv), 2),
        "total_unrealized_pnl": _round(total_unrealized),
        "total_unrealized_pnl_pct": _round(_safe_pct(total_unrealized, total_cost), 2),
    }

    return {
        "report_version": SCHEMA_VERSION,
        "generated_at": datetime.now(TPE).isoformat(timespec="seconds"),
        "username": username,
        "deploy_url": cfg["deploy_url"],
        "as_of_date": today_iso,
        "price_source_requested": cfg["price_source"],
        "fallback_to_twse": cfg["fallback_to_twse"],
        "summary": summary,
        "holdings": enriched,
    }


# ---------- 入口 ----------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="stock_hold + yfinance 盤後報告產生器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config", "-c", default="config.json",
        help="設定檔路徑（預設 ./config.json）",
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="覆寫 config 內的 output_path",
    )
    parser.add_argument(
        "--source", "-s", choices=["yfinance", "twse", "auto"], default=None,
        help="行情來源（預設 auto=yfinance+TWSE MIS fallback）",
    )
    parser.add_argument(
        "--no-write", action="store_true",
        help="不寫檔，只印到 stdout",
    )
    parser.add_argument(
        "--pretty", action="store_true",
        help="除了寫檔，也 pretty-print 到 stdout",
    )
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    if args.output:
        cfg["output_path"] = args.output
    if args.source:
        cfg["price_source"] = args.source

    log = lambda msg: print(msg, file=sys.stderr)
    log(f"[1/5] 驗證 token @ {cfg['deploy_url']}/api/v1/auth/me ...")
    username = auth_check(cfg["deploy_url"], cfg["api_token"])
    log(f"      → 通過，使用者={username}")

    log(f"[2/5] 抓 holdings ...")
    holdings = api_get_items(cfg["deploy_url"], "/api/v1/holdings", cfg["api_token"])
    log(f"      → {len(holdings)} 筆")

    log(f"[3/5] 抓 securities ...")
    securities = api_get_items(cfg["deploy_url"], "/api/v1/securities", cfg["api_token"])
    log(f"      → {len(securities)} 筆")

    sec_by_id = {s["id"]: s for s in securities if "id" in s}
    tickers: list[str] = []
    seen: set[str] = set()
    for h in holdings:
        sec = sec_by_id.get(h.get("security_id", ""), {})
        tk = to_yf_ticker(h.get("symbol", ""), sec.get("exchange", "TW"))
        if tk not in seen:
            seen.add(tk)
            tickers.append(tk)

    log(f"[4/5] 抓行情 {len(tickers)} 個 ticker（source={cfg['price_source']}）...")
    prices = fetch_prices(
        tickers,
        cfg["price_source"],
        cfg["history_days"],
        cfg["fallback_to_twse"],
    )
    ok = sum(1 for v in prices.values() if v.get("rows"))
    log(f"      → 成功 {ok}/{len(tickers)}；失敗詳見 holdings[].errors")

    log(f"[5/5] 組裝報告 ...")
    report = compose_report(cfg, holdings, securities, prices, username)

    if args.no_write:
        log("      → --no-write，略過寫檔")
    else:
        out_path = Path(cfg["output_path"])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log(f"      → 寫入 {out_path}")

    if args.pretty or args.no_write:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())