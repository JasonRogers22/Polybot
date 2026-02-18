"""
Gamma API client for Polymarket 15-minute markets.

Verified against live API on 2026-02-16.

CONFIRMED facts from live API response:
- Endpoint: GET https://gamma-api.polymarket.com/events?order=id&ascending=false&closed=false&limit=100
- The first results ARE the 15-minute markets (highest IDs = newest = BTC/ETH/SOL/XRP 15m)
- Event slug format:  btc-updown-15m-{unix_timestamp}
- Market data is EMBEDDED inside event["markets"][0] - no second API call needed
- clobTokenIds is inside markets[0] as a JSON string e.g. '["123...", "456..."]'
- Tag ID for 15M markets: 102467 (label: "15M")
- Series slugs: btc-up-or-down-15m, eth-up-or-down-15m, sol-up-or-down-15m, xrp-up-or-down-15m
"""
import json
import aiohttp
from typing import Optional, Dict, List
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"

# Verified tag ID for 15-minute crypto markets (from live API)
TAG_15M = "102467"

# Verified series slugs per coin (from live API)
SERIES_SLUGS = {
    "BTC": "btc-up-or-down-15m",
    "ETH": "eth-up-or-down-15m",
    "SOL": "sol-up-or-down-15m",
    "XRP": "xrp-up-or-down-15m",
}

# Verified event slug prefixes per coin (from live API)
EVENT_SLUG_PREFIXES = {
    "BTC": "btc-updown-15m-",
    "ETH": "eth-updown-15m-",
    "SOL": "sol-updown-15m-",
    "XRP": "xrp-updown-15m-",
}


