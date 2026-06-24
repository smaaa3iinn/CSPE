import geopandas as gpd
from pathlib import Path

path = Path(r"C:\Users\LEGION\Desktop\CSPE\data\raw\geo\traces-des-lignes-de-transport-en-commun-idfm.geojson")
gdf = gpd.read_file(path)

print("route_type unique:")
print(gdf["route_type"].value_counts(dropna=False).sort_index())

print("\ntype unique:")
print(gdf["type"].value_counts(dropna=False).head(50))

print("\nnetworkname unique:")
print(gdf["networkname"].value_counts(dropna=False).head(50))

print("\noperatorname unique:")
print(gdf["operatorname"].value_counts(dropna=False).head(50))

print("\nSample rows:")
print(gdf[["route_short_name", "route_long_name", "route_type", "type", "networkname", "operatorname"]].head(30).to_string())