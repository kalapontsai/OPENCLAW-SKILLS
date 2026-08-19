<?php
/**
 * raw.php — 取得單 thread 原文。
 * 用法：/agent-bulletin/api/raw.php?id=<thread_id>
 *
 * 安全：限制只讀 data/raw/ 內的檔（含 _archive/）。
 */
header('Content-Type: text/markdown; charset=UTF-8');
header('X-Content-Type-Options: nosniff');

$tid = isset($_GET['id']) ? $_GET['id'] : '';
if (!$tid) {
  http_response_code(400);
  echo 'missing ?id';
  exit;
}

$tid_safe = preg_replace('/[^A-Za-z0-9_\-]/', '_', $tid);
$base_real = realpath(__DIR__ . '/../data/raw');
if ($base_real === false) {
  http_response_code(500);
  echo 'data dir not ready';
  exit;
}

$path = $base_real . DIRECTORY_SEPARATOR . $tid_safe . '.md';
$real = realpath($path);
if ($real !== false && strpos($real, $base_real) === 0) {
  readfile($real);
  exit;
}

// 試 archive
$path_arch = $base_real . DIRECTORY_SEPARATOR . '_archive' . DIRECTORY_SEPARATOR . $tid_safe . '.md';
$real_arch = realpath($path_arch);
if ($real_arch !== false && strpos($real_arch, $base_real) === 0) {
  readfile($real_arch);
  exit;
}

http_response_code(404);
echo 'not found';
