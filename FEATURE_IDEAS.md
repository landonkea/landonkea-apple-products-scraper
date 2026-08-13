# Feature Ideas

Concrete, scoped ideas for this specific scraper, grounded in what it
actually does today (`README.md`, `src/`). Not a roadmap, just a
running list to pull from. Each one names the files it'd touch and
why it's worth doing.

## More marketplaces / product coverage

**1. Amazon Warehouse / Amazon Renewed scraper.** A comment in
`src/price_analyzer.py`'s `top_deals_count` history already mentions
"future Facebook + Amazon" as a planned source. Amazon Warehouse
specifically carries used/open-box Apple gear at a discount, same
shape as Best Buy Open Box (`src/scrapers/bestbuy.py`), same
JS-rendering problem, same fix (Playwright). Would need a new
`src/scrapers/amazon.py` and an `amazon` entry in `config.yaml`'s
`sites:` block, `applicable_product_types: [electronics]` since Amazon
Warehouse only carries hardware.

**2. AirPods Max / AirPods Pro as a product type.** Right now
`electronics.py` only covers MacBook Pro, iPhone, and iPad Pro.
AirPods have their own resale market and their own accessory-listing
noise problem (charging cases, ear tips sold separately). Given how
`vision_pro.py` was built as its own `ProductTypeHandler` because
Vision Pro doesn't fit the RAM/chip shape, AirPods would likely need
the same treatment: no RAM, no chip tier, just model generation and
color.

**3. Apple Watch Ultra as a product type.** Same reasoning as AirPods.
Apple Watch has no RAM/storage tier that matters to buyers the way it
does for MacBook/iPhone, its value drivers are case size, cellular vs.
GPS-only, and band included. Another `ProductTypeHandler` candidate.

**4. Mac mini / Mac Studio / iMac support in `electronics.py`.**
The desktop line is completely unscraped today, only MacBook Pro is
configured. Desktops (especially Mac Studio) hold resale value well
and show up on the same marketplaces already scraped. This is a
`config.yaml` search entry plus verifying `electronics.py`'s title
parsing handles "Mac Studio M4 Max" the same way it handles "MacBook
Pro M5 Max" (it likely mostly does, since chip/RAM/storage parsing
isn't laptop-specific).

**5. EU/UK resale marketplaces (Vinted, CeX, MPB, Back Market's
non-US storefronts).** `backmarket.py` currently hits
backmarket.com (US). Back Market operates separate national sites
with different inventory and pricing. Relevant if the project ever
needs to track a device for someone outside the US, or just wants a
wider price-comparison baseline.

## Scoring and filtering improvements

**6. Seller reputation as a scoring input.** `price_analyzer.py`
already has a per-*marketplace* trust bonus (`source_reliability`,
e.g. Apple Refurb +2, Craigslist -3), but it can't tell a seller with
2,000 positive eBay ratings from one with 3. eBay and Mercari both
expose seller feedback score/rating in their listing HTML; parsing it
into a per-*listing* reliability nudge (on top of, not instead of,
the existing per-source one) would catch a bad-actor seller on an
otherwise-trusted marketplace.

**7. Bundle/lot detection.** A listing titled "MacBook Pro M5 Max LOT
OF 3" or "iPhone 17 Pro Max bundle w/ case + charger + AirPods" prices
multiple items as one line, which breaks the assumption that
`price_usd` is the price of *one* unit. `price_analyzer.py`'s
suspicious-price-outlier check already exists for a related problem
(implausibly cheap single items); a keyword-based bundle/lot filter
(`lot of`, `bundle`, `x2`, `x3`) in the relevant `ProductTypeHandler`
would catch the other failure mode, a bundle looking like a steal on
a per-unit basis when it isn't one.

**8. Normalized condition grading across marketplaces.**
`price_analyzer.py` currently does a loose keyword match
("excellent"/"good"/"fair") for the condition scoring bonus, but
Back Market and Gazelle both publish structured grading scales
("Fair/Good/Excellent/Premium" for Back Market, "Good/Great/Flawless"
for Gazelle) that don't map 1:1 onto each other or onto eBay's free-
text condition field. A small per-source grading-scale table (source
→ their grade → a normalized 1-5 scale) would make the existing
`condition` scoring bonus meaningfully comparable across all ten
scrapers instead of approximately comparable.

**9. AppleCare+/warranty-remaining as a scoring input.** Two
identically priced, identically specced listings aren't equal value
if one has a year of AppleCare+ left and the other has none. Some
sellers (especially Apple Refurb and Back Market) mention this in the
listing text. Worth a small parsed bonus similar to the existing
condition bonus, feeding into `deal_score_breakdown`.

