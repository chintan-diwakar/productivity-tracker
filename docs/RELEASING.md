# Release Guide

## Supported package targets

Version `1.0.0` has two package targets:

| Package | Target |
| --- | --- |
| Debian package | Ubuntu 24.04, AMD64 |
| Disk image | macOS 13 or later, Apple Silicon |

The Rust binary provides the GTK 4 and Libadwaita interface. PyInstaller packages the Python tracking engine.

The GitHub workflow uses separate Ubuntu and macOS jobs.

## Build the Ubuntu package

Install Python 3.12 and Rust 1.92. Then install the Ubuntu build libraries:

```bash
sudo apt install build-essential pkg-config libgtk-4-dev libadwaita-1-dev
```

Install the Python build tools. Then build the package:

```bash
python -m pip install '.[dev,packaging]'
RELEASE_VERSION=1.0.0 bash packaging/build_ubuntu.sh
```

The script creates these files in `dist/`:

```text
know-your-focus_1.0.0_amd64.deb
know-your-focus_1.0.0_amd64.deb.sha256
```

The Docker build gives a repeatable Ubuntu 24.04 environment:

```bash
docker build \
  -f packaging/Dockerfile.ubuntu \
  --build-arg RELEASE_VERSION=1.0.0 \
  --output type=local,dest=dist \
  .
```

## Build a macOS test package

Install Python 3.12 and Rust 1.92 on Apple Silicon macOS.

Install the GTK libraries and the dynamic-library bundler:

```bash
brew install gtk4 libadwaita dylibbundler
```

Install the Python build tools. Then build the package:

```bash
python -m pip install '.[dev,packaging]'
RELEASE_VERSION=1.0.0 bash packaging/build_macos.sh
```

This command creates an ad-hoc signed test disk image. The disk image contains GTK, Libadwaita, and the Python engine.

The test disk image is not a public release package.

## Configure signed macOS releases

Add these GitHub Actions secrets:

| Secret | Value |
| --- | --- |
| `MACOS_CERTIFICATE_BASE64` | Base64 text for a Developer ID Application `.p12` file |
| `MACOS_CERTIFICATE_PASSWORD` | Password for the `.p12` file |
| `APPLE_CODESIGN_IDENTITY` | Full Developer ID Application identity |
| `APPLE_ID` | Apple account for notarization |
| `APPLE_TEAM_ID` | Apple Developer team identifier |
| `APPLE_APP_PASSWORD` | App-specific password for notarization |

The release workflow imports the certificate into a temporary keychain. The build script signs the complete application with the hardened runtime.

The build script submits the disk image to Apple. It waits for notarization and staples the result.

The macOS job runs only when all six values exist. Without them, the job does not run, and the workflow never builds an unsigned disk image.

A tagged release then publishes the Ubuntu package alone. The release notes say that the macOS disk image is absent.

## Run the release workflow

Use **Build release packages** in GitHub Actions for a test build. Enter the version without a `v` prefix.

A tag that starts with `v` creates a GitHub release after the Ubuntu package job passes.

```bash
git tag v1.0.0
git push origin v1.0.0
```

Do not push the tag until the release commit is on `main`.

## Release gates

Complete these checks before a tag:

- All tests and Ruff checks pass.
- The Ubuntu package installs and starts in a clean Ubuntu 24.04 environment.
- The macOS job creates a signed and notarized disk image.
- Both checksum files match their package.
- Known limits appear in the README and release notes.
- A real-world evaluation report exists before a stable accuracy claim.

Version `1.0.0` is the first release. The current memory result does not pass the original `150 MB` goal.
