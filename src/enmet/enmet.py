import logging
import re
import sys
from abc import ABC
from datetime import timedelta, datetime
from enum import Enum
from functools import lru_cache, cached_property, reduce
from inspect import getmembers
from os.path import expandvars, expanduser
from pathlib import PurePath, Path
from time import sleep
from urllib.parse import urljoin, urlparse
from weakref import WeakValueDictionary

from bs4 import BeautifulSoup, Tag, ResultSet
from requests import get
from requests_cache import CachedSession
from typing import List, Optional, Tuple, Union, Iterable, Type

from .countries import country_to_enum_name, Countries

APPNAME = "enmet"

_logger = logging.getLogger(APPNAME)

__all__ = ["PartialDate", "ReleaseTypes", "set_session_cache", "Entity", "ExternalEntity", "EnmetEntity",
           "DynamicEnmetEntity", "Band", "Album", "Disc", "Track", "Artist", "EntityArtist", "LineupArtist",
           "AlbumArtist", "search_bands", "search_albums", "SimilarBand"]

_METALLUM_URL = "https://www.metal-archives.com"
# Without correct user-agent there are 4xx responses
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)" \
              "Chrome/102.0.5005.167 Safari/537.36"


def _url_to_id(url: str) -> str:
    """Extract id from URL, if id is the last part of path: http://host.com/path/more_path/id?param=value."""
    _, _, path, *_ = urlparse(url)
    return PurePath(path).name


class PartialDate:
    """Keeps date that has only year, only year and month or year, month and day components."""
    DAYS_IN_MONTH = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    MONTHS = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December"]

    def __init__(self, year: int, month: str = None, day: int = None):
        """ Supports pre-parsed format used on Metal Archives pages: '14th September 1984'"""
        days_in_month = 99  # Just to sedate linters
        if month and month not in self.MONTHS[1:]:
            raise ValueError(f"Invalid month value: {month}")
        if month is not None:
            month = self.MONTHS.index(month)
            days_in_month = self.DAYS_IN_MONTH[month]
            days_in_month += 1 if month == 2 and year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 0
        if any([day and not month,
                day and not (1 <= day <= days_in_month)]):
            raise ValueError(f"Invalid date values: {year}, {month}, {day}")
        self.year = year
        self.month = month
        self.day = day

    def __repr__(self):
        return f"<{self.__class__.__name__}: year={self.year}, month={self.month}, day={self.day}>"

    def __str__(self):
        return f"{self.year}{'' if self.month is None else '-{:02}'.format(self.month)}" \
               f"{'' if self.day is None else '-{:02}'.format(self.day)}"

    def __eq__(self, other):
        return self.year == other.year and self.month == other.month and self.day == other.day


def _datestr_to_date(date_string: str) -> PartialDate:
    """Convert date string as used on Metal Archives pages ('14th September 1984') into PartialDate object."""
    match date_string.split():
        case month, day, year:  # February 19th, 1981  
            day = "".join(filter(str.isdigit, day))
            return PartialDate(day=int(day), month=month, year=int(year))
        case month, year:  # September 1981
            return PartialDate(month=month, year=int(year))
        case year:  # 1981
            return PartialDate(year=int(year[0]))


def _timestr_to_time(time_string: str) -> Optional[timedelta]:
    """Convert time presented as [hh:mm|mm]:ss into timedelta."""
    if not time_string:
        return None
    data = dict(zip(["seconds", "minutes", "hours"], reversed([int(t) for t in time_string.split(":")])))
    return timedelta(**data)


def _split_by_sep(data: str) -> List[str]:
    """Split different text list (genres, lyrical themes etc.) into separate parts."""
    return re.split(r"\s*[,;]\s*", data.strip())


def _discstr_to_name(name: Optional[str]) -> Optional[str]:
    """Determine disc name (if any) from header item of track list (like "Disc 1 - Gloom")."""
    if name and "- " in name:
        return name[name.index("-")+2:].strip()
    else:
        return None


class ReleaseTypes(Enum):
    """Names for release types."""
    FULL = "Full-length"
    LIVE = "Live album"
    DEMO = "Demo"
    SINGLE = "Single"
    EP = "EP"
    VIDEO = "Video"
    BOX = "Boxed set"
    SPLIT = "Split"
    COMPILATION = "Compilation"
    SPLIT_VIDEO = "Split video"
    COLLABORATION = "Collaboration"


