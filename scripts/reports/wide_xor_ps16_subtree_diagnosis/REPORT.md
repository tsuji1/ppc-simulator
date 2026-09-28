# WIDE global XOR: PS /16 subtree diagnosis

`descendant route nodes` is the number of explicit routing-table prefixes longer than /16 under a /16 node.
The 256-child plot assigns every route node to the /24 child cells it can affect; prefixes shorter than /24 span multiple cells.
All packet-weighted statistics use the same 10,000,000 destination packets as the XOR search.

## WIDE 2025-09 → 2026-03 LPM distribution

- mask: `0x002d2400`
- /0 packet share: 0.0224% → 8.1125%
- packet-weighted descendant nodes: 22.56 → 47.13 (2.09x)
- weighted median: 2 → 19
- weighted p90: 81 → 104
- two worst sets: 1011,844 (98.05% of cacheline misses)
- Pearson r(second miss, packet-weighted subtree nodes): 0.0648
- Pearson r(second miss, packets): 0.9304
- Pearson r(second miss, distinct LPM entries touched): 0.6874

## WIDE 2025-12 → 2026-03 LPM distribution

- mask: `0x002d0800`
- /0 packet share: 0.0214% → 4.7414%
- packet-weighted descendant nodes: 21.36 → 49.56 (2.32x)
- weighted median: 0 → 20
- weighted p90: 68 → 106
- two worst sets: 1011,844 (98.68% of cacheline misses)
- Pearson r(second miss, packet-weighted subtree nodes): 0.0656
- Pearson r(second miss, packets): 0.8945
- Pearson r(second miss, distinct LPM entries touched): 0.7073
