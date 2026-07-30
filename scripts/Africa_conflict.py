#!/usr/bin/env python
# coding: utf-8

# In[1]:


import pandas as pd
import numpy as np
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from shapely.geometry import Point

# File Manipulation modules
import os, glob, pickle

# Geo modules
import srtm
import pycountry, rasterio
import geopandas as gpd
from rasterio.merge import merge

import country_converter as coco  # to map ISO3 standard country names with the dataset

# Regional or administration information defining files
from geo_spatial_class import oceans, territories
from africa_region_mapping import region_map


# In[2]:


# Note: The dataset contains a significant # of high-fatality events located in non-land areas # (International Waters & oceanic  regions), especially
#       clustered offshore West Africa. They are not treated as noise, as they represent meaningful maritime conflict activity.
#      Instead of removing them, they are classified, here, using a structured approach:
#        - geo_type is introduced to distinguish land, coastal, and maritime events
#        - maritime zones are assigned for spatial grouping of oceanic incidents
#        - events with coordinates in water are optionally mapped to the nearest coastal country to enable country-level aggregation
# Missing values (NaN) in maritime fields are treated as triggers for rule-based assignment, not as final invalid states.


# In[3]:


# File paths to on
srtm_path = "C:/srtm"
file_path="F:/Computer SCience/Data Mining/Projects/Africa_aggregated_data_up_to_week_of-2026-06-06.csv"


# In[4]:


# Open and load dataset from file
total_df=pd.read_csv(file_path)


# In[5]:


# Data that starts from year 2000 todate
total_df["WEEK"]=pd.to_datetime(total_df["WEEK"])
start_year= 1997
end_year = pd.Timestamp.today().year

df = total_df[(total_df["WEEK"] >= f"{start_year}-01-01") & (total_df["WEEK"] <= pd.Timestamp.today())]

# Total Fatality recorded in the time range
total_fatality =df["FATALITIES"].sum()


# In[6]:


# Convert dataset COUNTRY feature with ISO3
cc = coco.CountryConverter()
df["ISO3"] = cc.pandas_convert(series=df["COUNTRY"], to="ISO3")

# For Mapping demonstration
world = gpd.read_file("C:/Geo Tools/ne_110m_admin_0_countries.shp")
# Filter Africa
africa = world[world["CONTINENT"] == "Africa"].copy()


# In[7]:


# geo-type classifier [classifies each value in country column as ocean, territory, or country];separating SRTM-valid vs SRTM-invalid domains
def get_geo_type(x):
    if x in oceans:
        return "ocean"
    elif x in territories:
        return "territory"
    else:
        return "country"
df["geo_type"] = df["COUNTRY"].apply(get_geo_type)


# In[8]:


""" Adds elevation values from SRTM data to a dataframe based on latitude and longitude coordinates.
- Loads SRTM elevation data once for efficiency.
- Uses caching system (pickle file) to store previously computed elevations, avoiding repeated downloads/computations for the same coordinates.
- Extracts latitude and longitude pairs from the input dataframe.
- Retrieves elevation values for each unique coordinate using SRTM data; Saves newly computed elevations into a cache file.
- Merges the elevation values back into the original dataframe; returns the updated dataframe with a new 'ELEVATION' column.

Parameters: df (pandas.DataFrame): Input dataframe containing 'LATITUDE' and 'LONGITUDE' columns.
            cache_file (str): Path to the cache file used to store computed elevations.
Returns: pandas.DataFrame: Original dataframe with an added 'ELEVATION' column. """
def get_srtm_elevation(df, cache_file="land_elevation.pkl"):

    # Load SRTM data (only once)
    elevation_data = srtm.get_data()

    def get_elevation_from_srtm(lat, lon):
        try:
            return elevation_data.get_elevation(lat, lon)
        except Exception as e:
            print(f"Error for ({lat}, {lon}): {e}")
            return None

    # Load or create cache
    if os.path.exists(cache_file):
        with open(cache_file, "rb") as f:
            elevation_cache_New = pickle.load(f)
        print(f"Loaded {len(elevation_cache_New)} cached elevations")
    else:
        elevation_cache_New = {}
        print("Starting with empty cache")

    # Unique coordinates
    unique_coords = df[["CENTROID_LATITUDE", "CENTROID_LONGITUDE"]].drop_duplicates().copy()

    # Process coordinates
    for lat, lon in zip(unique_coords["CENTROID_LATITUDE"], unique_coords["CENTROID_LONGITUDE"]):

        key = (round(lat, 5), round(lon, 5))

        if key not in elevation_cache_New:
            elevation = get_elevation_from_srtm(lat, lon)
            elevation_cache_New[key] = elevation

            with open(cache_file, "wb") as f:
                pickle.dump(elevation_cache_New, f)

    # Add elevation column
    unique_coords["ELEVATION"] = [
        elevation_cache_New[(round(lat, 5), round(lon, 5))]
        for lat, lon in zip(unique_coords["CENTROID_LATITUDE"], unique_coords["CENTROID_LONGITUDE"])
    ]

    # Merge back
    df = df.merge(unique_coords, on=["CENTROID_LATITUDE", "CENTROID_LONGITUDE"], how="left")

    return df


