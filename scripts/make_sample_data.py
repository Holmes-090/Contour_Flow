# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate the fictional Contour Flow sample data in ``sample_data/``.

Run with QGIS's Python (it needs PyQGIS and GDAL), from the repository root::

    scripts\\run_with_qgis.bat scripts\\make_sample_data.py

Creates (overwriting previous versions):

* ``sample_data/contour_flow_sample.gpkg`` with layers ``sample_wells`` and
  ``site_boundary``;
* ``sample_data/sample_dem.tif``;
* ``sample_data/contour_flow_sample.qgs``, a project with all three loaded (plain
  XML ``.qgs``, not zipped ``.qgz``: the QGIS plugin repository does not allow
  zipped files in a plugin's source repository).

All data is fictional and generated from the formulas below (EPSG:32633,
UTM 33N, local offsets in metres from X0, Y0).
"""

import math
import re
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, "sample_data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import (  # noqa: E402
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsFillSymbol,
    QgsGeometry,
    QgsMarkerSymbol,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsSingleSymbolRenderer,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

CRS = "EPSG:32633"
X0, Y0 = 452000.0, 5288000.0

# (well_id, dx, dy). 13 wells spread irregularly over about 400 x 300 m.
# MW-13 lies outside the site boundary on purpose (an "off-site" well).
WELLS = [
    ("MW-01", 20, 30), ("MW-02", 140, 15), ("MW-03", 270, 40), ("MW-04", 380, 25),
    ("MW-05", 60, 140), ("MW-06", 190, 120), ("MW-07", 320, 150), ("MW-08", 35, 260),
    ("MW-09", 150, 230), ("MW-10", 260, 270), ("MW-11", 390, 240), ("MW-12", 210, 190),
    ("MW-13", 440, 330),
]


def gw_elev(dx, dy):
    """Groundwater: regional gradient falling to the north-east, plus a small recharge mound."""
    mound = 0.35 * math.exp(-((dx - 120) ** 2 + (dy - 210) ** 2) / 9000.0)
    return 98.60 - 0.0045 * dx - 0.0030 * dy + mound


def ground_elev(dx, dy):
    """Ground surface: a broad hill in the centre-east on a gentle westward slope."""
    hill = 4.0 * math.exp(-((dx - 280) ** 2 + (dy - 160) ** 2) / 25000.0)
    return 103.0 + 0.004 * dx + hill


def bedrock_elev(dx, dy):
    """Bedrock: dipping north, with a buried channel running roughly north-south near x = 170."""
    channel = -2.5 * math.exp(-((dx - 170 - 0.2 * dy) ** 2) / 4000.0)
    return 86.0 + 0.012 * dy + channel


# A well that was not drilled to bedrock: NULL bedrock elevation (a useful test condition).
NO_BEDROCK = {"MW-04"}

# Groundwater Mode demo fields (see sample_data/README.md):
# mp_elev = measuring point (top of casing) 0.6 m above ground; dtw = mp_elev - gw_elev.
STICKUP = 0.6
NO_DTW = {"MW-10"}  # depth to water not measured: NULL
DTW_ENTRY_ERROR = {"MW-12": 1.8}  # deliberate data-entry error (1.8 m too deep), flagged by the QA check
# wl_text: water levels stored as text, as often found in spreadsheets.
WL_TEXT_SPECIAL = {"MW-03": "N/A", "MW-08": "Dry"}

BOUNDARY = [(-15, -10), (200, -20), (410, 5), (425, 160), (400, 295), (230, 315), (90, 300), (-20, 280), (-30, 120)]

DEM_COLUMNS, DEM_ROWS, DEM_CELL = 240, 180, 2.0  # 480 x 360 m


def dem_value(dx, dy):
    """Fictional terrain for the DEM: the ground-surface formula plus a small valley."""
    valley = -1.5 * math.exp(-((dy - 60 - 0.25 * dx) ** 2) / 1500.0)
    return ground_elev(dx, dy) + valley


def write_layer(layer, path, name):
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
        raise RuntimeError(f"{name}: {message}")


def make_wells():
    layer = QgsVectorLayer(
        f"Point?crs={CRS}&field=well_id:string(10)&field=gw_elev:double&field=ground_elev:double"
        "&field=bedrock_elev:double&field=mp_elev:double&field=dtw:double&field=wl_text:string(12)",
        "sample_wells",
        "memory",
    )
    features = []
    for well_id, dx, dy in WELLS:
        feature = QgsFeature(layer.fields())
        bedrock = None if well_id in NO_BEDROCK else round(bedrock_elev(dx, dy), 2)
        gw, ground = round(gw_elev(dx, dy), 2), round(ground_elev(dx, dy), 2)
        mp = round(ground + STICKUP, 2)
        dtw = None if well_id in NO_DTW else round(mp - gw + DTW_ENTRY_ERROR.get(well_id, 0.0), 2)
        text = WL_TEXT_SPECIAL.get(well_id, f" {gw:.2f}" if dx > 200 else f"{gw:.2f}")
        feature.setAttributes([well_id, gw, ground, bedrock, mp, dtw, text])
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(X0 + dx, Y0 + dy)))
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    return layer


def make_boundary():
    layer = QgsVectorLayer(f"Polygon?crs={CRS}&field=name:string(40)", "site_boundary", "memory")
    feature = QgsFeature(layer.fields())
    feature.setAttributes(["Fictional site"])
    feature.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(X0 + x, Y0 + y) for x, y in BOUNDARY + BOUNDARY[:1]]]))
    layer.dataProvider().addFeatures([feature])
    return layer


def make_dem(path):
    from osgeo import gdal, osr

    gdal.DontUseExceptions()  # explicit default; global exception mode can break QGIS code

    if os.path.exists(path):
        os.remove(path)
    dataset = gdal.GetDriverByName("GTiff").Create(
        path, DEM_COLUMNS, DEM_ROWS, 1, gdal.GDT_Float32, options=["COMPRESS=DEFLATE", "PREDICTOR=3"]
    )
    origin_x, origin_y = X0 - 40.0, Y0 - 30.0 + DEM_ROWS * DEM_CELL
    dataset.SetGeoTransform((origin_x, DEM_CELL, 0.0, origin_y, 0.0, -DEM_CELL))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32633)
    dataset.SetProjection(srs.ExportToWkt())
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(-9999.0)
    rows = []
    for row in range(DEM_ROWS):
        dy = origin_y - (row + 0.5) * DEM_CELL - Y0
        rows.append(struct.pack(
            f"{DEM_COLUMNS}f",
            *[dem_value(origin_x + (col + 0.5) * DEM_CELL - X0, dy) for col in range(DEM_COLUMNS)],
        ))
    band.WriteRaster(0, 0, DEM_COLUMNS, DEM_ROWS, b"".join(rows))
    band.FlushCache()
    dataset = None


def make_project(gpkg, dem, path):
    project = QgsProject.instance()
    project.clear()
    project.setCrs(QgsCoordinateReferenceSystem(CRS))
    project.setTitle("Contour Flow sample data")
    dem_layer = QgsRasterLayer(dem, "sample_dem")
    boundary = QgsVectorLayer(f"{gpkg}|layername=site_boundary", "site_boundary", "ogr")
    wells = QgsVectorLayer(f"{gpkg}|layername=sample_wells", "sample_wells", "ogr")
    for layer in (dem_layer, boundary, wells):
        if not layer.isValid():
            raise RuntimeError(f"sample layer {layer.name()} is invalid")
    # Neutral, readable defaults: outline-only boundary, small dark well markers.
    boundary.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": "#444444", "outline_width": "0.6", "outline_style": "dash"})))
    wells.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
        {"name": "circle", "color": "#333333", "outline_color": "white", "size": "2.6"})))
    # Layer tree order (top to bottom): wells, boundary, DEM. addMapLayers appends to the tree.
    project.addMapLayers([wells, boundary, dem_layer])
    project.writeEntryBool("Paths", "/Absolute", False)  # relative paths: the folder can be moved
    if not project.write(path):
        raise RuntimeError(f"Could not write {path}: {project.error()}")
    project.clear()
    # Saving a .qgs also writes an (empty) "<name>_attachments.zip". The project
    # has no attachments, and the repository must not contain zipped files.
    attachments = os.path.splitext(path)[0] + "_attachments.zip"
    if os.path.exists(attachments):
        os.remove(attachments)
    # QGIS stamps the OS account and the default metadata author into the
    # project. This is a public sample file, so replace them with neutral values.
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    text = re.sub(r'saveUser="[^"]*"', 'saveUser=""', text)
    text = re.sub(r'saveUserFull="[^"]*"', 'saveUserFull=""', text)
    text = re.sub(r"<author>[^<]*</author>", "<author>Contour Flow sample data</author>", text)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main():
    os.makedirs(OUT, exist_ok=True)
    gpkg = os.path.join(OUT, "contour_flow_sample.gpkg")
    dem = os.path.join(OUT, "sample_dem.tif")
    qgs = os.path.join(OUT, "contour_flow_sample.qgs")
    for path in (gpkg, qgs, os.path.join(OUT, "contour_flow_sample.qgz")):
        if os.path.exists(path):
            os.remove(path)
    write_layer(make_wells(), gpkg, "sample_wells")
    write_layer(make_boundary(), gpkg, "site_boundary")
    make_dem(dem)
    make_project(gpkg, dem, qgs)
    for name in sorted(os.listdir(OUT)):
        print(f"  {name}  {os.path.getsize(os.path.join(OUT, name)):,} bytes")


if __name__ == "__main__":
    QgsApplication.setPrefixPath(os.environ["QGIS_PREFIX_PATH"], True)
    app = QgsApplication([], True)
    app.initQgis()
    code = 0
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}")
        code = 1
    sys.stdout.flush()
    app.exitQgis()
    os._exit(code)
