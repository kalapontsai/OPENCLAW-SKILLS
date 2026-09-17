#!/usr/bin/env python3
"""
fund-plan: 把 etf_universe_raw.csv 寄給主人 (kadelat@gmail.com)

- 複用主人既有 SMTP_mail.py 的 send_email() function
- 不複製主人 SMTP 密碼到我自己的檔案
- 收件人: kadelat@gmail.com (USER.md)
- 寄件人: bt994846@sampo.com.tw (主人 outlook 公司帳號, hardcode 在 SMTP_mail.py)
- 附件: data/etf_universe_raw.csv (266 檔)

作者: 大寶 (agent-one)
日期: 2026-08-29
"""
import sys
from pathlib import Path

# 1. 載入主人現成的 SMTP function (密碼 hardcode 在那, 我們不碰)
SMTP_LIB = "/mnt/d/OneDrive - Sampo Corporation/3.Data/5.python/automate-email/"
sys.path.insert(0, SMTP_LIB)
from SMTP_mail import send_email

# 2. 準備資料
PROJECT_DIR = Path("/home/bt994846/.openclaw/workspace/projects/fund-plan")
csv_path = PROJECT_DIR / "data/etf_universe_raw.csv"

if not csv_path.is_file():
    print(f"❌ CSV 不存在: {csv_path}")
    sys.exit(1)

# 3. 主旨 + HTML body
subject = "[fund-plan] 台股 ETF 清單 — 266 檔 (2026-08-29)"

body = """
<h3>🎯 fund-plan — 台股 ETF 候選清單</h3>

<p>主人，這是 Phase 1b 產出的 ETF 清單，請 review。</p>

<h4>📊 分類分布 (266 檔)</h4>
<table border="1" cellpadding="4" cellspacing="0" style="border-collapse:collapse">
<tr><th>分類</th><th>檔數</th></tr>
<tr><td>債券型</td><td>100</td></tr>
<tr><td>高股息</td><td>35</td></tr>
<tr><td>主動型</td><td>32</td></tr>
<tr><td>一般股票</td><td>32</td></tr>
<tr><td>主題/產業</td><td>29</td></tr>
<tr><td>其他</td><td>26</td></tr>
<tr><td>ESG</td><td>6</td></tr>
<tr><td>金融</td><td>4</td></tr>
<tr><td>REITs</td><td>2</td></tr>
</table>

<h4>📋 來源</h4>
<ul>
<li>主要：StockQ.org /etf/ (357 筆原始清單)</li>
<li>輔助：MoneyDJ et305001list.djhtm</li>
<li>篩選：ticker 結尾 L/R/U/K (槓桿反向) + 名稱含「中國/日本/歐洲/美股」等海外關鍵字</li>
</ul>

<h4>⚠️ 已知限制</h4>
<ul>
<li>MoneyDJ parse 失敗 (regex 對不上) → metadata 暫缺 (殖利率/規模/今年報酬率)</li>
<li>26 檔分類「其他」待修 (可能是新發行的 00981A 系列或分類規則漏掉)</li>
<li>尚未驗證每檔 2019-01-01 前是否已上市 (Phase 2 篩選前要做)</li>
</ul>

<h4>📂 CSV 欄位</h4>
<p><code>tid, name, category, price, yield, scale, volume, premium, ytd, date, source</code></p>

<h4>📎 附件</h4>
<p><code>etf_universe_raw.csv</code> (266 檔台股一般 ETF, 排除槓桿反向與海外)</p>

<hr>
<p>大寶 (agent-one) 自動產生 · 2026-08-29</p>
"""

# 4. 寄出
print(f"📧 寄出 → kadelat@gmail.com")
print(f"📎 附件 → {csv_path}")
print(f"📨 寄件人 → bt994846@sampo.com.tw (office365)")
print()

ok = send_email(
    subject=subject,
    body=body,
    to_emails="kadelat@gmail.com",
    attachments=[str(csv_path)],
)

if ok:
    print("\n✅ 寄信成功")
    sys.exit(0)
else:
    print("\n❌ 寄信失敗，請看 SMTP_mail.py 錯誤訊息")
    sys.exit(1)
