#!/bin/bash
set -e
umask 077

app_dir="$(cd -- "$(dirname -- "$0")" && pwd)/macOS"
machine="$(/usr/bin/uname -m)"
case "$machine" in
  arm64) target=aarch64 ;;
  x86_64) target=x86_64 ;;
  *)
    printf 'Этот процессор macOS не поддерживается: %s\n' "$machine"
    exit 1 ;;
esac

runtime_dir="$HOME/Library/Caches/AltegioAnalyticsClient/3.13.18-20261110-$target"

install_runtime() (
  mkdir -p "$(dirname -- "$runtime_dir")" || exit 1
  stage="$(mktemp -d "$(dirname -- "$runtime_dir")/.unpack.XXXXXX")" || exit 1
  trap 'rm -rf -- "$stage"' EXIT
  /usr/bin/tar -xzf "$app_dir/runtime/python-$target.tar.gz" -C "$stage" || exit 1
  # Publish the complete directory atomically, including on a second launch.
  "$stage/python/bin/python3.13" -I - "$stage/python" "$runtime_dir" <<'PYTHON'
import errno
import os
import sys

source, destination = sys.argv[1:]
try:
    os.rename(source, destination)
except OSError as error:
    if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
        raise
PYTHON
)

if [ ! -x "$runtime_dir/bin/python3.13" ]; then
  printf 'Готовим Altegio Analytics к первому запуску…\n'
  if ! install_runtime; then
    printf 'Не удалось распаковать приложение. Распакуйте весь ZIP и повторите запуск.\n'
    read -r -p 'Нажмите Enter, чтобы закрыть окно.' || true
    exit 1
  fi
fi

if [ -z "${SSL_CERT_FILE:-}" ] && [ -r /etc/ssl/cert.pem ]; then
  export SSL_CERT_FILE=/etc/ssl/cert.pem
fi

if ! "$runtime_dir/bin/python3.13" -E -s -B "$app_dir/scripts/client_macos.py"; then
  read -r -p 'Нажмите Enter, чтобы закрыть окно.' || true
  exit 1
fi
