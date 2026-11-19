# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic, fictional GIS fixtures for the real-QGIS integration tests.

Everything is generated locally (nothing is downloaded). Values are chosen so
results are predictable:

* **Points** (EPSG:32633, UTM 33N), offsets 0-100 m from (500000, 5000000).
  Valid values lie exactly on the plane ``elev = 100 + 0.03*dx + 0.01*dy``
  (range 100-104), so a linear TIN reproduces that plane. The data also has
  one NULL, one equal-value duplicate location, one conflicting duplicate, a
  text field (must not be offered as a value field) and an integer field.
* **Boundary in WGS84** (EPSG:4326): a quadrilateral, stored in another CRS
  on purpose. In UTM it is (10,10)-(90,10)-(90,60)-(10,90).
* **Multipart / invalid boundary** (EPSG:32633): feature 1 is a two-part
  multipolygon; feature 2 is a self-intersecting "bow-tie" (invalid but
  repairable).
* **Gradient raster** (EPSG:32633): 200 x 100 cells of 1 m, value
  ``50 + 0.1 * column`` (column 0-199, so range 50.0-69.9), Float32, NoData -9999.
* **Groundwater wells** (EPSG:32633), offsets 0-200 m: heads on the plane
  ``head = 100 - 0.01*dx + 0.01*dy``, which falls to the east and to the
  south, so groundwater flows to the **south-east** (azimuth 135 degrees) with
  a hydraulic gradient of ``0.01 * sqrt(2)``. Fields: ``head`` (double),
  ``mp_elev`` and ``dtw`` (head = mp_elev - dtw), ``ground`` (head + 3) and
  ``wl_text`` (heads as padded text). Four records have no usable head: NULL,
  "Dry", "N/A" and blank.
* **Groundwater QA wells**: the 13 valid wells with one off-trend head
  (+1.5 m), one head above ground and one nested well at the same location
  with a different head.
