// Reference quorum-replicated KV replica. N=3, W=2 (self + one peer), R=quorum read across peers.
package main

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
)

type rec struct {
	val string
	ver int64
}

var (
	mu    sync.Mutex
	store = map[string]rec{}
	verCt int64
	peers = map[string]string{} // name -> base url
	names []string              // sorted peer names
)

func putLocal(key, val string, ver int64) {
	mu.Lock()
	defer mu.Unlock()
	if cur, ok := store[key]; !ok || ver >= cur.ver {
		store[key] = rec{val, ver}
	}
}

func getLocal(key string) (rec, bool) {
	mu.Lock()
	defer mu.Unlock()
	r, ok := store[key]
	return r, ok
}

func fetch(url string) string {
	resp, err := http.Get(url)
	if err != nil {
		return ""
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return string(b)
}

func main() {
	port := os.Getenv("PORT")
	for _, kv := range os.Environ() {
		i := strings.IndexByte(kv, '=')
		k, v := kv[:i], kv[i+1:]
		if strings.HasPrefix(k, "PEER_") && strings.HasSuffix(k, "_HOST") {
			name := strings.ToLower(k[len("PEER_") : len(k)-len("_HOST")])
			if p := os.Getenv("PEER_" + strings.ToUpper(name) + "_PORT"); p != "" {
				peers[name] = "http://" + v + ":" + p
			}
		}
	}
	for n := range peers {
		names = append(names, n)
	}
	sort.Strings(names)

	// coordinator write: store locally, replicate to ONE peer (W=2), then ack.
	http.HandleFunc("/put", func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		ver := atomic.AddInt64(&verCt, 1)
		putLocal(q.Get("key"), q.Get("val"), ver)
		if len(names) > 0 {
			fetch(fmt.Sprintf("%s/replicate?key=%s&val=%s&ver=%d",
				peers[names[0]], q.Get("key"), q.Get("val"), ver))
		}
		fmt.Fprint(w, "ok")
	})
	// peer replication: store locally only (no further fan-out).
	http.HandleFunc("/replicate", func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		ver, _ := strconv.ParseInt(q.Get("ver"), 10, 64)
		putLocal(q.Get("key"), q.Get("val"), ver)
		fmt.Fprint(w, "ok")
	})
	// local-only read, used by quorum reads.
	http.HandleFunc("/local", func(w http.ResponseWriter, r *http.Request) {
		if rc, ok := getLocal(r.URL.Query().Get("key")); ok {
			fmt.Fprintf(w, "%d|%s", rc.ver, rc.val)
		}
	})
	// quorum read: highest-version value across local + every peer.
	http.HandleFunc("/get", func(w http.ResponseWriter, r *http.Request) {
		key := r.URL.Query().Get("key")
		bestVer, bestVal := int64(-1), ""
		if rc, ok := getLocal(key); ok {
			bestVer, bestVal = rc.ver, rc.val
		}
		for _, n := range names {
			body := fetch(peers[n] + "/local?key=" + key)
			if p := strings.SplitN(body, "|", 2); len(p) == 2 {
				if v, err := strconv.ParseInt(p[0], 10, 64); err == nil && v > bestVer {
					bestVer, bestVal = v, p[1]
				}
			}
		}
		fmt.Fprint(w, bestVal)
	})
	http.ListenAndServe("0.0.0.0:"+port, nil)
}