# In[9]:


# geo-aware elevation extraction system that combines: SRTM (Shuttle Radar Topography Mission) → land elevation
def get_srtm_elevation(df, cache_file="land_elevation.pkl"):

    elevation_data = srtm.get_data()

    def get_elevation(lat, lon):
        try:
            val = elevation_data.get_elevation(lat, lon)
            return None if val is None else float(val)
        except:
            return None

    # Load cache
    if os.path.exists(cache_file):
        with open(cache_file, "rb") as f: cache = pickle.load(f)
        print(f"Loaded {len(cache)} cached elevations")
    else:
        cache = {}

    # Work on copy
    df = df.copy()

    # Create stable coordinate key 
    df["lat_key"] = df["CENTROID_LATITUDE"].round(7)
    df["lon_key"] = df["CENTROID_LONGITUDE"].round(7)

    # To speed up the function and not get already retrieved elevation for coordinates
    coords = df[["lat_key", "lon_key"]].drop_duplicates()

    # Compute missing only
    for lat, lon in zip(coords["lat_key"], coords["lon_key"]):
        key = (lat, lon)

        if key not in cache:
            cache[key] = get_elevation(lat, lon)

    # Save cache once (land_elevation.pkl file)
    with open(cache_file, "wb") as f: pickle.dump(cache, f)

    # Map back safely
    coords["ELEVATION"] = coords.apply( lambda r: cache.get((r["lat_key"], r["lon_key"])),  axis=1 )

    # Remove old elevation column to avoid suffix columns (_x, _y) or (prevents duplicates if the function is called multiple times)
    df = df.drop(columns=["ELEVATION", "ELEVATION_x", "ELEVATION_y"], errors="ignore")

    # Merge lat, lon, and elevation features
    df = df.merge(coords, on=["lat_key", "lon_key"], how="left")
    # Drop temporary features
    df.drop(columns=["lat_key", "lon_key"], inplace=True)

    return df


# In[10]:


# Elevation routing logic
def assign_elevation(row):
    if row["geo_type"] == "ocean":
        return get_gebco_elevation(row["CENTROID_LATITUDE"], row["CENTROID_LONGITUDE"])

    elif row["geo_type"] == "country":
        return get_srtm_elevation(row["CENTROID_LATITUDE"], row["CENTROID_LONGITUDE"])

    elif row["geo_type"] == "territory":
        # try SRTM first, fallback to GEBCO
        val = get_srtm_elevation(row["CENTROID_LATITUDE"], row["CENTROID_LONGITUDE"])
        return val if val is not None else get_gebco_elevation(row["CENTROID_LATITUDE"], row["CENTROID_LONGITUDE"])


# In[11]:


# Call function to fetch elevation of implicit country model (SRTM land elevation)
df= get_srtm_elevation(df)

