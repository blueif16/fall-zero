"""The page's own API: only the catalogs the page needs are served, nothing else under skill/."""

from fastapi.testclient import TestClient

from fall_zero.furniture import catalog
from fall_zero.server import app

client = TestClient(app)


def test_the_page_reads_the_handoffs_and_household_catalogs():
    for name in ("handoffs", "household"):
        assert client.get(f"/api/catalog/{name}").json() == catalog(name)


def test_no_other_file_is_served_as_a_catalog():
    for name in ("examples", "materials", "..%2F..%2Fconfig", "nope"):
        assert client.get(f"/api/catalog/{name}").status_code == 404
