# ───────────────────────────────────────────────────────────────────
# Apparel product type — boots/footwear, the second ProductTypeHandler
# ───────────────────────────────────────────────────────────────────
# WHAT: This is the "genuinely different category" example promised
# by src/product_types/base.py's module docstring and config.yaml's
# PRODUCT TYPES section -- proof that the pluggable architecture built
# for electronics.py actually generalizes, not just documentation that
# claims it would. Boots were picked (over, say, a second Apple
# product) specifically because nothing here resembles chip/RAM/
# storage: size/brand/color instead, a completely different accessory
# keyword list, and a completely different scoring rationale (brand
# reputation and deadstock/new condition instead of spec tier).
#
# WHY BOOTS: the exact example already used in base.py's "HOW TO ADD
# A NEW PRODUCT TYPE" comment and electronics.py's file docstring, so
# implementing it validates the documented plan rather than inventing
# a new one that might not actually fit the interface as described.
#
# WHAT THIS DOES NOT DO: this file does not add a dedicated boots
# retailer scraper (e.g. a Nordstrom Rack scraper). Per base.py's
# docstring, the general marketplaces (eBay, Swappa, Mercari, OfferUp,
# BackMarket, Craigslist, Facebook) already build their search queries
# from `product_name` alone and need zero changes to search apparel --
# that's the whole point of the abstraction. A dedicated retailer
# scraper is optional follow-up work, not required to prove the
# product_type plumbing works end to end.
#
# NOT ENABLED IN THE LIVE config.yaml: adding a real `searches:` entry
# would make every production run actually scrape and alert on boots
# alongside MacBook Pro/iPhone, which isn't what this repo's owner
# wants their Discord channel doing. See config.yaml's commented-out
# example entry and tests/test_product_types_apparel.py for how to
# exercise this handler without touching production behavior.
# ───────────────────────────────────────────────────────────────────

import re
from typing import Optional

from product_types.base import ProductTypeHandler


# ── Spec-parsing helpers ───────────────────────────────────────────
# Mirrors electronics.py's extract_*() helpers in shape (plain
# functions, regex/keyword-driven, return None when not found) but
# for a completely different field set.

# Recognized boot brands, most-common-first. Not exhaustive -- new
# brands can be added here without touching any other file, same as
# electronics.py's chip regex needing no change for new chip names.
KNOWN_BRANDS = [
    "Red Wing", "Wolverine", "Thorogood", "Danner", "Chippewa",
    "Timberland", "Dr. Martens", "Doc Martens", "Carhartt",
    "Whites Boots", "White's Boots", "Nicks Boots", "Nick's Boots",
    "Viberg", "Alden", "Frye", "Blundstone", "Ariat",
]

KNOWN_COLORS = [
    "black", "brown", "tan", "oxblood", "amber", "chestnut",
    "brindle", "moc toe", "copper", "natural", "olive", "navy",
    "gray", "grey", "white", "cream",
]


