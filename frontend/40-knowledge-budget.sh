#!/bin/sh
set -eu
file_bytes=${KNOWLEDGE_MAX_FILE_BYTES:?required}
metadata_bytes=${KNOWLEDGE_REQUEST_METADATA_BYTES:?required}
document_chars=${KNOWLEDGE_MAX_DOCUMENT_CHARS:?required}
case "$file_bytes:$metadata_bytes:$document_chars" in *[!0-9:]*|:*|*::*|*:) exit 1;; esac
file_budget=$((4 * ((file_bytes + 2) / 3) + metadata_bytes))
text_budget=$((12 * document_chars + metadata_bytes))
sed -e "s/__KNOWLEDGE_FILE_BODY_BYTES__/$file_budget/g" \
    -e "s/__KNOWLEDGE_TEXT_BODY_BYTES__/$text_budget/g" \
    /etc/nginx/knowledge.conf.template > /etc/nginx/conf.d/default.conf
