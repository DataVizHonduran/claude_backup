import warnings
import requests
import pandas as pd

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

BASE_URL = "https://localhost:5000/v1/api"

_DEFAULT_FIELDS = [31, 84, 86, 83, 70, 71, 87, 7295, 7296]


class IBKRClient:
    def __init__(self, base_url: str = BASE_URL):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.verify = False

    def _get(self, path: str, **params):
        r = self.session.get(f"{self.base}{path}", params=params)
        if r.status_code == 401:
            raise PermissionError("IBKR session not authenticated. Open https://localhost:5000 in your browser to log in.")
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, json=None):
        r = self.session.post(f"{self.base}{path}", json=json or {})
        r.raise_for_status()
        return r.json()

    def auth_status(self) -> dict:
        return self._get("/iserver/auth/status")

    def reauthenticate(self) -> dict:
        return self._post("/iserver/reauthenticate")

    def search_contract(self, symbol: str, sec_type: str = "STK", currency: str = "USD") -> int:
        results = self._post("/iserver/secdef/search", json={"symbol": symbol, "secType": sec_type})
        if not results:
            raise ValueError(f"No contracts found for {symbol!r}")
        # prefer USD-denominated or first result
        for item in results:
            if item.get("description", "").upper() == symbol.upper() or item.get("companyName"):
                sections = item.get("sections", [])
                for s in sections:
                    if s.get("secType") == sec_type:
                        return int(item["conid"])
                return int(item["conid"])
        return int(results[0]["conid"])

    def get_snapshot(self, conid: int, fields: list = None) -> dict:
        flds = ",".join(str(f) for f in (fields or _DEFAULT_FIELDS))
        # first call may return empty — IBKR needs a warm-up request
        for _ in range(2):
            data = self._get("/iserver/marketdata/snapshot", conids=conid, fields=flds)
            if data and data[0].get("31"):
                break
        return data[0] if data else {}

    def get_history(
        self,
        conid: int,
        period: str = "1M",
        bar: str = "1d",
        outside_rth: bool = False,
    ) -> pd.DataFrame:
        data = self._get(
            "/hmds/history",
            conid=conid,
            period=period,
            bar=bar,
            outsideRth=str(outside_rth).lower(),
        )
        bars = data.get("data", [])
        if not bars:
            raise ValueError(f"No historical data returned for conid={conid}")
        df = pd.DataFrame(bars)
        df.index = pd.to_datetime(df["t"], unit="ms")
        df.index.name = "date"
        df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        return df[["open", "high", "low", "close", "volume"]]

    def get_options_chain(self, conid: int, month: str, exchange: str = "SMART") -> dict:
        """Returns {'call': [...strikes], 'put': [...strikes]}. month e.g. '20251219'"""
        data = self._get(
            "/iserver/secdef/strikes",
            conid=conid,
            sectype="OPT",
            month=month,
            exchange=exchange,
        )
        return data
