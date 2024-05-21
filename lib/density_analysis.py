import numpy as np
import pandas as pd
import geopandas as gpd

import matplotlib.pyplot as plt
import matplotlib as mpl

mpl.rcParams['figure.facecolor'] = 'white'
rl_polygons = gpd.read_file('polygons/yerevan_red_lines/yerevan_only_red_lines.shp')


# ---------------- Filtering the points inside the red lines ----------------- #

def filter_points_inside_polygons(positionfixes, buffer=0.5): 
    gdf = gpd.GeoDataFrame(positionfixes, geometry='geom')
    polygons_gdf = gpd.GeoDataFrame(rl_polygons, geometry='geometry')
    
    # Taking the polygons with some buffer
    polygons_gdf = create_buffer(polygons_gdf, 0.5, 'geom')
    joined = gpd.sjoin(gdf, polygons_gdf, how="inner", op='within')

    joined.rename(columns={'id': 'belongs_to'}, inplace=True)
    joined.drop(index=joined.index[0], inplace=True) # First polygon is empty

    return joined.drop(columns=['index_right'])

def create_buffer(geopandas_df : gpd.GeoDataFrame, buffer : float, buffer_col_name : str):
    gdf = geopandas_df.copy(deep=True)

    gdf = gdf.set_crs(4326, allow_override=True)
    gdf = gdf.to_crs(4326)
    
    mean_lat = gdf.geometry.centroid.y.mean()
    mean_long = gdf.geometry.centroid.x.mean()
    
    pojection_string = f'+proj=aeqd +lat_0={mean_lat} +lon_0={mean_long} +k=1 +x_0=0 +y_0=0 +ellps=WGS84 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs'
    gdf = gdf.to_crs(pojection_string)
    
    gdf[buffer_col_name] = gdf.geometry.buffer(buffer).to_crs(4326)
    gdf['geometry'] = gdf.geometry.to_crs(4326)
   
    gdf = gdf.drop(['geometry'],axis=1)
    gdf = gdf.set_geometry(buffer_col_name).to_crs(4326)
    
    return gdf

def break_geometry_points(pfs):
    # Define a function to extract latitude and longitude from Point objects
    def extract_lat_lon(point):
        lat = point.y
        lon = point.x
        return pd.Series({'latitude': lat, 'longitude': lon})

    pfs[['latitude', 'longitude']] = pfs['geom'].apply(extract_lat_lon)
    pfs.drop(columns=['geom'], inplace=True)

    return pfs

def add_point_density_columns(pfs_rl, polygons=rl_polygons):
    # Group pfs_rl by belongs_to and count points in each polygon
    counts = pfs_rl.groupby('belongs_to').size().reset_index(name='points')

    # Merge counts with polygons
    polygons_with_counts = polygons.merge(counts, left_on='id', right_on='belongs_to', how='left')

    # Calculate the area of each polygon
    polygons_with_counts['area'] = polygons_with_counts.geometry.area

    # Calculate point density ratio (points per unit area)
    polygons_with_counts['density'] = polygons_with_counts['points'] / polygons_with_counts['area']

    # Save the modified polygons GeoDataFrame
    polygons_with_counts.to_file('./geojson/polygons_with_density.geojson', driver='GeoJSON')

    return polygons_with_counts


# ---------------- Grouping pfs by weeks, months ----------------- #

def group_pfs_by_months(pfs):
    # Group position fixes by month
    pfs_grouped = pfs.groupby(pd.Grouper(key='tracked_at', freq='M'))
    pfs_monthly = []

    for month, group in pfs_grouped:
        pfs_monthly.append(group)

    return pfs_monthly

def group_pfs_by_weeks(pfs):
    # Group position fixes by week
    pfs_grouped = pfs.groupby(pd.Grouper(key='tracked_at', freq='W'))
    pfs_weekly = []
    
    for week, group in pfs_grouped:
        pfs_weekly.append(group)

    return pfs_weekly

def group_pfs_by_weekdays(pfs):
    pfsw = group_pfs_by_weeks(pfs)
    
    pfs_weekdays = []
    pfs_weekends = []
    
    for week in pfsw:
        weekdays = pd.concat([week[(week['tracked_at'].dt.dayofweek < 5)]], ignore_index=True)
        weekends = pd.concat([week[(week['tracked_at'].dt.dayofweek >= 5)]], ignore_index=True)
        
        pfs_weekdays.append(weekdays)
        pfs_weekends.append(weekends)
    
    return pfs_weekdays, pfs_weekends


# --------------- People in Polygons Analysyis -------------- #

def count_people_in_polygons(people_rl):
    polygon_people = {}

    for person in people_rl:
        unique_polygons = person.pfs['belongs_to'].unique()
        for polygon in unique_polygons:
            if polygon in polygon_people:
                polygon_people[polygon].add(person.id)
            else:
                polygon_people[polygon] = {person.id}

    result = {polygon: len(users) for polygon, users in polygon_people.items()}
    return result

