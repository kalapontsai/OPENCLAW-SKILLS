<?php
/**
 * answer.php — 接收 Q&A 寫回。
 * body: {thread_id, action: 'answer'|'instruction'|'request_close', text, decision?}
 * → 寫 data/.writeback-<thread_id>.json，warden 撿到後 append 到 thread。
 */
header('Content-Type: application/json; charset=UTF-8');

$body = json_decode(file_get_contents('php://input'), true);
if (!$body) {
  http_response_code(400);
  echo json_encode(['ok' => false, 'error' => 'invalid json'], JSON_UNESCAPED_UNICODE);
  exit;
}

$tid = isset($body['thread_id']) ? preg_replace('/[^A-Za-z0-9_\-]/', '_', $body['thread_id']) : '';
$action = isset($body['action']) ? $body['action'] : 'answer';
$text = isset($body['text']) ? trim($body['text']) : '';
$decision = isset($body['decision']) ? $body['decision'] : null;

if (!$tid || !$text) {
  http_response_code(400);
  echo json_encode(['ok' => false, 'error' => 'thread_id + text required'], JSON_UNESCAPED_UNICODE);
  exit;
}

if (!in_array($action, ['answer', 'instruction', 'request_close'], true)) {
  http_response_code(400);
  echo json_encode(['ok' => false, 'error' => 'invalid action'], JSON_UNESCAPED_UNICODE);
  exit;
}

$payload_file = __DIR__ . '/../data/.writeback-' . $tid . '.json';
$payload = [
  'thread_id' => $tid,
  'action' => $action,
  'text' => $text,
  'decision' => $decision,
  'submitted_at' => date('c'),
];
$ok = @file_put_contents(
  $payload_file,
  json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT)
);

if (!$ok) {
  http_response_code(500);
  echo json_encode(['ok' => false, 'error' => 'cannot write payload'], JSON_UNESCAPED_UNICODE);
  exit;
}

echo json_encode([
  'ok' => true,
  'queued_at' => date('c'),
  'payload' => basename($payload_file),
  'note' => 'warden 撿到後會 append 到 thread 檔；前端會自動同步',
], JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);
