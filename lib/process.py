from shapely.geometry import LineString
from pyproj import CRS
from tqdm import tqdm

import lib.network as net
import pandas as pd
import geopandas as gpd
import trackintel as ti

yvn_polygon = gpd.read_file('./polygons/yerevan/yerevan.shp').set_crs('EPSG:4326')

class Person:
    """
    Description:
    - Represents an individual tracked by a device, containing
      their device ID, sorted position fixes, and segments.

    Instance variables:
    - id: A unique identifier for the person.
    - path: DataFrame containing the sorted position fixes of the person, sorted by timestamp.
    - segments: DataFrame containing segments generated from the sorted position fixes.
    """
    def __init__(self, id: str, positionfixes: ti.Positionfixes):
        self.id = id
        self.pfs = positionfixes.sort_values(by='tracked_at')

        self.sp = None
        self.tpls = None
        
    def __str__(self):
        return self.pfs
    
    def group_pfs_by_date(self):
        grouped = self.pfs.groupby(self.pfs['tracked_at'].dt.date)
        grouped_pfs = []
        
        for date, group_data in grouped:
            grouped_pfs.append(group_data)
            
        return grouped_pfs
    
    def group_sp_by_date(self):
        grouped = self.sp.groupby(self.sp['started_at'].dt.date)
        grouped_sp = []
        
        for date, group_data in grouped:
            grouped_sp.append(group_data)
        
        return grouped_sp

    def group_tpls_by_date(self):
        grouped_tpls = []
        grouped = self.tpls.groupby(self.tpls['started_at'].dt.date)

        for data, group_data in grouped:
            grouped_tpls.append(group_data)
    
        return grouped_tpls

    def generate_staypoints(self):
        days = self.group_pfs_by_date()
        sp_days = []

        for day in days:
            if (len(day) <= 1):
                continue

            p, sp = day.generate_staypoints(method='sliding', dist_threshold=100, time_threshold=5.0, gap_threshold=15.0)
           
            if (not sp.empty):
                sp_days.append((p, sp)) # Array of staypoints for each day ... item tuple(pfs, sp)

       
        self.pfs = pd.concat([item[0] for item in sp_days])
        self.sp = pd.concat([item[1] for item in sp_days])
        
    def generate_triplegs(self):
        triplegs = pd.DataFrame(columns=['user_id', 'started_at', 'finished_at', 'distance', 'geom'])

        pfs_days = self.group_pfs_by_date()
        sp_days = self.group_sp_by_date()
        
        for index in range(len(pfs_days)):
            day = pfs_days[index].sort_values(by='tracked_at')
            sp = sp_days[index].sort_values(by='started_at')

            if (len(sp) <= 1):
                dist, path = self._distance_in_between(day)
                tripleg = self._create_tripleg(day, dist, path)
                triplegs.loc[len(triplegs)] = tripleg
                continue

            for pos in range(len(sp) - 1):
                dist, path = self._distance_in_between(day, sp, pos)         
                tripleg = self._create_tripleg(day, dist, path, sp, pos)

                triplegs.loc[len(triplegs)] = tripleg
        
        triplegs = triplegs.set_geometry('geom')
        self.tpls = ti.Triplegs(triplegs)
    

    
    # ---------------- UTILITY FUNCTIONS ---------------- #
    
    def _distance_in_between(self, pfs, sp=None, pos=-1):
        dist = 0
        path = list()

        if (sp is not None) and (pos != -1):
            pfs = pfs[(pfs['tracked_at'] >= sp.iloc[pos]['started_at']) & (pfs['tracked_at'] < sp.iloc[pos+1]['finished_at'])]

        for i in range(len(pfs) - 1):
            first = pfs.iloc[i]['geom']
            second = pfs.iloc[i+1]['geom']
            distance, shortest_path = net.distance(first, second)

            dist += distance
            path = path[:-1] + shortest_path
        
        return dist, path
    
    def _create_tripleg(self, day, dist, path, sp=None, pos=-1):
        # Create LineString from the shortest paths
        path_coord = [(net.graph.nodes[node]['x'], net.graph.nodes[node]['y']) for node in path]
        path = LineString(path_coord)

        # Creaet the geometry of the origin and destination
        if (sp is not None) and (pos != -1):
            start = sp.iloc[pos]['finished_at']
            end = sp.iloc[pos + 1]['started_at']
        else:
            start = day.iloc[0]['tracked_at']
            end = day.iloc[len(day) - 1]['tracked_at']

        tripleg = {
            'user_id': day.iloc[pos]['user_id'],
            'started_at': start,
            'finished_at': end,
            'distance': dist,
            'geom': path,
        }

        return tripleg


# -------------------------------------------------------------- #
#                  MAIN PRE-PROCESSING FUNCTIONS                 #
# -------------------------------------------------------------- #

def read_positionfixes(file_path):
    usecols = ['identifier', 'timestamp', 'device_lat', 'device_lon']
    columns = {'identifier': 'user_id', 'timestamp': 'tracked_at',
               'device_lat': 'latitude', 'device_lon': 'longitude'}

    return ti.io.read_positionfixes_csv(
        file_path, usecols=usecols, columns=columns, sep=",", tz='UTC', index_col=None, crs=CRS.from_epsg(4326)
    )

def extract_people(pfs: ti.Positionfixes):
    people = []

    # Group position fixes by device_id
    grouped = pfs.groupby('user_id')

    # Iterate over each device group
    for uid, group in tqdm(grouped, colour='GREEN', desc='People Extracted: '):
        person = Person(uid, group)
        people.append(person)

    return people

def update_staypoints(people, sp):
    grouped = sp.groupby('user_id')

    for person in people:
        if person.id in grouped.groups:
            person.sp = grouped.get_group(person.id)

def clean_staypoints(people):
    cln_people = []

    for person in tqdm(people, colour='Green', desc='People Cleaned: '):
        sp = person.sp
        pfs = person.pfs

        sp['count'] = sp['started_at'].dt.date.map(sp['started_at'].dt.date.value_counts())
        dates_removed = sp[sp['count'] == 1]['started_at'].dt.date.unique()

        # Remove positionfixes with dates in dates_removed
        pfs = pfs[~pfs['tracked_at'].dt.date.isin(dates_removed)]

        # Remove the unneccessary staypoints
        sp = sp[sp['count'] > 1]
        sp.drop(columns=['count'], inplace=True)

        # Update the pfs and staypoints
        if not pfs.empty and not sp.empty:
            person.pfs = pfs
            person.sp = sp
            cln_people.append(person)
        
    return cln_people
        

def filter_yerevan_data(pfs: ti.Positionfixes):
    gdf = gpd.GeoDataFrame(pfs, crs=yvn_polygon.crs, geometry='geom')
    points_in_yvn = gpd.sjoin(yvn_polygon, gdf, predicate='contains')

    filtered_indices = points_in_yvn['index_right'].unique()
    filtered_pfs = pfs[pfs.index.isin(filtered_indices)]

    return filtered_pfs.reset_index(drop=True)


# //TODO: Work from parking polygons with the density of people look into Madina