#!/usr/bin/env bash
set -euo pipefail

# Tampilkan lsusb dulu (output "sebelumnya")
echo "=== lsusb ==="
lsusb || true
echo

# Cari /dev/video* dan tampilkan info manusiawi
shopt -s nullglob
devices=(/dev/video*)

if [ ${#devices[@]} -eq 0 ]; then
  echo "Tidak ada /dev/video* ditemukan."
fi

entry_count=0
json="["

for dev in "${devices[@]}"; do
  [ -e "$dev" ] || continue

  # Ambil properti udev
  UDEV=$(udevadm info --query=property --name="$dev" 2>/dev/null || true)

  VID=$(echo "$UDEV" | awk -F= '/ID_VENDOR_ID/ {print $2; exit}')
  PID=$(echo "$UDEV" | awk -F= '/ID_MODEL_ID/ {print $2; exit}')
  VENDOR=$(echo "$UDEV" | awk -F= '/ID_VENDOR=/ {print $2; exit}')
  PRODUCT=$(echo "$UDEV" | awk -F= '/ID_MODEL=/ {print $2; exit}')
  [ -z "$PRODUCT" ] && PRODUCT="Unknown"

  echo "Device: $dev"
  echo "  Vendor: ${VENDOR:-?} id:${VID:-?}"
  echo "  Product: ${PRODUCT:-?} id:${PID:-?}"

  if [[ -n "$VID" && -n "$PID" ]]; then
    idhex="${VID}:${PID}"
    match=$(lsusb | grep -i "$idhex" || true)
    if [[ -n "$match" ]]; then
      echo "  lsusb: $match"
    fi
  fi

  echo

  # Escape untuk JSON (escape backslash, double quotes, newlines)
  esc_dev=$(printf '%s' "$dev" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')
  esc_prod=$(printf '%s' "$PRODUCT" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e ':a;N;s/\n/\\n/g;ta')

  json+="{\"device\":\"$esc_dev\",\"product\":\"$esc_prod\"},"
  entry_count=$((entry_count+1))
done

# Jika tidak ada entry, hasil JSON harus [].
if [ "$entry_count" -eq 0 ]; then
  json="[]"
else
  # hapus koma terakhir dan tutup array
  json="${json%,}]"
fi

# BARIS TERAKHIR: cetak JSON (pastikan ini memang line terakhir)
echo "$json"
