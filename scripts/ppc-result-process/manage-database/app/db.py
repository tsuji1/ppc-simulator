from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base

from sqlalchemy.orm import Session,sessionmaker
from .config import DATABASE_URL

# データベース接続設定
# create_engineでデータベース接続エンジンを作成
engine = create_engine(DATABASE_URL)

# セッションを作成するためのクラスを定義
# autocommit=False：トランザクションは明示的にコミットされるまでコミットされない
# autoflush=False：データは明示的にフラッシュされるまでデータベースに送信されない
# bind=engine：このセッションが使用するデータベース接続エンジンを指定
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class TestingSession(Session):
    def commit(self):
        # テストなので永続化しない
        self.flush()
        self.expire_all()



# 基底クラスの定義
# 全てのモデルクラスはこのBaseクラスを継承して定義される
Base = declarative_base()

# データベースの初期化関数
# models.py内で定義された全てのテーブルをデータベースに作成する
def init_db():
    Base.metadata.create_all(bind=engine)
def delete_db():

    # confirmation = input("本当にデータベースを削除しますか？ (yes/no): ")
    confirmation = 'yes'
    
    if confirmation.lower() == 'yes':
        print("データベースのテーブルを削除します...")
        Base.metadata.drop_all(bind=engine)
        print("削除完了しました。")
    else:
        print("操作がキャンセルされました。")
