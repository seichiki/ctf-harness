[English](README.md) | [日本語](README.ja.md)

# CTF ハーネス

カテゴリ別に使える、ソースコードだけで構成した Codex CLI 用ハーネスです。**自分の ChatGPT アカウントで Codex にサインイン**し、そのアカウントで利用できるモデル ID を指定します。公開版の初期設定は Daybreak **オフ**、**単体**セッションです。Daybreak Blue と複数セッションによる実行は、自分で選んだ場合だけ有効になります。API キー、有料モデル API への自動切替、フラグの自動提出、問題データ、過去の実行記録は含みません。

## Linux または Ubuntu WSL で始める

必要なものは、ChatGPT アカウントでサインインした Codex CLI 0.164.0 以降、[uv](https://docs.astral.sh/uv/)、Python 3.12 です。Codex と uv は各自で用意してください。このリポジトリはそれらをインストールせず、グローバル設定も変更しません。`./ctf-start doctor` で CLI、uv、ロックファイル、同梱スキルの不足を確認できます。モデルと推論の強度を使えるかどうかは各アカウントによって異なり、実行時に Codex が判定します。利用できなくても別のモデルへ自動的に切り替えません。

```sh
git clone https://github.com/<OWNER>/<REPO>.git
cd <REPO>
uv sync --locked                 # ローカル環境を作成。Python 3.12 がなければ取得する場合があります
codex login                      # 自分の ChatGPT アカウントでサインイン
./ctf-start doctor
./ctf-start setup --model <MODEL_ID_FROM_YOUR_ACCOUNT>
./ctf-start list
./ctf-start init --category crypto --case-id sample --scope-note 'My authorized local CTF problem'
# 選んだ問題の配布ファイルだけを categories/crypto/cases/sample/input/ に置く
./ctf-start seal --category crypto --case-id sample
./ctf-start run --category crypto --case-id sample --preset test --dry-run
./ctf-start run --category crypto --case-id sample --preset test
```

`setup` が書き込むのは、Git の対象外になっている `.local/config.toml` だけです。ここにはモデル ID、推論の強度、Daybreak の指定、実行方式を保存し、認証情報はコピーしません。設定ファイルが既にある場合は、`config.example.toml` を確認してから直接編集してください。推論の強度の初期値は `medium` です。使用モデルが対応する強度を選んでください。設定ファイルにモデル名を書いても、そのモデルを利用する権限が得られるわけではありません。`run` に `--model`、`--effort`、`--daybreak`、`--orchestration` を指定すると、その実行の全セッションでローカル設定より優先されます。

所有者が `.local/config.toml` に保存する設定例は、`./ctf-start setup --model gpt-5.6-sol --effort high --daybreak blue --orchestration multi` です。これは任意です。Blue を使えない人は `--daybreak off` のまま、自分が使えるモデルを選べます。選んだモデル、強度、アクセス区分が利用できなければ、失敗を記録して停止します。黙って別のものには切り替えません。

## 実行方式と切替設定

`--orchestration single` は新しい CLI セッションを1つ起動します。公開版の初期値です。`--orchestration multi` は、最初の検証役、並列に動く独立した2つの解答役、結果を固定してから確認する別の検証役を起動します。それぞれ別の CLI プロセスであり、Codex のネイティブなサブエージェントではありません。`--orchestration interactive` は、問題文を自動送信せずに新しい対話セッションを開きます。対話モードで Blue を使うときは、文書化された `daybreak=true` を指定したうえで、問題を入力する前に `/model` から **Daybreak Blue** を選んでください。選択状況は利用者の確認に基づいて「選択済み」または「不明」と記録します。サーバー側で適用されたことの証明にはなりません。オフの場合は `daybreak=false` と Blue ではないモデルを明示します。非対話のオフ設定では、さらに `--cyber-access-program standard` を指定します。Blue 設定では、各 `codex exec` に `daybreak_blue` を指定します。非対話実行ではグローバルのユーザー設定を読み込まず、既存の ChatGPT サインインを利用します。子 Codex プロセスへ渡す環境変数から API キーを除外します。

`--preset test` の初期値は、類似問題検索オフ・正解参照オフです。`--preset production` の初期値は、類似問題検索オン・正解参照オフです。検索はプリセットとは別に `--similar-search on|off` で切り替えられます。正解ファイルをすべての役割に渡す意図がある場合だけ、`--answer-reference on --answer-file /path/to/reference` を指定してください。設定を変えるたびに新しい実行フォルダを作ります。検索オンでは Codex 内蔵の Web 検索とローカルの `ctf-similar-search` アダプターを使い、Tavily キーや追加の API は不要です。検索オフでは `web_search=disabled` を設定し、そのアダプターを役割フォルダに配置しません。これはツールと指示の設定であり、**ネットワーク分離ではありません**。明示的に許可された問題サーバーへモデルが接続できる場合があります。実行記録と問題ファイルは Git の対象外ですが、フォルダを分けるだけでは OS レベルで他の読取可能なファイルへのアクセスを遮断できません。

外部実行では、問題ごとの制限時間は1～15分です。起動用プロンプト、CLI オプション、JSONL イベント、取得できた場合の使用量、参照した URL、候補のハッシュを記録します。`candidate_pending` は、候補の正否を**利用者が**確認する必要がある状態です。未知の配布バイナリやスクリプトをホストで直接実行せず、別途承認された隔離環境を使ってください。フラグは自動提出しません。

## ソースの対応表と公開

7カテゴリの `AGENTS.md`、スキル、実行時に生成される役割ファイルは、指示ファイルの対応表（[English](docs/INSTRUCTION-MAP.md) | [日本語](docs/INSTRUCTION-MAP.ja.md)）にまとめています。上流ソースの出典と MIT ライセンスは [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md) を参照してください。Python の外部依存パッケージはなく、uv のロックファイルを同梱しています。カテゴリ固有のツールは任意で、選んだ問題に必要になったときだけ別途インストールしてください。

ソースだけを新規公開する場合は、内容を確認してから自分のアカウントに空の GitHub リポジトリを作り、以下をローカルで実行します。URL は自分のリポジトリに置き換えてください。既にこのプロジェクトを push した場合は、現在の Git リポジトリとリモートを使い、`git init` と `git remote add origin` を省いてください。ハーネスを実行するだけで GitHub にアップロードされることはありません。

```sh
cd ~/ctf/ctf-harness
git init -b main
git status --short
git ls-files --others --exclude-standard
git check-ignore -v categories/crypto/cases/sample/input/problem.txt
git add -n .                    # 追加予定のソースファイルをすべて確認
git add .
git commit -m 'Initial CTF harness'
git remote add origin https://github.com/<OWNER>/<REPO>.git
git push -u origin main
```

Git の対象外のファイルを `-f` で強制追加しないでください。`.gitignore` では、既にコミットした秘密情報を履歴から消せません。その場合は新しいソース専用リポジトリを使ってください。既存リポジトリで README を更新する場合は、コミットと既存リモートへの push の前に `git status --short` と `git add -n .` で変更を確認してください。

後から所有者の `~/ctf/daybreak-blue` に配置する場合は、新しいリポジトリとクローンを確認したうえで [docs/MIGRATION.md](docs/MIGRATION.md) の手順に従ってください。この README の追加作業では、旧プロジェクトの移動や削除は行いません。
