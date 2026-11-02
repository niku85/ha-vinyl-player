"""Tests for the dependency-free Discogs helpers (no Home Assistant needed)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).parents[1] / "custom_components" / "vinyl_player" / "discogs.py"
_spec = importlib.util.spec_from_file_location("vinyl_discogs", _PATH)
discogs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(discogs)


def item(rid, title, artists, fmt="Vinyl", year=1969, **extra):
    return {
        "id": rid,
        "instance_id": rid * 10,
        "date_added": "2024-01-01T10:00:00-08:00",
        "rating": 0,
        "basic_information": {
            "id": rid,
            "master_id": 1,
            "title": title,
            "year": year,
            "artists": artists,
            "formats": [{"name": fmt, "qty": "1", "descriptions": ["LP", "Album"]}],
            "labels": [{"name": "Apple Records", "catno": "PCS 7088"}],
            "genres": ["Rock"],
            "styles": ["Pop Rock"],
            "cover_image": f"https://i.discogs.com/x/{rid}.jpeg",
            "thumb": f"https://i.discogs.com/t/{rid}.jpeg",
            **extra,
        },
    }


def test_clean_artist_and_join():
    assert discogs.clean_artist("Nirvana (2)") == "Nirvana"
    artists = [
        {"name": "Simon (3)", "join": "&"},
        {"name": "Garfunkel", "join": ""},
    ]
    assert discogs.join_artists(artists) == "Simon & Garfunkel"
    assert discogs.join_artists([{"name": "A", "join": ","}, {"name": "B"}]) == "A, B"
    assert discogs.join_artists([]) == "Unknown Artist"


def test_build_releases_filters_dedupes_and_sorts():
    items = [
        item(3, "Nevermind", [{"name": "Nirvana (2)"}], year=1991),
        item(1, "Abbey Road", [{"name": "The Beatles"}]),
        item(1, "Abbey Road", [{"name": "The Beatles"}]),  # second copy
        item(2, "Some CD", [{"name": "Aaa"}], fmt="CD"),
    ]
    releases = discogs.build_releases(items, vinyl_only=True)
    assert [r["id"] for r in releases] == [1, 3]  # "The Beatles" sorts under B
    assert releases[1]["artist"] == "Nirvana"
    assert releases[0]["format_text"] == "Vinyl, LP, Album"
    assert releases[0]["catno"] == "PCS 7088"
    assert len(discogs.build_releases(items, vinyl_only=False)) == 3


def test_export_document():
    doc = discogs.build_export("me", discogs.build_releases([item(1, "X", [{"name": "Y"}])]))
    assert doc["version"] == 1 and doc["count"] == 1 and doc["username"] == "me"


def test_cover_filename():
    assert discogs.cover_filename(5, "https://i.discogs.com/a/b.jpeg") == "5.jpg"
    assert discogs.cover_filename(5, "https://x/y.png?z=1") == "5.png"
    assert discogs.cover_filename(5, None) == "5.jpg"


def test_parse_tracklist():
    release = {
        "tracklist": [
            {"type_": "heading", "title": "Side One", "position": ""},
            {"type_": "track", "title": "Come Together", "position": "A1", "duration": "4:20"},
            {
                "type_": "index",
                "title": "Medley",
                "sub_tracks": [
                    {"type_": "track", "title": "Golden Slumbers", "position": "B5a", "duration": "1:31"},
                    {"type_": "track", "title": "Carry That Weight", "position": "B5b", "duration": ""},
                ],
            },
        ]
    }
    tracks = discogs.parse_tracklist(release)
    assert [t["title"] for t in tracks] == ["Come Together", "Golden Slumbers", "Carry That Weight"]
    assert tracks[0]["duration"] == 260 and tracks[2]["duration"] is None
    assert discogs.side_of("B5a") == "B"


def test_merge_user_fields_and_tags():
    new = discogs.build_releases([item(1, "Abbey Road", [{"name": "The Beatles"}])])
    old = [{"id": 1, "ma_query": "Beatles - Abbey Road (Remastered)", "tag_id": ["x", "y"], "hidden": True}]
    discogs.merge_user_fields(new, old)
    assert new[0]["ma_query"].endswith("(Remastered)") and new[0]["hidden"] is True
    assert discogs.tag_ids(new[0]) == ["x", "y"]
    assert discogs.tag_ids({"tag_id": " a1b2 "}) == ["a1b2"]


def test_album_matches():
    rec = {"title": "The Dark Side Of The Moon", "artist": "Pink Floyd", "artists": ["Pink Floyd"]}
    assert discogs.album_matches(rec, {"name": "The Dark Side of the Moon (2011 Remaster)", "artists": [{"name": "Pink Floyd"}]})
    assert not discogs.album_matches(rec, {"name": "The Wall", "artists": [{"name": "Pink Floyd"}]})
    assert not discogs.album_matches(rec, {"name": "The Dark Side Of The Moon", "artists": [{"name": "Tribute Band"}]})
