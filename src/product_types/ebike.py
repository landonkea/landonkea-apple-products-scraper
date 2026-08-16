# ───────────────────────────────────────────────────────────────────
# E-bike product type, folding step-through commuter e-bikes
# ───────────────────────────────────────────────────────────────────
# WHAT: A third ProductTypeHandler (after electronics.py and the
# apparel.py proof-of-concept), the first one that's a genuinely new
# category AND live in production config.yaml at the same time. It
# targets one specific bike: a used folding, step-through, fat-tire
# e-bike suitable as a daily 15-mile-each-way commute vehicle for a
# 5'2", ~290lb rider, researched and specified directly by this
# repo's owner (see PR/commit description for the full rider brief).
#
# WHY A GRADUATED-BONUS DESIGN INSTEAD OF HARD FILTERS: nearly every
# spec here (step-through, folding, wheel size, battery capacity,
# motor wattage, brakes, suspension, UL certification) comes from
# free-text title parsing, the same reliability tier as boots'
# size/brand/color, not a structured API field. A hard filter on an
# imperfectly-parsed field produces false-negative rejections (a
# genuinely great bike whose title just doesn't happen to say
# "folding"). So, aside from the two things worth hard-rejecting on
# (see HARD FILTERS below), every spec here is a scoring bonus,
# weighted by how much it matters for THIS rider (see the priority
# order in score_bonuses()'s docstring), not a pass/fail gate. This
# mirrors how electronics.py treats chip/RAM as bonuses once a listing
# already cleared is_relevant(), not the other way around.
#
# HARD FILTERS (passes_type_filters): weight_capacity_lb, ONLY when a
# listing's title actually states one, rejected below 330lb (below
# that is not safe for a 290lb rider, per the rider brief's explicit
# "generally reject below 330lb" cutoff). A listing that simply
# doesn't mention capacity in its title is NOT rejected, there's no
# way to verify it from title text alone, so absence of the field is
# treated as "unknown", not "fails". The other hard filter, a $300
# price floor, lives in min_price_usd() and rejects obvious accessory
# listings (a battery alone, a charger alone) the same way
# electronics.py's MINIMUM_PRICE_USD does for computer accessories.
#
# STEP-THROUGH CAVEAT (read before trusting this field): the rider
# brief is explicit that a low-frame marketing claim is NOT the same
# thing as a verified true step-through geometry, and that verifying
# the real thing requires looking at manufacturer photos/spec sheets,
# something no title-parsing pipeline can do. `step_through` here is
# ONLY a title-keyword signal ("step thru", "step-through", "stepthru"
# , "low step"), never a geometry confirmation. notifier.py's ebike
# alert path is expected to append a "(verify frame geometry before
# buying)" note whenever this bonus applied, so the alert itself never
# overstates certainty the parsing can't back up.
#
# NOMINAL VS. PEAK MOTOR WATTAGE: a listing that says "1200W" with no
# other qualifier is genuinely ambiguous, sellers routinely quote
# either figure alone. extract_motor_watts() below only ever assigns a
# bare number to motor_watts_peak when the title itself uses the word
# "peak" (or "max") next to it, and to motor_watts_nominal when the
# title says "nominal"/"continuous", or when it's the ONLY wattage
# figure in the title (the common case, and the one the rider brief
# explicitly warns not to silently reclassify as peak). When a title
# states both ("750W nominal / 1200W peak"), both fields are set
# correctly instead of collapsing to one number.
# ───────────────────────────────────────────────────────────────────

import re
from typing import Optional

from product_types.base import ProductTypeHandler


# ── Spec-parsing helpers ───────────────────────────────────────────

# Reputable e-bike brands worth a small reliability bonus, per the
# rider brief. NOT an exclusion list, an unlisted brand is still fully
# eligible, it just scores no brand bonus, same convention as
# apparel.py's KNOWN_BRANDS / preferred_brands split.
KNOWN_BRANDS = [
    "Lectric", "Tern", "Brompton", "Rad Power", "RadPower", "Aventon",
    "Ride1Up", "Ride 1Up", "Blix", "Velotric", "REI Co-op", "Specialized",
    "Trek", "Electra", "Cannondale", "ENGWE", "Himiway", "Heybike",
    "AIPAS", "ET.Cycle", "ET Cycle", "Vtuvia", "Mokwheel", "Fiido",
    "Eunorau", "Juiced", "Magnum", "Pedego", "Addmotor", "Surface 604",
]


def extract_brand(title: str) -> Optional[str]:
    """Find a known e-bike brand in a listing title (case-insensitive)."""
    title_lower = title.lower()
    for brand in KNOWN_BRANDS:
        if brand.lower() in title_lower:
            return brand
    return None


