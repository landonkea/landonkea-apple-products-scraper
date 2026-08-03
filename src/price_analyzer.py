# ───────────────────────────────────────────────────────────────────
# Price analyzer — computes deal scores and picks top deals
# ───────────────────────────────────────────────────────────────────
# Every scraped listing gets a "deal score" from 0 (bad) to 100
# (amazing).  The score is based on:
#
#   1. How far below market average (biggest factor)
#   2. RAM amount (128GB scores higher than 64GB)
#   3. Condition (new/refurb scores higher than used)
#   4. How recently it was listed (fresh deals score higher)
#
# The top deals are ranked by score and included in alerts.
# ───────────────────────────────────────────────────────────────────

import statistics
from typing import Optional

from database import Listing
from config import Config
from product_types import PRODUCT_TYPES


# ── Suspicious-price safeguard ─────────────────────────────────────
# A listing priced way below the rest of its batch AND claiming to be
# new/sealed is more likely mislabeled, a scam, or a typo than a
# genuine steal -- e.g. a live test found a "New *Sealed* Apple
# iPhone 17 Pro Max 1TB Silver Unlocked" listed at $238 when a real
# new sealed 1TB iPhone 17 Pro Max costs $1,400+. Nothing caught that
# case before; it would have scored as the #1 top deal. We don't want
# to silently drop it (it might occasionally be real), so instead we
# flag it: cap its score low and prefix its title so a human glancing
# at the alert knows to verify carefully before buying.
#
# Threshold note: live-tested against real eBay results rather than
# picked in the abstract. A batch mixing generations/conditions (e.g.
# older used iPhone 15 Pro Max units alongside a "new" iPhone 17 Pro
# Max) has a median dragged down by the cheaper used units, so an
# aggressive "under 20% of median" cutoff (the initial guess) did NOT
# catch the real $238-in-a-$621-median case -- the next-cheapest
# genuine listing in that same batch was still ~80% of median, so
# 50% leaves a wide, safe margin between "real cheap deal" and
# "implausible for a claimed-new item" without needing a tighter cutoff.
#
# The actual thresholds now live in config.yaml's price: block
# (price.suspicious_price_ratio / price.suspicious_min_sample) so
# they're tunable without a code change, same as great_deal_usd /
# good_deal_usd. These module constants are just the documented
# defaults used if config.yaml doesn't set them (see config.py's
# load_config()).
SUSPICIOUS_PRICE_RATIO = 0.5   # under 50% of the batch median price
SUSPICIOUS_MIN_SAMPLE = 3      # need at least this many listings for
                                # "median" to be a meaningful reference
SUSPICIOUS_CONDITION_KEYWORDS = ["new", "sealed", "brand new", "factory sealed"]
SUSPICIOUS_TAG = "⚠️ VERIFY PRICE — "


def is_meaningful_price_drop(old_price: Optional[float], new_price: float,
                              config: Config) -> bool:
    """
    Decide whether a listing's price change from `old_price` to
    `new_price` is a meaningful "price drop" worth alerting on.

    WHAT: Powers the price-drop alert (separate from the "great/good
    deal" thresholds above, which only ever look at a listing the
    first time it's seen). This is called on every re-scrape of an
    ALREADY-KNOWN listing, comparing its previously recorded price
    against the freshly scraped one.

    THRESHOLD DESIGN (config.price_drop, see config.yaml): requires
    BOTH min_drop_percent AND min_drop_usd to be cleared, same
    "require multiple signals" style as SUSPICIOUS_PRICE_RATIO above.
    A percent-only rule fires on trivial drops for cheap items (5% of
    a $60 listing is $3 -- noise); a dollar-only rule fires on
    trivial drops for expensive items ($50 off an $8,000 listing is
    0.6% -- also noise). Requiring both keeps the alert meaningful
    across the full price range these scrapers see.

    Args:
        old_price: The price this same listing (same source +
            listing_id) was last recorded at, or None if this is the
            first time we've ever seen it -- there's no prior price
            to compare against, so it can never be a "drop".
        new_price: The freshly scraped price.
        config: The global Config object (reads config.price_drop).

    Returns:
        True if this qualifies as a meaningful price drop worth
        alerting on, False otherwise (including: no prior price,
        price stayed the same or went up, or the drop didn't clear
        both thresholds).
    """
    drop_cfg = config.price_drop
    if not drop_cfg.enabled:
        return False

    # First time we've ever seen this listing -- nothing to compare
    # against, so this can never be a "drop".
    if old_price is None:
        return False

    if old_price <= 0 or new_price >= old_price:
        return False

    drop_usd = old_price - new_price
    drop_percent = (drop_usd / old_price) * 100

    return drop_usd >= drop_cfg.min_drop_usd and drop_percent >= drop_cfg.min_drop_percent


