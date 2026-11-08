"""List / extract members of a remote zip via HTTP range requests (no full download).
Usage: remote_zip.py <url> list [pattern] | get <member> <out_path>"""
import sys, io, zipfile, urllib.request, fnmatch
class HTTPFile(io.RawIOBase):
    def __init__(s, url):
        s.url = url; s.pos = 0
        r = urllib.request.urlopen(urllib.request.Request(url, method="HEAD")); s.size = int(r.headers["Content-Length"]); s.url = r.url
    def seekable(s): return True
    def readable(s): return True
    def tell(s): return s.pos
    def seek(s, off, wh=0):
        s.pos = off if wh == 0 else s.pos + off if wh == 1 else s.size + off; return s.pos
    def read(s, n=-1):
        if n < 0: n = s.size - s.pos
        if n == 0 or s.pos >= s.size: return b""
        end = min(s.pos + n, s.size) - 1
        d = urllib.request.urlopen(urllib.request.Request(s.url, headers={"Range": f"bytes={s.pos}-{end}"})).read()
        s.pos += len(d); return d
    def readinto(s, b):
        d = s.read(len(b)); b[:len(d)] = d; return len(d)
f = io.BufferedReader(HTTPFile(sys.argv[1]), buffer_size=1 << 20); z = zipfile.ZipFile(f)
if sys.argv[2] == "list":
    pat = sys.argv[3] if len(sys.argv) > 3 else "*"
    names = [i for i in z.infolist() if fnmatch.fnmatch(i.filename, pat)]
    print(len(z.infolist()), "members;", len(names), "match")
    for i in names[:60]: print(i.file_size, i.filename)
else:
    open(sys.argv[4], "wb").write(z.read(sys.argv[3])); print("ok", sys.argv[4])
