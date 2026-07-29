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
