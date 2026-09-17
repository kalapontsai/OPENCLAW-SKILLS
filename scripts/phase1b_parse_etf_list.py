#!/usr/bin/env python3
"""
fund-plan Phase 1b: 解析 MoneyDJ + StockQ spilled logs → 寫入 etf_universe_raw.csv

來源（不限來源原則）：
  1. MoneyDJ: /tmp/openclaw-web-fetch-3e9e992e8ef3279e.log (R=500 完整台股 ETF)
  2. StockQ:  /tmp/openclaw-web-fetch-f9f021fa792505f6.log (台灣 ETF 列表 + 分類)

任務：
  - parse ticker + name + 殖利率 + 規模
  - 剔除槓桿反向（L/R/+U/K 結尾）
  - 用名稱推導分類 (高股息/股票型/債券型/REITs/主題/海外)
  - 寫入 data/etf_universe_raw.csv

作者: 大寶 (agent-one)
日期: 2026-08-29
"""
import re
import sys
from pathlib import Path
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
LOG_DIR = PROJECT_DIR / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 1. 讀 spilled logs
# ============================================================
LOGS = {
    "moneydj": "/tmp/openclaw-web-fetch-3e9e992e8ef3279e.log",
    "stockq":  "/tmp/openclaw-web-fetch-f9f021fa792505f6.log",
}

texts = {}
for src, path in LOGS.items():
    if not Path(path).is_file():
        print(f"⚠️  {src} log 缺失: {path}", file=sys.stderr)
        texts[src] = ""
    else:
        texts[src] = Path(path).read_text(encoding="utf-8", errors="ignore")
        print(f"📄 {src}: {len(texts[src])} chars")

# ============================================================
# 2. Parse MoneyDJ 表格
#    格式: [0050](url) [元大台灣50](url) 2026/08/28 106.95 0.90 ...
# ============================================================
def parse_moneydj(text: str) -> list[dict]:
    # 抓 [ticker](url) [name](url) + 數字
    # 跳過表頭
    rows = []
    # pattern: [ticker](url) 緊接著 [name](url) 然後 date + 8-9 個數字
    pattern = re.compile(
        r'\[(?P<tid>[A-Z0-9]+)\]\([^)]+\)\s*'
        r'\[(?P<name>[^\]]+)\]\([^)]+\)\s*'
        r'(?P<date>\d{4}/\d{2}/\d{2})\s+'
        r'(?P<price>[\d.]+|N/A)\s+'
        r'(?P<change>[-+.\d]+|N/A)\s+'
        r'(?P<chg_pct>[-+.\d]+|N/A)\s+'
        r'(?P<volume>[\d,]+|N/A)\s+'
        r'(?P<premium>[-+.\d]+%|N/A)\s+'
        r'(?P<scale>[\d,.]+|N/A)\s+'
        r'\([^)]+\)\s*'  # 台幣規模
        r'(?P<yield>[\d.]+|N/A)\s*'
        r'(?P<ytd>[-+.\d]+|N/A)'
    )
    for m in pattern.finditer(text):
        d = m.groupdict()
        # 把 N/A 轉成空
        for k in ("price", "change", "chg_pct", "volume", "premium", "scale", "yield", "ytd"):
            if d[k] == "N/A":
                d[k] = None
        d["source"] = "moneydj"
        rows.append(d)
    return rows


# ============================================================
# 3. Parse StockQ 表格
#    格式: ticker\n[name](url)\n ... 折溢價% 漲跌幅% 成交量 偏離 日期 時間
#    每行 ticker 後面跟 name link，再跟空行
# ============================================================
def parse_stockq(text: str) -> list[dict]:
    rows = []
    # pattern: 純 4-6 碼 ticker 行（沒在 [...] 內） 緊接著 [name](url) 行
    pattern = re.compile(
        r'(?:^|\n)(?P<tid>00\d{2,4}[A-Z]?)\s*\n'
        r'\[(?P<name>[^\]]+)\]\([^)]+\)'
    )
    for m in pattern.finditer(text):
        d = {
            "tid": m.group("tid"),
            "name": m.group("name").strip(),
            "source": "stockq",
            "date": None, "price": None, "change": None,
            "chg_pct": None, "volume": None, "premium": None,
            "scale": None, "yield": None, "ytd": None,
        }
        rows.append(d)
    return rows


