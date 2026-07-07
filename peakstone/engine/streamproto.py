"""The runner→viewer live-stream protocol — ONE declaration (review R21).

Under --stream-output the runner interleaves human progress lines with protocol lines on stdout;
a protocol line is identified by its one-byte prefix. The TUI (dashboard) parses these back out
of the daemon's SSE log tail. Both sides import THIS module — the constants were hand-duplicated
before and only stayed in sync by luck.

Protocol lines:
  GEN_MARK + <delta>       one generation chunk; real newlines inside are escaped to GEN_NL
  GEN_PHASE + "thinking"|"answering"   the model switched generation channel
  GEN_ATTEMPT + <n>        a self-repair retry began (viewer draws a section boundary)
"""

GEN_MARK = "\x01"
GEN_NL = "\x02"
GEN_PHASE = "\x03"
GEN_ATTEMPT = "\x04"
