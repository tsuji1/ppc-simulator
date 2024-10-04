from sqlalchemy.orm import Session
from .models import CacheStats,StatDetail,Referred,Replaced,Hit,MatchMap,LongestMatchMap,CacheLayer,Parameter,CachePolicy
from .models.cache_models import MultiLayerCacheExclusive
def get_cache_stats(db: Session, stat_id: int):
    return db.query(CacheStats).filter(CacheStats.id == stat_id).first()




def save_cache_data_to_db(session:Session, cache : MultiLayerCacheExclusive):
    
    # CacheStatsエントリを作成
    cache_stat = CacheStats(
        type=cache.Type,
        processed=cache.Processed,
        hit=cache.Hit,
        hit_rate=cache.HitRate
    )
    
    session.add(cache_stat)
    session.flush()    
    # StatDetailエントリを作成
    parameter = Parameter(
        cache_stat_id=cache_stat.id,
        cache_type=cache.Parameter.Type,
        parameter_hash= cache.Parameter.generate_hash(),
    )
    
    session.add(parameter)
    session.flush()
    for i, layer in enumerate(cache.Parameter.CacheLayers.CacheLayers):
        cache_layer = CacheLayer(
            parameter_id=parameter.id,
            layer_index=i,
            type=layer.Type,
            size=layer.Size,
            refbits=layer.Refbits,
           
        )
        session.add(cache_layer)
    
    for i, policy in enumerate(cache.Parameter.CachePolicies):
        cache_policy = CachePolicy(
            parameter_id=parameter.id,
            policy_index=i,
            policy=policy
        )
        session.add(cache_policy)
        
    
    stat_detail = StatDetail(
        cache_stat_id=cache_stat.id,
        depth_sum=cache.StatDetail.DepthSum,
    )    
    session.add(stat_detail)
    session.flush()
    # StatDetail内のリストデータを保存
    for i, refered in enumerate(cache.StatDetail.Refered):
        referred_entry = Referred(stat_detail_id=stat_detail.id, layer_index=i, referred=refered)
        session.add(referred_entry)

    for i, replaced in enumerate(cache.StatDetail.Replaced):
        replaced_entry = Replaced(stat_detail_id=stat_detail.id, layer_index=i, replaced=replaced)
        session.add(replaced_entry)

    for i, hit in enumerate(cache.StatDetail.Hit):
        hit_entry = Hit(stat_detail_id=stat_detail.id, layer_index=i, hit=hit)
        session.add(hit_entry)

    for i, match in enumerate(cache.StatDetail.MatchMap):
        match_map_entry = MatchMap(stat_detail_id=stat_detail.id, layer_index=i, match_value=match)
        session.add(match_map_entry)

    for i, longest_match in enumerate(cache.StatDetail.LongestMatchMap):
        longest_match_map_entry = LongestMatchMap(stat_detail_id=stat_detail.id, layer_index=i, longest_match_value=longest_match)
        session.add(longest_match_map_entry)