* **Groundwater boundary in WGS84**: the UTM rectangle (20,20)-(180,120).
"""

import os

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

UTM = "EPSG:32633"
WGS84 = "EPSG:4326"
X0, Y0 = 500000.0, 5000000.0


def plane(dx, dy):
    """Exact elevation of the fixture plane at offsets (dx, dy)."""
    return 100.0 + 0.03 * dx + 0.01 * dy


# (id, dx, dy, elev or None, name)
POINTS = [
    (1, 0, 0, plane(0, 0), "corner SW"),
    (2, 100, 0, plane(100, 0), "corner SE"),
    (3, 0, 100, plane(0, 100), "corner NW"),
    (4, 100, 100, plane(100, 100), "corner NE"),
    (5, 50, 50, plane(50, 50), "centre"),
    (6, 25, 75, plane(25, 75), "W6"),
    (7, 75, 25, plane(75, 25), "W7"),
    (8, 80, 80, None, "NULL value"),
    (9, 25, 75, plane(25, 75), "equal duplicate of 6"),
    (10, 75, 25, 99.0, "conflicting duplicate of 7"),
]
VALID_DISTINCT_POINTS = 7

BOUNDARY_UTM_WKT = "POLYGON((500010 5000010, 500090 5000010, 500090 5000060, 500010 5000090, 500010 5000010))"
MULTI_UTM_WKT = (
    "MULTIPOLYGON(((500005 5000005, 500030 5000005, 500030 5000030, 500005 5000030, 500005 5000005)),"
    "((500060 5000060, 500095 5000060, 500095 5000095, 500060 5000095, 500060 5000060)))"
)
BOWTIE_UTM_WKT = "MULTIPOLYGON(((500040 5000040, 500060 5000060, 500060 5000040, 500040 5000060, 500040 5000040)))"

RASTER_COLUMNS, RASTER_ROWS, RASTER_CELL = 200, 100, 1.0
RASTER_NODATA = -9999.0


def raster_value(column):
    return 50.0 + 0.1 * column


def gw_head(dx, dy):
    """Exact head of the groundwater fixture plane (flow to the south-east)."""
    return 100.0 - 0.01 * dx + 0.01 * dy


GW_GRADIENT = 0.01 * 2 ** 0.5
GW_AZIMUTH = 135.0
GW_WELLS = [(i + 1, dx, dy) for i, (dx, dy) in enumerate([
    (0, 0), (100, 0), (200, 0), (0, 100), (100, 100), (200, 100), (0, 200), (100, 200), (200, 200),
    (50, 150), (150, 50), (150, 150), (50, 50),
])]
#: (id, dx, dy, wl_text) records without a usable head.
GW_UNUSABLE = [(14, 60, 120, None), (15, 140, 90, "Dry"), (16, 90, 160, "N/A"), (17, 170, 20, "  ")]
GW_VALID = len(GW_WELLS)
GW_BOUNDARY_UTM_WKT = "POLYGON((500020 5000020, 500180 5000020, 500180 5000120, 500020 5000120, 500020 5000020))"
GW_OUTLIER_WELL, GW_ABOVE_GROUND_WELL, GW_NESTED_WELL = 13, 9, 5


def _write_vector(layer, path, name):
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = name
    options.actionOnExistingFile = (
        QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
        if os.path.exists(path)
        else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
    )
    error, *_rest, message = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, path, QgsCoordinateTransformContext(), options
    )
    if error != QgsVectorFileWriter.WriterError.NoError:
        raise RuntimeError(f"Could not write fixture {name}: {message}")
    return f"{path}|layername={name}"


def _points_layer():
    layer = QgsVectorLayer(
        f"Point?crs={UTM}&field=id:integer&field=elev:double&field=name:string", "points", "memory"
    )
    features = []
    for pid, dx, dy, elev, name in POINTS:
        feature = QgsFeature(layer.fields())
        feature.setAttributes([pid, elev, name])
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(X0 + dx, Y0 + dy)))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


def _boundary_wgs84_layer():
    geometry = QgsGeometry.fromWkt(BOUNDARY_UTM_WKT)
    geometry.transform(
        QgsCoordinateTransform(
            QgsCoordinateReferenceSystem(UTM), QgsCoordinateReferenceSystem(WGS84), QgsCoordinateTransformContext()
        )
    )
    layer = QgsVectorLayer(f"Polygon?crs={WGS84}&field=name:string", "boundary_wgs84", "memory")
    feature = QgsFeature(layer.fields())
    feature.setAttributes(["site"])
    feature.setGeometry(geometry)
    layer.dataProvider().addFeatures([feature])
    return layer


def _gw_layer(qa=False):
    layer = QgsVectorLayer(
        f"Point?crs={UTM}&field=well_id:string&field=head:double&field=mp_elev:double&field=dtw:double"
        "&field=ground:double&field=wl_text:string",
        "gw_qa_wells" if qa else "gw_wells", "memory",
    )
    rows = []
    for wid, dx, dy in GW_WELLS:
        head = gw_head(dx, dy)
        ground = head + 3.0
        if qa and wid == GW_OUTLIER_WELL:
            head += 1.5
        if qa and wid == GW_ABOVE_GROUND_WELL:
            ground = head - 0.4
        mp = ground + 0.5
        rows.append((f"MW-{wid}", dx, dy, head, mp, mp - head, ground, f" {head:.3f} "))
    if qa:
        dx, dy = next((dx, dy) for wid, dx, dy in GW_WELLS if wid == GW_NESTED_WELL)
        head = gw_head(dx, dy) + 0.7
        rows.append((f"MW-{GW_NESTED_WELL}D", dx, dy, head, head + 3.5, 3.5, head + 3.0, f"{head:.3f}"))
    else:
        for wid, dx, dy, text in GW_UNUSABLE:
            ground = gw_head(dx, dy) + 3.0
            rows.append((f"MW-{wid}", dx, dy, None, ground + 0.5, None, ground, text))
    features = []
    for well_id, dx, dy, *values in rows:
        feature = QgsFeature(layer.fields())
        feature.setAttributes([well_id, *values])
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(X0 + dx, Y0 + dy)))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


def _gw_boundary_wgs84_layer():
    geometry = QgsGeometry.fromWkt(GW_BOUNDARY_UTM_WKT)
    geometry.transform(
        QgsCoordinateTransform(
            QgsCoordinateReferenceSystem(UTM), QgsCoordinateReferenceSystem(WGS84), QgsCoordinateTransformContext()
        )
    )
    layer = QgsVectorLayer(f"Polygon?crs={WGS84}&field=name:string", "gw_boundary_wgs84", "memory")
    feature = QgsFeature(layer.fields())
    feature.setAttributes(["site"])
    feature.setGeometry(geometry)
    layer.dataProvider().addFeatures([feature])
    return layer


def _boundary_multi_layer():
    layer = QgsVectorLayer(f"MultiPolygon?crs={UTM}&field=name:string", "boundary_multi", "memory")
    features = []
    for name, wkt in (("two parts", MULTI_UTM_WKT), ("bow-tie (invalid)", BOWTIE_UTM_WKT)):
        feature = QgsFeature(layer.fields())
        feature.setAttributes([name])
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


def _write_raster(path):
    from osgeo import gdal, osr

    gdal.DontUseExceptions()  # explicit default; global exception mode can break QGIS code

    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(path, RASTER_COLUMNS, RASTER_ROWS, 1, gdal.GDT_Float32)
    dataset.SetGeoTransform((X0, RASTER_CELL, 0.0, Y0 + RASTER_ROWS * RASTER_CELL, 0.0, -RASTER_CELL))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32633)
    dataset.SetProjection(srs.ExportToWkt())
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(RASTER_NODATA)
    row = [raster_value(c) for c in range(RASTER_COLUMNS)]
    import struct

    data = struct.pack(f"{RASTER_COLUMNS}f", *row) * RASTER_ROWS
    band.WriteRaster(0, 0, RASTER_COLUMNS, RASTER_ROWS, data)
    band.FlushCache()
    dataset = None
    return path


def create_fixtures(folder):
    """Write all fixtures into ``folder``. Returns a dict of layer sources."""
    os.makedirs(folder, exist_ok=True)
    gpkg = os.path.join(folder, "contour_flow_fixtures.gpkg")
    if os.path.exists(gpkg):
        os.remove(gpkg)
    return {
        "points": _write_vector(_points_layer(), gpkg, "points"),
        "boundary_wgs84": _write_vector(_boundary_wgs84_layer(), gpkg, "boundary_wgs84"),
        "boundary_multi": _write_vector(_boundary_multi_layer(), gpkg, "boundary_multi"),
        "raster": _write_raster(os.path.join(folder, "gradient_dem.tif")),
        "gw_wells": _write_vector(_gw_layer(), gpkg, "gw_wells"),
        "gw_qa_wells": _write_vector(_gw_layer(qa=True), gpkg, "gw_qa_wells"),
        "gw_boundary_wgs84": _write_vector(_gw_boundary_wgs84_layer(), gpkg, "gw_boundary_wgs84"),
    }