def calculate_duration(person):
    person.pfs.reset_index(inplace=True)

    pfs_by_date = person.group_pfs_by_date()
    durations = []
    
    # Iterate over each row in the sorted DataFrame
    for day in pfs_by_date:
        grouped = day.groupby('belongs_to')

        for polygon_id, group in grouped:
            start_time = group['tracked_at'].min()
            end_time = group['tracked_at'].max()
            duration = end_time - start_time

            durations.append({
                'user_id': person.id,
                'polygon_id': polygon_id,
                'started_at': start_time,
                'finished_at': end_time,
                'duration': duration,
            })
    
    # Create a DataFrame from the list of durations
    durations_df = pd.DataFrame(durations)
    
    return durations_df

# ---------------- Visualization ----------------- #

def monthly_percentage_graph(pfs_months, rl_months, ax=None):
    # Initialize lists to store percentages and months
    rl_percentages, pfs_counts = [], []

    year = pfs_months[0].iloc[0]['tracked_at'].year
    months = [1,2,3,4,5,6,7,8,9,10,11,12]
    labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    for m in range(len(pfs_months)):
        # Calculate the percentage of red lines
        if len(pfs_months[m]) > 0:
            red_lines_percentage = (len(rl_months[m]) / len(pfs_months[m])) * 100
        else:
            red_lines_percentage = 0
        
        # Append the percentage and month
        rl_percentages.append(red_lines_percentage)
        pfs_counts.append(len(pfs_months[m]))

    # Plotting
    if ax is None:
        plt.figure(figsize=(12, 8))
        ax = plt.gca()

    ax.bar(months, rl_percentages, color='red', label='Red Lines Percentage')
    
    ax.set_xlabel('Month')
    ax.set_ylabel('Percentage')
    ax.set_title('Percentage of Points in Red Lines for {}'.format(year))
    
    ax.set_xticks(months)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, max(rl_percentages) + 10)  # Add some padding for better visualization
    
    ax.grid(True, linestyle='--', alpha=0.5)

    # Create a second y-axis for position fixes count
    ax2 = ax.twinx()
    ax2.plot(months, pfs_counts, color='blue', label='Position Fixes Count')
    
    ax2.set_ylabel('Position Fixes Count')
    ax2.set_ylim(0, max(pfs_counts) + 1000)  # Add some padding for better visualization

    # Display legend
    ax.legend(loc='upper left')
    ax2.legend(loc='upper right')

    plt.tight_layout()
    if ax is None:
        plt.show()

def weekly_percentage_graph(pfs_weeks, rl_weeks, ax=None):
    # Initialize lists to store percentages and weeks
    rl_percentages, pfs_counts = [], []
    weeks = list(range(1, len(pfs_weeks) + 1))

    for pfs_week, rl_week in zip(pfs_weeks, rl_weeks):
        # Calculate the percentage of red lines
        if len(pfs_week) > 0:
            red_lines_percentage = (len(rl_week) / len(pfs_week)) * 100
        else:
            red_lines_percentage = 0

        # Append the percentage and position fixes count
        rl_percentages.append(red_lines_percentage)
        pfs_counts.append(len(pfs_week))

    # Plotting
    if ax is None:
        plt.figure(figsize=(12, 8))
        ax = plt.gca()

    ax.bar(weeks, rl_percentages, color='red', alpha=0.7)

    ax.set_xlabel('Week')
    ax.set_ylabel('Percentage of Points in Red Lines')
    ax.set_title('Percentage of Points in Red Lines by Week {}'.format(pfs_weeks[0].iloc[0]['tracked_at'].year))
    
    ax.set_xticks(weeks)
    ax.set_xticklabels(weeks, fontsize=8)
    
    ax.set_ylim(0, max(rl_percentages) + 10)  # Add some padding for better visualization
    ax.grid(True, linestyle='--', alpha=0.5)

    # Create a secondary y-axis for position fixes count
    ax2 = ax.twinx()
    ax2.plot(weeks, pfs_counts, color='blue', linestyle='--', marker='o', label='Position Fixes Count')
    
    ax2.set_ylabel('Position Fixes Count')
    ax2.set_ylim(0, max(pfs_counts) + 100)  # Add some padding for better visualization
    
    # Display legend
    ax2.legend(loc='upper right')

    plt.tight_layout()
    if ax is None:
        plt.show()

