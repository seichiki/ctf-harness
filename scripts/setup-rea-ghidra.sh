#!/bin/sh
# Optional, project-local install of pinned official native RE tools.
# This script is never called by doctor or by a challenge run.
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tool_root="$project/.local/tools"
downloads="$tool_root/downloads"
mkdir -p "$downloads"

fetch_verified() {
    url=$1
    digest=$2
    name=$3
    archive="$downloads/$name"
    if [ ! -e "$archive" ]; then
        curl --fail --location --show-error --silent --retry 2 "$url" -o "$archive.part"
        printf '%s  %s\n' "$digest" "$archive.part" | sha256sum --check --status || {
            echo "Checksum mismatch for $name; inspect $archive.part" >&2
            exit 1
        }
        mv "$archive.part" "$archive"
    fi
    printf '%s  %s\n' "$digest" "$archive" | sha256sum --check --status || {
        echo "Checksum mismatch for existing $archive; no replacement attempted" >&2
        exit 1
    }
}

node="$tool_root/node-v24.22.1-linux-x64"
fetch_verified 'https://nodejs.org/dist/v24.22.1/node-v24.22.1-linux-x64.tar.xz' \
    '6c172a9ab6718f7b801fb5a7bd486af2ee5e32758086a04b84fcce2aa77095e6' \
    'node-v24.22.1-linux-x64.tar.xz'
if [ ! -e "$node" ]; then
    stage="$tool_root/.node-extract"
    mkdir "$stage"
    tar -xJf "$downloads/node-v24.22.1-linux-x64.tar.xz" -C "$stage"
    mv "$stage/node-v24.22.1-linux-x64" "$node"
    rmdir "$stage"
fi
test -x "$node/bin/node" || { echo 'Node install incomplete' >&2; exit 1; }

jdk="$tool_root/jdk-21.0.13+9"
fetch_verified 'https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/OpenJDK21U-jdk_x64_linux_hotspot_21.0.13_9.tar.gz' \
    'd7f5d5cf865a2902b70ff549b97586a7d3f234e016f041ab447ea740c7d66d1c' \
    'OpenJDK21U-jdk_x64_linux_hotspot_21.0.13_9.tar.gz'
if [ ! -e "$jdk" ]; then
    stage="$tool_root/.jdk-extract"
    mkdir "$stage"
    tar -xzf "$downloads/OpenJDK21U-jdk_x64_linux_hotspot_21.0.13_9.tar.gz" -C "$stage"
    mv "$stage/jdk-21.0.13+9" "$jdk"
    rmdir "$stage"
fi
test -x "$jdk/bin/java" && test -x "$jdk/bin/javac" || { echo 'JDK install incomplete' >&2; exit 1; }

ghidra="$tool_root/ghidra_12.1.4_PUBLIC"
fetch_verified 'https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip' \
    'ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db' \
    'ghidra_12.1.4_PUBLIC_20260921.zip'
if [ ! -e "$ghidra" ]; then
    stage="$tool_root/.ghidra-extract"
    uv run --project "$project" --offline --locked --no-sync python \
        "$project/scripts/extract-verified-ghidra.py" \
        "$downloads/ghidra_12.1.4_PUBLIC_20260921.zip" "$stage"
    mv "$stage/ghidra_12.1.4_PUBLIC" "$ghidra"
    rmdir "$stage"
fi
test -x "$ghidra/support/analyzeHeadless" || { echo 'Ghidra install incomplete' >&2; exit 1; }

rea="$tool_root/rea"
if [ ! -e "$rea" ]; then
    mkdir "$rea"
    cp "$project/scripts/rea-npm/package.json" "$project/scripts/rea-npm/package-lock.json" "$rea/"
    env PATH="$node/bin:/usr/local/bin:/usr/bin:/bin" \
        npm_config_cache="$tool_root/npm-cache" npm_config_update_notifier=false \
        "$node/bin/npm" ci --prefix "$rea" --no-audit --no-fund
fi
test -f "$rea/node_modules/rea-agents/scripts/rea.mjs" || { echo 'REA install incomplete' >&2; exit 1; }

env PATH="$node/bin:$jdk/bin:/usr/local/bin:/usr/bin:/bin" \
    GHIDRA_INSTALL_DIR="$ghidra" JAVA_HOME="$jdk" \
    "$rea/node_modules/.bin/rea" doctor --provider ghidra --json > "$tool_root/rea-doctor.json"
echo 'Project-local Ghidra 12.1.4, JDK 21.0.13, Node 24.22.1 and REA 6.8.0 ready.'
echo 'Read .local/tools/rea-doctor.json for provider checks; run ./ctf-start tools --category reverse.'
