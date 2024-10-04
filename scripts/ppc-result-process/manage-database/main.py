from app.db import init_db, SessionLocal
from app.crud import create_cache_stat

def main():
    # データベースの初期化
    init_db()
    
    # セッションの作成
    db = SessionLocal()

    # データの挿入例
    # create_cache_stat(db, type="FullAssociativeDstipNbitLRUCache", processed=222305156, hit=217392359, hit_rate=0.9779)

if __name__ == "__main__":
    main()
