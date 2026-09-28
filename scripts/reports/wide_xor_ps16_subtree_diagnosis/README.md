# WIDE global XOR /16 subtree diagnosis

This report compares PS `/16` cache-set activity and routing-table descendants before and after the global 24-bit XOR selected to move each anonymous WIDE trace toward the 2026-03 non-anonymous WIDE LPM distribution.

## Cases

- WIDE 2025-09 → 2026-03: mask `0x002d2400`
- WIDE 2025-12 → 2026-03: mask `0x002d0800`
- Each case uses 10,000,000 destination packets.

A descendant node is an explicit RIB route longer than `/16` under that `/16`. It is not a count of trie leaves only.

## Main finding

For 2025-09 → 2026-03, packet-weighted descendant routes increased from 22.56 to 47.13 (2.09×); the weighted median rose from 2 to 19. For 2025-12 → 2026-03, the count increased from 21.36 to 49.56 (2.32×), and the median rose from 0 to 20.

The two worst sets accounted for 98.05% and 98.68% of misses. Across sets, second misses correlated strongly with packet count (Pearson r=0.9304 and 0.8945) but weakly with packet-weighted subtree-node count (r=0.0648 and 0.0656). Subtree size alone therefore does not explain the misses; traffic concentration, set collisions, and temporal locality also matter.

## Files

- `REPORT.md` and `summary.csv`: written summary and aggregate values.
- `wide09_set_hit_miss_before_after.png`, `wide12_set_hit_miss_before_after.png`: hit/miss counts by PS /16 set.
- `wide09_prefix16_subtree_before_after.png`, `wide12_prefix16_subtree_before_after.png`: before/after descendant-route counts by traffic-active `/16`.
- `wide09_hot_prefix16_256_children.png`, `wide12_hot_prefix16_256_children.png`: route distribution over each `/16`’s 256 `/24` child cells.
- `simple_hot_prefix_graphs/`: presentation-ready figures for child-node counts, distinct LPM entries, and second misses on the two hottest prefixes.
- `*_prefix16_mapping.csv`, `*_after_set_structure.csv`, and `simple_hot_prefix_graphs/hot_prefix_evidence.csv`: tabular evidence.
- `../../../plot_wide_xor_hot_prefix_evidence.py` and `../../../analyze_wide_xor_ps16_subtree.py`: analysis/plotting code.
- `../wide_xor_ps16_diagnosis/*/unified_cacheline_by_set.csv`: set-level inputs used by the presentation-ready plots.

The report, figures, and derived tables are included here. Raw packet captures and full RIB dumps are not included.
