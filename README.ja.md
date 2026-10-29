[English](README.md) | [日本語](README.ja.md)

# CTF ハーネス

カテゴリ別に使える、ソースコードだけで構成した Codex CLI 用ハーネスです。**自分の ChatGPT アカウントで Codex にサインイン**し、そのアカウントで利用できるモデル ID を指定します。公開版の初期設定は Daybreak **オフ**、**単体**セッション、サンドボックスの外向き通信 **オフ** です。Daybreak Blue、複数セッション、外向き通信は明示的に選んだ場合だけ有効になります。API キー、有料モデル API への自動切替、フラグの自動提出、問題データ、過去の実行記録は含みません。

## Linux または Ubuntu WSL で始める

必要なものは、ChatGPT アカウントでサインインした Codex CLI 0.164.0 以降、[uv](https://docs.astral.sh/uv/)、Python 3.12 です。Codex と uv は各自で用意してください。このリポジトリはそれらをインストールせず、グローバル設定も変更しません。`./ctf-start doctor` で CLI、uv、ロックファイル、同梱スキルの不足を確認できます。モデルと推論の強度を使えるかどうかは各アカウントによって異なり、実行時に Codex が判定します。利用できなくても別のモデルへ自動的に切り替えません。

```sh
git clone https://github.com/<OWNER>/<REPO>.git
cd <REPO>
uv sync --locked                 # ローカル環境を作成。Python 3.12 がなければ取得する場合があります
codex login                      # 自分の ChatGPT アカウントでサインイン
./ctf-start doctor
./ctf-start setup --model <MODEL_ID_FROM_YOUR_ACCOUNT>
./ctf-start                     # 新しい問題のウィザード
```

引数なしの `./ctf-start` は新規問題から始まります。カテゴリと問題名を入力すると、ケース ID が自動生成され、下書きフォルダがすぐに作成されます。続いて `配布ファイル保存先：<ケース>/input/files` と `Enterで完了` の２行を表示します。配布ファイルがあれば自分でその場所に置き、Enter を押してください。なくても空のまま Enter で進めます。配置されたファイルの一覧を確認してから、問題文をその場で複数行入力し、単独行の `/end` で終えます。ローカル問題か許可済みライブ接続先、正の整数で指定する制限時間（初期値15分、固定上限なし）、test または production を選びます。最後の設定を確認し、`RUN` を入力した場合だけ封印して実行します。保存設定のネットワークがオフでライブ接続先を選ぶ場合、その１回だけ `ENABLE` が必要です。`RUN` 前の `/cancel`、EOF、Ctrl-C は、作成済みの下書きを残して終了し、モデルや接続先へ要求しません。対話端末で起動してください。実行後は、作成されていれば `引継ぎファイル：...`、続いて `ログ保存先：...` を表示します。

既存ケースの再実行やアーカイブ・復元は明示的なコマンドで行います。自動処理や手作業での準備には次を使えます。

```sh
./ctf-start list
./ctf-start init --category crypto --case-id sample --scope-note 'My authorized local CTF problem'
# 問題文と配布ファイルを categories/crypto/cases/sample/input/ に置く
./ctf-start seal --category crypto --case-id sample
./ctf-start run --category crypto --case-id sample --preset test --dry-run
./ctf-start run --category crypto --case-id sample --preset test
```

`setup` が書き込むのは、Git の対象外になっている `.local/config.toml` だけです。モデル ID、推論の強度、Daybreak、実行方式、ネットワーク、進行表示、任意の HTTP プロキシを保存し、認証情報はコピーしません。古い設定ファイルで新しい項目がなければ安全側の初期値（`network_access = "off"`、`progress = false`、`proxy_url = ""`）を使います。設定ファイルが既にある場合は、`config.example.toml` を見て直接編集してください。`setup` は上書きしません。モデル名を保存しても利用権限は得られません。`run` の `--model`、`--effort`、`--daybreak`、`--orchestration`、`--network-access off|on`、`--progress` / `--no-progress`、`--proxy URL` / `--no-proxy` は、その1回だけ保存値に優先します。

個人設定を保存した後は `./ctf-start` で新しい問題を作成・実行できます。封印済みケースを再実行するには `./ctf-start run --category web --case-id <既存ケースID> --preset test` を使います。自動処理などで表示を抑えるときは明示的な `run` に `--quiet` を付けます。起動時の設定表示と進行表示を止め、最後の JSON は標準出力に残します。通常の明示的実行では要求設定を標準エラーへ短く表示します。プロキシはオン・オフだけを示し、URL は表示しません。実問題に接続する前に dry-run で計画を確認してください。

所有者が `.local/config.toml` に保存する設定例は、`./ctf-start setup --model gpt-5.6-sol --effort high --daybreak blue --orchestration multi` です。これは任意です。Blue を使えない人は `--daybreak off` のまま、自分が使えるモデルを選べます。選んだモデル、強度、アクセス区分が利用できなければ、失敗を記録して停止します。黙って別のものには切り替えません。

各外部実行は、実行フォルダに `HANDOFF.md` を早期に作成し、進行表示がオフでも役割・ツールの節目で更新します。ケースの許可範囲、要求設定、マスク済みコマンドと終了状態、役割ごとの候補やレポート不在、根拠ファイルの相対パスを１つにまとめます。チャレンジの正解を保証するものではありません。認証情報のマスクは最善努力で、解析済み CTF 候補は報告されたまま示します。共有前に内容を確認してください。配布バイナリや完全なログは参照するだけで埋め込まず、別の環境へ引き継ぐ場合は必要なファイルも一緒にコピーしてください。強制終了や停電では最後に書き終えた時点の内容だけが残る場合があります。
対話セッションにも設定と終了状態の基本的な引継ぎファイルを作りますが、Codex の対話 UI 内で行った操作はハーネスでは記録しません。

新規問題ウィザードの外部実行中は、有効な役割レポートから出た候補に `C1` などの ID を付けて表示します。公式画面への提出は自分で行ってください。その**候補全文**が正解だった場合、実行中の同じ端末で `solved` と入力し、候補 ID と全文を確認して `ACCEPT C1` と入力します。モデルの発言やツール出力から自動的に正解扱いにはしません。確認後に `OWNER_CONFIRMATION.json` を保存し、`SOLUTION.md` の生成を試みてから、この実行に属する残りの Codex 子プロセスを停止して、`result.json` に `user_confirmed` と記録します。これは**ユーザーによる公式提出の正解報告**であり、ハーネスがサーバーで検証した意味ではありません。`SOLUTION.md` は記録されたコマンドの開始・終了と、役割が報告した手法・根拠・再現コマンド・制約を区別してまとめます。存在しない出力や手順は補いません。完全な writeup には元の入力ファイルとイベントログも保存してください。既存ケースの明示的な `run` でも使うなら、対話端末で `--owner-confirmation` を追加します。初期値はオフで、`--quiet` や対話オーケストレーションとは併用できません。未確認のまま Ctrl-C を押した場合は中止扱いです。
子プロセスの停止前に `OWNER_CONFIRMATION.json` を原子的に保存します。`SOLUTION.md` の生成だけに失敗した場合も正解報告と元の役割ログが残り、終了処理で再生成を試みます。正解報告自体を保存できなければ、停止も正解扱いもしません。この操作は最前面の端末からのみ受け付け、入力は Codex 子プロセスへ渡しません。

## 実行方式と切替設定

`--orchestration single` は新しい CLI セッションを1つ起動します。公開版の初期値です。`--orchestration multi` は、最初の検証役、並列に動く独立した2つの解答役、結果を固定してから確認する別の検証役を起動します。それぞれ別の CLI プロセスであり、Codex のネイティブなサブエージェントではありません。`--orchestration interactive` は、問題文を自動送信せずに新しい対話セッションを開きます。対話モードで Blue を使うときは、文書化された `daybreak=true` を指定したうえで、問題を入力する前に `/model` から **Daybreak Blue** を選んでください。選択状況は利用者の確認に基づいて「選択済み」または「不明」と記録します。サーバー側で適用されたことの証明にはなりません。オフの場合は `daybreak=false` と Blue ではないモデルを明示します。非対話のオフ設定では、さらに `--cyber-access-program standard` を指定します。Blue 設定では、各 `codex exec` に `daybreak_blue` を指定します。非対話実行ではグローバルのユーザー設定を読み込まず、既存の ChatGPT サインインを利用します。子 Codex プロセスへ渡す環境変数から API キーを除外します。

`--preset test` の初期値は、類似問題検索オフ・正解参照オフです。`--preset production` の初期値は、類似問題検索オン・正解参照オフです。検索はプリセットとは別に `--similar-search on|off` で切り替えられます。正解ファイルをすべての役割に渡す意図がある場合だけ `--answer-reference on --answer-file /path/to/reference` を指定してください。設定を変えるたびに新しい実行フォルダを作ります。検索オンでは Codex 内蔵の Web 検索とローカルの `ctf-similar-search` アダプターを使い、Tavily キーや追加の API は不要です。検索オフでは `web_search=disabled` を設定し、そのアダプターを役割フォルダに配置しません。検索・正解参照の設定とサンドボックスの外向き通信は独立しています。実行記録と問題ファイルは Git の対象外ですが、フォルダを分けるだけでは OS レベルで他の読取可能なファイルへのアクセスを遮断できません。

外向き通信はすべてのプリセットで初期値オフです。許可済みの実問題で使うときは `./ctf-start run --category web --case-id <新しいケースID> --preset test --network-access on --dry-run` で確認し、`--dry-run` を外して実行します。オンは各役割の `sandbox_workspace_write.network_access=true` を、オフは `false` を要求します。**オンにしても問題サーバーだけに通信先を限定するわけではありません**。ケースの対象指定は指示であり、通信先を強制するファイアウォールではありません。dry-run、`settings.json`、`result.json` は要求した設定を記録しますが、実効的な通信許可の証明ではありません。ハーネスは `approval_policy=on-request` を要求しますが、Codex CLI 0.164.0 の非対話 `codex exec` で `approval: never` と表示された実例があります。外部実行で承認プロンプトが出ることを前提にしないでください。`workspace-write` サンドボックスを維持し、失敗しても制限の緩い方式へ切り替えません。

外部実行では、問題ごとの制限時間は正の整数の分数で、初期値は15分、固定上限はありません。multi の全役割で同じ期限を共有します。起動用プロンプト、CLI オプション、JSONL イベント、取得できた場合の使用量、参照した URL、候補のハッシュを記録します。`candidate_pending` は、候補の正否を**利用者が**確認する必要がある状態です。未知の配布バイナリやスクリプトをホストで直接実行せず、別途承認された隔離環境を使ってください。フラグは自動提出しません。

外部実行の状況を見るには、個人設定で `progress = true` とするか、その1回だけ `--progress` を付けます。保存値が true でも `--no-progress` で一時停止できます。役割の開始・終了、コマンドやツールの開始・結果を経過時間付きで**標準エラー出力**に表示し、最後の JSON は従来どおり標準出力に出します。コマンド開始時には通常の引数や URL を含む実コマンドを示し、イベント ID で終了状態・終了コードと対応付けます。各役割のレポート解析後すぐに、候補の原文、正しい形式の空候補、または有効なレポートがない旨を表示します。コマンドの生出力、エージェントの発言、非公開の推論は自動表示しません。端末制御文字を除去し、一般的な認証ヘッダー、Cookie、パスワード、トークン、機密性の高い URL パラメータをマスクします。**マスクは最善努力で、漏えいしない保証ではありません**。進行表示は自分だけが見られる端末で使ってください。表示が420文字を超えるコマンドは省略を明示します。候補フラグは報告された文字列をそのまま表示し、認証情報向けマスクをかけません。完全な JSONL イベントは各役割の実行フォルダに保存され、機密情報を含む可能性があります。Codex がイベントを書き込むまで表示できず、常に連続して更新される保証はありません。プロセスの強制終了や停電では最後の状態行を出せません。

`proxy_url` は任意で、初期値は空です。通常実行に Caido は不要です。認証情報を含まない `http://host:port` を保存してネットワークをオンにした場合、開始前と各役割の開始前に TCP 接続を確認します。接続できなければ直接通信へ切り替えず停止します。Codex の `shell_environment_policy.set` で起動後のシェルコマンドに HTTP(S) プロキシ変数を渡し、その実行の Codex/API 親プロセスには継承したプロキシ変数を渡しません。グローバル設定や Codex/OpenAI/DeepSeek の API 通信先は変更しません。変数を無視するツールもあるため、全通信の強制転送やファイアウォールにはなりません。子プロセスの生のイベント・stderr ファイルには問題の機密情報が含まれ得ます。Caido で HTTPS を中継する場合は、対象アクセスに使うツールが Caido の証明書を信頼する必要があります。必要なら隔離環境内でそのツール向けに設定し、TLS 検証を無効化したりグローバル CA を追加したりしないでください。Codex の Web 検索やシェル以外のツールは対象外です。設定の根拠は [Codex 設定資料](https://developers.openai.com/codex/config-reference) を参照してください。

## 問題データのアーカイブと復元

`archive` は選んだカテゴリの問題入力と実行履歴を一緒に移します。全カテゴリは `--all-categories` を明示した場合だけ対象です。初期動作はプレビューで、`--confirm` を付けたときだけ移動します。問題データは削除しません。保存先は `archives/<日時-ID>/` で、`manifest.json` に元の場所と保存先を記録します。`archives/` は Git の対象外です。成功後、対象カテゴリの `categories/<カテゴリ>/cases/` と `runs/` は空で使える状態になります。個人設定の `.local/`、ツール、スキル、ソース、`.venv/`、Git 履歴は触りません。

```sh
./ctf-start archive --category web --dry-run
./ctf-start archive --category web --confirm
./ctf-start archive --all-categories --dry-run   # 全カテゴリは先に確認
./ctf-start archive --all-categories --confirm   # 確認後のみ
./ctf-start archives
./ctf-start restore --archive-id <archivesで表示されたID> --dry-run
./ctf-start restore --archive-id <archivesで表示されたID> --confirm
```

復元は、移動先の問題入力・実行履歴が空でない場合に拒否します。新しいランチャーで実行中のカテゴリも、共通ロックによりアーカイブ・復元を拒否します。以前の版で開始したプロセスはロックを持たない可能性があるため、終了を確認してください。対象データ内にシンボリックリンクがあれば拒否します。移動の途中で元へ戻せなくなった場合は `archives/.pending-<id>/manifest.json` と移動済みデータを残します。再試行の前にそのフォルダと元の場所を確認してください。完全削除コマンドはありません。

## ソースの対応表と公開

7カテゴリの `AGENTS.md`、スキル、実行時に生成される役割ファイルは、指示ファイルの対応表（[English](docs/INSTRUCTION-MAP.md) | [日本語](docs/INSTRUCTION-MAP.ja.md)）にまとめています。上流ソースの出典と MIT ライセンスは [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md) を参照してください。カテゴリ別 Python パッケージは pyproject.toml で宣言し、uv.lock で固定しています。uv sync --locked は指定された全カテゴリの依存をプロジェクト内 .venv に導入します。外部のネイティブツールは別に確認します。

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

### カテゴリ別 Python 環境と候補の根拠

クローン後または依存更新後に `uv sync --locked` を実行します。`./ctf-start` は `uv run --offline --locked`、各役割は作業フォルダから `uv run --no-cache --offline --locked --no-sync python` を使います。全カテゴリの依存グループが既定で有効なので、通常の同期で別カテゴリのパッケージが消えません。問題実行中にパッケージを追加しないでください。明示的に追加したものは Web: `httpx`, `beautifulsoup4`, `lxml`、Crypto: `pycryptodome`, `sympy`、Pwn: `pwntools`、Reverse: `z3-solver`, `capstone`, `pyelftools`, `pefile`、Forensics: `Pillow`, `scapy`, `exifread`, `pypdf`、OSINT: `dnspython`、Misc: `regex` です。正確なバージョンと間接依存は `uv.lock` に固定しています。Ghidra や GDB などの外部ツールは Python import とは別に確認します。

各実行は不一致や一部失敗でも `candidates.json` と `CANDIDATES.md` に全役割の候補を保存します。文字列が異なる候補は統合せず、役割、報告された根拠の種類、レポートと成果物のパスを残します。`memory_hypothesis` は役割レポートが記憶や推測による候補と述べたものです。その他の分類もハーネスによる正答検証ではありません。レビュー役は先行レポートを読むため独立証拠ではありません。従来の合意または利用者確認済み出力は `candidate.txt` に維持します。`reference-assisted` は対象外 URL への成功したシェルコマンドか完了した外部検索を観測した場合に限ります。問題サーバーの URL だけではこの分類にしません。宣言された外部 URL でもアクセスを観測できない場合は `external-reference-declared-unverified` です。

プロキシ有効時は HTTP 400、HTTP 502、接続拒否の観測回数を役割別に `result.json` に残します。シェル終了コードが 0 でも HTTP エラーの場合があります。回数だけでは 400 を返した主体や上流接続拒否の原因は確定できません。元のイベントとプロキシログを非公開で確認してください。ローカルの検証用 HTTP サーバーでは HEAD、GET、大きな GET、並列 GET を試しますが、過去の対象固有の失敗までは証明できません。
`./ctf-start tools --category reverse --missing-only --json` は Python import、外部コマンド、REA/Ghidra の状態を読み取り専用で一覧表示します。全カテゴリを見るには `--category` を省略します。`available`、`missing`、`misconfigured`、`incompatible`、`untested` を区別し、ツールを自動インストールしません。任意の外部ツールは必要になるまで未導入でも構いません。

Reverse の問題では、プロジェクト内の `rea-static` を REA/Ghidra の窓口として使います。固定した外部ツールが不足している場合はモデル起動前に停止します。[導入方法と対象範囲](docs/REA-GHIDRA.md)を参照してください。広い MCP サーバーは登録しません。

明示的な `--no-proxy` は、その1回の Codex プロセスと子シェルから継承された HTTP(S)・ALL・NO プロキシ変数を除外します。Codex API の経路にも影響する場合があります。グローバル設定は変更しません。過去の HTTP エラーとローカル検証の限界は [Caido 調査](docs/CAIDO-INVESTIGATION.md) を参照してください。
このホストでは実際の Codex 子プロセスを network OFF で動かした際、Ghidra のローカル Unix ソケットが拒否されました。このプロファイルでの REA 連携は未達です。詳細は [REA/Ghidra の手順](docs/REA-GHIDRA.md) を参照してください。

所有者が許可した1回限りの network ON 検証では、実際の Codex 子プロセスから自作 ELF の REA/Ghidra 逆コンパイルが成功しました。network OFF ではローカル Unix ソケットが拒否されたままです。network ON は外部ホストへの通信も可能にするため、この結果を他の設定や実問題の保証と解釈しないでください。
Ubuntu 26.04 x86-64 WSL の Pwn・Forensics 用外部ツールは `./scripts/setup-native-tools.sh` でクローン内に導入できます。`./ctf-start tools --missing-only --json` で版を確認し、`uv run --offline --locked --no-sync python scripts/native_smoke.py` でローカル試料を確認します。対象は GDB、socat、ExifTool、TShark、Binwalk 3、7-Zip、unzip です。sudo やグローバル PATH の変更はありません。[機能と制限](docs/NATIVE-TOOLS.md) を参照してください。

`./ctf-start tools` は現在の導入・版・プロバイダー診断だけを表示します。保存済みの REA/Codex 過去テストは通常表示・`--missing-only`・JSON のどれにも出しません。`available` は将来の子サンドボックス動作まで保証しません。
