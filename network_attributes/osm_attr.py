# -*- coding: utf-8 -*-
"""
Created on Mon Jul 25 21:19:26 2022

@author: tpassmore6
"""
import geopandas as gpd
import pandas as pd
import numpy as np
import os
from pathlib import Path

#settings
studyarea_name = 'bikewaysim'
fp = Path.home() / Path(f'Documents/NewBikewaySim/{studyarea_name}')

#import network
links = gpd.read_file(fp / Path('reconciled_network.gpkg'),layer='osm_roadbike_links')
nodes = gpd.read_file(fp / Path('filtered_network.gpkg'),layer='osm_roadbike_links')

#bring in attribute data
attr = pd.read_pickle(fp / Path('osm.pkl'))

#attach attribute data to filtered links
links = pd.merge(links,attr,on='osm_A_B')


#%% speed limit

#change nones to NaN
links['maxspeed'] = pd.to_numeric(links['maxspeed'],errors='coerce').fillna(links['maxspeed'])

#covert to ints
func = lambda x: int(str.split(x,' ')[0]) if type(x) == str else (np.nan if x == None else int(x))
links['maxspeed'] = links['maxspeed'].apply(func)

#speed categories
bins = [0,25,30,70]
names = ['< 25','25-30','> 30']

#replace
links['maxspeed'] = pd.cut(links['maxspeed'],bins=bins,labels=names)
links['maxspeed'] = links['maxspeed'].astype(str)

#%% number of lanes

#convert none to nan
links['lanes'] = links['lanes'].apply(lambda x: np.nan if x == None else x)

#make sure numeric
links['lanes'] = pd.to_numeric(links['lanes'])

#speed cats
bins = [0,3,6,links.lanes.max()]
names = ['one lane', 'two or three lanes', 'four or more']

#replace
links['lanes'] = pd.cut(links['lanes'],bins=bins,labels=names)
links['lanes'] = links['lanes'].astype(str)

#%% road directionality
links.loc[(links['oneway']=='-1') | (links['oneway'] is None),'oneway'] = 'NA'

#%% bike facilities

#get bike specific columns
bike_columns = [x for x in links.columns.to_list() if (('cycle' in x) | ('bike' in x)) & ('motorcycle' not in x)]
foot_columns = [x for x in links.columns.to_list() if ('foot' in x)]

#add lit
bike_columns = bike_columns + foot_columns + ['lit']

#anything that contains lane is a bike lane
links.loc[(links[bike_columns] == 'lane').any(axis=1),'bikefacil'] = 'bike lane'

#multi use paths or protected bike lanes (i don't think there's a way to tell in OSM)
mups = ['path','footway','pedestrian','cycleway']
links.loc[links['highway'].isin(mups),'bikefacil'] = 'mup or pbl'

#drop excess columns
links.drop(columns=bike_columns,inplace=True)

#%% parking
parking_columns = [x for x in links.columns.to_list() if 'parking' in x]
parking_vals = ['parallel','marked','diagonal','on_street']
links.loc[(links[parking_columns].isin(parking_vals)).any(axis=1),'parking_pres'] = 'yes'
links.loc[(links[parking_columns]=='no').any(axis=1),'parking_pres'] = 'yes'
links.drop(columns=parking_columns,inplace=True)


#%% sidewalk presence
sidewalks = [x for x in links.sidewalk.unique().tolist() if x not in [None,'no','none']]
links['sidewalk_pres'] = 'NA'
links.loc[links['sidewalk'].isin(sidewalks),'sidewalk_pres'] = 'yes'
links.loc[links['sidewalk'].isin([None,'no','none']),'sidewalk_pres'] = 'no'
links.drop(columns=['sidewalk'],inplace=True)

#%% export for conflation
links.to_file(fp / Path('to_conflate.gpkg'),layer='osm_links')
nodes.to_file(fp / Path('to_conflate.gpkg'),layer='osm_nodes')