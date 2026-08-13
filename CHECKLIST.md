# landonkea-apple-products-scraper checklist

Status + explicit next-agenda items. Delete this file once everything below is checked off.

## Next up
- [ ] Delete the now-merged `feat/apple-vision-pro` and `promote/apple-vision-pro` branches on GitHub (local + remote), they're fully merged into `main`/`staging`/`dev` and just clutter the branch list now.
- [ ] Watch the next scheduled production run (13 UTC / 6am Phoenix) and the staging CI run to confirm Apple Vision Pro alerts actually fire correctly against live marketplace data (only verified offline with synthetic listings so far, not a real scrape).

## Future / ideas
- [ ] Apple-only storefronts (Apple Refurb, BestBuy, Newegg, Gazelle) don't search Vision Pro yet, they're scoped to `applicable_product_types: [electronics]` and some hit hardcoded per-generation URLs. Extending them needs real per-scraper work, not just config.
- [ ] `apparel` product type (boots) is fully built and tested but intentionally not live in `config.yaml`, still true, not a regression, just noting it's still on the shelf if ever wanted.
- [ ] If Apple ever ships a genuine second-generation (redesigned) Vision Pro, `generations:`-style lookback logic would need to be added to `vision_pro.py`, it currently only distinguishes M2 vs M5 by a flat chip-string check, not a generation window.
