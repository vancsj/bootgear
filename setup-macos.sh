#!/bin/bash
set -euo pipefail

checkout="$(cd -- "${BASH_SOURCE[0]%/*}" && pwd)"
temporary=''
trap 'if [[ -n "$temporary" ]]; then rm -rf -- "$temporary"; fi' EXIT
if [[ "$(uname -s)" != Darwin ]]; then
    printf '%s\n' 'Bootgear Setup requires macOS.' >&2
    exit 2
fi

if [[ -f "$checkout/.claude-plugin/marketplace.json" && -x "$checkout/plugins/cli/bin/gear" ]]; then
    export BOOTGEAR_SETUP_LOCAL=1
else
    temporary="$(mktemp -d)"
    archive="$temporary/bootgear.tar.gz"
    if ! curl -fLsS --max-time 120 \
            https://codeload.github.com/vancsj/bootgear/tar.gz/refs/heads/main -o "$archive"; then
        printf '%s\n' 'Could not download Bootgear. Retry the setup command.' >&2
        exit 2
    fi
    checkout="$temporary/bootgear"
    mkdir "$checkout"
    if ! tar -xzf "$archive" --strip-components 1 -C "$checkout"; then
        printf '%s\n' 'Could not open the Bootgear download. Retry the setup command.' >&2
        exit 2
    fi
    export BOOTGEAR_SETUP_LOCAL=0
fi

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
export BOOTGEAR_SETUP_SOURCE="$checkout"
if ! command -v uv >/dev/null; then
    if ! /usr/bin/osascript -e 'display dialog "Bootgear uses uv to install and manage Python. Install uv to continue." with title "Bootgear Setup" buttons {"Cancel", "Install uv"} default button "Install uv" cancel button "Cancel"'; then
        exit 0
    fi
    if [[ -z "$temporary" ]]; then
        temporary="$(mktemp -d)"
    fi
    installer="$temporary/uv-install.sh"
    source "$checkout/plugins/cli/bin/setup-deadline.sh"
    if ! curl -fsSL --max-time 120 https://astral.sh/uv/install.sh -o "$installer" ||
            ! UV_NO_MODIFY_PATH=1 UV_INSTALL_DIR="$HOME/.local/bin" setup_with_deadline 120 /bin/sh "$installer"; then
        printf '%s\n' 'Could not install uv. Retry Bootgear Setup.' >&2
        exit 2
    fi
fi
"$checkout/plugins/cli/bin/gear" cli setup --gui