# Check missing elevations
print("Missed elevations:",df["ELEVATION"].isna().sum())

# Check how much elevations missed from which geo-spatial classifiactions
df[df["ELEVATION"].isna()]["geo_type"].value_counts()


# In[12]:


df = df.dropna(subset=["ELEVATION"])


# In[13]:


df[df["geo_type"]=="territory"][["COUNTRY","geo_type"]].value_counts()


# In[14]:


df.columns


# In[15]:


 # Include REGION column into dataset from prepared Africa regional - Country  maping dictionary
df["REGION_New"] = df["COUNTRY"].map(region_map)


# In[16]:


# List of locations in the dataset that are not directly administered by African countries
df[df["REGION_New"].isna()]["COUNTRY"].unique()


# In[17]:


# Top 10 African countries with high conflict fatalities
fatal_countries= df.groupby("COUNTRY")[["FATALITIES","EVENTS"]].sum().sort_values(ascending=False, by="FATALITIES").head(10)
fatal_countries.plot(kind="barh")
plt.xlabel("Fatalities")
plt.ylabel("African Countries")
plt.title(f"African Countries with High Conflict Fatalities\n{start_year}–{end_year}")
plt.show()


# In[18]:


# Bar chart: Fatalities and conflict events from 2000-2026
df["WEEK"]=pd.to_datetime(df["WEEK"])
df["year"]=df["WEEK"].dt.year
fatal_year = df.groupby("year").agg(fatalities=("FATALITIES","sum"),event=("EVENTS","sum"))
ax= fatal_year.plot(kind="bar", figsize=(13,3))

ax.set_xlabel("Year")
ax.set_ylabel("Count")
ax.set_title(f"Fatalities and  Conflict Events by Year\n{start_year} - {end_year}\n Total fatalit: {total_fatality}")
plt.xticks(rotation=45)

fig = ax.get_figure()
cbar = fig.axes[-1]
cbar.yaxis.set_major_formatter(mtick.StrMethodFormatter('{x:,.0f}'))
plt.show()


# In[19]:


fig, (ax1, ax2) = plt.subplots(1, 2,figsize=(18,8))

# Map 1: Fatalities Per Country
fatal_map = (df.groupby("ISO3")["FATALITIES"].sum().reset_index())
# create 5 categories (Quantile-based categories); balanced groups
fatal_map["fatal_cat"]=pd.qcut(fatal_map["FATALITIES"],
                                   q=5,
                                   labels=["Very Low Fatality", "Low Fatality", "Medium Fatality", "High Fatality", "Very High Fatality"])
fatal_map.sort_values("FATALITIES", ascending=False)


africa = world[world["CONTINENT"] == "Africa"].copy()
africa = africa.merge(fatal_map, left_on="ADM0_A3", right_on="ISO3", how="left")   # or ISO_A3 depending on your file right_on="ISO3",
africa.plot(column="fatal_cat", cmap="Reds", legend=True, edgecolor="black", missing_kwds={"color": "lightgrey"}, ax=ax1)

ax1.set_title(f"African Conflict Fatalities ({start_year}–{end_year})")
ax1.axis("off")

# format colorbar numbers with commas
fig = ax.get_figure()
cbar = fig.axes[-1]
cbar.yaxis.set_major_formatter(mtick.StrMethodFormatter('{x:,.0f}'))

# Map 2: Fatalities Per Region
africa["FATALITIES"] = africa["FATALITIES"].fillna(0)

africa_regions = africa.dissolve(by="SUBREGION", aggfunc="count").reset_index()
africa_regions.plot(column="FATALITIES", cmap="Reds", legend=True, edgecolor="black", ax=ax2)

ax2.set_title(f"African Conflict Fatalities Per Region ({start_year}–{end_year})")
ax2.axis("off")
plt.tight_layout()
plt.show()
fig.savefig("African_fatality_map.png", dpi=300, bbox_inches="tight")


# In[20]:


# Elevation classification for conflict analysis in Africa [Strong GIS-Grade classification version]

