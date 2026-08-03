# ───────────────────────────────────────────────────────────────────
# Notifier — sends alerts via email and Discord
# ───────────────────────────────────────────────────────────────────
# When great deals are found, this module:
#   1. Sends an HTML email via Gmail SMTP (free with app password)
#   2. Posts a message to a Discord channel via webhook (free)
#
# Both methods are optional — set enabled: false in config.yaml
# to disable either one.
# ───────────────────────────────────────────────────────────────────

import smtplib
import json
import os
import re
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import requests

from database import Listing
from config import Config
from environment import is_production


def clean_url(url: str) -> str:
    url = re.sub(r'\?.*', '', url)
    url = re.sub(r'#.*', '', url)
    return url


def format_listing_age(first_seen_at: Optional[datetime]) -> str:
    """
    Render "how long ago was this listing first seen" as a short,
    human-friendly string for alerts, e.g. "Listed 4h ago" or
    "Listed 3d ago".

    WHY: "Listed 4 hours ago" is a real buyer signal (a fresh listing
    is more likely still available / negotiable than one that's sat
    for weeks) that wasn't previously surfaced anywhere in the alert.

    HOW: `first_seen_at` comes back from SQLite as a naive datetime
    (tzinfo stripped on round-trip even though it's stored as UTC --
    see Listing.first_seen_at's default) -- this treats a naive value
    as UTC rather than assuming local time, and also tolerates an
    already-aware datetime (e.g. one built directly in a test) so
    both cases produce a correct delta against "now".

    Args:
        first_seen_at: The listing's Listing.first_seen_at value, or
            None if unknown.

    Returns:
        A string like "Listed 4h ago", or "" if first_seen_at is
        None.
    """
    if first_seen_at is None:
        return ""

    seen = first_seen_at
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)

    seconds = max((datetime.now(timezone.utc) - seen).total_seconds(), 0)
    minutes = seconds / 60
    hours = minutes / 60
    days = hours / 24

    if hours < 1:
        return f"Listed {max(int(minutes), 1)}m ago"
    elif days < 1:
        return f"Listed {int(hours)}h ago"
    else:
        return f"Listed {int(days)}d ago"


