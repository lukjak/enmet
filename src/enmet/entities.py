import re
from abc import ABC
from datetime import datetime, timedelta
from functools import cached_property, reduce
from inspect import getmembers
from typing import List, Iterable, Optional, Tuple, Union, Dict

from .countries import Countries, country_to_enum_name
from .common import CachedInstance, ReleaseTypes, url_to_id, datestr_to_date, PartialDate
from .pages import BandPage, DiscographyPage, BandRecommendationsPage, AlbumPage, LyricsPage, ArtistPage

__all__ = ["ReleaseTypes", "Entity", "ExternalEntity", "EnmetEntity",
           "DynamicEnmetEntity", "Band", "Album", "Disc", "Track", "Artist", "EntityArtist", "LineupArtist",
           "AlbumArtist", "SimilarBand"]


def _timestr_to_time(time_string: str) -> Optional[timedelta]:
    """Convert time presented as [hh:mm|mm]:ss into timedelta."""
    if not time_string:
        return None
    data = dict(zip(["seconds", "minutes", "hours"], reversed([int(t) for t in time_string.split(":")])))
    return timedelta(**data)


def _discstr_to_name(name: Optional[str]) -> Optional[str]:
    """Determine disc name (if any) from header item of track list (like "Disc 1 - Gloom")."""
    if name and "- " in name:
        return name[name.index("-")+2:].strip()
    else:
        return None


def _turn_na_into_none(data: Union[str, List, timedelta]) -> Union[List, None, str, timedelta]:
    if isinstance(data, list) and len(data) == 1 and data[0].lower() == "n/a":
        return []
    elif isinstance(data, timedelta) and data == timedelta(0):
        return None
    elif isinstance(data, str) and data.lower() in ["n/a", "unknown"] or data == "":
        return None
    else:
        return data


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
    def __init__(self, name: str, **kwargs):
        self.name = name
        for arg in kwargs:
            setattr(self, arg, kwargs[arg])

    def __dir__(self) -> Iterable[str]:
        return vars(self)

    def __eq__(self, other):
        return hash(self) == hash(other)

    def __hash__(self):
        return hash(tuple(sorted((k, getattr(self, k)) for k in vars(self))))


class EnmetEntity(Entity, CachedInstance, ABC):
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
    def __init__(self, id_: str, *, name: str = None, country: Countries = None, genres: str = None):
        if not hasattr(self, "id"):
            super().__init__(id_)
            if name is not None:
                setattr(self, "name", name)
            if country is not None:
                setattr(self, "country", country)
            if genres is not None:
                setattr(self, "genres", genres)
            self._band_page = BandPage(self.id)
            self._albums_page = DiscographyPage(self.id)

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
        return _turn_na_into_none(self._band_page.location)

    @cached_property
    def formed_in(self) -> Optional[int]:
        data = self._band_page.formed_in
        value = _turn_na_into_none(data)
        return int(value) if value else value

    @cached_property
    def years_active(self) -> List[str]:
        return _turn_na_into_none(self._band_page.years_active)

    @cached_property
    def genres(self) -> List[str]:
        return self._band_page.genres

    @cached_property
    def status(self) -> Optional[str]:
        return self._band_page.status

    @cached_property
    def lyrical_themes(self) -> Optional[List[str]]:
        return _turn_na_into_none(self._band_page.lyrical_themes)

    @cached_property
    def label(self) -> str:
        return self._band_page.current_label or self._band_page.last_label

    @cached_property
    def lineup(self) -> List["LineupArtist"]:
        data = self._band_page.lineup
        return [LineupArtist(url_to_id(a[0]), self.id, a[1], a[2]) for a in data]

    @cached_property
    def past_members(self) -> List["LineupArtist"]:
        data = self._band_page.past_members
        return [LineupArtist(url_to_id(a[0]), self.id, a[1], a[2]) for a in data]

    @cached_property
    def live_musicians(self) -> List["LineupArtist"]:
        data = self._band_page.live_musicians
        return [LineupArtist(url_to_id(a[0]), self.id, a[1], a[2]) for a in data]

    @cached_property
    def discography(self) -> List["Album"]:
        """List of band's albums in chronological order."""
        return [Album(url_to_id(a[0]), name=a[1], year=a[3]) for a in self._albums_page.albums]

    @cached_property
    def similar_artists(self) -> List["SimilarBand"]:
        return [SimilarBand(url_to_id(sa[0]), self.id, sa[4], name=sa[1], country=sa[2], genres=sa[3])
                for sa in BandRecommendationsPage(self.id).similar_artists]

    @cached_property
    def info(self) -> str:
        return _turn_na_into_none(self._band_page.info)

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
            self._album_page = AlbumPage(self.id)

    def __repr__(self):
        return f"<Album: {self.name} ({self.id})>"

    def __str__(self):
        return f"{self.name} ({self.year})"

    @cached_property
    def name(self) -> str:
        return self._album_page.name

    @cached_property
    def bands(self) -> List[Band]:
        return [Band(url_to_id(bid[0])) for bid in self._album_page.bands]

    @cached_property
    def type(self) -> ReleaseTypes:
        return ReleaseTypes(self._album_page.type)

    @cached_property
    def year(self) -> int:
        return self.release_date.year

    @cached_property
    def release_date(self) -> PartialDate:
        return datestr_to_date(self._album_page.release_date)

    @cached_property
    def label(self) -> str:
        return self._album_page.label

    @cached_property
    def format(self) -> str:
        return _turn_na_into_none(self._album_page.format)

    @cached_property
    def reviews(self) -> Tuple[str, str]:
        return self._album_page.reviews

    @cached_property
    def catalog_id(self) -> str:
        return _turn_na_into_none(self._album_page.catalog_id)

    @cached_property
    def discs(self) -> List["Disc"]:
        return [Disc(self.id, idx, self.bands) for idx in range(len(self._album_page.disc_names))]

    def _get_artists_for_kind(self, kind: str) -> List["AlbumArtist"]:
        return [AlbumArtist(url_to_id(a[0]), self.id, name=a[1], role=a[2]) for a in getattr(self._album_page, kind)]

    @cached_property
    def lineup(self) -> List["AlbumArtist"]:
        return self._get_artists_for_kind("lineup")

    @cached_property
    def guest_session_musicians(self) -> List["AlbumArtist"]:
        return self._get_artists_for_kind("guest_session_musicians")

    @cached_property
    def other_staff(self) -> List["AlbumArtist"]:
        return self._get_artists_for_kind("other_staff")

    @cached_property
    def total_time(self) -> Optional[timedelta]:
        return _turn_na_into_none(
            reduce(timedelta.__add__, [disc.total_time for disc in self.discs if disc.total_time], timedelta()))

    @cached_property
    def additional_notes(self) -> str:
        return self._album_page.additional_notes