_RELEASE_TYPE_IDS = {ReleaseTypes.FULL: 1, ReleaseTypes.LIVE: 2, ReleaseTypes.DEMO: 3, ReleaseTypes.SINGLE: 4,
                     ReleaseTypes.EP: 5, ReleaseTypes.VIDEO: 6, ReleaseTypes.BOX: 7, ReleaseTypes.SPLIT: 8,
                     ReleaseTypes.COMPILATION: 10, ReleaseTypes.SPLIT_VIDEO: 12, ReleaseTypes.COLLABORATION: 13}


class _CachedInstance:
    """Mixin to reuse existing objects."""
    _CACHE = WeakValueDictionary()

    def __new__(cls, id_: str, *args, **kwargs):
        id_ = str(id_)
        if obj := _CachedInstance._CACHE.get((cls.__name__, id_)):
            _logger.debug(f"cached get {cls.__name__} {id_}")
            return obj
        else:
            _logger.debug(f"uncached get {cls.__name__} {id_}")
            obj = super().__new__(cls)
            _CachedInstance._CACHE[(cls.__name__, id_)] = obj
            return obj


class _Page(ABC):
    # Path part of URL
    RESOURCE = None


class _SearchResultsPage(_Page, ABC):
    def __init__(self, params):
        self.params = params

    def _fetch_search_result(self):
        """Note: iDisplayLength does not work"""
        params = self.params
        data = get(urljoin(_METALLUM_URL, self.RESOURCE),
                   params=params,
                   headers={"User-Agent": _USER_AGENT}
                   ).json()
        if len(data["aaData"]) == 0:
            return []
        records = data["aaData"]
        while len(records) < data["iTotalRecords"]:
            self.params["iDisplayStart"] = len(records)
            data = get(urljoin(_METALLUM_URL, self.RESOURCE),
                       params=params,
                       headers={"User-Agent": _USER_AGENT}
                       ).json()
            records.extend(data["aaData"])
        return records


class _BandSearchPage(_SearchResultsPage):
    RESOURCE = "search/ajax-advanced/searching/bands"

    @cached_property
    def bands(self) -> List[Tuple[str, ...]]:
        records = self._fetch_search_result()
        result = []
        for item in records:
            bs = BeautifulSoup(item[0], features="html.parser")
            band_link, band = bs.select_one("a")["href"], bs.select_one("a").text
            genres = item[1]
            country = item[2]  # Location if searched with single country
            formed = None
            if len(item) == 4:  # May be not present
                formed = item[3]
            result.append((band_link, band, genres, country, formed))
        return result


class _AlbumSearchPage(_SearchResultsPage):
    RESOURCE = "search/ajax-advanced/searching/albums/"

    @cached_property
    def albums(self) -> List[Tuple[str, ...]]:
        records = self._fetch_search_result()
        result = []
        for item in records:
            bs = BeautifulSoup(item[0], features="html.parser")
            band_link, band = bs.select_one("a")["href"], bs.select_one("a").text
            bs = BeautifulSoup(item[1], features="html.parser")
            album_link, album = bs.select_one("a")["href"], bs.select_one("a").text
            release_date = item[3][:item[3].find("<")]
            result.append((album_link, album, band_link, band, release_date))
        return result


class _CachedSite:
    """Virtual The Metal Archives site. Descriptor getting data from Metal Archives site for supported classes."""
    _CACHE_PATH = Path(expandvars("%LOCALAPPDATA%") if sys.platform == "win32" else expanduser("~")) / ".enmet"
    _CACHE_NAME = "enmet_data"
    # 1/QUERY_RATE second is the delay after each non-cached _DataPage read from the site
    QUERY_RATE = 3
    # Get a bit more performance maybe by saving time on reading from database and converting to BeautifulSoup objects?
    _BS_CACHE_SIZE = 100

    def __init__(self):
        self._session = None

    def set_session(self, **kwargs) -> CachedSession:
        """Factory method for CachedSession with delay hook."""
        session = CachedSession(
            **({"cache_name": str(self._CACHE_PATH / self._CACHE_NAME), "backend": "sqlite"} | kwargs))
        session.hooks['response'].append(
            lambda r, *args, **kwargs: None if not getattr(r, "from_cache", False) and sleep(
                1 / _CachedSite.QUERY_RATE) else None)
        self._session = session
        return session

    @lru_cache(maxsize=_BS_CACHE_SIZE)
    def _cached_get(self, resource: str) -> BeautifulSoup:
        """Get page from Metal Archives with caching."""
        response = self._session.get(urljoin(_METALLUM_URL, resource),
                                     headers={"User-Agent": _USER_AGENT, 'Accept-Encoding': 'gzip'}
                                     )
        response.raise_for_status()
        return BeautifulSoup(response.content, features="html.parser")

    def __get__(self, instance, owner) -> Union[BeautifulSoup, "_CachedSite"]:
        """Method returning page or search results from Metal Archives"""
        if instance is None:
            return self
        if self._session is None:  # Lazy session creation to enable setting cache before it is accessed.
            self._CACHE_PATH.mkdir(parents=True, exist_ok=True)
            self.set_session()
        resource = instance.RESOURCE.format(instance.id)
        return self._cached_get(resource)


