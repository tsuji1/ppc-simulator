// db/db.go
package db

import (
	"context"
	"fmt"
	"test-module/simulator"
	"time"

	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/mongo"
	"go.mongodb.org/mongo-driver/mongo/options"
)

const uri = "mongodb://localhost:27017"

// DB のインターフェース
type DB interface {
	InsertResult(ctx context.Context, simulatorResult simulator.SimulatorResult) error
	DeleteResult(ctx context.Context, id string) error
}

// MongoDBクライアント構造体
type MongoDB struct {
	Client     *mongo.Client
	Collection *mongo.Collection
}

// MongoDBクライアントを作成
func NewMongoDB() (*MongoDB, error) {
	// mongo.NewClientの代わりにmongo.Connectを直接使用
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	client, err := mongo.Connect(ctx, options.Client().ApplyURI(uri))
	if err != nil {
		return nil, err
	}

	collection := client.Database("db").Collection("simulator_results")
	return &MongoDB{Client: client, Collection: collection}, nil
}

// MongoDBクライアントを作成
func NewTestMongoDB() (*MongoDB, error) {
	// mongo.NewClientの代わりにmongo.Connectを直接使用
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	client, err := mongo.Connect(ctx, options.Client().ApplyURI(uri))
	if err != nil {
		return nil, err
	}

	collection := client.Database("testdb_test").Collection("simulator_results_test")
	return &MongoDB{Client: client, Collection: collection}, nil
}

// MongoDBクライアントをクローズする
func (db *MongoDB) Close(ctx context.Context) error {
	return db.Client.Disconnect(ctx)
}

// SimulatorResultWithMetadata 構造体
type SimulatorResultWithMetadata struct {
	SimulatorResult simulator.SimulatorResult `bson:"simulator_result"` // ネストされたSimulatorResult
	Timestamp       time.Time                 `bson:"timestamp"`        // 挿入時のタイムスタンプ
}

// InsertResult を実装。simulatorResult に timestamp を追加して挿入
func (db *MongoDB) InsertResult(ctx context.Context, simulatorResult simulator.SimulatorResult) error {
	// Timestamp を現在時刻に設定

	// SimulatorResultWithMetadata 構造体を作成
	var simulatorResultWithMetadata SimulatorResultWithMetadata
	simulatorResultWithMetadata.SimulatorResult = simulatorResult
	simulatorResultWithMetadata.Timestamp = time.Now()

	// データを挿入f
	_, err := db.Collection.InsertOne(ctx, simulatorResultWithMetadata)
	if err != nil {
		return fmt.Errorf("failed to insert simulator result: %w", err)
	}

	return nil
}

func (db *MongoDB) IsResultExist(ctx context.Context, simulatorResult simulator.SimulatorResult) (bool, error) {

	// フィルタークエリ: Parameter と Processed が一致するドキュメントを検索
	filterQuery := bson.M{
		"simulator_result.parameter": simulatorResult.Parameter,
		"simulator_result.processed": simulatorResult.Processed,
		"simulator_result.type":      simulatorResult.Type,
	}

	// ドキュメントを探して結果を取得
	var result SimulatorResultWithMetadata
	err := db.Collection.FindOne(ctx, filterQuery).Decode(&result)
	fmt.Println(result)
	if err != nil {
		if err == mongo.ErrNoDocuments {
			// ドキュメントが存在しない場合
			return false, nil
		}
		fmt.Println("その他のエラー")
		fmt.Println(err)
		// その他のエラー
		return false, err
	}

	// ドキュメントが存在する場合
	return true, nil
}

// DeleteResult を実装。指定された id でデータを削除
func (db *MongoDB) DeleteResult(ctx context.Context, id string) error {
	// ID で削除
	_, err := db.Collection.DeleteOne(ctx, bson.M{"_id": id})
	if err != nil {
		return fmt.Errorf("failed to delete result with id %s: %w", id, err)
	}

	return nil
}
