from typing import List, Dict, Literal

MultiLayerCacheExclusiveType =Literal['MultiLayerCacheExclusive']
class MultiLayerCacheExclusive:
    class MultiLayerCacheStatDetail:
        def __init__(self, data: Dict):
            self.Refered:List[int] = data["Refered"]
            self.Replaced:List[int] = data["Replaced"]
            self.Hit:List[int] = data["Hit"]
            self.MatchMap:List[int] = data["MatchMap"]
            self.LongestMatchMap:List[int] = data["LongestMatchMap"]
            self.DepthSum:List[int] = data["DepthSum"]
            self.NotInserted:List[int] = data["NotInserted"]
            

    def __init__(self, data: Dict):
        self.Type = data["Type"]
        self.Parameter = data["Parameter"]
        self.Processed:int = int(data["Processed"])
        self.Hit :int= int(data["Hit"])
        self.HitRate:float =float(data["HitRate"])
        self.StatDetail = self.MultiLayerCacheStatDetail(data["StatDetail"])
        
    
        
    def display(self):
        print("Type:", self.Type)
        print("Processed:", self.Processed)
        print("Hit:", self.Hit)
        print("HitRate:", self.HitRate)

        print("\nParameter Details:")
        for layer in self.Parameter["CacheLayers"]:
            print(f"Cache Layer Type: {layer['Type']}, Size: {layer['Size']}, Refbits: {layer['Refbits']}")

        print("\nCache Policies:", self.Parameter["CachePolicies"])

        print("\nStatDetail:")
        stat_detail = self.StatDetail
        print("Refered:", stat_detail["Refered"])
        print("Replaced:", stat_detail["Replaced"])
        print("Hit:", stat_detail["Hit"])
        print("MatchMap:", stat_detail["MatchMap"])
        print("LongestMatchMap:", stat_detail["LongestMatchMap"])
        print("DepthSum:", stat_detail["DepthSum"])
        print("NotInserted:", stat_detail["NotInserted"])
