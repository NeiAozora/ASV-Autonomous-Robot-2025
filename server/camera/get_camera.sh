#!/usr/bin/env bash
set -euo pipefail

# Print lsusb first (output "sebelumnya")
echo "=== lsusb ==="
lsusb || true
echo

# function: escape string for JSON (basic)
json_escape() {
  # replace backslash, newline, double-quote
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e ':a;N;s/\n/\\n/g;ta'
}

shopt -s nullglob
devices=(/dev/video*)

if [ ${#devices[@]} -eq 0 ]; then
  echo "Tidak ada /dev/video* ditemukan."
fi

json="[" 
count=0

for dev in "${devices[@]}"; do
  [ -e "$dev" ] || continue

  echo "Device: $dev"

  # sysfs path to the device node (follow symlink)
  sys_dev=$(readlink -f "/sys/class/video4linux/$(basename "$dev")/device" 2>/dev/null || true)
  if [ -z "$sys_dev" ]; then
    echo "  (tidak dapat menemukan sysfs path untuk $dev)"
    product_if="Unknown"
    vid=""
    pid=""
    lsusb_match=""
  else
    # ascend parents until we find a dir that contains idVendor (USB device)
    usb_dev="$sys_dev"
    while [ "$usb_dev" != "/" ] && [ ! -f "$usb_dev/idVendor" ]; do
      usb_dev=$(dirname "$usb_dev")
    done

    if [ -f "$usb_dev/idVendor" ]; then
      vid=$(cat "$usb_dev/idVendor" 2>/dev/null || true)
      pid=$(cat "$usb_dev/idProduct" 2>/dev/null || true)
      manuf=$(cat "$usb_dev/manufacturer" 2>/dev/null || true)
      product_usb=$(cat "$usb_dev/product" 2>/dev/null || true)
      # try get bus/dev numbers from sysfs (busnum/devnum) or uevent
      busnum=$(cat "$usb_dev/busnum" 2>/dev/null || true)
      devnum=$(cat "$usb_dev/devnum" 2>/dev/null || true)
      if [ -z "$busnum" ] && [ -f "$usb_dev/uevent" ]; then
        busnum=$(grep -m1 '^BUSNUM=' "$usb_dev/uevent" 2>/dev/null | sed 's/^BUSNUM=//')
        devnum=$(grep -m1 '^DEVNUM=' "$usb_dev/uevent" 2>/dev/null | sed 's/^DEVNUM=//')
      fi

      # get the interface-level name reported by udev (if any)
      udev_props=$(udevadm info --query=property --path="$sys_dev" 2>/dev/null || true)
      model_if=$(echo "$udev_props" | awk -F= '/ID_MODEL=/ {print $2; exit}')
      [ -z "$model_if" ] && model_if="Unknown"

      echo "  sysfs usb dev: $usb_dev"
      echo "  Vendor: ${manuf:-?} id:${vid:-?}"
      echo "  Product (USB descriptor): ${product_usb:-?} id:${pid:-?}"
      echo "  Interface name (udev): ${model_if:-?}"
      if [ -n "$busnum" ] || [ -n "$devnum" ]; then
        printf "  bus: %s dev: %s\n" "${busnum:-?}" "${devnum:-?}"
      fi

      # try to match lsusb: prefer Bus/Device numbers, otherwise match by idVendor:idProduct
      lsusb_line=""
      if [ -n "$busnum" ] && [ -n "$devnum" ]; then
        # format Bus 001 Device 004:
        # we match using awk fields to avoid locale issues
        lsusb_line=$(lsusb | awk -v b="$busnum" -v d="$devnum" 'BEGIN{IGNORECASE=1} $2==b && $4==d":"{print; exit}')
      fi
      if [ -z "$lsusb_line" ] && [ -n "$vid" ] && [ -n "$pid" ]; then
        lsusb_line=$(lsusb | grep -i "${vid}:${pid}" || true)
        # restrict to first match
        lsusb_line=$(printf '%s\n' "$lsusb_line" | head -n1)
      fi
      if [ -n "$lsusb_line" ]; then
        echo "  lsusb match: $lsusb_line"
      else
        echo "  lsusb: tidak ditemukan entri yang cocok (dengan bus/dev atau idVendor:idProduct)"
      fi

      product_if="$model_if"
      lsusb_match="$lsusb_line"
    else
      echo "  (tidak menemukan parent USB device yang berisi idVendor/idProduct)"
      product_if="Unknown"
      vid=""
      pid=""
      lsusb_match=""
    fi
  fi

  echo

  # prepare JSON entry (pakai interface name sebagai product, fallback ke usb product)
  if [ -n "$product_if" ] && [ "$product_if" != "Unknown" ]; then
    json_prod="$product_if"
  elif [ -n "$product_usb" ]; then
    json_prod="$product_usb"
  else
    json_prod="Unknown"
  fi

  # escape
  esc_dev=$(json_escape "$dev")
  esc_prod=$(json_escape "$json_prod")

  json+="{\"device\":\"$esc_dev\",\"product\":\"$esc_prod\"},"
  count=$((count+1))
done

# finalize JSON
if [ "$count" -eq 0 ]; then
  json="[]"
else
  json="${json%,}]"
fi

# BARIS TERAKHIR: hanya cetak JSON array (pastikan ini benar-benar baris terakhir)
echo "$json"
