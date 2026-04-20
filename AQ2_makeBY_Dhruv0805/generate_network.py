"""
generate_network.py
───────────────────
Generates ahmedabad_network.json based on a specific, hand-drawn map.
Draws 3 Main Trunks (Yellow, Green, Red) with perpendicular sub-branches.
"""

import json
import os
import math

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ahmedabad_network.json')
STEP = 0.00045  # ~50 meters spacing


def build_path(zone_id, waypoints, branches_config):
    nodes = []
    trunk_nodes = []
    
    # 1. Build the Main Trunk (The colored lines)
    start_node = {
        'id': f"{zone_id}-T0",
        'lat': waypoints[0][0],
        'lon': waypoints[0][1],
        'type': 'segment',
        'parent_id': None
    }
    nodes.append(start_node)
    trunk_nodes.append(start_node)
    pid = start_node['id']
    node_count = 1
    
    # Interpolate points along the waypoints
    for i in range(len(waypoints) - 1):
        p1 = waypoints[i]
        p2 = waypoints[i+1]
        dist = math.hypot(p2[0]-p1[0], p2[1]-p1[1])
        steps = int(dist / STEP)
        if steps == 0: continue
        
        for s in range(1, steps + 1):
            lat = p1[0] + (p2[0]-p1[0]) * s / steps
            lon = p1[1] + (p2[1]-p1[1]) * s / steps
            nid = f"{zone_id}-T{node_count}"
            
            n = {
                'id': nid, 'lat': round(lat, 7), 'lon': round(lon, 7),
                'type': 'segment', 'parent_id': pid
            }
            nodes.append(n)
            trunk_nodes.append(n)
            pid = nid
            node_count += 1

    # 2. Build the Sub-branches (The black lines)
    b_count = 0
    for pct, angle_deg, length in branches_config:
        # Find the node on the main trunk at the specified percentage (e.g., 20% down the line)
        idx = int(pct * len(trunk_nodes))
        if idx >= len(trunk_nodes): idx = len(trunk_nodes) - 1
        root = trunk_nodes[idx]
        
        # Calculate the direction the main trunk is facing
        p_prev = trunk_nodes[max(0, idx - 5)]
        p_next = trunk_nodes[min(len(trunk_nodes) - 1, idx + 5)]
        trunk_angle = math.atan2(p_next['lat'] - p_prev['lat'], p_next['lon'] - p_prev['lon'])
        
        # Snap the branch perfectly perpendicular (or angled) to the trunk
        branch_angle = trunk_angle + math.radians(angle_deg)
        
        b_pid = root['id']
        curr_lat, curr_lon = root['lat'], root['lon']
        
        for s in range(1, length + 1):
            curr_lat += STEP * math.sin(branch_angle)
            curr_lon += STEP * math.cos(branch_angle)
            nid = f"{zone_id}-B{b_count}"
            
            nodes.append({
                'id': nid, 'lat': round(curr_lat, 7), 'lon': round(curr_lon, 7),
                'type': 'branch', 'parent_id': b_pid
            })
            b_pid = nid
            b_count += 1

    return nodes


def main():
    zones = {}
    
    # ── YELLOW ZONE (Mapped to Z1) ──
    # Trunk: Starts North near Sabarmati, curves South-West towards Sarkhej
    BLUE_waypoints = [(23.13, 72.56), (23.08, 72.54), (23.03, 72.51), (22.98, 72.48)]
    # Branches: (Percentage down trunk, angle off trunk, length of branch)
    BLUE_branches = [(0.15, 90, 45), (0.35, -90, 35), (0.60, 90, 50), (0.80, -90, 40), (0.90, 90, 25)]
    zones['ZONE_BLUE'] = build_path('ZONE_BLUE', BLUE_waypoints, BLUE_branches)
    
    # ── GREEN ZONE (Mapped to Z2) ──
    # Trunk: Starts North-East, drops straight South past Kathwada/Hathijan
    YELLOW_waypoints = [(23.11, 72.64), (23.06, 72.65), (23.00, 72.66), (22.95, 72.65)]
    YELLOW_branches = [(0.20, 90, 30), (0.45, -90, 45), (0.70, 90, 35), (0.85, -90, 40)]
    zones['ZONE_YELLOW'] = build_path('ZONE_YELLOW', YELLOW_waypoints, YELLOW_branches)
    
    # ── RED ZONE (Mapped to Z3) ──
    # Trunk: Starts West near Thaltej, cuts straight across Central to the East
    GREEN_waypoints = [(23.05, 72.50), (23.04, 72.55), (23.02, 72.60), (23.01, 72.65)]
    GREEN_branches = [(0.10, 90, 35), (0.30, -90, 25), (0.55, 90, 45), (0.75, -90, 30)]
    zones['ZONE_GREEN'] = build_path('ZONE_GREEN', GREEN_waypoints, GREEN_branches)

    with open(OUTPUT_PATH, 'w') as f:
        json.dump({'zones': zones}, f, indent=2)

    total = sum(len(v) for v in zones.values())
    print("-" * 50)
    print(f"✅ Generated specific map design with {total} total segments.")
    print(f"✅ Saved network to: {OUTPUT_PATH}")

if __name__ == '__main__':
    main()