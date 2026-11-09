#!/usr/bin/env bash
# Install gVisor (runsc) and register it as the Docker runtime "runsc" (Deploy Step 3).
#
# Used by CI (the `gvisor` and `prod-images` jobs) and by the server (Deploy Step 5):
#     sudo deploy/install-gvisor.sh
# Then grade with it:  SANDBOX_RUNTIME=runsc  (docs/deploy.md).
#
# The release is pinned and so is the SHA-512 of each archive: a swapped download fails here,
# instead of installing a program that runs as root next to Docker. To update, change VERSION and
# both hashes together (from the release's SHA512SUMS, ideally compared with a download of
# your own), and keep the "at least two weeks old" rule.
set -euo pipefail

VERSION="20261019.0"
SHA512_X86_64="bcbf431b2f9a039f6ab23bfe23986031130c0f149294978cedfd46910901deba0737d8642c848f597ed4b5c72324885db4d75ee86a1f6a90915fbe1f2f2eb915"
SHA512_AARCH64="60a8239ec21ba1495633dbfa24ab4d43578066fcebef2482f9d0cd1486abbfd3c5c5face1749a31cc62b287a0a44198a0852024c7f2e5683917c7c1c342d0bbe"
INSTALL_DIR="/usr/local/bin"
# The grading image (grader/sandbox.py DOCKER_IMAGE); a test keeps the two equal.
TEST_IMAGE="python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f"

if [ "$(id -u)" -ne 0 ]; then
    echo "run this as root: sudo $0" >&2
    exit 1
fi

arch="$(uname -m)"
case "$arch" in
    x86_64) expected="$SHA512_X86_64" ;;
    aarch64 | arm64) arch="aarch64"; expected="$SHA512_AARCH64" ;;
    *) echo "unsupported CPU: $arch (gVisor releases exist for x86_64 and aarch64)" >&2; exit 1 ;;
esac

if ! command -v zstd >/dev/null 2>&1; then
    echo "zstd is needed to unpack the release (apt install zstd)" >&2
    exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
archive="gvisor-${arch}.tar.zstd"
url="https://github.com/google/gvisor/releases/download/release-${VERSION}/${archive}"

echo "downloading $url"
curl -fsSL --retry 3 -o "$work/$archive" "$url"
echo "${expected}  $work/$archive" | sha512sum --check --status || {
    echo "the downloaded archive does not match the pinned SHA-512: refusing to install it" >&2
    exit 1
}

tar --zstd -xf "$work/$archive" -C "$work"
for binary in runsc containerd-shim-runsc-v1; do
    found="$(find "$work" -type f -name "$binary" | head -n 1)"
    if [ -z "$found" ]; then
        echo "$binary is not in the archive: the release layout changed" >&2
        exit 1
    fi
    install -m 0755 "$found" "$INSTALL_DIR/$binary"
done

"$INSTALL_DIR/runsc" --version | head -n 1
"$INSTALL_DIR/runsc" install            # adds the "runsc" runtime to /etc/docker/daemon.json
systemctl restart docker

# The proof that it works: a container under gVisor that says hello.
for _ in 1 2 3 4 5 6 7 8 9 10; do
    if docker info >/dev/null 2>&1; then break; fi
    sleep 1
done
docker run --rm --runtime runsc --network none "$TEST_IMAGE" \
    python -c "import platform; print('hello from inside gVisor, kernel', platform.release())"
