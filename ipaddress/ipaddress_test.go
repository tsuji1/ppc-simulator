package ipaddress

import (
	"fmt"
	"testing"
)

func TestMaskedBitString(t *testing.T) {
	ip := NewIPaddress("192.168.2.2")
	fmt.Println(ip.String())
	masked := ip.MaskedBitString(24)
	ip_masked := BitStringToIP(masked)
	fmt.Println(masked)
	fmt.Print(len(masked))
	if len(masked) != 24 {
		t.Error("TestMaskedBitString error")
	}
	if ip_masked != "192.168.2.0" {
		t.Error("TestMaskedBitString error")
	}
}
