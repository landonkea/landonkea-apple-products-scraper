# ───────────────────────────────────────────────────────────────────
# Electronics product type — MacBook Pro / iPhone specific logic
# ───────────────────────────────────────────────────────────────────
# This is a relocation, not a rewrite: everything in this file used
# to live directly in src/scrapers/base.py and src/price_analyzer.py.
# It's the reference implementation of ProductTypeHandler (see
# src/product_types/base.py) — read that file first if you're adding
# a new product type; this one is the example to structurally match.
# ───────────────────────────────────────────────────────────────────

import re
from typing import Optional

from product_types.base import ProductTypeHandler


# ── Spec-parsing helpers ───────────────────────────────────────────
# These extract structured data from messy listing titles like:
#   "Apple MacBook Pro 14\" M5 Max Chip 128GB Memory 2TB SSD - Space Black"

def extract_ram_gb(title: str) -> Optional[int]:
    """
    Find RAM size in a listing title.

    Looks for patterns like "128GB", "128 GB", "64GB" near "RAM",
    "Memory", "Unified Memory", or "GB" of memory.

    Strategy:
      1. First try to match "N GB" near "RAM"/"Memory" keywords
         (most reliable).
      2. Fallback: match any "N GB" where N is a reasonable RAM
         size (8-256).  Higher numbers are typically storage.

    Returns:
        The RAM in GB (e.g. 128), or None if not found.
    """
    # Pattern 1: number GB followed by a RAM keyword
    patterns = [
        r'(\d+)\s*GB\s*(?:RAM|Memory|Unified\s*Memory)',
        r'(?:RAM|Memory|Unified\s*Memory)[:\s]*(\d+)\s*GB',
    ]
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            val = int(match.group(1))
            if val <= 256:
                return val

    # Pattern 2: just "N GB" alone — but only if N is a reasonable
    # RAM size (not storage).  MacBook Pro RAM configs are:
    # 8, 16, 24, 32, 36, 48, 64, 96, 128, 192
    # Storage always starts at 256+ GB.
    all_gb = re.findall(r'(\d+)\s*GB', title, re.IGNORECASE)
    for val_str in all_gb:
        val = int(val_str)
        if val in (8, 16, 24, 32, 36, 48, 64, 96, 128, 192):
            return val
    for val_str in all_gb:
        val = int(val_str)
        if val <= 256:
            return val

    return None


def extract_storage_gb(title: str) -> Optional[int]:
    """
    Find storage (SSD) size in a listing title.

    Looks for patterns like "2TB", "2 TB", "512GB", "8TB SSD".

    Strategy:
      1. Match "N TB" (always storage).
      2. Match "N GB SSD" or "N GB Storage" (explicit).
      3. Match "N GB" where N >= 256 (storage sizes are always
         at least 256GB on MacBook Pros).

    Returns:
        The storage in GB (e.g. 2048 for 2TB), or None.
    """
    # Pattern 1: TB always means storage
    tb_match = re.search(r'(\d+)\s*TB\s*(?:SSD)?', title, re.IGNORECASE)
    if tb_match:
        return int(tb_match.group(1)) * 1024

    # Pattern 2: GB with explicit storage keyword
    gb_storage = re.search(
        r'(\d+)\s*GB\s*(?:SSD|Storage)', title, re.IGNORECASE
    )
    if gb_storage:
        val = int(gb_storage.group(1))
        if val >= 256:
            return val

    # Pattern 3: "N GB" with N >= 256 (only storage is this big)
    all_gb = re.findall(r'(\d+)\s*GB', title, re.IGNORECASE)
    for val_str in all_gb:
        val = int(val_str)
        if val >= 256:
            return val

    return None


