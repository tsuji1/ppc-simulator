#!/usr/bin/env bash
set -euo pipefail

root=/home/yuzugon
runner="$root/osada-ppc-simulator/scripts/run_global_xor_lpm_tv_hitrate_one.sh"
derived="$root/pcap/derived/global-xor-lpm-tv-exhaustive24"

jobs=$(mktemp)
trap 'rm -f "$jobs"' EXIT

printf '%s\t%s\t%s\n' \
  chicago-original "$root/rules/route-views.chicago.rib.20160628.1400.unique.rule" "$root/pcap/equinix-chicago.dirB.20140320-140100.UTC.anon.pcap" \
  nyc-original "$root/rules/rrc11.bview.20190117.1600.unique.rule" "$root/pcap/equinix-nyc.dirB.20190117-135900.UTC.anon.pcap" >> "$jobs"

for date in 2025-09-27 2025-12-27 2026-03-27; do
  case "$date" in
    2025-09-27)
      rule="$root/rules/rib.20250927.0600.unique.rule"
      anon="$root/pcap/202509271400.pcap"
      real="$root/pcap/non-anon/2025-09-27.pcap"
      ;;
    2025-12-27)
      rule="$root/rules/rib.20251227.0600.unique.rule"
      anon="$root/pcap/202512271400.pcap"
      real="$root/pcap/non-anon/2025-12-27.pcap"
      ;;
    2026-03-27)
      rule="$root/rules/rib.20260327.0600.unique.rule"
      anon="$root/pcap/202603271400.pcap"
      real="$root/pcap/non-anon/2026-03-27.pcap"
      ;;
  esac
  printf '%s\t%s\t%s\n' \
    "chicago-transformed-$date" "$root/rules/route-views.chicago.rib.20160628.1400.unique.rule" "$derived/chicago/$date.txt" \
    "nyc-transformed-$date" "$root/rules/rrc11.bview.20190117.1600.unique.rule" "$derived/nyc/$date.txt" \
    "wide-original-$date" "$rule" "$anon" \
    "wide-transformed-$date" "$rule" "$derived/anon-wide/$date.txt" \
    "wide-nonanon-$date" "$rule" "$real" >> "$jobs"
done

xargs -0 -P3 -n3 "$runner" < <(while IFS=$'\t' read -r label rule trace; do
  printf '%s\0%s\0%s\0' "$label" "$rule" "$trace"
done < "$jobs")