moneydj_rows = parse_moneydj(texts["moneydj"])
stockq_rows = parse_stockq(texts["stockq"])

print(f"\n📊 parse 結果:")
print(f"  MoneyDJ: {len(moneydj_rows)} rows")
print(f"  StockQ:  {len(stockq_rows)} rows")

# ============================================================
# 4. Merge + 去重 (以 ticker 為主，MoneyDJ 優先因為有殖利率)
# ============================================================
merged = {}
for r in moneydj_rows:
    merged[r["tid"]] = r
for r in stockq_rows:
    if r["tid"] not in merged:
        merged[r["tid"]] = r
    else:
        # 補上 StockQ 的 name 如果 MoneyDJ 沒有
        if not merged[r["tid"]].get("name"):
            merged[r["tid"]]["name"] = r["name"]

print(f"  Merged unique tickers: {len(merged)}")

# ============================================================
# 5. 篩選：剔除槓桿反向 + 不適合退休組合
# ============================================================
LEVERAGED_PAT = re.compile(r'(正2|反1|槓�|反向|期元大|S&P日圓|S&P黃金|S&P原油|布蘭特|彭博|恒生國企|那斯達克|N系列|\+U|\+R)', re.IGNORECASE)

def is_leveraged_or_exotic(tid: str, name: str) -> bool:
    # 槓桿：00631L 00632R 00663L 00664R 00675L 00676R 00685L 00686R
    # 00680L 00681R 00670L 00671R ...
    # 00640L 00641R 00655L 00656R 00665L 00666R 00673R 00674R
    # 00647L 00648R 00637L 00638R 00633L 00634R 00650L 00651R
    # 00653L 00654R 00678 群益那斯達克生技 (海外/生技)
    # 020000 020001 020011 N 系列 (新上市槓桿)
    # 0061 元大寶滬深 (中國/海外)
    # 00636 00636K 國泰中國A50 (中國/海外)
    # 00639 富邦深100 (中國)
    # 00643 00643K 群益深証中小 (中國)
    # 00646 元大S&P500 (海外美股)
    # 00652 00653L 00654R 富邦印度 (印度)
    # 00657 00657K 國泰日經225 (日本)
    # 00660 元大歐洲50 (歐洲)
    # 00661 元大日經225 (日本)
    # 00662 富邦NASDAQ (美股)
    # 00665L 00666R 富邦恒生國企 (港股)
    # 00668 00668K 00669R 國泰美國道瓊 (美股)
    # 00670L 00671R 富邦NASDAQ (美股)
    # 00645 富邦日本 (日本)
    # 00635U 00636K 00642U 期元大S&P (商品)
    # 00679B 元大美債20年 (債券 - 可留)
    # 00706L 00707R 00708L (商品槓桿)
    # 00678 群益那斯達克生技 (生技海外)
    # 海外/商品/中國/印度/日本/歐洲/美股 太多，這次先只留「台股」

    # 規則 1: ticker 結尾是 L/R/U/K/2 (槓桿/反向/外幣/2 倍)
    if re.search(r'[LRUK]$', tid):
        return True
    if re.search(r'[A-Z]\d$', tid):  # 020000 020011 等
        # 020000 系列也是槓桿
        if tid.startswith("020"):
            return True
    # 規則 2: 名稱含槓桿/反向/正2/反1
    if LEVERAGED_PAT.search(name):
        return True
    # 規則 3: 純海外/中國/印度/日本/歐洲/美股 (0061 00636 00643 00645 00646 00652 00657 00660 00661 00662 00665 00666 00668 00670 00639 等)
    overseas_pat = re.compile(r'(中國|滬深|深證|深100|恒生|香港|印度|日經|日本|歐洲|NASDAQ|道瓊|S&P500|標普500|S&P日圓|S&P黃金|S&P原油|那斯達克|寶滬深|摩台|那斯|生技)')
    if overseas_pat.search(name):
        # 例外：富邦摩台 0057 是台股的「台灣中型股」，要留
        if tid == "0057" or "摩台" in name:
            return False
        # 其他海外全剔
        return True
    return False


