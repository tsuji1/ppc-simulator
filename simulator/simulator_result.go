package simulator

// MultiLayerCacheの構造体を定義
type SimulatorResult struct {
	Type       string     `json:"Type"`
	Parameter  Parameter  `json:"Parameter"`
	Processed  int        `json:"Processed"`
	Hit        int        `json:"Hit"`
	HitRate    float64    `json:"HitRate"`
	StatDetail StatDetail `json:"StatDetail"`
}

type Parameter struct {
	Type          string       `json:"Type"`
	CacheLayers   []CacheLayer `json:"CacheLayers"`
	CachePolicies []string     `json:"CachePolicies"`
}

type CacheLayer struct {
	Type string `json:"Type"`
	Way  int    `json:"Way"`
	Size int    `json:"Size"`
	Ref  int    `json:"Ref"`
}

type StatDetail struct {
	Refered         []int `json:"Refered"`
	Replaced        []int `json:"Replaced"`
	Hit             []int `json:"Hit"`
	MatchMap        []int `json:"MatchMap"`
	LongestMatchMap []int `json:"LongestMatchMap"`
	DepthSum        int   `json:"DepthSum"`
	Inserted        []int `json:"Inserted"`
}
