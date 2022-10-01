from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, ANY

import pytest
from bs4 import BeautifulSoup

from src.enmet.enmet import search_albums, PartialDate, Album, search_bands, _datestr_to_date, Artist, Track, Band, \
    ReleaseTypes, EnmetEntity, set_session_cache, _CachedSite
from src.enmet.countries import Countries


@pytest.fixture(scope="session", autouse=True)
def temp_cache():
    Path("enmet_test_dummy.sqlite").unlink(missing_ok=True)
    set_session_cache(cache_name="enmet_test_dummy")
    yield


def test_band():
    band = search_bands(name="megadeth", strict=True)[0]
    assert repr(band) == "<Band: Megadeth (138)>"
    assert str(band) == "Megadeth (United States)"
    assert band.name == "Megadeth"
    assert str(band.country) == "United States"
    assert band.location == "Los Angeles, California"
    assert band.formed_in == 1983
    assert band.years_active == ["1983 (as Fallen Angels)", "1983-2002", "2004-present"]
    assert band.genres == ["Thrash Metal (early/later)", "Heavy Metal/Rock (mid)"]
    assert band.lyrical_themes == ["Politics", "War", "History", "Death", "Religion", "Society", "New World Order"]
    assert band.label == "Tradecraft"
    assert {a.id for a in band.lineup} == {"184", "2836", "3826", "1391"}
    assert repr(band.lineup[0]) == "<LineupArtist: Dave Mustaine (184)>"
    assert str(band.lineup[0]) == "Dave Mustaine"
    assert Artist(184) is band.lineup[0].artist
    assert band.lineup[0].artist.real_full_name == "David Scott Mustaine"
    assert str(band.lineup[0].artist) == "Dave Mustaine"
    assert band.discography[0].release_date == PartialDate(year=1984, month="March", day=9)
    assert dir(band) == ['country', 'discography', 'formed_in', 'genres', 'label', 'lineup', 'location',
                         'lyrical_themes', 'name', 'status', 'years_active']
    assert dir(band.lineup[0]) == ['band', 'name', 'name_in_lineup', 'real_full_name', 'role']


def test_band_splitup():
    band = Band("72")
    assert band.label == "Nuclear Blast"


def test_search_bands_set_country(mocker):
    # given
    asp_mock = mocker.patch("src.enmet.enmet._BandSearchPage")
    # when
    search_bands(name="dummy", countries=[Countries.POLAND])
    # then
    assert asp_mock.mock_calls[0] == call({'bandName': 'dummy', 'country[]': ['PL']})


def test_album():
    album = search_albums(name="Metal Heart", band="Accept")[0]
    assert {a.id for a in album.lineup} == {'21647', '21529', '21621', '21592', '21656'}
    assert album.discs[0].tracks[0].lyrics.startswith("It is 1999")
    assert album.type == ReleaseTypes.FULL
    assert album.catalog_id == "PL 70638"
    assert album.label == "RCA"
    assert album.format == '12" vinyl (33⅓ RPM)'
    assert album.reviews == ('https://www.metal-archives.com/reviews/Accept/Metal_Heart/826/', '\n12 reviews (avg. 78%)\n')
    assert album.total_time == timedelta(minutes=39, seconds=55)
    assert repr(album) == "<Album: Metal Heart (826)>"
    assert str(album) == "Metal Heart (1985)"
    assert album.discs[0].number == 1
    assert album.discs[0].tracks[0].band is Band("198")
    assert album.year == 1985
    assert dir(album) == ['bands', 'catalog_id', 'discs', 'format', 'label', 'lineup', 'name', 'release_date',
                          'reviews', 'total_time', 'type', 'year']
    assert dir(album.lineup[0]) == ['album', 'name', 'name_on_album', 'real_full_name', 'role']
    assert dir(album.discs[0]) == ['name', 'number', 'total_time', 'tracks']
    assert dir(album.discs[0].tracks[0]) == ['band', 'lyrics', 'name', 'number', 'time']


def test_search_album_with_years(mocker):
    # given
    asp_mock = mocker.patch("src.enmet.enmet._AlbumSearchPage")
    # when
    search_albums(name="dummy", year_from=1991, year_to=1992)
    # then
    assert asp_mock.mock_calls[0] == call({'releaseTitle': 'dummy', 'releaseYearFrom': 1991, 'releaseYearTo': 1992, 'releaseType[]': []})


def test_album_missing_values():
    album = Album("3509")
    assert album.name == "World War III"
    assert album.discs[0].tracks[2].name == "Vindicator"
    assert album.discs[0].tracks[2].time is None
    assert album.discs[0].tracks[2].lyrics is None
    assert album.discs[0].name is None


