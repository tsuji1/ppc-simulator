from sqlalchemy import Column, Integer, BigInteger, Text, DECIMAL,ForeignKey,SmallInteger
from sqlalchemy.orm import relationship
from ..db import Base


class Templaete(Base):
    __tablename__ = 'template'
    
    id = Column(Integer, primary_key=True)
    parameter_id = Column(Integer, ForeignKey('template.id'))
    layer_index = Column(SmallInteger)
    layer_type = Column(Text)
    size = Column(Integer)
    refbits = Column(Integer)
    
    parameter = relationship("Parameter", back_populates="template")
