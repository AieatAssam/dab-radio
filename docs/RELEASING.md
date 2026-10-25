# Build and publish a release

DAB Radio packages target Debian 13 (Trixie) and 64-bit Raspberry Pi OS Trixie on `arm64` and `amd64`, using Python 3.13. The project does not claim support for 32-bit systems or Ubuntu 24.04. Package runtime dependencies are pinned in `requirements-runtime.txt`; development and test dependencies are in `requirements.txt`.

## CI builds

The GitHub Actions workflow at `.github/workflows/release.yml` builds packages in Debian Trixie containers using native `ubuntu-24.04-arm` (`arm64`) and `ubuntu-24.04` (`amd64`) runners.

- Pull requests and pushes to `main` build and smoke-test packages without publishing a release.
- A push of a version tag matching `v*` builds both architectures and publishes a GitHub Release.
- Manual workflow dispatch builds and uploads artifacts for review; it does not publish a release.

Each architecture build runs the Python tests, JavaScript syntax checks and shell syntax checks, builds the patched decoder and native DL+ test, then creates and smoke-tests a Debian package. Build artifacts include the `.deb` package and corresponding GPL decoder source archive. The tagged release job downloads both architecture artifacts, creates `SHA256SUMS`, and publishes the packages, source archives and checksums.

Packages install the application under `/opt/dab-radio`, runtime state under `/var/lib/dab-radio`, and configuration under `/etc/dab-radio/dab-radio.conf`. The service runs as `dab-radio` on port 8090. The decoder and Python runtime dependencies are included in the package; installation does not compile source on the target or download Python packages with pip. `apt` may fetch operating-system libraries from configured Debian repositories.

## Create a release

Set `VERSION` to the release version, commit the release changes, and create and push a matching `v` tag. The workflow rejects a tag whose version does not match `VERSION`. For the initial `0.1.0` release:

```bash
git tag -a v0.1.0 -m "DAB Radio 0.1.0"
git push origin v0.1.0
```

The tagged workflow publishes the release and marks it as the latest release. Check the workflow run and assets at [GitHub Releases](https://github.com/AieatAssam/dab-radio/releases/latest). Installation instructions are in [INSTALL.md](INSTALL.md).

## Local package build

Build on Debian 13 Trixie with native architecture matching the package (`arm64` or `amd64`) and Python 3.13. The build needs the native decoder build dependencies documented in the README and the Python build dependencies in `requirements.txt`.

```bash
./scripts/build-decoder.sh
./scripts/build-package.sh 0.1.0
```

The package builder reads the runtime dependency pins from `requirements-runtime.txt` and writes the `.deb` and decoder source archive under `dist/`. It supports native `arm64` and `amd64` builds only.

## Licensing

Release packages contain original project files under MIT and third-party components under their respective licenses. The patched decoder is GPL-3.0-or-later; each release includes its corresponding decoder source archive and required notices. See the README, `THIRD_PARTY_NOTICES.md`, `licenses/`, and [decoder patch notes](../patches/README.md) for attribution and license details.
