#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
release_version="${RELEASE_VERSION:-0.1.0}"
release_version="${release_version#v}"
export RELEASE_VERSION="$release_version"
architecture="$(uname -m)"
app="$project_root/dist/Know Your Focus.app"
artifact="$project_root/dist/KnowYourFocus-${release_version}-macOS-${architecture}.dmg"

notary_values=0
[[ -n "${APPLE_ID:-}" ]] && ((notary_values += 1))
[[ -n "${APPLE_TEAM_ID:-}" ]] && ((notary_values += 1))
[[ -n "${APPLE_APP_PASSWORD:-}" ]] && ((notary_values += 1))
if [[ "$notary_values" -ne 0 && "$notary_values" -ne 3 ]]; then
  echo "Set APPLE_ID, APPLE_TEAM_ID, and APPLE_APP_PASSWORD together." >&2
  exit 2
fi
if [[ "$notary_values" -eq 3 && -z "${APPLE_CODESIGN_IDENTITY:-}" ]]; then
  echo "Set APPLE_CODESIGN_IDENTITY before notarization." >&2
  exit 2
fi

for command in cargo dylibbundler brew; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing build dependency: $command" >&2
    exit 2
  fi
done

cd "$project_root"
python packaging/build_icon.py packaging/generated
iconutil -c icns packaging/generated/know-your-focus.iconset \
  -o packaging/generated/know-your-focus.icns
cargo build --locked --release --manifest-path desktop/Cargo.toml
python -m PyInstaller --clean --noconfirm packaging/know_your_focus.spec

rm -rf "$app"
mkdir -p \
  "$app/Contents/MacOS" \
  "$app/Contents/Frameworks" \
  "$app/Contents/Resources/engine" \
  "$app/Contents/Resources/share/glib-2.0" \
  "$app/Contents/Resources/share/icons"
install -m 0755 desktop/target/release/know-your-focus \
  "$app/Contents/MacOS/know-your-focus"
cp -a dist/KyfEngine/. "$app/Contents/Resources/engine/"
cp packaging/generated/know-your-focus.icns "$app/Contents/Resources/know-your-focus.icns"
sed "s/@VERSION@/$release_version/g" packaging/macos/Info.plist.in \
  > "$app/Contents/Info.plist"

homebrew_prefix="$(brew --prefix)"
# Dereference symlinks: Homebrew links these files into the Cellar with
# relative targets that dangle once copied into the bundle, and codesign
# refuses to seal dangling symlinks.
cp -RpL "$homebrew_prefix/share/glib-2.0/schemas" \
  "$app/Contents/Resources/share/glib-2.0/"
for icon_theme in Adwaita hicolor; do
  if [[ -d "$homebrew_prefix/share/icons/$icon_theme" ]]; then
    cp -RpL "$homebrew_prefix/share/icons/$icon_theme" \
      "$app/Contents/Resources/share/icons/"
  fi
done
glib-compile-schemas "$app/Contents/Resources/share/glib-2.0/schemas"

dylibbundler \
  -od \
  -b \
  -x "$app/Contents/MacOS/know-your-focus" \
  -d "$app/Contents/Frameworks" \
  -p @executable_path/../Frameworks

signing_identity="${APPLE_CODESIGN_IDENTITY:--}"
codesign_arguments=(--force --deep --sign "$signing_identity")
if [[ "$signing_identity" != "-" ]]; then
  codesign_arguments+=(--options runtime --timestamp)
fi
codesign "${codesign_arguments[@]}" \
  --entitlements packaging/macos/KnowYourFocus.entitlements \
  "$app"
codesign --verify --deep --strict --verbose=2 "$app"

hdiutil create \
  -volname "Know Your Focus" \
  -srcfolder "$app" \
  -ov \
  -format UDZO \
  "$artifact"

if [[ "$notary_values" -eq 3 ]]; then
  xcrun notarytool submit "$artifact" \
    --apple-id "$APPLE_ID" \
    --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_PASSWORD" \
    --wait
  xcrun stapler staple "$artifact"
fi

hdiutil verify "$artifact"
(
  cd "$(dirname "$artifact")"
  artifact_name="$(basename "$artifact")"
  shasum -a 256 "$artifact_name" > "$artifact_name.sha256"
)