class _DataPage(_Page, _CachedInstance, ABC):

    enmet = _CachedSite()

    def __init__(self, id_: str):
        self.id = str(id_)

    def _get_header_item(self, name: str) -> Optional[Tag]:
        elem = self.enmet.find("dt", string=name)
        return elem.find_next_sibling() if elem else None

    @staticmethod
    def set_session_cache(**kwargs) -> CachedSession:
        return _DataPage.enmet.set_session(**kwargs)


def set_session_cache(**kwargs) -> CachedSession:
    """Set cache for DataPages reads"""
    return _DataPage.set_session_cache(**kwargs)


class _DiscographyPage(_DataPage):
    RESOURCE = "band/discography/id/{}/tab/all"

    @cached_property
    def albums(self) -> List[List[Optional[str]]]:
        result = []
        for elem in self.enmet.select(".discog tbody tr"):
            # Album URL, Name
            result.append([elem.select_one("td:nth-child(1) a")["href"], elem.select_one("td:nth-child(1) a").text])
            # Type
            result[-1].append(elem.select_one("td:nth-child(2)").text)
            # Year
            result[-1].append(elem.select_one("td:nth-child(3)").text)
            # Reviews URL, Reviews
            if (e := elem.select_one("td:nth-child(4)")).text.strip():
                result[-1].extend([e.select_one("a")["href"], e.select_one("a").text])
            else:
                result[-1].extend([None, None])
        return result


class _BandPage(_DataPage):
    RESOURCE = "bands/_/{}"

    @cached_property
    def name(self):
        return self.enmet.select_one(".band_name a").text

    @cached_property
    def country(self) -> Optional[str]:
        return elem.text if (elem := self._get_header_item("Country of origin:")) else None

    @cached_property
    def location(self) -> Optional[str]:
        return elem.text if (elem := self._get_header_item("Location:")) else None

    @cached_property
    def status(self) -> Optional[str]:
        return elem.text if (elem := self._get_header_item("Status:")) else None

    @cached_property
    def formed_in(self) -> Optional[str]:
        return elem.text if (elem := self._get_header_item("Formed in:")) else None

    @cached_property
    def years_active(self):
        return _split_by_sep(self._get_header_item("Years active:").text.strip())

    @cached_property
    def genres(self) -> List[str]:
        return _split_by_sep(self._get_header_item("Genre:").text.strip())

    @cached_property
    def lyrical_themes(self) -> List[str]:
        return _split_by_sep(self._get_header_item("Lyrical themes:").text.strip())

    @cached_property
    def current_label(self):
        return elem.text if (elem := self._get_header_item("Current label:")) else None

    @cached_property
    def last_label(self):
        return elem.text if (elem := self._get_header_item("Last label:")) else None

    @staticmethod
    def _get_members_list(rows: ResultSet[Tag]) -> List[List[Optional[str]]]:
        result = []
        for elem in rows:
            # Artist URL, Artist
            result.append([elem.select_one("a")["href"], elem.select_one("a").text])
            # Role
            result[-1].append(elem.select_one("td:nth-child(2)").text.replace("\n", " ").replace("\xa0", " ").strip())
        return result

    @cached_property
    def lineup(self) -> List[List[Optional[str]]]:
        rows = self.enmet.select("#band_tab_members_current tr.lineupRow")
        return self._get_members_list(rows)

    @cached_property
    def past_members(self) -> List[List[Optional[str]]]:
        rows = self.enmet.select("#band_tab_members_past tr.lineupRow")
        return self._get_members_list(rows)

    @cached_property
    def live_musicians(self) -> List[List[Optional[str]]]:
        rows = self.enmet.select("#band_tab_members_live tr.lineupRow")
        return self._get_members_list(rows)

    @cached_property
    def info(self) -> str:
        if self.enmet.select_one(".band_comment a.btn_read_more"):
            return _BandInfoPage(self.id).info.strip()
        else:
            return " ".join(e.text.strip() for e in self.enmet.select_one(".band_comment").contents).strip()

    @cached_property
    def last_modified(self) -> str:
        return self.enmet.find("td", string=re.compile("Last modified on")).text


