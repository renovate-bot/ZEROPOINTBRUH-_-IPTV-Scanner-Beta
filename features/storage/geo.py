"""Country code / name helpers for filter facets and inference."""

from __future__ import annotations

from typing import Optional

# ISO 3166-1 alpha-2 → English short name (subset covering this catalog).
COUNTRY_CODE_TO_NAME: dict[str, str] = {
    "AD": "Andorra",
    "AE": "United Arab Emirates",
    "AL": "Albania",
    "AM": "Armenia",
    "AR": "Argentina",
    "AT": "Austria",
    "AU": "Australia",
    "AZ": "Azerbaijan",
    "BA": "Bosnia and Herzegovina",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "BR": "Brazil",
    "BY": "Belarus",
    "CA": "Canada",
    "CG": "Congo",
    "CH": "Switzerland",
    "CL": "Chile",
    "CN": "China",
    "CR": "Costa Rica",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DE": "Germany",
    "DK": "Denmark",
    "DO": "Dominican Republic",
    "DZ": "Algeria",
    "EE": "Estonia",
    "EG": "Egypt",
    "ES": "Spain",
    "FI": "Finland",
    "FO": "Faroe Islands",
    "FR": "France",
    "GB": "United Kingdom",
    "GE": "Georgia",
    "GL": "Greenland",
    "GR": "Greece",
    "HK": "Hong Kong",
    "HR": "Croatia",
    "HU": "Hungary",
    "ID": "Indonesia",
    "IE": "Ireland",
    "IL": "Israel",
    "IN": "India",
    "IQ": "Iraq",
    "IR": "Iran",
    "IS": "Iceland",
    "IT": "Italy",
    "JO": "Jordan",
    "JP": "Japan",
    "KE": "Kenya",
    "KR": "South Korea",
    "KW": "Kuwait",
    "KZ": "Kazakhstan",
    "LB": "Lebanon",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "MA": "Morocco",
    "MD": "Moldova",
    "ME": "Montenegro",
    "MK": "North Macedonia",
    "MX": "Mexico",
    "MY": "Malaysia",
    "NG": "Nigeria",
    "NL": "Netherlands",
    "NO": "Norway",
    "NZ": "New Zealand",
    "OM": "Oman",
    "PA": "Panama",
    "PE": "Peru",
    "PH": "Philippines",
    "PK": "Pakistan",
    "PL": "Poland",
    "PT": "Portugal",
    "QA": "Qatar",
    "RO": "Romania",
    "RS": "Serbia",
    "RU": "Russia",
    "SA": "Saudi Arabia",
    "SE": "Sweden",
    "SG": "Singapore",
    "SI": "Slovenia",
    "SK": "Slovakia",
    "TD": "Chad",
    "TH": "Thailand",
    "TN": "Tunisia",
    "TR": "Turkey",
    "TW": "Taiwan",
    "UA": "Ukraine",
    "US": "United States",
    "UY": "Uruguay",
    "VE": "Venezuela",
    "VN": "Vietnam",
    "XK": "Kosovo",
    "ZA": "South Africa",
}

# Extra aliases seen in playlist group-title values.
_COUNTRY_ALIASES: dict[str, str] = {
    "bosnia": "BA",
    "czech": "CZ",
    "czechia": "CZ",
    "czech republic": "CZ",
    "costa": "CR",
    "costa rica": "CR",
    "dominican": "DO",
    "dominican republic": "DO",
    "faroe": "FO",
    "faroe islands": "FO",
    "uk": "GB",
    "u.k.": "GB",
    "united kingdom": "GB",
    "united": "GB",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "united states": "US",
    "united states of america": "US",
    "korea": "KR",
    "south korea": "KR",
    "russia": "RU",
    "russian federation": "RU",
    "uae": "AE",
    "日本": "JP",
    "macedonia": "MK",
    "holland": "NL",
    "the netherlands": "NL",
    "chad": "TD",
    "greenland": "GL",
    "hong": "HK",
    "hong kong": "HK",
}

COUNTRY_NAME_TO_CODE: dict[str, str] = {
    name.lower(): code for code, name in COUNTRY_CODE_TO_NAME.items()
}
COUNTRY_NAME_TO_CODE.update(_COUNTRY_ALIASES)

# Placeholders / non-category group titles to keep out of the Category menu.
_NON_CATEGORY_GROUPS = frozenset(
    {
        "undefined",
        "unknown",
        "global",
        "ungrouped",
        "all",
        "other",
        "misc",
        "miscellaneous",
        "vod",
        "country",
        "countries",
    }
)


def country_code_to_name(code: Optional[str]) -> str:
    if not code:
        return ""
    c = str(code).strip().upper()
    if c in ("GLOBAL", "XX", "ZZ"):
        return ""
    return COUNTRY_CODE_TO_NAME.get(c, c)


def country_name_to_code(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    text = str(name).strip()
    if not text:
        return None
    if len(text) == 2 and text.isalpha():
        code = text.upper()
        return code if code in COUNTRY_CODE_TO_NAME or code == "XK" else None
    return COUNTRY_NAME_TO_CODE.get(text.lower())


def is_country_like_group(label: Optional[str]) -> bool:
    """True when a group-title is really a country (or empty placeholder)."""
    if not label:
        return True
    text = str(label).strip()
    if not text:
        return True
    low = text.lower()
    if low in _NON_CATEGORY_GROUPS:
        return True
    if country_name_to_code(text):
        return True
    return False


def resolve_country_code(channel: dict, source_url: Optional[str] = None) -> Optional[str]:
    """Best-effort ISO country code from channel metadata / source URL."""
    if not isinstance(channel, dict):
        return None

    existing = (channel.get("country") or "").strip()
    if existing and existing.upper() not in ("GLOBAL", "XX", "ZZ", "UNKNOWN", "UNDEFINED"):
        if len(existing) == 2 and existing.isalpha():
            return existing.upper()
        mapped = country_name_to_code(existing)
        if mapped:
            return mapped

    tvg_id = (channel.get("tvg_id") or "").strip().lower()
    if "." in tvg_id:
        suffix = tvg_id.split(".")[-1]
        if len(suffix) == 2 and suffix.isalpha():
            return suffix.upper()

    if source_url:
        import re

        match = re.search(r"/countries/([a-z]{2})\.m3u", source_url, re.IGNORECASE)
        if match:
            return match.group(1).upper()

    group = (channel.get("group_title") or "").strip()
    mapped = country_name_to_code(group)
    if mapped:
        return mapped

    return None
