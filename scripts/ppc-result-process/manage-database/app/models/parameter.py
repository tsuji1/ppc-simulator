from sqlalchemy import Column, Integer, BigInteger, Text, DECIMAL,ForeignKey,UniqueConstraint
from sqlalchemy.orm import relationship
from ..db import Base
from .cache_layers import CacheLayer
from .cache_policies import CachePolicy
class Parameter(Base):
    __tablename__ = 'parameter'
    
    id = Column(Integer, primary_key=True)
    cache_stat_id = Column(Integer, ForeignKey('cache_stats.id'))
    cache_type = Column(Text)
    parameter_hash = Column(Text)
      
    # ユニーク制約の追加
    __table_args__ = (
        UniqueConstraint('parameter_hash', name='parameter_unique_constraint'),
    )
    
    
    # 関連するテーブルとのリレーションシップ
    cache_layers = relationship(CacheLayer, back_populates="parameter")
    cache_policies = relationship(CachePolicy, back_populates="parameter")
  # CacheStats とのリレーションシップを定義
    cache_stat = relationship("CacheStats", back_populates="parameters")
    