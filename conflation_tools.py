# -*- coding: utf-8 -*-
"""
Created on Thu Nov  4 14:56:07 2021

@author: tpassmore6 and ziyi
"""

#%%
import os
import geopandas as gpd
import pandas as pd
import numpy as np
from shapely import wkt
from shapely.wkt import dumps
from itertools import compress
from shapely.ops import LineString, Point, MultiPoint
from pathlib import Path

#network routing to find connections between networks
import networkx as nx
from tqdm import tqdm

from helper_functions import ckdnearest

def rename_geo(gdf:gpd.GeoDataFrame,name:str,type:str):
    '''
    For distinguishing geometry columns by network. Needed for some of the functions in this
    module.
    '''
    if type == 'links':
        gdf = gdf.rename(columns={'geometry':f'{name}_line_geo'}).set_geometry(f'{name}_line_geo')
    elif type == 'nodes':
        gdf = gdf.rename(columns={'geometry':f'{name}_point_geo'}).set_geometry(f'{name}_point_geo')
    else:
        raise Exception('Enter "links" or "nodes" for name')
    return gdf

def unname_geo(gdf:gpd.GeoDataFrame,name:str,type:str):
    '''
    For removing the geometry name columns from the rename_geo function
    '''
    if type == 'links':
        gdf = gdf.rename(columns={f'{name}_line_geo':'geometry'}).set_geometry('geometry')
    elif type == 'nodes':
        gdf = gdf.rename(columns={f'{name}_point_geo':'geometry'}).set_geometry('geometry')
    else:
        raise Exception('Enter "links" or "nodes" for name')
    return gdf

def initialize_base(base_links:gpd.GeoDataFrame,base_nodes:gpd.GeoDataFrame,join_name:str):
    '''
    Adds empty columns to the base links and nodes to be populated with IDs from the join network.
    '''
    #links
    base_links[f'{join_name}_A'] = None
    base_links[f'{join_name}_B'] = None
    base_links[f'{join_name}_A_B'] = None
    #nodes
    base_nodes[f'{join_name}_N'] = None
    return base_links, base_nodes

