// ps-agent — the Peakstone guest agent for Firecracker microVMs (PLAN.md §9 P3, Milestone 1).
//
// It boots as PID 1 (kernel arg init=/usr/local/bin/ps-agent), brings up the essential filesystems
// itself (no systemd), and serves a newline-delimited JSON protocol over AF_VSOCK. The host
// (engine/env/firecracker.py) connects through Firecracker's vsock UDS and issues one request per
// connection: ping / write / read / run. This is the exec layer a microVM lacks (no `docker exec`).
//
// Build (static, no libc): CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o ps-agent .
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

const agentPort = 1024     // fixed; the host connects to this vsock port
const maxRequest = 8 << 20 // cap one request so a never-newline client can't buffer unbounded

type req struct {
	Op         string            `json:"op"`
	Path       string            `json:"path"`
	Content    string            `json:"content"`
	Cmd        string            `json:"cmd"`
	Cwd        string            `json:"cwd"`
	Env        map[string]string `json:"env"`
	Timeout    int               `json:"timeout"`
	Background bool              `json:"background"`
}

func main() {
	pid1 := os.Getpid() == 1
	if pid1 {
		bringUp()
		go reap()
	}
	logln("ps-agent up (pid1=%v); listening on vsock port %d", pid1, agentPort)

	fd, err := unix.Socket(unix.AF_VSOCK, unix.SOCK_STREAM, 0)
	if err != nil {
		fatal("vsock socket: %v", err)
	}
	if err := unix.Bind(fd, &unix.SockaddrVM{CID: unix.VMADDR_CID_ANY, Port: agentPort}); err != nil {
		fatal("vsock bind: %v", err)
	}
	if err := unix.Listen(fd, 16); err != nil {
		fatal("vsock listen: %v", err)
	}
	for {
		nfd, _, err := unix.Accept(fd)
		if err != nil {
			logln("accept: %v", err)
			continue
		}
		// recv timeout: a stalled/half-open client can't pin a goroutine forever
		_ = unix.SetsockoptTimeval(nfd, unix.SOL_SOCKET, unix.SO_RCVTIMEO, &unix.Timeval{Sec: 30})
		go handle(nfd)
	}
}

// bringUp mounts the filesystems a normal init would (we replace init for a fast, minimal boot).
func bringUp() {
	for _, m := range []struct{ src, dst, fs string }{
		{"proc", "/proc", "proc"}, {"sysfs", "/sys", "sysfs"},
		{"devtmpfs", "/dev", "devtmpfs"}, {"tmpfs", "/tmp", "tmpfs"},
	} {
		os.MkdirAll(m.dst, 0o755)
		if err := unix.Mount(m.src, m.dst, m.fs, 0, ""); err != nil {
			logln("mount %s: %v (continuing)", m.dst, err)
		}
	}
	os.MkdirAll("/work", 0o755)
	// loopback must be up or 127.0.0.1 is "Network unreachable" (a minimal init leaves lo down)
	exec.Command("/bin/sh", "-c", "ip link set lo up").Run()
}

func reap() { // PID 1 must reap orphaned children
	ch := make(chan os.Signal, 8)
	signal.Notify(ch, syscall.SIGCHLD)
	for range ch {
		for {
			var ws unix.WaitStatus
			pid, err := unix.Wait4(-1, &ws, unix.WNOHANG, nil)
			if pid <= 0 || err != nil {
				break
			}
		}
	}
}

func handle(fd int) {
	f := os.NewFile(uintptr(fd), "vsock")
	defer f.Close()
	line, err := bufio.NewReaderSize(io.LimitReader(f, maxRequest), 64<<10).ReadBytes('\n')
	if err != nil && len(line) == 0 {
		return
	}
	var r req
	if err := json.Unmarshal(bytes.TrimSpace(line), &r); err != nil {
		writeJSON(f, map[string]any{"error": "bad request: " + err.Error()})
		return
	}
	writeJSON(f, dispatch(r))
}

