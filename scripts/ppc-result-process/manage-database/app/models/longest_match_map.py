from sqlalchemy import Column, Integer, BigInteger, Text, DECIMAL,ForeignKey
from sqlalchemy.orm import relationship
from ..db import Base
class LongestMatchMap(Base):
    __tablename__ = 'longest_match_map'
    
    id = Column(Integer, primary_key=True)
    stat_detail_id = Column(Integer, ForeignKey('stat_detail.id'))
    layer_index = Column(Integer)
    longest_match_value = Column(BigInteger)
    
    stat_detail = relationship("StatDetail", back_populates="longest_match_map")
