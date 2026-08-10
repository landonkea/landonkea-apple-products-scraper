# ───────────────────────────────────────────────────────────────────
# Product type registry
# ───────────────────────────────────────────────────────────────────
# Maps a SearchConfig's `product_type` string to the handler that
# knows how to parse/filter/score listings of that kind. See
# src/product_types/base.py for the interface and how to add a new
# entry here.
# ───────────────────────────────────────────────────────────────────

from product_types.electronics import ElectronicsHandler
from product_types.apparel import ApparelHandler

PRODUCT_TYPES = {
    "electronics": ElectronicsHandler(),
    # The reference "genuinely different category" implementation --
    # see product_types/apparel.py's module docstring. Not referenced
    # by any active config.yaml `searches:` entry (see the commented-
    # out example there), so registering it here has no effect on
    # production runs until a search actually opts into it.
    "apparel": ApparelHandler(),
}
