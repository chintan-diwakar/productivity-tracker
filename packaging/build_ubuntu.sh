#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
release_version="${RELEASE_VERSION:-0.1.0}"
release_version="${release_version#v}"
export RELEASE_VERSION="$release_version"
architecture="$(dpkg --print-architecture)"
stage_root="$project_root/packaging/stage/desk-focus-tracker"
application_root="$stage_root/opt/desk-focus-tracker"
artifact="$project_root/dist/desk-focus-tracker_${release_version}_${architecture}.deb"

cd "$project_root"
python -m PyInstaller --clean --noconfirm packaging/desk_focus.spec

rm -rf "$stage_root"
mkdir -p \
  "$application_root" \
  "$stage_root/DEBIAN" \
  "$stage_root/usr/bin" \
  "$stage_root/usr/share/applications" \
  "$stage_root/usr/share/icons/hicolor/scalable/apps"
cp -a dist/DeskFocusTracker/. "$application_root/"
ln -s /opt/desk-focus-tracker/desk-focus-tracker "$stage_root/usr/bin/desk-focus-tracker"
install -m 0644 packaging/linux/desk-focus-tracker.desktop \
  "$stage_root/usr/share/applications/desk-focus-tracker.desktop"
install -m 0644 packaging/assets/desk-focus-tracker.svg \
  "$stage_root/usr/share/icons/hicolor/scalable/apps/desk-focus-tracker.svg"

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
