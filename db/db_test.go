package db_test

import (
	"context"
	"test-module/cache"
	"test-module/db"
	"test-module/simulator"
	"testing"
	"time"

	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/mongo/readpref"
)

// MongoDBへの接続をテスト
func TestMongoDBConnection(t *testing.T) {
	mongoDB, err := db.NewTestMongoDB()
	if err != nil {
		t.Fatalf("Failed to create MongoDB client: %v", err)
	}
	defer mongoDB.Client.Disconnect(context.Background())

	// Pingで接続確認
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	err = mongoDB.Client.Ping(ctx, readpref.Primary())
	if err != nil {
		t.Fatalf("MongoDB connection test failed: %v", err)
	}

	t.Log("MongoDB connection test passed.")

	// コレクションの削除 (テーブルの中身を消す)
	collection := mongoDB.Collection
	err = collection.Drop(ctx)
	if err != nil {
		t.Fatalf("Failed to drop collection: %v", err)
	}

	t.Log("MongoDB connection test passed and collection dropped.")
}

func TestInsertResult(t *testing.T) {
	ctx := context.Background()

	// Create a new test MongoDB instance
	mongoDB, err := db.NewTestMongoDB()
	if err != nil {
		t.Fatalf("Failed to create test MongoDB instance: %v", err)
	}
	defer mongoDB.Client.Disconnect(ctx)

	// Initialize CacheLayers
	cacheLayers := []cache.Parameter{
		&cache.NbitFullAssociativeParameter{
			Type:    "FullAssociativeDstipNbitLRUCache",
			Size:    1,
			Refbits: 32,
		},
		&cache.NbitFullAssociativeParameter{
			Type:    "FullAssociativeDstipNbitLRUCache",
			Size:    640,
			Refbits: 24,
		},
	}

	// Initialize CachePolicies
	cachePolicies := []cache.CachePolicy{0, 0}

	// Initialize MultiLayerCacheExclusiveParameter
	param := &cache.MultiCacheParameter{
		Type:          "MultiLayerCacheExclusive",
		CacheLayers:   cacheLayers,
		CachePolicies: cachePolicies,
	}

	// Create test simulator result
	simResult := simulator.SimulatorResult{
		Type:       "CacheSimulation",
		Processed:  1000,
		Hit:        950,
		HitRate:    0.95,
		Parameter:  param,
		StatDetail: struct{}{}, // Fill with actual details if needed
	}

	// Test InsertResult
	err = mongoDB.InsertResult(ctx, simResult, "", "")
	if err != nil {
		t.Fatalf("InsertResult failed: %v", err)
	}

	// Check if the data was inserted correctly
	var result db.SimulatorResultWithMetadata
	filter := bson.M{"simulator_result.type": "CacheSimulation"}

	err = mongoDB.Collection.FindOne(ctx, filter).Decode(&result)
	if err != nil {
		t.Fatalf("Inserted result not found: %v", err)
	}

	if result.SimulatorResult.Type != simResult.Type {
		t.Errorf("Expected Type %s, but got %s", simResult.Type, result.SimulatorResult.Type)
	}
}

