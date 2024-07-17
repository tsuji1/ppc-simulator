package ipaddress

import (
	"fmt"
	"strconv"
	"net"
	"strings"
	"regexp"
	"math"
	"github.com/praserx/ipconv"
	"encoding/binary"
)

type IPaddress struct{
	ipaddress	uint32
}

func (hoge IPaddress) Uint32() uint32{
	return hoge.ipaddress
}

func (hoge IPaddress) BitString() string{
	return hoge.MaskedBitString(32)
}

func (hoge IPaddress) MaskedBitString(prefix int) string{
	if 0 <= prefix && prefix <= 32 {
		str := fmt.Sprintf("%032s", strconv.FormatInt(int64(hoge.ipaddress), 2))
		return str[:prefix]
	}else{
		panic(fmt.Sprintf("MaskedBitString:mask or prefix is %d", prefix))
	}
	/*
	input:	ipアドレス(整数)とマスク
	output:	ビット列 (マスク分欠け)
	ex. 255, 3 = 0.0.0.255/29
		00000000 00000000 00000000 11111
	*/
}

func (hoge IPaddress) String() string{
	ip := make(net.IP, 4)
	binary.BigEndian.PutUint32(ip, hoge.ipaddress)
	return ip.String()
}

func (hoge *IPaddress) SetIP(input interface{}) {
	switch a := input.(type){
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

var regIP = regexp.MustCompilePOSIX(`[^01]+`)

func isBitString(a string) bool{
	if !(regIP.MatchString(a)) && len(a)<=32{
		return true
	}
	return false
}

func Reverse(s string) string {
	runes := []rune(s)
	for i, j := 0, len(runes)-1; i < j; i, j = i+1, j-1 {
		runes[i], runes[j] = runes[j], runes[i]}
	return string(runes)
}

func bitStringToIP(a string) string{
	b := a + "00000000000000000000000000000000"
	b = b[0:32]
	c := func(c string) int{
		ans := 0
		for i,item := range(Reverse(c)){
			if item == 49{
				ans += int(math.Pow(2,float64(i)))}}
		return ans
	}
	return fmt.Sprintf("%d.%d.%d.%d",c(b[0:8]), c(b[8:16]), c(b[16:24]), c(b[24:32]))
}

func NewIPaddress(input interface{}) IPaddress {
	var temp uint32
	switch a := input.(type){
		case int:
			temp = uint32(a)
		case string:
			if strings.Contains(a, "."){
				i, _ := ipconv.IPv4ToInt(net.ParseIP(a))
				temp = i
			}else if isBitString(a){
				i, _ := ipconv.IPv4ToInt(net.ParseIP(bitStringToIP(a)))
				temp = i
			}else{
				panic(fmt.Sprintf("NewIPaddress:%v is not IPaddress string", input))}
		case uint32:
			temp = a
		default:
			panic(fmt.Sprintf("NewIPaddress:%v (type:%T) is not IPaddress", input, a))
	}
	return IPaddress{
		ipaddress: temp,
	}
}