def match_nodes(base_nodes:gpd.GeoDataFrame, base_name:str, join_nodes:gpd.GeoDataFrame, join_name:str, tolerance_ft:float, remove_duplicates = True, export_error_lines = False, export_unmatched = False):
    '''
    Node Matching
    This function matches nodes within a set tolerence (in CRS units) that are likely to be the same nodes.
    This function is intended for matching road intersections or road termini since these are likely to be
    in both networks. This function can be applied with an iteratively increasing tolerance if you're not
    sure what's a good tolerance. At some point, the number of matched nodes will not increase by much.

    The match results will get printed out.

    NOTE: This function handles duplicate matches (i.e. when two or more nodes share a nearest node in the
    other network) by selecting the one with the shorter match distance. The duplicates won't be rematched
    unless you run the matching process again.

    When looping match function, feed outputs from previous like:
    first match the nodes, can repeat this by adding in previously matched_nodes
    tolerance_ft = 25
    base_nodes = match_nodes(base_nodes,base_name,join_nodes,join_name,tolerance_ft)

    #second iteration example with same tolerance
    base_nodes = match_nodes(base_nodes,base_name,join_nodes,join_name,tolerance_ft)

    #third iteration example with larger tolerance
    tolerance_ft = 30
    base_nodes = match_nodes(base_nodes,base_name,join_nodes,join_name,tolerance_ft)

    Function Inputs
    - base_nodes, base_name, join_nodes, join_name # self explanatory
    - tolerance_ft: the match tolerance in units of feet
    - prev_matched_nodes: geodataframe of the list of currently matched nodes, set to none for first run
    - remove_duplicates: if set to 'True' (default), then remove duplicate matches. If set to false, duplicate
    matches will be returned in the matched_nodes gdf.
    - export_error_lines: if set to 'False', a geojson of linestrings visualizing the matches will be written.
    - export_unmatched: if you want a geojson of the nodes that didn't match in each network set this to true
    (False by default).

    Function Outputs
    - matched_nodes: a df of matched nodes, just the node ids.
    - unmatched_base_nodes: a gdf of the base nodes that weren't matched.
    - unmatched_join_nodes: a gdf of the join nodes that weren't matched. 
    '''
    #check for nodes that have already been matched and remove them from being matched
    #does for both join and base network
    check_prev_matches = base_nodes[f'{join_name}_N'].isnull()
    base_matching = base_nodes[check_prev_matches]
    check_prev_matches = join_nodes[f'{join_name}_N'].isin(base_nodes[f'{join_name}_N'])
    join_matching = join_nodes[-check_prev_matches]
    
    #drop join id from base
    base_matching = base_matching.drop(columns=[f'{join_name}_N'])
    
    #append new to join node id name
    join_matching.rename(columns={f'{join_name}_N':f'{join_name}_N_new'},inplace=True)
    
    #print current number of matches
    if check_prev_matches.sum() > 0:
        print(f'{check_prev_matches.sum()} previous matches detected.')
    
    #from each base node, find the nearest join node
    closest_nodes = ckdnearest(base_matching,join_matching)

    #filter out matched nodes where the match is greater than specified amount aka tolerence, 25ft seemed okay    
    matched_nodes = closest_nodes[closest_nodes['dist'] <= tolerance_ft]

    #if there are one to many matches, then remove_duplicates == True will only keep the match with the smallest match distance
    #set to false if you want to deal with these one to many joins manually
    if remove_duplicates == True:    
        
        #find duplicate matches
        duplicate_matches = matched_nodes[matched_nodes[f'{join_name}_N_new'].duplicated(keep=False)]
        
        #if two or base nodes match to the same join nodes, then only match the one with the smaller distance
        duplicate_matches_removed = matched_nodes.groupby([f'{join_name}_N_new'], sort=False)['dist'].min()
    
        #used df_2 id to join back to matched nodes
        matched_nodes = pd.merge(matched_nodes, duplicate_matches_removed, how = 'inner', 
                                 on=[f'{join_name}_N_new','dist'], suffixes=(None,'_dup'))
        
    else:
        #mark which ones have been duplicated
        duplicate_matches = matched_nodes[matched_nodes[f'{join_name}_N_new'].duplicated(keep=False)]
        print(f'There are {len(duplicate_matches)} duplicate matches.')

    #if this is set to true, it will export a geojson of lines between the matched nodes
    #can be useful for visualizing the matching process
    if export_error_lines == True:
        #make the lines
        error_lines_geo = matched_nodes.apply(
            lambda row: LineString([row[f'{base_name}_point_geo'], row[f'{join_name}_point_geo']]), axis=1)
        #create geodataframe
        error_lines = gpd.GeoDataFrame({f"{base_name}_N":matched_nodes[f"{base_name}_N"],
                                        f"{join_name}_N":matched_nodes[f"{join_name}_N"],
                                        "geometry":error_lines_geo}, geometry = "geometry")
        #export it to file
        error_lines.to_file(
            rf'processed_shapefiles/conflation/node_matching/{base_name}_to_{join_name}_{tolerance_ft}ft.gpkg', layer='errorlines', driver = 'GPKG')
    
    #filter matched nodes
    matched_nodes = matched_nodes[[f'{base_name}_N',f'{join_name}_N_new']]
    
    #resolve with base nodes
    base_nodes = pd.merge(base_nodes, matched_nodes, on=f'{base_name}_N', how = 'left')
    
    #if there is no existing join node id AND there is a matched node id then replace the None with the node id
    cond = -(base_nodes[f'{join_name}_N'].isnull() & -(base_nodes[f'{join_name}_N_new'].isnull()))
    base_nodes[f'{join_name}_N'] = base_nodes[f'{join_name}_N'].where(cond,base_nodes[f'{join_name}_N_new'])
    
    #drop new node id columns
    base_nodes.drop(columns=[f'{join_name}_N_new'],inplace=True)

    #find unmatched base nodes
    unmatched_base_nodes = base_nodes[base_nodes[f'{join_name}_N'].isnull()]
    
    #find unmatched join nodes
    unmatched_join_nodes = join_nodes[-join_nodes[f'{join_name}_N'].isin(base_nodes[f'{join_name}_N'])]
    
    if export_unmatched == True:
        #export
        unmatched_base_nodes.to_file(rf'processed_shapefiles/conflation/node_matching/{base_name}_to_{join_name}_{tolerance_ft}ft.gpkg', layer='unmatched_base_nodes', driver = 'GPKG')
        unmatched_join_nodes.to_file(rf'processed_shapefiles/conflation/node_matching/{base_name}_to_{join_name}_{tolerance_ft}ft.gpkg', layer='unmatched_join_nodes', driver = 'GPKG')

    #get number of matched nodes
    num_matches = (-(base_nodes[f'{join_name}_N'].isnull())).sum()
    
    print(f'There are {len(unmatched_base_nodes)} {base_name} nodes and {len(unmatched_join_nodes)} {join_name} nodes remaining')
    print(f'{num_matches - check_prev_matches.sum()} new matches')
    print(f'{num_matches} node pairs have been matched so far.')
    
    return base_nodes

