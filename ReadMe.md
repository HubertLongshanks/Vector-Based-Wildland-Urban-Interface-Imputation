# Vector Based Wildland Urban Interface Classification Tool

## About
This tool was created in order to facilitate better WUI classification over the CONUS for downstream wildland fire related tasks. The tool is based on a 2022 paper and related work by Carlson , et. al. released in 2022 and using 2018 and 2016 source data - see: https://data.usgs.gov/datacatalog/data/USGS:617bfb43d34ea58c3c70038f

This tool aims to facilitate easier classification of WUI environments at varying spatial resolutions especially for smaller, local workflows. This tool works exclusively with vector based data as opposed to raster (in contrast to Carlson. et. al.). This has some tradeoff - on the one hand you can specify an essentially arbitrary spatial resolution as long as it is supported by your source data and on the other you require significantly more computational resources - particurally for large areas like the entire CONUS. This workflow is best run with ample compute, ample time or over a smaller area at high resolution.

## API

### WUIClassifier
The library exports a single class, *WUIClassifier*, that takes in two main inputs - polygonal building locations over an area of interest and a polygonal flammable landcover mask over the same area of interest. You can then classify WUI environments using these two sources at a spatial resolution and using parameters that fit your needs. For details on how one might source and handle this input data see: [Input Data Preparation](#input-data-preparation).

The tool depends heavily on the Geopandas API for its computation, see -> https://geopandas.org/en/stable/

An example usage:
```py
from WUICalculation import WUIClassifier
import geopandas as gp

landcover = gp.read_file("my_landcover_mask.fgb") #you may want to choose a file format that supports streaming or bounding box queries for larger areas.

buildings = gp.read_file("buildings.fgb")

#use the bounds of the landcover df and set up for 100M resolution using EPSG:5070 ( which uses metres and is reccommended for the CONUS )
classifier = WUIClassifier( landcover , buildings , None , 100 , 5070 )

#compute WUI cells using the default parameters
wuiCells = classifier.computeWUI()

#you will get back a df of classified grid cells under "wuiClass" : 1->Intermix , 2->Interface , the unclassified cells will not be included


#You may choose to combine the WUI classified cells into contiguous polygons depending on your needs
dissolved = wuiCells.dissolve( by=[ col for col in df.columns if col != df.active_geometry_name ] )
```


## Input Data Preparation
Typically, you would use this tool with some measure of flammable landcover, like a subset of the CONUS landcover dataset along with building locations for a specified area. You could also bring your own data for a specific area if it fits your workflow or needs better. Here we will discuss using CONUS landcover at 30M resolution and microsoft's open building locations dataset, which are both updated regurally and were used by *Carlson et. al.* as well.

### Working With Buildings Footprints
You may choose to grab only a certain state or the whole US depending on your needs, this sample shows for a single state. Microsoft has made this dataset freely accessible and usable. https://planetarycomputer.microsoft.com/dataset/ms-buildings
```py
import pandas as pd
import geopandas as gpd
import json
import requests
import zipfile
from io import BytesIO

def downloadState( state : str ) :

    response = requests.get( f"https://minedbuildings.z5.web.core.windows.net/legacy/usbuildings-v2/Ohio.geojson.zip" , stream=True )

    if (response.status_code != 200) :
        raise ConnectionError( f"status code: {response.status_code}")

    io = BytesIO( response.content )

    with zipfile.ZipFile( io ) as file :

        file.extractall()

    df = gpd.read_file('Ohio.geojson')
    df.to_crs( epsg=5070 , inplace=True)
```


### Downloading and Polygonizing Landcover
You can download the latest landcover tif from the USGS website or do it programitically like so, then polygonize it ( this can take some time and you may want to subset by your area of interest if compute is limited ).

```py
import requests 
import zipfile
from io import BytesIO
import subprocess

#for 2024 data
resp = requests.get('https://www.mrlc.gov/downloads/sciweb1/shared/mrlc/data-bundles/Annual_NLCD_LndCov_2024_CU_C1V1.zip' , stream=True)

if ( resp.status_code != 200 ) :
    raise ConnectionError

io = BytesIO( resp.content )

with zipfile.ZipFile( io ) as file :

    file.extractall()

#make sure you have gdal installed on your machine, this can take a minute for the whole U.S. and may use a fair amount of memory - you may want to use a smaller area if needed or resources are limited
subprocess.run( [ "gdal_polygonize.py" , "Annual_NLCD_LndCov_2024_CU_C1V1.tif" , "-f" , "FlatGeobuf" , "landcoverPolygons.fgb" , ])

vegPixels = { #you can use this as a starter or make your own to fit your needs
    "description" : "data dictionary classifying landcover pixel values as vegetative or not" , 
    "11" : false ,
    "12" : false ,
    "21" : false , 
    "22" : false , 
    "23" : false , 
    "24" : false , 
    "31" : false , 
    "41" : true , 
    "42" : true , 
    "43" : true , 
    "51" : true , 
    "52" : true , 
    "71" : true , 
    "72" : true , 
    "73" : true , 
    "74" : true , 
    "81" : true , 
    "82" : true , 
    "90" : true , 
    "95" : true
}

landcover = gp.read_file("landcoverPolygons.fgb") #you should probably subset to a smaller area and chunk the operation unless you have a few 100 GB of RAM (for the whole US)

landcover["isVegetative"] = landcover["DN"].map( lambda x : mapping[str(x)])

landcover = landcover[ landcover["isVegetative"] ]

landcover.to_crs( epsg = 5070 , inplace = True )

#you might choose ton combine vegetative landcover polygons regardless of class value or keep them as single class depending on your needs. Use a .dissolve() on "DN" if you want.

landcover.to_file( "./LandcoverMask.fgb" )
```

