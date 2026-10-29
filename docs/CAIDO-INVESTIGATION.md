# Caido proxy investigation / Caido 経由の通信調査

## Observed historical failures / 過去の観測

- `categories/web/runs/head-dump/20261028T175759Z-multi-d3b5a4/` contained an HTTP **400** response during a proxied request. This is an HTTP response, not proof that the target or the proxy rejected a particular header.
- `categories/web/runs/cookie-monster-secret-recipe-20261028185222-e5dffa/20261028T185333Z-multi-3d58ac/` contained HTTP **502** and `Connection refused` diagnostics from solver roles. A 502 and a refused connection are separate observations; either may reflect the proxy, upstream, timing, or request details. The old endpoint was not reused.

The harness now records bounded counts of these response/error markers in `result.json` under `proxy_http_observations`, by role. A process exit code of zero for `curl` does not establish HTTP success. The detector saves no response bodies, cookies, or proxy URL.

## Controlled local check / ローカルでの検証

A harmless local HTTP fixture was requested directly and through the configured Caido proxy. HEAD and GET, an approximately 11.5 MB GET, two concurrent GETs, and equivalent curl HEAD/GET/large GET checks returned HTTP **200** through both paths. A deliberately malformed local proxy request caused a connection reset, rather than reproducing the historical 400. This check shows that the currently configured proxy can handle those local request shapes. It does **not** identify the exact cause of the earlier 400, 502, or refused connection. Those events may depend on the original request or an expired upstream service; no historical live target was contacted again.

For a new authorized run, inspect the role's sanitized `events.jsonl` command and status, `proxy_http_observations`, and Caido's local request log at the same time. Compare the same fresh endpoint through the explicitly selected direct or proxy path only within the problem's scope. `--no-proxy` clears inherited HTTP(S), ALL and NO proxy variables in that one Codex process and its spawned shells; it can also change Codex API routing for that invocation. It does not alter global settings. A saved proxy setting does not silently fall back to direct access if its local TCP preflight fails. No TLS verification or certificate policy was weakened.

日本語: 以前の HTTP 400、HTTP 502、接続拒否は実際に記録されていますが、原因は確定していません。現在の Caido を使うローカル再現では通常の HEAD/GET、大きい応答、同時 GET は成功し、過去の失敗は再現しませんでした。`result.json` の `proxy_http_observations` は原因判定ではなく観測件数です。次回は新しい許可済みインスタンスで、同時刻のコマンド・HTTP 状態・Caido ログを照合してください。
