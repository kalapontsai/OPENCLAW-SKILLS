# OPENCLAW-SKILLS

精選的 OpenClaw skills 集合。每個 skill 是**獨立分支**(branch),用 `git clone -b <branch>` 抓單一 skill 即可。

## Skill 索引

| # | Skill (branch) | 用途 | Owner |
|---|-------|------|-------|
| 1 | [agent-cowork](https://github.com/kalapontsai/OPENCLAW-SKILLS/tree/agent-cowork/agent-cowork) | 跨 agent 檔案型訊息協議（v1.3）+ 三方互動章節（flags.awaiting-decision）+ bulletin UI 實作 | agent-one (agent-one) |
| 2 | [agents-bulletin](https://github.com/kalapontsai/OPENCLAW-SKILLS/tree/agents-bulletin/agents-bulletin) | agents-bulletin 三方互動 UI 實作（depends-on agent-cowork） | agent-one (agent-one) |
| 3 | [stock-scoring-rebalancer](https://github.com/kalapontsai/OPENCLAW-SKILLS/tree/stock-scoring-rebalancer/stock-scoring-rebalancer) | ETF/股票歷史回測評分 + 半年 rebalance SOP（generic 範本） | agent-one (fund-plan) |
| 4 | [livestream-recorder](https://github.com/kalapontsai/OPENCLAW-SKILLS/tree/feat/livestream-recorder/livestream-recorder) | 多小時直播錄製（yt-dlp + ffmpeg + OpenClaw cron 心跳監控） | 大寶 |

## 安裝（單一 skill）

每個 skill 是獨立分支,只 clone 一個 branch:

```
# 範例：抓 livestream-recorder
git clone -b feat/livestream-recorder --single-branch \
  https://github.com/kalapontsai/OPENCLAW-SKILLS.git \
  /tmp/openclaw-skills-tmp

cp -r /tmp/openclaw-skills-tmp/livestream-recorder \
  ~/.openclaw/workspace/skills/livestream-recorder
```

或直接從 branch 下載 zip:

```
https://github.com/kalapontsai/OPENCLAW-SKILLS/archive/refs/heads/feat/livestream-recorder.zip
```

放到 `~/.openclaw/workspace/skills/<branch-name>/` 後重啟 OpenClaw gateway 即生效。branch 名稱跟 skill 名稱相同。

## Branch 列表

```
main                       僅 README + LICENSE（本檔）
agent-cowork               agent-cowork skill（branch 根目錄就是 skill）
agents-bulletin            agents-bulletin skill
stock-scoring-rebalancer   stock-scoring-rebalancer skill
feat/livestream-recorder   livestream-recorder skill
```

每個 skill branch 的**根目錄**就是 skill 內容(已把子目錄 wrapper 拿掉)。
所以 clone 下來直接 `cp -r <clone-dir>/* ~/.openclaw/workspace/skills/<branch-name>/` 即可。

## 貢獻

每個 skill 由各自的維護 agent 負責。修改前請先在 `agent-cowork` 開 thread 通知主維護者，或在 agent 自己的 workspace 開本地工單。

每個 skill 一個 branch 讓安裝、版本控管、回滾都更單純。

## License

MIT
