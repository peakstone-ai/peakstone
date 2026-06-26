// Reference client: write via two coordinators, then read both keys from the replica that holds
// neither — exercising the quorum read.
package main

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

func base(name string) string {
	return "http://" + os.Getenv("PEER_"+name+"_HOST") + ":" + os.Getenv("PEER_"+name+"_PORT")
}

func fetch(url string) string {
	for i := 0; i < 60; i++ {
		if resp, err := http.Get(url); err == nil {
			b, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			return string(b)
		}
		time.Sleep(200 * time.Millisecond)
	}
	return ""
}

func main() {
	p0, p1, p2 := base("PEER0"), base("PEER1"), base("PEER2")
	fetch(p0 + "/put?key=k1&val=alpha") // peer0 replicates to peer1; peer2 left without k1
	fetch(p1 + "/put?key=k2&val=beta")  // peer1 replicates to peer0; peer2 left without k2
	var v1, v2 string
	for i := 0; i < 60; i++ {
		v1 = fetch(p2 + "/get?key=k1") // peer2 holds neither -> needs a quorum read
		v2 = fetch(p2 + "/get?key=k2")
		if v1 != "" && v2 != "" {
			break
		}
		time.Sleep(200 * time.Millisecond)
	}
	os.WriteFile("result.txt", []byte(fmt.Sprintf("k1=%s\nk2=%s", v1, v2)), 0644)
}