def extract_size(title: str) -> Optional[float]:
    """
    Find a US shoe/boot size in a listing title.

    Looks for patterns like "Size 10.5", "Size: 11", "10.5 D", or a
    bare "sz 9". Half sizes (10.5) are common in footwear, unlike
    electronics.py's screen sizes, so this always returns a float.

    Returns:
        The US size (e.g. 10.5), or None if not found.
    """
    patterns = [
        r'\bsize[:\s]*(\d{1,2}(?:\.5)?)\b',
        r'\bsz[:\s]*(\d{1,2}(?:\.5)?)\b',
        r'\b(\d{1,2}(?:\.5)?)\s*(?:us|d|ee|eee)\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            val = float(match.group(1))
            if 4 <= val <= 16:  # plausible adult US boot size range
                return val
    return None


def extract_brand(title: str) -> Optional[str]:
    """Find a known boot brand in a listing title (case-insensitive)."""
    title_lower = title.lower()
    for brand in KNOWN_BRANDS:
        if brand.lower() in title_lower:
            return brand
    return None


def extract_color(title: str) -> Optional[str]:
    """Find a known color/leather-tone keyword in a listing title."""
    title_lower = title.lower()
    for color in KNOWN_COLORS:
        if color in title_lower:
            return color
    return None


# Accessory/off-topic keywords -- things that mention a boot brand or
# "boots" but aren't a pair of boots (mirrors electronics.py's
# ACCESSORY_KEYWORDS: reject before real matching runs).
ACCESSORY_KEYWORDS = [
    "laces only", "shoelaces", "bootlaces", "shoe laces",
    "insoles", "inserts", "shoe trees", "boot trees", "cedar shoe",
    "polish", "leather conditioner", "cleaning kit", "boot cream",
    "box only", "empty box", "sticker", "keychain", "patch",
    "socks", "sock", "boot socks",
    "for parts", "sole only", "heel only", "replacement sole",
]

# Condition red flags -- worth rejecting the same way electronics.py
# rejects "broken"/"cracked" MacBooks, since a badly damaged pair
# isn't a real deal regardless of price.
BAD_CONDITION_KEYWORDS = [
    "as-is", "as is", "for parts", "no soles", "sole separation",
    "heavily worn", "destroyed", "beyond repair",
]

# A real pair of boots essentially never lists for less than this;
# anything cheaper is almost certainly an accessory (laces, insoles)
# that slipped past the keyword filter (mirrors electronics.py's
# MINIMUM_PRICE_USD floor).
MINIMUM_PRICE_USD = 50


class ApparelHandler(ProductTypeHandler):
    """
    Boots/footwear -- the second ProductTypeHandler, proving the
    interface defined in base.py generalizes beyond Apple hardware.
    See this module's docstring for the full rationale.
    """

    def parse_specs(self, title: str) -> dict:
        return {
            "size": extract_size(title),
            "brand": extract_brand(title),
            "color": extract_color(title),
        }

    def is_relevant(self, title: str, search, condition: Optional[str] = None) -> bool:
        title_lower = title.lower()
        condition_lower = (condition or "").lower()

        for kw in ACCESSORY_KEYWORDS:
            if kw in title_lower or kw in condition_lower:
                return False
        for kw in BAD_CONDITION_KEYWORDS:
            if kw in title_lower or kw in condition_lower:
                return False

        return True

    def passes_type_filters(self, listing, search) -> bool:
        s = search

        # Size match (only if sizes is configured -- empty means "any
        # size", same "skip the check if unset" convention electronics
        # uses for chip/ram/storage).
        if s.sizes and listing.size:
            if not any(abs(listing.size - size) < 0.01 for size in s.sizes):
                return False

        # Color match (only if colors is configured).
        if s.colors and listing.color:
            if listing.color.lower() not in [c.lower() for c in s.colors]:
                return False

        return True

    def score_bonuses(self, listing, search) -> float:
        s = search
        bonus = 0.0

        # Preferred-brand bonus (weight: high) -- brand reputation
        # matters a lot more for boots than for a MacBook, where spec
        # tier (RAM/chip) dominates instead.
        if listing.brand and s.preferred_brands:
            if listing.brand.lower() in [b.lower() for b in s.preferred_brands]:
                bonus += 10

        # Exact size match bonus (weight: medium) -- mirrors
        # electronics.py's RAM-tier bonus shape.
        if listing.size and s.sizes:
            if any(abs(listing.size - size) < 0.01 for size in s.sizes):
                bonus += 5

        # New/deadstock condition bonus (weight: medium) -- boots see
        # much wider used-condition variance than electronics, so
        # condition wording carries more scoring weight here than the
        # general condition check price_analyzer.py already does.
        condition_lower = (listing.condition or "").lower()
        title_lower = (listing.title or "").lower()
        if any(kw in condition_lower or kw in title_lower
               for kw in ("deadstock", "new in box", "nib", "brand new")):
            bonus += 6

        # Color preference bonus (weight: low)
        if listing.color and s.colors:
            if listing.color.lower() in [c.lower() for c in s.colors]:
                bonus += 2

        return bonus

    def min_price_usd(self, search) -> float:
        return MINIMUM_PRICE_USD
