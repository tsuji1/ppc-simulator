// db/db.go
package db

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/binary"
	"fmt"
	"log"
	"os"
	"strings"
	"test-module/cache"
	"test-module/simulator"

	// "test-module/cache"
	"time"

	"github.com/joho/godotenv"
	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/bson/primitive"
	"go.mongodb.org/mongo-driver/mongo"
	"go.mongodb.org/mongo-driver/mongo/options"
	"go.mongodb.org/mongo-driver/mongo/readpref"
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
	return newMongoDB("db", "simulator_results")
}

// MongoDBクライアントを作成
func NewTestMongoDB() (*MongoDB, error) {
	return newMongoDB("testdb_test", "simulator_results_test")
}

func newMongoDB(databaseName string, collectionName string) (*MongoDB, error) {
	if err := godotenv.Load(".env"); err != nil {
		// .env が無くても環境変数が直接設定されていれば動作できるため、警告のみ。
		log.Printf("warning: could not load .env: %v", err)
	}

	databaseURL := strings.TrimSpace(os.Getenv("DATABASE_URL"))
	if databaseURL == "" {
		return nil, fmt.Errorf("DATABASE_URL is empty")
	}

	connectCtx, connectCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer connectCancel()

	client, err := mongo.Connect(connectCtx, options.Client().ApplyURI(databaseURL))
	if err != nil {
		return nil, fmt.Errorf("failed to connect MongoDB: %w", err)
	}

	pingCtx, pingCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer pingCancel()
	if err := client.Ping(pingCtx, readpref.Primary()); err != nil {
		_ = client.Disconnect(context.Background())
		return nil, fmt.Errorf("failed to ping MongoDB: %w", err)
	}

	collection := client.Database(databaseName).Collection(collectionName)
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
type SimulatorResultWithMetadataUnifiedCache struct {
	SimulatorResult        simulator.SimulatorResult `bson:"simulator_result"`             // ネストされたSimulatorResult
	RuleFileName           string                    `bson:"rule_file_name"`               // ルールファイル名
	Timestamp              time.Time                 `bson:"timestamp"`                    // 挿入時のタイムスタンプ
	TraceFileName          string                    `bson:"trace_file_name"`              // トレースファイル名
	UnifiedStatEncoding    string                    `bson:"unified_stat_encoding"`        // 圧縮形式
	UnifiedStatRows        int                       `bson:"unified_stat_rows"`            // 行数(=セット数)
	HitCountListCompressed primitive.Binary          `bson:"hit_count_list_compressed"`    // ヒットカウントリスト(gzip圧縮)
	FirstMissCompressed    primitive.Binary          `bson:"first_miss_count_compressed"`  // 初回ミスカウント(gzip圧縮)
	SecondMissCompressed   primitive.Binary          `bson:"second_miss_count_compressed"` // 2回目以降ミス(gzip圧縮)
}

type UnifiedCacheStatSummary struct {
	DepthSum uint64 `json:"DepthSum" bson:"depthsum"`
}

func compressUnifiedCounterRows(rows [][32]uint32) (primitive.Binary, error) {
	raw := make([]byte, 0, len(rows)*32*4)
	var buf [4]byte
	for _, row := range rows {
		for _, v := range row {
			binary.LittleEndian.PutUint32(buf[:], v)
			raw = append(raw, buf[:]...)
		}
	}

	var zipped bytes.Buffer
	zw := gzip.NewWriter(&zipped)
	if _, err := zw.Write(raw); err != nil {
		_ = zw.Close()
		return primitive.Binary{}, err
	}
	if err := zw.Close(); err != nil {
		return primitive.Binary{}, err
	}

	return primitive.Binary{
		Subtype: 0x00,
		Data:    zipped.Bytes(),
	}, nil
}

// InsertResult を実装。simulatorResult に timestamp を追加して挿入
func (db *MongoDB) InsertResult(ctx context.Context, simulatorResult simulator.SimulatorResult, ruleFileName string, traceFileName string) error {
	// UnifiedCache は追加の統計情報を持つため専用ドキュメントで保存する。
	if simulatorResult.Type == "UnifiedCache" {
		unifiedStat, ok := simulatorResult.StatDetail.(cache.UnifiedCacheStat)
		if !ok {
			return fmt.Errorf("unexpected UnifiedCache stat detail type: %T", simulatorResult.StatDetail)
		}

		hitCompressed, err := compressUnifiedCounterRows(unifiedStat.CachelineHitCount)
		if err != nil {
			return fmt.Errorf("failed to compress UnifiedCache hit_count_list: %w", err)
		}
		firstMissCompressed, err := compressUnifiedCounterRows(unifiedStat.CachelineFirstMissCount)
		if err != nil {
			return fmt.Errorf("failed to compress UnifiedCache first_miss_count: %w", err)
		}
		secondMissCompressed, err := compressUnifiedCounterRows(unifiedStat.CachelineSecondMissCount)
		if err != nil {
			return fmt.Errorf("failed to compress UnifiedCache second_miss_count: %w", err)
		}

		// 大きな配列は圧縮フィールドに保存し、statdetail には要約のみ残す。
		simulatorResult.StatDetail = UnifiedCacheStatSummary{
			DepthSum: unifiedStat.DepthSum,
		}

		simulatorResultWithMetadata := SimulatorResultWithMetadataUnifiedCache{
			SimulatorResult:        simulatorResult,
			RuleFileName:           ruleFileName,
			Timestamp:              time.Now(),
			TraceFileName:          traceFileName,
			UnifiedStatEncoding:    "gzip+uint32le[rows][32]",
			UnifiedStatRows:        len(unifiedStat.CachelineHitCount),
			HitCountListCompressed: hitCompressed,
			FirstMissCompressed:    firstMissCompressed,
			SecondMissCompressed:   secondMissCompressed,
		}
		if _, err := db.Collection.InsertOne(ctx, simulatorResultWithMetadata); err != nil {
			return fmt.Errorf("failed to insert simulator result(type=%s): %w", simulatorResult.Type, err)
		}
		return nil
	}

	// それ以外のキャッシュタイプは共通形式で保存する。
	simulatorResultWithMetadata := SimulatorResultWithMetadata{
		SimulatorResult: simulatorResult,
		RuleFileName:    ruleFileName,
		Timestamp:       time.Now(),
		TraceFileName:   traceFileName,
	}
	if _, err := db.Collection.InsertOne(ctx, simulatorResultWithMetadata); err != nil {
		return fmt.Errorf("failed to insert simulator result(type=%s): %w", simulatorResult.Type, err)
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
	simulatorParameter cache.Parameter,
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
	} else if simulatorType == "UnifiedCache" {
		fmt.Printf("UnifiedCache is selected in isResultExist\n")
		fmt.Printf("Parameter: %+v\n", simulatorParameter)
		param := simulatorParameter.(*cache.UnifiedCacheParameter)
		filterQuery = bson.M{
			"simulator_result.parameter.size":           param.Size,
			"simulator_result.parameter.way":            param.Way,
			"simulator_result.parameter.type":           param.Type,
			"simulator_result.parameter.cacheindextype": param.CacheIndexType,
			"simulator_result.parameter.cachetaglength": param.CacheTagLength,
			"simulator_result.processed":                simulatorProcessed,
			"simulator_result.type":                     simulatorType,
			"rule_file_name":                            ruleFileName,
			"trace_file_name":                           traceFileName, // depthsum が 0 以上である条件を追加
		}
	} else {
		filterQuery = bson.M{
			"simulator_result.parameter": simulatorParameter,
			"simulator_result.processed": simulatorProcessed,
			"simulator_result.type":      simulatorType,
			"rule_file_name":             ruleFileName,
			"trace_file_name":            traceFileName,
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