class _BandInfoPage(_DataPage):
    RESOURCE = "band/read-more/id/{}"

    @cached_property
    def info(self) -> str:
        return self.enmet.text


class _BandRecommendationsPage(_DataPage):
    RESOURCE = "band/ajax-recommendations/id/{}/showMoreSimilar/1"

    @cached_property
    def similar_artists(self) -> List[List[str]]:
        rows = self.enmet.select("#artist_list tr:not(:last-child)")
        results = []
        for row in rows:
            data = row.select("td")
            results.append([data[0].select_one("a")["href"], data[0].text])  # Band URL, band name
            results[-1].append(data[1].text)  # Country
            results[-1].append(data[2].text)  # Genre
            results[-1].append(data[3].text)  # Score
        return results


class _AlbumPage(_DataPage):
    RESOURCE = "albums/_/_/{}"

    @cached_property
    def name(self):
        return self.enmet.select_one(".album_name a").text

    @cached_property
    def bands(self) -> List[Tuple[str, str]]:
        """List of album bands, more than 1 for splits, cooperations etc."""
        bands = []
        elems = self.enmet.select("#album_info .band_name a")
        for b in elems:
            bands.append((b["href"], b.text))
        return bands

    @cached_property
    def type(self):
        return self._get_header_item("Type:").text

    @cached_property
    def release_date(self):
        return self._get_header_item("Release date:").text

    @cached_property
    def catalog_id(self):
        return self._get_header_item("Catalog ID:").text

    @cached_property
    def label(self):
        return self._get_header_item("Label:").text

    @cached_property
    def format(self):
        return self._get_header_item("Format:").text

    @cached_property
    def reviews(self) -> Tuple[Optional[str], str]:
        elem = self._get_header_item("Reviews:")
        if elem.select_one("a"):
            return elem.select_one("a")["href"], elem.text
        else:
            return None, elem.text

    @cached_property
    def tracks(self):
        result = [[]]
        for elem in self.enmet.select_one("#album_tabs_tracklist").select("tr.even,tr.odd,.discRow"):
            if "discRow" in elem["class"]:
                if len(result[0]) != 0:  # Another disc
                    result.append([])
                continue
            # Id
            result[-1].append([elem.select_one("td:nth-of-type(1) a")["name"]])
            # Number
            number = elem.select_one("td:nth-of-type(1)").text
            result[-1][-1].append(int(number[:number.index(".")]))
            # Name
            result[-1][-1].append(elem.select_one("td:nth-of-type(2)").text.strip())
            # Time
            result[-1][-1].append(elem.select_one("td:nth-of-type(3)").text)
            # Lyrics status
            lyrics = elem.select_one("td:nth-of-type(4)")
            if lyrics.select_one("a"):  # Has lyrics
                result[-1][-1].append(True)
            elif lyrics.select_one("em"):  # Marked as instrumental
                result[-1][-1].append(False)
            else:
                result[-1][-1].append(None)
        return result

    @cached_property
    def disc_names(self) -> List[Optional[str]]:
        return [e.text for e in self.enmet.select(".discRow td")] or [None]

    @cached_property
    def total_times(self) -> List[Optional[str]]:
        return [e.text for e in self.enmet.select(".table_lyrics strong")] or [None]

    @cached_property
    def lineup(self):
        result = []
        for elem in self.enmet.select("#album_members_lineup tr.lineupRow"):
            # Artist URL, Artist
            result.append([elem.select_one("a")["href"], elem.select_one("a").text])
            # Role
            result[-1].append(elem.select_one("td:nth-child(2)").text.strip())
        return result