func TestIsExistResult(t *testing.T) {
	ctx := context.Background()

	// Create a new test MongoDB instance
	mongoDB, err := db.NewTestMongoDB()
	if err != nil {
		t.Fatalf("Failed to create test MongoDB instance: %v", err)
	}
	defer mongoDB.Client.Disconnect(ctx)

	// Initialize CacheLayers
	cacheLayers := []cache.Parameter{
		&cache.NbitFullAssociativeParameter{
			Type:    "FullAssociativeDstipNbitLRUCache",
			Size:    1,
			Refbits: 32,
		},
		&cache.NbitFullAssociativeParameter{
			Type:    "FullAssociativeDstipNbitLRUCache",
			Size:    640,
			Refbits: 24,
		},
	}

	// Initialize CachePolicies
	cachePolicies := []cache.CachePolicy{0, 0}

	// Initialize MultiLayerCacheExclusiveParameter
	param := &cache.MultiCacheParameter{
		Type:          "MultiLayerCacheExclusive",
		CacheLayers:   cacheLayers,
		CachePolicies: cachePolicies,
	}

	// Create test simulator result
	simResult := simulator.SimulatorResult{
		Type:       "CacheSimulation",
		Processed:  1000,
		Hit:        950,
		HitRate:    0.95,
		Parameter:  param,
		StatDetail: struct{}{}, // Fill with actual details if needed
	}

	// Insert the test data first
	err = mongoDB.InsertResult(ctx, simResult, "", "")
	if err != nil {
		t.Fatalf("InsertResult failed: %v", err)
	}

	// Test IsResultExist function
	exists, err := mongoDB.IsResultExist(ctx, simResult.Parameter, uint64(simResult.Processed), simResult.Type, "", "")
	if err != nil {
		t.Fatalf("IsResultExist failed: %v", err)
	}

	// Check if the result exists
	if !exists {
		t.Errorf("Expected result to exist, but it does not")
	}

	// Check with different Processed value to ensure non-existence
	simResult.Processed = 999 // Modify to an unmatched value
	exists, err = mongoDB.IsResultExist(ctx, simResult.Parameter, uint64(simResult.Processed), simResult.Type, "", "")
	if err != nil {
		t.Fatalf("IsResultExist failed with different Processed value: %v", err)
	}

	if exists {
		t.Errorf("Expected result to not exist, but it does")
	}

	simResult.Processed = 1000 // Reset to original value

	// Check with different Type value to ensure non-existence
	simResult.Type = "DifferentType" // Modify to an unmatched value
	exists, err = mongoDB.IsResultExist(ctx, simResult.Parameter, uint64(simResult.Processed), simResult.Type, "", "")
	if err != nil {
		t.Fatalf("IsResultExist failed with different Type value: %v", err)
	}

	if exists {
		t.Errorf("Expected result to not exist, but it does")
	}

	simResult.Type = "CacheSimulation" // Reset to original value

	// Check with different Parameter value to ensure non-existence
	simResult.Parameter = &cache.MultiCacheParameter{
		Type:          "MultiLayerCacheExclusive",
		CacheLayers:   cacheLayers,
		CachePolicies: []cache.CachePolicy{1, 1}, // Modify to an unmatched value
	} // Modify to an unmatched value
	exists, err = mongoDB.IsResultExist(ctx, simResult.Parameter, uint64(simResult.Processed), simResult.Type, "", "")
	if err != nil {
		t.Fatalf("IsResultExist failed with different Parameter value: %v", err)
	}

	if exists {
		t.Errorf("Expected result to not exist, but it does")
	}

	// Check with Same Parameter value to ensure existence
	simResult.Parameter = &cache.MultiCacheParameter{
		Type:          "MultiLayerCacheExclusive",
		CacheLayers:   cacheLayers,
		CachePolicies: []cache.CachePolicy{0, 0}, // Modify to an unmatched value
	} // Modify to an unmatched value
	exists, err = mongoDB.IsResultExist(ctx, simResult.Parameter, uint64(simResult.Processed), simResult.Type, "", "")
	if err != nil {
		t.Fatalf("IsResultExist failed with different Parameter value: %v", err)
	}

	if !exists {
		t.Errorf("Expected result to exist, but it doesn't")
	}

	exists, err = mongoDB.IsResultExist(ctx, simResult.Parameter, uint64(simResult.Processed), simResult.Type, "test", "")
	if err != nil {
		t.Fatalf("IsResultExist failed with different Parameter value: %v", err)
	}

	if exists {
		t.Errorf("Expected result to not exist, but it does")
	}

	exists, err = mongoDB.IsResultExist(ctx, simResult.Parameter, uint64(simResult.Processed), simResult.Type, "", "test")
	if err != nil {
		t.Fatalf("IsResultExist failed with different Parameter value: %v", err)
	}

	if exists {
		t.Errorf("Expected result to not exist, but it does")
	}

}

// DeleteResult をテスト
// func TestDeleteResult(t *testing.T) {
// 	ctx := context.Background()

// 	// Create a new test MongoDB instance
// 	mongoDB, err := db.NewTestMongoDB()
// 	if err != nil {
// 		t.Fatalf("Failed to create test MongoDB instance: %v", err)
// 	}
// 	defer mongoDB.Client.Disconnect(ctx)

// 	// Initialize CacheLayers
// 	cacheLayers := []cache.Parameter{
// 		&cache.NbitFullAssociativeParameter{
// 			Type:    "FullAssociativeDstipNbitLRUCache",
// 			Size:    1,
// 			Refbits: 32,
// 		},
// 		&cache.NbitFullAssociativeParameter{
// 			Type:    "FullAssociativeDstipNbitLRUCache",
// 			Size:    640,
// 			Refbits: 24,
// 		},
// 	}

// 	// Initialize CachePolicies
// 	cachePolicies := []cache.CachePolicy{0, 0}

// 	// Initialize MultiLayerCacheExclusiveParameter
// 	param := &cache.MultiCacheParameter{
// 		Type:          "MultiLayerCacheExclusive",
// 		CacheLayers:   cacheLayers,
// 		CachePolicies: cachePolicies,
// 	}

// 	// Create test simulator result
// 	simResult := simulator.SimulatorResult{
// 		Type:       "CacheSimulation",
// 		Processed:  1000,
// 		Hit:        950,
// 		HitRate:    0.95,
// 		Parameter:  param,
// 		StatDetail: struct{}{}, // Fill with actual details if needed
// 	}
// 	err = mongoDB.InsertResult(ctx, simResult)
// 	if err != nil {
// 		t.Fatalf("InsertResult failed: %v", err)
// 	}

// 	// Retrieve inserted data to get its ID
// 	var result db.SimulatorResultWithMetadata
// 	err = mongoDB.Collection.FindOne(ctx, bson.M{"simulatorResult.Type": "CacheSimulation"}).Decode(&result)
// 	if err != nil {
// 		t.Fatalf("Inserted result not found: %v", err)
// 	}

// 	// Test DeleteResult
// 	err = mongoDB.DeleteResult(ctx, result.SimulatorResult.Type)
// 	if err != nil {
// 		t.Fatalf("DeleteResult failed: %v", err)
// 	}

// 	// Verify deletion
// 	err = mongoDB.Collection.FindOne(ctx, bson.M{"simulatorResult.Type": "CacheSimulation"}).Decode(&result)
// 	if err == nil {
// 		t.Errorf("Result should have been deleted, but it was found")
// 	}
// }