**10. Region-adjusted pricing for Craigslist.** `craigslist.py` loops
over every configured metro region and merges results into one batch,
but the same MacBook Pro can legitimately cost more in San Francisco
than in Phoenix. A per-region price adjustment (or at minimum,
excluding Craigslist listings from the suspicious-price-outlier
median calculation, since mixing regions skews that median) would
stop a normal SF price from getting flagged as "not actually a great
deal" against a national median, or a normal Phoenix price from
skewing what counts as suspicious elsewhere.

## Alerts and history

**11. Historical-low-price badge.** The `price_history` table
(`src/database.py`'s `PriceHistory` model) already stores every price
a listing has ever been seen at. A one-line addition to the deal
alert, "lowest price this listing has ever shown" or "matches its
30-day low", turns data that's already being collected into
something visible in the Discord alert instead of only queryable by
hand.

**12. Buy-vs-wait seasonal guidance.** `DailyPriceStat` already tracks
min/avg/max per generation per day, enough to notice "average price
for M4 Max MacBook Pro has dropped 8% in the last 14 days" ahead of an
expected new-chip announcement. A periodic (weekly?) summary alert
built from that existing table, separate from the four
per-listing alert types that already exist, would answer "is this a
good week to buy" rather than just "is this one listing a good deal."

**13. Cross-source duplicate detection.** The same physical item
sometimes gets posted to both Craigslist and OfferUp (or Facebook)
by the same seller with different `listing_id`s. `main.py`'s
dedup is by `(source, listing_id)`, which correctly treats those as
two different rows, but two nearly-identical Discord alerts for what
is actually one item is noise. A fuzzy match (same price ± a few
dollars, same rough title, same metro) across sources within one run
could either merge them in the alert or flag the second one as
"possible duplicate of an above listing."

**14. Listing snapshot images.** Marketplace listings vanish once
sold, which is exactly when the "scooped deal" alert
(`Notifier.send_scooped_deal_alert()`) fires, there's no way to go
back and see what the listing actually looked like. Saving the first
product image URL (already present in most scrapers' parsed data,
just not persisted) alongside the `Listing` row would make scooped-
deal alerts and historical review more useful without adding real
scraping cost.

**15. Slack or ntfy.sh as a second notification channel.**
`notifier.py` supports email and Discord. Adding a third channel
(Slack incoming webhook, or ntfy.sh for a phone push notification
with zero app install) follows the same pattern already used for
Discord, gated behind its own `alerts.<channel>.enabled` config flag
and its own environment-scoped webhook/token, exactly like
`DISCORD_WEBHOOK_URL` vs. `DISCORD_WEBHOOK_URL_DEV`.

## Operational visibility

**16. Per-scraper health tracking.** Right now, if a marketplace
silently starts returning zero results (a selector broke, a site
redesign happened, the way `backmarket.py` needed a rewrite after a
real redesign, see `BUILD_LOG.md`), nothing surfaces that until a
human happens to notice the marketplace's listings have dried up. A
small table recording each scraper's listing count per run, with a
Discord warning if a normally-active source returns 0 for N
consecutive runs, would catch that class of silent failure instead of
waiting for a human to notice.

**17. Weekly digest page on GitHub Pages.** `docs/index.html` already
renders a daily trend chart from `docs/data/daily_stats.json`
(built by `src/pages_generator.py`). A weekly rollup view, best deal
of the week per product, biggest price drop, total listings seen,
would give the existing GitHub Pages site something worth checking
even on days without a personal deal alert.

**18. Ad hoc one-off search CLI command.** Every current search comes
from a `config.yaml` `searches:` entry, always-on and re-run every
scrape. Sometimes what's wanted is a single, immediate check ("what's
the cheapest 16-inch M4 Max right now") without editing the config
file. A `apple-product-scraper search "MacBook Pro" --chip "M4 Max"
--max-price 3500` subcommand, reusing the existing scraper registry
and price analyzer but skipping the database/alert steps, would cover
that without touching the production config.

**19. Configurable per-source scrape frequency.** All ten scrapers
currently run on the same daily schedule. Some marketplaces (eBay,
Craigslist) get new listings constantly; others (Apple Refurb's
catalog) barely change day to day. A per-source `check_every_n_runs`
config value would cut unnecessary requests to slow-changing sources
without touching the fast-changing ones, useful mainly if the
schedule is ever increased back toward multiple runs a day.

**20. `--source` / `--product` CLI filters for manual runs.**
`workflow_dispatch` manual runs and local `--dry-run` runs currently
always scrape every enabled site for every configured search. A
`--source ebay,swappa` or `--product "iPhone Pro Max"` flag would let
someone debugging a single scraper (the OfferUp saga in `BUILD_LOG.md`
is the textbook case) iterate on just that one path instead of
waiting through nine other scrapers' network calls first.