class PriceAnalyzer:
    """
    Analyzes listing prices and computes deal scores.
    
    Usage:
        analyzer = PriceAnalyzer(config)
        analyzer.add_listings(all_scraped_listings)
        top_deals = analyzer.get_top_deals(15)
    """
    
    def __init__(self, config: Config):
        """
        Initialize with config for price thresholds.
        
        Args:
            config: The global Config object.
        """
        self.config = config
        
        # Store all listings we've collected
        self.listings: list[Listing] = []
        
        # Cache computed stats (recalculated after each batch)
        self._stats: Optional[dict] = None
    
    def add_listings(self, listings: list[Listing]):
        """
        Add a batch of listings for analysis.
        
        Args:
            listings: List of Listing ORM objects from the database.
        """
        self.listings.extend(listings)
        # Invalidate cached stats so they get recalculated
        self._stats = None
    
    def _compute_stats(self) -> dict:
        """
        Compute price statistics across all current listings.
        
        Calculates:
          - mean (average) price
          - median (middle) price
          - mode (most common) price
          - standard deviation (how spread out prices are)
          - min/max prices
          - quartile boundaries (25th, 50th, 75th percentiles)
        
        Returns:
            A dict of statistics.
        """
        if not self.listings:
            return {
                "count": 0,
                "mean": 0,
                "median": 0,
                "min": 0,
                "max": 0,
                "std_dev": 0,
                "q25": 0,
                "q75": 0,
            }
        
        prices = [l.price_usd for l in self.listings]
        prices_sorted = sorted(prices)
        n = len(prices_sorted)
        
        mean_val = statistics.mean(prices)
        median_val = statistics.median(prices)
        
        # Quartiles
        q25 = prices_sorted[n // 4] if n >= 4 else prices_sorted[0]
        q75 = prices_sorted[3 * n // 4] if n >= 4 else prices_sorted[-1]
        
        # Standard deviation (population)
        try:
            std_dev = statistics.stdev(prices) if n > 1 else 0
        except statistics.StatisticsError:
            std_dev = 0
        
        self._stats = {
            "count": n,
            "mean": round(mean_val, 2),
            "median": round(median_val, 2),
            "min": min(prices),
            "max": max(prices),
            "std_dev": round(std_dev, 2),
            "q25": q25,
            "q75": q75,
        }
        
        return self._stats

    def _is_suspiciously_cheap(self, listing: Listing, stats: dict) -> bool:
        """
        Flag listings priced implausibly low for their claimed
        new/sealed condition, relative to the rest of the batch.

        Requires BOTH:
          - price is under SUSPICIOUS_PRICE_RATIO of the batch median
            (with at least SUSPICIOUS_MIN_SAMPLE listings, so a tiny
            batch doesn't produce a meaningless "median")
          - the title/condition claims new/sealed condition

        A genuinely cheap listing that's simply used, cosmetically
        damaged, or an older condition grade does NOT get flagged --
        only the "too good to be true for a claimed-new item"
        combination does, so real bargains aren't buried.
        """
        min_sample = getattr(self.config.price, "suspicious_min_sample", SUSPICIOUS_MIN_SAMPLE)
        price_ratio = getattr(self.config.price, "suspicious_price_ratio", SUSPICIOUS_PRICE_RATIO)

        median = stats.get("median", 0)
        if median <= 0 or stats.get("count", 0) < min_sample:
            return False
        if listing.price_usd >= median * price_ratio:
            return False

        text = f"{listing.condition or ''} {listing.title or ''}".lower()
        return any(kw in text for kw in SUSPICIOUS_CONDITION_KEYWORDS)

    def _score_listing(self, listing: Listing) -> float:
        """
        Compute a deal score for one listing (0-100).
        
        Scoring formula:
          - Base score starts at 50.
          - Price below median: +30 points max (scaled by how far).
          - Has 128GB RAM: +10 points.
          - Condition is New/Refurbished: +5 points.
          - Price above median: -20 points max.
          - Price over absolute_max: score = 0.
        
        Args:
            listing: A Listing with price_usd and ram_gb.
        
        Returns:
            A score from 0 to 100.
        """
        stats = self._compute_stats()
        
        # If we have no data, use config thresholds as baseline
        if stats["count"] == 0:
            # Score based purely on great_deal/good_deal thresholds
            ram = listing.ram_gb or 64
            great = self.config.price.great_deal_usd.get(ram, 5000)
            good = self.config.price.good_deal_usd.get(ram, 5500)
            
            if listing.price_usd <= great:
                return 90.0  # Great deal
            elif listing.price_usd <= good:
                return 70.0  # Good deal
            else:
                return 40.0  # Average
        
        # ── Score calculation ──
        score = 50.0
        
        # Factor 1: Price vs median (weight: high)
        median = stats["median"]
        if median > 0:
            if listing.price_usd < median:
                # Below median: score increases
                ratio = (median - listing.price_usd) / median
                price_bonus = min(ratio * 100, 30)  # Cap at +30
                score += price_bonus
            else:
                # Above median: score decreases
                ratio = (listing.price_usd - median) / median
                price_penalty = min(ratio * 50, 20)  # Cap at -20
                score -= price_penalty
        
        # Factor 2: Condition bonus (weight: low) — universal across
        # product types (a "new"/"excellent" boot is as much of a
        # plus as a "new"/"excellent" laptop). Includes the "Good" /
        # "Fair" grading tiers used by Swappa/BackMarket/Gazelle-style
        # condition grading (Excellent/Good/Fair) alongside "Excellent"
        # above — "Good" previously fell through with no bonus at all
        # even though it's a real, better-than-baseline condition
        # grade; "Fair" is intentionally left with no bonus since it's
        # the bottom of that grading scale, equivalent to an ungraded
        # "Used" listing.
        if listing.condition:
            cond_lower = listing.condition.lower()
            if any(word in cond_lower for word in ["new", "certified", "refurbished"]):
                score += 5
            elif any(word in cond_lower for word in ["open", "excellent"]):
                score += 3
            elif "good" in cond_lower:
                score += 1

        # Factor 3: product-type-specific bonuses (weight: varies) —
        # for electronics this is RAM tier, chip generation, core
        # count, screen size preference, and storage size. See
        # src/product_types/electronics.py's score_bonuses(). A future
        # product type supplies its own via the same interface.
        s = self.config.search
        handler = PRODUCT_TYPES[s.product_type]
        score += handler.score_bonuses(listing, s)

        # Clamp to 0-100
        score = max(0, min(100, score))

        # Suspicious-price safeguard: an implausibly-low price for a
        # claimed new/sealed item is far more likely mislabeled/a scam
        # than a genuine steal -- don't let it rank as a top deal.
        if self._is_suspiciously_cheap(listing, stats):
            score = min(score, 10.0)

        return round(score, 1)
    
    def analyze(self, listings: Optional[list[Listing]] = None) -> list[Listing]:
        """
        Analyze listings and attach deal scores.
        
        This modifies the listings in-place by setting deal_score
        and is_great_deal on each one.
        
        Args:
            listings: Optional list of listings.  If None, uses
                      the internal list from add_listings().
        
        Returns:
            The same listings with scores attached, sorted by
            deal_score descending.
        """
        if listings is not None:
            self.add_listings(listings)
        
        stats = self._compute_stats()

        for listing in self.listings:
            listing.deal_score = self._score_listing(listing)

            # Check if it qualifies as a "great deal"
            ram = listing.ram_gb or 64
            threshold = self.config.price.great_deal_usd.get(ram, 5000)
            listing.is_great_deal = listing.price_usd <= threshold

            # Suspicious-price safeguard (see module docstring above):
            # never present these as a vetted "great deal", and tag
            # the title so it's visibly flagged in alerts even though
            # we still surface it rather than silently dropping it.
            if self._is_suspiciously_cheap(listing, stats):
                listing.is_great_deal = False
                if not listing.title.startswith(SUSPICIOUS_TAG):
                    listing.title = SUSPICIOUS_TAG + listing.title
        
        # Sort by score descending (best deals first)
        self.listings.sort(key=lambda l: l.deal_score or 0, reverse=True)
        
        return self.listings
    
    def get_top_deals(self, count: Optional[int] = None) -> list[Listing]:
        """
        Get the highest-scored deals.
        
        Args:
            count: How many to return.  Defaults to config value.
        
        Returns:
            The top N listings by deal score.
        """
        if count is None:
            count = self.config.price.top_deals_count
        
        return self.listings[:count]
    
    def get_stats(self) -> dict:
        """
        Get current price statistics (for the alert message).
        
        Returns:
            A dict of stats (mean, median, etc.).
        """
        return self._compute_stats()
