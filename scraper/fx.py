"""JPY -> AUD rate from Frankfurter (European Central Bank reference rates), free, no key."""
from .common import log

URL = "https://api.frankfurter.app/latest?from=AUD&to=JPY"


def aud_to_jpy(http, fallback: float | None = None) -> float:
    try:
        rate = float(http.get_json(URL)["rates"]["JPY"])
        log.info("1 AUD = %.2f JPY", rate)
        return rate
    except Exception as e:  # noqa: BLE001
        if fallback:
            log.warning("FX lookup failed (%s), using last known rate %.2f", e, fallback)
            return fallback
        raise