class Disc(DynamicEnmetEntity):
    def __init__(self, album_id: str, number: int = 0, bands: List[Band] = None):
        self._number = number
        self._album_page = AlbumPage(album_id)
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
            tracks.append(Track(t[0], self._bands, int(t[1]), t[2], _timestr_to_time(t[3]), t[4]))
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
            return LyricsPage(self.id).lyrics


class Artist(EnmetEntity):
    """General artist info"""

    def __init__(self, id_):
        if not hasattr(self, "id"):
            super().__init__(id_)
            self._artist_page = ArtistPage(id_)

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

    def _get_bands(self, attrib: str) -> Dict[Band, List[Album]]:
        data = getattr(self._artist_page, attrib)
        result = {
            Band(url_to_id(band[0]), name=band[1]) if band[0] else ExternalEntity(band[1], role=band[2]):
                [Album(url_to_id(album[0]), name=album[1]) for album in data[band]]
            for band in data}
        return result

    @cached_property
    def active_bands(self) -> Dict[Union[Band, ExternalEntity], List[Album]]:
        return self._get_bands("active_bands")

    @cached_property
    def past_bands(self) -> Dict[Union[Band, ExternalEntity], List[Album]]:
        return self._get_bands("past_bands")

    @cached_property
    def guest_session(self) -> Dict[Union[Band, ExternalEntity], List[Album]]:
        return self._get_bands("guest_session")

    @cached_property
    def misc_staff(self) -> Dict[Union[Band, ExternalEntity], List[Album]]:
        return self._get_bands("misc_staff")

    @cached_property
    def links(self) -> List[Tuple[str, str]]:
        return self._artist_page.links


class EntityArtist(DynamicEnmetEntity, ABC):
    """"Album artist or lineup artist"""

    def __init__(self, id_, role: str = None):
        self.artist = Artist(id_)
        self.role = role

    def __getattr__(self, item):
        return getattr(self.artist, item)

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

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.name_in_lineup} ({self.id})>"

    def __str__(self):
        return self.name_in_lineup


class AlbumArtist(EntityArtist):
    """Artist for an album"""

    def __init__(self, id_: str, album_id: str, *, name: str = None, role: str = None):
        super().__init__(id_, role)
        self.name_on_album = name
        self.album = Album(album_id)

    def __dir__(self) -> Iterable[str]:
        return super().__dir__() + ["name_on_album", "album"]

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.name_on_album} ({self.id})>"

    def __str__(self):
        return self.name_on_album
