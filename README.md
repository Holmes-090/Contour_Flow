# Contour Flow (QGIS plugin)

A single-purpose QGIS plugin for making **editable vector contour lines** from
point measurements or from an existing elevation raster.

> **Status: early development (experimental).** Not yet published. The
> workflows below are implemented. They have been checked offline but not
> yet fully exercised in QGIS (see [TESTING.md](TESTING.md)).

> **Professional review required.** Interpolated contours are *estimates*
> derived from the supplied data and the chosen method. They do not add
> information that is not in the data. Review them professionally before
> using them for technical interpretation, e.g. groundwater flow directions,
> earthworks, or regulatory reporting.

## What it is (and is not)

Contour Flow does one job: turn values into contour lines you can edit.

It is **not** a general GIS toolkit, a hydrogeology suite, or a replacement
for SAGA, GRASS or the Processing Toolbox. Every GIS step uses an algorithm
that already ships with QGIS or GDAL. The plugin puts them behind one
focused, documented workflow and records exactly what it did.

The value field can be anything numeric: groundwater elevation, ground
surface, bedrock, survey elevation, concentrations, and so on. The plugin
makes no assumption about its meaning or units. Source layers are never modified.

## Workflows

**Point input:** point layer → numeric field (all or selected features) →
TIN or IDW → extent and optional boundary → interpolate → contour → clip →
optional smoothing → major/minor → labels and style → editable line layer.

**Raster input:** raster/DEM → band → optional boundary → contour → clip →
optional smoothing → major/minor → labels and style → editable line layer.

## Features

### Interpolation: TIN or IDW

| Method | What it does | When to use |
|---|---|---|
| **TIN, linear** | Triangulates the points and interpolates linearly inside each triangle. Values never exceed the data range. No values outside the points' convex hull. | Default. Honest, reproducible, good for sparse data such as wells. |
| **TIN, Clough-Toucher** | Smooth (cubic) surface on the same triangulation. Can slightly over- or undershoot the data. | Smoother-looking contours from the same data. |
| **IDW** | Inverse distance weighting: each cell is a weighted mean of all points. A higher **power** gives near points more weight (default 2). Values stay within the data range. It produces "bull's-eyes" around points and **extrapolates** everywhere in the extent. | Dense, evenly spread data. Use with care beyond the points. |

Cell size is automatic (about 500 cells along the longer side of the
extent) or set by you, in the point layer's CRS units.

### Extent (point input)

- **Bounding box of usable points** (default).
- **Convex hull** of usable points.
- **Convex hull + buffer**: the buffer is in the layer's CRS units. You get a
  warning if the CRS is geographic.
- **Boundary polygon**: the selected boundary is both the extent and the clip.
- **Custom extent**: drawn, taken from a layer, or typed.

The plugin never extrapolates silently. If part of the area lies outside the
points' convex hull, the summary says so. For IDW, this is an **IMPORTANT**
warning.

### Boundary clipping

Choose a polygon layer, using all features or only the selected ones, for
point or raster input. The boundary may use a different CRS; it is
transformed with the project's transformation settings. Multipart polygons
are supported, and invalid polygons are repaired (and reported). The contour
lines are clipped **exactly** to the boundary.

### Duplicate locations

Points at exactly the same location are grouped:

- **Equal values:** a warning, and one point is used.
- **Different values:** an **IMPORTANT** warning with examples. These may be
  different wells, screens or intervals.

You choose what happens: *keep the first value* (default), *average*, or
*stop*.

### Contour intervals

- **Automatic:** a "nice" interval (1, 2, 2.5 or 5 × 10ⁿ) aiming for an
  approximate number of contours (default 10), based on the value range.
- **Fixed:** any positive interval.

Levels are multiples of the interval. A run with no levels, or with more than
1000, is refused.

### Major and minor contours

*Major contour every N intervals* sets the field `is_major` (1/0). Example:
interval 0.25 and every 4 gives majors at 100.0, 101.0, 102.0, … Major lines
are drawn thicker.

### Smoothing (optional)

Uses QGIS *Smooth*, Chaikin corner cutting:

- **Light:** 1 iteration, offset 0.25.
- **Medium:** 2 iterations, offset 0.25.
- **Custom:** 1–5 iterations, offset 0.05–0.5.

Smoothing changes line geometry only, never the point values or the surface.
It is cosmetic and can move lines slightly away from the interpolated values,
so it is off by default. Smoothed layers are named "… smoothed" and the
metadata records the settings. Tick *Also keep an unsmoothed copy* to get both.

