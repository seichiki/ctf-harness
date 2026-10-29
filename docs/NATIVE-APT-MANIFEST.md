# Native Ubuntu package snapshot / Ubuntu パッケージ記録

Snapshot from `./scripts/setup-native-tools.sh` on Ubuntu 26.04 x86-64. Packages came from the host's configured official Ubuntu apt repositories and were extracted under ignored `.local/tools/ubuntu-root/` without sudo. This records observed package files; the setup script resolves current supported versions from the host repository. Package contents stay in the clone, not Git.

| Package | Version | Architecture | Downloaded .deb SHA-256 |
| --- | --- | --- | --- |
| `7zip` | `26.00+dfsg-1` | `amd64` | `97dc6694bd7919e163a600dff8a5d7f72d892934f97cb0d7deba285abff779ce` |
| `gdb` | `17.1-2ubuntu1` | `amd64` | `e1034f3c120b99d9a34964b274d81d7525c4f22bf76f9f31308014a6bec20b3e` |
| `libbabeltrace1` | `1.5.11-5build1` | `amd64` | `ef5b7809f1d7fe9c62056bc970d15a43c621b11674a7a57d0ef2ccd61871014b` |
| `libbrotli-dev` | `1.2.0-3ubuntu0.1` | `amd64` | `822fb56d07c0cd06c178a6f3b0b0a750f159534bf2a19c37b4b8559d0bea94ad` |
| `libbz2-dev` | `1.0.8-6ubuntu0.1` | `amd64` | `a983927bd8f7952d742814b53cef35c21b1836c920fa2e5002e48f2e6f46905e` |
| `libc-ares2` | `1.34.6-1ubuntu0.2` | `all` | `85b41df9fbb8513b73c1b489731f811422af7814cbbd95451699c5932f5d65f3` |
| `libcares2` | `1.34.6-1ubuntu0.2` | `amd64` | `e493f60515895fde6c235e787605b935f6a50c71150a6be1f66903d1359ba090` |
| `libdebuginfod1t64` | `0.194-4` | `amd64` | `2d1eacbaf69feb2ba6a775e53606b2bf85cd975f7a3832d4d46d414443241b6e` |
| `libexpat1-dev` | `2.7.4-1ubuntu0.2` | `amd64` | `78b22a6dcdd3053dd2f3d442347ebf0427612f3b7efac75447a2229ba1568544` |
| `libfontconfig-dev` | `2.17.1-3ubuntu1` | `amd64` | `cdb2383bd9c5fcdb0809943ecd21b11cb2da60777d345f052eda7672c1718e7c` |
| `libfreetype-dev` | `2.14.2+dfsg-1ubuntu0.2` | `amd64` | `215038a81ba0895911f0f2975c8d5fadc064961493d090252ce26b86f8b90c2b` |
| `libibverbs1` | `61.0-2ubuntu3` | `amd64` | `1d9e2e86e6500dabb6143c04adea8d122c7caa72aae3832de88d7ada4fa97201` |
| `libimage-exiftool-perl` | `13.50+dfsg-1` | `all` | `3d052a521302fa24f7166b1554859aa0e9df241839edd3f290887e678e0bf603` |
| `libipt2` | `2.1.2-3` | `amd64` | `0113f73b628f0fdeb00bb0099268088e5bbbbd231d03d65d2dac60edb3cb57ea` |
| `liblua5.4-0` | `5.4.8-1build1` | `amd64` | `ff589ea3f181b89dd76b0240f79c59ac2f13f24e2053f624f774f596c7ef7897` |
| `libnghttp3-9` | `1.12.0-1` | `amd64` | `e72d78a458f77ed3fc9b0bb11780e7ba0b98fd063cb6593de77f146e227936d4` |
| `libnl-3-200` | `3.12.0-2` | `amd64` | `52fda1b991baa2d0fbe82f5dfb15584dcb1f25a7e3d311e2e319cc33858b4f2c` |
| `libnl-route-3-200` | `3.12.0-2` | `amd64` | `58c5fa3c2f5226ffb1846db6cf7318196dbf5294a4354edd00fdae2db30a45dc` |
| `libpcap0.8t64` | `1.10.6-1ubuntu1.1` | `amd64` | `3547e50eef05d4beb17c2a7fbdaad3d54be9c07f71bebea8054e5e52509485b0` |
| `libpkgconf7` | `2.5.1-4` | `amd64` | `353f622f6432a3d65bedd3c23e0af98c2c438650b497b355772a56a05ebf7dd0` |
| `libpng-dev` | `1.6.57-1ubuntu0.1` | `amd64` | `7186da2c1b77a683c3ef42660b9a66f6ed17bb9ef5bb75c191b26e91a5a39a3c` |
| `libsmi2t64` | `0.4.8+dfsg2-18` | `amd64` | `99b84be2e711fb7bff620b969f148b51c1394b6dc1fe1ac83d2f598df96c83d6` |
| `libsnappy1v5` | `1.2.2-2` | `amd64` | `1679c696614780a0137e2b484ade47fc226177556e261bace9a779ae98b29346` |
| `libsource-highlight4t64` | `3.1.9-4.3build2` | `amd64` | `ac2cae4028ef60f003bd62f719a0c9d2451c3ff3f72da6e9fef8808de7636b8a` |
| `libwireshark-data` | `4.6.4-1` | `all` | `1cea0e2a49eb7eb4508e4de300e300b822607b7fa7df87e1e58dd0a6a990b049` |
| `libwireshark19` | `4.6.4-1` | `amd64` | `f66fa831b3b8cafe5ecc8cba5917e7f053724480d63a1c9f9af9dfc4311c14b9` |
| `libwiretap16` | `4.6.4-1` | `amd64` | `28ea6ab5d1a1b102511c6a400983ac2156b01e95e599b8ad073be354f2ada015` |
| `libwrap0` | `7.6.q-36build2` | `amd64` | `a3784ca083c626c3ae41cdd32d4c5898554650dc77d2b54dbb1197a38198adf8` |
| `libwsutil17` | `4.6.4-1` | `amd64` | `99fe5dcb49dea88a8ff27ce30e08f848346672e45cf03510eee32db8f1a7105f` |
| `pkgconf-bin` | `2.5.1-4` | `amd64` | `9690471f395b6652f2cd8962334b9400e26a10daf4af7bf2f2c1a0325c193f0b` |
| `socat` | `1.8.1.1-1ubuntu0.1` | `amd64` | `7e216496b3dfd7c0d7d655f5230e3062c0db028e0a95afff79b00ee17f557188` |
| `tshark` | `4.6.4-1` | `amd64` | `de06fc08cb4c604894ba3174ddc1be8677339e13bf4a79a80cf00b6e29cfe973` |
| `unzip` | `6.0-29ubuntu1` | `amd64` | `1f6f2bdcde84641e89c9367a7a99d90e990efa3e487a8d625241c2f9c55db5f4` |
| `uuid-dev` | `2.41.3-3ubuntu2.2` | `amd64` | `0ba791f89888491857c69ad3d59d8517d4926eae0c242f213579fc59ea0b5e94` |
| `wireshark-common` | `4.6.4-1` | `amd64` | `2e852cffabd7c40f1f242a8f16ac19d7a79c8f690dda23a297fb601a70f24272` |
| `zlib1g-dev` | `1:1.3.dfsg+really1.3.1-1ubuntu3.2` | `amd64` | `2e4663ab8d018aff8351ee949e53971911b2aca3491eefde61e82111ee83cbc3` |
