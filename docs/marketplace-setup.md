# Setting up login-gated marketplaces (like Facebook Marketplace)

This guide is for marketplaces that this project can't search *at all*
without being logged in — right now that's just Facebook Marketplace.
It's written assuming you've never done anything like this before, so
it starts from the basics.

If you just want the short version: **you don't need to do any of
this to use the scraper.** Facebook Marketplace is `enabled: false` in
`config.yaml` and will stay off (and silent) until you deliberately
set it up. Everything below is for when you're ready.

## Why does Facebook need this but eBay/Swappa/Mercari don't?

Most of the marketplaces this scraper already supports (eBay, Swappa,
Mercari, OfferUp, Back Market, Best Buy, Newegg, Gazelle, Apple
Refurbished) let anyone — even a logged-out visitor, even a script —
view their search results pages. That's why those scrapers can just
send a normal web request to a search URL and get real results back.

Facebook Marketplace is different: if you're not logged into a
Facebook account in your browser, and you try to view a Marketplace
search page, Facebook shows you a login screen instead of results.
There's no "logged out" version of Marketplace search to scrape.

So for the scraper to see Facebook Marketplace results, it needs to
make its requests *look like* they're coming from a browser where
you're already logged in. That's what a "session cookie" is for.

## What is a "session cookie," in plain terms?

When you log into a website like Facebook, the website doesn't ask you
to type your password again on every single page you visit — that
would be exremely annoying. Instead, after you log in once, Facebook
gives your browser a small piece of data called a **cookie**, and your
browser automatically shows that cookie to Facebook on every
subsequent request. Facebook checks the cookie and effectively says
"oh, I recognize this — you're logged in as [you]," without asking for
your password again.

A **session cookie** is the specific cookie that represents "this
browser is currently logged in." If you copy that cookie's value out
of your own logged-in browser and hand it to a script, the script can
include that same cookie on its own requests — and from Facebook's
point of view, those requests look like they're coming from your
already-logged-in browser too.

A few important things to understand about this:

- **A session cookie is almost as sensitive as your password.**
  Anyone who has it can act as if they're logged into your account
  (until it expires or you log out). Never paste it into a public
  place, a GitHub commit, or share it with anyone you don't trust.
  This project stores it as an environment variable / GitHub Secret
  specifically so it never ends up in the code or in `config.yaml`
  (which does get committed to the repo).
- **It's not your password**, and getting it doesn't require giving
  the scraper your Facebook password. Your password never leaves
  Facebook's login page.
- **It expires.** Depending on Facebook's settings, a session cookie
  might stop working after some weeks or if you log out elsewhere. If
  the scraper's Facebook results suddenly stop working, a good first
  guess is "the cookie expired, I need a fresh one."

## The general idea of how you'd get one

You won't do this by typing a command — you'll use your web browser's
built-in **developer tools**, which let you peek at things the browser
normally hides from you, including cookies. In broad strokes:

1. Open your browser and log into Facebook normally, the way you
   always do.
2. Open developer tools. In most browsers this is right-click
   anywhere on the page → "Inspect" (or a similar option), which opens
   a panel usually docked to the side or bottom of the window.
3. Inside developer tools, look for a tab named something like
   **"Application"** (Chrome/Edge) or **"Storage"** (Firefox/Safari).
   This is where the browser lists cookies it's storing for the site
   you're on.
4. Find the list of cookies for `facebook.com`. You'll see a table of
   cookie names and values — this can look intimidating (there are
   often dozens), but you're looking for one specific one that
   represents your logged-in session.
5. Copy that cookie's **value** (a long string of letters/numbers) —
   not the whole row, just the value.
6. That value is what gets set as the `FACEBOOK_SESSION_COOKIE`
   environment variable (locally in a `.env` file, or as a GitHub
   Secret for the automated cron runs) — the same pattern this project
   already uses for things like `DISCORD_WEBHOOK_URL`.

That's the general shape of it. I'm deliberately **not** giving you
exact click-by-click steps with exact menu names here, because
browsers change their UI over time and I don't want to hand you
instructions that turn out to be stale or slightly wrong for whatever
version you're running.

**When you're actually ready to set this up: just ask Claude to walk
you through the current exact steps for your specific browser.**
Claude can look at what browser and version you're using and give you
precise, up-to-date, click-by-click instructions — and can also help
you decide where to safely store the cookie value once you have it
(`.env` file locally, GitHub Secrets for the automated runs) and
double check you haven't accidentally pasted it anywhere it shouldn't
be, like a commit or a chat log.

## What happens once it's set up

Once `FACEBOOK_SESSION_COOKIE` is set, `src/scrapers/facebook.py` will
still need its actual fetch/parse logic filled in (right now it's a
stub with a `# TODO` outline) before it can return real listings — and
`facebook.enabled` in `config.yaml` needs to be flipped to `true`. Both
of those are intentionally left for later, once the credential side of
things is sorted out and can be tested against the real site.
