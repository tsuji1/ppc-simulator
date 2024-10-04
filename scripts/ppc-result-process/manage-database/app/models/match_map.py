from sqlalchemy import Column, Integer, BigInteger, Text, DECIMAL,ForeignKey,SmallInteger
from sqlalchemy.orm import relationship
from ..db import Base
class MatchMap(Base):
    __tablename__ = 'match_map'
    
    id = Column(Integer, primary_key=True)
    stat_detail_id = Column(Integer, ForeignKey('stat_detail.id'))
    layer_index = Column(SmallInteger)
    match_value = Column(BigInteger)
    
    stat_detail = relationship("StatDetail", back_populates="match_map")
