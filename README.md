# README.md


## メモ

ルーティングテーブルのルールは.ruleでruleディレクトリ以下



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
