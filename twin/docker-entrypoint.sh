#!/bin/sh
# The Twin listens on the host written in config/twin.yaml (127.0.0.1), and nothing outside the
# container can reach that. This makes a copy of the real file with 0.0.0.0 instead, so there is
# no second config to keep in sync. Everything else in the file stays as it is.
set -e
sed 's/^\([[:space:]]*host:[[:space:]]*\)127\.0\.0\.1/\10.0.0.0/' config/twin.yaml > /tmp/twin.docker.yaml
export TWIN_CONFIG=/tmp/twin.docker.yaml
exec "$@"