def extract_wheel_size_in(title: str) -> Optional[float]:
    """
    Find a wheel size in inches, e.g. "20 inch", "20-inch", '20"',
    "20x4" (fat-tire notation, the leading number is wheel diameter).

    Only returns 16/20/24 (the rider brief's target sizes), any other
    plausible-looking number (e.g. a 26" or 700C road wheel, or a
    stray unrelated "20" elsewhere in the title) is deliberately not
    returned, this field feeds a bonus for the three specific sizes
    that fit a 5'2" rider well, not a general wheel-size extractor.
    """
    patterns = [
        r'\b(16|20|24)\s*(?:x\s*\d(?:\.\d)?)?[\s-]*(?:inch|in\b|")',
        r'\b(16|20|24)x\d',
    ]
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def extract_fat_tire(title: str) -> bool:
    """
    Detect a fat-tire mention: "fat tire", "fat-tire", or a wheel
    notation like "20x4" / "20 x 4.0" where the tire-width figure is
    in the ~3-4in fat-tire range.
    """
    title_lower = title.lower()
    if "fat tire" in title_lower or "fat-tire" in title_lower or "fattire" in title_lower:
        return True
    match = re.search(r'\b\d{2}\s*x\s*(\d(?:\.\d)?)\b', title_lower)
    if match:
        width = float(match.group(1))
        if 3.0 <= width <= 4.5:
            return True
    return False


# Title-keyword signal only, see module docstring's STEP-THROUGH
# CAVEAT, never a verified frame-geometry confirmation.
STEP_THROUGH_KEYWORDS = [
    "step thru", "step-thru", "step through", "step-through",
    "stepthru", "stepthrough", "low step",
]


def extract_step_through(title: str) -> bool:
    """Title-keyword signal for a step-through frame claim (see module docstring)."""
    title_lower = title.lower()
    return any(kw in title_lower for kw in STEP_THROUGH_KEYWORDS)


def extract_folding(title: str) -> bool:
    """Title-keyword signal for a folding frame."""
    title_lower = title.lower()
    return any(kw in title_lower for kw in ("folding", "fold up", "fold-up", "foldable", "fold"))


def extract_battery_voltage_ah(title: str) -> tuple[Optional[int], Optional[float]]:
    """
    Find battery voltage and amp-hours, e.g. "48V 20Ah", "48V 15.5Ah",
    "36V/10.4Ah". Returns (voltage, ah), either may be None.
    """
    voltage = None
    ah = None
    v_match = re.search(r'\b(\d{2,3})\s*V\b', title, re.IGNORECASE)
    if v_match:
        val = int(v_match.group(1))
        if 24 <= val <= 72:  # plausible e-bike battery voltage range
            voltage = val
    ah_match = re.search(r'\b(\d{1,2}(?:\.\d)?)\s*Ah\b', title, re.IGNORECASE)
    if ah_match:
        ah_val = float(ah_match.group(1))
        if 3 <= ah_val <= 40:  # plausible e-bike battery capacity range
            ah = ah_val
    return voltage, ah


def extract_motor_watts(title: str) -> tuple[Optional[int], Optional[int]]:
    """
    Find nominal and peak motor wattage, distinguishing the two per
    the module docstring's NOMINAL VS. PEAK section, never silently
    treating an unqualified figure as peak.

    Returns:
        (motor_watts_nominal, motor_watts_peak), either may be None.
    """
    nominal = None
    peak = None

    peak_match = re.search(r'(\d{3,4})\s*W\w*\s*(?:peak|max)', title, re.IGNORECASE)
    if peak_match:
        peak = int(peak_match.group(1))

    nominal_match = re.search(
        r'(\d{3,4})\s*W\w*\s*(?:nominal|continuous|rated)', title, re.IGNORECASE
    )
    if nominal_match:
        nominal = int(nominal_match.group(1))

    if nominal is None:
        # No explicit "nominal"/"continuous" qualifier -- fall back to
        # any bare "NNNW" figure NOT already claimed by the peak match
        # above and not immediately followed by "peak"/"max" (that
        # combination is peak, handled above). This is the common case
        # (a listing states one wattage figure with no qualifier at
        # all) -- treated as nominal, per the rider brief's explicit
        # instruction not to record an unqualified figure as peak.
        for match in re.finditer(r'(\d{3,4})\s*W\b(?!att)', title, re.IGNORECASE):
            val = int(match.group(1))
            tail = title[match.end():match.end() + 12].lower()
            if "peak" in tail or "max" in tail:
                continue
            if peak is not None and val == peak:
                continue
            if 200 <= val <= 3000:  # plausible e-bike motor wattage
                nominal = val
                break

    return nominal, peak


