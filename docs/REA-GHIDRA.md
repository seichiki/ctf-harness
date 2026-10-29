# REA and Ghidra for reverse runs / Reverse 実行用 REA・Ghidra

## English

Reverse runs require the pinned tools below; other categories do not. The Linux
x86-64 WSL setup is local to this clone. It does not use sudo, change the
global Codex configuration, install a browser certificate, or start a service.
Complete the normal `uv sync --locked` first, then run:

```sh
./scripts/setup-rea-ghidra.sh
./ctf-start tools --category reverse --missing-only --json
```

The installer downloads from the official Node.js, Eclipse Temurin, and NSA Ghidra
release locations listed below, checks the published SHA-256 values before extraction,
and installs REA from the locked `scripts/rea-npm/package-lock.json`. Everything goes
under ignored `.local/tools/`. It stops on an incomplete or conflicting install rather
than silently replacing it. The installer may fetch packages; `tools` is read-only and
never installs anything. Friends cloning the repository repeat the two commands above.

| Item | Pinned version | Official source | SHA-256 |
| --- | --- | --- | --- |
| Node Linux x64 | 24.22.1 | [nodejs.org distribution](https://nodejs.org/dist/v24.22.1/) | `6c172a9ab6718f7b801fb5a7bd486af2ee5e32758086a04b84fcce2aa77095e6` |
| Temurin JDK Linux x64 | 21.0.13+9 | [Adoptium release](https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.13%2B9) | `d7f5d5cf865a2902b70ff549b97586a7d3f234e016f041ab447ea740c7d66d1c` |
| Ghidra | 12.1.4 | [NSA release](https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build) | `ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db` |
| REA (`rea-agents`) | 6.8.0 | [canonical npm package](https://www.npmjs.com/package/rea-agents) | npm SHA-512 integrity is pinned in `scripts/rea-npm/package-lock.json` |

REA is the interface; Ghidra performs native decompilation. The installed REA 6.8.0
provider doctor accepts this Ghidra 12.1.4/JDK 21 combination. See
[REA installation guidance](https://github.com/morluto/rea/blob/main/docs/installation.md)
and [Ghidra's release guide](https://github.com/NationalSecurityAgency/ghidra/blob/Ghidra_12.1.4_build/GhidraDocs/GettingStarted.md).

The harness uses the project-local `rea-static` interface for reverse tasks. It exposes
only `inspect`, `layout`, `search`, `function`, and `decompile` on regular files under
the current role's `input/` or self-authored `analysis/` directories. From a role
working directory, an example is:

```sh
/absolute/path/to/ctf-harness-test/rea-static decompile input/program main
```

The wrapper sends no inherited API keys or HTTP proxy variables to Node/Ghidra. It
never executes the target binary. It is an interface guard, not an OS security boundary:
the Codex sandbox and the selected case authorization still govern work. Ghidra may
need more than the wrapper's 512 MiB JVM heap for a large target. REA's broad MCP server
advertises 229 tools, including dynamic operations, so the harness does not register it
globally or automatically expose that catalog to a solver.

### Codex child sandbox result on this host

The project-local wrapper and REA/Ghidra decompiled a self-built ELF when invoked
directly in WSL. A bounded real `codex exec` test using the harness's `workspace-write`
profile with `sandbox_workspace_write.network_access=false` launched the wrapper, but
Ghidra failed before bridge startup with `java.net.SocketException: Operation not
permitted`. REA's Linux bridge needs a local Unix socket. Thus **REA is not usable by
the actual Codex child under the network-off profile on this host**.

With the owner's approval, **one** subsequent actual Codex child test used the same
profile and harmless self-built ELF, changing only
`sandbox_workspace_write.network_access=true` for that invocation. `rea-static
decompile input/sample helper` exited 0; the saved Ghidra 12.1.4 result reports ELF
x86-64 SHA-256 `3c2c031898efba9663996a661d19c68dddae9fbd687a666df6c0e3a3f3e7f1cc`
and `return param_1 * 7 + 3;`. Evidence is in ignored
`categories/reverse/runs/rea-integration-selftest/20261029T110500Z-single/solver/`.
This verifies that local sample under that **network-on** profile only. Network ON
also permits external destinations; the wrapper and task scope do not constitute a
host firewall. Both fixture results and the ignored
`.local/tools/rea-child-smoke.json` remain saved in this clone. The `tools` checker
does **not** read or display historical self-tests in normal, missing-only, or JSON
output; it reports current installation, version and provider-doctor checks only.
Those checks cannot establish how a future Codex child sandbox will behave.
No broad MCP server was enabled and no persistent network preference was changed.

## 日本語

Reverse カテゴリの実行には以下のツールが必要です。他カテゴリには必須ではありません。
この手順は WSL Linux x86-64 のクローン内だけに Node、JDK、Ghidra、REA を配置します。
まず `uv sync --locked` を実行し、上の `./scripts/setup-rea-ghidra.sh` を実行してください。
公式配布元の SHA-256 を照合し、REA はリポジトリ内の npm ロックファイルから入れます。
保存先は Git の対象外である `.local/tools/` です。`./ctf-start tools --category reverse
--missing-only --json` はインストールを行わず、足りない項目を表示します。

逆解析の役には `rea-static` を使います。対象はその役の `input/` と自作の `analysis/`
配下の通常ファイルだけです。`inspect`、`layout`、`search`、`function`、`decompile`
以外の操作は受け付けません。解析対象バイナリは実行しません。Ghidra が解析本体で、
REA がその操作窓口です。MCP サーバーは動的操作も多数公開するため、ハーネスから
自動登録しません。このラッパーは OS の隔離を追加するものではありません。

このホストでの実際の Codex 子プロセス検証では、`workspace-write` かつ
`sandbox_workspace_write.network_access=false` の状態で Ghidra のローカル Unix
ソケット作成が `Operation not permitted` で拒否されました。WSL での直接呼び出しは
成功しました。所有者が許可した別の1回限りの検証では、同じ自作 ELF に対し
子実行の network ON のみ指定し、`helper` の逆コンパイルが終了値0で成功しました。
network ON は外部ホストへの通信も可能にします。この成功はその設定と試料に限る
もので、他のクローンや network OFF での成功を意味しません。保存済み設定や広範な
MCP サーバーは変更していません。

保存済みの ON/OFF テスト結果と無視対象の `.local/tools/rea-child-smoke.json` は残しています。`tools` チェッカーは過去の結果を読み込まず、通常表示、`--missing-only`、JSON のいずれにも表示しません。現在の導入状況と版・プロバイダー診断のみ確認します。
