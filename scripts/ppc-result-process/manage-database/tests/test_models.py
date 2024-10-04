import pytest
from app.db import SessionLocal, init_db,TestingSession
from app.crud import save_cache_data_to_db
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.session import close_all_sessions
from app.models.cache_models import MultiLayerCacheExclusive
from app.models import CacheStats, StatDetail, Referred, Replaced, Hit, MatchMap, LongestMatchMap
from sqlalchemy.orm import Session
import json
from app.db import delete_db
@pytest.fixture
def db():
    # テスト用セッションの作成
    delete_db()
    init_db()
    db = SessionLocal()

   # ネストされたトランザクションを開始
    transaction = db.begin_nested()

    yield db  # テスト実行時、ここでセッションが使われる

    # テスト終了後にトランザクションをロールバックしてデータをリセット
    transaction.rollback()
    db.close()
    
def test_save_cache_data_to_db(db: Session):
    
    dst_file_path = 'test_data.json'

    with open(dst_file_path,'r') as file:
        json_result_data = json.load(file)
        

    cache = MultiLayerCacheExclusive(json_result_data)

    # データを保存
    save_cache_data_to_db(db, cache)
    
    # フラッシュしてデータベースに反映
    db.flush()
    # db.commit() これはデータを追加する

    # データが正しく保存されたか確認する
    cache_stats = db.query(CacheStats).filter_by(type='TestCache').first()
    assert cache_stats is not None
    assert cache_stats.processed == cache.Processed
    assert cache_stats.hit == cache.Hit
    assert float(cache_stats.hit_rate) == cache.HitRate
    

    # # StatDetail が保存されたか確認する
    stat_detail = db.query(StatDetail).filter_by(cache_stat_id=cache_stats.id).first()
    assert stat_detail is not None
    assert stat_detail.depth_sum == cache.StatDetail.DepthSum
    assert stat_detail.cache_stat_id == cache_stats.id
    
    
    cacheLen = len(cache.Parameter.CacheLayers.CacheLayers)
    # Referred のリストデータが保存されたか確認
    referred = db.query(Referred).filter_by(stat_detail_id=stat_detail.id).all()
    assert len(referred) == cacheLen
    assert referred[0].stat_detail_id == stat_detail.id
    for i, refered in enumerate(cache.StatDetail.Refered):
        assert referred[i].referred == refered

    # Replaced のリストデータが保存されたか確認
    replaced = db.query(Replaced).filter_by(stat_detail_id=stat_detail.id).all()
    assert len(replaced) == cacheLen
    for i, replaced_data in enumerate(cache.StatDetail.Replaced):
        assert replaced[i].replaced == replaced_data

    # Hit のリストデータが保存されたか確認
    hits = db.query(Hit).filter_by(stat_detail_id=stat_detail.id).all()
    assert len(hits) == cacheLen
    for i, hit_data in enumerate(cache.StatDetail.Hit):
        assert hits[i].hit == hit_data

    # MatchMap のリストデータが保存されたか確認
    match_map = db.query(MatchMap).filter_by(stat_detail_id=stat_detail.id).all()
    assert len(match_map) == 33
    for i, match_data in enumerate(cache.StatDetail.MatchMap):
        assert match_map[i].match_value == match_data

    # LongestMatchMap のリストデータが保存されたか確認
    longest_match_map = db.query(LongestMatchMap).filter_by(stat_detail_id=stat_detail.id).all()
    assert len(longest_match_map) == 33
    for i, longest_match_data in enumerate(cache.StatDetail.LongestMatchMap):
        assert longest_match_map[i].longest_match_value == longest_match_data

