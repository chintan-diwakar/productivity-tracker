#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
release_version="${RELEASE_VERSION:-0.1.0}"
release_version="${release_version#v}"
export RELEASE_VERSION="$release_version"
architecture="$(dpkg --print-architecture)"
stage_root="$project_root/packaging/stage/know-your-focus"
application_root="$stage_root/opt/know-your-focus"
artifact="$project_root/dist/know-your-focus_${release_version}_${architecture}.deb"

cd "$project_root"
cargo build --locked --release --manifest-path desktop/Cargo.toml
python -m PyInstaller --clean --noconfirm packaging/know_your_focus.spec

rm -rf "$stage_root"
mkdir -p \
  "$application_root" \
  "$stage_root/DEBIAN" \
  "$stage_root/usr/bin" \
  "$stage_root/usr/share/applications" \
  "$stage_root/usr/share/icons/hicolor/scalable/apps"
install -m 0755 desktop/target/release/know-your-focus \
  "$application_root/know-your-focus"
mkdir -p "$application_root/engine"
cp -a dist/KyfEngine/. "$application_root/engine/"
ln -s /opt/know-your-focus/know-your-focus "$stage_root/usr/bin/know-your-focus"
install -m 0644 packaging/linux/know-your-focus.desktop \
  "$stage_root/usr/share/applications/know-your-focus.desktop"
install -m 0644 packaging/assets/know-your-focus.svg \
  "$stage_root/usr/share/icons/hicolor/scalable/apps/know-your-focus.svg"

installed_size="$(du -sk "$stage_root" | cut -f1)"
sed \
  -e "s/@VERSION@/$release_version/g" \
  -e "s/@ARCHITECTURE@/$architecture/g" \
  -e "s/@INSTALLED_SIZE@/$installed_size/g" \
  packaging/linux/control.in > "$stage_root/DEBIAN/control"

dpkg-deb --build --root-owner-group "$stage_root" "$artifact"
(
  cd "$(dirname "$artifact")"
  artifact_name="$(basename "$artifact")"
  sha256sum "$artifact_name" > "$artifact_name.sha256"
)
