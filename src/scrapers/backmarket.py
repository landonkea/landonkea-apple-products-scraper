import re

from config import Config
from scrapers.base import BaseScraper, ScrapedListing


class BackMarketScraper(BaseScraper):

    def __init__(self, config: Config):
        super().__init__(config)
        self.source_name = "backmarket"

    def _build_search_url(self, screen_size: int) -> str:
        product = self.config.search.product_name
        query = f"{product} {screen_size}-inch"
        encoded = query.replace(" ", "+")
        return f"https://www.backmarket.com/search?q={encoded}"

    def _fetch_with_stealth(self, search_url: str) -> str:
        try:
            from playwright.sync_api import sync_playwright
            from playwright_stealth import Stealth

            with Stealth().use_sync(sync_playwright()) as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                )
                page = context.new_page()

                page.goto("https://www.backmarket.com", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)

                page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(8000)

                html = page.content()
                browser.close()
                return html
        except Exception as e:
            raise Exception(f"Playwright stealth failed: {e}") from e

    def _slug_to_title(self, slug: str) -> str:
        parts = slug.split("/")
        if len(parts) >= 3:
            slug = parts[2]
        slug = slug.split("/")[0] if "/" in slug else slug
        title = slug.replace("-", " ")
        title = title.replace("gb", "GB").replace("ssd", "SSD").replace("ram", "RAM").replace("gpu", "GPU")
        words = title.split()
        if words:
            words[0] = words[0].capitalize()
        return " ".join(words)

    def scrape(self) -> list[ScrapedListing]:
        found: list[ScrapedListing] = []
        found_ids: set = set()

        for screen_size in self.config.search.screen_sizes:
            url = self._build_search_url(screen_size)
            html = None

            try:
                html = self._fetch_with_stealth(url)
            except Exception as e:
                print(f"  [Back Market] Playwright stealth failed: {e}, trying normal Playwright...")
                try:
                    html = self.fetch_with_playwright(url)
                except Exception as e2:
                    print(f"  [Back Market] Normal Playwright also failed: {e2}, trying plain request...")
                    try:
                        html = self.fetch_page(url)
                    except Exception as e3:
                        print(f"  [Back Market] All methods failed: {e3}")
                        continue

            if not html:
                continue
            soup = self.parse_html(html)

            cards = soup.select("article[data-spec='product-card-content']")
            if not cards:
                cards = soup.select("article._cardContainer")
            if not cards:
                cards = soup.select("[class*='_cardContainer_']")
            if not cards:
                cards = soup.find_all("article")

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

        print(f"  [Back Market] Found {len(found)} matching listings")
        return found

    def _parse_card(self, card) -> ScrapedListing | None:
        title_elem = card.select_one("span[data-test='product-title']")
        if not title_elem:
            return None

        display_title = title_elem.get_text(strip=True)
        if not display_title:
            return None

        link_elem = card.select_one("h3 a")
        url = ""
        slug = ""
        if link_elem:
            href = link_elem.get("href", "")
            if href:
                url = href
                if not url.startswith("http"):
                    url = f"https://www.backmarket.com{url}"
                slug_match = re.search(r"/p/([^/?]+)", href)
                if slug_match:
                    slug = slug_match.group(1)

        title = self._slug_to_title(slug) if slug else display_title

        price_el = card.select_one("[data-qa='productCardPrice'] .heading-2")
        if not price_el:
            price_el = card.select_one("[data-qa='productCardPrice']")
        if not price_el:
            return None

        price_text = price_el.get_text(strip=True)
        price_text = price_text.replace("$", "").replace(",", "").replace(" ", "")
        price_match = re.search(r'(\d+(?:\.\d{2})?)', price_text)
        if not price_match:
            return None
        price = float(price_match.group(1))

        condition = "Refurbished"

        listing_id = f"bm_{hash(url or title)}"

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
