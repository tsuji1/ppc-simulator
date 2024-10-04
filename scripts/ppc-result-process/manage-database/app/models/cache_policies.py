from sqlalchemy import Column, Integer, BigInteger, Text, DECIMAL,ForeignKey,SmallInteger
from sqlalchemy.orm import relationship
from ..db import Base

class CachePolicy(Base):
    __tablename__ = 'cache_policies'
    
    id = Column(Integer, primary_key=True)
    parameter_id = Column(Integer, ForeignKey('parameter.id'))
    policy_index = Column(SmallInteger)
    policy = Column(Text)
    
    parameter = relationship("Parameter", lazy='joined', back_populates="cache_policies")
