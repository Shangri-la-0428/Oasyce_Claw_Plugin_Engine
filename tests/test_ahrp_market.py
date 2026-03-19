"""Tests for AHRP Task Market — competitive bidding."""

from __future__ import annotations
import pytest
from oasyce.ahrp import (
    AgentIdentity,
    AnnouncePayload,
    Capability,
    ConfirmPayload,
    DeliverPayload,
    Need,
    OfferPayload,
    RequestPayload,
    TxState,
)
from oasyce.ahrp.executor import AHRPExecutor
from oasyce.ahrp.router import Router
from oasyce.ahrp.market import TaskMarket, score_bid, Bid


def _announce(executor, router, agent_id, tags, price, origin="human", rep=50.0, stake=1000.0):
    payload = AnnouncePayload(
        identity=AgentIdentity(
            agent_id=agent_id, public_key=f"pk-{agent_id}", reputation=rep, stake=stake
        ),
        capabilities=[
            Capability(
                capability_id=f"cap-{agent_id}",
                tags=tags,
                price_floor=price,
                origin_type=origin,
                access_levels=["L0", "L1"],
            )
        ],
        endpoints=[f"https://{agent_id}.example.com"],
    )
    executor.handle_announce(payload)
    router.announce(payload)


@pytest.fixture
def market():
    executor = AHRPExecutor(require_signature=False)
    router = Router()
    # Register 4 providers with different profiles
    _announce(executor, router, "alice", ["finance"], 1.0, "human", rep=80.0, stake=5000.0)
    _announce(executor, router, "bob", ["finance", "SEC"], 2.0, "human", rep=90.0, stake=10000.0)
    _announce(executor, router, "carol", ["finance"], 0.5, "synthetic", rep=60.0, stake=500.0)
    _announce(
        executor, router, "dave", ["finance", "crypto"], 3.0, "sensor", rep=70.0, stake=8000.0
    )
    # Register buyer
    _announce(executor, router, "buyer", ["NLP"], 0.0, "curated", rep=50.0, stake=2000.0)
    return TaskMarket(router, executor)


class TestScoreFormula:
    def test_basic_score(self):
        offer = OfferPayload(request_id="r", capability_id="c", price_oas=1.0, offer_id="o")
        bid = Bid(offer=offer, provider_id="a", reputation=80.0, stake=5000.0, origin_type="human")
        score = score_bid(bid, budget=10.0)
        assert score > 0

    def test_lower_price_higher_score(self):
        offer_cheap = OfferPayload(request_id="r", capability_id="c", price_oas=1.0, offer_id="o1")
        offer_expensive = OfferPayload(
            request_id="r", capability_id="c", price_oas=5.0, offer_id="o2"
        )
        bid_cheap = Bid(offer=offer_cheap, provider_id="a", reputation=80.0, stake=5000.0)
        bid_expensive = Bid(offer=offer_expensive, provider_id="b", reputation=80.0, stake=5000.0)
        assert score_bid(bid_cheap, 10.0) > score_bid(bid_expensive, 10.0)

    def test_higher_rep_higher_score(self):
        offer = OfferPayload(request_id="r", capability_id="c", price_oas=2.0, offer_id="o")
        bid_high = Bid(offer=offer, provider_id="a", reputation=90.0, stake=5000.0)
        bid_low = Bid(offer=offer, provider_id="b", reputation=30.0, stake=5000.0)
        assert score_bid(bid_high, 10.0) > score_bid(bid_low, 10.0)

    def test_higher_stake_higher_score(self):
        offer = OfferPayload(request_id="r", capability_id="c", price_oas=2.0, offer_id="o")
        bid_staked = Bid(offer=offer, provider_id="a", reputation=80.0, stake=10000.0)
        bid_unstaked = Bid(offer=offer, provider_id="b", reputation=80.0, stake=100.0)
        assert score_bid(bid_staked, 10.0) > score_bid(bid_unstaked, 10.0)

    def test_human_beats_synthetic(self):
        offer = OfferPayload(request_id="r", capability_id="c", price_oas=2.0, offer_id="o")
        bid_human = Bid(
            offer=offer, provider_id="a", reputation=80.0, stake=5000.0, origin_type="human"
        )
        bid_synth = Bid(
            offer=offer, provider_id="b", reputation=80.0, stake=5000.0, origin_type="synthetic"
        )
        assert score_bid(bid_human, 10.0) > score_bid(bid_synth, 10.0)

    def test_over_budget_rejected(self):
        offer = OfferPayload(request_id="r", capability_id="c", price_oas=15.0, offer_id="o")
        bid = Bid(offer=offer, provider_id="a", reputation=80.0, stake=5000.0)
        assert score_bid(bid, budget=10.0) == 0.0

    def test_zero_price_rejected(self):
        offer = OfferPayload(request_id="r", capability_id="c", price_oas=0.0, offer_id="o")
        bid = Bid(offer=offer, provider_id="a", reputation=80.0, stake=5000.0)
        assert score_bid(bid, budget=10.0) == 0.0


