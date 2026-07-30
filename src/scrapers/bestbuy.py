import re
from typing import Optional

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class BestBuyScraper(BaseScraper):

    def __init__(self, config: Config):
        super().__init__(config)
        self.source_name = "bestbuy"

    def _fetch_search_page(self, url: str) -> Optional[str]:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                )
                page = context.new_page()
                page.goto("https://www.bestbuy.com", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(5000)
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            print(f"  [Best Buy] Playwright fetch failed: {e}")
            return None

    def _build_search_url(self, screen_size: int) -> str:
        product = self.config.search.product_name
        query = f"open box {product} {screen_size}-inch"
        encoded_query = query.replace(" ", "+")
        return (
            f"https://www.bestbuy.com/site/searchpage.jsp"
            f"?st={encoded_query}"
            f"&sort=PRICE_LOW_TO_HIGH"
        )

    def _parse_listing_id(self, item, url: str) -> str:
        pid = item.get("data-product-id")
        if pid:
            return str(pid)
        match = re.search(r'/sku/(\d+)', url)
        if match:
            return match.group(1)
        return f"url_{hash(url)}"

    def _get_condition(self, item) -> Optional[str]:
        link_el = item.select_one("a.product-list-item-link")
        if link_el:
            href = link_el.get("href", "")
            if "/openbox" in href:
                return "Open-Box"
        badge = item.select_one('[data-testid="price-block-badging-text"]')
        if badge:
            text = badge.get_text(strip=True)
            if "open" in text.lower():
                return "Open-Box"
        cond = item.select_one('[data-testid*="open-box-sku-messaging"] .font-weight-medium')
        if cond:
            text = cond.get_text(strip=True)
            if text:
                return text
        full_text = item.get_text(" ", strip=True)
        if "Open Box" in full_text or "Open-Box" in full_text:
            return "Open-Box"
        return None

    def _parse_single_item(self, item) -> Optional[ScrapedListing]:
        title_el = item.select_one("h3.product-title")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        if not title or "MacBook" not in title:
            return None
        link_el = item.select_one("a.product-list-item-link")
        if not link_el:
            return None
        url = link_el.get("href", "")
        if url.startswith("/"):
            url = "https://www.bestbuy.com" + url
        condition = self._get_condition(item)
        if not condition:
            return None
        price_el = item.select_one('[data-testid="price-block-customer-price"] .font-500')
        if not price_el:
            return None
        price_text = price_el.get_text(strip=True)
        price_text = price_text.replace("$", "").replace(",", "")
        price_match = re.search(r'(\d+(?:\.\d{2})?)', price_text)
        if not price_match:
            return None
        price = float(price_match.group(1))
        listing_id = self._parse_listing_id(item, url)
        ram = self.extract_ram(title)
        storage = self.extract_storage(title)
        screen = self.extract_screen(title)
        chip = self.extract_chip(title)
        if ram is None:
            if "128GB" in url:
                ram = 128
            elif "64GB" in url:
                ram = 64
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

    def scrape(self) -> list[ScrapedListing]:
        found: list[ScrapedListing] = []
        found_ids: set = set()
        for screen_size in self.config.search.screen_sizes:
            search_url = self._build_search_url(screen_size)
            html = self._fetch_search_page(search_url)
            if not html:
                continue
            soup = self.parse_html(html)
            items = soup.select("li.product-list-item")
            if not items:
                items = soup.select(".product-list-item")
            results_for_size = 0
            max_results = self.config.search.results_per_size
            for item in items:
                if results_for_size >= max_results:
                    break
                try:
                    listing = self._parse_single_item(item)
                    if listing and listing.listing_id not in found_ids:
                        if self.passes_filters(listing):
                            found.append(listing)
                            found_ids.add(listing.listing_id)
                            results_for_size += 1
                except Exception:
                    continue
        print(f"  [Best Buy] Found {len(found)} matching Open Box listings")
        return found