class _ArtistPage(_DataPage):
    RESOURCE = "artists/_/{}"

    @cached_property
    def name(self):
        return self.enmet.select_one(".band_member_name").text

    @cached_property
    def real_full_name(self):
        return self._get_header_item("Real/full name:").text.strip()

    @cached_property
    def age(self) -> str:
        return self._get_header_item("Age:").text.strip()

    @cached_property
    def place_of_birth(self) -> str:
        return self._get_header_item("Place of birth:").text.strip()

    @cached_property
    def gender(self) -> str:
        return self._get_header_item("Gender:").text

    def _get_extended_section(self, caption: str, cls_data_source: Type[_DataPage]) -> Optional[str]:
        # This is a mess because the HTML for this section is a mess...
        top = self.enmet.select_one("#member_content .band_comment")
        if caption_elem := top.find("h2", string=caption):
            idx_caption = top.index(caption_elem)
            has_readme = False
            idx = 0
            for idx, elem in enumerate(top.contents[idx_caption+1:]):
                if not isinstance(elem, Tag):
                    continue
                elif elem.text == "Read more":
                    has_readme = True
                    break
                elif elem.name == "h2":
                    break
            else:
                idx += 1
            if has_readme:
                return getattr(cls_data_source(self.id), caption.lower()).strip()
            else:
                return " ".join([e.text.strip() for e in top.contents[idx_caption+1:idx_caption+1+idx]])
        else:
            return None

    @cached_property
    def biography(self) -> Optional[str]:
        return self._get_extended_section("Biography", _ArtistBiographyPage)

    @cached_property
    def trivia(self) -> Optional[str]:
        return self._get_extended_section("Trivia", _ArtistTriviaPage)


class _ArtistBiographyPage(_DataPage):
    RESOURCE = "artist/read-more/id/{}"

    @cached_property
    def biography(self) -> str:
        return self.enmet.text


class _ArtistTriviaPage(_DataPage):
    RESOURCE = "artist/read-more/id/{}/field/trivia"

    @cached_property
    def trivia(self) -> str:
        return self.enmet.text


class _LyricsPage(_DataPage):
    RESOURCE = "release/ajax-view-lyrics/id/{}"

    # az lyrics
    # darklyrics
    # GENIUS
    @cached_property
    def lyrics(self):
        return self.enmet.get_text().strip()


class Entity(ABC):
    """A thing, like band or album"""
    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.name}>"

    def __dir__(self) -> List[str]:
        return [p[0] for p in getmembers(self.__class__) if type(p[1]) is cached_property]


class ExternalEntity(Entity):
    """
    Non EM entity, like non-metal musician in metal album lineup.
    It has only string representation and is a class just for the
    sake of consistency.
    """
    def __init__(self, name: str):
        self.name = name

    def __dir__(self) -> Iterable[str]:
        return ["name"]


class EnmetEntity(Entity, _CachedInstance, ABC):
    def __init__(self, id_):
        id_ = str(id_)
        if not hasattr(self, "id"):
            self.id = id_

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.name} ({self.id})>"


class DynamicEnmetEntity(Entity, ABC):
    """Represents entities without its own identity in Enmet, for example disc of an album"""
    def __str__(self):
        return self.name


