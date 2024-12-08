package ipaddress

import (
	"encoding/binary"
	"fmt"
	"math"
	"math/rand"
	"net"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/praserx/ipconv"
)

// IPaddress型の定義。内部で32ビットのIPアドレスを保持。
type IPaddress struct {
	ipaddress uint32
}

// Uint32メソッドは、IPaddress構造体のipaddressフィールドを返す。
func (hoge IPaddress) Uint32() uint32 {
	return hoge.ipaddress
}

// BitStringメソッドは、32ビットのビット列としてIPアドレスを返す。
func (hoge IPaddress) BitString() string {
	return hoge.MaskedBitString(32)
}

// MaskedBitStringメソッドは、指定されたプレフィックス長に基づいてビット列を返す。
/*
	input:  ipアドレス(整数)とマスク
	output: ビット列 (マスク分欠け)
	ex. 255, 3 = 0.0.0.255/29
		00000000 00000000 00000000 11111
*/
func (hoge IPaddress) MaskedBitString(prefix int) string {
	if 0 <= prefix && prefix <= 32 {
		str := fmt.Sprintf("%032s", strconv.FormatInt(int64(hoge.ipaddress), 2))
		return str[:prefix]
	} else {
		panic(fmt.Sprintf("MaskedBitString:mask or prefix is %d", prefix))
	}

}

// Stringメソッドは、IPアドレスをドット区切りの文字列として返す。
func (hoge IPaddress) String() string {
	ip := make(net.IP, 4)
	binary.BigEndian.PutUint32(ip, hoge.ipaddress)
	return ip.String()
}

// SetIPメソッドは、様々な入力形式からIPアドレスを設定する。
func (hoge *IPaddress) SetIP(input interface{}) {
	switch a := input.(type) {
	case int:
		hoge.ipaddress = uint32(a)
	case string:
		i, _ := ipconv.IPv4ToInt(net.ParseIP(a))
		hoge.ipaddress = uint32(i)
	case uint32:
		hoge.ipaddress = a
	default:
		panic(fmt.Sprintf("SetIP:%v is not IPaddress", input))
	}
}

// regIPは、ビット文字列をチェックするための正規表現。
var regIP = regexp.MustCompilePOSIX(`[^01]+`)

// isBitString関数は、入力がビット文字列であるかを判定する。
func isBitString(a string) bool {
	if !(regIP.MatchString(a)) && len(a) <= 32 {
		return true
	}
	return false
}

// Reverse関数は、文字列を逆順にする。
func Reverse(s string) string {
	runes := []rune(s)
	for i, j := 0, len(runes)-1; i < j; i, j = i+1, j-1 {
		runes[i], runes[j] = runes[j], runes[i]
	}
	return string(runes)
}

// BitStringToIP関数は、ビット文字列をドット区切りのIPアドレス文字列に変換する。
func BitStringToIP(a string) string {
	b := a + "00000000000000000000000000000000"
	b = b[0:32]
	c := func(c string) int {
		ans := 0
		for i, item := range Reverse(c) {
			if item == 49 {
				ans += int(math.Pow(2, float64(i)))
			}
		}
		return ans
	}
	return fmt.Sprintf("%d.%d.%d.%d", c(b[0:8]), c(b[8:16]), c(b[16:24]), c(b[24:32]))
}

// NewIPaddress関数は、入力をもとに新しいIPaddress構造体を作成する。
func NewIPaddress(input interface{}) IPaddress {
	var temp uint32
	switch a := input.(type) {
	case int:
		temp = uint32(a)
	case string:
		if strings.Contains(a, ".") {
			i, _ := ipconv.IPv4ToInt(net.ParseIP(a))
			temp = i
		} else if isBitString(a) {
			i, _ := ipconv.IPv4ToInt(net.ParseIP(BitStringToIP(a)))
			temp = i
		} else {
			panic(fmt.Sprintf("NewIPaddress:%v is not IPaddress string", input))
		}
	case uint32:
		temp = a
	default:
		panic(fmt.Sprintf("NewIPaddress:%v (type:%T) is not IPaddress", input, a))
	}
	return IPaddress{
		ipaddress: temp,
	}
}

func GetRandomIP() IPaddress {

	// 乱数生成
	strIP := ""
	for i := 0; i < 4; i++ {
		rand.NewSource(time.Now().UnixNano())
		randomint := rand.Intn(254) // 0-253の乱数生成
		randomint = randomint + 1
		strIP += strconv.Itoa(randomint)
		if i != 3 {
			strIP += "."
		}
	}
	ip := NewIPaddress(strIP)

	return ip
}

func GetRandomPrefix() uint8 {
	rand.NewSource(time.Now().UnixNano())
	
	return uint8(rand.Intn(32)+1)
}
