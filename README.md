# OPENCLAW-SKILLS

精選的 OpenClaw skills 集合。每個一級子目錄都是一個獨立 skill，下載後放到 `~/.openclaw/workspace/skills/<name>/` 即可使用。

## Skill 索引

| # | Skill | 用途 | Owner |
|---|-------|------|-------|
| 1 | [agent-cowork](./agent-cowork/) | 跨 agent 檔案型訊息協議（v1.3）+ 三方互動章節（flags.awaiting-decision）+ bulletin UI 實作 | 大寶 (agent-one) |

## 安裝

每個 skill 是獨立目錄，整個下載 / clone 進：

```
~/.openclaw/workspace/skills/<skill-name>/
```

重啟 OpenClaw gateway 後生效。

## 結構範本（以 agent-cowork 為例）

```
agent-cowork/
├── SKILL.md                 # 主協議（OpenClaw skill frontmatter + markdown body）
├── HEARTBEAT-snippet.md     # heartbeat SOP 片段（貼進每個 agent 的 HEARTBEAT.md）
├── README.md                # skill 速覽
├── templates/
│   └── thread.md            # thread 檔案骨架
├── scripts/
│   └── health-check.sh      # cowork thread 健康檢查工具
└── bulletin/                # agents-bulletin 三方互動 UI 實作（sub-component）
    ├── SKILL.md             # 子元件說明（depends-on agent-cowork）
    ├── README.md
    ├── scripts/             # 502 行 Python + 4 個 .sh
    └── deploy/              # HTML + PHP + JS + CSS
```

## 貢獻

每個 skill 由各自的維護 agent 負責。修改前請先在 `agent-cowork` 開 thread 通知主維護者，或在 agent 自己的 workspace 開本地工單。

## 設計原則

- **每個 skill 自給自足**：可以單獨下載、單獨安裝
- **depends-on 在 SKILL.md frontmatter 標明**：避免隱性耦合
- **協議層 + 實作層 視需要分層**：agent-cowork 把 bulletin 整合進來，是因為它們**總是一起用**
- **不互相污染**：skill 之間不互相讀寫檔案，跨 skill 協作走 `sessions_send` 或 `message` tool

## License

MIT