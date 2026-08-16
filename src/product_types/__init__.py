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
from product_types.vision_pro import VisionProHandler
from product_types.ebike import EbikeHandler

PRODUCT_TYPES = {
    "electronics": ElectronicsHandler(),
    # The reference "genuinely different category" implementation --
    # see product_types/apparel.py's module docstring. Not referenced
    # by any active config.yaml `searches:` entry (see the commented-
    # out example there), so registering it here has no effect on
    # production runs until a search actually opts into it.
    "apparel": ApparelHandler(),
    # Apple Vision Pro -- see product_types/vision_pro.py's module
    # docstring for why it's a dedicated handler rather than an
    # electronics.py `searches:` entry (no RAM tier, no Pro/Max chip
    # tier, its own accessory keyword list). Referenced by an active
    # searches: entry in config.yaml.
    "vision_pro": VisionProHandler(),
    # Folding step-through commuter e-bikes -- see
    # product_types/ebike.py's module docstring. Unlike apparel, this
    # one IS referenced by an active config.yaml `searches:` entry.
    "ebike": EbikeHandler(),
}
