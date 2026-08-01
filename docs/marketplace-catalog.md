# Marketplace & Retailer Catalog

Reference doc for deciding what to scrape next as this project expands into new
product categories (e.g. dress boots after MacBook Pro / iPhone). Compiled via
web search in July 2026, cross-checking that each listed site is still
operating — this project previously discovered that Decluttr (a well-known
used-electronics site) had permanently shut down in June 2025, so "well known"
is not the same as "currently live."

**This is a planning aid, not a scraping guarantee.** The "scraping
feasibility" notes below are best-guess inferences (public search page vs.
JS-heavy app vs. known bot defenses), not verified results. Actually confirming
feasibility requires live-testing against the real site, the same way this
project's 9 existing scrapers (eBay, Swappa, Mercari, OfferUp, BackMarket,
Apple Refurb, Best Buy, Newegg, Gazelle) were actually built and verified.

Columns: **What it sells** | **Login to search?** | **Feasibility guess**

---

## 1. General / cross-category marketplaces

Sell almost anything; not tied to one product vertical. The project already
uses eBay, Swappa, Mercari, OfferUp, and BackMarket.

| Site | What it sells | Login to search? | Scraping feasibility (best guess) |
|---|---|---|---|
| **eBay** *(in use)* | Everything, new & used, auction + fixed price | No | Public search pages; has an official API too |
| **Swappa** *(in use)* | Used tech (phones, laptops, etc.), peer-to-peer | No | Public search/listing pages, likely scrapable |
| **Mercari** *(in use)* | Everything, general secondhand marketplace | No | Public search, but has a JS-heavy SPA front end |
| **OfferUp** *(in use)* | Everything, local peer-to-peer | No | Public search pages; some bot-detection reported |
| **BackMarket** *(in use)* | Certified refurbished electronics only | No | Public catalog/search pages, likely scrapable |
| **Facebook Marketplace** | Everything, local peer-to-peer | Partial — browsing/search works logged-out (dismiss the login prompt, or use `facebook.com/marketplace` with a ZIP code), but contacting sellers/alerts need an account | Heavy JS SPA; known for aggressive anti-scraping; project already treats this as needing a session-cookie approach |
| **Craigslist** | Everything, local classifieds | No | Plain server-rendered HTML, historically very scrapable, no JS required |
| **Poshmark** | Clothing, shoes, accessories (used & new via closet sellers) | Effectively yes for the app; desktop web search works without login, and Google `site:poshmark.com` search is a workaround | Server-rendered search results on desktop web, likely scrapable |
| **Depop** | Fashion resale, vintage, streetwear (younger/Gen-Z skew) | No for browsing | JS-heavy app; being acquired by eBay from Etsy (deal closed July 30 2026) but continuing to operate under its own brand/site |
| **Vinted** | Clothing, footwear, accessories, growing home-goods category; zero seller fees | No for browsing (account needed to sell/message) | Public search/category pages, likely scrapable; large EU-origin marketplace now active in the US |

---

## 2. Electronics / computers / phones

Project already uses Apple Refurb, Best Buy, Newegg, and Gazelle.

| Site | What it sells | Login to search? | Scraping feasibility (best guess) |
|---|---|---|---|
| **Apple Refurbished Store** *(in use)* | Apple-certified refurbished Apple products | No | Public catalog pages, likely scrapable |
| **Best Buy** *(in use)* | New electronics, plus "Open Box"/outlet | No | Public search; has an official API |
| **Newegg** *(in use)* | New & marketplace-seller computer hardware/electronics | No | Public search pages, likely scrapable |
| **Gazelle** *(in use)* | Buys used phones/tablets; sells certified refurbished phones/tablets | No | Public catalog pages under `buy.gazelle.com`, likely scrapable |
| ~~**Decluttr**~~ | *(used electronics/tech — do not use)* | — | **Shut down permanently, June 17 2025** — confirmed via multiple sources; site now just shows a closure banner |
| **B&H Photo Video** | New (and a dedicated "Used" department) cameras, computers, electronics | No | Public catalog/search pages; a third-party service (Zinc) offers a paid order/search API, but no native public API confirmed |
| **Micro Center** | New computer parts/electronics, plus Clearance/Open-Box/Refurbished filters | No | Public search pages (`microcenter.com/search/...`), but inventory/pricing is store-specific — a location parameter matters |
| **Woot (Amazon)** | Rotating daily-deal electronics, refurbished/overstock goods across categories | No for browsing; Amazon account needed to buy | Public deal pages, likely scrapable; deal catalog rotates daily/hourly |
| **Amazon Trade-In / Amazon Renewed** | Amazon's own used/renewed electronics program + trade-in credit | No for browsing Renewed listings | Public search under the "Renewed" storefront; Amazon has strong bot detection generally |
| **SellCell** | Not a marketplace itself — a price-comparison aggregator across phone/electronics buyback sites (Gazelle, etc.) | No | Public comparison pages; useful as a secondary data source rather than a primary scrape target |
| **Swappa** *(already listed above, general — but effectively electronics-only in practice)* | Used phones, laptops, tablets, smartwatches | No | See above |

---

## 3. Apparel / shoes / boots (user's next category)

Mix of new-only retail and resale/consignment — noted per site.

