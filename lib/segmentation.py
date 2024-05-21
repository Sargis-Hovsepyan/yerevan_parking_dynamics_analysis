import pandas as pd
import geopandas as gpd
import trackintel as ti
import lib.network as net

from shapely.geometry import Point, LineString
from pyproj import CRS

def convert_to_segments(pfs: ti.Positionfixes):
    data_segments = []

    pfs.sort_values(by='tracked_at')
    for i in range(len(pfs) - 1):
        # Get two adjacent position fixes
        p1 = pfs.iloc[i]['geom']
        p2 = pfs.iloc[i + 1]['geom']

        t1 = pfs.iloc[i]['tracked_at']
        t2 = pfs.iloc[i + 1]['tracked_at']

        # Calculate distance, duration and avarage speed between two fixes
        try:
            distance, path = net.distance(p1, p2)
        except:
            continue

        duration = (t2 - t1).total_seconds()
        average_speed = distance / duration if duration > 0 else 0

        # Constructing the path through street map
        path_coord = [(net.graph.nodes[node]['x'], net.graph.nodes[node]['y']) for node in path]
        path = LineString(path_coord) if len(path_coord) > 1 else p1
        # path = LineString([p1, p2])

        segment = {
            'user_id': pfs.iloc[i]['user_id'],
            'started_at': t1,
            'finished_at': t2,
            'distance': distance,
            'duration': duration,
            'avg_speed': average_speed,
            'geom': path
        }
        data_segments.append(segment)

    return data_segments

def merge_segments(segments, v_thresh=0.6):
    """
    Merge adjacent data segments with the same status into one data segment.

    Parameters:
        segments (list): List of data segments represented as dictionaries.
        v_thresh (float): Speed threshold in m/s for identifying moving segments.

    Returns:
        list: List of merged data segments with calculated status.
    """
    merged_segments = []

    i = 0
    while i < len(segments):
        # Initialize variables for merging
        j = i + 1
        merged_distance = segments.iloc[i]['distance']
        merged_duration = segments.iloc[i]['duration']
        merged_geom = segments.iloc[i]['geom']

        # Calculate status of the first segment
        status = 1 if segments.iloc[i]['avg_speed'] > v_thresh else 0

        # Merge adjacent segments with the same status
        while j < len(segments):
            # Calculate status of the current segment
            current_status = 1 if segments.iloc[j]['avg_speed'] > v_thresh else 0

            # Check if the status of the current segment matches the status of the first segment
            if current_status == status:
                merged_distance += segments.iloc[j]['distance']
                merged_duration += segments.iloc[j]['duration']
                merged_geom = LineString(list(merged_geom.coords) + list(segments.iloc[j]['geom'].coords))
                j += 1
            else:
                break

        # Calculate merged segment attributes
        merged_started_at = segments.iloc[i]['started_at']
        merged_finished_at = segments.iloc[j - 1]['finished_at']
        merged_avg_speed = merged_distance / merged_duration

        # Create merged segment dictionary with status
        merged_segment = {
            'user_id': segments.iloc[i]['user_id'],
            'started_at': merged_started_at,
            'finished_at': merged_finished_at,
            'distance': merged_distance,
            'duration': merged_duration,
            'avg_speed': merged_avg_speed,
            'status': status,
            'geom': merged_geom
        }
        merged_segments.append(merged_segment)

        # Update index for next iteration
        i = j

    return gpd.GeoDataFrame(merged_segments, geometry='geom', crs=CRS.from_epsg(4326))


def adjust_status(merged_segments, t_thresh=30, d_thresh=300):
    # Copy the GeoDataFrame to avoid modifying the original one
    adjusted_gdf = merged_segments.copy()
    
    # Iterate over the rows and adjust the status
    for idx, row in adjusted_gdf.iterrows():
        duration = row['duration']
        distance = row['distance']
        status = row['status']
        
        # Adjust status based on duration and distance thresholds
        if status == 0 and duration < t_thresh:
            adjusted_gdf.iloc[idx]['status'] = 1
        elif status == 1 and distance < d_thresh:
            adjusted_gdf.iloc[idx]['status'] = 0
    
    return adjusted_gdf


# -------------------------------------------------------------- #
#                  MAIN SEGMENTATIUON FUNCTIONS                  #
# -------------------------------------------------------------- #

def segregate(pfs: ti.Positionfixes, v_thresh=0.6, t_thresh=30, d_thresh=300):
    segments = convert_to_segments(pfs)
    segments = merge_segments(segments, v_thresh)
    segments = adjust_status(segments, t_thresh, d_thresh)
    
    return gpd.GeoDataFrame(segments, geometry='geom')

def split_segments_by_user(gdf):
    # Group GeoDataFrame by 'user_id'
    grouped = gdf.groupby('user_id')

    # Initialize an empty list to store GeoDataFrames
    geo_dfs = []

    # Iterate over groups
    for user_id, group in grouped:
        # Convert group to GeoDataFrame
        group_gdf = gpd.GeoDataFrame(group)
        
        # Append GeoDataFrame to the list
        geo_dfs.append(group_gdf)
    
    return geo_dfs

def split_segments_by_date(gdf):
    # Ensure 'started_at' and 'finished_at' are datetime types
    gdf['started_at'] = pd.to_datetime(gdf['started_at'])
    gdf['finished_at'] = pd.to_datetime(gdf['finished_at'])

    # Group DataFrame by date
    grouped = gdf.groupby(gdf['started_at'].dt.date)

    # Initialize an empty list to store GeoDataFrames
    geo_dfs = []

    # Iterate over groups
    for date, group in grouped:
        # Convert 'geom' column to Shapely geometry objects
        group['geom'] = group['geom'].apply(lambda x: Point(x.x, x.y) if x.geom_type == 'Point' else LineString(x.coords))
        
        # Convert DataFrame to GeoDataFrame
        gdf = gpd.GeoDataFrame(group, geometry='geom')
        
        # Append GeoDataFrame to the list
        geo_dfs.append(gdf)
    
    return geo_dfs
