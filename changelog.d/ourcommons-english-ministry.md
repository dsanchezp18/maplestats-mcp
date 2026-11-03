### Fixed

- `ourcommons_get_ministry` in English: the House of Commons moved the English ministry feed
  from `/Members/en/ministries/XML` to `/members/en/ministry/xml`; the old address answered
  its 404 page, so the English call failed (French was fixed in 0.4.4).
