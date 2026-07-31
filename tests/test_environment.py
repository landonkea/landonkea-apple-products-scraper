# ───────────────────────────────────────────────────────────────────
# Tests for the environment-awareness module (src/environment.py)
# ───────────────────────────────────────────────────────────────────
# These tests verify that:
#   1. ENVIRONMENT unset defaults to "production" (must not change,
#      since this is what GitHub Actions relies on today).
#   2. Valid values ("dev", "staging", "production") are accepted,
#      case-insensitively.
#   3. Invalid values raise a clear ValueError.
#   4. is_production() reflects the current environment correctly.
#
# HOW TO RUN:
#   pytest tests/test_environment.py -v
#   (from the project root directory)
# ───────────────────────────────────────────────────────────────────

import os
import sys

# Add src/ to the Python path so we can import the project's modules.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from environment import get_environment, is_production


def test_defaults_to_production_when_unset():
    """
    ENVIRONMENT must default to "production" when not set at all.

    This is the most important behavior in this module: GitHub
    Actions currently runs with no ENVIRONMENT var set, so this
    default must keep production behaving exactly as it does today.
    """
    os.environ.pop("ENVIRONMENT", None)
    try:
        assert get_environment() == "production"
        assert is_production() is True
    finally:
        os.environ.pop("ENVIRONMENT", None)


def test_accepts_dev():
    os.environ["ENVIRONMENT"] = "dev"
    try:
        assert get_environment() == "dev"
        assert is_production() is False
    finally:
        del os.environ["ENVIRONMENT"]


def test_accepts_staging():
    os.environ["ENVIRONMENT"] = "staging"
    try:
        assert get_environment() == "staging"
        assert is_production() is False
    finally:
        del os.environ["ENVIRONMENT"]


def test_accepts_production_explicitly():
    os.environ["ENVIRONMENT"] = "production"
    try:
        assert get_environment() == "production"
        assert is_production() is True
    finally:
        del os.environ["ENVIRONMENT"]


def test_is_case_insensitive():
    os.environ["ENVIRONMENT"] = "DEV"
    try:
        assert get_environment() == "dev"
    finally:
        del os.environ["ENVIRONMENT"]

    os.environ["ENVIRONMENT"] = "Production"
    try:
        assert get_environment() == "production"
    finally:
        del os.environ["ENVIRONMENT"]


def test_rejects_invalid_value():
    os.environ["ENVIRONMENT"] = "bogus"
    try:
        with pytest.raises(ValueError):
            get_environment()
    finally:
        del os.environ["ENVIRONMENT"]
