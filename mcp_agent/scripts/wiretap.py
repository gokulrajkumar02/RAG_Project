"""
A transparent stdio wiretap for MCP. Put it in front of any stdio server in
mcp_servers.json and every JSON-RPC line the agent's own host exchanges with that
server is written, byte-for-byte, to a log — without the host or the server knowing.

    python wiretap.py LOGFILE -- <server command> [args...]

stdio framing in MCP is newline-delimited JSON, so one line == one message. The
tap forwards each line unchanged and appends {"n", "dir", "t", "raw"} to LOGFILE
(JSON lines). `dir` is "client->server" or "server->client". The server's stderr is
passed straight through.
"""

import json
import subprocess
import sys
import threading
import time


def pump(src, dst, direction, log, lock, counter, t0):
    for line in iter(src.readline, b""):
        with lock:
            counter[0] += 1
            n = counter[0]
            log.write(json.dumps({"n": n, "dir": direction, "t": round(time.time() - t0, 4),
                                  "raw": line.decode("utf-8").rstrip("\r\n")}) + "\n")
            log.flush()
        dst.write(line)
        dst.flush()
    try:
        dst.close()
    except OSError:
        pass


def main():
    if "--" not in sys.argv or len(sys.argv) < 4:
        sys.exit(__doc__)
    sep = sys.argv.index("--")
    log_path, cmd = sys.argv[1], sys.argv[sep + 1:]
    child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    lock, counter, t0 = threading.Lock(), [0], time.time()
    with open(log_path, "w", encoding="utf-8") as log:
        up = threading.Thread(target=pump, args=(sys.stdin.buffer, child.stdin, "client->server", log, lock, counter, t0))
        down = threading.Thread(target=pump, args=(child.stdout, sys.stdout.buffer, "server->client", log, lock, counter, t0))
        up.start()
        down.start()
        up.join()
        child.wait()
        down.join()


if __name__ == "__main__":
    main()
