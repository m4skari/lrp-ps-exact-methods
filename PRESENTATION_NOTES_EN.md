# Speaker Notes: LRP-PS Presentation

The slides are intentionally math-heavy. The main points to emphasize are:

1. Large GVs do not visit customers. They only replenish opened pick-up stations.
2. Customer demand is satisfied either by a station or by a small GV route, never both.
3. The objective includes station opening, discounted large-GV station round trip, station handling, small-GV fixed cost, and small-GV travel.
4. Constraints (2)-(4) are assignment, coverage/opening, and station capacity constraints.
5. Routing constraints are only for small GVs: depot balance, fleet cap, customer flow, load flow, and battery propagation.
6. In the paper decomposition, station patterns become knapsack-type columns and small-GV routes become ESPPRC-type columns.
7. The master problem is a set-partitioning model over feasible columns.
8. MCI cuts are derived from minimal covers of station-capacity constraints.
9. B&C + MCI is exact because these cuts are globally valid.
10. MCI count is large when many customers are near the same station and station capacity is tight.
11. MCI count is small when neighborhoods are sparse, station capacity is loose, or root/node LP solutions do not violate the covers.
12. In this benchmark, B&P is faster than B&C + MCI, but both certify the same optimum.
13. GitHub push was attempted separately; if no credential is available, add the final repository URL manually after upload.
