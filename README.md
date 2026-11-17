# Contour Flow

**Make editable contour lines in QGIS from point measurements or an elevation
raster, in a few clicks.**

Contour Flow is a free, open-source QGIS plugin. Choose a point layer with a
number field (such as groundwater levels or survey elevations) or a DEM, and
it draws clean, labelled contour lines that you can edit and save like any
other layer.

![Groundwater contours made with Contour Flow](docs/images/groundwater_contours.png)

## What you can do with it

- **Contour point data:** turn well, borehole or survey points into contours of
  groundwater level, ground surface, bedrock, or any other measured value.
- **Contour a DEM:** draw contour lines from an elevation raster.
- **Clip to your site:** keep only the contours inside a boundary polygon.
- **Get readable maps straight away:** major and minor contours, labels, and a
  choice of styles (Neutral, Topographic, Groundwater).
- **Edit and keep the results:** the output is a normal QGIS line layer. Move
  lines, change the style, or save it to a GeoPackage.

It uses QGIS's own interpolation and contouring tools, so there is nothing
extra to install.

## Getting started

1. In QGIS, open **Plugins ▸ Manage and Install Plugins**, search for
   **Contour Flow**, and click **Install**.
   (While the plugin is marked *experimental*, tick *Show also experimental
   plugins* in the Plugin Manager's **Settings** tab first.)
2. Add your point layer or DEM to the map.
3. Click the **Contour Flow** toolbar button, or use **Plugins ▸ Contour Flow**.
4. Choose your layer (and, for points, the value field). Optionally pick a
   boundary to clip to.
5. Click **Generate Contours**.

That's it. The new contour layer appears in your project. It is a temporary
layer, so to keep it, right-click it and choose **Make Permanent**, or set
**Save as: GeoPackage** before you generate.

<img src="docs/images/dialog.png" alt="The Contour Flow window" width="360">

## Tips

- **Interval:** *Automatic* picks a tidy contour spacing for you. Switch to
  *Fixed* to set your own, for example every 0.5 m.
- **Summary:** the Summary box shows what will happen (number of points,
  value range, contour interval) before you click Generate.
- **Advanced settings:** open this section to choose the interpolation method,
  the cell size, smoothing and more. The defaults work well for most data.
- **Selected features only:** contour just the points you have selected on the map.
- **Your settings travel with the result:** every contour layer records how it
  was made, in **Layer Properties ▸ Metadata**.

## Try it with the sample data

The [`sample_data`](sample_data/README.md) folder has a small, fictional
example: 13 wells, a site boundary and a DEM. Open
`contour_flow_sample.qgs` in QGIS and follow the three short tests in its README.

![Contours from the sample DEM](docs/images/dem_contours.png)

## A note on accuracy

Contours drawn from points are **estimates**. Between and beyond your
measurements, the plugin can only interpolate what the data suggests. Results
should be reviewed by an appropriately qualified person before being used for
technical or professional decisions.

## Requirements

- QGIS 3.44 (LTR) or newer 3.x
- The **Processing** plugin enabled (it is on by default)
- Tested on Windows. It uses only tools built into QGIS, so it should also run
  on macOS and Linux. Please report any problems there.

## Help and feedback

Found a problem or have a suggestion? Please open an issue at
<https://github.com/Holmes-090/Contour_Flow/issues>. It helps to include your
QGIS version, and any messages from **View ▸ Panels ▸ Log Messages ▸ Contour Flow**.

## For developers

How the plugin is built and tested: [ARCHITECTURE.md](ARCHITECTURE.md),
[DEVELOPMENT.md](DEVELOPMENT.md), [TESTING.md](TESTING.md),
[CHANGELOG.md](CHANGELOG.md).

## License

Contour Flow is free software under the GNU General Public License v2 or later
(GPL-2.0-or-later). See [LICENSE](LICENSE).