def split_lines_create_points(join_nodes:gpd.GeoDataFrame, join_name:str, base_links:gpd.GeoDataFrame, base_name:str, tolerance_ft:float):
    '''
    This function takes a set of nodes (join_nodes) and uses them to split a set of links (base_links) into
    2 or more segments if they are within the tolerance_ft.

    NOTE: This may create way more new nodes/links than needed. Be sure to filter out nodes that you don't
    want to use for splitting beforehand (like nodes that connect two links or dead ends).

    It interpolates the closest point on a line from source line. Then it converts the line geometry from
    shapely objects to well-known text (WKT). THe interpolated point is inserted and the line is turned into
    a shapely MultiLineString. These MultiLineStrings are then broken up.

    This function can be looped, if unsure what tolerance to use.

    Make sure to any filtering beforehand if there are certain links that shouldn't be split or nodes that
    shouldn't be used for splitting.

    Function Inputs:
    -join_nodes: gdf of nodes you want to use to split
    -join_name: name of the join network
    -base_links: links that you want to split
    -base_name: name of the base network
    -tolerance_ft: distance threshold for splitting (join nodes within this distance of a base link will be
    use to split)

    Function Outputs:
    -split_lines: the new splitted base links
    -split_points: the nodes on the base network that were used to split the base links
    -unmatched_join_nodes: the join nodes that were not used to split the base links
    
    Also, for adding the new split links and nodes used to split the links be sure to run add_new_links_nodes
    afterwards.
    '''
    base_links = rename_geo(base_links,base_name,'links')
    join_nodes = rename_geo(join_nodes,join_name,'nodes')

    #get CRS information
    desired_crs = base_links.crs
    
    #note that these function use WKT to do the splitting rather than shapely geometry
    split_points, line_to_split, unmatched_join_nodes = point_on_line(join_nodes, join_name, base_links, base_name, tolerance_ft) #finds the split points
    print(f"{len(split_points.index)} {join_name} points matching to {len(line_to_split[f'{base_name}_A_B'].unique())} {base_name} links")
    #print(f'There are {len(unmatched_join_nodes)} {join_name} nodes remaining')
    
    #splits the lines by nodes found in previous function
    split_lines = split_by_nodes(line_to_split, split_points, base_name) 
    print(f'{len(split_lines)} new lines created.')
    
    #drop the wkt columns and A_B column for points
    split_points.drop(columns=[f'{base_name}_split_point_wkt',f'{base_name}_A_B'], inplace=True)
    split_lines.drop(columns=[f'{base_name}_wkt'], inplace=True)
    
    #project gdfs
    split_points.set_crs(desired_crs, inplace=True)
    split_lines.set_crs(desired_crs, inplace=True)

    #undo renaming
    split_lines = unname_geo(split_lines,base_name,'links')
    split_points = unname_geo(split_points,join_name+'_split','nodes')
    unmatched_join_nodes = unname_geo(unmatched_join_nodes,join_name,'nodes')

    return split_lines, split_points, unmatched_join_nodes

