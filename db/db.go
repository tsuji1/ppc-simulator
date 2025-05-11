// db/db.go
package db

import (
	"context"
	"fmt"
	"log"
	"os"
	"test-module/simulator"
	"time"

	"github.com/joho/godotenv"
	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/bson/primitive"
	"go.mongodb.org/mongo-driver/mongo"
	"go.mongodb.org/mongo-driver/mongo/options"
)

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
	if godotenv.Load(".env") != nil {
		log.Fatal("Error loading .env file")
	}
	databaseUrl := os.Getenv("DATABASE_URL")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	client, err := mongo.Connect(ctx, options.Client().ApplyURI(databaseUrl))
	if err != nil {
		return nil, err
	}

	collection := client.Database("db").Collection("simulator_results")
	return &MongoDB{Client: client, Collection: collection}, nil
}

// MongoDBクライアントを作成
func NewTestMongoDB() (*MongoDB, error) {
	// mongo.NewClientの代わりにmongo.Connectを直接使用
	if godotenv.Load(".env") != nil {
		log.Fatal("Error loading .env file")
	}
	databaseUrl := os.Getenv("DATABASE_URL")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	client, err := mongo.Connect(ctx, options.Client().ApplyURI(databaseUrl))
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
type SimulatorResultWithMetadataWithRuleFileName struct {
	ID                 primitive.ObjectID        `bson:"_id"`              // ID
	SimulatorResult    simulator.SimulatorResult `bson:"simulator_result"` // ネストされたSimulatorResult
	Timestamp          time.Time                 `bson:"timestamp"`        // 挿入時のタイムスタンプ
	RuleFileName       string                    `bson:"rule_file_name"`   // ルールファイル名
	TraceFileName      string                    `bson:"trace_file_name"`  // トレースファイル名
	Bitsum             uint64                    `bson:"bitsum"`
	CactiResults       interface{}               `bson:"cacti_results"`
	ThroughputSeries   float64                   `bson:"throughput_series"`
	ThroughputParallel float64                   `bson:"throughput_parallel"`
	CacheSize          uint64                    `bson:"cache_size"`
	PowerSeries        float64                   `bson:"power_series"`
	PowerParallel      float64                   `bson:"power_parallel"`
	Area               float64                   `bson:"area"`
}

type SimulatorResultWithMetadata struct {
	SimulatorResult simulator.SimulatorResult `bson:"simulator_result"` // ネストされたSimulatorResult
	RuleFileName    string                    `bson:"rule_file_name"`   // ルールファイル名
	Timestamp       time.Time                 `bson:"timestamp"`        // 挿入時のタイムスタンプ
	TraceFileName   string                    `bson:"trace_file_name"`  // トレースファイル名
}

// InsertResult を実装。simulatorResult に timestamp を追加して挿入
func (db *MongoDB) InsertResult(ctx context.Context, simulatorResult simulator.SimulatorResult, ruleFileName string, traceFileName string) error {
	//もっといい方法があるとおもう。LRUを追加したときの僕より

	// Timestamp を現在時刻に設定

	if simulatorResult.Type == "MultiLayerCacheExclusive" {
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
	} else if simulatorResult.Type == "NWaySetAssociativeLRUCache" {
		// SimulatorResultWithMetadata 構造体を作成
		var simulatorResultWithMetadata SimulatorResultWithMetadata
		simulatorResultWithMetadata.SimulatorResult = simulatorResult
		simulatorResultWithMetadata.Timestamp = time.Now()
		simulatorResultWithMetadata.TraceFileName = traceFileName

		// データを挿入
		_, err := db.Collection.InsertOne(ctx, simulatorResultWithMetadata)
		if err != nil {
			return fmt.Errorf("failed to insert simulator result: %w", err)
		}
	} else if simulatorResult.Type == "MultiLayerCacheInclusive" {
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
	} else {
		panic("Unknown Simulator Type, Type: " + simulatorResult.Type)
	}

	return nil
}

func (db *MongoDB) GetForDepth(ctx context.Context,
	ruleFileName string,
	traceFileName string) ([][][2]int, error) {
	// フィルタークエリ: Parameter と Processed が一致するドキュメントを検索

	fmt.Printf("ruleFileName: %v\n", ruleFileName)
	fmt.Printf("traceFileName: %v\n", traceFileName)
	filterQuery := bson.M{
		"simulator_result.processed":           10000000,
		"throughput_series":                    bson.M{"$exists": true},
		"rule_file_name":                       ruleFileName,
		"trace_file_name":                      traceFileName,
		"simulator_result.statdetail.depthsum": 0,
	}

	// ドキュメントを探して結果を取得opts := options.Find().SetLimit(0) // 制限なし
	opts := options.Find().SetLimit(0)         // 制限なし
	opts1 := options.Find().SetBatchSize(1000) // 必要ならバッチサイズを設定
	cursor, err := db.Collection.Find(ctx, filterQuery, opts, opts1)
	if err != nil {
		log.Fatal(err)
	}
	defer cursor.Close(ctx)
	var results = make([][][2]int, 0, 300000)
	var size int64
	var refbits int32
	sizedocument := 0

	for cursor.Next(ctx) {
		sizedocument++
		var result SimulatorResultWithMetadataWithRuleFileName
		settings := [][2]int{}
		err := cursor.Decode(&result)
		if err != nil {
			fmt.Printf("Failed to decode: %v", err)
			log.Printf("Failed to decode: %v", err)
			continue
		}
		param := result.SimulatorResult.Parameter.(primitive.D)
		for _, v := range param {
			if v.Key == "cachelayers" {
				cachelayers := v.Value.(primitive.A)
				for _, v := range cachelayers {
					cacheLayer := v.(primitive.D)
					for _, v := range cacheLayer {

						if v.Key == "size" {
							switch v := v.Value.(type) {
							case int64:
								size = v
							case int32:
								size = int64(v) // int32 を int64 に変換
							default:
								log.Printf("Unexpected type for size: %T\n", v)
							}
						}
						if v.Key == "refbits" {
							refbits = v.Value.(int32)
						}

					}
					settings = append(settings, [2]int{int(size), int(refbits)})
					size = 0
					refbits = 0
				}

			}
		}
		results = append(results, settings)
	}
	fmt.Printf("size_document: %v\n", sizedocument)

	// カーソルエラーの確認
	if err := cursor.Err(); err != nil {
		fmt.Printf("cursor.Err(): %v\n", err)
	}

	// ドキュメントが存在する場合
	return results, nil
}

func (db *MongoDB) IsResultExist(ctx context.Context,
	simulatorParameter interface{},
	simulatorProcessed uint64,
	simulatorType string,
	ruleFileName string,
	traceFileName string) (*SimulatorResultWithMetadata, error) {
	// フィルタークエリ: Parameter と Processed が一致するドキュメントを検索

	var filterQuery bson.M

	if simulatorType == "MultiLayerCacheExclusive" {
		filterQuery = bson.M{
			"simulator_result.parameter": simulatorParameter,
			"simulator_result.processed": simulatorProcessed,
			"simulator_result.type":      simulatorType,
			"rule_file_name":             ruleFileName,
			"trace_file_name":            traceFileName, // depthsum が 0 以上である条件を追加
			"simulator_result.statdetail.depthsum": bson.M{
				"$gte": 0, // Greater Than or Equal: 0以上
			},
		}
	} else if simulatorType == "MultiLayerCacheInclusive" {
		fmt.Printf("MultiLayerCacheInclusive\n")
		fmt.Printf("Parameter: %+v\n", simulatorParameter)
		filterQuery = bson.M{
			"simulator_result.parameter": simulatorParameter,
			"simulator_result.processed": simulatorProcessed,
			"simulator_result.type":      simulatorType,
			"rule_file_name":             ruleFileName,
			"trace_file_name":            traceFileName, // depthsum が 0 以上である条件を追加
			// "simulator_result.statdetail.depthsum": bson.M{
			// 	"$gte": 0, // Greater Than or Equal: 0以上
			// },
		}
	} else {
		filterQuery = bson.M{
			"simulator_result.parameter": simulatorParameter,
			"simulator_result.processed": simulatorProcessed,
			"simulator_result.type":      simulatorType,
			"trace_file_name":            traceFileName,
			// depthsum が 0 以上である条件を追加
			"simulator_result.statdetail.depthsum": bson.M{
				"$gte": 0, // Greater Than or Equal: 0以上
			},
		}
	}

	// ドキュメントを探して結果を取得
	var result SimulatorResultWithMetadata
	mongoResult := db.Collection.FindOne(ctx, filterQuery)
	err := mongoResult.Decode(&result)

	if err != nil {
		if err == mongo.ErrNoDocuments {
			// ドキュメントが存在しない場合
			fmt.Println("ドキュメントが存在しない")
			return nil, nil
		}
		fmt.Println("その他のエラー")
		fmt.Println(err)
		// その他のエラー
		return nil, err
	}
	fmt.Println("ドキュメントが存在する")

	// ドキュメントが存在する場合
	return &result, nil
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
