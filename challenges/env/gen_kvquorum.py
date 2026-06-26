#!/usr/bin/env python3
"""Generate env-04-kv-quorum (Go p2p): quorum-replicated key-value store.

Three replicas (peer0..peer2) + a client. N=3, W=2, R=2 (W+R>N => read sees the latest write). A PUT
to a coordinator stores locally and replicates to exactly ONE other replica (W=2), deliberately
leaving the third without the key. The client then GETs from that third replica — which only returns
the value if it performs a real quorum read across peers. A local-only read would miss it, so the
verifier has teeth. Stdlib only (net/http) so `go run .` works offline.

Run:  python challenges/env/gen_kvquorum.py
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent / "env-04-kv-quorum"
REPLICAS = ["peer0", "peer1", "peer2"]
GOMOD = "module kv\n\ngo 1.21\n"

PEER_GO = r'''// Reference quorum-replicated KV replica. N=3, W=2 (self + one peer), R=quorum read across peers.
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
'''

CLIENT_GO = r'''// Reference client: write via two coordinators, then read both keys from the replica that holds
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
'''

VERIFY_PY = '''"""Goal-state verifier for env-04-kv-quorum.

The client wrote k1 via peer0 and k2 via peer1 (each replicated to only ONE other replica, leaving
peer2 without either key), then read both back from peer2. peer2 can only return them via a quorum
read across its peers — a local-only read would miss them. So a correct result proves quorum reads
work. Deterministic: exact expected content.
"""
import time


def verify(env):
    want = "k1=alpha\\nk2=beta"
    got = ""
    deadline = time.time() + 15
    while time.time() < deadline:
        got = (env.node("client").read_file("result.txt").get("content") or "").strip()
        if got == want:
            break
        time.sleep(0.5)
    ok = got == want
    return {"passed": ok, "checks": [
        {"name": "quorum read on a non-replica node returned both writes", "ok": ok,
         "detail": f"client wrote {got!r}; want {want!r}"}]}
'''

META = '''id = "env-04-kv-quorum"
title = "Quorum-replicated key-value store (N=3, W=2, R=2)"
type = "goal-state-env"
category = "multi-machine"
difficulty = 5
max_turns = 14
timeout = 60
published_at        = "2026-06-30"
published_at_source = "author"
'''

SPEC = '''# Quorum-replicated key-value store

Three replica nodes (`peer0`, `peer1`, `peer2`) form a key-value store with **N=3, W=2, R=2**
(W+R>N, so a quorum read always observes the latest quorum write). A separate `client` drives it.

Implement the replica program (`peer.go`) and the `client.go` so that:

- A **PUT** to any replica (the coordinator) stores the value and replicates it to a **write quorum
  of W=2** replicas (itself + one peer), then acknowledges. It must NOT assume every replica gets a
  copy.
- A **GET** from any replica performs a **quorum read (R=2)** across replicas and returns the value
  with the highest version — so a replica that did not receive a particular write still returns the
  correct value.
- The client must: PUT `k1=alpha` via `peer0`, PUT `k2=beta` via `peer1`, then GET both `k1` and
  `k2` **from `peer2`**, and write them to `result.txt` as:

  ```
  k1=alpha
  k2=beta
  ```

`peer2` will be the replica left without those keys, so reading them back from `peer2` only succeeds
with a working quorum read. Use only the Go standard library (`net/http`).

Discovery contract: `PORT` (your listen port) and `PEER_<NAME>_HOST` / `PEER_<NAME>_PORT` for peers.
'''


def main() -> None:
    for name in REPLICAS:
        d = OUT / "reference" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "peer.go").write_text(PEER_GO)
        (d / "go.mod").write_text(GOMOD)
    cl = OUT / "reference" / "client"
    cl.mkdir(parents=True, exist_ok=True)
    (cl / "client.go").write_text(CLIENT_GO)
    (cl / "go.mod").write_text(GOMOD)

    nodes = []
    for name in REPLICAS:
        needs = [p for p in REPLICAS if p != name]
        nodes.append(
            f'[[nodes]]\nname = "{name}"\nimage = "golang:1.23"\nstart = "go run ."\n'
            f'background = true\nports = [7000]\nneeds = {needs!r}\n')
    nodes.append(
        f'[[nodes]]\nname = "client"\nimage = "golang:1.23"\nstart = "go run ."\nneeds = {REPLICAS!r}\n')
    (OUT / "env.toml").write_text(
        "# Three Go replicas (quorum KV) + a client. Writes hit a W=2 quorum; reads must quorum-read.\n"
        "# Discovery via PORT + PEER_<NAME>_HOST/PORT.\n\n" + "\n".join(nodes))
    (OUT / "meta.toml").write_text(META)
    (OUT / "spec.md").write_text(SPEC)
    (OUT / "verify.py").write_text(VERIFY_PY)
    print(f"wrote {OUT} — {len(REPLICAS)} Go replicas + client")


if __name__ == "__main__":
    main()