def extract_screen_size(title: str) -> Optional[float]:
    """
    Find screen size in a listing title.

    Looks for patterns like:
      - "14-inch", "14 inch", "14.2-inch"
      - '14"', '14.2"'
    """
    patterns = [
        r'(\d+(?:\.\d+)?)[\s-]*inch',   # "14-inch" or "14 inch"
        r'(\d+(?:\.\d+)?)"',             # '14"' or '14.2"'
    ]
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def extract_chip(title: str) -> Optional[str]:
    """
    Find the chip name in a listing title.

    Looks for "M5 Max", "M4 Max", "M5 Pro", etc.
    Also matches plain "M4", "M5" without suffix.

    Uses M\\d{1,2} (not a hardcoded M1-M5 range) so future chip
    generations (M6, M7, ...) parse correctly without a code change.
    """
    match = re.search(r'(M\d{1,2}\s*(?:Pro|Max|Ultra))', title, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r'\b(M\d{1,2})\b', title, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def extract_core_counts(title: str) -> tuple[Optional[int], Optional[int]]:
    """
    Find CPU and GPU core counts in a listing title.

    Looks for Apple's standard spec phrasing, e.g.
    "16-Core CPU and 40-Core GPU" or "16 Core CPU / 40 Core GPU".

    Returns:
        (cpu_cores, gpu_cores) — either may be None if not found.
    """
    cpu_cores = None
    gpu_cores = None

    cpu_match = re.search(r'(\d+)[\s‑-]*Core\s*CPU', title, re.IGNORECASE)
    if cpu_match:
        cpu_cores = int(cpu_match.group(1))

    gpu_match = re.search(r'(\d+)[\s‑-]*Core\s*GPU', title, re.IGNORECASE)
    if gpu_match:
        gpu_cores = int(gpu_match.group(1))

    return cpu_cores, gpu_cores


ACCESSORY_KEYWORDS = [
    "case", "cover", "skin", "decals", "sticker", "sleeve", "bag",
    "charger", "adapter", "power cord", "cable", "hub", "docking",
    "keyboard", "mouse", "trackpad", "screen protector", "tempered glass",
    "stand", "mount", "arm", "holder", "tray", "shell", "hard shell",
    "battery", "replacement battery", "strap", "backpack",
    "logic board", "motherboard", "lcd", "display", "digitizer",
    "flex cable", "ribbon cable", "hinge", "palm rest", "top case",
    "bottom case", "fan", "speaker", "wrist rest", "bezel",
    "repair", "replacement", "parts", "for parts", "not working",
    "broken", "damaged", "for repair", "as-is", "as is",
    "screen only", "cracked", "water damage",
    "defective", "faulty", "does not work", "doesn't work",
]

IPHONE_BAD_KEYWORDS = [
    "locked", "icloud", "activation lock",
    "for parts", "not working", "broken", "cracked", "damaged",
    "water damage", "for repair", "as is", "as-is", "parts only",
    "repair needed", "stolen", "blacklisted",
    "hardware locked", "sim locked", "carrier locked",
    "network locked", "bad imei",
    "defective", "faulty", "does not work", "doesn't work",
]

# iPhone accessory titles very often literally contain the phone's
# generation name (e.g. "Case for iPhone 15 Pro Max") since that's
# the product they're compatible with — so, unlike MacBook listings,
# a plain "does the title mention iPhone 15 Pro Max" search can't
# tell an accessory apart from an actual phone. This list plus the
# MINIMUM_PRICE_USD/storage check in is_likely_iphone() is what
# actually filters them out.
IPHONE_ACCESSORY_KEYWORDS = [
    "case", "cover", "skin", "decal", "sticker", "sleeve", "pouch",
    "screen protector", "tempered glass", "privacy glass", "camera lens",
    "charger", "charging cable", "cable", "adapter", "magsafe charger",
    "power bank", "battery pack", "car mount", "mount", "holder", "stand",
    "wallet", "lanyard", "strap", "pop socket", "popsocket", "stylus",
    "earbuds", "airpods", "headphones", "screen only", "lcd", "digitizer",
    "back glass", "housing", "flex cable", "logic board", "motherboard",
    "for parts", "repair part", "replacement part",
]

# A real iPhone listing almost always states storage capacity
# ("128GB", "256GB", "1TB", ...) — accessories essentially never do.
MINIMUM_IPHONE_PRICE_USD = 100

# Minimum price for a real computer (anything cheaper is an accessory/part)
MINIMUM_PRICE_USD = 200

# iPad-specific keywords for filtering accessories
IPAD_ACCESSORY_KEYWORDS = [
    "case", "cover", "skin", "sleeve", "bag", "pouch", "shell",
    "screen protector", "tempered glass", "privacy glass",
    "charger", "charging cable", "cable", "adapter", "power bank",
    "keyboard", "keyboard case", "smart keyboard", "magic keyboard",
    "apple pencil", "stylus", "pen", "holder", "stand", "mount",
    "car mount", "arm", "tray", "dock", "docking station",
    "hub", "adapter", "converter", "dongle",
    "repair", "replacement", "parts", "for parts", "not working",
    "broken", "damaged", "for repair", "as-is", "as is",
    "screen only", "cracked", "water damage",
    "defective", "faulty", "does not work", "doesn't work",
    "lcd", "digitizer", "flex cable", "ribbon cable",
    "logic board", "motherboard", "battery",
]

IPAD_BAD_KEYWORDS = [
    "locked", "icloud", "activation lock",
    "for parts", "not working", "broken", "cracked", "damaged",
    "water damage", "for repair", "as is", "as-is", "parts only",
    "repair needed", "stolen", "blacklisted",
    "defective", "faulty", "does not work", "doesn't work",
]


def is_likely_macbook_pro(title: str, condition: Optional[str] = None) -> bool:
    """
    Check if a title is likely a real MacBook Pro (not an accessory).

    Filters out items like cases, chargers, keyboards that mention
    "MacBook" but aren't actual computers.

    A real MacBook Pro listing has:
      - "MacBook Pro" in the title (not just "MacBook")
      - No accessory keywords (case, charger, cable, etc.)
      - At least one hardware spec: chip (M1-M5), screen size, RAM,
        or storage

    Args:
        title: The listing title to check.
        condition: The marketplace's condition label, if available
            (e.g. eBay's "Parts Only" badge). Some red-flag signals
            (like "parts only") show up ONLY here, not in the title
            text — a listing found live had title "Apple iPhone 15
            Pro Max - 1 TB - Blue Titanium (Unlocked)" with condition
            "Parts Only", so title-only keyword checks missed it
            entirely. Checked alongside the title, not in place of it.

    Returns:
        True if this looks like an actual MacBook Pro computer.
    """
    title_lower = title.lower()
    condition_lower = (condition or "").lower()

    # Must be a MacBook Pro (not just MacBook)
    if "macbook pro" not in title_lower:
        return False

    # Exclude accessories/red-flag condition by keyword — checked
    # against both the title and the marketplace's condition label.
    for kw in ACCESSORY_KEYWORDS:
        if kw in title_lower or kw in condition_lower:
            return False

    # Must have at least one hardware indicator
    has_chip = bool(re.search(r'M\d{1,2}\s*(?:Pro|Max|Ultra)', title, re.IGNORECASE))
    has_screen = bool(re.search(r'\d{2}\s*[‑\-]?\s*inch', title, re.IGNORECASE)) or bool(re.search(r'\d{2}"', title))
    has_ram = bool(re.search(r'\d+\s*GB\s*(?:RAM|Memory|Unified)', title, re.IGNORECASE))
    has_storage = bool(re.search(r'\d+\s*(?:TB|GB)\s*(?:SSD|Storage)', title, re.IGNORECASE))

    if not (has_chip or has_screen or has_ram or has_storage):
        return False

    return True


def is_likely_iphone(title: str, condition: Optional[str] = None) -> bool:
    """
    Check if a title is likely a real iPhone (not an accessory).

    WHAT: Filters out cases, screen protectors, chargers, etc. that
    mention a specific iPhone generation but aren't actual phones,
    plus locked/broken/parts-only listings.
    HOW: Rejects titles (and the marketplace's condition label, if
    given) containing accessory or bad-condition keywords, then
    requires at least one storage-capacity mention (e.g. "256GB",
    "1TB") as the hardware-indicator check — mirrors
    is_likely_macbook_pro()'s "must have at least one real spec"
    requirement.
    WHY: Unlike MacBook listings, iPhone accessory titles routinely
    contain the exact generation name (e.g. "Case for iPhone 15 Pro
    Max") because that's the product they're compatible with — a
    plain keyword match can't tell an accessory from a real phone.
    Real phone listings almost always state storage; accessories
    almost never do, so that's the more reliable signal here.
    The `condition` check matters because red-flag signals sometimes
    show up ONLY in the marketplace's condition badge, not the title
    — a live eBay result had title "Apple iPhone 15 Pro Max - 1 TB -
    Blue Titanium (Unlocked)" (nothing suspicious) but condition
    "Parts Only", which a title-only check would have missed.

    Args:
        title: The listing title to check.
        condition: The marketplace's condition label, if available.
    """
    title_lower = title.lower()
    condition_lower = (condition or "").lower()
    if "iphone" not in title_lower:
        return False

    for kw in IPHONE_ACCESSORY_KEYWORDS:
        if kw in title_lower or kw in condition_lower:
            return False

    locked = "locked" in title_lower and "unlocked" not in title_lower
    for kw in IPHONE_BAD_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower == "locked":
            continue
        if kw_lower in title_lower or kw_lower in condition_lower:
            return False
    if locked:
        return False

    has_storage = bool(re.search(r'\d+\s*(?:GB|TB)\b', title, re.IGNORECASE))
    if not has_storage:
        return False

    return True


def is_likely_ipad_pro(title: str, condition: Optional[str] = None) -> bool:
    """
    Check if a title is likely a real iPad Pro (not an accessory).

    WHAT: Filters out cases, keyboards, Apple Pencils, screen
    protectors, etc. that mention "iPad Pro" but aren't actual tablets.
    Also rejects locked/broken/parts-only listings.
    HOW: Rejects titles (and the marketplace's condition label, if
    given) containing accessory or bad-condition keywords, then
    requires at least one hardware spec: chip (M1-M5), screen size,
    RAM, or storage.
    WHY: iPad accessory titles often contain "iPad Pro" because that's
    the product they're compatible with, similar to iPhone accessories.
    Real iPad Pro listings almost always state at least one spec.

    Args:
        title: The listing title to check.
        condition: The marketplace's condition label, if available.
    """
    title_lower = title.lower()
    condition_lower = (condition or "").lower()

    # Must be an iPad Pro (not just iPad or iPad Air)
    if "ipad pro" not in title_lower:
        return False

    # Exclude accessories/red-flag condition by keyword
    for kw in IPAD_ACCESSORY_KEYWORDS:
        if kw in title_lower or kw in condition_lower:
            return False

    # Check for bad condition keywords
    locked = "locked" in title_lower and "unlocked" not in title_lower
    for kw in IPAD_BAD_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower == "locked":
            continue
        if kw_lower in title_lower or kw_lower in condition_lower:
            return False
    if locked:
        return False

    # Must have at least one hardware indicator
    has_chip = bool(re.search(r'M\d{1,2}\s*(?:Pro|Max|Ultra)?', title, re.IGNORECASE))
    has_screen = bool(re.search(r'\d+(?:\.\d+)?[\s-]*inch', title, re.IGNORECASE))
    has_screen = has_screen or bool(re.search(r'\d+(?:\.\d+)?"', title))
    has_ram = bool(re.search(r'\d+\s*GB\s*(?:RAM|Memory|Unified)', title, re.IGNORECASE))
    has_storage = bool(re.search(r'\d+\s*(?:TB|GB)\s*(?:SSD|Storage)', title, re.IGNORECASE))

    if not (has_chip or has_screen or has_ram or has_storage):
        return False

    return True


class ElectronicsHandler(ProductTypeHandler):
    """Apple hardware (MacBook Pro / iPhone) — the reference ProductTypeHandler."""

    def parse_specs(self, title: str) -> dict:
        cpu_cores, gpu_cores = extract_core_counts(title)
        return {
            "ram_gb": extract_ram_gb(title),
            "storage_gb": extract_storage_gb(title),
            "screen_size": extract_screen_size(title),
            "chip": extract_chip(title),
            "cpu_cores": cpu_cores,
            "gpu_cores": gpu_cores,
        }

    def is_relevant(self, title: str, search, condition: Optional[str] = None) -> bool:
        product_lower = search.product_name.lower()
        if "macbook" in product_lower:
            return is_likely_macbook_pro(title, condition)
        elif "iphone" in product_lower:
            return is_likely_iphone(title, condition)
        elif "ipad" in product_lower:
            return is_likely_ipad_pro(title, condition)
        return True

    def passes_type_filters(self, listing, search) -> bool:
        s = search
        title_lower = listing.title.lower()

        # Check chip (only if a chip filter is configured).
        # If chip_options is set (via a generation_family), it's a
        # rolling window of the last N flagship generations — match
        # against any of them instead of a fixed primary/fallback pair.
        if s.chip_options:
            if not listing.chip:
                return False
            listing_chip_lower = listing.chip.lower()
            if not any(opt.lower() in listing_chip_lower for opt in s.chip_options):
                return False
        elif s.chip:
            if not listing.chip:
                return False
            chip_primary = s.chip.lower()
            chip_primary_ok = chip_primary in listing.chip.lower()
            chip_fallback_ok = False
            if s.chip_fallback:
                chip_fallback_ok = s.chip_fallback.lower() in listing.chip.lower()
            if not (chip_primary_ok or chip_fallback_ok):
                return False

        # Check model generation keywords (only if configured, e.g. for
        # iPhone where the generation number lives in the title, not a
        # separately parsed field like chip).
        if s.model_keywords:
            if not any(kw.lower() in title_lower for kw in s.model_keywords):
                return False

        # Check screen size (only if screen_sizes is configured)
        if s.screen_sizes and listing.screen_size:
            size_ok = any(
                abs(listing.screen_size - size) < 1.0
                for size in s.screen_sizes
            )
            if not size_ok:
                return False

        # Check RAM (only if a RAM filter is configured)
        if s.ram_gb_primary and listing.ram_gb:
            ram_ok = (
                listing.ram_gb == s.ram_gb_primary
                or (s.ram_gb_fallback and listing.ram_gb == s.ram_gb_fallback)
            )
            if not ram_ok:
                return False

        # Check storage minimum/maximum
        if s.storage_gb_min and listing.storage_gb:
            if listing.storage_gb < s.storage_gb_min:
                return False
        if s.storage_gb_max and listing.storage_gb:
            if listing.storage_gb > s.storage_gb_max:
                return False

        # Check cellular requirement (for iPad Pro WiFi + Cellular)
        if s.cellular:
            # Title must mention cellular, 5G, or LTE
            has_cellular = bool(re.search(r'cellular|5g|lte', title_lower))
            if not has_cellular:
                return False

        return True

    def score_bonuses(self, listing, search) -> float:
        s = search
        bonus = 0.0

        # RAM bonus (weight: medium)
        if listing.ram_gb == s.ram_gb_primary:
            bonus += 10  # e.g. 128GB = premium
        elif listing.ram_gb == s.ram_gb_fallback:
            bonus += 2   # e.g. 64GB = acceptable

        # Chip generation bonus (weight: medium) — only meaningful
        # when the search uses a generation_family window
        # (chip_generation_map is empty for manually-configured searches).
        if listing.chip and s.chip_generation_map:
            gen = s.chip_generation_map.get(listing.chip)
            if gen is not None:
                newest_gen = max(s.chip_generation_map.values())
                gens_back = newest_gen - gen
                bonus += max(8 - 3 * gens_back, 0)  # newest +8, next +5, oldest +2

        # Core count bonus (weight: low) — reward listings that state
        # the flagship CPU/GPU core-count bin for their chip
        # generation. Listings that just don't mention core counts in
        # the title (common) get no bonus and no penalty.
        if listing.chip and s.core_count_reference:
            gen_match = re.search(r'\d+', listing.chip)
            gen = int(gen_match.group()) if gen_match else None
            reference = s.core_count_reference.get(gen) if gen is not None else None
            if reference and listing.cpu_cores and listing.gpu_cores:
                if (listing.cpu_cores >= reference.get("cpu", 0)
                        and listing.gpu_cores >= reference.get("gpu", 0)):
                    bonus += 4

        # Screen size preference (weight: low) — earlier entries in
        # screen_sizes are preferred (e.g. [14, 16] means 14" is
        # preferred, 16" is an accepted fallback).
        if listing.screen_size and s.screen_sizes:
            for i, size in enumerate(s.screen_sizes):
                if abs(listing.screen_size - size) < 1.0:
                    bonus += max(3 - 2 * i, 0)  # 1st +3, 2nd +1, 3rd+ +0
                    break

        # Storage bonus (weight: lowest) — bigger is better, but this
        # matters least of all the specs.
        if listing.storage_gb:
            bonus += min(listing.storage_gb / 8192 * 3, 3)  # up to +3 at 8TB

        return bonus

    def min_price_usd(self, search) -> float:
        if "iphone" in search.product_name.lower():
            return MINIMUM_IPHONE_PRICE_USD
        elif "ipad" in search.product_name.lower():
            return 500  # iPad Pro minimum price
        return MINIMUM_PRICE_USD
