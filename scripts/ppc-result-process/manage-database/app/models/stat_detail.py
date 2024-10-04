
from sqlalchemy import Column, Integer, BigInteger, Text, DECIMAL,ForeignKey
from sqlalchemy.orm import relationship
from ..db import Base
from .referred import Referred
from .replaced import Replaced
from .hit import Hit
from .match_map import MatchMap
from .longest_match_map import LongestMatchMap
from .inserted import Inserted

class StatDetail(Base):
    __tablename__ = 'stat_detail'
    
    id = Column(Integer, primary_key=True)
    cache_stat_id = Column(Integer, ForeignKey('cache_stats.id'))
    depth_sum = Column(Integer)
    
    cache_stat = relationship("CacheStats", back_populates="stat_details")
    referred = relationship(Referred, back_populates="stat_detail")
    replaced = relationship(Replaced, back_populates="stat_detail")
    hit = relationship(Hit, back_populates="stat_detail")
    match_map = relationship(MatchMap, back_populates="stat_detail")
    longest_match_map = relationship(LongestMatchMap, back_populates="stat_detail")
    inserted = relationship(Inserted, back_populates="stat_detail")
