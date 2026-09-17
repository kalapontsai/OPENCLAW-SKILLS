<?php
/**
 * refresh.php — 點擊刷新按鈕。
 * 寫一個 trigger 檔到 data/，warden 看到會跑 sync_bulletin.py。
 */
header('Content-Type: application/json; charset=UTF-8');
$trigger = __DIR__ . '/../data/.refresh-trigger';
$payload = json_encode(['requested_at' => date('c')], JSON_UNESCAPED_UNICODE);
$ok = @file_put_contents($trigger, $payload);

echo json_encode([
  'ok' => (bool)$ok,
  'queued_at' => date('c'),
  'note' => 'warden 將在 1-2 秒內同步；前端會自動輪詢 manifest',
], JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
