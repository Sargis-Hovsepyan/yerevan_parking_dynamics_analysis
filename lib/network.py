import osmnx as ox
import networkx as nx

from shapely.geometry import Point

# Getting the Street Network for Yerevan from OpenStreetMap
graph = ox.graph_from_place("Yerevan, Armenia", simplify=True)

# OSM data are sometime incomplete so we use the speed module of osmnx to add missing edge speeds and travel times
graph = ox.add_edge_speeds(graph)
graph = ox.add_edge_travel_times(graph)

def distance(origin: Point, destination: Point, path_nodes=True):
    orig_node = ox.nearest_nodes(graph, origin.x, origin.y)
    target_node = ox.nearest_nodes(graph, destination.x, destination.y)

    shortest_path = nx.shortest_path(graph, orig_node, target_node, weight='length') if path_nodes else None
    distance = nx.shortest_path_length(G=graph, source=orig_node, target=target_node, weight='length')

    return distance, shortest_path