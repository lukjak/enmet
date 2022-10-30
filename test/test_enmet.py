from datetime import timedelta, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, ANY

import pytest
from bs4 import BeautifulSoup

from enmet import set_session_cache, search_bands, Artist, PartialDate, Band, Countries, search_albums, ReleaseTypes, \
    Album, Track, EnmetEntity, ExternalEntity
from enmet.common import datestr_to_date
from enmet.pages import _CachedSite, ArtistPage


@pytest.fixture(scope="session", autouse=True)
def temp_cache():
    Path("enmet_test_dummy.sqlite").unlink(missing_ok=True)
    set_session_cache(cache_name="enmet_test_dummy")
    yield


def test_band():
    band = search_bands(name="megadeth", strict=True, formed_from=1980)[0]
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
    assert all(x in dir(band.lineup[0]) for x in ["name_in_lineup", "band"])
    assert len(band.past_members) > 22
    assert len(band.live_musicians) > 5
    assert band.discography[0].release_date == PartialDate(year=1984, month="March", day=9)
    assert repr(band.discography[0].discs[0]) == "<Disc: None>"
    assert set(dir(band)) == {'country', 'discography', 'formed_in', 'genres', 'info', 'label', 'last_modified',
                              'lineup', 'live_musicians', 'location', 'lyrical_themes', 'name', 'past_members',
                              'similar_artists', 'status', 'years_active'}
    # similar_artists
    assert len(band.similar_artists) > 180
    assert band.similar_artists[0].score > 490
    assert band.similar_artists[0].similar_to is band
    assert band.similar_artists[0].name == "Metallica"
    assert "Metallica" in repr(band.similar_artists[0])
    assert set(dir(band.similar_artists[0])) == {'country', 'discography', 'formed_in', 'genres', 'info', 'label',
                                                 'last_modified', 'lineup', 'live_musicians', 'location',
                                                 'lyrical_themes', 'name', 'past_members', 'score', 'similar_artists',
                                                 'similar_to', 'status', 'years_active'}
    assert band.info.startswith("Pictured from left to right")
    assert band.last_modified >= datetime(2022, 10, 10, 15, 58, 54)


def test_band_no_formed_in_no_biography():
    # given
    b = search_bands(name="witches of moodus")[0]
    # then
    assert b.formed_in is None
    assert b.info.startswith("Compilation")
    # assert b.lineup[1].biography is None  # no Trivia or Biography section


def test_band_no_similar_artists():
    # given
    band = Band("32039")
    # then
    assert band.similar_artists == []


def test_artist():
    # given
    a = Artist(184)
    # then
    assert "1961" in a.age
    assert a.place_of_birth == 'United States (La Mesa, California)'
    assert a.gender == "Male"
    assert a.biography.startswith("Mustaine was born in La Mesa")
    assert a.trivia.startswith("Dave performed alongside Dream Theater")
    assert set(dir(a)) == {'active_bands', 'age', 'biography', 'gender', 'guest_session', 'links', 'misc_staff', 'name',
                           'past_bands', 'place_of_birth', 'real_full_name', 'trivia'}
    assert list(a.active_bands.keys()) == [Band(138)]
    assert set(a.past_bands) == {Band(3540464105), Band(4984), Band(125), Band(3540461857),
                                 ExternalEntity("Fallen Angels", role="Vocals, Guitars (1983)"), ExternalEntity("Panic", role="Guitars (?-1981)")}
    assert set(a.guest_session) == {Band(401), Band(37), Band(706), Band(343)}
    assert set(a.misc_staff) == {Band(138), Band(4984), Band(125), Band(3540461857), Band(401), Band(343), Band(25),
                                 Band(1831)}
    assert len(a.links) == 10


def test_artist_two_extended_sections_first_no_read_more():
    # given
    a = Artist(107)
    # then
    assert a.biography.startswith("Adrian Smith is an English guitarist")


def test_artist_less_extras():
    # given
    a = Artist(14883)
    # then
    assert a.trivia.startswith("DiSanto was arrested")
    assert a.biography is None


def test_ArtistPage_with_band_and_album_alias():
    # given
    a = ArtistPage(15954)
    # then
    assert [key[3] for key in a.past_bands if key[0] and "/510#" in key[0]][0] == "John Syriis"
    albums = [v for v in a.active_bands.values() if len(v) > 5][0]
    assert [key[3] for key in albums if "No Other Godz Before Me" in key[1]][0] == "Johnny Cyriis"


def test_band_splitup():
    band = Band("72")
    assert band.label == "Nuclear Blast"


def test_search_bands_set_country(mocker):
    # given
    asp_mock = mocker.patch("enmet.search.BandSearchPage")
    # when
    search_bands(name="dummy", countries=[Countries.POLAND])
    # then
    assert asp_mock.mock_calls[0] == call(
        {'bandName': 'dummy', 'exactBandMatch': '', 'genre': '', 'yearCreationFrom': '', 'yearCreationTo': '',
         'country[]': ['PL']})


def test_search_bands_no_params():
    # when
    bands = search_bands()
    # then
    assert bands == []


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
    assert len(album.other_staff) == 8
    assert album.additional_notes.startswith("Trivia")
    assert set(dir(album)) == {'additional_notes', 'bands', 'catalog_id', 'discs', 'format', 'guest_session_musicians',
                               'label', 'lineup', 'name', 'other_staff', 'release_date', 'reviews', 'total_time',
                               'type', 'year'}
    assert set(dir(album.lineup[0])) == {'active_bands', 'age', 'album', 'biography', 'gender', 'guest_session',
                                         'links', 'misc_staff', 'name', 'name_on_album', 'past_bands', 'place_of_birth',
                                         'real_full_name', 'role', 'trivia'}
    assert dir(album.discs[0]) == ['name', 'number', 'total_time', 'tracks']
    assert dir(album.discs[0].tracks[0]) == ['band', 'lyrics', 'name', 'number', 'time']
    assert "AlbumArtist" in repr(album.lineup[0])
    assert str(album.lineup[0]) == "Udo Dirkschneider"


def test_search_albums_with_years(mocker):
    # given
    asp_mock = mocker.patch("enmet.search.AlbumSearchPage")
    # when
    search_albums(name="dummy", year_from=1991, year_to=1992)
    # then
    assert asp_mock.mock_calls[0] == call(
        {'releaseTitle': 'dummy', 'exactReleaseMatch': '', 'bandName': '', 'exactBandMatch': '',
         'releaseYearFrom': 1991, 'releaseMonthFrom': '', 'releaseYearTo': 1992, 'releaseMonthTo': '', 'genre': '',
         'releaseType[]': []})


def test_search_albums_no_params():
    # when
    albums = search_albums()
    # then
    assert albums == []


def test_album_missing_values():
    # given
    album = Album("3509")
    # then
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


def test_album_session_musicians():
    album = Album("534606")
    assert len(album.guest_session_musicians) == 5


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
    result = datestr_to_date(datestr)
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
    mocker.patch("enmet.pages._DataPage._get_header_item", lambda p1, p2: val)
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
    mocker.patch("enmet.pages._DataPage._get_header_item", lambda p1, p2: Dummy())
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
    cs_mock = mocker.patch("enmet.pages.CachedSession")
    cs_mock.return_value.get.return_value = SimpleNamespace(content="<HTML />", raise_for_status=lambda: None)
    cp_mock = mocker.patch("enmet.pages._CachedSite._CACHE_PATH")

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


def test_ExternalEntity_dir():
    # given
    ee = ExternalEntity("abc", data=123)
    # then
    assert set(dir(ee)) == {"name", "data"}

