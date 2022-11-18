# Enmet - The Encyclopaedia Metallum API

_Enmet_ is a programmatic API to Encyclopaedia Metallum - The Metal Archives site. It allows convenient access to specific Metal Archives data from python code. It is designed for ease of use and ease of development and maintenance.

What _Enmet_ is great for:
- Cleaning and extending tags of your CD rips/downloads collection. _Enmet_ was created, because I wanted to add some more metadata to my CD rips/downloads and found existing packages hard to use and/or hard to extend for my needs.
- Downloading selected information for further use.

What _Enmet_ is not suitable for:
- Data scraping 
- Data mining
- Using as a command line tool
- Uploading any data to MA
- Building own database of music information from scratch

Please note: _Enmet_ is a young project. Even though each release is supposed to be stable by itself, some breaking changes may occur even between minor versions. 

# Quickstart

_Warning, by default Enmet creates a cache file in \<settings\>/.enmet directory. Read [here](#caching) about Enmet caching._

```python
>>> import enmet
>>> megadeth = enmet.search_bands(name="Megadeth")[0]  # Search bands named "Megadeth" and pick the first one
>>> print(megadeth.discography)  # List discography (output truncated)
[<Album: Last Rites (4250)>, <Album: Killing Is My Business... and Business Is Good! (659)>, ...]
>>> print(megadeth.discography[0].discs[0].tracks) # Print tracks of the 1st album
[<Track: Last Rites / Loved to Deth (38701A)>, <Track: Mechanix (38702A)>, <Track: The Skull Beneath the Skin (38703A)>]
>>> print(megadeth.lineup)  # Print the current lineup
[<LineupArtist: Dave Mustaine (184)>, <LineupArtist: James LoMenzo (2836)>, <LineupArtist: Kiko Loureiro (3826)>, <LineupArtist: Dirk Verbeuren (1391)>]
>>> print([str(artist) for artist in megadeth.lineup])  # The lineup in some simpler form
['Dave Mustaine', 'James LoMenzo', 'Kiko Loureiro', 'Dirk Verbeuren']
```

# User guide
This section is intended for persons who want just to use _Enmet_.

Metal Archives data are made available in _Enmet_ by objects of a few classes. Each class represents some "thing", aka "entity": band (class `Band`), artist (class `Artist`), album (class `Album`) etc. Each object presents data via its properties (which can be again entity objects or just simple data) - so that `Band.name` is a string being the a band's name and `Band.discography` is a list of `Album` objects. Each `Album` object has in turn `Album.bands` property, which is a list of `Band` objects (as an album can be a split album by multiple bands); one of these objects is the starting `Band` object. And so on and on.

You can get all the available properties by calling `dir` on an object, for example `dir(Band(18))` returns `['country', 'discography', 'formed_in', 'genres', ...]`.

Mind that currently only a part of data available is covered.

### Enmet objects

There are 3 types of classes which present data in the same way, but differ a bit in handling:
- EnmetEntity subclasses: they represent "native" Metal Archives objects - this means objects which have their own identifiers in Metal Archives. Examples of these subclasses are Artist, Band, Album, Track etc. All they have `id` property containing relevant identifier. 
- DynamicEnmetEntity subclasses: they represent "dynamic" Metal Archives objects - entities, which don't have their identities in Metal Archives and thus no identifiers. Examples of these subclasses are `Disc` and `AlbumArtist`. Creation of these subclasses was necessary to preserve natural logic when manipulating entity objects; for example name of an album artist (represented by class `AlbumArtist`) stated on a physical media can be different from what appears on the artist's page in Metal Archives as name or full name.
- ExternalEntity: objects of these class represent entities external to Metal Archives, for example non-metal artist of a collaboration album. The objects have the property `name` and other properties depending on concrete object purpose. These entities have no own data pages in MetalArchives, they are just mentioned by name.

### Creating objects

There are two ways of creating the entity objects: search functions and standard object creation mechanism.
- [Search functions](#functions) are the primary way of creating Enmet objects. They are basically a way to determine what id has a looked for entity. They return a list of relevant objects, which you can scan to find out the ones of interest. Using just names for the purpose of object creation is not feasible, as too often there are multiple matches for a given name (there are fe. 3 _Inner Sanctum_ bands from Germany).
- All EnmetEntity objects can be also created by hand and most of the time all you need for this purpose is a relevant id. For example `Band("138")` gives you the same object as `search_bands(name="megadeth")[0]`.
   - Once you search for entities and get their ids, you can persist them between your code runs to speed up work the next time. 
   - Sometimes id is not sufficient, for example in the case of `Track` objects. The reason is that there is no web resources for them to query on Metal Archives site, and getting all the properties dynamically could be costly. However, there should be no need to create these objects manually.
- You should have no need to create manually either `DynamicEnmetEntity` or `ExternalEntity` objects. They are created in the background dynamically when needed.

## Caching

### Web caching

Working with a web site is costly in terms of time - fetching each page takes significant amount of time. Thus _Enmet_ uses on-disk cache to keep and reuse data pages downloaded from Metal Archives. The next time a page is needed, it is picked up from the local cache file instead of getting it from the web.

Searches, which also involve requesting data from Metal Archives, at NOT cached - each search fetches a new result. 

The cache by default is located in `%LOCALAPPDATA%\.enmet` or `~/.enmet` directory. The cache is handled by a `CachedSession` object from [_requests-cache_](https://requests-cache.readthedocs.io/en/stable/) package. Again by default, this is sqlite database named _enmet_data.sqlite_ with _no expiration set_ (pages are kept forever and never refreshed from Metal Archives site).

In order to control caching, you can both obtain the default cache object (for example to clean up old entries) and set your own cache. If you use your own cache, you need to set it each time you use _Enmet_, as there is no persistent configuration for it. The function to manipulate the cache is [`set_session_cache`](#functions).

There is no feature to disable session caching.

### Object caching

When using Enmet, some entities may appear in many objects. For example each album of a band refers to this band and each track refers to a band that performs it. In order to optimize memory usage, some objects are reused when there is an attempt to create another object for the same entity when an object for this entity already exists. This code sample prints out `True`:

```python

import enmet

megadeth = enmet.search_bands(name="Megadeth")[0]
megadeth2 = enmet.Band("138")
print(megadeth is megadeth2)
```
- To optimise memory usage, only actually used objects are cached. Once an object is nowehere referenced in your code, it is removed from the cache.

## Reference manual

Note: Any optional parameters in constructors that provide values related to an entity and which are not provided when creating the object, are resolved lazily later.

Note: Any "empty" values are returned as `None` or `[]`. This refers both to values nonexistent for a given entity and values with equvalen meaning (like "N/A", "Unknown" etc.).

### Classes

- `Album(EnmetEntity)`. This class represents an album. 
  - `__init__(self, id_: str, *, name: str = None, year: int = None)` `id_` is album identifier in Metal Archives. `name` is album name as appearing on the album's page. `year` is album release year.
  - Attributes and properties:
    - `id: str` - identifier
    - `name(self) -> str`
    - `bands(self) -> List[Band]`
    - `type(self) -> ReleaseTypes`
    - `year(self) -> int`
    - `release_date(self) -> PartialDate`
    - `label(self) -> str`
    - `format(self) -> str`
    - `reviews(self) -> Tuple[str, str]`
    - `discs(self) -> List[Disc]`
    - `lineup(self) -> List[AlbumArtist]`
    - `total_time(self) -> timedelta`
    - `guest_session_musicians(self) -> List["AlbumArtist"]`
    - `other_staff(self) -> List["AlbumArtist"]`
    - `additional_notes(self) -> str`
    - `last_modified(self) -> datetime` (time of the last modification of the album's page)
    - `other_versions(self) -> List["Album"]`
- `AlbumArtist(_EntityArtist)`. This class represent an artist performing on a specific album.
  - `__init__(self, id_: str, album_id: str, *, name: str = None, role: str = None)`. `id_` is the artist's identifier in Metal Archives. `album_id` is an album's identifier. `name` is the artist's name as stated on the album. `role` is the artist's role on the album.
  - Attributes and properties:
    - `name_on_album: str` - name of the artist as stated on the album. The name can be different than stated on the artist's page.
    - `album: Album` - the album object
    - `role: str` - a role that artist has on the album.
    - all remaining attributes and properties are identical as for `Artist`.
- `Artist(EnmetEntity)`. This class represents an artist (a person).
  - `__init__(self, id_)`. `id_` is artist identifier in Metal Archives.
  - Attributes and properties:
    - `id: str` - identifier
    - `name(self) -> str`
    - `real_full_name(self) -> str`
    - `age(self) -> str`
    - `place_of_birth(self) -> str`
    - `gender(self) -> str`
    - `biography(self) -> str`
    - `trivia(self) -> str`
    - `active_bands(self) -> Dict[Union[Band, ExternalEntity], List[Album]]`
    - `past_bands(self) -> Dict[Union[Band, ExternalEntity], List[Album]]`
    - `guest_session(self) -> Dict[Union[Band, ExternalEntity], List[Album]]`
    - `misc_staff(self) -> Dict[Union[Band, ExternalEntity], List[Album]]`
    - `links(self) -> List[Tuple[str, str]]`
    - `last_modified(self) -> datetime` (time of the last modification of the artist's page)
- `Band(EnmetEntity)`. This class represents a band.
  - `__init__(self, id_: str, *, name: str = None, country: Countries = None)`. `id_` is the band's identifier in Metal Archives. `name` is the band's name as stated on the band's page. `country` is the band's country of origin.
  - Attributes and properties:
    - `id: str` - identifier
    - `name(self) -> str`
    - `country(self) -> Countries`
    - `location(self) -> str`
    - `formed_in(self) -> int`
    - `years_active(self) -> List[str]`
    - `genres(self) -> List[str]`
    - `lyrical_themes(self) -> List[str]`
    - `label(self) -> str` (current or last known)
    - `lineup(self) -> List["LineupArtist"]` (current or last known)
    - `discography(self) -> List["Album"]`
    - `similar_artists(self) -> List["SimilarBand"]` (Note: There is naming inconseqence here on Metal Archives page - this list refers to bands, not artists, ie. persons. Property name follows Metal Archives wording, but otherwise the notion of "band" is used.)
    - `past_members(self) -> List["LineupArtist"]`
    - `live_musicians(self) -> List["LineupArtist"]`
    - `info(self) -> str` (free text information below header items)
    - `last_modified(self) -> datetime` (date of the last band page modification)
    - `status(self) -> Optional[BandStatuses]`
    - `links_official(self) -> List[Tuple[str, str]]` (returns list or tuples- url, page name)
    - `links_official_merchandise(self) -> List[Tuple[str, str]]` (returns list or tuples- url, page name)
    - `links_unofficial(self) -> List[Tuple[str, str]]` (returns list or tuples- url, page name)
    - `links_labels(self) -> List[Tuple[str, str]]` (returns list or tuples- url, page name)
    - `links_tabulatures(self) -> List[Tuple[str, str]]` (returns list or tuples- url, page name)
- `Disc(DynamicEnmetEntity)`. This class represents a disc of an album. More precisely, it is a container which holds some or all tracks of the album. Except for a CD, it can be in fact a physical cassette, VHS, DVD or even arbitrary partition in case of electronic releases - whatever Metal Archives considers a "disc". 
  - `__init__(self, album_id: str, number: int = 0, bands: List[Band] = None)`. `album_id` is id of an album the disc belongs to. `number` is ordinal number of the disc on the album (counted from 0). `bands` is a list of bands that perform tracks on the disc.
  - Attributes and properties:
    - `number(self) ->int` (disc number on the album counted from 1)
    - `name(self) -> Optional[str]` (disc name or None if the disc has no specific name)
    - `total_time(self) -> timedelta`
    - `tracks(self) -> List["Track"]`
- `ExternalEntity(Entity)`. This class represents entity external to Metal Archives, for example band or artist which appear on metal albums, but is not represented in Metal Archives itself.
  - `__init__(self, name: str):` `name` is data to store for the entity.
  - Attributes and properties:
    - `name` (data to store for the entity)
- `LineupArtist(_EntityArtist)`. This class represent an artist belonging to the current or the last known band's lineup.
  - `__init__(self, id_: str, band_id: str, *, name: str = None, role: str = None)`. `id_` is the artist's identifier in Metal Archives. `album_id` is an album's identifier. `name` is the artist's name as stated on the album. `role` is the artist's role on the album.
  - Attributes and properties:
    - `name_in_lineup: str` - name of the artist as stated in the lineup section. The name can be different than the one stated on the artist's page.
    - `band: Band` - the band object
    - `role: str` - a role that artist has in the lineup.
    - all remaining attributes and properties are identical as for `Artist`.
- `SimilarBand(DynamicEnmetEntity)`. This class represents a band in _Similar artists_ tab on another band's page.
  - `__init__(self, id_: str, similar_to_id: str, score: str, name: str = None, country: str = None, genres: str = None)`. `id_` is the band's identifier. `similar_to_id` is the id of a band which the given band is similar to. `score` is similarity score (number of user votes). `name` is the band's name. `country` is the band's country. `genres` is the band's genres.
  - Attributes and properties:
    - `band: Band` - the band object
    - `similar_to: Band` - the band given band is similar to
    - `score: int` - similarity score.
    - all remaining attributes and properties are identical as for `Band`.
- `Track(EnmetEntity)`. This class represents a track on an album. It's a bit different than the other EnmetEntity classes, as tracks don't have their own resources (pages) in Metal Archives.
  - `__init__(self, id_, bands: List[Band], number: int = None, name: str = None, time: timedelta = None, lyrics_info: Optional[bool] = None)`. `id_` a track's identifier. `bands` is a list of bands performing on the `Disc` which the track belongs to. `number` is the track's number on the disc (counter from 1). `name` is the track's name. `time` is the track's duration. `lyrics_info` is lyrics availability status (`None` if there is no information, `True` if a link to the lyrics is available, `False` it the track is marked as _instrumental_).
  - Attributes and properties:
    - `number: int` (the track's number on a disc counted from 1)
    - `time: timedelta` (the track's duration)
    - `name(self) -> str`
    - `band(self) -> Band`
    - `lyrics(self) -> Optional[Union[bool, str]]` (lyrics; `False` if the track is marked as instrumental, `None` if there is no track informaction, lyrics text otherwise)


### Functions
-  `set_session_cache(**kwargs) -> CachedSession`. Set HTTP requests caching.
    - The parameters are identical as for `CachedSession` class of the `requests-cache` package.
    - This function returns cache object set for `Enmet`.
    - If you provide no parameters, you will get the default cache object.
    - Providing any set of parameters excluding both `cache_name` and `backend` allows to use the default cache with modified parameters.
    - You can change cache at any moment. If you change cache before any other _Enmet_ usage, the default cache will not get created.
- `search_bands(*, name: str = None, strict: bool = True, genre: str = None, countries: List[Countries] = None, formed_from: int = None, formed_to: int = None) -> List[Band]`. This function searches for bands, returning a list of `Band` objects. Parameters:
  - `name` - band name
  - `strict` - force strict matching for `name` (case-insensitive)
  - `genre` - genre name (substring matching)
  - `countries` - list of Countries enum members
  - `formed_from` and `formed_to` - year range for band formation
- `search_albums(*, name: str = None, strict: bool = None, band: str = None, band_strict: bool = None, year_from: int = None, month_from: int = None, year_to: int = None, month_to: int = None, genre: str = None, release_types: List[ReleaseTypes] = None)`. This function searches for albums, returning a list of `Album` objects. Parameters:
  - `name` - album name
  - `strict` - force strict matching for `name` (case-insensitive)
  - `band` - name of a band performing the album
  - `band_strict` - force strict matching for `band_name` (case-insensitive)
  - `year_from`, `month_from`, `year_to`, `month_to` - time range for album release date
  - `genre` - genre name (substring matching)
  - `release_types` - list of ReleaseType enum members
- `random_band() -> Band` - get a random band from The Metal Archives. This function is used mainly for testing.   

### Enums
- `Countries`. This is a dynamic enum with available countries.
- `ReleaseTypes`. This is an enum keeping available release (album) types.
- `BandStatuses`. Available band statuses.

### Helper classes
- `PartialDate`. This class enables keeping a date that has year, month and day, only year and month or only year. Its objects have integer `year`, `month` and `day` properties, where the two latter may also be `None`. 

# Developer guide
This section is intended for persons who want to contribute to _Enmet_. As _Enmet_ code is pretty straightforward, it just explains designs and concepts. 

Two extreme approaches to The Metal Archives API could be just providing text values for elements found on Metal Archives pages _and_ building complete data model for all the Metal Archives data, loading data into it and exposing the data via some query language.  

_Enmet_ is somewhere in the middle: there is object model available, but it doesn't try to cover all the data (at least for now) or stick to Metal Archives model acccurately, and data are exposed via static properties.

### Objects

There are two object layers used:
1. Subclasses of class `Page` represent responses to HTTP requests sent to Metal Archives. They expose data from the responses via properties. The extracted data are "raw" data, ie. only built-in python types with minimal cleanup. RESOURCE attribute in `Page` classes determines resource to query and it is None in abstract classes. 
    1. Subclasses of `SearchResultPage(Page)` represent responses to search HTTP requests. They have a single property that returns a list, where each list element is a tuple of simple data pertaining to a single found entity (`List[Tuple[str, ...]]`) - for example a list where each element is (band name, band country, formation year) tuple. These subclasses process JSON returned by requests sent to search resources.
    2. Subclasses of `DataPage(Page)` represent responses to entity HTTP requests. Sometimes a `DataPage` subclass represents just what can be seen in a browser for an entity, but most of the time there is no 1:1 correspondence between what a user sees in a browser and some `DataPage` subclass. These subclasses have multiple properties that make available different pieces of data found on the corresponding webpages. `_CachedSite` descriptor in `_DataPage` class returns BeautifulSoup objects for requests, thus data extraction in `_DataPage` subclasses is done with CSS selectors. 
2. Concrete subclassess of `Entity` class represent items like band, album or track. They use `DataPage` objects and other `Entity` objects to present full entity via properties. There are 3 types of `Entity` subclasses:
   1. Class `ExternalEntity` represents entity from outside of The Metal Archives (without MA id), like non-metal musician without MA page participating in a release. This class has property `name`, which provides simple textual information about the entity, and other properties depending on what the object represents.
   2. Class `EnmetEntity` represents Metal Archives entity which has its own id (like band).
   3. Class `DynamicEnmetEntity` represents Metal Archives entity without own identity (id). Using this class was necessary in order to be able all availabe information in consistent and logical manner.

All properties across classes are evaluated lazily on access, which may include fetching a page from Metal Archives, converting it to BeautifulSoup object, selecting data with CSS selectors and then converting them to objects. Thus a scenario when you get a 1000 band names, then lineups for these bands and then discographies for them _may_ result in repeatedly querying Metal Archives for the same data if the HTTP cache (see below) is not caching them. (Also conversion to BeautifulSoup objects would need to be repeated, but this problem is a few orders of magnitude smaller).

This is a design choice aimed at balancing performance and code clarity, while assuring API simplicity for users.  

### Caching and object deduplication

Working with Metal Archives can involve many HTTP requests and creation of large number of objects which often describe the same entity (for example each track has a property which determines the band it is performed by).

To mitigate negative effects of these factors and to improve general responsiveness, there are following methods applied (_mind that no related tests have been done, there is just some common sense applied_):
- HTTP session cache in `_CachedSite` class from `requests-cache` package. This on-disk cache stores responses obtained from Metal Archives servers for `DataPages` objects. Read more [here](https://requests-cache.readthedocs.io/en/stable/).
- BeautifulSoup objects cache in `_CachedSite` class using `@lru_cache`. This fixed-size (`_BS_CACHE_SIZE`) cache keeps BeautifulSoup objects created from HTTP response pages. It is supposed to increase performance when multiple properties of a set of objects are accessed.
- Deduplication of `DataPage` and `Entity` objects using `CachedInstance` mixin class. Only one instance of relevant object is created and then re-used when there is attempt to create an object referring to the same page or entity. In this way fe. all `Album` objects in a band's discography can refer to the same `Band` object. Object identities are determined by static `hash(*args, **kwargs) -> Tuple` functions which provide hashable value used by `CachedInstance` along with object type to determine whether a new object should be created or an existing object used.


### Unit tests

`test_enmet.py` uses pytest and pytest-mock to do some testing. Part of tests actually connects to Metal Archives, so they are not quite unit tests. They are not very clean, but cover the code nicely.

# ToDo items

- Add cardinality one properties (album.tracks, album.band etc) with corresponding exception system.
- Add enums where relevant (band.status, genres - ?)
- Make more data available