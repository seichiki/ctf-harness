# 不足ツールの導入

新しいクローンでは、最初に uv と Python 3.12 を用意します。

```sh
./ctf-start tools --missing-only
./ctf-start tools install
# または ./ctf-start tools install --all
# または ./ctf-start tools install --required
```

オプションなしの導入画面には現在不足・非互換・設定不備の項目だけが表示されます。上下キーで移動、Space でチェック、Enter で選択完了、Esc または Ctrl+C で中止します。`--all` は不足項目すべて、`--required` は必須項目だけです。両方は併用できません。すべてのモードで計画を表示し、最後に `INSTALL` と入力して初めて開始します。非対話端末からは導入を始めません。

進捗バーの1単位は1つの導入処理で、ダウンロード量ではありません。完了・失敗・スキップした単位を数えます。STARTED/COMPLETED/FAILED/SKIPPED を逐次表示し、実行中のマスク済み出力と無出力時の経過通知も表示します。要約と単位別ログは Git 対象外の `.local/install-runs/<timestamp-id>/` に保存します。途中失敗後は `./ctf-start tools --missing-only` で現在の状態を再確認してください。中断するとインストーラー自身が起動した子プロセス群だけを停止し、既に導入されたファイルは残します。

導入画面は `uv run --no-project --offline --python 3.12` で起動するため、カテゴリ用 `.venv` がなくても開きます。Python の全7カテゴリは `uv sync --locked` の1単位で、1つを選んでもロックされた全グループを同期します。REA/Ghidra も固定版の1単位です。Binwalk には展開用のローカル 7-Zip が含まれます。native 導入は Ubuntu 26.04 x86-64 上で `scripts/setup-native-tools.sh --only <tool>` を使います。導入前の計画に、入手元、固定版がある場合の版、依存物、保存先を明示します。

Codex CLI とログイン、および curl・jq・OpenSSL・file・binutils など基本 OS ツールには、このクローン内での自動導入レシピがありません。不足時は手動項目として SKIPPED と表示して終了コードを非0にします。sudo、グローバル CA、ファイアウォール、プロキシ、キャプチャ権限、認証設定は変更しません。native の Ubuntu パッケージ版は導入時のディストリビューションのリポジトリに従い、Python の版は `uv.lock` に固定されています。導入コマンドが成功しても、将来のすべての Codex 子サンドボックスで動くことまでは証明しません。
