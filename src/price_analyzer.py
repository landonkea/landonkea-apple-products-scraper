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
        
        # Factor 2: RAM bonus (weight: medium)
        if listing.ram_gb == self.config.search.ram_gb_primary:
            score += 10  # 128GB = premium
        elif listing.ram_gb == self.config.search.ram_gb_fallback:
            score += 2   # 64GB = acceptable
        
        # Factor 3: Condition bonus (weight: low)
        if listing.condition:
            cond_lower = listing.condition.lower()
            if any(word in cond_lower for word in ["new", "certified", "refurbished"]):
                score += 5
            elif any(word in cond_lower for word in ["open", "excellent"]):
                score += 3
        
        # Clamp to 0-100
        score = max(0, min(100, score))
        
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
        
        for listing in self.listings:
            listing.deal_score = self._score_listing(listing)
            
            # Check if it qualifies as a "great deal"
            ram = listing.ram_gb or 64
            threshold = self.config.price.great_deal_usd.get(ram, 5000)
            listing.is_great_deal = listing.price_usd <= threshold
        
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