### Labels and styles

- **Labels:** native QGIS labels on `value`, either all contours or major
  contours only. You choose the decimals. Labels are curved along the line
  with a white buffer.
- **Style presets:** Neutral (black), Topographic (brown), Groundwater (blue).

Everything is ordinary QGIS styling, so you can change it in Layer Properties.

### Output

- **Contours:**
  - **Temporary layer** (default). Save it with *Make Permanent*.
  - **GeoPackage:** a new layer in a new or existing `.gpkg`. An existing
    layer is never overwritten; a clashing name gets a `_2` suffix and a
    warning. The style is stored in the GeoPackage.
- **Interpolated surface** (point input only): not added, a temporary raster,
  or a GeoTIFF. An existing file gets a new name.
- **Attributes:** `value` (the contour level) and `is_major`.
- **Metadata:** all processing settings, warnings and the review disclaimer
  are stored once per layer (*Layer Properties ▸ Metadata*), not on every feature.

### Summary, progress and cancel

- The **Summary** section previews the run before you start it:
  - point input: usable and skipped points;
  - raster input: band;
  - both: value range, method, cell size, extent, interval and approximate
    number of levels.
- During the run, a progress dialog shows each stage and has a working
  **Cancel** button.
- A failed or cancelled run leaves no partial outputs behind.

## Intended users

QGIS users, hydrogeologists, environmental consultants, geologists, and
survey and GIS technicians.

## Target QGIS versions

| | Version | Notes |
|---|---|---|
| Minimum supported | **QGIS 3.44** | The current Long Term Release (LTR) and the final QGIS 3.x series. |
| Recommended for development | **QGIS 3.44 LTR** | Primary test environment. |
| Second target | **QGIS 4.x** | Qt 6. The code uses `qgis.PyQt` and scoped enums; not yet tested on 4.x. |
| Maximum declared | 4.99 | Set in `metadata.txt`; required for QGIS 4 to load the plugin. |

See [DEVELOPMENT.md](DEVELOPMENT.md#target-qgis-versions) for the reasoning.

## Current limitations

- **Processing runs in the QGIS main thread.** A progress dialog with Cancel
  is shown, but QGIS cannot be used for other work until the run finishes.
- Contour levels are always multiples of the interval (no base offset).
- Only exact duplicate coordinates are detected. Near-coincident points
  (e.g. 0.1 m apart) are not flagged.
- The summary refreshes automatically only for inputs up to 100,000 features
  or 50 million raster cells. For larger inputs, press *Refresh summary*.
- For raster input with automatic intervals, the value range is that of the
  whole band, even when a boundary is used.
- Only file-based (GDAL) rasters can be contoured.
- No groundwater-specific workflow yet (aerial basemaps, well labels and so
  on are planned separately).
- Not published to the official QGIS plugin repository. The author, e-mail
  and repository URLs in `metadata.txt` are placeholders.

## Development status

| Milestone | Scope | Status |
|---|---|---|
| 0–2 | Repository, plugin shell, input selection | Done (tested in QGIS 3.44) |
| Core engine | Data checks, TIN, raster contours, intervals, editable output | Implemented; offline-checked |
| Professional controls | IDW, extents, clipping, duplicates, smoothing, major/minor, labels, styles, GeoPackage, summary, progress | Implemented; offline-checked, awaiting QGIS test |
| Later | Groundwater workflow, release polish | Not started |

See [CHANGELOG.md](CHANGELOG.md) for details.

## Installation

- **Developers:** link the `contour_flow/` folder into your QGIS profile
  as described in [DEVELOPMENT.md](DEVELOPMENT.md).
- **Users (future):** install from the official QGIS plugin repository via
  *Plugins ▸ Manage and Install Plugins*, or from a ZIP file via
  *Plugins ▸ Manage and Install Plugins ▸ Install from ZIP*.

The Processing plugin (a core QGIS plugin, enabled by default) must be enabled.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md): how the code is organised and why.
- [DEVELOPMENT.md](DEVELOPMENT.md): QGIS setup, Processing algorithms used, debugging.
- [TESTING.md](TESTING.md): testing philosophy, automated tests and the QGIS acceptance test.
- [CHANGELOG.md](CHANGELOG.md): version history.

## License

Contour Flow is free software, licensed under the
**GNU General Public License, version 2 or (at your option) any later version**
(`GPL-2.0-or-later`). See [LICENSE](LICENSE). This matches QGIS's own license
and meets the requirements of the official QGIS plugin repository.