BRAKE_KEYWORDS = [
    ("hydraulic", "hydraulic"),
    ("mechanical disc", "mechanical"),
    ("disc brake", "mechanical"),  # disc brake with no qualifier -- assume mechanical, the more common/cheaper spec
    ("rim brake", "rim"),
]


def extract_brake_type(title: str) -> Optional[str]:
    """Find brake type: "hydraulic", "mechanical", "rim", or None."""
    title_lower = title.lower()
    if "hydraulic" in title_lower:
        return "hydraulic"
    if "mechanical disc" in title_lower or "disc brake" in title_lower or "disc brakes" in title_lower:
        return "mechanical"
    if "rim brake" in title_lower:
        return "rim"
    return None


def extract_suspension(title: str) -> bool:
    """Detect a front-suspension mention."""
    title_lower = title.lower()
    return "suspension" in title_lower or "suspension fork" in title_lower


def extract_ul_certified(title: str) -> bool:
    """Detect a UL 2849 (e-bike) or UL 2271 (battery) certification claim."""
    title_lower = title.lower()
    return bool(re.search(r'ul\s*-?\s*2849|ul\s*-?\s*2271|ul\s+certified|ul-certified', title_lower))


def extract_weight_capacity_lb(title: str) -> Optional[int]:
    """
    Find a stated weight/load capacity in lb, e.g. "400lb capacity",
    "350 lb weight limit", "400lbs load capacity". Distinct from a
    bike's own shipping/curb weight (also often in lb), which is why
    this requires a capacity/limit/load keyword nearby, not just a
    bare "NNNlb".
    """
    match = re.search(
        r'(\d{3})\s*(?:lb|lbs)\.?\s*(?:capacity|weight\s*limit|load\s*capacity|max\s*(?:weight|load))',
        title, re.IGNORECASE,
    )
    if match:
        return int(match.group(1))
    match = re.search(
        r'(?:capacity|weight\s*limit|load\s*capacity|max\s*(?:weight|load))\s*(?:of\s*)?(\d{3})\s*(?:lb|lbs)\.?',
        title, re.IGNORECASE,
    )
    if match:
        return int(match.group(1))
    return None


# Listings that mention an e-bike brand/model but aren't a complete,
# rideable bike -- mirrors electronics.py's ACCESSORY_KEYWORDS.
ACCESSORY_KEYWORDS = [
    "battery only", "charger only", "frame only", "shell only",
    "for parts", "parts bike", "no battery", "no motor", "motor only",
    "display only", "controller only", "case only",
]

# Condition red flags -- a bike in this state isn't safely rideable
# and isn't a real commute-ready candidate regardless of price.
BAD_CONDITION_KEYWORDS = [
    "as-is", "as is", "for parts", "does not hold charge",
    "dead battery", "won't turn on", "wont turn on", "non-functional",
    "doesn't charge", "does not charge", "not charging",
]

# A real complete e-bike essentially never lists under this; cheaper
# listings are almost certainly an accessory/part that slipped past
# the keyword filter (mirrors electronics.py's MINIMUM_PRICE_USD).
MINIMUM_PRICE_USD = 300

# Below this, weight_capacity_lb (when the title actually states one)
# is rejected outright -- see module docstring's HARD FILTERS section
# and the rider brief's explicit "generally reject below 330lb".
MIN_ACCEPTABLE_WEIGHT_CAPACITY_LB = 330


