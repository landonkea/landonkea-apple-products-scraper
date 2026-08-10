# ───────────────────────────────────────────────────────────────────
# Vision Pro product type — Apple's headset, a third ProductTypeHandler
# ───────────────────────────────────────────────────────────────────
# WHAT: Apple Vision Pro doesn't fit electronics.py's MacBook/iPhone/
# iPad shape at all -- no RAM configuration (fixed unified memory,
# never advertised as a buyer-facing option), no "Pro"/"Max" chip
# tier, and no annual generation cycle. There have only ever been two
# real hardware variants: the original Feb 2024 launch unit (M2) and
# an internal chip refresh, same external design, announced by Apple
# on Oct 15 2025 and shipping Oct 22 2025 (M5 + a new Dual Knit Band,
# https://www.apple.com/newsroom/2025/10/apple-vision-pro-upgraded-with-the-m5-chip-and-dual-knit-band/).
# There is no "Vision Pro 2" -- Apple has not announced a redesigned
# second-generation headset as of this writing.
#
# WHY A DEDICATED HANDLER (not just a new electronics.py `searches:`
# entry): ElectronicsHandler.is_relevant() only special-cases
# "macbook"/"iphone"/"ipad" in the product name and falls through to
# `return True` for anything else -- meaning a plain "Apple Vision
# Pro" electronics search would let every case/light-seal/battery-
# cable/prescription-lens-insert accessory listing through unfiltered
# (none of those get rejected without a Vision-Pro-specific accessory
# keyword list). Reusing the interface documented in base.py --
# following apparel.py as the second, structurally-different
# precedent -- keeps that filtering real instead of silently broken.
#
# WHAT THIS REUSES FROM electronics.py: storage_gb and chip are
# genuinely the same kind of field Vision Pro listings use ("512GB",
# "M5"), so parse_specs() calls electronics.py's extract_storage_gb()/
# extract_chip() directly rather than reimplementing near-identical
# regexes (unlike apparel.py, whose size/brand/color fields have no
# electronics.py equivalent to reuse).
# ───────────────────────────────────────────────────────────────────

from typing import Optional

from product_types.base import ProductTypeHandler
from product_types.electronics import extract_storage_gb, extract_chip


# Accessory / off-topic keywords -- things that mention "Vision Pro"
# (because they're compatible with it) but aren't the headset itself.
# Mirrors electronics.py's ACCESSORY_KEYWORDS / apparel.py's
# ACCESSORY_KEYWORDS in spirit: reject before real spec matching runs.
ACCESSORY_KEYWORDS = [
    "case", "travel case", "carrying case", "cover", "sleeve", "pouch",
    "light seal", "light seal cushion", "eye cushion", "face cushion",
    "head strap", "solo knit band", "dual loop band", "dual knit band",
    "battery pack", "battery cable", "replacement battery", "power bank",
    "prescription lens", "prescription insert", "zeiss", "optic insert",
    "polishing cloth", "cleaning cloth", "screen protector",
    "front cover", "lens protector", "dust cover",
    "compatible with", "for apple vision pro",
    "charger", "charging cable", "power adapter", "power cord",
    "stand", "mount", "holder", "display case", "shipping box only",
    "empty box", "box only", "manual only",
    "repair", "replacement part", "spare part", "logic board",
    "for parts", "parts only",
]

BAD_CONDITION_KEYWORDS = [
    "for parts", "parts only", "not working", "doesn't work",
    "does not work", "broken", "cracked", "screen damage",
    "water damage", "defective", "faulty", "as-is", "as is",
    "icloud locked", "activation locked",
]

# A real Vision Pro unit essentially never lists for less than this;
# anything cheaper is almost certainly an accessory that slipped past
# the keyword filter, or a parts/broken unit not worth surfacing as a
# "deal" (mirrors electronics.py's MINIMUM_PRICE_USD / apparel.py's
# MINIMUM_PRICE_USD floor pattern).
MINIMUM_PRICE_USD = 500

# Storage tiers Apple actually sells (GB). Used only to decide which
# score bonus tier a listing falls into -- passes_type_filters()
# still defers min/max range checks to config.yaml's
# storage_gb_min/storage_gb_max like every other search.
STORAGE_TIERS = {256: 0, 512: 6, 1024: 12}
# WHY THESE WEIGHTS: this repo's owner asked for the biggest/best
# (1TB) configuration to rank toward the top of the alert list. 1TB
# gets double 512GB's bonus and a clear step above 256GB, without
# swamping the price-vs-median factor (still capped well under that
# factor's +30 max) -- same "meaningful but not dominant" weighting
# electronics.py uses for its own RAM-tier bonus.


class VisionProHandler(ProductTypeHandler):
    """
    Apple Vision Pro -- the third ProductTypeHandler. See this
    module's docstring for why it's dedicated rather than folded into
    ElectronicsHandler.
    """

    def parse_specs(self, title: str) -> dict:
        return {
            "storage_gb": extract_storage_gb(title),
            "chip": extract_chip(title),
        }

    def is_relevant(self, title: str, search, condition: Optional[str] = None) -> bool:
        title_lower = title.lower()
        condition_lower = (condition or "").lower()

        if "vision pro" not in title_lower:
            return False

        for kw in ACCESSORY_KEYWORDS:
            if kw in title_lower or kw in condition_lower:
                return False
        for kw in BAD_CONDITION_KEYWORDS:
            if kw in title_lower or kw in condition_lower:
                return False

        return True

    def passes_type_filters(self, listing, search) -> bool:
        s = search

        # Storage minimum/maximum (same convention as electronics.py:
        # only checked when the listing has a parsed value AND the
        # search configures a bound).
        if s.storage_gb_min and listing.storage_gb:
            if listing.storage_gb < s.storage_gb_min:
                return False
        if s.storage_gb_max and listing.storage_gb:
            if listing.storage_gb > s.storage_gb_max:
                return False

        return True

    def score_bonuses(self, listing, search) -> float:
        bonus = 0.0

        # Storage-tier bonus (weight: medium-high) -- see STORAGE_TIERS
        # above for why 1TB is weighted well above 512GB/256GB.
        if listing.storage_gb in STORAGE_TIERS:
            bonus += STORAGE_TIERS[listing.storage_gb]

        # Chip bonus (weight: medium) -- the Oct 2025 M5 refresh is the
        # newer, more capable, more desirable unit vs. the original Feb
        # 2024 M2 launch unit (see module docstring). Only ever applies
        # when the listing actually states a chip -- most listings
        # (especially of the original M2 unit, which Apple never
        # marketed by chip name) mention neither, and get no bonus
        # either way rather than being penalized for an unknown chip.
        if listing.chip:
            chip_lower = listing.chip.lower()
            if "m5" in chip_lower:
                bonus += 8
            elif "m2" in chip_lower:
                bonus += 0

        return bonus

    def min_price_usd(self, search) -> float:
        return MINIMUM_PRICE_USD
