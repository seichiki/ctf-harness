# Candidate evidence / 候補の根拠

Each new run preserves every exact role proposal in `candidates.json` and `CANDIDATES.md`,
including disagreement, timeout and partial failure. Different prefixes or suffixes are
never merged. A repeated proposal from `verifier_review` remains a dependent review of
frozen reports, not another independent solve.

| Evidence grade | Recorded basis | Limit |
| --- | --- | --- |
| `target_http_observed` | A completed shell command named the authorized target and its saved output contained HTTP 2xx/3xx; the role also supplied a hashed artifact. | The response may not contain or support the proposed candidate. |
| `external_reference_access_observed` | A completed shell command named a non-target URL, or a hosted search was observed. | Tool access does not prove the report used that source. |
| `memory_hypothesis` | The role's report describes memory, a recalled answer or a guess. | Even if an artifact exists, the candidate is not live-derived evidence. |
| `local_artifact_backed_report` | A valid role report points to a regular local artifact hashed by the harness. | The model authored the artifact; its contents are not independently verified. |
| `dependent_review` | The review role consumed frozen prior reports. | It must not be counted as independent agreement. |
| `unknown` | No stronger recorded basis. | Inspect the role report and events. |

Each source retains the report path and SHA-256, artifact paths and hashes, and bounded
target HTTP status observations with event-file pointers. The catalog never claims
challenge correctness. `OWNER_CONFIRMATION.json` records a user's report that their
official submission was accepted; it is distinct from harness verification. A report's
`method`, `evidence` and `limitations` are model claims. The basis classifier uses
conservative keyword and URL-path rules and can misclassify ambiguous wording. A URL
on the target host under a clear `/writeups/`, `/solutions/`, `/walkthroughs/`, `/blog/`,
`/guide/` or `/answers/` path is treated as an external reference candidate, not as
challenge traffic merely because its host matches. Other same-host paths remain
ambiguous; inspect them manually. Prior run files are never rewritten.

## 日本語

新しい実行では不一致・時間切れ・一部失敗でも全役割の候補を正確な文字列のまま保存します。
接頭辞や末尾の違う候補を統合しません。`verifier_review` は先行レポートを読むため、
同じ候補でも独立した正答証拠には数えません。

`target_http_observed` は許可対象へのコマンドと保存された HTTP 2xx/3xx を示しますが、
候補が応答から導けたことまでは証明しません。`external_reference_access_observed` は
対象外 URL へのコマンドなどの観測、`memory_hypothesis` は記憶・推測の自己申告、
`local_artifact_backed_report` はハッシュを確認した役割内成果物、`dependent_review` は
先行レポートへの依存です。どの分類も公式正答判定ではありません。
利用者の提出成功報告は `OWNER_CONFIRMATION.json` に別記します。

役割レポートの説明はモデルの申告です。キーワードと URL パスによる分類には
曖昧さが残ります。同じホストでも明らかな writeup 等のパスは問題サーバーへの
通信として扱いません。判断しづらい場合は元のレポートとイベントを確認してください。
