import geopandas as gp
import pandas as pd
import shapely
import numpy as np
from typing_extensions import Self


class WUIClassifier:

    def __init__(
        self,
        landcoverMask: gp.GeoDataFrame,
        buildings: gp.GeoDataFrame,
        bounds: shapely.geometry.Polygon = None,
        gridSize: int = 300,
        crs: int = 5070,
    ) -> Self:
        """A base level object for calculating WUI classes across an area using specified parameters.

        Args:
            landcoverMask (gp.GeoDataFrame): A mask of vegetative (flammable) polygons representing the search area. It is expected that all polygons in this search area are flammable source polygons.
            buildings (gp.GeoDataFrame): A polygonal dataset where each polygon represents a building footprint.
            bounds (shapely.geometry.box, optional): The bounding box over which to calculate the results. Defaults to the bounding box of 'landcoverMask'
            gridSize (int, optional): _description_. Defaults to 300.
            crs (int, optional): _description_. Defaults to EPSG:5070 , best for the continental U.S.

        Raises:
            TypeError: invalid argument types
            AssertionError: Invalid bounding box specification

        Returns:
            Self:
        """

        if bounds:
            assert isinstance(
                bounds, shapely.Polygon
            ), "Box specified but not instance of shapely Polygon."

            self.bounds = bounds
        else:
            bnds = landcoverMask.total_bounds

            self.bounds = shapely.geometry.box(bnds[0], bnds[1], bnds[2], bnds[3])

        assert isinstance(buildings, gp.GeoDataFrame), "Invalid buildings df."
        assert isinstance(landcoverMask, gp.GeoDataFrame), "Invalid Landcover df."

        assert type(gridSize) == int, "invalid grid size given, expected 'int'"
        assert type(crs) == int, "invalid crs specified, expected 'int'"

        self.crs = crs
        self.gridSize = gridSize
        self.buildings = buildings
        self.landcoverMask = landcoverMask

    def __checkSurroundingVegetationCover(
        self,
        searchArea: gp.GeoSeries,
        landcover: gp.GeoDataFrame,
        threshold: float = 0.5,
    ) -> bool:
        """checks if vegeation cover around searcharea is >= thresh proportion according to , if so then returns true else false"""

        assert threshold > 0 and threshold <= 1, "threshold out of bounds"

        intersectionBuffer: gp.GeoSeries = searchArea.buffer(1).difference(
            searchArea.geometry[0]
        )

        possibleMatches = landcover.loc[
            landcover.sindex.query(
                intersectionBuffer.geometry[0], predicate="intersects"
            )
        ]
        landcoverMask: pd.Series[bool] = possibleMatches.intersects(
            intersectionBuffer.geometry[0]
        )

        surroundingVegetation: gp.GeoDataFrame = possibleMatches[landcoverMask]

        if len(surroundingVegetation) == 0:
            return False

        bufferArea: float = intersectionBuffer.area.sum()

        # buffer area is denom

        # use area of intersection of vegetation as numerator

        surroundingVegArea: float = surroundingVegetation.intersection(
            intersectionBuffer.geometry[0]
        ).area.sum()

        surroundingVegProportion: float = surroundingVegArea / bufferArea

        return True if surroundingVegProportion >= threshold else False

    def __createGrid(
        self,
        coords: list[np.float64, np.float64, np.float64, np.float64],
        gridSize: int,
        crs: int = 5070,
    ) -> gp.GeoDataFrame:
        """creates a grid inside of 'coords' , where 'coords' is a bounding box area, you may lose some space on the edges if your bbox is not divisible by 'gridSize'.
        CRS defaults to 5070 for continental U.S."""

        geoms: list[gp.GeoSeries] = []

        # guarantee that the size of the grid is above and at least a multiple of the needed size - duplicate work can be resolved with a .dissolve operation
        xCoords = np.arange(coords[0], coords[2] + gridSize, gridSize, dtype=np.float64)
        yCoords = np.arange(coords[1], coords[3] + gridSize, gridSize, dtype=np.float64)

        for xCoord in xCoords:
            for yCoord in yCoords:
                geom = shapely.geometry.box(
                    minx=xCoord,
                    miny=yCoord,
                    maxx=xCoord + gridSize,
                    maxy=yCoord + gridSize,
                )
                geoms.append(geom)

        grid = gp.GeoDataFrame(geometry=geoms, crs=crs)

        return grid

    def __checkBuildingDensity(
        self,
        buildings: gp.GeoDataFrame,
        searchArea: gp.GeoSeries,
        radius: int = 1000,
        threshold: int = 6.17,
        crs: int = 5070,
    ) -> bool:
        """building density according to 'buildings' meeting 'theshold' inside 'radius' from 'searchArea' ,
        returns true if the density meets the threshold False otherwise."""

        centroid: gp.GeoSeries = searchArea.centroid

        buffer: gp.GeoSeries = centroid.buffer(radius)
        buffer.crs = crs

        possibleBuildings = buildings.loc[
            buildings.sindex.query(
                buffer.geometry[0], predicate="intersects", output_format="dense"
            )
        ].reset_index(drop=True)

        if len(possibleBuildings) == 0:
            return False

        buildingMask: pd.Series[bool] = possibleBuildings.intersects(buffer.geometry[0])

        densityOverRadius = len(
            possibleBuildings[buildingMask]
        )  # numbuildings inside radius density in radiusUnits^2 / 1000 so for projection in metres (expected) in Km^2

        return True if densityOverRadius >= threshold else False

    def __createWUI(
        self,
        landcover: gp.GeoDataFrame,
        buildings: gp.GeoDataFrame,
        grid: gp.GeoDataFrame,
        searchDistance: int = 1000,
        patchSizeThreshhold: int = 5e6,
        vegetationThreshold: float = 0.5,
        buildingDensityThreshold: float = 6.17,
        buildingDensityRadius: int = 1_000,
        crs: int = 5070,
    ) -> gp.GeoDataFrame:
        """'landcover' is assumed to be a polygonal dataset of all "flammable" (vegetative) polygons for the US at 30m res , in projection with metres.
        'buildings' is assumed to be a polygonal dataset where each polygon is a building observation for the US , metres projection
        'grid' is assumed to be a spatial grid/gridlike covering the area we are concerned with, each row is assumed to be a cell of the grid metres projection
        'searchDistance' is distance to search for significant vegetation from a building in crs units
        'patchSizeThreshold' is in units of crs and is threshold for vegetation patch size within searchDistance for consideration - 5000 = 5km^2 if crs in metres
        ALL MUST BE IN SAME PROJECTION USING METRES AS UNITS"""

        # calculate vegetation patch areas
        landcover["area"] = landcover.area
        grid["wuiClass"] = 0

        split = len(grid) // 100

        for index, row in grid.iterrows():

            if index % split == 0:
                pass
                # print( f"{index} of {len(grid)} complete or {(index / len(grid)) * 100}%" )

            searchArea: gp.GeoSeries = gp.GeoSeries(row.geometry).buffer(searchDistance)

            # see if buildings are in or intersect cell
            possibleBuildings = buildings.loc[
                buildings.sindex.query(
                    row.geometry, predicate="intersects", output_format="dense"
                )
            ]

            containedBuildingsMask: pd.Series[bool] = possibleBuildings.intersects(
                row.geometry
            )

            containedBuildings: gp.GeoDataFrame = possibleBuildings[
                containedBuildingsMask
            ]  # buildings inside cell/intersecting

            if len(containedBuildings) == 0 or not self.__checkBuildingDensity(
                buildings,
                searchArea,
                radius=buildingDensityRadius,
                threshold=buildingDensityThreshold,
                crs=crs,
            ):  # no buildings, skip
                continue
            else:
                pass

            # find landcover features that intersect with the searchArea
            possiblePatches = landcover.loc[
                landcover.sindex.query(searchArea.geometry[0], predicate="intersects")
            ]
            vegetationPatchesMask: pd.Series[bool] = possiblePatches.intersects(
                searchArea.geometry[0]
            )  # boolean mask

            vegetationPatches: gp.GeoDataFrame = possiblePatches[
                vegetationPatchesMask
            ]  # possible matches
            vegetationPatches: gp.GeoDataFrame = vegetationPatches[
                vegetationPatches["area"] >= patchSizeThreshhold
            ]

            # now have all vegetation patches within search dist from cell that meet size criteria, now classify

            if (
                not len(vegetationPatches) == 0
            ):  # has at least 1 vegetation patch > size thresh then interface
                grid.loc[index, "wuiClass"] = 2  # interface
                continue

            if self.__checkSurroundingVegetationCover(
                gp.GeoSeries(row.geometry), landcover, threshold=vegetationThreshold
            ):
                grid.loc[index, "wuiClass"] = 1  # intermix
                continue

        return grid

    def computeWUI(
        self,
        vegetationThreshold: float = 0.5,
        buildingDensityThreshold: float = 6.17,
        buildingDensityRadius: int = 1_000,
        patchSearchDistance: int = 1_000,
        patchSizeThreshold: int = 5e6,
    ) -> gp.GeoDataFrame:
        """Compute a WUI classification task over the bounds of the instance and return a dataframe of the resulting classified cells

        Args:
            vegetationThreshold (float, optional): the proportion of a cell that should be surrounded by vegetation to be eligible for classification as Intermix. Defaults to 0.5.
            buildingDensityThreshold (float, optional): the number of buildings per buildingDensityRadius^2 to be eligible for any WUI class. Defaults to 6.17.
            buildingDensityRadius (int , optional): the radius around a given cell to calculate building density over. Defaults to 1_000 in CRS units (assumed metres)
            patchSearchDistance (int, optional): The distance from a cell to search for a path of flammable vegetation meeting 'patchSizeThreshhold'. Defaults to 1_000.
            patchSizeThreshold (int, optional): The contiguous polygonal size of a patch of flammable vegetation in CRS^2 to be considered for the Intermix class. Defaults to 5e6.
        Returns:
            gp.GeoDataFrame: A geodataframe with the computed WUI cells over the search area. Non classified cells ( not 1 or 2 ) are excluded. 1 -> Intermix , 2 -> Interface class
        """

        grid = self.__createGrid(self.bounds.bounds, self.gridSize, self.crs)

        wui = self.__createWUI(
            self.landcoverMask,
            self.buildings,
            grid,
            patchSearchDistance,
            patchSizeThreshold,
            vegetationThreshold,
            buildingDensityThreshold,
            buildingDensityRadius,
            self.crs,
        )

        return wui[wui["wuiClass"] != 0]
