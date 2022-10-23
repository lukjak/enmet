import logging
from enum import Enum
from pathlib import PurePath
from urllib.parse import urlparse
from weakref import WeakValueDictionary

__all__ = ["ReleaseTypes", "PartialDate"]

_logger = logging.getLogger(__file__)


def url_to_id(url: str) -> str:
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


def datestr_to_date(date_string: str) -> PartialDate:
    """Convert date string as used on Metal Archives pages ('14th September 1984') into PartialDate object."""
    match date_string.split():
        case month, day, year:  # February 19th, 1981
            day = "".join(filter(str.isdigit, day))
            return PartialDate(day=int(day), month=month, year=int(year))
        case month, year:  # September 1981
            return PartialDate(month=month, year=int(year))
        case year:  # 1981
            return PartialDate(year=int(year[0]))


class CachedInstance:
    """Mixin to reuse existing objects."""
    _CACHE = WeakValueDictionary()

    def __new__(cls, id_: str, *args, **kwargs):
        id_ = str(id_)
        if obj := CachedInstance._CACHE.get((cls.__name__, id_)):
            _logger.debug(f"cached get {cls.__name__} {id_}")
            return obj
        else:
            _logger.debug(f"uncached get {cls.__name__} {id_}")
            obj = super().__new__(cls)
            CachedInstance._CACHE[(cls.__name__, id_)] = obj
            return obj


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
