# ───────────────────────────────────────────────────────────────────
# Tests for spec parsing helpers
# ───────────────────────────────────────────────────────────────────

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from scrapers.base import (
    extract_ram_gb,
    extract_storage_gb,
    extract_screen_size,
    extract_chip,
    is_likely_iphone,
)


def test_extract_ram():
    """Test RAM extraction from listing titles."""
    # Standard formats
    assert extract_ram_gb("MacBook Pro M5 Max 128GB Memory") == 128
    assert extract_ram_gb("MacBook Pro 14 M5 Max 64GB RAM") == 64
    assert extract_ram_gb("M5 Max 128 GB Unified Memory") == 128
    assert extract_ram_gb("M5 Max 36GB") == 36
    
    # No RAM mentioned
    assert extract_ram_gb("MacBook Pro M5 Max Laptop") is None
    
    # Storage vs RAM: 512 is storage, not RAM.
    # Our parser correctly rejects it as RAM (returns None).
    assert extract_ram_gb("MacBook Pro 512GB SSD") is None


def test_extract_storage():
    """Test storage extraction from listing titles."""
    # TB formats
    assert extract_storage_gb("MacBook Pro 2TB SSD") == 2048
    assert extract_storage_gb("MacBook Pro 4 TB Storage") == 4096
    assert extract_storage_gb("M5 Max 8TB") == 8192
    
    # GB formats
    assert extract_storage_gb("MacBook Pro 512GB SSD") == 512
    assert extract_storage_gb("MacBook Pro 1TB") == 1024
    
    # No storage
    assert extract_storage_gb("MacBook Pro M5 Max 128GB RAM") is None


def test_extract_screen_size():
    """Test screen size extraction."""
    assert extract_screen_size("14-inch MacBook Pro") == 14.0
    assert extract_screen_size("14 inch MacBook Pro") == 14.0
    assert extract_screen_size("MacBook Pro 14.2-inch Display") == 14.2
    
    # No screen size
    assert extract_screen_size("MacBook Pro M5 Max") is None


def test_extract_chip():
    """Test chip name extraction."""
    assert extract_chip("MacBook Pro M5 Max 128GB") == "M5 Max"
    assert extract_chip("MacBook Pro M4 Max 128GB") == "M4 Max"
    assert extract_chip("M5 Pro MacBook Pro") == "M5 Pro"
    assert extract_chip("M3 Ultra Mac Studio") == "M3 Ultra"
    
    # No chip
    assert extract_chip("MacBook Pro Laptop") is None


def test_all_parsers_together():
    """Test parsing a realistic listing title."""
    title = 'Apple MacBook Pro 14" M5 Max Chip 128GB Memory 2TB SSD - Space Black'
    
    assert extract_ram_gb(title) == 128
    assert extract_storage_gb(title) == 2048
    assert extract_screen_size(title) == 14.0
    assert extract_chip(title) == "M5 Max"


def test_is_likely_iphone_rejects_defective_and_faulty_listings():
    """A real live eBay result during testing was titled 'DEFECTIVE
    Apple iPhone 15 Pro Max 1TB Black - Unlocked' and passed every
    filter — 'defective' wasn't in IPHONE_BAD_KEYWORDS. Make sure
    obvious condition red-flag words are now rejected."""
    assert is_likely_iphone("DEFECTIVE Apple iPhone 15 Pro Max 1TB Black - Unlocked") is False
    assert is_likely_iphone("Apple iPhone 15 Pro Max 256GB - Faulty, sold as-is") is False
    assert is_likely_iphone("Apple iPhone 14 Pro Max 128GB - Screen Does Not Work") is False
    assert is_likely_iphone("Apple iPhone 14 Pro Max 128GB - Doesn't Work, for parts") is False


def test_is_likely_iphone_accepts_genuine_listing():
    """Sanity check: a normal, healthy listing still passes."""
    assert is_likely_iphone("Apple iPhone 15 Pro Max 256GB Unlocked - Excellent Condition") is True


def test_is_likely_iphone_checks_condition_field_too():
    """Live eBay data found a listing whose TITLE looked completely
    clean ('Apple iPhone 15 Pro Max - 1 TB - Blue Titanium
    (Unlocked)') but whose separate marketplace condition badge said
    'Parts Only' — a title-only keyword check missed it. condition
    must be checked too."""
    title = "Apple iPhone 15 Pro Max - 1 TB - Blue Titanium (Unlocked)"
    assert is_likely_iphone(title) is True  # title alone looks fine
    assert is_likely_iphone(title, condition="Parts Only") is False
    assert is_likely_iphone(title, condition="For parts or not working") is False
