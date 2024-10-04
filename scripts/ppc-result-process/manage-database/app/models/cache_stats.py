from sqlalchemy import Column, Integer, BigInteger, Text, DECIMAL
from sqlalchemy.orm import relationship
from ..db import Base
from .parameter import Parameter
from .stat_detail import StatDetail

# SQLAlchemyのベースクラスから継承してデータベースのテーブルとマッピングするクラス
class CacheStats(Base):
    # テーブル名を定義
    __tablename__ = 'cache_stats'
    
    # 主キーとして、連番のIDカラムを定義。各レコードは一意のIDを持つ
    id = Column(Integer, primary_key=True)
    
    # キャッシュのタイプを表すテキストカラム。例えばキャッシュアルゴリズムの種類などを保持する
    type = Column(Text)
    
    # 処理されたデータ数を表すBigInteger（64ビット整数）カラム。非常に大きな数値を扱う場合に適する
    processed = Column(BigInteger)
    
    # ヒットしたデータ数を保持するBigIntegerカラム。キャッシュヒットの数を記録
    hit = Column(BigInteger)
    
    # ヒット率（hit / processed）を保持するDECIMAL型のカラム。小数点を含む数値を扱う
    hit_rate = Column(DECIMAL)
    
    # "Parameter" テーブルとのリレーションシップを定義。多対1（"Parameter"側は1、"CacheStats"側は多）の関係を表す。
    # back_populatesは双方向リレーションシップを設定し、"Parameter"モデル側にも同様の関係が定義されていることを示す
    parameters = relationship(Parameter, back_populates="cache_stat")
    
    # "StatDetail" テーブルとのリレーションシップを定義。多対1（"StatDetail"側は1、"CacheStats"側は多）の関係。
    # これもback_populatesで双方向の関係を設定する
    stat_details = relationship(StatDetail, back_populates="cache_stat")
