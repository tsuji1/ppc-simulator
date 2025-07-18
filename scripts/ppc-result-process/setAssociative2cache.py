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


def aggregate_result(dst_file_path = '../../result/result021230da-e4b0-4cea-8847-dff1b92bc6ae.json'):
    
    json_result_data = []
    with open(dst_file_path,'r') as file:
        json_result_data = json.load(file)
    return json_result_data["results"]


j = aggregate_result()


analy = AnalysisResults(j)
# s = aggregate_result("../../result/result600b8b7b-0492-4785-a48c-fe86bd1a8f16.json")
# analy.add_result(s)
analy.find_top_n_hitrate(10)
analy.print_results()
# analy.hitrate_bar_graph_2cache_refbits_fixed_32bitcapacity(capacity_32bit=[64,256,512,1024],refbits_range=list(range(16,24+1)),capacity_range=[2**i for i in range(4,12)])
end = 15
analy.hitrate_bar_graph_2cache_refbits_fixed_32bitcapacity(capacity_32bit=64,refbits_range=list(range(16,24+1)),capacity_range=[2**i for i in range(4,end)])

analy.hitrate_bar_graph_2cache_refbits_fixed_32bitcapacity(capacity_32bit=256,refbits_range=list(range(16,24+1)),capacity_range=[2**i for i in range(4,end)])

analy.hitrate_bar_graph_2cache_refbits_fixed_32bitcapacity(capacity_32bit=512,refbits_range=list(range(16,24+1)),capacity_range=[2**i for i in range(4,end)])

analy.hitrate_bar_graph_2cache_refbits_fixed_32bitcapacity(capacity_32bit=1024,refbits_range=list(range(16,24+1)),capacity_range=[2**i for i in range(4,end)])
# analy.hitrate_2dplot_2layer_refbits_capacity("tes")

# キャパシティが同じで
