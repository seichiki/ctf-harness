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
    echo "This project-local installer is pinned for Ubuntu 26.04 x86-64 only." >&2
    exit 2
fi
command -v apt-get >/dev/null
command -v dpkg-deb >/dev/null
command -v curl >/dev/null
mkdir -p "$archive" "$sysroot" "$bin" "$tools/binwalk"
packages=(gdb socat libimage-exiftool-perl tshark libbabeltrace1 libipt2
    libsource-highlight4t64 libdebuginfod1t64 libwrap0 libwireshark19
    libpcap0.8t64 libwiretap16 libwsutil17 wireshark-common
    libibverbs1 liblua5.4-0 libsnappy1v5 libnghttp3-9 libsmi2t64
    libwireshark-data libc-ares2 libcares2 libnl-3-200 libnl-route-3-200
    pkgconf-bin libpkgconf7 libfontconfig-dev libexpat1-dev libfreetype-dev
    uuid-dev zlib1g-dev libbz2-dev libpng-dev libbrotli-dev unzip 7zip)
for package in "${packages[@]}"; do
    if ! compgen -G "$archive/${package}_*.deb" >/dev/null; then
        (cd "$archive" && apt-get download "$package")
    fi
done
for deb in "$archive"/*.deb; do
    dpkg-deb -x "$deb" "$sysroot"
done
# Ubuntu's runtime libraries are already present; provide the linker targets
# required by the locally extracted development metadata without sudo.
for soname in libfontconfig.so.1 libfreetype.so.6; do
    target=$(readlink -f "/usr/lib/x86_64-linux-gnu/$soname")
    cp --update=none "$target" "$lib/$(basename "$target")"
    ln -sfn "$(basename "$target")" "$lib/${soname%%.so.*}.so"
done
ln -sfn ../ubuntu-root/usr/bin/pkgconf "$bin/pkg-config"
for tool in gdb socat exiftool tshark unzip 7z; do
    ln -sfn ../../../scripts/native-tool "$bin/$tool"
done
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
"$bin/gdb" --version | head -1
"$bin/socat" -V | head -2
"$bin/exiftool" -ver
"$bin/tshark" -v | head -2
"$bin/binwalk" --version
echo "Local tools installed under $tools. No system package or global shell setting was changed."
