import re
import sys
from abc import ABC
from functools import cached_property, lru_cache
from os.path import expandvars, expanduser
from pathlib import Path
from time import sleep
from typing import List, Tuple, Union, Optional, Type, Dict
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag, ResultSet
from requests import get
from requests_cache import CachedSession

from enmet.common import CachedInstance

__all__ = ["set_session_cache"]

_METALLUM_URL = "https://www.metal-archives.com"
# Without correct user-agent there are 4xx responses
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)" \
              "Chrome/102.0.5005.167 Safari/537.36"


def _split_by_sep(data: str) -> List[str]:
    """Split different text list (genres, lyrical themes etc.) into separate parts."""
    return re.split(r"\s*[,;]\s*", data.strip())


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


class BandSearchPage(_SearchResultsPage):
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


class AlbumSearchPage(_SearchResultsPage):
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


class _DataPage(_Page, CachedInstance, ABC):

    enmet = _CachedSite()

    def __init__(self, id_: str):
        self.id = str(id_)

    def _get_header_item(self, name: str) -> Optional[Tag]:
        elem = self.enmet.find("dt", string=name)
        return elem.find_next_sibling() if elem else None

    @staticmethod
    def set_session_cache(**kwargs) -> CachedSession:
        return _DataPage.enmet.set_session(**kwargs)


class DiscographyPage(_DataPage):
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


class BandPage(_DataPage):
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


class BandRecommendationsPage(_DataPage):
    RESOURCE = "band/ajax-recommendations/id/{}/showMoreSimilar/1"

    @cached_property
    def similar_artists(self) -> List[List[str]]:
        rows = self.enmet.select("#artist_list tr:not(:last-child)")
        results = []
        if len(rows) and rows[0].text.startswith("No similar artist"):
            return results
        for row in rows:
            data = row.select("td")
            results.append([data[0].select_one("a")["href"], data[0].text])  # Band URL, band name
            results[-1].append(data[1].text)  # Country
            results[-1].append(data[2].text)  # Genre
            results[-1].append(data[3].text)  # Score
        return results


class AlbumPage(_DataPage):
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
    def tracks(self) -> List[List[Union[int, str, Optional[bool]]]]:
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
            result[-1][-1].append(number[:number.index(".")])
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

    def _get_people(self, group_id: str) -> List[List[str]]:
        result = []
        for elem in self.enmet.select(f"{group_id} tr.lineupRow"):
            # Artist URL, Artist
            result.append([elem.select_one("a")["href"], elem.select_one("a").text])
            # Role
            result[-1].append(elem.select_one("td:nth-child(2)").text.strip())
        return result

    @cached_property
    def lineup(self) -> List[List[str]]:
        return self._get_people("#album_members_lineup")

    @cached_property
    def guest_session_musicians(self) -> List[List[str]]:
        return self._get_people("#album_members_guest")

    @cached_property
    def other_staff(self) -> List[List[str]]:
        return self._get_people("#album_members_misc")

    @cached_property
    def additional_notes(self) -> str:
        return self.enmet.select_one("#album_tabs_notes").text.strip()


class ArtistPage(_DataPage):
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

    def _get_band_tab(self, tab: str) -> Dict[Tuple[str, ...], List[Tuple[str, ...]]]:
        result = {}
        # Process band sections
        for section in self.enmet.select(tab + " div.member_in_band"):
            band_url = band_name = band_role = name_in_lineup = None
            # Band url and name
            band = section.select_one(".member_in_band_name")
            if band_data := band.select_one("a"):
                band_url, band_name = band_data["href"], band_data.text
            else:
                band_name = band.text
            # Role and name in lineup
            band_member_data = section.select_one(".member_in_band_role").text.strip().replace("\n", " ")
            name_in_lineup = self.name
            if match := re.search(r"As (.+): (.+)", band_member_data, re.I):
                band_role = match.group(2)
                name_in_lineup = match.group(1)
            else:
                band_role = band_member_data
            # Add band entry to results
            key = band_url, band_name, band_role, name_in_lineup
            result[key] = []
            # Process rows in band section
            for entry in section.select("table tr"):
                if "show all" in entry.text:
                    continue
                album_url = album_name = album_role = name_on_album = None
                # Album url and name
                album = entry.select_one("td:nth-of-type(2)")
                album_url, album_name = album.select_one("a")["href"], album.select_one("a").text
                # Role and name on album
                album_role = entry.select_one("td:nth-of-type(3)").text.strip()
                name_on_album = name_in_lineup or self.name
                if match := re.search(r'(.+) \(as "(.+)"\)', album_role, re.I):
                    album_role, name_on_album = match.group(1), match.group(2)
                # Add album entry for the band to results
                result[key].append([album_url, album_name, album_role, name_on_album])
        return result

    @cached_property
    def active_bands(self) -> Dict[Tuple[str, ...], List[Tuple[str, ...]]]:
        return self._get_band_tab("#artist_tab_active")

    @cached_property
    def past_bands(self) -> Dict[Tuple[str, ...], List[Tuple[str, ...]]]:
        return self._get_band_tab("#artist_tab_past")

    @cached_property
    def guest_session(self) -> Dict[Tuple[str, ...], List[Tuple[str, ...]]]:
        return self._get_band_tab("#artist_tab_guest")

    @cached_property
    def misc_staff(self) -> Dict[Tuple[str, ...], List[Tuple[str, ...]]]:
        return self._get_band_tab("#artist_tab_misc")

    @cached_property
    def links(self) -> List[Tuple[str, str]]:
        data = _ArtistLinksPage(self.id).links
        result = []
        links = data.select("a")
        for link in links:
            result.append((link["href"], link.text))
        return result


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


class _ArtistLinksPage(_DataPage):
    RESOURCE = "link/ajax-list/type/person/id/{}"

    @cached_property
    def links(self) -> str:
        return self.enmet


class LyricsPage(_DataPage):
    RESOURCE = "release/ajax-view-lyrics/id/{}"

    # az lyrics
    # darklyrics
    # GENIUS
    @cached_property
    def lyrics(self):
        return self.enmet.get_text().strip()


class RandomBandPage:
    @cached_property
    def band(self) -> str:
        data = get(urljoin(_METALLUM_URL, "band/random"),
                   headers={"User-Agent": _USER_AGENT})
        return data.url


def set_session_cache(**kwargs) -> CachedSession:
    """Set cache for DataPages reads"""
    return _DataPage.set_session_cache(**kwargs)
