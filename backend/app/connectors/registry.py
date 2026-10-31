"""Source key -> connector class. Add a new source by adding a row to app/data/reference.py SOURCES and,
if it needs bespoke logic, a connector class here."""
from app.connectors.base import BaseConnector
from app.connectors.gated import (ApolloConnector, ImportYetiConnector, KompassConnector, PanjivaConnector,
                                  TradeDataProConnector, VolzaConnector, make_directory)
from app.connectors.government import ComtradeConnector, UsCensusConnector
from app.connectors.imports import CsvImportConnector
from app.connectors.web_search import WebSearchConnector
from app.connectors.website import WebsiteConnector

CONNECTORS: dict[str, type[BaseConnector]] = {
    "web_search": WebSearchConnector,
    "company_website": WebsiteConnector,
    "us_census": UsCensusConnector,
    "un_comtrade": ComtradeConnector,
    "csv_import": CsvImportConnector,
    "importyeti": ImportYetiConnector,
    "volza": VolzaConnector,
    "panjiva": PanjivaConnector,
    "tradedata_pro": TradeDataProConnector,
    "kompass": KompassConnector,
    "apollo": ApolloConnector,
    "enf_plastic": make_directory("enf_plastic"),
    "plasticker": make_directory("plasticker"),
    "plastics_markets": make_directory("plastics_markets"),
    "epda": make_directory("epda"),
}

# Default job type per source for "Run now"
DEFAULT_JOB = {
    "web_search": "discover",
    "company_website": "refresh_websites",
    "us_census": "trade_stats",
    "un_comtrade": "trade_stats",
    "importyeti": "fetch_shipments",
    "volza": "fetch_shipments",
    "panjiva": "fetch_shipments",
    "tradedata_pro": "fetch_shipments",
    "kompass": "collect_directory",
    "apollo": "enrich_contacts",
    "enf_plastic": "collect_directory",
    "plasticker": "collect_directory",
    "plastics_markets": "collect_directory",
    "epda": "collect_directory",
}


def get_connector(key: str) -> type[BaseConnector] | None:
    return CONNECTORS.get(key)
