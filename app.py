from flask import Flask, send_file, render_template, request, session
import osmnx as ox
import networkx as nx
import folium
import os
import heapq
from collections import defaultdict

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'default-fallback') # Dibutuhkan untuk session

GRAPH_PATH = "depok.graphml"

# Ambil graph dari file atau download baru
if os.path.exists(GRAPH_PATH):
    print("Loading graph from file...")
    G = ox.load_graphml(GRAPH_PATH)
else:
    print("Downloading graph...")
    G = ox.graph_from_place("Depok, Indonesia", network_type='drive')
    ox.save_graphml(G, GRAPH_PATH)

# Daftar lokasi
lokasi_pilihan = {
    "UI Depok": (-6.3646, 106.8266),
    "Stasiun Pondok Cina": (-6.368588078493545, 106.83206363708297),
    "Stasiun Depok Baru": (-6.3909700611949445, 106.82170072359146),
    "Margo City Mall": (-6.373446618263608, 106.83389863708304),
    "Depok Town Square": (-6.372362129346898, 106.83167450548203),
    "Kampus D Gunadarma": (-6.368906678945894, 106.83320512883571)
}

def is_margonda_edge(graph, u, v):
    edge_data = graph.get_edge_data(u, v)
    if edge_data:
        for key, data in edge_data.items():
            name = str(data.get('name', '')).lower()
            if "margonda" in name:
                return True
    return False

def dijkstra_with_margonda_preference(graph, start_node, end_node, margonda_penalty=500):
    # Inisialisasi
    distances = defaultdict(lambda: float('infinity'))
    previous_nodes = {}
    distances[start_node] = 0
    heap = [(0, start_node)]
    
    while heap:
        current_dist, current_node = heapq.heappop(heap)
        
        # Jika sudah sampai tujuan, hentikan pencarian
        if current_node == end_node:
            break
            
        # Jika jarak saat ini lebih besar dari yang tercatat, lewati
        if current_dist > distances[current_node]:
            continue
            
        for neighbor in graph.neighbors(current_node):
            edge_data = graph.get_edge_data(current_node, neighbor)
            if not edge_data:
                continue
                
            # Temukan edge dengan panjang minimum
            min_length = min(data.get('length', float('infinity')) for _, data in edge_data.items())
            
            # Tambahkan penalti jika ini jalan Margonda
            additional_penalty = margonda_penalty if is_margonda_edge(graph, current_node, neighbor) else 0
            distance = current_dist + min_length + additional_penalty
            
            if distance < distances[neighbor]:
                distances[neighbor] = distance
                previous_nodes[neighbor] = current_node
                heapq.heappush(heap, (distance, neighbor))
    
    # Rekonstruksi jalur
    path = []
    current_node = end_node
    while current_node is not None:
        path.append(current_node)
        current_node = previous_nodes.get(current_node, None)
    
    path.reverse()
    
    return path if path and path[0] == start_node else None

def get_route_details(graph, route):
    details = {
        'total_length': 0,
        'margonda_segments': 0,
        'margonda_length': 0,
        'path': []
    }
    
    for i in range(len(route)-1):
        u = route[i]
        v = route[i+1]
        edge_data = graph.get_edge_data(u, v)
        
        if not edge_data:
            continue
            
        # Ambil edge dengan panjang terpendek
        best_edge = min(edge_data.items(), key=lambda x: x[1].get('length', float('infinity')))
        length = best_edge[1].get('length', 0)
        name = str(best_edge[1].get('name', ''))
        
        details['total_length'] += length
        details['path'].append({
            'from': u,
            'to': v,
            'length': length,
            'name': name,
            'is_margonda': "margonda" in name.lower()
        })
        
        if "margonda" in name.lower():
            details['margonda_segments'] += 1
            details['margonda_length'] += length
    
    return details

@app.route("/", methods=["GET", "POST"])
def index():
    peta = None
    error_message = None
    route_details = None

    # Inisialisasi session jika belum ada
    if 'selected_asal' not in session:
        session['selected_asal'] = next(iter(lokasi_pilihan.keys()))
    if 'selected_tujuan' not in session:
        session['selected_tujuan'] = next(iter(lokasi_pilihan.keys()))

    if request.method == "POST":
        asal = request.form["asal"]
        tujuan = request.form["tujuan"]
        
        # Simpan pilihan ke session
        session['selected_asal'] = asal
        session['selected_tujuan'] = tujuan
        
        start_coords = lokasi_pilihan[asal]
        end_coords = lokasi_pilihan[tujuan]

        try:
            # Temukan node terdekat
            start_node = ox.distance.nearest_nodes(G, start_coords[1], start_coords[0])
            end_node = ox.distance.nearest_nodes(G, end_coords[1], end_coords[0])

            # Cari rute dengan preferensi menghindari Margonda
            route = dijkstra_with_margonda_preference(G, start_node, end_node)
            
            if not route:
                raise ValueError("Tidak ditemukan rute yang memungkinkan")

            # Dapatkan detail rute
            route_details = get_route_details(G, route)
            route_details['asal'] = asal
            route_details['tujuan'] = tujuan

            # Buat peta
            lat_center = (start_coords[0] + end_coords[0]) / 2
            lon_center = (start_coords[1] + end_coords[1]) / 2
            peta = folium.Map(location=[lat_center, lon_center], zoom_start=14)

            # Gambar rute dengan warna berbeda untuk segmen Margonda
            for i in range(len(route)-1):
                u = route[i]
                v = route[i+1]
                edge_data = G.get_edge_data(u, v)
                
                if not edge_data:
                    continue
                    
                # Ambil edge dengan panjang terpendek
                best_edge = min(edge_data.items(), key=lambda x: x[1].get('length', float('infinity')))
                is_margonda = "margonda" in str(best_edge[1].get('name', '')).lower()
                
                segment_coords = [
                    (G.nodes[u]['y'], G.nodes[u]['x']),
                    (G.nodes[v]['y'], G.nodes[v]['x'])
                ]
                
                color = "red" if is_margonda else "blue"
                weight = 6 if is_margonda else 4
                
                folium.PolyLine(
                    segment_coords,
                    color=color,
                    weight=weight,
                    opacity=0.7,
                    popup=f"{best_edge[1].get('name', 'Unnamed')} ({best_edge[1].get('length', 0):.0f} m)"
                ).add_to(peta)

            # Tambahkan marker
            folium.Marker(
                location=start_coords, 
                popup=f"Asal: {asal}", 
                icon=folium.Icon(color='green')
            ).add_to(peta)
            
            folium.Marker(
                location=end_coords, 
                popup=f"Tujuan: {tujuan}", 
                icon=folium.Icon(color='red')
            ).add_to(peta)

            # Simpan peta
            peta.save("static/peta.html")

        except Exception as e:
            print(f"Error saat mencari rute: {e}")
            error_message = str(e)

    return render_template(
        "index.html", 
        lokasi=lokasi_pilihan.keys(), 
        peta=peta is not None, 
        error=error_message,
        route_details=route_details,
        selected_asal=session.get('selected_asal', ''),
        selected_tujuan=session.get('selected_tujuan', '')
    )


if __name__ == "__main__":
    app.run(debug=True)