func dispatch(r req) map[string]any {
	switch r.Op {
	case "ping":
		return map[string]any{"ok": true, "pid": os.Getpid()}
	case "write":
		p := rooted(r.Path)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			return map[string]any{"error": err.Error()}
		}
		if err := os.WriteFile(p, []byte(r.Content), 0o644); err != nil {
			return map[string]any{"error": err.Error()}
		}
		return map[string]any{"ok": true, "path": r.Path, "bytes": len(r.Content)}
	case "read":
		b, err := os.ReadFile(rooted(r.Path))
		if err != nil {
			return map[string]any{"error": "no such file: " + r.Path}
		}
		return map[string]any{"content": string(b)}
	case "run":
		return run(r)
	default:
		return map[string]any{"error": "unknown op: " + r.Op}
	}
}

func rooted(p string) string {
	if filepath.IsAbs(p) {
		return p
	}
	return filepath.Join("/work", p)
}

// baseEnv is the environment for executed commands. As PID 1 we inherit almost nothing from the
// kernel (notably no PATH), so a bare `sh -c "go test"` couldn't find the toolchains. Seed from
// /etc/environment — where the image declares its PATH/GOROOT/CARGO_HOME/etc — and guarantee a PATH.
// Loaded once; per-request env (r.Env) overlays it.
var baseEnv = loadBaseEnv()

func loadBaseEnv() []string {
	m := map[string]string{}
	for _, kv := range os.Environ() {
		if i := strings.IndexByte(kv, '='); i > 0 {
			m[kv[:i]] = kv[i+1:]
		}
	}
	if data, err := os.ReadFile("/etc/environment"); err == nil { // KEY=VALUE / KEY="VALUE" lines
		for _, line := range strings.Split(string(data), "\n") {
			line = strings.TrimSpace(line)
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			if i := strings.IndexByte(line, '='); i > 0 {
				m[strings.TrimSpace(line[:i])] = strings.Trim(strings.TrimSpace(line[i+1:]), "\"'")
			}
		}
	}
	if m["PATH"] == "" {
		m["PATH"] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
	}
	out := make([]string, 0, len(m))
	for k, v := range m {
		out = append(out, k+"="+v)
	}
	return out
}

func run(r req) map[string]any {
	cwd := r.Cwd
	if cwd == "" {
		cwd = "/work"
	}
	env := append([]string(nil), baseEnv...)
	for k, v := range r.Env {
		env = append(env, k+"="+v)
	}
	if r.Background {
		c := exec.Command("/bin/sh", "-c", r.Cmd)
		c.Dir, c.Env = cwd, env
		log, _ := os.Create(filepath.Join(cwd, ".bglog"))
		c.Stdout, c.Stderr = log, log
		if err := c.Start(); err != nil {
			return map[string]any{"rc": 127, "stderr": err.Error()}
		}
		return map[string]any{"ok": true, "pid": c.Process.Pid, "rc": 0}
	}
	to := r.Timeout
	if to <= 0 {
		to = 30
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(to)*time.Second)
	defer cancel()
	c := exec.CommandContext(ctx, "/bin/sh", "-c", r.Cmd)
	c.Dir, c.Env = cwd, env
	var out, errb bytes.Buffer
	c.Stdout, c.Stderr = &out, &errb
	err := c.Run()
	rc := 0
	if ctx.Err() == context.DeadlineExceeded {
		rc = 124
	} else if ee, ok := err.(*exec.ExitError); ok {
		rc = ee.ExitCode()
	} else if err != nil {
		rc = 127
	}
	return map[string]any{"rc": rc, "stdout": out.String(), "stderr": errb.String(),
		"timed_out": ctx.Err() == context.DeadlineExceeded}
}

func writeJSON(f *os.File, v any) {
	b, _ := json.Marshal(v)
	f.Write(append(b, '\n'))
}

func logln(format string, a ...any) { fmt.Fprintf(os.Stderr, "[ps-agent] "+format+"\n", a...) }

func fatal(format string, a ...any) {
	logln(format, a...)
	time.Sleep(2 * time.Second) // let the console flush before PID1 dies (kernel panics)
	os.Exit(1)
}
