import re
from typing import Optional
from urllib.parse import quote

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class MercariScraper(BaseScraper):

    def __init__(self, config: Config):
        super().__init__(config)
        self.source_name = "mercari"

    def _build_search_url(self, screen_size: Optional[int]) -> str:
        product = self.config.search.product_name
        if screen_size:
            query = f"{product} {screen_size}inch"
        else:
            query = product
        encoded = quote(query)
        return f"https://jp.mercari.com/search?keyword={encoded}"

    def scrape(self) -> list[ScrapedListing]:
        found: list[ScrapedListing] = []
        found_ids: set = set()

        screen_sizes = self.config.search.screen_sizes
        sizes_to_search = screen_sizes if screen_sizes else [None]
        
        for screen_size in sizes_to_search:
            url = self._build_search_url(screen_size)
            html = None

            try:
                html = self.fetch_with_playwright(url)
            except Exception as e:
                print(f"  [Mercari] Playwright failed: {e}, trying plain request...")
                try:
                    html = self.fetch_page(url)
                except Exception as e2:
                    print(f"  [Mercari] Plain request also failed: {e2}")
                    continue

            if not html:
                continue
            soup = self.parse_html(html)

            cards = soup.select("li[data-testid='item-cell']")
            if not cards:
                cards = soup.select("a[data-testid='thumbnail-link']")

            results_for_size = 0
            max_results = self.config.search.results_per_size

            for card in cards:
                if results_for_size >= max_results:
                    break
                try:
                    listing = self._parse_card(card)
                    if listing and listing.listing_id not in found_ids:
                        if self.passes_filters(listing):
                            found.append(listing)
                            found_ids.add(listing.listing_id)
                            results_for_size += 1
                except Exception:
                    continue

        print(f"  [Mercari] Found {len(found)} matching listings")
        return found

    def _parse_card(self, card) -> Optional[ScrapedListing]:
        title_elem = card.select_one("span[data-testid='thumbnail-item-name']")
        if not title_elem:
            return None

        title = title_elem.get_text(strip=True)
        if not title or "MacBook" not in title:
            return None

        price_amount = card.select_one("span.number__6b270ca7")
        if not price_amount:
            return None
        price_text = price_amount.get_text(strip=True)
        price_text = price_text.replace("$", "").replace(",", "")
        try:
            price = float(price_text)
        except ValueError:
            return None

        link_elem = card.select_one("a[data-testid='thumbnail-link']")
        url = ""
        if link_elem:
            url = link_elem.get("href", "")
            if url and not url.startswith("http"):
                url = f"https://jp.mercari.com{url}"

        id_match = re.search(r'/(?:item|shops/product)/([^/]+)', url)
        listing_id = f"mercari_{id_match.group(1)}" if id_match else f"mercari_{abs(hash(url))}"

        condition = None

        ram = self.extract_ram(title)
        storage = self.extract_storage(title)
        screen = self.extract_screen(title)
        chip = self.extract_chip(title)

        return ScrapedListing(
            source=self.source_name,
            listing_id=listing_id,
            title=title,
            price_usd=price,
            url=url,
            condition=condition,
            ram_gb=ram,
            storage_gb=storage,
            screen_size=screen,
            chip=chip,
            location=None,
        )
