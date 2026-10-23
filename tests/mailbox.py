"""Loopback SMTP capture used only by isolated integration tests."""
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
import socketserver,threading

class CaptureSMTP(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b'220 KriyoHR test mailbox\r\n')
        while True:
            line=self.rfile.readline(65536)
            if not line: return
            command=line.split(b' ',1)[0].strip().upper()
            if command in {b'EHLO',b'HELO'}: self.wfile.write(b'250 localhost\r\n')
            elif command in {b'MAIL',b'RCPT',b'RSET',b'NOOP'}: self.wfile.write(b'250 OK\r\n')
            elif command==b'DATA':
                self.wfile.write(b'354 End with dot\r\n')
                body=[]
                while True:
                    row=self.rfile.readline(65536)
                    if not row or row==b'.\r\n': break
                    body.append(row[1:] if row.startswith(b'..') else row)
                message=BytesParser(policy=policy.default).parsebytes(b''.join(body))
                self.server.messages.append({'to':str(message['To']),'subject':str(message['Subject']),'body':message.get_body(preferencelist=('plain',)).get_content()})
                self.wfile.write(b'250 Captured\r\n')
            elif command==b'QUIT': self.wfile.write(b'221 Bye\r\n');return
            else: self.wfile.write(b'502 Unsupported\r\n')

@contextmanager
def mailbox():
    with socketserver.ThreadingTCPServer(('127.0.0.1',0),CaptureSMTP) as server:
        server.daemon_threads=True;server.messages=[]
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try: yield server
        finally: server.shutdown();thread.join(timeout=5)