class EbikeHandler(ProductTypeHandler):
    """
    Folding step-through commuter e-bikes -- see this module's
    docstring for the full rationale (hard filters vs. bonuses,
    step-through caveat, nominal/peak motor wattage).
    """

    def parse_specs(self, title: str) -> dict:
        motor_nominal, motor_peak = extract_motor_watts(title)
        voltage, ah = extract_battery_voltage_ah(title)
        battery_wh = round(voltage * ah, 1) if (voltage and ah) else None
        return {
            # Electronics-shaped keys, always None for an e-bike
            # listing. Present (not omitted) so every general-
            # marketplace scraper's existing `specs["ram_gb"]`-style
            # bracket access (written for electronics.py's dict shape)
            # doesn't raise KeyError when the active search is
            # product_type: ebike -- see scrapers/ebay.py, craigslist.py,
            # mercari.py, offerup.py's _parse_single_item()/_parse_card()
            # /_parse_listing() methods, none of which needed to change
            # their electronics-field access because of this.
            "ram_gb": None,
            "storage_gb": None,
            "screen_size": None,
            "chip": None,
            "cpu_cores": None,
            "gpu_cores": None,
            # E-bike-specific fields.
            "brand": extract_brand(title),
            "wheel_size_in": extract_wheel_size_in(title),
            "fat_tire": extract_fat_tire(title),
            "step_through": extract_step_through(title),
            "folding": extract_folding(title),
            "battery_voltage": voltage,
            "battery_ah": ah,
            "battery_wh": battery_wh,
            "motor_watts_nominal": motor_nominal,
            "motor_watts_peak": motor_peak,
            "weight_capacity_lb": extract_weight_capacity_lb(title),
            "brake_type": extract_brake_type(title),
            "suspension": extract_suspension(title),
            "ul_certified": extract_ul_certified(title),
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
        # Only hard filter: weight capacity, and only when the title
        # actually states one (see module docstring's HARD FILTERS).
        if listing.weight_capacity_lb is not None:
            if listing.weight_capacity_lb < MIN_ACCEPTABLE_WEIGHT_CAPACITY_LB:
                return False
        return True

    def score_bonuses(self, listing, search) -> float:
        """
        Weighted per the rider brief's stated priority order: safety
        > weight capacity > step-through > battery > commute
        suitability > rider fit (5'2") > folding/storage > brand
        reliability > parts availability > price. Price itself is
        scored separately (PriceAnalyzer's price-vs-median factor),
        not here.
        """
        bonus = 0.0

        # ── Safety: UL certification (weight: highest) ─────────────
        if listing.ul_certified:
            bonus += 12

        # ── Weight capacity (weight: very high) ─────────────────────
        cap = listing.weight_capacity_lb
        if cap is not None:
            if cap >= 400:
                bonus += 15
            elif cap >= 350:
                bonus += 10
            elif cap >= MIN_ACCEPTABLE_WEIGHT_CAPACITY_LB:
                bonus += 3  # 330-349lb: usable, but flagged as use-caution in the rider brief

        # ── Step-through frame (weight: high, but see module
        # docstring's caveat, this is a title-keyword signal only) ──
        if listing.step_through:
            bonus += 10

        # ── Battery: capacity tier + voltage + removability language
        # (weight: high, commute-viability-critical) ────────────────
        ah = listing.battery_ah
        if ah is not None:
            if ah >= 20:
                bonus += 10
            elif ah >= 15:
                bonus += 7
            elif ah >= 13:
                bonus += 4
            elif ah >= 10:
                bonus += 1
            # under 10Ah: no bonus -- not realistically viable for a
            # 15-mile commute at this rider's weight, per the rider
            # brief ("13Ah+ may be considered... under that, no").
        if listing.battery_voltage == 48:
            bonus += 4
        elif listing.battery_voltage and listing.battery_voltage >= 36:
            bonus += 1
        title_lower = (listing.title or "").lower()
        if "removable battery" in title_lower or "removable" in title_lower:
            bonus += 3

        # ── Motor: nominal wattage near 750W preferred, peak 1200W+
        # a plus (weight: medium-high) ───────────────────────────────
        nominal = listing.motor_watts_nominal
        if nominal is not None:
            if 700 <= nominal <= 850:
                bonus += 6
            elif 500 <= nominal <= 1000:
                bonus += 3
        if listing.motor_watts_peak and listing.motor_watts_peak >= 1200:
            bonus += 3

        # ── Rider fit: wheel size 16/20/24in, fat tire (weight:
        # medium, "5'2\" rider fit" + "mostly flat + hills" in the
        # priority order) ─────────────────────────────────────────
        if listing.wheel_size_in in (16.0, 20.0, 24.0):
            bonus += 5
        if listing.fat_tire:
            bonus += 3

        # ── Brakes / suspension (weight: medium, safety-adjacent) ──
        if listing.brake_type == "hydraulic":
            bonus += 5
        elif listing.brake_type == "mechanical":
            bonus += 2
        elif listing.brake_type == "rim":
            bonus -= 3  # explicitly not preferred per the rider brief
        if listing.suspension:
            bonus += 3

        # ── Folding / storage practicality (weight: medium) ────────
        if listing.folding:
            bonus += 6

        # ── Brand reliability (weight: low-medium) ──────────────────
        # Reuses the generic preferred_brands field (also used by
        # apparel.py) rather than a duplicate ebike-only field --
        # config.yaml's ebike search entry sets preferred_brands to
        # the same reputable-brand list this module's KNOWN_BRANDS
        # already restricts extract_brand() to, so in practice any
        # listing.brand that got parsed at all is on this list, but
        # the check is still against search.preferred_brands (not a
        # bare "brand is set" check) so a differently-configured
        # search's brand list is honored instead of ignored.
        if listing.brand and search.preferred_brands:
            if listing.brand.lower() in [b.lower() for b in search.preferred_brands]:
                bonus += 4

        return bonus

    def min_price_usd(self, search) -> float:
        return MINIMUM_PRICE_USD
