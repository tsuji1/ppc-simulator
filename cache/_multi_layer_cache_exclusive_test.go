package cache

import (
	"fmt"
	"github.com/yosuke-furukawa/json5/encoding/json5"
	"os"
	"test-module/simulator"
	"testing"
)

func TestMain(m *testing.M) {
	// 初期化処理
	println("setup")

	simulaterDefinitionBytes, err := os.ReadFile(os.Args[1])
	if err != nil {
		panic(err)
	}

	var simlatorDefinition interface{}
	err = json5.Unmarshal(simulaterDefinitionBytes, &simlatorDefinition)
	if err != nil {
		panic(err)
	}

	cacheSim, err := simulator.BuildSimpleCacheSimulator(simlatorDefinition, "", nil)

	if err != nil {
		panic(err)
	}
}

func Test1(t *testing.T) {
	// テスト実施
	fmt.Println("do test1")
}

func Test2(t *testing.T) {
	// テスト実施
	fmt.Println("do test2")
}
