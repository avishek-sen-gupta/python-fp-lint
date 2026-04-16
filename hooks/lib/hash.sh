#!/bin/sh
# hash.sh — Portable MD5 hashing helper.
# Source this file, then call: project_hash "$PWD"

project_hash() {
  printf '%s' "$1" | (md5 2>/dev/null || md5sum | cut -d' ' -f1)
}