def weekdays_percentage_graph(pfs, pfs_rl, ax=None):
    pfs_rlw_weekdays, pfs_rlw_weekends = group_pfs_by_weekdays(pfs_rl)
    pfsw_weekdays, pfsw_weekends = group_pfs_by_weekdays(pfs)

    rlw_wd_len = sum([len(week) for week in pfs_rlw_weekdays])
    rlw_we_len = sum([len(week) for week in pfs_rlw_weekends])
    pfsw_wd_len = sum([len(week) for week in pfsw_weekdays])
    pfsw_we_len = sum([len(week) for week in pfsw_weekends])

    # Calculate percentages
    weekdays_percent = (rlw_wd_len / pfsw_wd_len) * 100
    weekends_percent = (rlw_we_len / pfsw_we_len) * 100

    # Plotting
    labels = [f'Weekdays (n={pfsw_wd_len})', f'Weekends (n={pfsw_we_len})']
    percentages = [weekdays_percent, weekends_percent]

    if ax is None:
        plt.figure(figsize=(12, 8))
        ax = plt.gca()

    ax.bar(labels, percentages, color=['blue', 'orange'])
    
    ax.set_xlabel('Day Type')
    ax.set_ylabel('Percentage')
    ax.set_title('Percentage of Weekday and Weekend Position Fixes Inside Red Lines')

    ax.set_ylim(0, max(percentages) + 10)  # Add some padding for better visualization

    # Add labels on top of bars
    for i in range(len(labels)):
        ax.text(i, percentages[i] + 1, f'{percentages[i]:.2f}%', ha='center', va='bottom')

    plt.tight_layout()
    if ax is None:
        plt.show()


def graph_subplots(pfs_data, rl_data, titles_list, graph_func, x_lable, y_lable, suptitle):
    # Calculate the number of subplots needed
    num_plots = len(pfs_data)
    num_rows = int(np.ceil(num_plots / 2))

    # Create subplots
    fig, axes = plt.subplots(num_rows, 2, figsize=(15, 5*num_rows))
    fig.suptitle(suptitle, fontsize=16)

    for i in range(num_rows):
        for j in range(2):
            plot_idx = i * 2 + j
            if plot_idx < num_plots:  # Check if index is within bounds
                # Call the appropriate plotting function with the corresponding data
                graph_func(pfs_data[plot_idx], rl_data[plot_idx], ax=axes[i, j])
                axes[i, j].set_title(titles_list[plot_idx])
                axes[i, j].set_xlabel(x_lable)
                axes[i, j].set_ylabel(y_lable)
            else:
                axes[i, j].axis('off')  # Hide empty subplot

    # Adjust layout to prevent overlap of subplots
    plt.tight_layout()
    plt.show()


def plot_people_per_polygon(counts):
    polygons = list(counts.keys())
    num_people = list(counts.values())

    plt.figure(figsize=(10, 6))
    plt.bar(polygons, num_people, color='skyblue')
    plt.xlabel('Polygon ID')
    plt.ylabel('Number of Unique People')
    plt.title('Number of Unique People per Polygon')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

# ---------------- Distributions ---------------- #

def distribution(df, col_name, minutes=False, boxplot=True):
    df = df.copy(deep=True)
    
    if minutes:
        df[col_name] = df[col_name] / 60  # Convert to minutes
        
   # Plot histogram only
    if not boxplot:
        plt.figure(figsize=(8, 6))
        plt.hist(df[col_name], bins=50, color='skyblue', edgecolor='black')
        plt.title(f'Distribution of {col_name}')
        plt.xlabel(col_name)
        plt.ylabel('Frequency')
        plt.grid(True)
        plt.tight_layout()
        plt.show()
    else:
        # Plot both histogram and boxplot
        fig, axes = plt.subplots(nrows=1, ncols=2, figsize=(12, 6))
        
        # Distribution plot
        axes[0].hist(df[col_name], bins=50, color='skyblue', edgecolor='black')
        axes[0].set_title(f'Distribution of {col_name}')
        axes[0].set_xlabel(col_name)
        axes[0].set_ylabel('Frequency')
        axes[0].grid(True)
        
        # Boxplot
        axes[1].boxplot(df[col_name], vert=False)
        axes[1].set_title(f'Boxplot of {col_name}')
        axes[1].set_xlabel(col_name)
        axes[1].grid(True)
        
        plt.tight_layout()
        plt.show() 

    # Calculate summary statistics
    mean_duration = round(df[col_name].mean(), 3)
    median_duration = round(df[col_name].median(), 3)
    mode_duration = round(df[col_name].mode()[0], 3)  # mode could be multiple values, so taking the first one
    quartiles = round(df[col_name].quantile([0.1, 0.25, 0.5, 0.75, 0.9]), 3)
    min_duration = round(df[col_name].min(), 3)
    max_duration = round(df[col_name].max(), 3)

    print("Summary Statistics:\n")
    
    print(f"Mean {col_name}: {mean_duration}")
    print(f"Median {col_name}: {median_duration}")
    print(f"Mode {col_name}: {mode_duration}\n")
    
    print(f"10% Quartile: {quartiles[0.1]}")
    print(f"25% Quartile (Q1): {quartiles[0.25]}")
    print(f"50% Quartile (Q2 or Median): {quartiles[0.5]}")
    print(f"75% Quartile (Q3): {quartiles[0.75]}")
    print(f"90% Quartile: {quartiles[0.9]}\n")

    print(f"Minimum {col_name}: {min_duration}")
    print(f"Maximum {col_name}: {max_duration}")

def boxplot(df, col_name):
    # Plot boxplot
    plt.figure(figsize=(10, 6))
    plt.boxplot(df[col_name], vert=False)
    plt.title(f'Boxplot of {col_name}')
    plt.xlabel(col_name)
    plt.grid(True)
    plt.show()