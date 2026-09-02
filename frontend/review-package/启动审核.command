#!/bin/zsh

cd "$(dirname "$0")" || exit 1
review_port=8008
open "http://localhost:${review_port}/#/login"
python3 -m http.server "$review_port"

