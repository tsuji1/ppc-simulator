import os
import subprocess
import copy
import concurrent.futures
import json
import time
import logging
from datetime import datetime
from models.MultiLayerCacheExclusive import MultiLayerCacheExclusive,AnalysisResults
from mpl_toolkits.mplot3d import Axes3D
import matplotlib.pyplot as plt

import heapq
import numpy as np
#
def _make_join(refbits,cache_capacity):
    refbits_string = "-".join([str(i) for i in refbits])
    cache_capacity_string = "-".join([str(i) for i in cache_capacity])
    return f"{refbits_string}_{cache_capacity_string}"
def make_tmp_file_path(base_dir, refbits, cache_capacity):
    joined = _make_join(refbits,cache_capacity)
    p = os.path.join(base_dir , f'tmp_{joined}.json')
    return p


def aggregate_result():
    
    json_result_data = []
    parsed_result_data = [] 

    dst_file_path = f'../result/multilayer_3layer_256-256-256.json'

    with open(dst_file_path,'r') as file:
        json_result_data = json.load(file)

    return json_result_data


first = 1
last = 32
j = aggregate_result()


analy = AnalysisResults(j)
analy.hitrate_3dplot_3layer(type="heatmap")

