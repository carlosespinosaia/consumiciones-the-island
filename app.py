#!/usr/bin/env python3
"""Tickets COPA: servidor local (127.0.0.1) + página con botón IMPRIMIR TICKET."""
import datetime, json, re, secrets, socket, time, subprocess, tempfile, os, threading, webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

PRINTER = "POS_P80"
PORT = 8765
STATS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats.json")
LOCK = threading.Lock()
STOCKF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stock.json")
HERE = os.path.dirname(os.path.abspath(__file__))
PINF = os.path.join(HERE, "pin.txt")
if not os.path.exists(PINF):
    open(PINF, "w").write("".join(secrets.choice("0123456789") for _ in range(6)))
PIN = open(PINF).read().strip()

def stats_load():
    try: return json.load(open(STATS))
    except Exception: return []

def stats_save(a):
    json.dump(a, open(STATS, "w"))
MAX_QTY = 50

HTML = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"index.html"),encoding="utf-8").read()

LOGO = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo_island.bin"), "rb").read()
DIAS = ["lunes","martes","miércoles","jueves","viernes","sábado","domingo"]

def ticket(qty, kind="copa"):
    now = datetime.datetime.now()
    fecha = f"{DIAS[now.weekday()].upper()} {now:%d/%m/%Y}\n{now:%H:%M}".encode("cp858")
    ESC, GS = b"\x1b", b"\x1d"
    if kind == "copa":
        body = (b"\n" + GS + b"!" + b"\x33" + "COPA\n".encode("cp858")
                + b"\n" + GS + b"!" + b"\x22" + "1 CONSUMICIÓN\n".encode("cp858"))
    else:
        body = (b"\n" + GS + b"!" + b"\x33" + "REFRESCO\n".encode("cp858")
                + b"\n" + GS + b"!" + b"\x33" + "O CERVEZA\n".encode("cp858")
                + b"\n" + GS + b"!" + b"\x22" + "1 CONSUMICIÓN\n".encode("cp858"))
    one = (ESC + b"@" + ESC + b"t" + bytes([19])      # init + codepage CP858 (acentos)
           + ESC + b"a" + b"\x01" + ESC + b"E" + b"\x01"  # centrado, negrita
           + b"\n" + LOGO + b"\n" + ESC + b"E" + b"\x00"
           + b"\n" + ESC + b"E" + b"\x01" + GS + b"!" + b"\x22" + fecha + b"\n" + GS + b"!" + b"\x00"
           + body
           + GS + b"!" + b"\x00" + ESC + b"E" + b"\x00"
           + ESC + b"d" + b"\x04"                      # avance 4 líneas
           + GS + b"V" + b"\x42" + b"\x00")            # avance y corte parcial
    return one * qty

class H(BaseHTTPRequestHandler):
    def _auth(self):
        local = self.client_address[0] == "127.0.0.1" and not self.headers.get("Cf-Connecting-Ip")
        if local or self.headers.get("X-PIN", "") == PIN: return True
        self._send(401, b'{"ok": false, "error": "PIN incorrecto"}'); return False
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="application/json"):
        self.send_response(code); self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers(); self.wfile.write(body)
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-PIN")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
    def do_GET(self):
        if self.path == "/":
            self._send(200, HTML.encode(), "text/html")
        elif self.path == "/stock":
            if self._auth():
                try: d = open(STOCKF).read()
                except Exception: d = "null"
                self._send(200, d.encode())
        elif self.path == "/stats":
            if self._auth(): self._send(200, json.dumps(stats_load()).encode())
        elif self.path == "/assets/logo-the-island-tarragona.png":
            self._send(200, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "logo-the-island-tarragona.png"), "rb").read(), "image/png")
        else:
            self._send(404, b"{}")
    def do_POST(self):
        if not self._auth(): return
        if self.path == "/stock":
            try:
                d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                with LOCK: open(STOCKF, "w").write(json.dumps(d))
                return self._send(200, b'{"ok": true}')
            except Exception as e:
                return self._send(500, json.dumps({"ok": False, "error": str(e)}).encode())
        if self.path == "/stats/reset":
            with LOCK: stats_save([])
            return self._send(200, b'{"ok": true}')
        if self.path != "/print": return self._send(404, b"{}")
        try:
            d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            qty = int(d.get("qty", 1)); kind = d.get("type", "copa")
            if kind not in ("copa", "refresco"): raise ValueError("tipo no válido")
            if not 1 <= qty <= MAX_QTY: raise ValueError("cantidad fuera de rango")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
                f.write(ticket(qty, kind)); path = f.name
            r = subprocess.run(["lp", "-d", PRINTER, "-o", "raw", path], capture_output=True, text=True)
            os.unlink(path)
            if r.returncode: raise RuntimeError(r.stderr.strip())
            with LOCK:
                a = stats_load(); a.append({"t": kind, "n": qty, "ts": int(time.time() * 1000)}); stats_save(a)
            self._send(200, json.dumps({"ok": True, "job": r.stdout.strip()}).encode())
        except Exception as e:
            self._send(500, json.dumps({"ok": False, "error": str(e)}).encode())

if __name__ == "__main__":
    srv = HTTPServer(("0.0.0.0", PORT), H)
    try:
        _s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); _s.connect(("8.8.8.8", 80)); ip = _s.getsockname()[0]
    except Exception:
        ip = "IP-DEL-MAC"
    print(f"Otros ordenadores de la misma red: http://{ip}:{PORT}/", flush=True)
    def tunnel():
        cf = os.path.join(HERE, "bin", "cloudflared")
        if not os.path.exists(cf): return
        pr = subprocess.Popen([cf, "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate"],
                              stderr=subprocess.PIPE, text=True)
        for line in pr.stderr:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m:
                url = m.group(0)
                print(f"Dirección pública (desde cualquier ordenador): {url}  PIN: {PIN}", flush=True)
                open(os.path.join(HERE, "tunnel.json"), "w").write(json.dumps({"url": url}))
                subprocess.run("git add tunnel.json && git commit -qm 'tunel' && git push -q origin main", shell=True, cwd=HERE,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
        for _ in pr.stderr: pass
    threading.Thread(target=tunnel, daemon=True).start()
    threading.Timer(0.8, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}/")).start()
    srv.serve_forever()