class TestAuction:
    def test_create_auction(self, market):
        req = RequestPayload(
            need=Need(description="finance", tags=["finance"]),
            budget_oas=10.0,
            request_id="auction-001",
        )
        auction = market.create_auction(req, "buyer")
        assert auction.budget_oas == 10.0
        assert not auction.closed

    def test_submit_bids(self, market):
        req = RequestPayload(
            need=Need(description="finance", tags=["finance"]),
            budget_oas=10.0,
            request_id="auction-002",
        )
        market.create_auction(req, "buyer")

        # Three providers bid
        for i, (provider, price) in enumerate([("alice", 3.0), ("bob", 4.0), ("carol", 1.5)]):
            bid = market.submit_bid(
                "auction-002",
                OfferPayload(
                    request_id="auction-002",
                    capability_id=f"cap-{provider}",
                    price_oas=price,
                    offer_id=f"off-{i}",
                ),
                provider,
            )
            assert bid.score > 0

        assert len(market.auctions["auction-002"].bids) == 3

    def test_winner_selection(self, market):
        req = RequestPayload(
            need=Need(description="finance", tags=["finance"]),
            budget_oas=10.0,
            request_id="auction-003",
        )
        market.create_auction(req, "buyer")

        # Bob: high rep (90), high stake (10000), price 4.0, human
        market.submit_bid(
            "auction-003",
            OfferPayload(
                request_id="auction-003",
                capability_id="cap-bob",
                price_oas=4.0,
                offer_id="off-bob",
            ),
            "bob",
        )

        # Carol: low rep (60), low stake (500), price 1.5, synthetic
        market.submit_bid(
            "auction-003",
            OfferPayload(
                request_id="auction-003",
                capability_id="cap-carol",
                price_oas=1.5,
                offer_id="off-carol",
            ),
            "carol",
        )

        # Alice: good rep (80), medium stake (5000), price 3.0, human
        market.submit_bid(
            "auction-003",
            OfferPayload(
                request_id="auction-003",
                capability_id="cap-alice",
                price_oas=3.0,
                offer_id="off-alice",
            ),
            "alice",
        )

        winner = market.close_auction("auction-003")
        assert winner is not None
        # Bob or Alice should win (high rep + stake + human), not Carol (synthetic)
        assert winner.provider_id in ("alice", "bob")

    def test_no_bids_no_winner(self, market):
        req = RequestPayload(
            need=Need(description="niche", tags=["niche"]),
            budget_oas=10.0,
            request_id="auction-empty",
        )
        market.create_auction(req, "buyer")
        winner = market.close_auction("auction-empty")
        assert winner is None

    def test_reputation_filter(self, market):
        req = RequestPayload(
            need=Need(description="finance", tags=["finance"], min_reputation=85.0),
            budget_oas=10.0,
            request_id="auction-rep",
        )
        market.create_auction(req, "buyer")

        # Alice has rep 80, below min 85 → rejected
        with pytest.raises(ValueError, match="below minimum"):
            market.submit_bid(
                "auction-rep",
                OfferPayload(
                    request_id="auction-rep",
                    capability_id="cap-alice",
                    price_oas=3.0,
                    offer_id="off-alice",
                ),
                "alice",
            )

        # Bob has rep 90 → accepted
        bid = market.submit_bid(
            "auction-rep",
            OfferPayload(
                request_id="auction-rep",
                capability_id="cap-bob",
                price_oas=4.0,
                offer_id="off-bob",
            ),
            "bob",
        )
        assert bid.score > 0


