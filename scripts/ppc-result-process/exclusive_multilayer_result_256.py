import os
import json
from models.MultiLayerCacheExclusive import AnalysisResults

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

    dst_file_path = '../result/multilayer_3layer_256-256-256.json'

    with open(dst_file_path,'r') as file:
        json_result_data = json.load(file)

    return json_result_data


first = 1
last = 32
j = aggregate_result()


analy = AnalysisResults(j)
analy.hitrate_3dplot_3layer(type="heatmap")