class Band(EnmetEntity):
    """Band or artist performing as a band."""
    def __init__(self, id_: str, *, name: str = None, country: str = None, genres: str = None):
        if not hasattr(self, "id"):
            super().__init__(id_)
            if name is not None:
                setattr(self, "name", name)
            if country is not None:
                setattr(self, "country", Countries[country_to_enum_name(country)])
            if genres is not None:
                setattr(self, "genres", genres)
            self._band_page = _BandPage(self.id)
            self._albums_page = _DiscographyPage(self.id)

    def __str__(self):
        return f"{self.name} ({self.country})"

    @cached_property
    def name(self) -> str:
        return self._band_page.name

    @cached_property
    def country(self) -> Countries:
        return Countries[country_to_enum_name(self._band_page.country)]

    @cached_property
    def location(self) -> str:
        return self._band_page.location

    @cached_property
    def formed_in(self) -> Optional[int]:
        data = self._band_page.formed_in
        if not data or data == "N/A":
            return None
        else:
            return int(data)

    @cached_property
    def years_active(self) -> List[str]:
        return self._band_page.years_active

    @cached_property
    def genres(self) -> List[str]:
        return self._band_page.genres

    @cached_property
    def status(self) -> Optional[str]:
        return self._band_page.status

    @cached_property
    def lyrical_themes(self) -> List[str]:
        return self._band_page.lyrical_themes

    @cached_property
    def label(self) -> str:
        return self._band_page.current_label or self._band_page.last_label

    @cached_property
    def lineup(self) -> List["LineupArtist"]:
        data = self._band_page.lineup
        return [LineupArtist(_url_to_id(a[0]), self.id, a[1], a[2]) for a in data]

    @cached_property
    def past_members(self) -> List["LineupArtist"]:
        data = self._band_page.past_members
        return [LineupArtist(_url_to_id(a[0]), self.id, a[1], a[2]) for a in data]

    @cached_property
    def live_musicians(self) -> List["LineupArtist"]:
        data = self._band_page.live_musicians
        return [LineupArtist(_url_to_id(a[0]), self.id, a[1], a[2]) for a in data]

    @cached_property
    def discography(self) -> List["Album"]:
        """List of band's albums in chronological order."""
        return [Album(_url_to_id(a[0]), name=a[1], year=a[3]) for a in self._albums_page.albums]

    @cached_property
    def similar_artists(self) -> List["SimilarBand"]:
        return [SimilarBand(_url_to_id(sa[0]), self.id, sa[4], name=sa[1], country=sa[2], genres=sa[3])
                for sa in _BandRecommendationsPage(self.id).similar_artists]

    @cached_property
    def info(self) -> str:
        return self._band_page.info

    @cached_property
    def last_modified(self) -> datetime:
        data = self._band_page.last_modified
        year, month, day, hour, minute, second = re.search(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})",
                                                           data).groups()
        return datetime(year=int(year), month=int(month), day=int(day), hour=int(hour), minute=int(minute),
                        second=int(second))


class SimilarBand(DynamicEnmetEntity):
    def __init__(self, id_: str, similar_to_id: str, score: str, name: str = None, country: str = None,
                 genres: str = None):
        self.band = Band(id_, name=name, country=country, genres=genres)
        self.similar_to = Band(similar_to_id)
        self.score = int(score)

    def __dir__(self) -> List[str]:
        return dir(self.band) + ["score", "similar_to"]

    def __getattr__(self, item):
        return getattr(self.band, item)

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.band.name} ({self.score})>"


class Album(EnmetEntity):
    def __init__(self, id_: str, *, name: str = None, year: int = None):
        # Have parameters for str and repr ready
        if not hasattr(self, "id"):
            super().__init__(id_)
            if name is not None:
                setattr(self, "name", name)
            if year is not None:
                setattr(self, "year", year)
            self._album_page = _AlbumPage(self.id)

    def __repr__(self):
        return f"<Album: {self.name} ({self.id})>"

    def __str__(self):
        return f"{self.name} ({self.year})"

    @cached_property
    def name(self) -> str:
        return self._album_page.name

    @cached_property
    def bands(self) -> List[Band]:
        return [Band(_url_to_id(bid[0])) for bid in self._album_page.bands]

    @cached_property
    def type(self) -> ReleaseTypes:
        return ReleaseTypes(self._album_page.type)

    @cached_property
    def year(self) -> int:
        return self.release_date.year

    @cached_property
    def release_date(self) -> PartialDate:
        return _datestr_to_date(self._album_page.release_date)

    @cached_property
    def label(self) -> str:
        return self._album_page.label

    @cached_property
    def format(self) -> str:
        return self._album_page.format

    @cached_property
    def reviews(self) -> Tuple[str, str]:
        return self._album_page.reviews

    @cached_property
    def catalog_id(self) -> str:
        return self._album_page.catalog_id

    @cached_property
    def discs(self) -> List["Disc"]:
        return [Disc(self.id, idx, self.bands) for idx in range(len(self._album_page.disc_names))]

    @cached_property
    def lineup(self) -> List["AlbumArtist"]:
        return [AlbumArtist(_url_to_id(a[0]), self.id, name=a[1], role=a[2]) for a in self._album_page.lineup]

    @cached_property
    def total_time(self) -> timedelta:
        return reduce(timedelta.__add__, [disc.total_time for disc in self.discs if disc.total_time], timedelta())


