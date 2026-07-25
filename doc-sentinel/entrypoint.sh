#!/bin/sh
set -e

# The Actions runner mounts the checkout with a different owner than the
# container user; git refuses to operate on it without this.
git config --global --add safe.directory "${GITHUB_WORKSPACE:-/github/workspace}"

exec doc-sentinel "$@"
