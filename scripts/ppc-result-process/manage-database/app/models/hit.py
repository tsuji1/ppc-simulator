from sqlalchemy import Column, Integer, BigInteger, Text, DECIMAL,ForeignKey,SmallInteger
from sqlalchemy.orm import relationship
from ..db import Base
class Hit(Base):
    __tablename__ = 'hit'
    
    id = Column(Integer, primary_key=True)
    stat_detail_id = Column(Integer, ForeignKey('stat_detail.id'))
    layer_index = Column(SmallInteger)
    hit = Column(BigInteger)
    
    stat_detail = relationship("StatDetail", back_populates="hit")
