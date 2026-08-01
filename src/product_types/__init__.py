# ───────────────────────────────────────────────────────────────────
# Product type registry
# ───────────────────────────────────────────────────────────────────
# Maps a SearchConfig's `product_type` string to the handler that
# knows how to parse/filter/score listings of that kind. See
# src/product_types/base.py for the interface and how to add a new
# entry here.
# ───────────────────────────────────────────────────────────────────

from product_types.electronics import ElectronicsHandler

PRODUCT_TYPES = {
    "electronics": ElectronicsHandler(),
}