def point_on_line(unmatched_join_nodes, join_name, base_links, base_name, tolerance_ft):
    '''
    Supporting function for split_lines_create_points. It interpolates the nearest point on
    each base link from every join node.
    '''
    split_points = pd.DataFrame() # dataframe for storing the corresponding interpolated point information 
    line_to_split = pd.DataFrame() # dataframe for storing the correspoding base link information
    
    # loop through every unmatched point, as long as the point lies on one link of the whole newtork, it would be identified as lying on the base network
    for index, row in unmatched_join_nodes.iterrows():
        # check if row in unmatched_join_nodes distance to all linestrings in base_links
        on_bool_list = base_links[f"{base_name}_line_geo"].distance(row[f"{join_name}_point_geo"]) < tolerance_ft 
        
        if any(on_bool_list) == True: # if this row matches to base_links feature within the tolerance
            line_Nx = list(compress(range(len(on_bool_list)), on_bool_list)) # find the corresponding line
            print(line_Nx[0])
            target_line = base_links.loc[line_Nx[0],f"{base_name}_line_geo"]
            interpolated_point = target_line.interpolate(target_line.project(row[f"{join_name}_point_geo"])) # find the interpolated point on the line
            unmatched_join_nodes.at[index, f"{base_name}_lie_on"] = "Y"
            split_points.at[index, f"{base_name}_split_point_wkt"] = str(Point(interpolated_point)).strip() 
            line_to_split.at[index, f"{base_name}_split_line_wkt"] = str(LineString(target_line)).strip()
            split_points.at[index, f"{join_name}_N"] = row[f"{join_name}_N"]
            split_points.at[index, f"{base_name}_A_B"] = base_links.loc[line_Nx[0], f"{base_name}_A_B"]
            line_to_split.at[index, f"{join_name}_N"] = row[f"{join_name}_N"]
            line_to_split.at[index, f"{base_name}_A_B"] = base_links.loc[line_Nx[0], f"{base_name}_A_B"]
        else:
            unmatched_join_nodes.at[index, f"{base_name}_lie_on"] = "N"

    #update the unmatced nodes
    unmatched_join_nodes = unmatched_join_nodes[unmatched_join_nodes[f"{base_name}_lie_on"] == "N"].reset_index(drop = True)
    unmatched_join_nodes.drop(columns=[f"{base_name}_lie_on"], inplace = True)
    
    #convert everything to a geodataframe but keep wkt column
    split_points = split_points.reset_index(drop = True)
    split_points[f"{base_name}_split_point_geo"] = split_points[f"{base_name}_split_point_wkt"].apply(wkt.loads) # transform from df to gdf
    split_points = gpd.GeoDataFrame(split_points,geometry=f"{base_name}_split_point_geo")

    line_to_split = line_to_split.reset_index(drop = True)
    line_to_split[f"{base_name}_split_line_geo"] = line_to_split[f"{base_name}_split_line_wkt"].apply(wkt.loads)
    line_to_split = gpd.GeoDataFrame(line_to_split,geometry=f"{base_name}_split_line_geo")
    
    return split_points, line_to_split, unmatched_join_nodes

def get_linesegments(point, line):
     '''
     Supporting function for split_lines_create_points. It splits the line into a MultiLineString.
     '''
     return line.difference(point.buffer(1e-6)) #IMPORTANT: add a buffer here make sure it works

def split_by_nodes(line_to_split, split_points, base_name):
    '''
    Supporting function for split_lines_create_points.
    '''
    
    ab_list = split_points[f"{base_name}_A_B"].unique().tolist()
    line_to_split = line_to_split.drop_duplicates(subset = [f"{base_name}_A_B"]) # multiple points could line on the same link, drop duplicates first
    df_split = pd.DataFrame(columns = {f"{base_name}_A_B",f"{base_name}_wkt"}) # dataframe for storing splitted multistring
    df_split[f"{base_name}_A_B"] = ab_list
    
    for idx, row in df_split.iterrows():
        ab = row[f"{base_name}_A_B"]
        df_ab = split_points[split_points[f"{base_name}_A_B"] == ab]
        ab_point = MultiPoint([x for x in df_ab[f"{base_name}_split_point_geo"]])
        ab_line = line_to_split[line_to_split[f"{base_name}_A_B"] == ab][f"{base_name}_split_line_geo"].values[0]
        split_line = get_linesegments(ab_point, ab_line) # split_line is a geo multilinestring type
        # ATTENTION: format the decimal places to make every row the same, this is important for successfully turning string to geopandas geometry
        # use dump to always get 16 decimal digits irregardles of the total number of digits, dump() change it to MultiLineString to string type
        split_line = dumps(split_line) 
        df_split.at[idx, f"{base_name}_wkt"] = split_line
    
    df_split[f'{base_name}_line_geo'] = df_split[f"{base_name}_wkt"].apply(wkt.loads)
    df_split = gpd.GeoDataFrame(df_split,geometry=f'{base_name}_line_geo')
    
    #convert from multilinestring to segments
    df_split = df_split.explode(index_parts=False).reset_index(drop=True)
    
    return df_split