class Notifier:
    """
    Sends deal alerts.
    
    Usage:
        notifier = Notifier(config)
        notifier.send_alert(top_deals, stats)
    """
    
    def __init__(self, config: Config):
        """
        Initialize the notifier with config and credentials.
        
        Args:
            config: The global Config object (has alert settings).
        """
        self.config = config
        self.secrets = config.secrets
    
    def send_alert(self, top_deals: list[Listing], stats: dict):
        """
        Send alerts through all enabled channels.
        
        Args:
            top_deals: The best deals (already sorted by score).
            stats: Price statistics dict from PriceAnalyzer.
        """
        if not top_deals:
            print("  [Notifier] No deals to alert about.")
            return
        
        print(f"  [Notifier] Sending alerts for {len(top_deals)} deals...")
        
        # Send via each enabled channel
        if self.config.alerts.email.enabled:
            try:
                self._send_email(top_deals, stats)
            except Exception as e:
                print(f"  [Notifier] Email failed: {e}")
        
        if self.config.alerts.discord.enabled:
            try:
                self._send_discord(top_deals, stats)
            except Exception as e:
                print(f"  [Notifier] Discord failed: {e}")

    def send_price_drop_alert(self, price_drops: list[tuple[Listing, float]]):
        """
        Send price-drop alerts through all enabled channels.

        WHAT: A SEPARATE alert type from send_alert() above -- fires
        for listings we've already seen before whose price just
        dropped meaningfully (see is_meaningful_price_drop in
        price_analyzer.py), rather than for newly discovered listings.

        Args:
            price_drops: (listing, old_price) pairs -- `listing` is
                the current (already-updated) Listing with its new
                price_usd; `old_price` is what it was recorded at
                before this scrape.
        """
        if not price_drops:
            return

        print(f"  [Notifier] Sending price-drop alerts for "
              f"{len(price_drops)} listing(s)...")

        if self.config.alerts.discord.enabled:
            try:
                self._send_discord_price_drop(price_drops)
            except Exception as e:
                print(f"  [Notifier] Discord price-drop alert failed: {e}")

    def send_scooped_deal_alert(self, scooped: list[Listing]):
        """
        Send an alert when a great deal disappears fast — likely
        bought by someone else.

        WHAT: A THIRD alert type (alongside send_alert's "new deal
        found" and send_price_drop_alert's "price dropped"), fired
        from main.py's expire_stale_listings() cross-reference: a
        listing that was flagged is_great_deal AND whose entire
        visible lifetime (first seen to last seen) was under
        SCOOPED_DEAL_HOURS.
        HOW: Same Discord-only send path as the other alert types
        (email isn't wired up for this one — it's a low-volume,
        Discord-first heads-up, not something worth a full email).
        WHY: Not previously surfaced anywhere — a great deal quietly
        going inactive looked identical to any other listing expiring,
        even though "great price, gone within a day" is a real signal
        worth knowing (confirms the scoring is finding genuinely good
        deals, and is a data point for how fast to act next time).

        Args:
            scooped: Listings that were great deals and expired fast.
                Note these are already marked is_active=False by the
                time this is called.
        """
        if not scooped:
            return

        print(f"  [Notifier] Sending scooped-deal alerts for "
              f"{len(scooped)} listing(s)...")

        if self.config.alerts.discord.enabled:
            try:
                self._send_discord_scooped_deal(scooped)
            except Exception as e:
                print(f"  [Notifier] Discord scooped-deal alert failed: {e}")

    def _build_stats_summary_html(self, stats: dict) -> str:
        """
        Build the "Market Overview" stats box HTML for the email body.

        WHAT: A small info box showing listing count, price range,
        average, median, and standard deviation.
        HOW: Formats the `stats` dict (produced by PriceAnalyzer) into
        an inline-styled HTML `<div>`.
        WHY: Pulled out of `_build_email_body` so the stats box can be
        read, tested, and changed independently of the deals table or
        footer — each piece of the email now has a single job.

        Args:
            stats: Price statistics dict from PriceAnalyzer.

        Returns:
            An HTML string for the stats summary box.
        """
        return f"""
        <div style="margin-bottom: 20px; padding: 15px;
                    background: #f5f5f5; border-radius: 8px;">
            <h2 style="margin-top: 0; color: #333;">
                📊 Market Overview
            </h2>
            <p>
                Found <strong>{stats['count']}</strong> matching listings.
                Price range:
                <strong>${stats['min']:,.0f}</strong> –
                <strong>${stats['max']:,.0f}</strong>
            </p>
            <p>
                Average: <strong>${stats['mean']:,.0f}</strong> |
                Median: <strong>${stats['median']:,.0f}</strong> |
                Std Dev: <strong>${stats['std_dev']:,.0f}</strong>
            </p>
        </div>
        """

    def _build_deal_row_html(self, listing: Listing) -> str:
        """
        Build the HTML `<tr>` for exactly one deal in the email table.

        WHAT: Renders one listing's emoji, title/link, price, RAM,
        condition, and source as a table row.
        HOW: Picks a quality emoji from the listing's deal score/flag,
        then formats the row with inline styles matching the rest of
        the email.
        WHY: Split out of the deals-table loop so a single row's markup
        can be read and tested on its own, separate from the looping
        and table-wrapping logic in `_build_deals_table_html`.

        Args:
            listing: One deal to render.

        Returns:
            An HTML string for a single `<tr>` row.
        """
        # Emoji for deal quality
        if listing.is_great_deal:
            emoji = "🔥"  # Fire = great deal
        elif listing.deal_score and listing.deal_score >= 60:
            emoji = "💰"  # Money = good deal
        else:
            emoji = "👀"  # Eyes = worth a look

        condition = listing.condition or "N/A"
        ram = f"{listing.ram_gb}GB" if listing.ram_gb else "?"

        return f"""
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">
                    {emoji}
                </td>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">
                    <a href="{listing.url}" style="color: #0066cc;
                       text-decoration: none; font-weight: 500;">
                        {listing.title[:80]}
                    </a>
                </td>
                <td style="padding: 10px; border-bottom: 1px solid #eee;
                           text-align: right; font-weight: bold;
                           color: {'#00aa00' if listing.is_great_deal else '#333'}">
                    ${listing.price_usd:,.0f}
                </td>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">
                    {ram}
                </td>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">
                    {condition}
                </td>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">
                    {listing.source}
                </td>
            </tr>
            """

    def _build_deals_table_html(self, top_deals: list[Listing]) -> str:
        """
        Build the full "Top Deals" heading + table for the email body.

        WHAT: Wraps one `<tr>` per deal (from `_build_deal_row_html`)
        in a `<table>` with a header row, under a "Top N Deals" title.
        HOW: Loops over `top_deals`, delegating each row's markup to
        `_build_deal_row_html`, then joins the rows into the table
        body.
        WHY: Separated from `_build_email_body` so the table structure
        (headers, wrapping markup) is readable independent of both the
        per-row rendering and the rest of the email shell.

        Args:
            top_deals: The top-scored listings, in display order.

        Returns:
            An HTML string with the deals heading and table.
        """
        deals_rows = "".join(
            self._build_deal_row_html(listing) for listing in top_deals
        )

        return f"""
        <h2 style="color: #333;">🔥 Top {len(top_deals)} Deals</h2>
        <table style="width: 100%; border-collapse: collapse;">
            <thead>
                <tr style="background: #333; color: white;">
                    <th style="padding: 10px; text-align: left;"></th>
                    <th style="padding: 10px; text-align: left;">Title</th>
                    <th style="padding: 10px; text-align: right;">Price</th>
                    <th style="padding: 10px; text-align: left;">RAM</th>
                    <th style="padding: 10px; text-align: left;">Condition</th>
                    <th style="padding: 10px; text-align: left;">Source</th>
                </tr>
            </thead>
            <tbody>
                {deals_rows}
            </tbody>
        </table>
        """

    def _build_email_footer_html(self) -> str:
        """
        Build the "Searching for: ..." footer paragraph for the email.

        WHAT: A small, muted paragraph summarizing the search criteria
        (product name, screen sizes, chip, RAM, max price) used to
        find these deals.
        HOW: Reads directly off `self.config.search`/`self.config.price`.
        WHY: This is intentionally NOT merged with `_build_search_summary()`
        (used for the Discord footer) — that helper produces a
        differently-formatted, product-branching summary without a
        "Searching for:" prefix or max-price field, built for Discord's
        embed footer. Forcing a merge here would change the email's
        visible text, which this refactor must not do. Still pulled
        into its own method so the email shell in `_build_email_body`
        doesn't have to inline this formatting itself.

        Returns:
            An HTML string for the email footer paragraph.
        """
        sizes_str = "/".join(str(s) for s in self.config.search.screen_sizes)
        chip_str = self.config.search.chip or "any chip"
        ram_str = f"{self.config.search.ram_gb_primary}GB" if self.config.search.ram_gb_primary else "any RAM"
        return f"""
        <p style="color: #999; font-size: 12px; margin-top: 30px;">
            Searching for: {self.config.search.product_name}
            {sizes_str}" | Chip: {chip_str} |
            RAM: {ram_str} |
            Max price: ${self.config.price.absolute_max_usd:,.0f}
        </p>
        """

    def _build_email_body(self, top_deals: list[Listing],
                          stats: dict) -> str:
        """
        Build an HTML email body with the best deals.

        WHAT: Assembles the full HTML document — header/styles, stats
        box, deals table, and footer — into one email body.
        HOW: Delegates each section to a dedicated builder
        (`_build_stats_summary_html`, `_build_deals_table_html`,
        `_build_email_footer_html`) and drops the results into the
        page shell (doctype, `<style>`, and `<h1>` title).
        WHY: Previously this method built every section inline in one
        ~140-line block. Splitting it keeps each section single-
        responsibility, independently testable, and easier to read —
        this method's job is now just "assemble the shell."

        Args:
            top_deals: The top-scored listings.
            stats: Price statistics.

        Returns:
            An HTML string for the email body.
        """
        stats_html = self._build_stats_summary_html(stats)
        deals_html = self._build_deals_table_html(top_deals)
        config_info = self._build_email_footer_html()

        # ── Full HTML ──────────────────────────────────────────
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont,
                                 'Segoe UI', Roboto, sans-serif;
                    max-width: 700px;
                    margin: 0 auto;
                    padding: 20px;
                    color: #333;
                }}
                a:hover {{ text-decoration: underline !important; }}
            </style>
        </head>
        <body>
            <h1 style="color: #333;">
                🎯 {self.config.search.product_name} Deal Alert
            </h1>
            {stats_html}
            {deals_html}
            {config_info}
        </body>
        </html>
        """

        return html
    
    def _send_email(self, top_deals: list[Listing], stats: dict):
        """
        Send an HTML email via Gmail SMTP.
        
        Requires these environment variables:
          ALERT_EMAIL_FROM    — your Gmail address
          ALERT_EMAIL_TO      — where to send the alert
          GMAIL_APP_PASSWORD  — Gmail app password (not your normal password)
        
        How to get a Gmail app password:
          1. Go to https://myaccount.google.com/security
          2. Turn on 2-Step Verification (if not already)
          3. Go to "App passwords"
          4. Generate one for "Mail" on "Mac"
          5. Copy the 16-character password
        
        Args:
            top_deals: The best deals.
            stats: Price statistics.
        """
        email_from = self.secrets.get("email_from")
        email_to = self.secrets.get("email_to")
        app_password = self.secrets.get("gmail_app_password")
        
        # Skip if email isn't configured
        if not all([email_from, email_to, app_password]):
            print("  [Notifier] Email not configured — set ALERT_EMAIL_FROM, "
                  "ALERT_EMAIL_TO, and GMAIL_APP_PASSWORD env vars.")
            return
        
        # Build the email
        product = self.config.search.product_name
        msg = MIMEMultipart("alternative")
        msg["Subject"] = (
            f"🎯 {len(top_deals)} {product} Deals Found — "
            f"Lowest: ${min(l.price_usd for l in top_deals):,.0f}"
        )
        msg["From"] = email_from
        msg["To"] = email_to

        # Plain text fallback (for email clients that don't render HTML)
        plain_text = (
            f"{product} Deals Found: {len(top_deals)} matching listings.\n"
            f"Price range: ${stats['min']:,.0f} - ${stats['max']:,.0f}\n"
            f"Median: ${stats['median']:,.0f}\n\n"
            f"Top deals:\n"
        )
        for i, l in enumerate(top_deals[:5], 1):
            plain_text += f"  {i}. ${l.price_usd:,.0f} - {l.title[:60]}...\n"
        plain_text += "\nView full list in the HTML email."
        
        msg.attach(MIMEText(plain_text, "plain"))
        msg.attach(MIMEText(self._build_email_body(top_deals, stats),
                            "html"))
        
        # Send via Gmail SMTP
        with smtplib.SMTP(self.config.alerts.email.smtp_server,
                          self.config.alerts.email.smtp_port) as server:
            server.starttls()  # Encrypt the connection
            server.login(email_from, app_password)
            server.send_message(msg)
        
        print(f"  [Notifier] Email sent to {email_to}")
    
    def _build_search_summary(self) -> str:
        """
        Build a one-line, product-aware summary for the alert footer.

        WHAT: Describes which hardware criteria this batch of deals
        was matched against (e.g. "MacBook Pro 14/16\" | Chip: M5 Max
        | 128GB" vs. "iPhone Pro Max | 1TB+").
        WHY: The old version hardcoded "MacBook Pro ..." into every
        alert, so an iPhone alert would confusingly say "MacBook Pro"
        in its footer. Search criteria differ by product (MacBook Pro
        cares about screen size/chip/RAM; iPhone cares about storage),
        so this branches on what's actually configured instead of
        assuming MacBook-shaped fields are always present.
        """
        s = self.config.search
        parts = [s.product_name]
        if s.screen_sizes:
            parts.append("/".join(str(size) for size in s.screen_sizes) + "\"")
        if s.chip_options:
            parts.append("Chip: " + "/".join(s.chip_options))
        elif s.chip:
            parts.append(f"Chip: {s.chip}")
        if s.ram_gb_primary:
            parts.append(f"{s.ram_gb_primary}GB")
        if s.storage_gb_min:
            parts.append(f"{s.storage_gb_min}GB+ storage")
        return " | ".join(parts)

    def _build_discord_messages(self, top_deals: list[Listing], stats: dict,
                                title: str, footer_text: str) -> list[list[dict]]:
        """
        Build one or more Discord messages, each a list of embed dicts.

        WHAT: Turns `top_deals` + `stats` into a list of MESSAGES (each
        message being a list of embed dicts), ready to send one
        webhook POST per message.
        HOW: Discord enforces three separate caps, and getting any one
        wrong causes the whole send to fail with a 400:
          1. 25 fields max per embed.
          2. 10 embeds max per message.
          3. 6000 characters max — NOT per embed, but summed across
             every title/field-name/field-value/footer in ALL embeds
             within one message combined. This is the one that broke
             production: pagination was originally per-embed only,
             so two embeds of ~3990 and ~2480 chars each individually
             looked fine but summed to 6470 — over Discord's combined
             6000-char message limit — and Discord rejected the whole
             message with a 400, silently dropping 40 real deals.
        So each new field is added to a running total that resets
        only when a new MESSAGE starts (not a new embed) — once
        adding a field would break any of the three caps, a new embed
        starts, and if that also means starting past 10 embeds, a new
        MESSAGE starts instead (its own fresh 6000-char budget).
        WHY: Pulled out of `_send_discord` so the pagination logic can
        be read and reasoned about separately from webhook resolution
        and the actual HTTP call(s).

        Args:
            top_deals: The best deals.
            stats: Price statistics.
            title: Embed title (already product-aware).
            footer_text: Embed footer text (already product-aware).

        Returns:
            A list of messages, each a list of embed dicts — call
            _post_to_discord once per message.
        """
        best = top_deals[0] if top_deals else None
        color = 0x00ff00 if best and best.is_great_deal else 0xffaa00

        market_snapshot_field = {
            "name": "📊 Market Snapshot",
            "value": (
                f"**{stats['count']}** listings found\n"
                f"Price range: **${stats['min']:,.0f}** – "
                f"**${stats['max']:,.0f}**\n"
                f"Median: **${stats['median']:,.0f}**"
            ),
            "inline": False,
        }

        fields = [market_snapshot_field]
        for i, listing in enumerate(top_deals):
            rank = i + 1
            emoji = "🔥" if listing.is_great_deal else "💰"
            age = format_listing_age(listing.first_seen_at)
            age_suffix = f" — {age}" if age else ""
            fields.append({
                "name": f"{emoji} #{rank} — ${listing.price_usd:,.0f} | {listing.source}",
                "value": (
                    f"[{listing.title[:80]}]({clean_url(listing.url)}) — "
                    f"Score: {listing.deal_score}/100{age_suffix}"
                ),
                "inline": False,
            })

        return self._paginate_discord_fields(fields, title, footer_text, color)

    def _build_price_drop_field(self, listing: Listing, old_price: float) -> dict:
        """
        Build the Discord embed field for one price-drop alert.

        WHAT: Renders one listing's source, old price, new price, drop
        amount/percent, title, and link.
        HOW: Mirrors the "one field per item" shape used by the
        top-deals fields in _build_discord_messages, just with
        price-drop-specific content (old → new price instead of a
        deal-score rank).

        Args:
            listing: The listing whose price just dropped (already
                holding its NEW price_usd).
            old_price: What this listing was priced at before this
                scrape.

        Returns:
            A Discord embed field dict.
        """
        drop_usd = old_price - listing.price_usd
        drop_percent = (drop_usd / old_price) * 100 if old_price else 0
        return {
            "name": (
                f"📉 {listing.source} — ${old_price:,.0f} → "
                f"${listing.price_usd:,.0f} (-{drop_percent:.0f}%)"
            ),
            "value": (
                f"[{listing.title[:80]}]({clean_url(listing.url)}) — "
                f"saved ${drop_usd:,.0f}"
            ),
            "inline": False,
        }

    def _build_price_drop_discord_messages(
        self, price_drops: list[tuple[Listing, float]],
    ) -> list[list[dict]]:
        """
        Build one or more Discord messages for a batch of price drops.

        WHAT: Turns `price_drops` into paginated MESSAGES the same way
        _build_discord_messages does for new-deal alerts — one field
        per dropped listing, same three Discord caps respected.
        HOW: Delegates the actual pagination (field/embed/message caps)
        to the same _paginate_discord_fields helper _build_discord_
        messages uses, just with price-drop title/footer/color and
        price-drop fields instead of deal-ranking fields.

        Args:
            price_drops: (listing, old_price) pairs.

        Returns:
            A list of messages, each a list of embed dicts.
        """
        product = self.config.search.product_name
        title = f"📉 {product} Price Drop Alert"
        footer_text = self._build_search_summary()
        # Blue — visually distinct from the green/orange used for
        # "new deal found" alerts, so a glance at the channel tells
        # the two alert types apart.
        color = 0x3498db

        fields = [
            self._build_price_drop_field(listing, old_price)
            for listing, old_price in price_drops
        ]

        return self._paginate_discord_fields(fields, title, footer_text, color)

    def _build_scooped_deal_field(self, listing: Listing) -> dict:
        """
        Build the Discord embed field for one scooped-deal alert.

        WHAT: Renders one listing's price, source, how fast it was
        gone (last_seen_at - first_seen_at), title, and link.
        HOW: Mirrors _build_price_drop_field's "one field per item"
        shape, just with scooped-deal-specific content (lifetime
        instead of old→new price).

        Args:
            listing: The great deal that expired fast. Expected to
                have first_seen_at and last_seen_at set (main.py's
                expire_stale_listings() only includes listings where
                both are present).

        Returns:
            A Discord embed field dict.
        """
        lifetime_hours = 0.0
        if listing.first_seen_at and listing.last_seen_at:
            lifetime_hours = (
                listing.last_seen_at - listing.first_seen_at
            ).total_seconds() / 3600

        return {
            "name": f"🏃 ${listing.price_usd:,.0f} | {listing.source} — gone in {lifetime_hours:.0f}h",
            "value": f"[{listing.title[:80]}]({clean_url(listing.url)}) — was a great deal",
            "inline": False,
        }

    def _build_scooped_deal_discord_messages(
        self, scooped: list[Listing],
    ) -> list[list[dict]]:
        """
        Build one or more Discord messages for a batch of scooped
        great deals.

        WHAT: Turns `scooped` into paginated MESSAGES the same way
        _build_price_drop_discord_messages does for price-drop
        alerts — one field per listing, same three Discord caps
        respected (see _paginate_discord_fields).

        Args:
            scooped: Great-deal listings that expired fast.

        Returns:
            A list of messages, each a list of embed dicts.
        """
        title = "🏃 Great Deal Alert — Scooped!"
        footer_text = (
            "A great deal disappeared shortly after being found — "
            "probably sold to someone else."
        )
        # Orange/red-ish — distinct from the green "new deal" and blue
        # "price drop" colors used elsewhere.
        color = 0xe74c3c

        fields = [self._build_scooped_deal_field(listing) for listing in scooped]

        return self._paginate_discord_fields(fields, title, footer_text, color)

    def _paginate_discord_fields(self, fields: list[dict], title: str,
                                  footer_text: str, color: int) -> list[list[dict]]:
        """
        Split a flat list of embed fields into Discord-safe messages.

        WHAT: Shared pagination engine used by both new-deal alerts
        (_build_discord_messages) and price-drop alerts
        (_build_price_drop_discord_messages). Discord enforces three
        separate caps, and getting any one wrong causes the whole send
        to fail with a 400:
          1. 25 fields max per embed.
          2. 10 embeds max per message.
          3. 6000 characters max — NOT per embed, but summed across
             every title/field-name/field-value/footer in ALL embeds
             within one message combined. This is the one that broke
             production: pagination was originally per-embed only, so
             two embeds of ~3990 and ~2480 chars each individually
             looked fine but summed to 6470 — over Discord's combined
             6000-char message limit — and Discord rejected the whole
             message with a 400, silently dropping 40 real deals.
        So each new field is added to a running total that resets only
        when a new MESSAGE starts (not a new embed) — once adding a
        field would break any of the three caps, a new embed starts,
        and if that also means starting past 10 embeds, a new MESSAGE
        starts instead (its own fresh 6000-char budget).

        Args:
            fields: Every embed field to place, in order (the first
                field stays first, etc).
            title: Embed title, repeated on every embed.
            footer_text: Embed footer text, repeated on every embed.
            color: Embed color (0xRRGGBB).

        Returns:
            A list of messages, each a list of embed dicts — call
            _post_to_discord once per message.
        """
        MAX_FIELDS_PER_EMBED = 25
        MAX_EMBEDS_PER_MESSAGE = 10
        # Discord's hard limit is 6000 combined per message; stay well
        # under it since our count doesn't include Discord's exact
        # JSON/markdown overhead, so leave real margin.
        MAX_CHARS_PER_MESSAGE = 5500

        def new_embed() -> dict:
            return {
                "title": title,
                "color": color,
                "fields": [],
                "footer": {"text": footer_text},
            }

        def field_chars(field: dict) -> int:
            return len(field["name"]) + len(field["value"])

        messages: list[list[dict]] = [[new_embed()]]
        message_chars = len(title) + len(footer_text)

        for field in fields:
            this_field_chars = field_chars(field)

            current_message = messages[-1]
            current_embed = current_message[-1]

            over_field_cap = len(current_embed["fields"]) >= MAX_FIELDS_PER_EMBED
            over_char_cap = message_chars + this_field_chars > MAX_CHARS_PER_MESSAGE

            if over_char_cap:
                # A new embed doesn't help — the char budget is shared
                # across the whole message — so start a fresh message
                # with its own budget.
                messages.append([new_embed()])
                message_chars = len(title) + len(footer_text)
                current_message = messages[-1]
                current_embed = current_message[-1]
            elif over_field_cap:
                if len(current_message) >= MAX_EMBEDS_PER_MESSAGE:
                    messages.append([new_embed()])
                    message_chars = len(title) + len(footer_text)
                    current_message = messages[-1]
                else:
                    # A new embed within the SAME message still repeats
                    # its own title + footer text, and Discord counts
                    # those again toward the shared 6000-char budget —
                    # this is exactly what the earlier version missed.
                    current_message.append(new_embed())
                    message_chars += len(title) + len(footer_text)
                current_embed = current_message[-1]

            current_embed["fields"].append(field)
            message_chars += this_field_chars

        return messages

    def _post_to_discord(self, webhook_url: str, payload: dict):
        """
        Send a built payload to Discord and handle the response.

        WHAT: Does the actual `requests.post` webhook call, then logs
        success/failure and triggers message-ID bookkeeping/cleanup.
        HOW: Posts JSON to `webhook_url?wait=true` (the `wait=true`
        query param makes Discord return the created message so we
        can record its ID for later cleanup). On a 200/204 response,
        stores the message ID; otherwise logs the error.
        WHY: Separated from `_send_discord` so the HTTP mechanics
        (request, status handling, cleanup trigger) are isolated from
        webhook-URL resolution and embed construction — this method's
        only job is "send this payload and handle what comes back."

        Args:
            webhook_url: The resolved Discord webhook URL to post to.
            payload: The JSON-serializable payload (username + embeds).
        """
        response = requests.post(
            webhook_url + "?wait=true",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=15,
        )

        if response.status_code in (200, 204):
            print("  [Notifier] Discord message sent ✅")
            # Store message ID for cleanup
            self._store_message_id(response)
        else:
            print(f"  [Notifier] Discord error: {response.status_code} "
                  f"{response.text[:200]}")

        # Clean up old messages
        self._cleanup_old_messages(webhook_url)

    def _send_discord(self, top_deals: list[Listing], stats: dict):
        """
        Post a deal alert to a Discord channel via webhook.

        How to create a Discord webhook:
          1. Open Discord → Server Settings → Integrations
          2. Click "Create Webhook"
          3. Name it "Apple Product Scraper Alerts"
          4. Copy the webhook URL
          5. Set it as DISCORD_WEBHOOK_URL in GitHub Secrets

        Args:
            top_deals: The best deals.
            stats: Price statistics.
        """
        # ── Environment gate ─────────────────────────────────────
        # WHY: In production (the real GitHub Actions run), we send
        # to the real DISCORD_WEBHOOK_URL exactly as always — this
        # branch is unchanged from before environment-awareness was
        # added. In dev/staging (a local test run), we must NOT post
        # to that same real, live channel. If the operator has set
        # up a separate DISCORD_WEBHOOK_URL_DEV (e.g. pointing at a
        # private test server/channel), we use that instead; if not,
        # we skip sending entirely and just log what would have
        # happened, so local testing never spams the real channel.
        if is_production():
            webhook_url = self.secrets.get("discord_webhook_url")
        else:
            dev_webhook_url = self.secrets.get("discord_webhook_url_dev")
            if not dev_webhook_url:
                print("[Notifier] Non-production environment — would "
                      "send to Discord but DISCORD_WEBHOOK_URL_DEV not "
                      "set, skipping.")
                return
            webhook_url = dev_webhook_url

        if not webhook_url:
            print("  [Notifier] Discord not configured — set "
                  "DISCORD_WEBHOOK_URL env var.")
            return

        # ── Build summary strings ───────────────────────────────
        product = self.config.search.product_name
        title = f"🎯 {product} Deal Alert"
        footer_text = self._build_search_summary()

        # ── Build the Discord embed message(s) ──────────────────
        # Usually just one message; splits into more only when the
        # deal count is large enough to exceed Discord's combined
        # 6000-char-per-message limit (see _build_discord_messages).
        messages = self._build_discord_messages(top_deals, stats, title, footer_text)

        for embeds in messages:
            payload = {
                "username": "Apple Product Scraper",
                "embeds": embeds,
            }
            self._post_to_discord(webhook_url, payload)

    def _send_discord_price_drop(self, price_drops: list[tuple[Listing, float]]):
        """
        Post a price-drop alert to a Discord channel via webhook.

        WHAT: The price-drop counterpart to _send_discord() above —
        same webhook resolution (prod vs. dev/staging gating) and same
        send-one-message-per-page loop, just building price-drop
        embeds instead of new-deal embeds.

        Args:
            price_drops: (listing, old_price) pairs.
        """
        # ── Environment gate — identical reasoning to _send_discord()
        # above: never post price-drop alerts to the real production
        # channel from a local/staging test run.
        if is_production():
            webhook_url = self.secrets.get("discord_webhook_url")
        else:
            dev_webhook_url = self.secrets.get("discord_webhook_url_dev")
            if not dev_webhook_url:
                print("[Notifier] Non-production environment — would "
                      "send price-drop alert to Discord but "
                      "DISCORD_WEBHOOK_URL_DEV not set, skipping.")
                return
            webhook_url = dev_webhook_url

        if not webhook_url:
            print("  [Notifier] Discord not configured — set "
                  "DISCORD_WEBHOOK_URL env var.")
            return

        messages = self._build_price_drop_discord_messages(price_drops)

        for embeds in messages:
            payload = {
                "username": "Apple Product Scraper",
                "embeds": embeds,
            }
            self._post_to_discord(webhook_url, payload)

    def _send_discord_scooped_deal(self, scooped: list[Listing]):
        """
        Post a scooped-great-deal alert to a Discord channel via
        webhook.

        WHAT: The scooped-deal counterpart to _send_discord() /
        _send_discord_price_drop() above — same webhook resolution
        (prod vs. dev/staging gating) and same send-one-message-per-
        page loop, just building scooped-deal embeds instead.

        Args:
            scooped: Great-deal listings that expired fast.
        """
        # ── Environment gate — identical reasoning to _send_discord()
        # above: never post to the real production channel from a
        # local/staging test run.
        if is_production():
            webhook_url = self.secrets.get("discord_webhook_url")
        else:
            dev_webhook_url = self.secrets.get("discord_webhook_url_dev")
            if not dev_webhook_url:
                print("[Notifier] Non-production environment — would "
                      "send scooped-deal alert to Discord but "
                      "DISCORD_WEBHOOK_URL_DEV not set, skipping.")
                return
            webhook_url = dev_webhook_url

        if not webhook_url:
            print("  [Notifier] Discord not configured — set "
                  "DISCORD_WEBHOOK_URL env var.")
            return

        messages = self._build_scooped_deal_discord_messages(scooped)

        for embeds in messages:
            payload = {
                "username": "Apple Product Scraper",
                "embeds": embeds,
            }
            self._post_to_discord(webhook_url, payload)

    def _store_message_id(self, response: requests.Response):
        """Save the Discord message ID for later cleanup."""
        try:
            msg = response.json()
            msg_id = msg.get("id")
            if not msg_id:
                return
            path = "data/discord_messages.json"
            messages = []
            if os.path.exists(path):
                with open(path) as f:
                    messages = json.load(f)
            messages.append({
                "id": msg_id,
                "ts": time.time(),
            })
            # Keep only last 50
            messages = messages[-50:]
            os.makedirs("data", exist_ok=True)
            with open(path, "w") as f:
                json.dump(messages, f)
        except Exception:
            pass
    
    def _cleanup_old_messages(self, webhook_url: str):
        """Delete Discord messages older than 48 hours."""
        path = "data/discord_messages.json"
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                messages = json.load(f)
            cutoff = time.time() - 48 * 3600
            remaining = []
            for msg in messages:
                if msg["ts"] < cutoff:
                    # Delete old message
                    delete_url = f"{webhook_url}/messages/{msg['id']}"
                    try:
                        requests.delete(delete_url, timeout=10)
                    except Exception:
                        pass
                else:
                    remaining.append(msg)
            with open(path, "w") as f:
                json.dump(remaining, f)
        except Exception:
            pass
