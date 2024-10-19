import os
import re
import json

def parse_assets_file(assets_file_path):
    device_info = {}
    with open(assets_file_path, 'r') as file:
        lines = file.readlines()
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 6:
                device_name = parts[0]
                device_info[device_name] = {
                    "primaryIP": parts[1],
                    "mac": parts[2],
                    "serial_number": parts[3],
                    "model": parts[4],
                    "version": parts[5]
                }
    return device_info

def parse_lldp_results(directory, device_info):
    topology_data = {
        "links": [],
        "nodes": []
    }

    device_nodes = {}
    device_id = 0
    link_id = 0

    for device_name, info in device_info.items():
        if "border" in device_name.lower():
            layer_sort_preference = 4
        elif "superspine" in device_name.lower():
            layer_sort_preference = 5
        elif "spine" in device_name.lower():
            layer_sort_preference = 6
        elif "leaf" in device_name.lower():
            layer_sort_preference = 7
        else:
            layer_sort_preference = 9

        device_node = {
            "icon": "switch",
            "id": device_id,
            "layerSortPreference": layer_sort_preference,
            "name": device_name,
            "primaryIP": info["primaryIP"],
            "model": info["model"],
            "serial_number": info["serial_number"]
        }
        topology_data["nodes"].append(device_node)
        device_nodes[device_name] = device_id
        device_id += 1

    for filename in os.listdir(directory):
        filepath = os.path.join(directory, filename)

        if not filename.endswith("_lldp_result.ini"):
            continue

        device_name = filename.split("_lldp_result.ini")[0]

        with open(filepath, 'r') as file:
            data = file.read()

        interface_pattern = r'Interface:\s+(\S+),.*?SysName:\s+(\S+).*?(?:MgmtIP:\s+([\d.]+))?.*?PortID:\s+ifname\s+(\S+)'
        interfaces = re.findall(interface_pattern, data, re.DOTALL)

        for interface in interfaces:
            interface_name, neighbor_device, mgmt_ip, port_descr = interface

            if interface_name.lower() == "eth0" or port_descr.lower() == "eth0":
                continue

            if neighbor_device not in device_nodes:
                continue

            link = {
                "id": link_id,
                "source": device_nodes[device_name],
                "srcDevice": device_name,
                "srcIfName": interface_name,
                "target": device_nodes.get(neighbor_device),
                "tgtDevice": neighbor_device,
                "tgtIfName": port_descr,
                "is_missing": "no"
            }
            topology_data["links"].append(link)
            link_id += 1

    return topology_data, device_nodes, link_id

def parse_topology_dot_file(dot_file_path):
    defined_links = set()
    with open(dot_file_path, 'r') as file:
        for line in file:
            line = line.strip()
            if line.startswith('"') and '--' in line:
                parts = re.findall(r'"(.*?)"', line)
                if len(parts) == 4:
                    src_device, src_ifname, tgt_device, tgt_ifname = parts
                    defined_links.add((src_device, src_ifname, tgt_device, tgt_ifname))
    return defined_links

def find_missing_links_in_topology(lldp_links, defined_links):
    missing_links = []
    seen_links = set()
    for link in lldp_links:
        src_device = link["srcDevice"]
        tgt_device = link["tgtDevice"]
        src_ifname = link["srcIfName"]
        tgt_ifname = link["tgtIfName"]

        forward_link = (src_device, src_ifname, tgt_device, tgt_ifname)
        reverse_link = (tgt_device, tgt_ifname, src_device, src_ifname)

        if forward_link not in defined_links and reverse_link not in defined_links and reverse_link not in seen_links:
            link["is_missing"] = "fail"  # "fail" olarak ayarla
            missing_links.append(link)
            seen_links.add(forward_link)

    return missing_links

def generate_topology_file(output_filename, directory, assets_file_path, dot_file_path):
    device_info = parse_assets_file(assets_file_path)
    topology_data, device_nodes, link_id = parse_lldp_results(directory, device_info)
    defined_links = parse_topology_dot_file(dot_file_path)

    unique_connections = set()
    duplicate_connections = set()

    for link in topology_data["links"]:
        src_device = link["srcDevice"]
        tgt_device = link["tgtDevice"]
        src_ifname = link["srcIfName"]
        tgt_ifname = link["tgtIfName"]

        reverse_link = (tgt_device, tgt_ifname, src_device, src_ifname)

        if reverse_link in unique_connections:
            duplicate_connections.add(reverse_link)

        unique_connections.add((src_device, src_ifname, tgt_device, tgt_ifname))

    unique_nodes = set(device_info.keys())

    # LLDP'de olup topology.dot'da olmayan bağlantıları bul ve is_missing değerini "fail" yap
    missing_links = find_missing_links_in_topology(topology_data["links"], defined_links)

    for defined_link in defined_links:
        if defined_link not in unique_connections and (defined_link[2], defined_link[3], defined_link[0], defined_link[1]) not in unique_connections:
            src_device, src_ifname, tgt_device, tgt_ifname = defined_link
            if src_device in device_nodes and tgt_device in device_nodes:
                link = {
                    "id": link_id,
                    "source": device_nodes[src_device],
                    "srcDevice": src_device,
                    "srcIfName": src_ifname,
                    "target": device_nodes[tgt_device],
                    "tgtDevice": tgt_device,
                    "tgtIfName": tgt_ifname,
                    "is_missing": "yes"
                }
                topology_data["links"].append(link)
                link_id += 1

    for link in topology_data["links"]:
        unique_nodes.add(link["srcDevice"])
        unique_nodes.add(link["tgtDevice"])

    topology_data["nodes"] = [node for node in topology_data["nodes"] if node["name"] in unique_nodes]
    topology_data["links"] = [link for link in topology_data["links"] if (link["tgtDevice"], link["tgtIfName"], link["srcDevice"], link["srcIfName"]) not in duplicate_connections]

    topology_data["nodes"] = sorted(topology_data["nodes"], key=lambda x: x["name"])
    id_map = {node["id"]: new_id for new_id, node in enumerate(topology_data["nodes"])}

    for node in topology_data["nodes"]:
        node["id"] = id_map[node["id"]]

    for link in topology_data["links"]:
        link["source"] = id_map[link["source"]]
        if link["target"] is not None:
            link["target"] = id_map[link["target"]]

    with open(output_filename, "w") as file:
        file.write("var topologyData = ")
        json.dump(topology_data, file, indent=4)
        file.write(";")

lldp_results_directory = "lldp-results"
assets_file_path = "assets.ini"
dot_file_path = "topology.dot"
output_file = "/var/www/html/topology/topology.js"
generate_topology_file(output_file, lldp_results_directory, assets_file_path, dot_file_path)
