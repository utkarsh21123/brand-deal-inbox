# Evaluation (rules only)

| Check | Result |
|---|---|
| Category, strict | 11/15 |
| Category, lenient (accepts listed alternatives) | 11/15 |
| Extracted fields | 21/23 |
| Deals grouped as expected | 1/1 |
| Recommended action | 1/1 |
| Risk flags (must be present / must be absent) | 0/0 |

## Misses

- H-07: category expected `deal_offer`, got `spam`
- H-08: category expected `needs_more_info`, got `spam`
- H-12: category expected `scam_or_phishing`, got `spam`
- H-13: category expected `deal_offer`, got `not_a_fit`
- H-07: fee_inr expected 30000, got None
- H-15: brand expected 'Zest Drinks', got 'SparkReach'
