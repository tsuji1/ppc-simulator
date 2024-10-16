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
	RuleFileName    string                    `bson:"rule_file_name"`   // ルールファイル名
	TraceFileName   string                    `bson:"trace_file_name"`  // トレースファイル名
}

// InsertResult を実装。simulatorResult に timestamp を追加して挿入
func (db *MongoDB) InsertResult(ctx context.Context, simulatorResult simulator.SimulatorResult, ruleFileName string, traceFileName string) error {
	// Timestamp を現在時刻に設定

	// SimulatorResultWithMetadata 構造体を作成
	var simulatorResultWithMetadata SimulatorResultWithMetadata
	simulatorResultWithMetadata.SimulatorResult = simulatorResult
	simulatorResultWithMetadata.Timestamp = time.Now()
	simulatorResultWithMetadata.RuleFileName = ruleFileName
	simulatorResultWithMetadata.TraceFileName = traceFileName

	// データを挿入f
	_, err := db.Collection.InsertOne(ctx, simulatorResultWithMetadata)
	if err != nil {
		return fmt.Errorf("failed to insert simulator result: %w", err)
	}

	return nil
}

func (db *MongoDB) IsResultExist(ctx context.Context,
	simulatorParameter interface{},
	simulatorProcessed uint64,
	simulatorType string,
	ruleFileName string,
	traceFileName string) (bool, error) {
	// フィルタークエリ: Parameter と Processed が一致するドキュメントを検索
	filterQuery := bson.M{
		"simulator_result.parameter": simulatorParameter,
		"simulator_result.processed": simulatorProcessed,
		"simulator_result.type":      simulatorType,
		"rule_file_name":             ruleFileName,
		"trace_file_name":            traceFileName,
	}

	// ドキュメントを探して結果を取得
	var result SimulatorResultWithMetadata
	fmt.Printf("filterQuery: %v\n", filterQuery)
	err := db.Collection.FindOne(ctx, filterQuery).Decode(&result)
	fmt.Println(result)
	if err != nil {
		if err == mongo.ErrNoDocuments {
			// ドキュメントが存在しない場合
			fmt.Println("ドキュメントが存在しない")
			return false, nil
		}
		fmt.Println("その他のエラー")
		fmt.Println(err)
		// その他のエラー
		return false, err
	}
	fmt.Println("ドキュメントが存在する")

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