# Elevation variable is grouped into physiographic zones to better understand how terrain influences conflict fatalities. These bins represent 
# generalized African elevation gradients (lowland to high mountains), which reflect differences in accessibility, population distribution, &
# terrain ruggedness. This allows comparison of fatality patterns across distinct geographic elevation zones rather than raw numeric values

# Create categories
conditions = [
    df["ELEVATION"] <200,  (df["ELEVATION"]  >= 200) & (df["ELEVATION"]  < 500), (df["ELEVATION"] >= 500) & (df["ELEVATION"] < 1000),
    (df["ELEVATION"] >= 1000) & (df["ELEVATION"] < 1500), (df["ELEVATION"] >= 1500) & (df["ELEVATION"] < 2000), 
    (df["ELEVATION"] >= 2000) & (df["ELEVATION"] < 2500), (df["ELEVATION"] >= 2500) & (df["ELEVATION"] < 3000), df["ELEVATION"] >= 3000
]

# Terrain classification system
labels = [
    "Extreme Lowland","Lowland","Lower Plateau","Mid Plateau","Upper Plateau","High Plateau","Mountain Zone","Extreme Mountain"
]
# Define order (pd.Categorical), Define GIS order (low --> high)
df["ELEVATION_ZONE"] = np.select(conditions, labels, default="Unknown")

df["ELEVATION_ZONE"] = pd.Categorical( df["ELEVATION_ZONE"], categories=labels,  ordered=True)

# Ordering of ELEVATION_ZONE (categorical variable)
# The elevation zones are converted into an ordered categorical type to define a meaningful hierarchy from low - high elevation
# This ordering doesn't change the data values or create a new column.Instead, it assigns a spatially meaningful rank to each category, allowing
# proper logical sorting, comparison, and visualization.

# Effect:
# - Ensures correct ordering in plots and summaries (not alphabetical)
# - Enables elevation-aware comparisons between zones
# - Improves GIS interpretation of terrain-fatality relationships
# - Prevents misleading category ordering in analysis outputs


# In[21]:


df["ELEVATION_ZONE"].unique()


# In[22]:


df = df.dropna(subset=["ELEVATION"])
df["ELEVATION_ZONE"].value_counts()


# In[23]:


fatal_heights=(df.groupby("ELEVATION_ZONE")["FATALITIES"].sum().sort_values(ascending=False))
gdf=gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["CENTROID_LATITUDE"],df["CENTROID_LONGITUDE"]), crs="EPSG:4326")
fatal_heights


# In[42]:


df1=df[["ELEVATION_ZONE","CENTROID_LATITUDE","CENTROID_LONGITUDE","FATALITIES"]]
df1.to_csv("my_new_file1.csv", index=False)


# In[43]:


fig, ax=plt.subplots(figsize=(10,11))

africa.boundary.plot(ax=ax, color="black",linewidth=0.5)

# Division by 12 used to scale down the point sizes so they don't become enormous on the map.
gdf.plot(ax=ax,column="ELEVATION_ZONE", markersize=gdf["FATALITIES"]/12, legend=True)

plt.show()


# In[25]:


fatal_heights.plot(kind="bar")
plt.xlabel("Elevation Classification")
plt.ylabel("Fatalities")
plt.title(f"Fatalities by Elevation Classification\n{start_year} - {end_year}")
plt.xticks(rotation=45)
plt.show()


# In[26]:


# Conflict density relative to land area(Conflict Density  = Number of Conflict Events/Land Area). Calculating conflict density is important because
# raw conflict-event counts can be misleading. Looking only at event counts, we might conclude that the lowlands are much more conflict-prone.
# A zone (say lowland) may have many events simply b/c it occupies a large portion of Africa. Density helps identify whether conflicts are truly 
# concentrated there. It enables fair comparison between elevation zones
# Conflict density can answers: "How concentrated are conflict events in a given amount of land?"/"How crowded with conflict events is this landscape?"