| Site | What it sells | New or resale | Login to search? | Scraping feasibility (best guess) |
|---|---|---|---|---|
| **Zappos** | Shoes, clothing, accessories (Amazon subsidiary) | New | No | Public search pages, likely scrapable |
| **6pm.com** | Discounted/clearance shoes & apparel (Zappos' outlet arm) | New (discount) | No | Public search pages, likely scrapable |
| **Nordstrom Rack** | Discounted designer apparel/shoes (Nordstrom's off-price arm) | New (discount) | No | Public search pages, likely scrapable |
| **DSW (Designer Shoe Warehouse)** | Shoes across brands, in-store + online | New | No | Public search pages, likely scrapable |
| **ThredUp** | Secondhand clothing/shoes/accessories, tech-enabled consignment | Resale | No | Public search pages, likely scrapable |
| **StockX** | Sneakers, streetwear, apparel, accessories — authenticated marketplace with bid/ask pricing | Resale (deadstock + used "Listings") | Unclear from research whether the new "Listings" (pre-owned) marketplace requires login to browse — verify directly | JS-heavy app; likely has some bot defenses given its bid/ask trading model |
| **GOAT** | Sneakers, apparel, accessories — authenticated marketplace | Resale + new | No login required to browse `goat.com`, only to buy/sell | JS-heavy app (React), moderate scraping difficulty likely |
| **Grailed** | Menswear-focused designer/streetwear resale (also womenswear via sister site) | Resale | No for browsing | Public search/listing pages, likely scrapable; owned by GOAT Group |
| **The RealReal** | Luxury consignment: apparel, shoes, bags, jewelry | Resale | No for browsing | Public search pages, likely scrapable; actively expanding (new stores in 2026) |
| **Vestiaire Collective** | Luxury/designer fashion resale, global (70+ countries) | Resale | No for browsing | Public search pages, likely scrapable; French company, strong in Europe, growing US presence |
| **Poshmark** *(overlaps with general category above)* | Clothing, shoes, accessories | Resale | Desktop browsing works without login | See general section above |
| **Depop** *(overlaps with general category above)* | Fashion resale, vintage, streetwear | Resale | No for browsing | See general section above |

---

## 4. Furniture / home goods

Facebook Marketplace and Craigslist (already listed above) are usually the
biggest sources for used furniture by volume.

| Site | What it sells | Login to search? | Scraping feasibility (best guess) |
|---|---|---|---|
| **Facebook Marketplace** *(see general section)* | Huge volume of local used furniture | Partial (browsing works logged-out) | Heavy JS SPA, session-cookie approach as already used in this project |
| **Craigslist** *(see general section)* | Huge volume of local used furniture | No | Plain HTML, very scrapable |
| **Chairish** | Curated vintage/high-end used furniture, décor, art | No for browsing | Public search pages, likely scrapable; acquired by Auction Technology Group (Aug 2025), still active in 2026 |
| **AptDeco** | Used furniture marketplace with pickup/delivery logistics (NYC-founded, national) | No for browsing | Public catalog pages (`aptdeco.com/catalog/...`), likely scrapable |
| **Wayfair Outlet** | Discounted overstock/discontinued/returned new furniture & home goods | No | Public site under `wayfair.com/daily-sales/closeout` plus physical outlet stores; likely scrapable |
| **1stDibs** | High-end/vintage furniture, art, and design (auction-house-adjacent pricing) | No for browsing | Public search pages, likely scrapable — not independently verified as still operating in this pass, worth a quick check before building |
| ~~**Kaiyo**~~ | *(used furniture marketplace — do not use)* | — | **Shut down / wound down, August 2024** — confirmed; site listed as "CLOSED" on Yelp as of July 2026 |
| ~~**Move Loot**~~ | *(used furniture — do not use)* | — | Shut down years ago (pre-2018); mentioned only to warn against outdated "best furniture resale sites" listicles that still cite it |

---

## 5. Collectibles / other (lower priority)

Sneakers/streetwear entries (StockX, GOAT) already covered above and overlap
heavily with apparel.

| Site | What it sells | Login to search? | Scraping feasibility (best guess) |
|---|---|---|---|
| **StockX** *(see apparel section)* | Sneakers, streetwear, trading cards, watches, collectibles | Unclear for new "Listings" resale tier | JS-heavy, likely some bot defenses |
| **GOAT** *(see apparel section)* | Sneakers, apparel, accessories | No for browsing | JS-heavy app |
| **Whatnot** | Live-video auction marketplace: collectibles, trading cards, comics, Funko Pops, fashion; also has a static "Marketplace" of fixed listings alongside live auctions | Likely yes for full listing detail/bidding; unconfirmed for casual browsing | Live-auction format plus a fixed-listing marketplace — real-time/video content makes this a poor scraping target compared to static listings |
| **eBay** *(see general section)* | Also the single largest trading-card/collectibles/watch marketplace by volume | No | Already in use by the project |

---

## Notes on sites deliberately excluded

- **Decluttr** — permanently shut down (US operations), June 2025.
- **Kaiyo** — furniture resale marketplace, wound down August 2024.
- **Move Loot** — furniture resale marketplace, shut down years ago; still shows up in stale "best of" listicles.

## Suggested next step

Before writing a scraper for any site above, do a quick manual check of:
1. Whether the search results page is server-rendered HTML (view source) vs. requiring a headless browser.
2. Robots.txt / ToS stance on automated access.
3. Whether pricing/availability is delivered via a discoverable JSON endpoint (many modern storefronts, e.g. Micro Center, load results via XHR — inspect network tab before assuming you need full HTML scraping).