def add_split_links(base_links, new_links, base_name):
    '''
    Take the split_lines output from the split_lines_create_points function and replaces the link that has
    been splitted.
    '''
    #remove links that were splitted
    mask = -base_links[f'{base_name}_A_B'].isin(new_links[f'{base_name}_A_B'])
    base_links = base_links[mask]
    
    #add new links
    base_links = pd.concat([base_links,new_links],ignore_index=True)
     
    return base_links

def add_rest_of_features(base_links,base_nodes,base_name,join_links,join_nodes,join_name):
    
    #find the nodes that are not present
    unadded_nodes = join_nodes[-join_nodes[f'{join_name}_N'].isin(base_nodes[f'{join_name}_N'])]
     
    #add them
    base_nodes = base_nodes.append(unadded_nodes)
    
    #find the links that are not present
    unadded_links = join_links[-join_links[f'{join_name}_A_B'].isin(base_links[f'{join_name}_A_B'])]
    
    #add them
    base_links = base_links.append(unadded_links)
    
    #merge the geometry columns into one called bikewaysim
    base_links[f'{base_name}_line_geo'] = base_links.apply(
           lambda row: row[f'{join_name}_line_geo'] if row[f'{base_name}_line_geo'] is None else row[f'{base_name}_line_geo'], axis = 1)
    
    base_nodes[f'{base_name}_point_geo'] = base_nodes.apply(
           lambda row: row[f'{join_name}_point_geo'] if row[f'{base_name}_point_geo'] is None else row[f'{base_name}_point_geo'], axis = 1)
    
    #drop the excess geo column, make sure base is set to active geometry
    base_links = base_links.drop(columns=[f'{join_name}_line_geo','original_length']).set_geometry(f'{base_name}_line_geo')
    base_nodes = base_nodes.drop(columns=[f'{join_name}_point_geo']).set_geometry(f'{base_name}_point_geo')
    
    return base_links, base_nodes
 
def find_path(project_dir,network_name,road_nodes,dead_ends,cutoff_ft):
    '''
    When re-joining sub-networks, there may be sections that are disconnected
    through the filtering process. This function imports the raw network to find
    paths between dead end links of the bike network and the road network link

    A cutoff distance is applied to speed up the shortest path search and also
    ensure that only short gaps in the network are allowed.
    '''
    #import the raw osm file
    raw_links = gpd.read_file(project_dir/'filtered.gpkg',layer=f'{network_name}_links_raw')
    raw_links['length_ft'] = raw_links.length

    raw_nodes = gpd.read_file(project_dir/"filtered.gpkg",layer=f'{network_name}_nodes_raw')
    raw_nodes.index = raw_nodes[f'{network_name}_N']

    #make an undirected graph
    G = nx.Graph()
    for row in raw_links[[f'{network_name}_A',f'{network_name}_B','length_ft']].itertuples(index=False):
        G.add_weighted_edges_from([(row[0], row[1], row[2])],weight='weight')

    #new connecting links
    new_links = []
    road_nodes_set = set(road_nodes[f'{network_name}_N'].tolist())

    #loop that goes through each dead end and finds all road points that are within network distance (start with 500 ft)
    for dead_end in tqdm(dead_ends[f'{network_name}_N'].tolist()):
        path_lengths = nx.single_source_dijkstra_path_length(G,dead_end,cutoff=cutoff_ft,weight='weight')
        #subset to only inlcude road nodes
        path_lengths = {k:v for k,v in path_lengths.items() if k in road_nodes_set}
        
        if len(path_lengths) > 1:  
            #find min and take first road node
            closest_road_node = [k for k,v in path_lengths.items() if v == min(path_lengths.values())][0]
            #add to new_links
            new_links.append((dead_end,closest_road_node))
        
    df = pd.DataFrame(new_links,columns=[f'{network_name}_A',f'{network_name}_B'])
    df[f'{network_name}_A_B'] = df[f'{network_name}_A'].astype(str) + '_' + df[f'{network_name}_B'].astype(str)
    df['geo_A'] = df[f'{network_name}_A'].map(raw_nodes['geometry'])
    df['geo_B'] = df[f'{network_name}_B'].map(raw_nodes['geometry'])
    df['geometry'] = df.apply(lambda row: LineString([row['geo_A'],row['geo_B']]),axis=1)
    df.drop(columns=['geo_A','geo_B'],inplace=True)
    df = gpd.GeoDataFrame(df,geometry='geometry',crs=road_nodes.crs)
    return df