# Conflict Statistics (Numberator)
conflict_stat = (df.groupby("ELEVATION_ZONE")
    .agg(EVENTS=("ELEVATION", "size"), FATALITIES=("FATALITIES", "sum"), AVG_FATALITIES=("FATALITIES", "mean") ) .reset_index())


# In[27]:


conflict_stat


# In[28]:


# Area in each elevation zone (Denominator to calculate conflict density relative to land area)

# Finds all .tif files in a folder
pattern = os.path.join(srtm_path, "srtm_*.tif")
files = glob.glob(pattern)

if len(files) == 0:
    raise ValueError("No SRTM files found. Check folder path!")

# Searches the folder, finds all files matching srtm_*.tif, returns a list of file paths
srcs = [rasterio.open(f) for f in files]
files = glob.glob(r"C:/srtm/srtm_*.tif")

labels = ["Extreme Lowland","Lowland","Lower Plateau","Mid Plateau", "Upper Plateau","High Plateau","Mountain Zone","Extreme Mountain"]
all_counts = []

# Opens each SRTM raster tile, reads its elevation values, converts missing values to NaN, and assigns every pixel to a predefined elevation zone 
# such as Lowland, Highland, or Mountain.
for f in files:
    with rasterio.open(f) as src:
        dem = src.read(1).astype("float32")
        # Replaces invalid elevation values with NaN (missing values). -32768 is a common NoData value 
        # dem <= -32768 creates a Boolean mask:dem =[[ 150, 300], [-32768, 1200]]; The mask becomes:[[False, False], [ True, False]]
        # SRTM commonly uses -32768 as a NoData value; replace with NaN
        dem[dem <= -32768] = np.nan

        zones = np.select(
            [
                dem < 200, (dem >= 200) & (dem < 500), (dem >= 500) & (dem < 1000), (dem >= 1000) & (dem < 1500),
                (dem >= 1500) & (dem < 2000), (dem >= 2000) & (dem < 2500), (dem >= 2500) & (dem < 3000), dem >= 3000
            ],
            labels,
            default="NoData"
        )
        # Counts how many pixels belong to each elevation zone and stores the results in a DataFrame.
        unique, counts = np.unique(zones, return_counts=True)
        tmp = pd.DataFrame({"ELEVATION_ZONE": unique, "PIXELS": counts })

        all_counts.append(tmp)


# In[29]:


# Combine tiles (SRTM tiles, pixel counts per elevation zone)
area_df = pd.concat(all_counts).groupby("ELEVATION_ZONE").sum().reset_index()
area_df = area_df[area_df["ELEVATION_ZONE"] != "NoData"]


# In[30]:


# Check NaN is not included
area_df = area_df[area_df["ELEVATION_ZONE"] != "NoData"].copy()
area_df.isna().value_counts()


# In[31]:


# Mere Numberator (Conflict) and Denominator (Area)
conflict_density=conflict_stat.merge(area_df,on="ELEVATION_ZONE", how="left")

# Relative Density (Even/Event Total); conflict share of each elecation zone
conflict_density["CONFLICT_SHARE"] = (conflict_density["EVENTS"] / conflict_density["EVENTS"].sum())

# Average deaths per event (It tells how deadly each event is on average.)
conflict_density["FATALITIES_SHARE"] = (conflict_density["FATALITIES"] / conflict_density["FATALITIES"].sum())

# Land share of each Elecation zone
conflict_density["LAND_SHARE"]=(conflict_density["PIXELS"]/conflict_density["PIXELS"].sum())

# The following two facts tells “How intense conflict is relative to space”
# Conflict(Events) density: EVENTS / LAND_SHARE
conflict_density["EVENT_DENSITY"] = conflict_density["EVENTS"]/conflict_density["LAND_SHARE"]
# Fatality density
conflict_density["FATALITIES_DENSITY"] = conflict_density["FATALITIES"]/conflict_density["LAND_SHARE"]

conflict_density


# In[3]:


import os

os.startfile(os.getcwd())


# In[ ]:




