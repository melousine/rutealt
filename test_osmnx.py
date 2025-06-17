import osmnx as ox

print("Start downloading graph")
G = ox.graph_from_place("Depok, Indonesia", network_type='drive')
print("Graph downloaded:", G)
