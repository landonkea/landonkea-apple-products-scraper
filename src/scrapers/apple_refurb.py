# ───────────────────────────────────────────────────────────────────
# Apple Certified Refurbished scraper
# ───────────────────────────────────────────────────────────────────
# Apple's refurb page embeds all product data in a JavaScript
# variable called `window.REFURB_GRID_BOOTSTRAP`.  We extract
# that JSON blob and parse it directly — no HTML card scraping.
# ───────────────────────────────────────────────────────────────────

import json
import re
from typing import Optional

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class AppleRefurbScraper(BaseScraper):
    """
    Scrapes Apple's Certified Refurbished MacBook Pro listings.
    
    Apple ships product data as a JSON blob inside a <script> tag
    rather than rendering it in HTML.  We grab the JS variable
    `window.REFURB_GRID_BOOTSTRAP` and parse the tiles array.
    """
    
    def __init__(self, config: Config):
        """Initialize the Apple Refurb scraper."""
        super().__init__(config)
        self.source_name = "apple_refurb"
    
    def scrape(self) -> list[ScrapedListing]:
        """
        Scrape Apple's refurbished store for matching products.
        
        Fetches both the 14-inch and 16-inch MacBook Pro refurb
        pages, or iPad Pro pages, or iPhone pages, extracts the JSON
        bootstrap, and filters for actual matching listings.
        
        Returns:
            A list of ScrapedListing objects.
        """
        found: list[ScrapedListing] = []
        
        product = self.config.search.product_name
        
        if "macbook" in product.lower():
            # MacBook Pro has specific size-based pages
            urls = [
                "https://www.apple.com/shop/refurbished/mac/14-inch-macbook-pro",
                "https://www.apple.com/shop/refurbished/mac/16-inch-macbook-pro",
            ]
        elif "iphone" in product.lower():
            # Apple's refurb store has no per-model iPhone page
            # (e.g. "iphone-17-pro-max" 404s) — only the category
            # root works. passes_filters()'s model_keywords check
            # narrows results down to the generations we want.
            urls = ["https://www.apple.com/shop/refurbished/iphone"]
        elif "ipad" in product.lower():
            # iPad Pro has a dedicated refurb page
            urls = ["https://www.apple.com/shop/refurbished/ipad/ipad-pro"]
        else:
            slug = product.lower().replace(" ", "-")
            urls = [f"https://www.apple.com/shop/refurbished/{slug}"]
        
        # Use a set of listing IDs we've already seen so we don't
        # add the same product twice (both pages return ALL products)
        seen_ids: set[str] = set()
        
        for page_url in urls:
            try:
                # Step 1: fetch the raw HTML with requests
                html = self.fetch_page(page_url)
                soup = self.parse_html(html)
                
                # Step 2: find the <script> tag that contains the
                # product data JSON
                script_tag = soup.find(
                    "script",
                    string=re.compile(r"window\.REFURB_GRID_BOOTSTRAP"),
                )
                if not script_tag:
                    print(
                        f"  [Apple Refurb] No REFURB_GRID_BOOTSTRAP found"
                        f" on {page_url}"
                    )
                    continue
                
                # Step 3: extract the JSON string from the script
                # content by removing the JS variable assignment
                script_content = script_tag.string
                
                # The variable looks like:
                #   window.REFURB_GRID_BOOTSTRAP = { ... };
                # We strip the prefix and the trailing semicolon.
                # Note: no ^ anchor — the content may have leading
                # whitespace (newlines + spaces before the var name)
                json_str = re.sub(
                    r"window\.REFURB_GRID_BOOTSTRAP\s*=\s*",
                    "",
                    script_content,
                    count=1,
                )
                json_str = json_str.strip().rstrip(";")
                
                # Step 4: parse the JSON
                data = json.loads(json_str)
                
                # Step 5: iterate through the tiles array
                tiles = data.get("tiles", [])
                for tile in tiles:
                    try:
                        # Step 6: filter for matching product type
                        # Apple uses "refurbClearModel" to identify product types
                        filters = tile.get("filters", {})
                        dimensions = filters.get("dimensions", {})
                        model = dimensions.get("refurbClearModel", "")
                        
                        # Filter based on product type
                        if "macbook" in product.lower():
                            if model != "macbookpro":
                                continue
                        elif "ipad" in product.lower():
                            if model != "ipadpro":
                                continue
                        elif "iphone" in product.lower():
                            if model != "iphone":
                                continue
                        
                        listing = self._parse_tile(tile)
                        if not listing:
                            continue
                        
                        # Deduplicate across both page fetches
                        if listing.listing_id in seen_ids:
                            continue
                        seen_ids.add(listing.listing_id)
                        
                        if self.passes_filters(listing):
                            found.append(listing)
                            
                    except Exception:
                        # Skip any malformed tile and move on
                        continue
                        
            except Exception as e:
                print(f"  [Apple Refurb] Error fetching {page_url}: {e}")
                continue
        
        print(f"  [Apple Refurb] Found {len(found)} matching listings")
        return found
    
    def _parse_tile(self, tile: dict) -> Optional[ScrapedListing]:
        """
        Parse a single tile from the REFURB_GRID_BOOTSTRAP JSON.
        
        Args:
            tile: A dict from the tiles array in the JSON data.
        
        Returns:
            A ScrapedListing or None if the tile is missing data.
        """
        # ── Title ───────────────────────────────────────────────
        # Apple titles look like:
        # "Refurbished 14-inch MacBook Pro Apple M5 Max chip with
        #  18‑Core CPU and 40‑Core GPU - Space Black"
        # or for iPad Pro:
        # "Refurbished 13-inch iPad Pro Apple M5 chip with
        #  8‑Core CPU and 10‑Core GPU - Space Black"
        title = tile.get("title", "")
        if not title:
            return None
        
        # Filter by product type in title
        product = self.config.search.product_name
        if "macbook" in product.lower() and "MacBook Pro" not in title:
            return None
        elif "ipad" in product.lower() and "iPad Pro" not in title:
            return None
        elif "iphone" in product.lower() and "iPhone" not in title:
            return None
        
        # ── Price ───────────────────────────────────────────────
        # The price object has a raw_amount field with the float
        price_obj = tile.get("price", {})
        current_price = price_obj.get("currentPrice", {})
        raw_amount = current_price.get("raw_amount")
        if raw_amount is None:
            return None
        
        try:
            price = float(raw_amount)
        except (ValueError, TypeError):
            return None
        
        # ── URL ─────────────────────────────────────────────────
        # productDetailsUrl is a relative path like
        # "/shop/product/FHFA4LL/A/refurbished-macbook-neo-..."
        # We need to prepend the Apple domain
        path = tile.get("productDetailsUrl", "")
        if not path:
            return None
        
        url = "https://www.apple.com" + path
        
        # ── Listing ID ──────────────────────────────────────────
        # Use the URL path as the unique ID since it's stable and
        # unique per product.  Strip the fnode query param so two
        # URLs for the same product still get the same ID.
        listing_id = path.split("?")[0]
        
        # ── Parse specs ─────────────────────────────────────────
        specs = self.parse_common_specs(title)
        ram = specs["ram_gb"]
        storage = specs["storage_gb"]
        screen = specs["screen_size"]
        chip = specs["chip"]
        cpu_cores = specs["cpu_cores"]
        gpu_cores = specs["gpu_cores"]

        return ScrapedListing(
            source=self.source_name,
            listing_id=listing_id,
            title=title,
            price_usd=price,
            url=url,
            condition="Refurbished",
            ram_gb=ram,
            storage_gb=storage,
            screen_size=screen,
            chip=chip,
            location="Apple Refurbished",
            cpu_cores=cpu_cores,
            gpu_cores=gpu_cores,
        )
