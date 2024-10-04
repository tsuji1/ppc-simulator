from sqlalchemy import Column, Integer, BigInteger, Text, DECIMAL,ForeignKey,SmallInteger
from sqlalchemy.orm import relationship
from ..db import Base
# from .parameter import Parameter
class CacheLayer(Base):
    __tablename__ = 'cache_layers'
    
    id = Column(Integer, primary_key=True)
    parameter_id = Column(Integer, ForeignKey('parameter.id'))
    layer_index = Column(SmallInteger)
    type = Column(Text)
    size = Column(Integer)
    refbits = Column(Integer)
    
    parameter = relationship("Parameter", back_populates="cache_layers")
