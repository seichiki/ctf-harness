[English](INSTRUCTION-MAP.md) | [日本語](INSTRUCTION-MAP.ja.md)

# 指示ファイルと設定の対応表

ルートの `AGENTS.md` は、すべての問題に適用されます。各カテゴリには、そのカテゴリ用の `AGENTS.md` と、Codex が検出できる `.agents/skills/ctf-<category>/SKILL.md` があります。アダプターは、必要な場合に固定版の上流 Markdown 資料を開くよう Codex に指示します。`third_party/` 内の上流ファイル自体が有効なスキルとして登録されるわけではありません。

| カテゴリ | カテゴリの指示ファイル | 検出対象のアダプター | 固定版の参照資料 |
| --- | --- | --- | --- |
| web | `categories/web/AGENTS.md` | `categories/web/.agents/skills/ctf-web/SKILL.md` | `third_party/ctf-skills/ctf-web/SKILL.md` |
| crypto | `categories/crypto/AGENTS.md` | `categories/crypto/.agents/skills/ctf-crypto/SKILL.md` | `third_party/ctf-skills/ctf-crypto/SKILL.md` |
| pwn | `categories/pwn/AGENTS.md` | `categories/pwn/.agents/skills/ctf-pwn/SKILL.md` | `third_party/ctf-skills/ctf-pwn/SKILL.md` |
| reverse | `categories/reverse/AGENTS.md` | `categories/reverse/.agents/skills/ctf-reverse/SKILL.md` | `third_party/ctf-skills/ctf-reverse/SKILL.md` |
| forensics | `categories/forensics/AGENTS.md` | `categories/forensics/.agents/skills/ctf-forensics/SKILL.md` | `third_party/ctf-skills/ctf-forensics/SKILL.md` |
| osint | `categories/osint/AGENTS.md` | `categories/osint/.agents/skills/ctf-osint/SKILL.md` | `third_party/ctf-skills/ctf-osint/SKILL.md` |
| misc | `categories/misc/AGENTS.md` | `categories/misc/.agents/skills/ctf-misc/SKILL.md` | `third_party/ctf-skills/ctf-misc/SKILL.md` |

`config.example.toml` は、持ち運べるローカル設定の見本です。`./ctf-start setup` は、Git の対象外である `.local/config.toml` を書き込みます。公開ソースには、特定のアカウントのモデル設定や Blue の利用権限は含まれません。`harness/config.py` は設定を検証し、`harness/runner.py` は指定値を明示した CLI コマンドを組み立て、`harness/report.py` は証拠と成果物のパスを検証します。`harness/cli.py` はメニューとサブコマンドを提供します。`docs/report.schema.json` は構造化レポートのひな形です。

外部実行では、`-C categories/<category>/runs/<case>/<run>/<role>` を指定します。`harness/runner.py` が共通指示と役割別指示からプロンプトを組み立て、役割フォルダの `prompt.txt` に保存します。実際の CLI オプションは、プロンプトを除いて `invocation.json` に保存します。単体モードの役割は `solver` です。複数モードには `verifier`、`solver_a`、`solver_b`、`verifier_review` があり、`frozen-reports.json` を受け取るのは最後の役割だけです。実行単位の `settings.json`、`output-schema.json`、`result.json` には、選択した設定、入力用スキーマ、最終候補の状態を記録します。各役割の `events.jsonl`、`run.json`、`structured-report.json` は、Git の対象外である実行フォルダに保存します。

対話モードは `.../<run>/interactive/` を作り、選択した問題の入力と、明示的に指定された場合だけ参照ファイルをコピーします。選んだ実行設定の指示は、その役割フォルダの `AGENTS.md` に書き込みます。`invocation.json` には、問題文を含まない対話 CLI の起動コマンドを記録します。Blue を要求した場合は、利用者がメニューから Blue を手動で選びます。実行単位の設定には、その選択を利用者の申告として記録します。サーバー側での適用を証明するものではありません。

テスト用の初期値は検索・正解参照ともオフ、本番用の初期値は検索オン・正解参照オフです。`--similar-search on` は `skill_templates/ctf-similar-search/SKILL.md` を実行フォルダ内の `.agents/skills/ctf-similar-search/SKILL.md` にコピーし、`web_search=live` を設定します。オフではこのアダプターを配置せず、`web_search=disabled` を設定します。`--answer-reference on --answer-file PATH` は、明示的に指定したファイルだけを各役割の `reference/answer.txt` にコピーします。オフではコピーしません。モードを変えるたびに、新しい CLI セッションと実行フォルダを用意します。問題の入力、正解、役割の出力、ローカルのアカウント設定は Git に含めません。
