from sqlalchemy import Column, Integer, BigInteger, Text, DECIMAL,ForeignKey,SmallInteger
from sqlalchemy.orm import relationship
from ..db import Base
class Referred(Base):
    __tablename__ = 'referred'
    
    id = Column(Integer, primary_key=True)
    stat_detail_id = Column(Integer, ForeignKey('stat_detail.id'))
    layer_index = Column(SmallInteger)
    referred = Column(BigInteger)
    
    stat_detail = relationship("StatDetail", back_populates="referred")