def test_album_sides_instrumental():
    album = Album("457889")
    assert len(album.discs[0].tracks) == 8
    assert album.discs[0].tracks[2].name == "The Ytse Jam"
    assert album.discs[0].tracks[2].lyrics is False


def test_album_named_discs():
    album = Album("534606")
    assert album.name == "Songs from the North I, II & III"
    assert [disc.name for disc in album.discs] == ["Gloom", "Beauty", "Despair"]


def test_album_split():
    album = Album("907847")
    assert {band.name for band in album.bands} == {"Vektor", "Cryptosis"}
    assert album.discs[0].tracks[0].band.name == "Vektor"
    assert album.discs[0].tracks[0].name == "Activate"
    assert album.discs[0].tracks[2].band.name == "Cryptosis"


def test_album_disc_and_sides():
    album = Album("78")
    assert len(album.discs) == 2
    assert len(album.discs[0].tracks) == 8
    assert len(album.discs[1].tracks) == 9


def test_no_search_results():
    # given
    result = search_albums(name="XYZ<>123")
    # then
    assert result == []


def test_big_search():
    # given
    result = search_bands(name="fire", strict=False)
    # then
    assert len(result) > 200


def test_partialdate_bad_month():
    with pytest.raises(ValueError):
        PartialDate(year=1999, month="dummy", day=1)


def test_partialdate_bad_day():
    with pytest.raises(ValueError):
        PartialDate(year=1999, month="September", day=99)


def test_partial_date_str_repr():
    # given
    pd = PartialDate(1999, "March", 7)
    # then
    assert str(pd) == "1999-03-07"
    assert repr(pd) == "<PartialDate: year=1999, month=3, day=7>"


@pytest.mark.parametrize("datestr, year, month, day",
                         [("March 1999", 1999, 3, None), ("2004", 2004, None, None)])
def test_datestr_to_date(datestr, year, month, day):
    # given
    result = _datestr_to_date(datestr)
    # then
    assert result.year == year
    assert result.month == month
    assert result.day == day


def test_Track_no_band_for_track():
    # given
    b1, b2 = SimpleNamespace(name="b1"), SimpleNamespace(name="b2")
    t = Track("1", [b1, b2], 1, name="test123")
    # then
    with pytest.raises(ValueError):
        _ = t.band


@pytest.mark.parametrize("attr, val, expected", [("country", SimpleNamespace(text="Poland"), Countries.POLAND),
                                                 ("status", SimpleNamespace(text=2), 2),
                                                 ("label", SimpleNamespace(text=3), 3)])
def test_Band_properties(mocker, attr, val, expected):
    # given
    mocker.patch("src.enmet.enmet._DataPage._get_header_item", lambda p1, p2: val)
    # when
    b = Band("dummy")
    # then
    assert getattr(b, attr) == expected


def test_Album_properties_reviews(mocker):
    # given
    class Dummy:
        text = "text123"

        def select_one(self, _):
            return None
    mocker.patch("src.enmet.enmet._DataPage._get_header_item", lambda p1, p2: Dummy())
    # when
    b = Album("dummy").reviews
    # then
    assert b == (None, "text123")


def test_track_split_name_without_band():
    # given
    b1, b2 = SimpleNamespace(name="b1"), SimpleNamespace(name="b2")
    t = Track("123", [b1, b2], 1, "name1")
    # when
    name = t.name
    # then
    assert name == "name1"


def test_track_get_cached_instance():
    # given
    t1 = Track("123", [1, 2], 1, "")
    t2 = Track("123", [1, 2], 1, "")
    # then
    assert t1 is t2


def test_album_get_year_when_no_year_in_init():
    # given
    a = Album("1")
    setattr(a, "release_date", PartialDate(year=1999))
    # when
    y = a.year
    # then
    assert y == 1999


def test_EnmetEntity_re_init():
    # given
    class Test(EnmetEntity):
        pass
    # when
    obj1 = Test("1")
    obj2 = Test("1")
    # then
    assert obj1 is obj2


def test_create_default_cache(mocker):
    #given
    cs_mock = mocker.patch("src.enmet.enmet.CachedSession")
    cs_mock.return_value.get.return_value = SimpleNamespace(content="<HTML />", raise_for_status=lambda: None)
    cp_mock = mocker.patch("src.enmet.enmet._CachedSite._CACHE_PATH")

    class Dummy:
        RESOURCE = "ABC_resource"
        id = "123890"
        e = _CachedSite()
    # when
    result = Dummy().e
    # then
    assert result == BeautifulSoup("<html />", features="html.parser")
    assert cp_mock.method_calls == [call.mkdir(parents=True, exist_ok=True)]
    assert call(cache_name=ANY, backend="sqlite") in cs_mock.mock_calls
