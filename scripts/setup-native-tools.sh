#!/usr/bin/env bash
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tools="$root/.local/tools"
archive="$tools/ubuntu-debs"
sysroot="$tools/ubuntu-root"
bin="$tools/bin"
lib="$sysroot/usr/lib/x86_64-linux-gnu"
source /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_ID" != 26.04 || $(uname -m) != x86_64 ]]; then
    echo 'Project-local native installer requires Ubuntu 26.04 x86-64.' >&2; exit 2
fi
for program in apt-get dpkg-deb curl; do command -v "$program" >/dev/null; done
declare -A selected=() packages=()
plan_only=0
if [[ ${1:-} == --plan ]]; then plan_only=1; shift; fi
if (( $# == 0 )); then
    set -- --only gdb --only socat --only exiftool --only tshark --only binwalk --only unzip
fi
while (( $# )); do
    if [[ "$1" != --only || $# -lt 2 ]]; then
        echo 'Usage: setup-native-tools.sh [--only gdb|socat|exiftool|tshark|binwalk|7z|unzip] ...' >&2; exit 2
    fi
    case "$2" in gdb|socat|exiftool|tshark|binwalk|7z|unzip) selected["$2"]=1 ;;
        *) echo "Unsupported tool: $2" >&2; exit 2 ;; esac
    shift 2
done
add_packages() { for package in "$@"; do packages["$package"]=1; done; }
if [[ ${selected[gdb]:-} ]]; then
    add_packages gdb libbabeltrace1 libipt2 libsource-highlight4t64 libdebuginfod1t64
fi
if [[ ${selected[socat]:-} ]]; then add_packages socat libwrap0; fi
if [[ ${selected[exiftool]:-} ]]; then add_packages libimage-exiftool-perl; fi
if [[ ${selected[tshark]:-} ]]; then
    add_packages tshark libwireshark19 libpcap0.8t64 libwiretap16 libwsutil17 wireshark-common \
        libibverbs1 liblua5.4-0 libsnappy1v5 libnghttp3-9 libsmi2t64 \
        libwireshark-data libc-ares2 libcares2 libnl-3-200 libnl-route-3-200
fi
if [[ ${selected[binwalk]:-} ]]; then
    selected[7z]=1
    add_packages pkgconf-bin libpkgconf7 libfontconfig-dev libexpat1-dev libfreetype-dev \
        uuid-dev zlib1g-dev libbz2-dev libpng-dev libbrotli-dev
fi
if [[ ${selected[7z]:-} ]]; then add_packages 7zip; fi
if [[ ${selected[unzip]:-} ]]; then add_packages unzip; fi
if (( plan_only )); then printf '%s\n' "${!packages[@]}" | LC_ALL=C sort; exit 0; fi
mkdir -p "$archive" "$sysroot" "$bin" "$tools/binwalk"
for package in "${!packages[@]}"; do
    if ! compgen -G "$archive/${package}_*.deb" >/dev/null; then
        (cd "$archive" && apt-get download "$package")
    fi
    matches=("$archive/${package}_"*.deb)
    if (( ${#matches[@]} != 1 )); then
        echo "Expected one cached package for $package; inspect $archive before continuing." >&2
        exit 1
    fi
    dpkg-deb -x "${matches[0]}" "$sysroot"
done
for tool in gdb socat exiftool tshark unzip 7z; do
    if [[ ${selected[$tool]:-} ]]; then ln -sfn ../../../scripts/native-tool "$bin/$tool"; fi
done
if [[ ${selected[binwalk]:-} ]]; then
    for soname in libfontconfig.so.1 libfreetype.so.6; do
        target=$(readlink -f "/usr/lib/x86_64-linux-gnu/$soname")
        cp --update=none "$target" "$lib/$(basename "$target")"
        ln -sfn "$(basename "$target")" "$lib/${soname%%.so.*}.so"
    done
    ln -sfn ../ubuntu-root/usr/bin/pkgconf "$bin/pkg-config"
    if [[ ! -x "$tools/cargo-home/bin/cargo" ]]; then
        curl --proto '=https' --tlsv1.2 -fsSLo "$tools/rustup-init.sh" https://sh.rustup.rs
        RUSTUP_HOME="$tools/rustup-home" CARGO_HOME="$tools/cargo-home" \
            sh "$tools/rustup-init.sh" -y --no-modify-path --profile minimal --default-toolchain 1.99.1
    fi
    if [[ ! -x "$tools/binwalk/bin/binwalk" ]]; then
        RUSTUP_HOME="$tools/rustup-home" CARGO_HOME="$tools/cargo-home" \
        PATH="$bin:$tools/cargo-home/bin:$PATH" LD_LIBRARY_PATH="$lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
        LIBRARY_PATH="$lib${LIBRARY_PATH:+:$LIBRARY_PATH}" \
        PKG_CONFIG_PATH="$lib/pkgconfig:$sysroot/usr/share/pkgconfig" \
        PKG_CONFIG_SYSROOT_DIR="$sysroot" \
            "$tools/cargo-home/bin/cargo" install binwalk --version 3.1.0 --locked --root "$tools/binwalk"
    fi
    ln -sfn ../binwalk/bin/binwalk "$bin/binwalk"
fi
for tool in "${!selected[@]}"; do
    case "$tool" in
        gdb) "$bin/$tool" --version >/dev/null ;;
        socat) "$bin/$tool" -V >/dev/null ;;
        exiftool) "$bin/$tool" -ver >/dev/null ;;
        tshark) "$bin/$tool" -v >/dev/null 2>&1 ;;
        unzip) "$bin/$tool" -v >/dev/null ;;
        7z) "$bin/$tool" >/dev/null ;;
        binwalk) "$bin/binwalk" --version >/dev/null ;;
    esac
done
echo "Selected tools installed under $tools; no system packages or global settings changed."
