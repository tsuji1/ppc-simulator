# README.md


## aloheart



### データ


#### ルール
/research/rulesにルールが存在し、普通の権限で読める
/research/rules/wide.rib.20240625.1400.unique.rule
/research/rules/rib.20260327.0600.unique.rule
/research/rules/rib.20251227.0600.unique.rule
/research/rules/rib.20160628.1200.bz2
/research/rules/rib.20250927.0600.unique.rule


#### トレース



/research/traceにトレースデータが存在する.root権限でしか読めない
/research/trace/wget-log
/research/trace/2025-12-27.pcap.xz
/research/trace/2025-09-27.pcap.zst
/research/trace/202509271400.pcap
/research/trace/202512271400.pcap.gz
/research/trace/2025-12-27.pcap
/research/trace/2026-03-27.pcap.xz
/research/trace/202603271400-anon.pcap
/research/trace/2025-09-27.pcap
/research/trace/202512271400.pcap
/research/trace/2026-03-27.pcap

anonとついているものは匿名化されている.また1400(jst)など時刻が付いているものは匿名化されているものである.
















## メモ

ルーティングテーブルのルールは.ruleでruleディレクトリ以下

go tool pprof -http=localhost:8080 cpu.prof


## 長田さんメモ

・環境
windows 10
GoLang ver.1.22.5

・コンパイル方法
このファイルがあるパスで下記コマンドを実行
go build main.go
生成されたmain.exeが実行ファイル

・実行方法
下記コマンドを上記パスで実行
main.exe ほげ.json ふが.txt
ほげ.jsonはキャッシュ構成のコンフィグファイル(test2.jsonがサンプル,長田の提案手法の構成)
	長田の提案手法のキャッシュ(multi_layer_cache_*)は、"Rule"でルーティング情報が書かれているファイルを指定する必要があります(zisaku_rule.txtがサンプル)
ふが.txtはネットワークトレースのファイル
	pcapからテキストに変換してください(zisaku.txtがサンプル)

・注意
routingtable.go内のCalTreeDepth()が未完成です。
理想：LPC trieに格納したときの高さ
現在：二分木に格納したときの高さ
