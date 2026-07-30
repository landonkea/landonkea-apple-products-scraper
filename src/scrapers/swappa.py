import re
from typing import Optional

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class SwappaScraper(BaseScraper):

    BASE_URL = "https://swappa.com"

    def __init__(self, config: Config):
        super().__init__(config)
        self.source_name = "swappa"
        self.target_screens = config.search.screen_sizes

    def _build_search_url(self, screen_size: Optional[int] = None) -> str:
        if screen_size:
            return f"{self.BASE_URL}/buy/macbooks/macbook-pro?sort=price_asc"
        else:
            product = self.config.search.product_name
            slug = product.lower().replace(" ", "-")
            category = "iphones" if "iphone" in product.lower() else slug
            return f"{self.BASE_URL}/buy/{category}/{slug}?sort=price_asc"

    def _fetch_listings_json(self, search_url: str) -> list[dict]:
        html = self.fetch_page(search_url)
        soup = self.parse_html(html)

        slugs: list[str] = []
        for card in soup.select("div.card.card_product"):
            title_el = card.select_one(".card-title.title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if self.target_screens and not any(str(size) in title for size in self.target_screens):
                continue

            sku_el = card.select_one('meta[itemprop="sku"]')
            slug = sku_el.get("content", "") if sku_el else ""
            if not slug:
                link = card.select_one("a")
                if link and link.get("href", "").startswith("/listings/"):
                    slug = link["href"].replace("/listings/", "")
            if slug:
                slugs.append(slug)

        all_listings: list[dict] = []
        for slug in slugs:
            listings_url = f"{self.BASE_URL}/listings/{slug}"
            try:
                listings_html = self.fetch_page(listings_url)
                listings_soup = self.parse_html(listings_html)
                for card in listings_soup.select("div.card.xui_card.xui_card_listing"):
                    listing = self._parse_listing(card)
                    if listing:
                        all_listings.append(listing)
            except Exception as e:
                print(f"  [Swappa] Error fetching listings for {slug}: {e}")
                continue

        return all_listings

    def _parse_listing(self, card) -> Optional[dict]:
        img = card.select_one("img[alt]")
        title = img.get("alt", "") if img else ""
        if not title:
            title_el = card.select_one("div.headline")
            title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None

        price_el = card.select_one('div.price span[itemprop="price"]')
        if not price_el:
            return None
        price_text = price_el.get_text(strip=True).replace("$", "").replace(",", "")
        try:
            price = float(price_text)
        except ValueError:
            return None

        link_el = card.select_one("div.price a")
        url = link_el.get("href", "") if link_el else ""
        if url and not url.startswith("http"):
            url = f"{self.BASE_URL}{url}"

        id_el = card.select_one("span.code.ms-2")
        listing_id = id_el.get_text(strip=True) if id_el else ""
        if not listing_id:
            m = re.search(r'/listing/view/([A-Z0-9]+)', url)
            if m:
                listing_id = m.group(1)

        location_el = card.select_one("div.ships_from")
        location = location_el.get_text(strip=True) if location_el else None

        attr_els = card.select("div.attrs span.attr")
        attrs = [a.get_text(strip=True) for a in attr_els] if attr_els else []

        condition = attrs[0] if len(attrs) > 0 else None

        raw_storage = attrs[1] if len(attrs) > 1 else ""
        raw_ram = attrs[2] if len(attrs) > 2 else ""
        raw_chip = attrs[3] if len(attrs) > 3 else ""

        storage_gb = None
        if raw_storage:
            m = re.search(r'(\d+)\s*(?:GB|TB)', raw_storage)
            if m:
                val = int(m.group(1))
                storage_gb = val * 1024 if "TB" in raw_storage.upper() else val

        ram_gb = None
        if raw_ram:
            m = re.search(r'(\d+)\s*GB', raw_ram)
            if m:
                ram_gb = int(m.group(1))

        chip = None
        if raw_chip:
            chip = raw_chip.replace("Apple ", "").strip()

        return {
            "title": title,
            "price": price,
            "url": url,
            "condition": condition,
            "listing_id": listing_id,
            "location": location,
            "ram_gb": ram_gb,
            "storage_gb": storage_gb,
            "chip": chip,
        }

    def _parse_item(self, item: dict) -> Optional[ScrapedListing]:
        title = item.get("title", "")
        if not title:
            return None

        price = item["price"]
        url = item.get("url", "")
        condition = item.get("condition")
        listing_id = item.get("listing_id", str(hash(title)))
        location = item.get("location")
        ram = item.get("ram_gb") or self.extract_ram(title)
        storage = item.get("storage_gb") or self.extract_storage(title)
        screen = self.extract_screen(title)
        chip = item.get("chip") or self.extract_chip(title)

        return ScrapedListing(
            source=self.source_name,
            listing_id=listing_id,
            title=title,
            price_usd=float(price),
            url=url,
            condition=condition,
            ram_gb=ram,
            storage_gb=storage,
            screen_size=screen,
            chip=chip,
            location=location,
        )

    def scrape(self) -> list[ScrapedListing]:
        found: list[ScrapedListing] = []
        found_ids: set = set()

        screen_sizes = self.config.search.screen_sizes
        sizes_to_search = screen_sizes if screen_sizes else [None]
        search_url = self._build_search_url(sizes_to_search[0])

        try:
            raw_listings = self._fetch_listings_json(search_url)
        except Exception as e:
            print(f"  [Swappa] Error fetching listings: {e}")
            return found

        for item in raw_listings:
            try:
                listing = self._parse_item(item)
                if listing and listing.listing_id not in found_ids:
                    if self.passes_filters(listing):
                        found.append(listing)
                        found_ids.add(listing.listing_id)
            except Exception:
                continue

        print(f"  [Swappa] Found {len(found)} matching listings")
        return found
