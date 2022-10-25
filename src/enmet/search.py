from typing import List

from enmet import Countries, country_to_enum_name
from enmet.common import ReleaseTypes, url_to_id, datestr_to_date
from enmet.entities import Band, Album
from enmet.pages import BandSearchPage, AlbumSearchPage, RandomBandPage

__all__ = ["search_albums", "search_bands", "random_band"]

_RELEASE_TYPE_IDS = {ReleaseTypes.FULL: 1, ReleaseTypes.LIVE: 2, ReleaseTypes.DEMO: 3, ReleaseTypes.SINGLE: 4,
                     ReleaseTypes.EP: 5, ReleaseTypes.VIDEO: 6, ReleaseTypes.BOX: 7, ReleaseTypes.SPLIT: 8,
                     ReleaseTypes.COMPILATION: 10, ReleaseTypes.SPLIT_VIDEO: 12, ReleaseTypes.COLLABORATION: 13}


_BAND_SEARCH_FIELDS_MAPPING = {
    "name": "bandName",
    "strict": "exactBandMatch",
    "genre": "genre",
    "countries": "country[]",
    "formed_from": "yearCreationFrom",
    "formed_to": "yearCreationTo",
}


def search_bands(*, name: str = None, strict: bool = None, genre: str = None, countries: List[Countries] = None,
                 formed_from: int = None, formed_to: int = None) -> List[Band]:
    if not any(locals().values()):
        return []
    params = {_BAND_SEARCH_FIELDS_MAPPING[k]: v or "" for k, v in locals().items()}
    params[_BAND_SEARCH_FIELDS_MAPPING["countries"]] = [c.value for c in countries or []]
    return [Band(url_to_id(b[0]),
                 name=b[1],
                 country=countries[0] if countries and len(countries) == 1 else Countries[country_to_enum_name(b[3])])
            for b in BandSearchPage(params).bands]


_ALBUM_SEARCH_FIELDS_MAPPING = {
    "name": "releaseTitle",
    "strict": "exactReleaseMatch",
    "band": "bandName",
    "band_strict": "exactBandMatch",
    "year_from": "releaseYearFrom",
    "month_from": "releaseMonthFrom",
    "year_to": "releaseYearTo",
    "month_to": "releaseMonthTo",
    "genre": "genre",
    "release_types": "releaseType[]"
}


def search_albums(*, name: str = None, strict: bool = None, band: str = None, band_strict: bool = None,
                  year_from: int = None, month_from: int = None, year_to: int = None, month_to: int = None,
                  genre: str = None, release_types: List[ReleaseTypes] = None):
    if not any(locals().values()):
        return []
    params = {_ALBUM_SEARCH_FIELDS_MAPPING[k]: v or "" for k, v in locals().items()}
    params[_ALBUM_SEARCH_FIELDS_MAPPING["release_types"]] = [_RELEASE_TYPE_IDS[rt] for rt in release_types or []]
    # Year is forced so that it is included in search results
    if year_from is None:
        params[_ALBUM_SEARCH_FIELDS_MAPPING["year_from"]] = 1900
    if year_to is None:
        params[_ALBUM_SEARCH_FIELDS_MAPPING["year_to"]] = 2999
    return [Album(url_to_id(a[0]), name=a[1], year=datestr_to_date(a[4]).year)
            for a
            in AlbumSearchPage(params).albums]


def random_band() -> Band:
    """Just get a random band."""
    return Band(url_to_id(RandomBandPage().band))