filtered = []
dropped = []
for tid, r in merged.items():
    if is_leveraged_or_exotic(tid, r["name"]):
        dropped.append((tid, r["name"]))
    else:
        filtered.append(r)

print(f"\n🚫 剔除槓桿/反向/海外: {len(dropped)} 檔")
for tid, name in dropped[:5]:
    print(f"   {tid} {name}")
if len(dropped) > 5:
    print(f"   ... 還有 {len(dropped)-5} 檔")

print(f"\n✅ 留下 (台股一般 ETF): {len(filtered)} 檔")

# ============================================================
# 6. 用名稱推導分類
# ============================================================
def classify(name: str, tid: str) -> str:
    # 優先順序：高股息 > 債券 > REITs > 主題/產業 > ESG > 主動 > 一般股票
    if re.search(r'(高息|高股息|高填息|股利|股息|優息|存股)', name):
        return "高股息"
    if re.search(r'(債|美債|公司債|金融債|投等債|投資級)', name):
        return "債券型"
    if re.search(r'(REIT|不動產|地產)', name):
        return "REITs"
    if re.search(r'(ESG|永續|低碳)', name):
        return "ESG"
    if re.search(r'(主動)', name):
        return "主動型"
    if re.search(r'(半導體|科技|電子|電動車|智能車|綠能|AI|5G|晶圓|IC設計|關鍵半導體|智慧)', name):
        return "主題/產業"
    if re.search(r'(金融)', name):
        return "金融"
    if re.search(r'(50|中型100|龍頭|領袖|精選|TOP|藍籌|高價|中小|價值|動能|Smart|精彩|優選|增長|強棒|卓越|豐收|鑫收|優勢|台灣)', name):
        return "一般股票"
    return "其他"


for r in filtered:
    r["category"] = classify(r["name"], r["tid"])

# 分類統計
from collections import Counter
cat_count = Counter(r["category"] for r in filtered)
print(f"\n📂 分類統計:")
for cat, n in sorted(cat_count.items(), key=lambda x: -x[1]):
    print(f"   {cat}: {n} 檔")

# ============================================================
# 7. 寫入 CSV
# ============================================================
out = DATA_DIR / "etf_universe_raw.csv"
df = pd.DataFrame(filtered)
# 重新排欄位
cols = ["tid", "name", "category", "price", "yield", "scale", "volume",
        "premium", "ytd", "date", "source"]
df = df[[c for c in cols if c in df.columns]]
df = df.sort_values("tid").reset_index(drop=True)
df.to_csv(out, index=False, encoding="utf-8-sig")
print(f"\n💾 寫入 {out}")
print(f"   {len(df)} 檔, {len(df.columns)} 欄")

# ============================================================
# 8. 寫 log
# ============================================================
log_path = LOG_DIR / "phase1b.log"
with open(log_path, "w", encoding="utf-8") as f:
    f.write(f"Phase 1b — 解析 ETF 清單\n")
    f.write(f"MoneyDJ rows: {len(moneydj_rows)}\n")
    f.write(f"StockQ rows: {len(stockq_rows)}\n")
    f.write(f"Merged: {len(merged)}\n")
    f.write(f"Dropped (槓桿/反向/海外): {len(dropped)}\n")
    f.write(f"Final filtered: {len(filtered)}\n\n")
    f.write(f"分類統計:\n")
    for cat, n in sorted(cat_count.items(), key=lambda x: -x[1]):
        f.write(f"  {cat}: {n}\n")
    f.write(f"\n清單 (前 30):\n")
    for r in filtered[:30]:
        f.write(f"  {r['tid']} | {r['name']} | {r['category']}\n")
print(f"📝 log: {log_path}")