class GammaClient:

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def get_current_15m_market(self, coin: str) -> Optional[Dict]:
        """
        Fetch the current active 15-minute market for a coin.

        Uses the verified approach:
          GET /events?order=id&ascending=false&closed=false&tag_id=102467&limit=20
        This returns only 15M crypto events, newest first.
        The BTC/ETH/SOL/XRP events are always at the top of this list.
        Market data including clobTokenIds is embedded in event["markets"][0].
        """
        if not self.session:
            self.session = aiohttp.ClientSession()

        coin = coin.upper()
        slug_prefix = EVENT_SLUG_PREFIXES.get(coin)
        if not slug_prefix:
            logger.error(f"Unknown coin: {coin}")
            return None

        try:
            url = f"{GAMMA_BASE}/events"
            params = {
                "order": "id",
                "ascending": "false",
                "closed": "false",
                "tag_id": TAG_15M,   # ID 102467 = "15M" tag - verified from live API
                "limit": "20",
            }
            async with self.session.get(url, params=params) as resp:
                logger.info(f"Gamma /events?tag_id={TAG_15M} status: {resp.status}")
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"API error: {text[:200]}")
                    return None

                events = await resp.json()

            if not isinstance(events, list):
                logger.error(f"Unexpected response type: {type(events)}")
                return None

            logger.info(f"Got {len(events)} 15M events. Slugs: {[e.get('slug','')[:30] for e in events[:6]]}")

            now = datetime.now(timezone.utc)
            for event in events:
                slug = event.get("slug", "")

                # Match coin by slug prefix
                if not slug.startswith(slug_prefix):
                    continue

                # Confirm still active and not yet ended
                end_date = event.get("endDate") or event.get("end_date") or ""
                if end_date:
                    try:
                        end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                        if end_dt < now:
                            logger.info(f"Skipping expired market: {slug} ended {end_date}")
                            continue
                    except Exception:
                        pass

                # Market data is embedded - extract it directly
                markets = event.get("markets", [])
                if not markets:
                    logger.warning(f"Event {slug} has no embedded markets")
                    continue

                market = markets[0]

                # Parse clobTokenIds from JSON string to list
                clob_raw = market.get("clobTokenIds", "[]")
                try:
                    token_ids = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw
                except Exception:
                    token_ids = []

                result = {
                    "question":     market.get("question"),
                    "condition_id": market.get("conditionId"),
                    "slug":         slug,
                    "end_date":     end_date,
                    "outcomes":     json.loads(market.get("outcomes", '["Up","Down"]')),
                    "token_ids": {
                        "yes": token_ids[0] if len(token_ids) > 0 else None,  # "Up"
                        "no":  token_ids[1] if len(token_ids) > 1 else None,  # "Down"
                    },
                    "clob_token_ids": token_ids,
                    "accepting_orders": market.get("acceptingOrders", True),
                    "fees_enabled": market.get("feesEnabled", False),
                    "_event": event,
                }

                yes_token = result['token_ids'].get('yes')
                no_token = result['token_ids'].get('no')
                yes_token_preview = str(yes_token or 'None')[:12]
                no_token_preview = str(no_token or 'None')[:12]

                logger.info(
                    f"[OK] Found {coin} 15m market: {result['question']} | "
                    f"conditionId: {result['condition_id']} | "
                    f"YES token: {yes_token_preview}... | "
                    f"NO token: {no_token_preview}..."
                )
                return result

            logger.warning(f"No active {coin} 15m market found in {len(events)} results")
            return None

        except Exception as e:
            logger.error(f"Error fetching {coin} 15m market: {e}", exc_info=True)
            return None


    async def discover_market(
        self,
        asset: str,
        keyword: str,
        window_minutes: int = 15,
        min_liquidity: float = 0.0,
        min_volume: float = 0.0,
        search_limit: int = 100,
    ) -> Optional[Dict]:
        """
        Generic market discovery using Gamma /events.

        This scans the newest active events and returns the best matching market by:
          - question contains `asset` and `keyword`
          - (if start/end present) duration is closest to `window_minutes`
          - (if numeric liquidity/volume present) meets minimums
        """
        if not self.session:
            self.session = aiohttp.ClientSession()

        asset_u = asset.upper()
        keyword_u = keyword.upper()

        try:
            url = f"{GAMMA_BASE}/events"
            params = {
                "order": "id",
                "ascending": "false",
                "closed": "false",
                "limit": str(min(max(search_limit, 20), 200)),
            }
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"Gamma API error: {resp.status} {text[:200]}")
                    return None
                events = await resp.json()

            if not isinstance(events, list):
                return None

            now = datetime.now(timezone.utc)
            best = None
            best_score = -1

            for event in events:
                markets = event.get("markets", []) or []
                if not markets:
                    continue
                for market in markets:
                    q = (market.get("question") or "").strip()
                    if not q:
                        continue
                    q_u = q.upper()
                    if asset_u not in q_u or keyword_u not in q_u:
                        continue

                    # active check if endDate exists
                    end_date = event.get("endDate") or event.get("end_date") or ""
                    if end_date:
                        try:
                            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00")).astimezone(timezone.utc)
                            if end_dt < now:
                                continue
                        except Exception:
                            pass

                    # token ids
                    clob_raw = market.get("clobTokenIds", "[]")
                    try:
                        token_ids = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw
                    except Exception:
                        token_ids = []
                    if not (isinstance(token_ids, list) and len(token_ids) >= 2):
                        continue

                    # liquidity/volume parse
                    def _to_float(x):
                        try:
                            return float(x)
                        except Exception:
                            return None

                    liq = _to_float(market.get("liquidity"))
                    vol = _to_float(market.get("volume"))
                    if liq is not None and liq < min_liquidity:
                        continue
                    if vol is not None and vol < min_volume:
                        continue

                    score = 0
                    score += 50  # base match

                    # duration score if start/end
                    start_date = event.get("startDate") or event.get("start_date") or ""
                    if start_date and end_date:
                        try:
                            st = datetime.fromisoformat(start_date.replace("Z", "+00:00")).astimezone(timezone.utc)
                            en = datetime.fromisoformat(end_date.replace("Z", "+00:00")).astimezone(timezone.utc)
                            dur = (en - st).total_seconds() / 60
                            score += max(0, 30 - abs(dur - window_minutes) * 3)
                        except Exception:
                            pass

                    if liq is not None:
                        score += min(10, int(liq / 1000))
                    if vol is not None:
                        score += min(10, int(vol / 5000))

                    if score > best_score:
                        best_score = score
                        best = {
                            "question":     q,
                            "condition_id": market.get("conditionId"),
                            "slug":         event.get("slug", ""),
                            "end_date":     end_date,
                            "outcomes":     json.loads(market.get("outcomes", '["Yes","No"]')),
                            "token_ids": {
                                "yes": token_ids[0],
                                "no":  token_ids[1],
                            },
                            "clob_token_ids": token_ids,
                            "accepting_orders": market.get("acceptingOrders", True),
                            "fees_enabled": market.get("feesEnabled", False),
                            "_event": event,
                        }

            if best:
                logger.info(f"[OK] Discovered market: {best['question']} (score={best_score})")
            return best

        except Exception as e:
            logger.error(f"Error discovering market: {e}", exc_info=True)
            return None

    async def get_all_15m_markets(self) -> List[Dict]:
        """Fetch all active 15-minute markets for BTC, ETH, SOL, XRP in one API call."""
        if not self.session:
            self.session = aiohttp.ClientSession()

        try:
            url = f"{GAMMA_BASE}/events"
            params = {
                "order": "id",
                "ascending": "false",
                "closed": "false",
                "tag_id": TAG_15M,
                "limit": "20",
            }
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                events = await resp.json()

            now = datetime.now(timezone.utc)
            results = []

            for coin, slug_prefix in EVENT_SLUG_PREFIXES.items():
                for event in events:
                    slug = event.get("slug", "")
                    if not slug.startswith(slug_prefix):
                        continue
                    end_date = event.get("endDate", "")
                    if end_date:
                        try:
                            if datetime.fromisoformat(end_date.replace("Z", "+00:00")) < now:
                                continue
                        except Exception:
                            pass
                    markets = event.get("markets", [])
                    if markets:
                        market = markets[0]
                        clob_raw = market.get("clobTokenIds", "[]")
                        token_ids = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw
                        results.append({
                            "coin": coin,
                            "question": market.get("question"),
                            "condition_id": market.get("conditionId"),
                            "slug": slug,
                            "token_ids": {
                                "yes": token_ids[0] if len(token_ids) > 0 else None,
                                "no":  token_ids[1] if len(token_ids) > 1 else None,
                            },
                            "_event": event,
                        })
                    break  # Only need the most recent per coin

            logger.info(f"Found {len(results)} active 15m markets: {[r['coin'] for r in results]}")
            return results

        except Exception as e:
            logger.error(f"Error fetching all 15m markets: {e}")
            return []

    async def get_market_by_condition(self, condition_id: str) -> Optional[Dict]:
        """Get market details by condition ID."""
        if not self.session:
            self.session = aiohttp.ClientSession()
        try:
            async with self.session.get(f"{GAMMA_BASE}/markets/{condition_id}") as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            logger.error(f"Error fetching market {condition_id}: {e}")
        return None
