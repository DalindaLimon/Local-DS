# Personalization

How likes and dislikes change what you see. Code: [app/personalization.py](../app/personalization.py) (math and
reactions), [app/api_feed.py](../app/api_feed.py) (`_foryou_order`, `reels_order`, `Ctx`), and
[app/discovery.py](../app/discovery.py) (suggestions).

**Principles**

- Everything is **per user**. Your reactions never change your friend's ordering.
- Reactions are stored as rows (`reactions` table). Every weight can be **recomputed from those rows** at any time.
- Weights only change **ordering**. They never hide items (except Mute) and never affect what gets downloaded.
- Nothing is sent to any outside service.

---

## Source weight

Each (user, source) pair has a weight, default **1.0**.

```
score  = Σ over the user's reactions on that source, made after reset_at:
           (+1 for a like | −DISLIKE_FACTOR for a dislike) × 0.5 ^ (age_days / REACTION_HALFLIFE_DAYS)

weight = LIKE_BASE ^ score
weight = weight × BOOST_MULTIPLIER        if the user boosted the source
weight = MIN_WEIGHT                        if the user muted the source (and the source is hidden for them)
weight = clamp(weight, MIN_WEIGHT, MAX_WEIGHT)
```

Functions: `compute_score()`, `weight_from_score()`, `recompute_weight()`.

With the defaults (`LIKE_BASE=1.25`, `DISLIKE_FACTOR=0.8`, `REACTION_HALFLIFE_DAYS=30`, `MIN_WEIGHT=0.1`,
`MAX_WEIGHT=5`):

| Your history with a source | score | weight |
|---|---|---|
| nothing yet | 0 | 1.00× |
| 1 like | 1 | 1.25× |
| 3 likes | 3 | 1.95× |
| 1 dislike | −0.8 | 0.84× |
| 5 dislikes | −4 | 0.41× |
| 3 likes, 60 days ago | 0.75 | 1.18× |
| 3 likes, then boosted | 3 | 3.91× |
| ~7+ net likes / ~13+ net dislikes | | capped at 5.0× / 0.1× |

**When is it recomputed?**

- Immediately on every reaction (`react()` → `recompute_weight()` for that user and source).
- On Boost/Mute/Reset (`set_manual()`, `reset_source()`).
- Nightly at 03:30 for every pair (`recompute_all()`), so old reactions keep fading even without new activity.
- When a user post is deleted, for every user who had reacted to it.

The result is cached in `user_source_prefs.weight` / `.score`.

**Reset** sets `reset_at = now`. Older reactions stay in the database but no longer count for that user.

**Where reactions point:** a reaction stores the item's `source_id` at the time of reacting. Reactions on items
of user posts point to the author's `kind='user'` source, so liking someone's posts makes you see more of their
posts.

## "Why" lines

`why_line()` explains the weight in plain words:

- *Exploring: a random pick so your feed doesn't become a bubble* (placed by exploration)
- *Source weight 2.5x (you boosted this source)*
- *Source weight 1.6x because you liked 3 of its posts and disliked 1*
- *New source for you (weight 1.0x)*

The Sources page also shows each source's **share of your feed**: its weight divided by the sum of weights of all
enabled, unmuted sources (`share_of_feed()`).

## For you feed

`GET /api/feed?mode=foryou` (`_foryou_order` in `api_feed.py`):

1. Take items from enabled, unmuted, feed-enabled sources published within `FORYOU_WINDOW_DAYS` (21) of the
   snapshot time (newest 4000 at most).
2. Score each: `score = weight(source) × 0.5 ^ (age_hours / FORYOU_HALFLIFE_HOURS)` (`foryou_score()`).
   With a 24 h half-life, a post from a 2× source that is one day old ranks equal to a brand-new post from a 1×
   source.
3. Sort by score (ties: newer id first).
4. Mix in exploration (below).
5. Cache the resulting id list in memory under `(user, snapshot time, seed, source filter)`, max 32 entries.

The **cursor** carries the snapshot time `t`, the random seed `sd` and the offset `o`. So while you scroll, the
order stays fixed (no repeats or skips), even if new posts arrive or weights change. Pulling to refresh starts a
new snapshot. Reacting drops your cached orders, so the next refresh reflects the new weight.

**Latest** mode ignores weights: newest first (`published_at DESC, id DESC`, keyset pagination).

Both modes exclude sources that are disabled, have `rss_enabled=0`, or that you muted. Disliked posts are **not**
excluded. With *Unread* on, items in `seen` are skipped.

## Reels order

`reels_order()` in `api_feed.py`, called by `POST /api/reels/next`:

1. All `available` Shorts from enabled, unmuted sources, minus the ones the client already has (`exclude`).
2. Split into **unseen** first, then **seen**.
3. Each group is ordered by a **weighted random shuffle** (`weighted_shuffle()`, Efraimidis–Spirakis):
   every Short gets `key = random() ^ (1 / weight)` and keys are sorted descending. A 2× source isn't always
   first, but it tends to come earlier, roughly twice as often.
4. Exploration is mixed into each group.
5. When everything has been shown, the client gets a fresh shuffle of everything with `reset: true`, so Reels
   never dead-ends.

## Exploration

`mix_exploration(ordered, EXPLORE_PERCENT, rng)` walks through the ordered list. For each slot, with probability
`EXPLORE_PERCENT / 100` it takes the next item from a **uniformly shuffled** copy instead of the next item in weight
order. Every item still appears exactly once. An item is flagged `explored` only when it actually jumped ahead of
its weighted position. This lets low-weight sources win you back. Set `EXPLORE_PERCENT=0` to turn it off.

## Discover suggestions

`discovery.suggested()` ranks entries of the curated `STARTER` list that you don't have yet:

```
affinity[topic] = Σ over existing sources with that topic:  0.5 + ln(your weight)   (−1.5 if you muted it)
                + Σ over your last 500 reactions whose title matches the topic:  +0.3 like / −0.25 dislike
candidate score = average affinity of its topics
                + 0.5 × (how often words of its name appear in titles you liked, max 3 per word)
```

Topics of a title are guessed with a keyword table (`guess_topics()`).

## Tuning

All constants are environment variables ([CONFIGURATION.md](CONFIGURATION.md#personalization)). Typical tweaks:

| Want | Change |
|---|---|
| Likes should matter more | `LIKE_BASE=1.4` |
| Dislikes should matter as much as likes | `DISLIKE_FACTOR=1.0` |
| Taste should change faster | `REACTION_HALFLIFE_DAYS=14` |
| For you should prefer fresh posts more | `FORYOU_HALFLIFE_HOURS=12` |
| Less randomness | `EXPLORE_PERCENT=5` |

After changing the formula in code, keep this page and the tests in `tests/test_personalization.py` in sync.