#function for creating match links



# DEPRECATED CODE

# def merge_diff_networks(base_links, base_nodes, base_type, join_links, join_nodes, join_type, tolerance_ft):
    
#     #notes
#     #merging network could have the same nodes
#     #don't mess with ref id till end
#     #need to consider how many ids there will be
    
#     #first find nodes that are already present and don't add them
    
#     #get network names for each network
#     base_cols = list(base_nodes.columns)
#     base_Ns = [base_cols for base_cols in base_cols if "_N" in base_cols]
    
#     join_cols = list(join_nodes.columns)
#     join_Ns = [join_cols for join_cols in join_cols if "_N" in join_cols]
    
#     #get list of common names between networks
#     common_Ns = [base_Ns for base_Ns in base_Ns if base_Ns in join_Ns]
    
#     #remove join_nodes that are in base_nodes
#     initial_nodes = len(join_nodes)
    
#     for name in common_Ns:
#         join_nodes = join_nodes[-join_nodes[name].isin(base_nodes[name])]
    
#     final_nodes = len(join_nodes)
#     print(f'{initial_nodes - final_nodes} nodes already in the base network')
    
#     #add rest of join nodes to base nodes
#     base_nodes = base_nodes.append(join_nodes)
    
#     #get geo names
#     base_line_geo = base_links.geometry.name
#     base_point_geo = base_nodes.geometry.name
#     join_line_geo = join_links.geometry.name
#     join_point_geo = join_nodes.geometry.name
    
#     #call the match nodes function to form connections between nodes
#     base_nodes_to_match = base_nodes.add_suffix(f'_{base_type}').set_geometry(f'{base_point_geo}_{base_type}')
#     join_nodes_to_match = join_nodes.add_suffix(f'_{join_type}').set_geometry(f'{join_point_geo}_{join_type}')
    
#     print(base_nodes_to_match.geometry.isnull().any())
#     print(join_nodes_to_match.isnull().any())
    
#     #this isn't working
#     #connections = ckdnearest(base_nodes_to_match,join_nodes_to_match)
#     #connections = connections[connections['dist'] <= tolerance_ft]

#     #only keep connections if there is not already a connection in respective column
#     #for name in common_Ns:
#        # rem_cond = connections[f'{name}_{base_type}'] == connections[f'{name}_{join_type}']
#        # connections = connections[-rem_cond]
     
#     #add all the links
#     base_links = base_links.append(join_links)
    
#     #merge the geometry columns into one
#     base_links[base_links.geometry.name] = base_links.apply(
#            lambda row: row[join_links.geometry.name] if row[base_links.geometry.name] is None else row[base_links.geometry.name], axis = 1)
    
#     base_nodes[base_nodes.geometry.name] = base_nodes.apply(
#            lambda row: row[join_nodes.geometry.name] if row[base_nodes.geometry.name] is None else row[base_nodes.geometry.name], axis = 1)
    
#     #drop the excess geo column, make sure base is set to active geometry
#     base_links = base_links.drop(columns=[join_line_geo]).set_geometry(base_line_geo)
#     base_nodes = base_nodes.drop(columns=[join_point_geo]).set_geometry(base_point_geo)

#     return base_links, base_nodes#, connections
   
# def add_reference_Ns(links, nodes):

#     #get network names
#     cols = list(nodes.columns)
#     id_cols = [cols for cols in cols if "_N" in cols]
#     names = [id_cols.split('_')[0] for id_cols in id_cols]
    
