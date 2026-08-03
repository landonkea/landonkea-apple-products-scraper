# ───────────────────────────────────────────────────────────────────
# Tests for the price analyzer's suspicious-price safeguard
# ───────────────────────────────────────────────────────────────────
# A listing priced way below the rest of its batch AND claiming to be
# new/sealed (e.g. a "New *Sealed* iPhone 17 Pro Max 1TB" at $238 when
# everything else in the batch is $1,400+) is more likely mislabeled
# or a scam than a genuine steal. These tests make sure that case gets
# flagged instead of silently ranking as the #1 top deal.

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import SearchConfig, PriceConfig
from database import Listing
from price_analyzer import PriceAnalyzer, SUSPICIOUS_TAG


class FakeConfig:
    """Minimal stand-in for Config — PriceAnalyzer only touches
    .search and .price, so a full Config (with YAML/env loading) is
    unnecessary for these tests."""

    def __init__(self, search: SearchConfig, price: PriceConfig):
        self.search = search
        self.price = price


def _make_search_config(**overrides) -> SearchConfig:
    defaults = dict(
        product_name="iPhone Pro Max",
        chip=None,
        chip_fallback=None,
        screen_sizes=[],
        ram_gb_primary=None,
        ram_gb_fallback=None,
        storage_gb_min=1000,
        storage_gb_max=None,
        results_per_size=20,
        location=None,
    )
    defaults.update(overrides)
    return SearchConfig(**defaults)


def _make_price_config(**overrides) -> PriceConfig:
    defaults = dict(
        absolute_max_usd=5000,
        great_deal_usd={64: 900},
        good_deal_usd={64: 1100},
        top_deals_count=15,
    )
    defaults.update(overrides)
    return PriceConfig(**defaults)


def _make_analyzer() -> PriceAnalyzer:
    config = FakeConfig(_make_search_config(), _make_price_config())
    return PriceAnalyzer(config)


def _make_listing(title, price_usd, condition=None) -> Listing:
    return Listing(
        source="ebay",
        listing_id=f"id_{price_usd}_{title[:10]}",
        title=title,
        price_usd=price_usd,
        url="https://ebay.com/itm/123",
        condition=condition,
    )


def test_implausibly_cheap_new_sealed_listing_is_flagged():
    """The exact scenario found during live testing: a $238 'New
    *Sealed* iPhone 17 Pro Max 1TB' amid a batch priced $1,400+ must
    NOT come out as the #1 top deal."""
    analyzer = _make_analyzer()

    listings = [
        _make_listing("New *Sealed* Apple iPhone 17 Pro Max 1TB Silver Unlocked", 238.0, "New"),
        _make_listing("Apple iPhone 17 Pro Max 1TB Unlocked", 1450.0, "New"),
        _make_listing("Apple iPhone 17 Pro Max 1TB Unlocked", 1499.0, "Used"),
        _make_listing("Apple iPhone 17 Pro Max 1TB Unlocked", 1550.0, "New"),
    ]

    analyzed = analyzer.analyze(listings)
    top = analyzed[0]

    # The suspicious $238 listing must not be ranked #1.
    assert top.price_usd != 238.0

    suspicious = next(l for l in analyzed if l.price_usd == 238.0)
    assert suspicious.deal_score <= 10.0
    assert suspicious.is_great_deal is False
    assert suspicious.title.startswith(SUSPICIOUS_TAG)


def test_legitimately_cheap_used_listing_is_not_flagged():
    """A genuinely low-priced listing that is NOT claiming new/sealed
    condition (e.g. a legitimately cheap, cosmetically-damaged used
    phone) should not be penalized by the safeguard — only the
    new/sealed + implausible-price combination should be."""
    analyzer = _make_analyzer()

    listings = [
        _make_listing("Apple iPhone 17 Pro Max 1TB Unlocked - Cracked Back, Used", 260.0, "Used - Fair"),
        _make_listing("Apple iPhone 17 Pro Max 1TB Unlocked", 1450.0, "New"),
        _make_listing("Apple iPhone 17 Pro Max 1TB Unlocked", 1499.0, "Used"),
        _make_listing("Apple iPhone 17 Pro Max 1TB Unlocked", 1550.0, "New"),
    ]

    analyzed = analyzer.analyze(listings)
    cheap = next(l for l in analyzed if l.price_usd == 260.0)

    # Not flagged: no "new"/"sealed" claim, so it's treated as a
    # legitimate (if unfortunate) cheap listing, not a scam signal.
    assert not cheap.title.startswith(SUSPICIOUS_TAG)
    assert cheap.deal_score > 10.0


def test_suspicious_ratio_is_config_driven():
    """The suspicious-price cutoff (price.suspicious_price_ratio) must
    actually be read from config, not just fall back to the module
    default -- a tighter ratio should stop flagging a listing that
    the default 0.5 ratio would have caught."""
    # 238 / 1450 (median) ≈ 0.164 -- well under the default 0.5 ratio
    # (flagged), but ABOVE a much tighter custom ratio of 0.1 (not
    # flagged), proving the analyzer actually reads config here.
    config = FakeConfig(
        _make_search_config(),
        _make_price_config(suspicious_price_ratio=0.1),
    )
    analyzer = PriceAnalyzer(config)

    listings = [
        _make_listing("New *Sealed* Apple iPhone 17 Pro Max 1TB Silver Unlocked", 238.0, "New"),
        _make_listing("Apple iPhone 17 Pro Max 1TB Unlocked", 1450.0, "New"),
        _make_listing("Apple iPhone 17 Pro Max 1TB Unlocked", 1499.0, "Used"),
        _make_listing("Apple iPhone 17 Pro Max 1TB Unlocked", 1550.0, "New"),
    ]

    analyzed = analyzer.analyze(listings)
    cheap = next(x for x in analyzed if x.price_usd == 238.0)

    assert not cheap.title.startswith(SUSPICIOUS_TAG)


def test_suspicious_min_sample_is_config_driven():
    """A custom suspicious_min_sample should raise the bar for how
    many listings are needed before the safeguard trusts the
    median -- a batch below that bar must not get flagged even if it
    would exceed the default of 3."""
    config = FakeConfig(
        _make_search_config(),
        _make_price_config(suspicious_min_sample=10),
    )
    analyzer = PriceAnalyzer(config)

    listings = [
        _make_listing("New *Sealed* Apple iPhone 17 Pro Max 1TB Silver Unlocked", 238.0, "New"),
        _make_listing("Apple iPhone 17 Pro Max 1TB Unlocked", 1450.0, "New"),
        _make_listing("Apple iPhone 17 Pro Max 1TB Unlocked", 1499.0, "Used"),
    ]

    analyzed = analyzer.analyze(listings)
    cheap = next(x for x in analyzed if x.price_usd == 238.0)

    # Only 3 listings, below the custom min_sample of 10 -- safeguard
    # must stay quiet even though the default (3) would have applied.
    assert not cheap.title.startswith(SUSPICIOUS_TAG)


def test_small_batch_does_not_trigger_safeguard():
    """With too few listings to trust a 'median', the safeguard
    should stay quiet rather than flag on noise."""
    analyzer = _make_analyzer()

    listings = [
        _make_listing("New *Sealed* Apple iPhone 17 Pro Max 1TB Silver Unlocked", 238.0, "New"),
        _make_listing("Apple iPhone 17 Pro Max 1TB Unlocked", 1450.0, "New"),
    ]

    analyzed = analyzer.analyze(listings)
    cheap = next(l for l in analyzed if l.price_usd == 238.0)

    assert not cheap.title.startswith(SUSPICIOUS_TAG)
