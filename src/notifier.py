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
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import requests

from database import Listing
from config import Config


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
    
    def _build_email_body(self, top_deals: list[Listing],
                          stats: dict) -> str:
        """
        Build an HTML email body with the best deals.
        
        Args:
            top_deals: The top-scored listings.
            stats: Price statistics.
        
        Returns:
            An HTML string for the email body.
        """
        # ── Stats section ──────────────────────────────────────
        stats_html = f"""
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
        
        # ── Deals list ─────────────────────────────────────────
        deals_rows = ""
        for i, listing in enumerate(top_deals, 1):
            # Emoji for deal quality
            if listing.is_great_deal:
                emoji = "🔥"  # Fire = great deal
            elif listing.deal_score and listing.deal_score >= 60:
                emoji = "💰"  # Money = good deal
            else:
                emoji = "👀"  # Eyes = worth a look
            
            condition = listing.condition or "N/A"
            ram = f"{listing.ram_gb}GB" if listing.ram_gb else "?"
            
            deals_rows += f"""
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
        
        deals_html = f"""
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
        
        # ── Config info ────────────────────────────────────────
        sizes_str = "/".join(str(s) for s in self.config.search.screen_sizes)
        chip_str = self.config.search.chip or "any chip"
        ram_str = f"{self.config.search.ram_gb_primary}GB" if self.config.search.ram_gb_primary else "any RAM"
        config_info = f"""
        <p style="color: #999; font-size: 12px; margin-top: 30px;">
            Searching for: {self.config.search.product_name} 
            {sizes_str}" | Chip: {chip_str} |
            RAM: {ram_str} |
            Max price: ${self.config.price.absolute_max_usd:,.0f}
        </p>
        """
        
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
                🎯 MacBook Pro Deal Alert
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
        msg = MIMEMultipart("alternative")
        msg["Subject"] = (
            f"🎯 {len(top_deals)} MacBook Pro Deals Found — "
            f"Lowest: ${min(l.price_usd for l in top_deals):,.0f}"
        )
        msg["From"] = email_from
        msg["To"] = email_to
        
        # Plain text fallback (for email clients that don't render HTML)
        plain_text = (
            f"MacBook Pro Deals Found: {len(top_deals)} matching listings.\n"
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
    
    def _send_discord(self, top_deals: list[Listing], stats: dict):
        """
        Post a deal alert to a Discord channel via webhook.
        
        How to create a Discord webhook:
          1. Open Discord → Server Settings → Integrations
          2. Click "Create Webhook"
          3. Name it "Mac Deal Alerts"
          4. Copy the webhook URL
          5. Set it as DISCORD_WEBHOOK_URL in GitHub Secrets
        
        Args:
            top_deals: The best deals.
            stats: Price statistics.
        """
        webhook_url = self.secrets.get("discord_webhook_url")
        
        if not webhook_url:
            print("  [Notifier] Discord not configured — set "
                  "DISCORD_WEBHOOK_URL env var.")
            return
        
        # ── Build summary strings ───────────────────────────────
        sizes_str = "/".join(str(s) for s in self.config.search.screen_sizes)
        chip_str = self.config.search.chip or "any chip"
        ram_str = f"{self.config.search.ram_gb_primary}GB" if self.config.search.ram_gb_primary else "any RAM"
        
        # ── Build the Discord embed message ─────────────────────
        # Discord uses "embeds" for rich formatting.
        
        best = top_deals[0] if top_deals else None
        
        embed = {
            "title": "🎯 MacBook Pro Deal Alert",
            "color": 0x00ff00 if best and best.is_great_deal else 0xffaa00,
            "fields": [
                {
                    "name": "📊 Market Snapshot",
                    "value": (
                        f"**{stats['count']}** listings found\n"
                        f"Price range: **${stats['min']:,.0f}** – "
                        f"**${stats['max']:,.0f}**\n"
                        f"Median: **${stats['median']:,.0f}**"
                    ),
                    "inline": False,
                }
            ],
            "footer": {
                "text": f"MacBook Pro {sizes_str}\" | Chip: {chip_str} | {ram_str}"
            },
            "timestamp": self.config.secrets.get("timestamp", ""),
        }
        
        # Add top deals as fields (Discord allows up to 25 fields, but embed size limit is 6000 chars)
        for i, listing in enumerate(top_deals[:5], 1):
            emoji = "🔥" if listing.is_great_deal else "💰"
            ram = f"{listing.ram_gb}GB" if listing.ram_gb else "?"
            
            embed["fields"].append({
                "name": (
                    f"{emoji} #{i} — ${listing.price_usd:,.0f} "
                    f"| {listing.source}"
                ),
                "value": (
                    f"[{listing.title[:80]}]({listing.url})\n"
                    f"Score: {listing.deal_score}/100"
                ),
                "inline": False,
            })
        
        # Build the payload
        payload = {
            "username": "Mac Deal Scraper",
            "avatar_url": (
                "https://cdn3.emoji.gg/emojis/4013-macbook.png"
            ),
            "embeds": [embed],
        }
        
        # Send to Discord
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