#     #filter nodes
#     id_cols.append(nodes.geometry.name)
#     nodes = nodes[id_cols]
    
#     #get name of geo column
#     links_geo = links.geometry.name
    
#     #match id to starting node
#     links['start_point_geo'] = links.apply(start_node_geo, geom= links.geometry.name, axis=1)
        
#     #set to active geo
#     links = links.set_geometry('start_point_geo')
        
#     #find nearest node from starting node
#     links = ckdnearest(links,nodes,return_dist=False)
        
#     #rename id columns to _A
#     links.columns = pd.Series(list(links.columns)).str.replace('_N','_A')

#     #remove start node and base_node_geo columns
#     links = links.drop(columns=['start_point_geo',nodes.geometry.name])
        
#     #reset geometry
#     links = links.set_geometry(links_geo)
     
        
#     #do same for end point
#     links['end_point_geo'] = links.apply(end_node_geo, geom= links.geometry.name, axis=1)
    
#     #set active geo
#     links = links.set_geometry('end_point_geo')
    
#     #find nearest node from starting node
#     links = ckdnearest(links,nodes,return_dist=False)
        
#     #rename id columns to _A
#     links.columns = pd.Series(list(links.columns)).str.replace('_N','_B')
 
#     #remove end point
#     links = links.drop(columns=['end_point_geo',nodes.geometry.name])
 
#     #reset geometry   
#     links = links.set_geometry(links_geo)

#     #check for missing ref ids
#     cols = list(links.columns)
#     a_cols = [cols for cols in cols if "_A" in cols]
#     b_cols = [cols for cols in cols if "_B" in cols]
    
#     #first see any As are missing
#     a_missing = links[a_cols].apply(lambda row: row.isnull().all(), axis = 1)
    
#     #then see if any Bs are missing
#     b_missing = links[b_cols].apply(lambda row: row.isnull().all(), axis = 1)
    
#     if a_missing.any() == True | b_missing.any() == True:
#         print("There are missing reference ids")
            
#     return links

# def fin_subnetwork(final_links,final_nodes,base_name,join_name):
#     comb = base_name + join_name
    
#     final_links.rename(columns={f'{base_name}_line_geo':f'{comb}_line_geo'},inplace=True)
#     final_links.set_geometry(f'{comb}_line_geo',inplace=True)
#     final_links[f'{comb}_A_B'] = np.nan
#     final_links[f'{comb}_A_B'] = final_links[f'{comb}_A_B'].fillna(final_links[f'{base_name}_A_B'])
#     final_links[f'{comb}_A_B'] = final_links[f'{comb}_A_B'].fillna(final_links[f'{join_name}_A_B'])
    
#     final_nodes.rename(columns={f'{base_name}_point_geo':f'{comb}_point_geo'},inplace=True)
#     final_nodes.set_geometry(f'{comb}_point_geo',inplace=True)
#     final_nodes[f'{comb}_N'] = np.nan
#     final_nodes[f'{comb}_N'] = final_nodes[f'{comb}_N'].fillna(final_nodes[f'{base_name}_N'])
#     final_nodes[f'{comb}_N'] = final_nodes[f'{comb}_N'].fillna(final_nodes[f'{join_name}_N'])
    
#     final_links = final_links.reset_index(drop=True)
#     final_nodes = final_nodes.reset_index(drop=True)
    
#     return final_links, final_nodes

# def add_attributes(base_links, base_name, join_links, join_name, buffer_ft):
     
#     #give base_links a temp column so each row has unique identifyer
#     base_links['temp_N'] = np.arange(base_links.shape[0]).astype(str)
    
#     #buffer base links by 30 ft (or whatever the projected coord unit is)
#     base_links['buffer_geo'] = base_links.buffer(buffer_ft)
#     base_links = base_links.set_geometry('buffer_geo')
    
#     #export buffer for examination
#     base_links.drop(columns={f'{base_name}_line_geo'}).to_file(rf'Processed_Shapefiles/conflation/add_attributes/{base_name}_buffer.geojson', driver = 'GeoJSON')
    
#     #calculate initial length of join links
#     join_links['original_length'] = join_links.length
    
#     #perform overlay with join links
#     overlapping_links = gpd.overlay(join_links, base_links, how='intersection')
    