class Disc(DynamicEnmetEntity):
    def __init__(self, album_id: str, number: int = 0, bands: List[Band] = None):
        self._number = number
        self._album_page = _AlbumPage(album_id)
        self._bands = bands

    @cached_property
    def number(self) -> int:
        return self._number + 1

    @cached_property
    def name(self) -> Optional[str]:
        return _discstr_to_name(self._album_page.disc_names[self._number])

    @cached_property
    def total_time(self) -> timedelta:
        return _timestr_to_time(self._album_page.total_times[self._number])

    @cached_property
    def tracks(self) -> List["Track"]:
        tracks = []
        for t in self._album_page.tracks[self._number]:
            tracks.append(Track(t[0], self._bands, t[1], t[2], _timestr_to_time(t[3]), t[4]))
        return tracks


class Track(EnmetEntity):
    def __init__(self, id_: str, bands: List[Band], number: int, name: str, time: timedelta = None,
                 lyrics_info: Optional[bool] = None):
        if not hasattr(self, "id"):
            super().__init__(id_)
            self.number = number
            self.time = time
            self._name = name
            self._lyrics_info = lyrics_info
            self._bands = bands

    def __dir__(self) -> List[str]:
        return super().__dir__() + ["number", "time"]

    @cached_property
    def name(self) -> str:
        if len(self._bands) < 2:
            return self._name
        else:
            for b in self._bands:  # Handle track on a split album
                if self._name.startswith(b.name):
                    return self._name[self._name.index("-")+2:]
            else:
                return self._name  # Probably wrong band name put into track name

    @cached_property
    def band(self) -> Band:
        if len(self._bands) == 1:
            return self._bands[0]
        else:
            for b in self._bands:
                if self._name.startswith(b.name):
                    return b
            else:
                raise ValueError("No band available for split album track")

    @cached_property
    def lyrics(self) -> Optional[Union[bool, str]]:
        if self._lyrics_info is None:
            return None  # No information
        elif self._lyrics_info is False:  # Instrumental
            return False
        else:
            return _LyricsPage(self.id).lyrics


class Artist(EnmetEntity):
    """General artist info"""

    def __init__(self, id_):
        if not hasattr(self, "id"):
            super().__init__(id_)
            self._artist_page = _ArtistPage(id_)

    def __str__(self):
        return f"{self.name}"

    def __dir__(self) -> Iterable[str]:
        return [p[0] for p in getmembers(self.__class__) if type(p[1]) is cached_property]

    @cached_property
    def name(self) -> str:
        return self._artist_page.name

    @cached_property
    def real_full_name(self) -> str:
        return self._artist_page.real_full_name

    @cached_property
    def age(self) -> str:
        return self._artist_page.age

    @cached_property
    def place_of_birth(self) -> str:
        return self._artist_page.place_of_birth

    @cached_property
    def gender(self) -> str:
        return self._artist_page.gender

    @cached_property
    def biography(self) -> str:
        return self._artist_page.biography

    @cached_property
    def trivia(self) -> str:
        return self._artist_page.trivia


class EntityArtist(DynamicEnmetEntity, ABC):
    """"Album artist or lineup artist"""

    def __init__(self, id_, role: str = None):
        self.artist = Artist(id_)
        self.role = role

    def __getattr__(self, item):
        return getattr(self.artist, item)

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.artist.name} ({self.id})>"

    def __dir__(self) -> List[str]:
        return dir(self.artist) + ["role"]


class LineupArtist(EntityArtist):
    """Artist in the current band lineup"""

    def __init__(self, id_: str, band_id: str, name=None, role=None):
        super().__init__(id_, role)
        self.name_in_lineup = name
        self.band = Band(band_id)

    def __dir__(self) -> Iterable[str]:
        return super().__dir__() + ["name_in_lineup", "band"]


class AlbumArtist(EntityArtist):
    """Artist for an album"""

    def __init__(self, id_: str, album_id: str, *, name: str = None, role: str = None):
        super().__init__(id_, role)
        self.name_on_album = name
        self.album = Album(album_id)

    def __dir__(self) -> Iterable[str]:
        return super().__dir__() + ["name_on_album", "album"]


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
    return [Band(_url_to_id(b[0]),
                 name=b[1],
                 country=countries[0] if countries and len(countries) == 1 else b[3])
            for b in _BandSearchPage(params).bands]


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
    return [Album(_url_to_id(a[0]), name=a[1], year=_datestr_to_date(a[4]).year)
            for a
            in _AlbumSearchPage(params).albums]