class TestFullAuctionLifecycle:
    def test_auction_to_settlement(self, market):
        """Full lifecycle: create → bid → close → execute → deliver → confirm."""
        req = RequestPayload(
            need=Need(description="on-chain analysis", tags=["finance", "crypto"]),
            budget_oas=10.0,
            request_id="full-001",
        )
        market.create_auction(req, "buyer")

        # Two providers bid
        market.submit_bid(
            "full-001",
            OfferPayload(
                request_id="full-001",
                capability_id="cap-alice",
                price_oas=2.0,
                offer_id="off-a",
            ),
            "alice",
        )
        market.submit_bid(
            "full-001",
            OfferPayload(
                request_id="full-001",
                capability_id="cap-dave",
                price_oas=5.0,
                offer_id="off-d",
            ),
            "dave",
        )

        # Close and select winner
        winner = market.close_auction("full-001")
        assert winner is not None

        # Execute winner → escrow locked
        tx = market.execute_winner("full-001")
        assert tx.state == TxState.ACCEPTED

        # Deliver
        tx = market.executor.handle_deliver(
            tx.tx_id,
            DeliverPayload(
                offer_id=winner.offer.offer_id,
                content_hash="sha256:analysis-result",
                content_ref="ipfs://QmResult",
            ),
        )
        assert tx.state == TxState.DELIVERED

        # Confirm → settled
        tx = market.executor.handle_confirm(
            tx.tx_id,
            ConfirmPayload(
                offer_id=winner.offer.offer_id,
                content_hash_verified=True,
                rating=5,
            ),
        )
        assert tx.state == TxState.CONFIRMED
        assert tx.settled_at is not None

    def test_stats(self, market):
        req = RequestPayload(
            need=Need(description="x", tags=["finance"]),
            budget_oas=5.0,
            request_id="stats-001",
        )
        market.create_auction(req, "buyer")
        market.submit_bid(
            "stats-001",
            OfferPayload(
                request_id="stats-001",
                capability_id="cap-alice",
                price_oas=2.0,
                offer_id="off-s1",
            ),
            "alice",
        )
        market.submit_bid(
            "stats-001",
            OfferPayload(
                request_id="stats-001",
                capability_id="cap-bob",
                price_oas=3.0,
                offer_id="off-s2",
            ),
            "bob",
        )
        market.close_auction("stats-001")

        stats = market.stats()
        assert stats["total_auctions"] == 1
        assert stats["total_bids"] == 2
        assert stats["auctions_with_winner"] == 1


class TestErrorHandling:
    def test_bid_on_closed_auction(self, market):
        req = RequestPayload(
            need=Need(description="x", tags=["finance"]),
            budget_oas=5.0,
            request_id="closed-001",
        )
        market.create_auction(req, "buyer")
        market.close_auction("closed-001")
        with pytest.raises(ValueError, match="closed"):
            market.submit_bid(
                "closed-001",
                OfferPayload(
                    request_id="closed-001",
                    capability_id="cap-alice",
                    price_oas=2.0,
                    offer_id="off-late",
                ),
                "alice",
            )

    def test_execute_no_winner(self, market):
        req = RequestPayload(
            need=Need(description="x", tags=["niche"]),
            budget_oas=5.0,
            request_id="no-win",
        )
        market.create_auction(req, "buyer")
        market.close_auction("no-win")
        with pytest.raises(ValueError, match="No winner"):
            market.execute_winner("no-win")

    def test_unregistered_provider(self, market):
        req = RequestPayload(
            need=Need(description="x", tags=["finance"]),
            budget_oas=5.0,
            request_id="unreg-001",
        )
        market.create_auction(req, "buyer")
        with pytest.raises(ValueError, match="not registered"):
            market.submit_bid(
                "unreg-001",
                OfferPayload(
                    request_id="unreg-001",
                    capability_id="cap-ghost",
                    price_oas=1.0,
                    offer_id="off-ghost",
                ),
                "ghost",
            )