#     #overlap length
#     overlapping_links['overlap_length'] = overlapping_links.length 
    
    
#     #for each base link find join link with greatest length overlap
#     overlapping_links = overlapping_links.loc[overlapping_links.groupby('temp_N')['overlap_length'].idxmax()]
    
#     #merge the join_A_B column to base_links by temp ID
#     base_links = pd.merge(base_links, overlapping_links[['temp_N',f'{join_name}_A_B']], on = 'temp_N', how = 'left')
    
#     #clean up base_links
#     base_links.drop(columns=['temp_N','buffer_geo'], inplace = True)
    
#     #reset active geo
#     base_links = base_links.set_geometry(f'{base_name}_line_geo')

#     #export final result
#     base_links.to_file(rf'Processed_Shapefiles/conflation/add_attributes/{base_name}_joined.geojson', driver = 'GeoJSON')

#     return base_links


# #function for importing networks
# def import_network(network_name:str,link_type:str,study_area:str):    
#     '''
#     This function imports networks that were processed 
#     '''
    
#     #expected relative fp
#     fp = Path.home()
    
#     if os.path.exists(fp + 'links.geojson'):
#         links = gpd.read_file(fp + 'links.geojson')
#     else:
#         print(f'{network_name} network links file does not exist')

#     if os.path.exists(fp + 'nodes.geojson'):
#         nodes = gpd.read_file(fp + 'nodes.geojson')
#     else:
#         print(f'{network_name} network nodes file does not exist')
     
#     #calculates the number of connecting links for each node for filtering purposes
#     num_links = links[f'{network_name}_A'].append(links[f'{network_name}_B']).value_counts()
#     num_links.name = 'num_links'
#     nodes = pd.merge(nodes,num_links,left_on=f'{network_name}_N',right_index=True)
 
#     return links, nodes


# def split_lines_create_points(unmatched_join_nodes, join_name, base_links, base_name, tolerance_ft, export = False):
    
#     #get CRS information
#     desired_crs = base_links.crs
    
#     #note that these function use WKT to do the splitting rather than shapely geometry
#     split_points, line_to_split, unmatched_join_nodes = point_on_line(unmatched_join_nodes, join_name, base_links, base_name, tolerance_ft) #finds the split points
#     print(f"There are {len(split_points.index)} {join_name} points matching to {len(line_to_split[f'{base_name}_A_B'].unique())} {base_name} links")
#     print(f'There are {len(unmatched_join_nodes)} {join_name} nodes remaining')
    
#     #splits the lines by nodes found in previous function
#     split_lines = split_by_nodes(line_to_split, split_points, base_name) 
#     print(f'There were {len(split_lines)} new lines created.')
    
#     #drop the wkt columns and A_B column for points
#     split_points.drop(columns=[f'{base_name}_split_point_wkt',f'{base_name}_A_B'], inplace=True)
#     split_lines.drop(columns=[f'{base_name}_wkt'], inplace=True)
    
#     #project gdfs
#     split_points.set_crs(desired_crs, inplace=True)
#     split_lines.set_crs(desired_crs, inplace=True)

#     if export == True:
#         #write these to file
#         split_lines.to_file("processed_shapefiles/conflation/line_splitting/split_lines.geojson", driver = "GeoJSON")
#         split_points.to_file("processed_shapefiles/conflation/line_splitting/split_points.geojson", driver = "GeoJSON")

#     return split_lines, split_points, unmatched_join_nodes


# def add_new_links_nodes(base_links, base_nodes, new_links, new_nodes, base_name):
#     '''
#     Use this function with the split_lines_create_points function outputs to add the new
#     split links and nodes to the base network links and nodes.
#     '''
#     #remove links that were splitted
#     mask = -base_links[f'{base_name}_A_B'].isin(new_links[f'{base_name}_A_B'])
#     base_links = base_links[mask]
    
#     #add new links
#     base_links = base_links.append(new_links)
     
#     #rename geo col
#     new_nodes = new_nodes.rename(columns={f'{base_name}_split_point_geo':f'{base_name}_point_geo'}).set_geometry(f'{base_name}_point_geo')
    
#     #add split nodes to nodes with the here match
#     base_nodes = base_nodes.append(new_nodes)
    
#     return base_links, base_nodes