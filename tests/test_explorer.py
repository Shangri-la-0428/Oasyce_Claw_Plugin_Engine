"""Tests for the Oasyce Block Explorer web UI."""

import json
from io import BytesIO
from unittest.mock import patch

import pytest

from oasyce_plugin.config import Config
from oasyce_plugin.storage.ledger import Ledger


# ── Helpers ──────────────────────────────────────────────────────────

def _setup_explorer(ledger):
    """Wire the explorer module globals to a test ledger + config."""
    import oasyce_plugin.explorer.app as exp

    cfg = Config.from_env()
    exp._ledger = ledger
    exp._config = cfg
    exp._staking = None  # force fresh
    return exp


class _FakeWfile:
    def __init__(self):
        self.buf = BytesIO()

    def write(self, data):
        self.buf.write(data)

    def getvalue(self):
        return self.buf.getvalue()


class _FakeHandler:
    """Minimal stand-in for BaseHTTPRequestHandler for unit testing."""

    def __init__(self, path="/"):
        self.path = path
        self.wfile = _FakeWfile()
        self._status = None
        self._headers = {}

    def send_response(self, code):
        self._status = code

    def send_header(self, key, value):
        self._headers[key] = value

    def end_headers(self):
        pass

    def send_error(self, code, msg=""):
        self._status = code


def _get(exp, path="/"):
    """Simulate a GET request through the explorer handler."""
    from oasyce_plugin.explorer.app import _Handler

    handler = _FakeHandler(path)
    # Bind handler attributes that BaseHTTPRequestHandler normally sets
    handler.command = "GET"
    handler.request_version = "HTTP/1.1"

    # Call do_GET directly
    _Handler.do_GET(handler)
    return handler


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def ledger():
    db = Ledger(":memory:")
    yield db
    db.close()


@pytest.fixture
def explorer(ledger):
    return _setup_explorer(ledger)


@pytest.fixture
def seeded_ledger():
    """A ledger with some data for richer tests."""
    db = Ledger(":memory:")
    # Register an asset
    db.save_asset({
        "asset_id": "test-asset-001",
        "owner": "Alice",
        "file_hash": "abc123",
        "tags": ["test", "data"],
    })
    # Record transactions + create a block
    db.record_tx("register", asset_id="test-asset-001", from_addr="Alice")
    db.record_tx("buy", asset_id="test-asset-001", from_addr="Bob", to_addr="Alice", amount=10.0)
    db.create_block()

    # Another block
    db.record_tx("stake", asset_id="", from_addr="Charlie", amount=10000.0)
    db.create_block()

    yield db
    db.close()


@pytest.fixture
def seeded_explorer(seeded_ledger):
    return _setup_explorer(seeded_ledger)


# ── Tests ────────────────────────────────────────────────────────────

class TestExplorerRoutes:
    """All HTML routes return 200 OK."""

    def test_overview(self, explorer):
        h = _get(explorer, "/")
        assert h._status == 200

    def test_blocks(self, explorer):
        h = _get(explorer, "/blocks")
        assert h._status == 200

    def test_assets(self, explorer):
        h = _get(explorer, "/assets")
        assert h._status == 200

    def test_validators(self, explorer):
        h = _get(explorer, "/validators")
        assert h._status == 200

    def test_nodes(self, explorer):
        h = _get(explorer, "/nodes")
        assert h._status == 200

    def test_api_chain(self, explorer):
        h = _get(explorer, "/api/chain")
        assert h._status == 200

    def test_api_mempool(self, explorer):
        h = _get(explorer, "/api/mempool")
        assert h._status == 200

    def test_unknown_route_404(self, explorer):
        h = _get(explorer, "/nonexistent")
        assert h._status == 404


class TestApiChain:
    """GET /api/chain returns correct JSON structure."""

    def test_empty_chain(self, explorer):
        h = _get(explorer, "/api/chain")
        data = json.loads(h.wfile.getvalue())
        assert "chain_height" in data
        assert "total_assets" in data
        assert "total_transactions" in data
        assert "node_id" in data
        assert data["chain_height"] == 0

    def test_with_blocks(self, seeded_explorer):
        h = _get(seeded_explorer, "/api/chain")
        data = json.loads(h.wfile.getvalue())
        assert data["chain_height"] == 2
        assert data["total_assets"] == 1
        assert data["total_transactions"] == 3


class TestApiMempool:
    """GET /api/mempool returns an array."""

    def test_empty_mempool(self, explorer):
        h = _get(explorer, "/api/mempool")
        data = json.loads(h.wfile.getvalue())
        assert isinstance(data, list)
        assert len(data) == 0

    def test_pending_tx(self, explorer, ledger):
        ledger.record_tx("register", asset_id="pending-asset", from_addr="Dave")
        h = _get(explorer, "/api/mempool")
        data = json.loads(h.wfile.getvalue())
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["asset_id"] == "pending-asset"


class TestBlocksPage:
    """GET /blocks renders block list HTML."""

    def test_empty_blocks(self, explorer):
        h = _get(explorer, "/blocks")
        body = h.wfile.getvalue().decode()
        assert "Blocks" in body
        assert "No blocks yet" in body

    def test_with_blocks(self, seeded_explorer):
        h = _get(seeded_explorer, "/blocks")
        body = h.wfile.getvalue().decode()
        assert "Blocks" in body
        assert "#1" in body or "#0" in body  # block numbers rendered

    def test_block_detail(self, seeded_explorer):
        h = _get(seeded_explorer, "/blocks/0")
        assert h._status == 200
        body = h.wfile.getvalue().decode()
        assert "Block #0" in body
        assert "Merkle Root" in body

    def test_block_not_found(self, seeded_explorer):
        h = _get(seeded_explorer, "/blocks/999")
        assert h._status == 404


class TestValidatorPage:
    """GET /validators shows staking information."""

    def test_empty_validators(self, explorer):
        h = _get(explorer, "/validators")
        body = h.wfile.getvalue().decode()
        assert "Validators" in body
        assert "Active Validators" in body
        assert "Total Staked" in body

    def test_with_staked_validator(self, explorer, ledger):
        # Add a stake through the ledger
        ledger.update_stake("node-abc", "staker-1", 50000.0)
        h = _get(explorer, "/validators")
        body = h.wfile.getvalue().decode()
        assert "node-abc" in body
        assert "50,000.00" in body or "50000" in body

    def test_validator_stats_grid(self, explorer):
        h = _get(explorer, "/validators")
        body = h.wfile.getvalue().decode()
        assert "Active Validators" in body
        assert "Total Staked" in body
        assert "Rewards Distributed" in body
